# AP2 v0.2 授权校验复现（commit e1ea56d）

- 仓库：google-agentic-commerce/AP2
- 版本：commit `e1ea56db72a6385bce3e5c1112b3a56ce60acb43`（v0.2，2026-04-29 后）
- 环境：Python 3.13 + pydantic 2.12.5 + jwcrypto 1.5.6 + sd-jwt 0.10.4
- 运行：
  ```bash
  PYTHONPATH=<AP2>/code/sdk/python python3 repro/repro_395.py
  PYTHONPATH=<AP2>/code/sdk/python python3 repro/repro_more.py
  ```

## F1 未知约束被解析成空约束（issue #395）

输入约束 `{"foo":"bar"}`，支付 $999,999.99：

```
parsed: ExecutionDate {'type': 'payment.execution_date'}
violations for $999,999.99: []
```

**结论**：未知约束没有拒绝，解析成空 `ExecutionDate`；`check_payment_constraints` 返回空列表，等于放行。规范要求未知约束必须失败。

## F2 负数金额通过 amount_range（issue #391）

约束 `amount_range.max=10000`（未给 min），支付 -5000 分：

```
violations: []
```

## F3 负数金额扣减预算（issue #391）

约束 `budget.max=100.0`，历史支出 5000 分，支付 -5000 分：

```
violations: []
```

**结论**：负金额不被拒绝，还会让累计支出变小。

## F4 预算浮点截断（issue #388）

约束 `budget.max=0.29`（元），支付 29 分：

```
violations: ['Cumulative spend 29 exceeds budget limit 28 (past spend: 0)']
```

**结论**：`int(0.29*100)=28`，恰好 29 分的支付被误拒（假阴性）。

## F5 单位不一致（issue #389）

- schema 的 `amount_range.max` 是整数最小单位（分）；文档示例写 `100.50`（元），该输入在 pydantic 解析阶段直接失败：
  ```
  parse rejected: ValidationError ... AmountRange.max Input should be a valid integer
  ```
- `budget.max` 是 number（元）；`250` 被当成 $250（25000 分），而 `amount_range.max=250` 被当成 250 分——同名不同义。

**结论**：同一个数字在不同约束下含义不同；文档、schema、SDK 三者不一致。

## act-guard 的对应

| AP2 行为 | act-guard |
|---|---|
| 未知约束 → 空约束放行 | 未知约束 → deny |
| 负数金额放行/扣预算 | 金额必须非负整数 → deny |
| 浮点预算截断 | 预算只收整数分 → 拒绝浮点 |
| 上下文缺失静默放行预算 | → unresolved（显式证据不足） |
| 空约束列表 | → deny（不能当放行） |

回归测试：`products/act-guard/tests/test_guard.py`（12 个用例）。
