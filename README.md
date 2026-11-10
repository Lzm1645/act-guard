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

CI（GitHub Actions）在每次 push 到 `master` 与每个 PR 上跑这 12 个单测，并用固定在复现 commit `e1ea56d` 的 AP2 SDK 跑 `repro/` 下的两个脚本。

## 0.1 边界与不支持场景

当前实现只做「约束是否被现有证据支持」的判定，不做协议栈的其余部分。以下明确不支持：

- **不验签、不验证凭证**：没有 JWT / SD-JWT / VC 解析，也没有信任锚、issuer 校验或密钥管理。因此本检查器无法证明 mandate 由谁签发、是否被篡改——它假设调用方传入的 mandate 与上下文已可信。
- **不是协议实现**：不解析完整 AP2 mandate，只读取 `constraints` 及少数字段；不依赖 AP2 SDK，也不做协议版本协商。
- **约束语义有限**：只覆盖 `KNOWN_PAYMENT_CONSTRAINTS` 里的 7 类，未知类型一律 `deny`。已有类型的实现也是最小语义，例如 `payment.agent_recurrence` 只比较 `total_uses` 计数、不看时间窗口；`payment.reference` 只比较 `transaction_id`。
- **不持久化状态**：预算累计 `total_amount_cents`、使用次数 `total_uses` 都由调用方提供，检查器不读写账本。上下文不可信时，结论同样不可信。
- **不换算金额**：金额只收整数最小单位（分），不做浮点、字符串或汇率换算；币种只按 3 字母字符串比较，不校验 ISO 4217 有效性。
- **时间只比时间戳**：带时区偏移的 ISO 8601 才精确；不带时区的字符串按运行环境本地时区解释。
- **不连支付网络**：不发起支付、不生成授权凭证、不撤销任何东西；输出只是可审计的检查结论，不构成支付建议。
- **路线图之外**：ACT/APASS 的 ISR/IAC、MCP 工具、`act-guard lint`、证据链哈希都尚未实现。

## 路线图

- [ ] 接入 ACT/APASS 的 ISR/IAC 结构（签发/校验/生命周期）
- [ ] `act-guard lint`：扫描 mandate/skill 配置，输出风险清单
- [ ] MCP 三工具：`check_intent` / `authorize_payment` / `record_receipt`
- [ ] 证据链哈希（每次决策可回溯到 mandate 与意图）
