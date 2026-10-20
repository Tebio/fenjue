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


## 勘察证据（2026-10-20 主 agent 实测，为血缘表定范围）

把注册表 11 个下游逐个对账「声明 vs 现实」，查出三类不一致——**这就是血缘表存在的理由**：

### ① 幽灵下游：「日度状态包」没有自动调用方
`engine/build_daily_state.py`（写 `data/daily_state/<date>.json`）在全库 grep 不到任何调用：
无 cron job、无 import、无 subprocess，唯一"调用方式"是 `docs/daily-state-schema.md:14` 里写的手动命令。
产物 `data/daily_state/2026-10-15.json` **停在 10-15**，之后再没跑过。
→ 它是个被遗忘的手动工具，不是每日下游。注册表把它列进 `blocks` 没错（手动跑时同样需要熔断），
但**不能据此认为它每天在产出**。

### ② 概念名 ≠ 作业：`日度状态包`、`回测族` 在 cron 里零引用
`晨报`、`盘前自检` 各命中 1 个 job；`回测族`、`日度状态包` 一个都没有。
→ 血缘表必须把「下游名」映射到**真实作业 id 或真实脚本入口**，不能只登记一个概念名。
一个查不到生产者的下游名，等于一条假的保护承诺。

### ③ 单一写入者核实（排除一处误判）
`docs/ops-state.json` 看似双写：`build_daily_state.py` 与 `dashboard_build.py` 都引用它。
实测 `build_daily_state.py:138/140/149/339` 全是 `jload` **只读**并做 freshness 检查，
真正写它的只有 `dashboard_build.py:1515`（整文件 write_text）。→ **无覆盖冲突**，先前的怀疑不成立。

### 由①得出的优先级修正
DATA-02 里「收编 `build_daily_state` 24 处 `freshness()`」的收益被高估了：它不在自动链路，
收编只让手动工具口径一致，不构成生产事故防线。**该子项降到 DATA-02 的最后一项**，
DATA-02 的主价值回到「存在性/日期一致性交叉校验」。

### 血缘表字段增补要求
`data/lineage.yaml` 每条下游必须写 `producer`（脚本路径）+ `trigger`（cron job id 或 `manual`），
两者任一缺失 → 加载即 raise。禁止只写概念名。
