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
3. ~~`claims_registry.yaml` 里有 `inputs` 类信息但未与数据健康打通。~~
   **2026-10-20 派单前自检实测证伪：`grep -c inputs data/claims_registry.yaml` = 0，一条都没有。**
   claims_registry 只有 `claims` 一个顶层键，每条主张都没有声明它依赖哪些数据集。
   → **`stale_claims()` 目前没有数据源，无法实现**。这是本 spec 最大的前提缺口（详见下方「自检修订 R1」）。

## 输入 / 输出
- 输入：`data/datasets_registry.yaml` + `data/claims_registry.yaml` + `data/data_health.json`
- 输出：`data/lineage.yaml`（声明式：dataset → artifacts → reports → claims）、
  `engine/lineage.py`（`impact(dataset)` / `stale_claims(ref_date)`）、
  `line_health.json` 每条线新增 `data_stale` 字段

## 接口契约
```python
def impact(dataset_key: str) -> dict:
    """{
      direct:  [下游作业名]      即注册表该数据集的 blocks，机器比对必须相等（一致性断言）
      artifacts: [{path, glob}]  下游作业声明的产物路径/glob 模板
      reports: [str]             人读报告（md）路径
      built_at: str              ISO 时间
    }
    注：原稿有 `rows` 字段但全文未定义语义，已删。`claims` 归 stale_claims，不混进 impact（一期无数据源，见 R1）。"""
def stale_claims(ref_date: str) -> list[dict]:
    """[{claim_id, blocking_dataset, reason}]；供 line_health/claims_audit 打标。
    **依赖 claims_registry 的 inputs 字段，该字段当前不存在（见 R1）→ 本函数二期实现。**"""
```

## 验收

### 一期（本次施工范围，全部可在本仓库内完成）
- 正例：`impact("big_kcache")` 返回的 `direct` == 注册表 `big_kcache.blocks`（实测值 `['深档名单','影子盘','周期仪','权威时间轴','X规则线']`，2026-10-20 核对一致）
- 反例：`lineage.yaml` 引用不存在的数据集/产物/下游名 → 加载即 raise（不许静默跳过）
- **机械断言（一期验收本体，比表本身重要）**：
  - 每个下游名必须绑定到**真实存在的脚本路径**（`Path(...).exists()`）
  - 每个产物 glob 必须**至少命中一个真实文件**（`Path.glob()` 非空）
  - 每条 `trigger` 若写 cron job id，必须能在 `hermes cron list` 里查到；若写 `manual`，必须能指向一份记载了手动命令的文档行号
- golden：新增血缘一致性 case（每个 dataset 的 `blocks` == lineage 的 `direct` 集合）

### 二期（**阻塞**，前置未满足，不许开工）
- 联动：伪造 `big_kcache` fatal → `stale_claims()` 非空 → `line_health` 打 `data_stale: true`。
  前置：先给 `claims_registry.yaml` 补 `inputs`（每条主张声明依赖的数据集）。
  68 条主张的 inputs 可半自动：扫 `law_pipeline.REGISTRY` 各 detector 函数体内的数据引用生成候选，人工确认后落盘。

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

### ② 概念名 ≠ 作业：多数下游名在 cron 里零引用
2026-10-20 复核更新（原稿写"`晨报`、`盘前自检` 各命中 1 个 job"，已过期）：
`晨报` 现在 **0 个 job**（该下游同日已清口，见 AGENTS #341/#342）；`回测族`、`日度状态包` 一个都没有；
`盘前自检` 有作业但它是 EXEMPT 恒放行。
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
`manual` 不是逃生舱：必须同时给出「记载该手动命令的文档路径:行号」，加载时校验该文件存在且该行确实含该脚本名，
否则 raise。否则任何幽灵下游写个 `manual` 就能通过，一致性断言形同虚设。

---

## 自检修订 R1（2026-10-20 主 agent 派单前自检，**这一节优先于正文**）

按 `docs/plan/PROTOCOL.md` 的派单前 5 项自检过了一遍，查出 4 处问题，正文已就地改，此节留痕：

1. **硬伤：`stale_claims()` 无数据源。** 原稿现状证据称"claims_registry 里有 `inputs` 类信息"，
   实测 `inputs` 出现 **0 次**，`claims_registry.yaml` 只有 `claims` 一个顶层键。
   → 二期验收（伪造 fatal → stale_claims 非空）**前提不存在，本次不许开工**；一期只做 `impact()`。
   → 若要做二期，必须先完成"给 68 条主张补 inputs"这个独立前置任务（半自动：扫 detector 函数体数据引用 → 人工确认）。
2. **契约不自洽**：`impact()` 返回值里有 `rows` 字段，全文未定义语义 → 删；`direct` 与 lineage.yaml 的 `artifacts` 混用 →
   明确 `direct` = 下游作业名集合（须等于注册表 blocks），`artifacts` = 产物路径/glob。
3. **验收缺机械断言**：原验收只有"列出来对得上"这种语义正确性，没有可自动判红的东西 → 补三条：
   脚本必须存在、glob 必须命中真实文件、trigger 必须能在 cron 里查到或指向记载 manual 命令的文档行。
   **这三条才是一期的防错价值本体，lineage.yaml 只是它们的数据。**
4. **`manual` 成为逃生舱**：原稿允许 trigger 写 `manual`，等于任何查不到生产者的下游写个 manual 就通过 → 补强校验（见上）。

**自检新增的通用纪律**（已写进 PROTOCOL）：spec 里每一条「某下游读某数据」「某脚本产某物」的断言，
都必须附**代码出处（文件名:行号）**。没有出处的先验再写。
本 spec 实测核对：`big_kcache.blocks = ['深档名单','影子盘','周期仪','权威时间轴','X规则线']` 与验收要求完全一致（无矛盾）；
读 big_kcache 的代码共 34 处，但只有注册的 5 个生产下游在保护范围（研究脚本按 DATA-07 #339 划出）。
