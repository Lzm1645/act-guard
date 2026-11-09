# act-guard

**支付授权体检：把「证据是否足以支持这笔支付」做成显式判定，而不是「没报错就放行」。**

## 说明

- 本仓库复现的 5 个问题都来自 AP2 官方仓库的公开 issue（#386/#388/#389/#391/#393/#395），不是未公开漏洞；
- 目的是回归用例与授权检查器参考实现，不是利用工具；
- 与 Google / AP2 项目无隶属关系。

## 为什么

AP2（Agent Payments Protocol）v0.2 的参考实现里有一类问题：约束校验「看起来通过」，实际上没有约束任何东西。我们在 commit `e1ea56d` 上复现了 5 个：

| # | 问题 | 现象 | 对应 issue |
|---|---|---|---|
| 1 | 未知约束被解析成空约束 | `{"foo":"bar"}` → 空 `ExecutionDate`，$999,999.99 支付返回 `[]` | #395 |
| 2 | 负数金额不拒绝 | `amount_range.max` 存在、`min` 缺失时，-5000 分通过 | #391 |
| 3 | 负数金额扣减预算 | 负金额让累计支出变小 | #391 |
| 4 | 预算浮点截断 | `max=0.29` → `int(0.29*100)=28`，29 分被误拒 | #388 |
| 5 | 单位不一致 | `amount_range.max` 按分、`budget.max` 按元；文档示例 `100.50` 无法表示 | #389 |

复现脚本与输出见 `repro/`。

## act-guard 的做法

- **三值决策**：`allow` / `deny` / `unresolved`。证据不足必须 `unresolved`，不能静默放行；
- **未知约束一律 deny**（不接受「解析成空约束」）；
- **金额只收整数最小单位**，拒绝负数、浮点、字符串；
- **预算整数运算**，上下文缺失 → `unresolved`；
- **证据链**：每次决策输出每条约束的 `pass/fail/unresolved` 与原因，可审计、可复现。

## 用法

```bash
python3 guard.py --self-test
python3 guard.py --mandate mandate.json --intent intent.json --context context.json
```

```json
// mandate.json
{"constraints": [{"type": "payment.amount_range", "max": 10000, "currency": "USD"}]}
// intent.json
{"amount_cents": 9900, "currency": "USD", "payee": "shop-a", "transaction_id": "tx1"}
```

输出：

```json
{"decision": "allow", "violations": [], "unresolved": [], "evidence": [...]}
```

## 测试

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

## 边界

- 这是「授权判定」的最小实现，不包含签名/凭证验证（那部分需要 AP2/ACT 的 VC 链路）；
- 不连接真实支付网络；不构成支付建议；
- 目标是可审计、可复现、可嵌入 CI 的检查器，而不是完整协议栈。

## 路线图

- [ ] 接入 ACT/APASS 的 ISR/IAC 结构（签发/校验/生命周期）
- [ ] `act-guard lint`：扫描 mandate/skill 配置，输出风险清单
- [ ] MCP 三工具：`check_intent` / `authorize_payment` / `record_receipt`
- [ ] 证据链哈希（每次决策可回溯到 mandate 与意图）
