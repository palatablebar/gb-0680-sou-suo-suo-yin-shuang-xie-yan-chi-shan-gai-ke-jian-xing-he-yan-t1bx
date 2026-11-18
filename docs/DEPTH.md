# 深度登记 搜索索引双写延迟与删改可见性核验

规模：中型。使用者：搜索数据同步值班工程师。核心规则：按源版本重建目标可见状态，删除墓碑拦截迟到旧写入；延迟与缺失分开定责。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 双端采信 | 查看并运行双端采信 | `/api/streams` | `app/modules/m1_streams/rules.py` | `tests/test_m1.py` |
| M2 字段契约 | 查看并运行字段契约 | `/api/schema` | `app/modules/m2_schema/rules.py` | `tests/test_m2.py` |
| M3 版本裁决 | 查看并运行版本裁决 | `/api/versions` | `app/modules/m3_versions/rules.py` | `tests/test_m3.py` |
| M4 可见性重建 | 查看并运行可见性重建 | `/api/visibility` | `app/modules/m4_visibility/rules.py` | `tests/test_m4.py` |
| M5 延迟闸门 | 查看并运行延迟闸门 | `/api/latency` | `app/modules/m5_latency/rules.py` | `tests/test_m5.py` |
| M6 双写对账 | 查看并运行双写对账 | `/api/parity` | `app/modules/m6_parity/rules.py` | `tests/test_m6.py` |
| M7 回补归档 | 查看并运行回补归档 | `/api/backfills` | `app/modules/m7_backfills/rules.py` | `tests/test_m7.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-01 | 旧编码 | 默认解码失败 | 回退GB18030 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_legacy_encoding_real_sample` |
| TRAP-02 | BOM | 首列名多字符 | utf-8-sig | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_bom_real_sample` |
| TRAP-03 | 带引号换行 | 拆成两条 | csv逻辑行 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_quoted_newline_is_one_record` |
| TRAP-05 | 列数不匹配 | 静默错列 | 隔离原行 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_bad_columns_real_sample` |
| TRAP-08 | 前导零ID | 编码变形 | 全程字符串 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_identifier_preserved_real_sample` |
| TRAP-14 | 重复键冲突 | 后写覆盖 | 保留首条并隔离冲突行 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_duplicate_conflict_real_sample` |
| TRAP-18 | 空态三态 | 一律成功 | 分别错误码 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_three_empty_states` |
| TRAP-26 | 旧版本提交 | 覆盖新结果 | 版本条件更新 | `app/store.py` | `tests/test_e2e.py::test_stale_review_409` |
| TRAP-06 | 全角版本 | 解析失败 | Decimal归一 | `app/values.py` | `tests/test_m2.py::test_fullwidth_version` |
| TRAP-07 | 缺版本 | 当零处理 | 空值隔离 | `app/values.py` | `tests/test_m2.py::test_real_sentinel_isolated` |
| TRAP-09 | 超大版本 | JSON精度损失 | 文本序列化 | `app/values.py` | `tests/test_m2.py::test_large_version_precise` |
| TRAP-13 | 删除后迟到旧写 | 文档复活 | 最大版本墓碑 | `app/modules/m3_versions/rules.py` | `tests/test_m3.py::test_tombstone_beats_late_old_write` |
| TRAP-23 | 延迟阈值边界 | 多判延迟 | 等于阈值通过 | `app/modules/m5_latency/rules.py` | `tests/test_m5.py::test_threshold_equal_pass` |
| TRAP-27 | 预算规则切换 | 新旧批次混用同一日报口径 | 预算登记版本化，批次冻结实际版本，日报按预算分栏，跨预算只做只读对照 | `app/budgets.py`、`app/store.py` | `tests/test_budget.py::test_daily_totals_split_by_budget_never_mixed` |
| TRAP-28 | 重跑改写封存 | 同输入换预算产生新批次或覆盖结论 | 预算字段不参与批次身份，`INSERT OR IGNORE` 复用批次 | `app/manifest.py`、`app/store.py` | `tests/test_budget.py::test_rerun_does_not_change_sealed_conclusion_after_review` |

## 预算规则更新裁决

2026-11-18 午间将延迟预算由 120 秒收紧到 90 秒。裁决为 `KEEP_SEALED`：

- 作废批次集合为空，追溯重算批次集合为空。
- 上午已复核批次保留 120 秒口径与全部封存结论；待复核旧批次同样不就地改写。
- 午间及以后新批次默认 90 秒，并在清单与导出中记录实际预算版本。
- 历史批次在 `/daily` 与 `/api/runs/<id>` 上展示只读影子评估：同一输入摘要下的通过结论与差异数变化一律归因预算版本，不归因文档。
- 重跑同一输入复用原批次：不新增批次，不改变已封存结论与复核状态，日报 `report_sha256` 稳定。

## 对账规则

输入原始逻辑行=最终采纳来源行+隔离来源行+重复行+空白行+分段表头。派生记录用_sources保存完整来源，因此分组不丢行。业务预期合计与上游申报合计之差等于逐行差异之和。结果按输入摘要、规则版本及非预算参数产生唯一批次，事务写入；同源重跑只复用已有批次。预算版本不参与批次身份，日报合计按实际预算版本分栏，不跨口径相加。

## 已知不覆盖

4MB以上文件需预先按业务键分批；不模拟生产支付与外部回调。人工复核只变更批次状态，不改写原始记录。
