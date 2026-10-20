# RES-11 · 「高位剧震」detector 接入 REGISTRY（让 AVOID_CLIMAX_QUAKE 进自动审计）

## 目标
把 RES-10 已注册的 `AVOID_CLIMAX_QUAKE` 从"只登记不复跑"升级为**自动复验主张**：
`claims_audit` 每轮能算出它的滚动边际，跌破 kill 线自动进 DECAYING/DEAD 状态机。

## 非目标
- 不改事件定义（口径必须与 `engine/r4_yearbreak.py::is_quake` 逐行等价）
- 不改 claims_audit 的状态机与 kill 逻辑
- 不做盘中实时

## 现状证据
1. `claims_audit.main()` 里 `if det_key not in REGISTRY: → "external 背书，本轮只登记不复跑"`；
2. `AVOID_CLIMAX_QUAKE.detector = 高位剧震`，目前不在 `law_pipeline.REGISTRY` → 走 external 分支（2026-10-20 实测确认）；
3. 事件定义只在 `r4_yearbreak.is_quake()` 里，且它依赖预加载的 `stocks` 结构，与 REGISTRY 的 detector 签名不同。

## 输入 / 输出
- 输入：`engine/law_pipeline.py` 的 REGISTRY 契约、`engine/r4_yearbreak.py::is_quake/collect`、`engine/claims_audit.py::marginals_ex`
- 输出：REGISTRY 新增 `高位剧震` detector（薄适配层，内部调用 `is_quake/collect` 的同一逻辑）；
  golden 新增 detector 一致性 case

## 验收
- `claims_audit` 复跑 `AVOID_CLIMAX_QUAKE`，输出的**全量边际必须与 RES-10 报告一致**（T+20 ≈ -2.71pp，误差只在样本期差异上解释）
- 适配层与原 `is_quake` 在同一 200 票子集上事件集合**完全相同**（断言集合相等，不是"数目相近"）
- `python -m tests.golden.record law_pipeline_three` 若因新增 detector 产生漂移 → 逐案记录进 `docs/golden-master-*.md`，不许静默刷新
- 不改动任何既有 detector 的输出

## 回滚
REGISTRY 删掉该键即回到 external 分支（claims 记录里的 note 已写明此状态），无数据副作用。

## 依赖 / 风险
依赖 RES-10。风险：REGISTRY 的 detector 契约含横截面/位置匹配的内置约定，适配层若自己造对照会与 claims_audit 的 control 机制打架——
必须让 `control: position_matched` 由 claims_audit 统一施加，detector 只负责"哪些事件"。

## 工期
0.5 人日
