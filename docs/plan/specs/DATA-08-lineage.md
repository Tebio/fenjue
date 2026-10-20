# DATA-08 · 血缘表 + DATA_STALE 联动（影响半径自动化）

## 目标
建一张「数据集 → 中间产物 → 报告/主张」的血缘表，使两件事变成一条命令：
①某数据集断供时，哪些产物与结论受影响（影响半径）；②数据不可信时，相关注册线/主张自动标 `DATA_STALE`
（`line_health` 现在会拿旧数据算什么滚动 edge，把「数据缺失」误判成「策略衰减」）。

## 非目标
- 不追踪到字段级（文件/产物级就够，字段级是过度工程）
- 不做可视化血缘图（先要机器可读 + 一条查询命令）
- 不改 `claims_audit` 的投票权

## 现状证据
1. 2026-10-20 补数事故中，「这次断供影响哪些胜率数据」是人工翻文件逐个查的，无工具；
2. `line_health.py` 只读 `claims_state` 与影子单，对输入数据的新鲜度零感知；
3. `claims_registry.yaml` 里有 `inputs` 类信息但未与数据健康打通。

## 输入 / 输出
- 输入：`data/datasets_registry.yaml` + `data/claims_registry.yaml` + `data/data_health.json`
- 输出：`data/lineage.yaml`（声明式：dataset → artifacts → reports → claims）、
  `engine/lineage.py`（`impact(dataset)` / `stale_claims(ref_date)`）、
  `line_health.json` 每条线新增 `data_stale` 字段

## 接口契约
```python
def impact(dataset_key: str) -> dict:
    """{direct: [artifacts], reports: [...], claims: [...], rows: [...], built_at: ...}"""
def stale_claims(ref_date: str) -> list[dict]:
    """[{claim_id, blocking_dataset, reason}]；供 line_health/claims_audit 打标。"""
```

## 验收
- 正例：`impact("big_kcache")` 必须列出深档名单/影子盘/周期仪/权威时间轴/X规则线，且与 `blocks` 字段一致（一致性断言）
- 反例：`lineage.yaml` 里引用不存在的数据集/产物 → 加载即 raise（不许静默跳过）
- 联动：伪造 `big_kcache` fatal → `stale_claims()` 非空，`line_health` 对这些线打 `data_stale: true` 并在报告中单列
- golden：新增血缘一致性 case（每个 dataset 的 blocks == lineage 的 direct 集合）

## 回滚
纯新增文件；`line_health` 侧只在字段缺失时保持沉默（向后兼容）。

## 依赖 / 风险
依赖 DATA-06。风险：血缘表会腐——用 golden 一致性断言 + `mandatory` 必注册集双向校验（新增产物必须登记）。

## 工期
1.5 人日
