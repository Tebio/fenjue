# V3 冻结线生产触面审计（2026-10-21，K3 审计单，只读）

审计范围：`scheduler/cron.py`、`api/app.py` 对 V3 冻结线模块的全部 import 与调用点；
被调模块函数体逐行核对 R4 已录缺陷。本单未改任何代码与文档。
行号以 HEAD（工作区现状）为准。证据命令见附录 A。

## 0. 结论速览

- 4 条图谱边全部属实，但**两条边的生产触面当前都是休眠的**：
  - `scheduler/cron.py` 全仓无人实例化（scheduler_jobs 表为空、无模块 import scheduler 包），最后运行痕迹 ~2026-08-11；
  - `api/app.py` 的 docker 容器未运行，NAS 上 8001 端口被另一服务占用（返回 zspace 风格 `{"code":"200","msg":"OK"}`，非 FastAPI），`/regime` 当前不可达。
- **R4「market_data/feedback/event_registry 三模块全仓零引用」断言落笔时即不成立**：三处引用全部存在于 2026-07-07 的 V1 提交，早于 R4（2026-09-06）两个月。不存在「R4 后有人接线」，无解冻流程被绕过——是 R4 审查本身的漏检（疑似只 grep 了 engine/ 目录）。
- 已录 7 条缺陷全部在源码中复核成立；另有 2 条本单新发现（cron 的行情 stub 使评分模板化；macro_adjustment 契约冲突在 cron 路径下实际不触发），见 §2 与 §4。

## 1. 调用点清单（4 条边逐一拆解）

### 边 1：scheduler/cron.py → engine/event_registry.py

- import：cron.py:23 `from engine.event_registry import EventRegistry, todays_registry`（`EventRegistry` 类本身 import 后未使用，仅 `todays_registry` 被调）。
- 调用点（全部在 `run_score_snapshot`，cron.py:292-391）：
  - cron.py:304 `registry = todays_registry()` → event_registry.py:155-166。**硬编码 2026-07-08 的 8 条事件**；`Event.created` 默认 `datetime.now`（event_registry.py:46），每次调用全部事件年龄归 0。
  - cron.py:305 `registry.tick()` → event_registry.py:99-103。`alive` 判定（event_registry.py:60-61）下年龄恒 ~0，永不剔除，tick 是无操作。
  - cron.py:306 `registry.regime_impact()` → event_registry.py:124-150。产出 `regime_override`（可能为 `"crisis"`，event_registry.py:140）与 `position_cap_adj`。
  - cron.py:309 `mapper.load_events(registry.breakdown())` → event_registry.py:109-122。breakdown 明细**不含 direction 字段**（只有 label/category/severity/age/ttl/decay/score）。
- 产出去向：macro_impact 只写进快照 JSON 的 `macro` 块（cron.py:369-376），**没有任何代码消费 regime_override / position_cap_adj**。

### 边 2：scheduler/cron.py → engine/macro_industry.py

- import：cron.py:24 `from engine.macro_industry import MacroIndustryMapper`。
- 调用点（同在 run_score_snapshot）：
  - cron.py:308 `MacroIndustryMapper()` → macro_industry.py:61-66（base_weights 硬编码 5 个产业）。
  - cron.py:310 `mapper.map()` → macro_industry.py:72-108。核心计算在 macro_industry.py:91：`impact = adj * (abs(score) / 4.5)` —— **abs() 把事件方向抹掉**，调整方向完全由 EVENT_INDUSTRY_RULES 写死（macro_industry.py:20-55）。
  - cron.py:311 `mapper.sector_multiplier_effect()` → macro_industry.py:110-115（内部再调一次 map()，重复计算）。
- 产出去向：同样只进快照 JSON（cron.py:374-375），不影响任何评分/分档。

### 边 3：scheduler/cron.py → engine/feedback.py

- import：cron.py:25（模块级）+ cron.py:500、559（函数内重复 import）。
- 调用点 A（写反馈）：cron.py:314 实例化 → feedback.py:64-70；cron.py:343 `fe.log_prediction(code, score)` → feedback.py:74-105。写 `data/feedback/{date}.json`。R4 A 组修复已在位（industry_hash 哈希的是 engine/mapping/industry.py，feedback.py:101；adjust_weight 防负权重，feedback.py:335-339）。
- 调用点 B（30 日验证）：`verify_30d_predictions`（cron.py:493-543）→ cron.py:507 `feedback._load_records`（feedback.py:364-369）→ cron.py:526 `feedback.verify(...)`（feedback.py:140-198）。verify 优先走 R4 补充审查修的 `_std_return`（big_kcache 前复权+次日开盘+0.15%，feedback.py:107-129）；cron 传入的 `current_price` 来自 `_get_quote_data` stub（cron.py:599-612），不含 price 键，cron.py:521-523 会 skip——即**旧口径回退路径在 cron 下永远走不到**，只用标准口径，行为正确。
- 注意：log_prediction 记录的分数来自边 1 下游的 ScoringEngine（见下），上游失真会原样入库。

### 边 4：api/app.py → engine/regime/market.py

- import：api/app.py:26 `from engine.regime.market import MarketRegime`。
- 调用点：api/app.py:186 `MarketRegime(CONFIG_PATH).assess(tier_counts=tiers)`（`/regime` 端点，api/app.py:174-195）→ market.py:43-82。tier_counts 来自 daily_score 表最新日期（api/app.py:178-183）。
- `assess` 的判定分支（market.py:65-72）只可能返回 `risk_on / risk_neutral / risk_off`——**没有 crisis 分支**；`_capital_style` 里有 crisis 映射（market.py:93）但从不可达。
- 其他触面：tests/test_endpoints.py:15 也 import api.app（测试用，非生产）；docker/docker-compose.yml:23 是唯一的生产启动定义，容器当前未运行（§4）。

### 附带：边 1 的下游传递调用（cron.py:328 `engine.score_stock`）

run_score_snapshot 的评分核心经 cron.py:552 惰性加载 `ScoringEngine`（engine/scoring/scorer.py），逐票调 `score_stock`（scorer.py:57-153），其内部链：
- `_score_industry` → engine/mapping/industry.py:64-80（`get_industry_score`，查不到返回 0，industry.py:72；多主题取 `entries[0]`，industry.py:73-74）。
- `money_flow.assess`（scorer.py:128）→ engine/moneyflow/__init__.py:29-90 → `institution.score` 恒 5（institution.py:16-19）、`margin.update_and_score`（margin.py:272-304，内含 223-233 死代码）、`dragon.score`。
- `_confidence`（scorer.py:296-335）在 scorer.py:325 **第二次**调 `money_flow.assess`（R4 补充 ⑧：每次 assess 都会触发 margin 的 curl 网络请求+缓存写，等于每票双倍请求）。
- macro_adjustment 契约冲突（R4 补充 ⑦）：docstring（scorer.py:73-77）宣称影响 total/tier/verdict，实现只写 metadata（scorer.py:112-116）。**cron.py:328 调用时根本没传 macro_adjustment**，所以该冲突在 cron 路径下不触发——但也意味着宏观管线对评分零影响是既定事实而非偶然。

## 2. 缺陷触及矩阵

行：调用点（§1 编号）；列：R4 已录缺陷。每格附行号证据。

| 缺陷＼调用点 | 1a registry/tick/impact | 1b mapper.map | 1c score_stock 链 | 3a log_prediction | 3b verify_30d | 4 /regime |
|---|---|---|---|---|---|---|
| ① MacroOverlay→MarketRegime 未接线，crisis 死代码 | **触及（供给侧）**：regime_impact 可产出 "crisis"（event_registry.py:140），但只写 JSON（cron.py:369-376），无消费者 | 未触及 | 未触及（macro 不进 score，scorer.py:112-116；cron.py:328 不传参） | 未触及 | 未触及 | **触及（需求侧）**：assess 无 crisis 分支（market.py:65-72），planner 的 `"crisis": []`（planner.py:85）因无人调用 get_plan 且 override 不传入而双死 |
| ② _confidence 哨兵不自洽 | 未触及 | 未触及 | **触及**：real_dims 判 `v != 5`（scorer.py:317），但 flow 无数据返 6（scorer.py:173）、industry 查不到返 0（industry.py:72），两者都被计为「真实数据」 | 间接（记录含该 confidence） | 间接 | 未触及 |
| ③ institution 恒 5 → 资金健康度多 unknown | 未触及 | 未触及 | **触及**：institution.py:16-19 恒 5；≥2 模块默认即 unknown（moneyflow/__init__.py:49-53）——institution 固定占掉 1 个默认名额，margin/dragon 再无数据即 unknown | 间接 | 未触及 | 未触及 |
| ④ macro_industry.map 丢 direction | 未触及（供给的 breakdown 本就无 direction 字段，event_registry.py:111-122） | **触及**：macro_industry.py:91 `abs(score)` 抹方向；地缘缓和（direction=+1）会按规则表写死的 +0.15（macro_industry.py:23）反向加军工 | 未触及 | 未触及 | 未触及 | 未触及 |
| ⑤ industry 多主题取 YAML 第一个 | 未触及 | 未触及 | **触及**：industry.py:73-74 注释明写 "Use the first theme's score"，取 entries[0] 不按热度 | 间接 | 未触及 | 未触及 |
| ⑥ margin.py 逐日累乘死代码 | 未触及 | 未触及 | **触及（无害）**：margin.py:223-233 `cumulative_daily_pct` 计算后无任何读取（评分逻辑只用 down_days/pct_3d/day1_change，margin.py:238-267） | 未触及 | 未触及 | 未触及 |
| ⑦ todays_registry 硬编码 07-08 快照 + created 重置 | **触及**：event_registry.py:155-166 硬编码 8 条 07-08 事件；created 默认 now（event_registry.py:46）→ age≈0 → decay≈1（event_registry.py:53-57）→ tick 永不剔除（event_registry.py:60-61,99-103）。**衰减形同虚设成立，且更糟：每天把 3.5 个月前的事件当「今日宏观」以满权重输出** | 间接（吃到陈旧事件） | 未触及 | 间接（macro_hash 哈希的是文件内容，feedback.py:102，文件不变哈希不变，发现不了事件陈旧） | 未触及 | 未触及 |

### 本单新发现（不在 R4 清单内）

- **N1（生产风险级，若 job 复跑）**：cron.py:599-612 `_get_quote_data` 是 stub，恒返 `{"turnover": 6.0, "pct_20d": 0.0}`。后果：每只票 flow 恒 8（scorer.py:175，3≤6≤10）、expect 恒 9（scorer.py:272）、margin 恒 6（scorer.py:224-225）——**所有股票六个维度里三个是模板值，评分差异只剩 industry 一项**。2026-07-07~08-11 期间产出的 scores JSON / daily_score / feedback 记录全部受此影响。
- **N2（隐性失真）**：/regime 的 tier_counts 取自 daily_score 最新日期（api/app.py:178-183），而该表停在 2026-08-11（附录 A）。服务若重启，返回的是基于两个月前评分的 regime，且无任何新鲜度告警。

## 3. 「零引用」断言核实（R4 原话：market_data/feedback/event_registry 三模块全仓零引用）

grep 实证（命令见附录 A）：

| 模块 | R4 断言 | 现状 | 引用者首次出现 | 结论 |
|---|---|---|---|---|
| engine/market_data.py | 零引用 | console/routes/dashboard.py:359 `from engine.market_data import MarketData`（try/except 内函数级 import） | commit d3b14c0a4，**2026-07-07**，早于 R4 两个月 | **断言落笔时即错**。无 R4 后接线。附带事实：该消费端（console 8002）当前也未运行 |
| engine/feedback.py | 零引用 | scheduler/cron.py:25（模块级 import，V1 即有） | commit f6e8f765d，**2026-07-07** | **断言落笔时即错**。engine/repro.py:43 的 "feedback" 只是 SKIP_DIRS 目录名字符串，非引用 |
| engine/event_registry.py | 零引用 | scheduler/cron.py:23（同上） | commit f6e8f765d，**2026-07-07** | **断言落笔时即错** |

- 不存在「R4 后有人接线、未过解冻流程」的情况：三处引用全部是 V1 原生代码，R4 审查时就在仓库里。
- 但断言的**精神部分成立**：这三个模块（及其唯一引用者 cron.py）都不在 V2 短线线、研究回测线、law_pipeline REGISTRY 注册线之内；它们属于 V1/V3 演示面，与每日生产信号（策略 A/B、涨停池、regime 时间轴等）无任何数据通路。
- 台账处置建议：AGENTS.md 只增不改，建议追加新编号条目更正 R4 该句为「审查漏检」，避免后人按「零引用」放心删除或放心接入。

## 4. 生产影响评估与处置建议

### 4.1 当前真实触面（实证）

| 触面 | 状态 | 证据 |
|---|---|---|
| run_score_snapshot / verify_30d_predictions | **休眠 ~2.5 个月**。全仓无 `import scheduler`；scheduler_jobs 表为空（job 从未持久化，历史运行是直接调方法）；scores JSON 停 2026-07-14，daily_score 停 2026-08-11，data/feedback 停 2026-08-11 | 附录 A |
| api/app.py（/score /watchlist /regime /run） | **未在运行**。compose 定义的容器没起；NAS 8001 被另一服务占用（非 FastAPI 响应），8002（console）无监听 | 附录 A |
| V2 短线线 / 研究线 / 注册信号线 | 与 V3 各模块**零数据通路**（本单 §3 grep 确认） | 附录 A |

**对每日生产输出的实际影响：当前为零**——不是因为缺陷无害，而是因为整个 V3 触面都没在跑。真正每日跑的策略 A/B、kcache、体检、影子盘等不经过这些模块。

### 4.2 处置建议（逐条给倾向+作废条件）

1. **scheduler/cron.py 宏观管线（todays_registry + mapper）**：倾向 **不摘依赖、不删代码，但冻结「禁止复跑」标注**——在解冻投票前不得把 run_score_snapshot / verify_30d_predictions 挂回任何调度（hermes cron / 系统 cron / 容器入口）。
   作废条件：任何人提出重启每日评分 job → 必须先走解冻流程，且解冻清单第一项就是修缺陷 ⑦（事件快照陈旧+衰减虚设）与 N1（行情 stub）。
2. **缺陷 ④（direction 丢失）**：倾向 **随解冻一并修**，不急。当前唯一消费者是快照 JSON 的展示字段，无人据此调仓。
   作废条件：industry_weights 若被任何下游（含人工读 JSON 决策）实际引用 → 升级为生产风险，需立即修（修法：breakdown 带 direction，map() 用带符号 score）。
3. **api/app.py /regime**：倾向 **维持不跑；若重启容器则接受「crisis 永不可达」需在文档显式声明**。重启前还要先解决 8001 端口冲突和 N2（tier_counts 数据陈旧无告警）。
   作废条件：若 /regime 的输出被任何自动化（含 cron 推送、看板轮询）消费 → crisis 死代码（缺陷①）升级为生产风险，必须先补可达 crisis 路径或摘除 crisis 语义。
4. **缺陷 ②③⑤（confidence 哨兵 / institution 占位 / 多主题取第一）**：倾向 **维持 R4 结论，全部进解冻投票材料**，不在冻结期单修。它们只影响休眠的评分链。
   作废条件：评分 job 复跑即触发，同第 1 条。
5. **缺陷 ⑥（margin.py 死代码）**：无害，解冻时直接删（维持 R4 结论）。
6. **台账更正（§3）**：倾向 追加 AGENTS.md 新编号，把 R4「三模块零引用」改记为审查漏检。不动代码、不动旧条目。

### 4.3 一句话总评

V3 冻结线的生产触面是「插着线但没通电」：接线在 V1 就存在（R4 漏检），但调度从未持久化、容器没在跑，缺陷当前零伤害；风险全部集中在「有人把 job 挂回调度或把容器重启」的那一刻——解冻流程是唯一正确的通电许可。

## 附录 A：证据命令（全部实跑于 2026-10-21）

```bash
# 零引用核实（在 /opt/data/fenjue）
grep -rn --include='*.py' -E 'market_data' . | grep -v '/.venv/' | grep -v 'engine/market_data.py'
grep -rn --include='*.py' -E 'event_registry|EventRegistry|todays_registry' . | grep -v '/.venv/' | grep -v 'engine/event_registry.py'
git log -1 --format='%h %ad %s' --date=iso d3b14c0a4   # 2026-07-07 market_data 接入 dashboard
git log --format='%h %ad %s' --date=short f6e8f765d -1  # 2026-07-07 V1 提交（含 cron.py 全部 import）

# scheduler 休眠证据
grep -rn --include='*.py' -E 'from scheduler|import scheduler' . | grep -v '/.venv/' | grep -v '^\./scheduler/'   # 空
sqlite3 data/fenjue.db 'select max(date),count(*) from daily_score; select * from scheduler_jobs;'
  # → ('2026-08-11', 53) / scheduler_jobs 0 行
ls -t research/data/scores/ | head -1   # 2026-07-14.json
ls -t data/feedback/ | head -1          # 2026-08-11.json

# API 存活证据（NAS 192.168.2.10）
curl -s http://127.0.0.1:8001/health    # {"code":"200","msg":"OK","ts":...,"data":{"status":"up"}} ← 非 FastAPI，端口被占
curl -s http://127.0.0.1:8001/regime    # 404 page not found（Go 风格，非 FastAPI 的 {"detail":...}）
ss -tln | grep -E ':8001|:8002'         # 仅 8001（且非本服务），8002 无监听

# 缺陷行号复核（逐一 read_file）
# ① market.py:65-72 / planner.py:85 / event_registry.py:140 + cron.py:369-376
# ② scorer.py:317,173 + industry.py:72
# ③ institution.py:16-19 + moneyflow/__init__.py:49-53
# ④ macro_industry.py:91,20-55 + event_registry.py:111-122
# ⑤ industry.py:73-74
# ⑥ margin.py:223-233
# ⑦ event_registry.py:155-166,46,53-61,99-103
# N1 cron.py:599-612 + scorer.py:175,272,224-225
# N2 api/app.py:178-183 + daily_score max date 2026-08-11
```
