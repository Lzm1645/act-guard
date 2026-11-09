#!/usr/bin/env python3
"""act-guard：支付授权体检的最小实现。

目标不是复刻 AP2，而是把「证据是否足以支持这笔支付」做成显式阶段：
- 三值决策：allow / deny / unresolved（证据不足必须 unresolved，不能静默 allow）；
- 未知约束一律 deny（不接受「解析成空约束」）；
- 金额只接受整数最小单位（分），拒绝负数与浮点；
- 预算用整数运算，上下文缺失时 unresolved；
- 每次决策输出证据链，便于审计与复现。

用法：
    python3 guard.py --mandate mandate.json --intent intent.json
    python3 guard.py --self-test
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

ALLOW, DENY, UNRESOLVED = "allow", "deny", "unresolved"

KNOWN_PAYMENT_CONSTRAINTS = {
    "payment.amount_range",
    "payment.budget",
    "payment.allowed_payees",
    "payment.allowed_payment_instruments",
    "payment.execution_date",
    "payment.agent_recurrence",
    "payment.reference",
}


def _int_amount(value: Any, field_name: str) -> tuple[int | None, str | None]:
    """金额必须是整数最小单位；浮点/字符串/负数都拒绝。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return None, f"{field_name} 必须是整数最小单位（分），收到 {type(value).__name__}={value!r}"
    if value < 0:
        return None, f"{field_name} 不能为负数（收到 {value}）"
    return value, None


def _ts(value: Any, field_name: str) -> tuple[float | None, str | None]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value), None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp(), None
        except ValueError:
            return None, f"{field_name} 不是合法时间：{value!r}"
    return None, f"{field_name} 缺失或类型错误"


@dataclass
class Evidence:
    check: str
    status: str  # pass | fail | unresolved
    detail: str


@dataclass
class Decision:
    decision: str
    violations: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "violations": self.violations,
            "unresolved": self.unresolved,
            "evidence": [e.__dict__ for e in self.evidence],
        }


def _add(decision: Decision, check: str, status: str, detail: str) -> None:
    decision.evidence.append(Evidence(check, status, detail))
    if status == "fail":
        decision.violations.append(f"{check}: {detail}")
    elif status == "unresolved":
        decision.unresolved.append(f"{check}: {detail}")


def check_intent(mandate: dict[str, Any], intent: dict[str, Any], context: dict[str, Any] | None = None) -> Decision:
    """核心：先做证据资格判定，再给出三值决策。"""
    decision = Decision(decision=ALLOW)
    ctx = context or {}

    # 1) 意图本身的合法性
    amount, err = _int_amount(intent.get("amount_cents"), "intent.amount_cents")
    if err:
        _add(decision, "intent.amount", "fail", err)
    currency = intent.get("currency")
    if not isinstance(currency, str) or len(currency) != 3:
        _add(decision, "intent.currency", "fail", f"币种非法：{currency!r}")
    if not intent.get("payee"):
        _add(decision, "intent.payee", "fail", "缺少收款方")

    constraints = mandate.get("constraints")
    if not isinstance(constraints, list) or not constraints:
        _add(decision, "mandate.constraints", "fail", "空约束不能视为放行")
        constraints = []

    for index, constraint in enumerate(constraints):
        if not isinstance(constraint, dict):
            _add(decision, f"constraint[{index}]", "fail", "约束不是对象")
            continue
        ctype = constraint.get("type")
        if ctype not in KNOWN_PAYMENT_CONSTRAINTS:
            # 关键：未知约束 -> deny，而不是解析成空约束
            _add(decision, f"constraint[{index}]", "fail", f"未知约束类型 {ctype!r}，按规范必须拒绝")
            continue

        if ctype == "payment.amount_range":
            if err:
                continue  # 金额本身已失败
            cmin, e1 = (None, None)
            if "min" in constraint:
                cmin, e1 = _int_amount(constraint["min"], "constraint.min")
                if e1:
                    _add(decision, f"constraint[{index}].min", "fail", e1)
            cmax, e2 = (None, None)
            if "max" in constraint:
                cmax, e2 = _int_amount(constraint["max"], "constraint.max")
                if e2:
                    _add(decision, f"constraint[{index}].max", "fail", e2)
            if constraint.get("currency") and constraint["currency"] != currency:
                _add(decision, f"constraint[{index}].currency", "fail",
                     f"币种不匹配：约束 {constraint['currency']}，意图 {currency}")
            elif not e1 and not e2 and amount is not None:
                if cmin is not None and amount < cmin:
                    _add(decision, f"constraint[{index}]", "fail", f"金额 {amount} < 下限 {cmin}")
                elif cmax is not None and amount > cmax:
                    _add(decision, f"constraint[{index}]", "fail", f"金额 {amount} > 上限 {cmax}")
                else:
                    _add(decision, f"constraint[{index}]", "pass", f"金额 {amount} 在 [{cmin},{cmax}] 内")

        elif ctype == "payment.budget":
            cmax, e2 = _int_amount(constraint.get("max"), "constraint.max")
            if e2:
                _add(decision, f"constraint[{index}].max", "fail", e2)
                continue
            if constraint.get("currency") and constraint["currency"] != currency:
                _add(decision, f"constraint[{index}].currency", "fail",
                     f"币种不匹配：约束 {constraint['currency']}，意图 {currency}")
                continue
            if "total_amount_cents" not in ctx:
                _add(decision, f"constraint[{index}]", "unresolved", "缺少累计已花上下文（total_amount_cents），无法判定预算")
                continue
            past, e3 = _int_amount(ctx["total_amount_cents"], "context.total_amount_cents")
            if e3:
                _add(decision, f"constraint[{index}]", "unresolved", e3)
                continue
            total = past + (amount or 0)
            if total > cmax:
                _add(decision, f"constraint[{index}]", "fail", f"累计 {total} 超过预算 {cmax}")
            else:
                _add(decision, f"constraint[{index}]", "pass", f"累计 {total} <= 预算 {cmax}")

        elif ctype == "payment.allowed_payees":
            allowed = constraint.get("allowed") or []
            ids = {a.get("id") for a in allowed if isinstance(a, dict) and a.get("id")}
            if intent.get("payee") in ids:
                _add(decision, f"constraint[{index}]", "pass", f"收款方 {intent['payee']} 在白名单")
            else:
                _add(decision, f"constraint[{index}]", "fail", f"收款方 {intent.get('payee')!r} 不在白名单")

        elif ctype == "payment.execution_date":
            intent_ts, e4 = _ts(intent.get("execution_date"), "intent.execution_date")
            if e4:
                _add(decision, f"constraint[{index}]", "unresolved", e4)
                continue
            nb, e5 = (None, None)
            if "not_before" in constraint:
                nb, e5 = _ts(constraint["not_before"], "constraint.not_before")
                if e5:
                    _add(decision, f"constraint[{index}].not_before", "fail", e5)
            na, e6 = (None, None)
            if "not_after" in constraint:
                na, e6 = _ts(constraint["not_after"], "constraint.not_after")
                if e6:
                    _add(decision, f"constraint[{index}].not_after", "fail", e6)
            if not e5 and not e6:
                if nb is not None and intent_ts < nb:
                    _add(decision, f"constraint[{index}]", "fail", "执行时间早于窗口")
                elif na is not None and intent_ts > na:
                    _add(decision, f"constraint[{index}]", "fail", "执行时间晚于窗口")
                else:
                    _add(decision, f"constraint[{index}]", "pass", "执行时间在窗口内")

        elif ctype == "payment.reference":
            expected = constraint.get("conditional_transaction_id")
            actual = intent.get("transaction_id")
            if not actual:
                _add(decision, f"constraint[{index}]", "unresolved", "意图缺少 transaction_id，无法校验引用")
            elif actual != expected:
                _add(decision, f"constraint[{index}]", "fail", "transaction_id 与引用不匹配")
            else:
                _add(decision, f"constraint[{index}]", "pass", "引用匹配")

        elif ctype == "payment.agent_recurrence":
            limit = constraint.get("max_occurrences")
            used = ctx.get("total_uses")
            if limit is None:
                _add(decision, f"constraint[{index}]", "pass", "未设置次数上限")
            elif used is None:
                _add(decision, f"constraint[{index}]", "unresolved", "缺少累计使用次数上下文（total_uses）")
            elif used >= limit:
                _add(decision, f"constraint[{index}]", "fail", f"已使用 {used} 次，达到上限 {limit}")
            else:
                _add(decision, f"constraint[{index}]", "pass", f"已使用 {used} 次 < 上限 {limit}")

        elif ctype == "payment.allowed_payment_instruments":
            allowed = constraint.get("allowed") or []
            ids = {a.get("id") for a in allowed if isinstance(a, dict) and a.get("id")}
            if not intent.get("payment_instrument_id"):
                _add(decision, f"constraint[{index}]", "unresolved", "意图缺少支付工具 id")
            elif intent["payment_instrument_id"] in ids:
                _add(decision, f"constraint[{index}]", "pass", "支付工具在白名单")
            else:
                _add(decision, f"constraint[{index}]", "fail", "支付工具不在白名单")

    # 2) 汇总：fail > unresolved > allow
    if decision.violations:
        decision.decision = DENY
    elif decision.unresolved:
        decision.decision = UNRESOLVED
    else:
        decision.decision = ALLOW
    return decision


SELF_TESTS: list[dict[str, Any]] = [
    {
        "name": "未知约束（AP2 #395）",
        "mandate": {"constraints": [{"foo": "bar"}]},
        "intent": {"amount_cents": 9_999_999, "currency": "USD", "payee": "any"},
        "expect": DENY,
    },
    {
        "name": "负数金额 amount_range（AP2 #391）",
        "mandate": {"constraints": [{"type": "payment.amount_range", "max": 10_000, "currency": "USD"}]},
        "intent": {"amount_cents": -5_000, "currency": "USD", "payee": "any"},
        "expect": DENY,
    },
    {
        "name": "预算浮点截断（AP2 #388）",
        "mandate": {"constraints": [{"type": "payment.budget", "max": 29, "currency": "USD"}]},
        "intent": {"amount_cents": 29, "currency": "USD", "payee": "any"},
        "context": {"total_amount_cents": 0},
        "expect": ALLOW,
    },
    {
        "name": "预算上下文缺失 → unresolved",
        "mandate": {"constraints": [{"type": "payment.budget", "max": 10_000, "currency": "USD"}]},
        "intent": {"amount_cents": 100, "currency": "USD", "payee": "any"},
        "expect": UNRESOLVED,
    },
    {
        "name": "金额上限（正常拒绝）",
        "mandate": {"constraints": [{"type": "payment.amount_range", "max": 100, "currency": "USD"}]},
        "intent": {"amount_cents": 101, "currency": "USD", "payee": "any"},
        "expect": DENY,
    },
    {
        "name": "空约束（不能当放行）",
        "mandate": {"constraints": []},
        "intent": {"amount_cents": 100, "currency": "USD", "payee": "any"},
        "expect": DENY,
    },
]


def self_test() -> int:
    failed = 0
    for case in SELF_TESTS:
        result = check_intent(case["mandate"], case["intent"], case.get("context"))
        ok = result.decision == case["expect"]
        failed += 0 if ok else 1
        print(f"[{'PASS' if ok else 'FAIL'}] {case['name']}: {result.decision} (expect {case['expect']})")
        for line in result.violations + result.unresolved:
            print(f"    - {line}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mandate", type=str, help="open mandate JSON 文件")
    parser.add_argument("--intent", type=str, help="payment intent JSON 文件")
    parser.add_argument("--context", type=str, help="累计上下文 JSON（total_amount_cents/total_uses）")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not args.mandate or not args.intent:
        parser.print_help()
        return 2
    mandate = json.loads(open(args.mandate, encoding="utf-8").read())
    intent = json.loads(open(args.intent, encoding="utf-8").read())
    context = json.loads(open(args.context, encoding="utf-8").read()) if args.context else {}
    result = check_intent(mandate, intent, context)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=1))
    return 0 if result.decision == ALLOW else 1


if __name__ == "__main__":
    raise SystemExit(main())
