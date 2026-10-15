# 晨报 2026-10-15（过夜五卡汇总）

隔夜五张卡全部完成落账，AGENTS.md 新增 #270/#271/#272/#273/#276 五条编号条目，git 已提交推送 GitHub（master）。逐块如下：

## 1. 记账消化（卡 t_89f4c4bd → AGENTS #271）
- verify.sh 与 plan_lint 实跑全绿：plan_lint exit 0（46 条目/8 spec/门 G0），py_compile 143 文件 0 失败，pytest/golden 如实 SKIP（tests/ 空，非假通过）；plan_lint 三条正反例实测能正确抓悬空引用和缺 spec。
- cron 体检：64 个 job，58 个在跑全 ok（X规则线 5 日"静默"查明是设计静默非故障）；未推送提交=0。
- AGENTS.md 体积治理：103.9KB 超 100KB 阈值，241–260 研究结论段（34,695B）逐字搬进 docs/agents-archive-2026q3.md，主干降到 74.1KB，归档可全文检索。
- backlog 修正：PLAT-00/SEC-01 改 blocked 挂 DECISIONS OPEN 裁决。

## 2. 双响炮形态（卡 t_fd907c22 → AGENTS #273）
- 查重零命中后新测：全宇宙 3335 只 8 年，20 个变体 20/20 REJECT。
- 主变体 A 845 例 T+5 -3.35%/33.7%，位置匹配边际 -5.51pp（同票同 MA60 侧随机日反而更好=形态本身扣分、替先手接盘）；收紧形态更差（涨停版 -3.92%、不破收盘版 -4.82%）。
- 唯一正号的低位子集（T+5 +1.58~+4.85%）逐条对闸全挂，且 edge 归低位轴（深档低位 v2 已注册），不立新案。
- 产物：engine/dual_cannon_study.py、data/dual_cannon_study_20261015.json、docs/dual-cannon-20261015.md。

## 3. 下跌中继突袭（卡 t_f32e9abf → AGENTS #272）
- 下跌趋势中突然涨停/大涨≥7%：裸均值壮观（大涨7 n=6353，T+20 74.4%/+11.14%）但三闸终审 REJECT。
- 日历时间组合（677 事件日真 t_NW）：T+5 -1.02%（t_NW -3.2）、T+20 -2.36%（t_NW -2.6）显著为负；正超额全部来自 62 个抱团日（K≥15 覆盖 73% 事件）；G7 容量 K1 年化 -13.1%/回撤 -72% 挂闸。
- 判词：不可参与——是市场级反弹日的跟随现象，持仓票下跌途中突涨≥7% 不构成加仓理由。已钉入 CONSTRAINTS.md C1 禁复活清单。
- 产物：engine/downtrend_raid.py + raid2–8 七个 stage 脚本、data/downtrend_raid_*.json。

## 4. 协同过滤「相似样本抄作业」引擎（卡 t_1dce09ff → AGENTS #276）
- 514 万股票日 × 15 维 PIT 状态向量，GridCF 分桶（全量 25 秒）+ KNN 双引擎互证。
- 事件级判别力成立：T+5 十分档 lift 0.74pp，撤掉 regime 轴后 1.31pp 且 9/9 全单调；洗牌对照≈0（真信号 1/25）；分年验尸四年全正；top 档 83% 是注册线之外的新领土。
- 但日历时间 t_NW 1.5~2.2 过不了 Harvey 3 → 不注册为交易线，入 backlog RES-07 作信号排序层候选（gate G3，不得作独立触发）。
- 方法级发现：regime 是闸门不是相似度轴（撤掉后 lift 不降反升）。
- 产物：engine/similarity_engine.py、docs/similarity-engine-20261015.md、data/similarity_engine_20261015.json。

## 5. 回测框架对标 + 数据问题终审（卡 t_02c4b3b5 → AGENTS #270）
- 核心判词：比错了对象——Backtrader/VectorBT 是「执行引擎」，自家 law_pipeline 是「证伪引擎」，不是同类件。
- 自家独有：G7 容量模拟、HAC t 值 + Harvey 门 + DSR 多重检验、A 股语义（T+1/一字/ST）；两家皆维护停滞（Backtrader 冻结于 2023-04，vectorbt 进入维护模式）。
- 数据问题逐项判决：退市股幸存者偏差未量化（当前最实质数据风险，方向=高估）；big_kcache_unadj 停更在 2026-09 且缺 500 只（314 只仍活跃）；静态双段≠真样本外；bootstrap/walk_forward 零命中。
- 差距清单 A1–A10 按影响钱排序；不补清单写死（迁框架/Barra/执行算法/ML 挖因子等）。
- 产物：docs/backtest-framework-review.md。

## 需要你裁决
1. pead_pool.py:22 低价层排序键仍读前复权价（#265③ 误标 bug 仍在生产线上跑）：修 big_kcache_unadj 底座，还是换绝对价格源？
2. claims_registry 的 g7_槽10.过G7 布尔位已被污染（16 条 CROSS_LOW_* 无 K1 数值）：引用一律以带 K1 数值的 37 条为准，是否重跑统一 schema？
3. docs/plan/DECISIONS.md 的 OPEN 项 O-01..O-08（转私仓/holdout 长度/引 statsmodels/槽位上限/恢复暂停 job/对账频率/清 tmp/税后锚口径）——PLAT-00、SEC-01 两条 P0 已 blocked 挂在这里。
4. data/similarity_features.npz 468MB 超 GitHub 单文件上限，本次未入库（NAS 本地保留），如需入库请指定方式（LFS/分卷/仅 NAS）。

## 同晚并行落账（非本晨报五卡，顺带知会）
- #274 数据破壁：历史竞价（问财可回填任意日）/分钟级（baostock 5分6年）/封单（HiThink seal_money 2020-08 起 1503 天已在库）/龙虎榜席位（东财 2004 起 219 万行）四类全挖通，fetcher 落地 engine/datawall_fetcher.py。
- #275 龙虎榜席位跟随：261 交易日严格复审全组 REJECT（游资买 T+5 边际 -1.96pp、机构买 -2.27pp 更差），与 #41/#246 构成「聪明钱跟单」三连证；玉兰路出货反向指标存活（仅作持仓减持语境证据）。
