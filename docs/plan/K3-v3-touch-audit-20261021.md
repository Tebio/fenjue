# K3 审计单：V3 冻结线的生产触面审计（2026-10-21）

## 背景（图谱发现，全部实证）

架构图谱（.ua/knowledge-graph.json）发现「V3 评分引擎（冻结线）」并非孤立——生产与呈现面在 import 它：

1. `scheduler/cron.py` → `engine/event_registry.py`、`engine/feedback.py`、`engine/macro_industry.py`
2. `api/app.py` → `engine/regime/market.py`

而 AGENTS.md R4（#100 条目区域）早记录 V3 内部未修缺陷：
- MacroOverlay→MarketRegime 物理上没接线（crisis 档永远走不到，ExecutionPlanner 的 crisis 空仓是死代码）
- ScoringEngine._confidence 哨兵值不自洽（无数据返回 6 / industry 查不到返回 0 都被误判为真实数据）
- MoneyFlowEngine 的 institution 恒为占位 5 → 资金健康度大多数 = unknown
- macro_industry.map 丢弃事件 direction 覆盖（地缘缓和类事件权重方向会算反）
- industry 多主题只取 YAML 顺序第一个
- margin.py 一段逐日累乘死代码
- event_registry 的 todays_registry 硬编码 2026-07-08 快照、每次调用重置 created 时间戳 → 衰减形同虚设
- market_data/feedback/event_registry 三模块曾被记为「全仓库零引用」——但图谱显示 cron.py 在 import 它们，需要核实现状

## 任务（代码级审计，不动一行代码）

逐调用点确认「调用什么 → 是否触及已知缺陷 → 对每日生产的实际影响」：

1. **读代码**：`scheduler/cron.py`、`api/app.py` 的全部 import 与调用点；被调的 V3 模块对应函数体
2. **对每个调用点产出**：
   - 调用的是哪个函数/类
   - 该函数是否触及上列已知缺陷（触及哪条、怎么触及）
   - 该缺陷对**每日生产输出**的实际影响（信号错？衰减失效？只是死代码无害？）
   - 严重度评级：生产风险（影响每日输出正确性）/ 隐性失真（输出错了但没人看）/ 无害（死代码路径）
3. **核实「零引用」断言**：R4 说 market_data/feedback/event_registry 三模块零引用——用 grep 实证现状（若已非零引用，说明 R4 后有接线，要查清是谁接的、何时接的、是否过了解冻流程）

## 纪律（先读再动手）

- 先读 `/opt/data/skills/fenjue-dev/SKILL.md`，按其「第一步」顺序读权威文档（START-HERE → CONSTRAINTS → 需要时 DECISIONS/R4 条目）
- **本单是只读审计**：不改任何代码、不改任何文档。产出只有一份报告
- 每条结论必须有代码行号级证据（文件:行号），禁止「看起来是」
- 图谱只作线索，一切以源码为准（函数级图谱抽取偏稀，别全信函数级边）

## 产出

`research/V3-prod-touch-audit-20261021.md`，结构：
- §1 调用点清单（上述 4 条边逐一拆解）
- §2 缺陷触及矩阵（调用点 × 已知缺陷 → 触及/未触及 + 证据）
- §3 「零引用」断言核实结果
- §4 生产影响评估与处置建议（继续用 / 摘依赖 / 解冻修缺陷——每条给倾向+作废条件）

## 验收

- 报告落盘且 §2 矩阵每格都有行号证据
- 我复核时会抽查 2 个调用点重读源码，对不上即整单返工
