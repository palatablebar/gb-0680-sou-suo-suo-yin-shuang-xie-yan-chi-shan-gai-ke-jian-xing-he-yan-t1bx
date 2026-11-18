# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。`/api/runs`使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。`/api/upload`接收multipart文件file。`/api/runs/<id>/archive`只导出一份带清单与证据的CSV。

## 预算口径

预算不是普通参数，按版本登记在 `app/budgets.py`，当前默认 `budget-2026.11.18-noon`（90s），历史 `budget-2026.11.18-am`（120s）。

- `parameters.budget_version` 指定预算版本；也可用 `parameters.max_delay_seconds` 反查已登记版本。
- 两者同时提供且不一致返回 `422 BUDGET_MISMATCH`；未登记版本返回 `422 BAD_BUDGET`。
- 预算字段不参与批次身份：同一输入换预算重跑复用原批次，不新增批次，不覆盖封存结论。
- 每个批次在 `manifest.budget` 与 `executed_budget` 中保留实际预算版本与秒数。

## 批次视图

`GET /api/runs/<id>` 返回封存结果，并附带 `evaluations`：按预算版本分列的只读评估，`sealed` 标记批次实际执行的口径，其余为影子对照。`comparison` 逐文档列出新旧预算下的门禁、对账状态与差异数，`changed` 表示口径变化。

`GET /api/runs` 返回历史批次，含各批 `budget_version` 与 `budget_seconds`。

## 唯一日报

`GET /api/daily` 是唯一日报：

- `batches[].sealed` 是每批次唯一封存结论，来自批次实际预算版本。
- `totals_by_budget` 按预算版本分栏合计，不跨口径相加。
- `counts.divergence_attribution` 在存在跨预算变化时固定为 `BUDGET`。
- `report_sha256` 只由批次封存内容派生：同库重跑得到同一日报。
- `ruling` 引用预算切换裁决（`KEEP_SEALED`），其中 `revoked_batches` 与 `recomputed_batches` 为空。

`GET /api/budget-rules` 返回已登记预算、当前预算与同一份裁决。
