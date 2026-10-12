# INTERFACES · 冻结数据契约（改它＝改全系统）

> **状态：FROZEN（冻结）**。任何字段/路径/单位变更必须：①在 `DECISIONS.md` 新增一条并注明影响面 ②用户签字 ③所有消费方同批改。
> 目的：**防止每个新模块自造一套 JSON 结构**——那是 #262-C（口径散在 109 个文件）的重演。
> 本文件是**唯一**定义字段的地方；其他文档只许引用，不许复述。

---

## I0 通用约定（所有新产物必须遵守）

| 项 | 规则 |
|---|---|
| 路径 | `data/<domain>/<artifact>[_<YYYYMMDD>].json(l)`；domain ∈ `portfolio` / `risk` / `recon` / `dq` / `registry` / `research` / `private` |
| 编码 | 写：UTF-8（无 BOM）；读旧文件允许 `utf-8-sig` |
| 写盘 | **原子写**：先写 `<file>.tmp` 再 `os.replace`；JSONL 用追加（`a`） |
| 日期 | `YYYY-MM-DD`，含义＝**BJT 交易日**（不是自然日、不是 UTC）|
| 时间戳 | ISO8601 带时区：`2026-10-09T19:45:00+08:00` |
| 货币/价格 | 价格 2 位小数（元）；金额 2 位小数（元）；股数**整数**（A 股 100 的整数倍）|
| 比率 | **小数**（`0.0123` 表示 1.23%）；禁止混用百分数字面量 |
| 字段名 | 新模块一律**英文 snake_case**；中文仅限展示层（面板/推送文案）|
| 兼容 | 旧产物字段名**不得重命名**（迁移另立条目）；只允许**追加**字段 |
| 必须带 `_meta` | 所有新结果文件必须含 I8 的 `_meta` 块 |

---

## I1 成交记录 Fill（`portfolio` · 账本输入）

文件：`data/portfolio/fills_<line>.jsonl`（一行一笔）

```json
{"line":"pead_pool","code":"002384","side":"buy","day":"2026-10-09","price":4.85,"shares":4100,
 "cash":19885.00,"fee":5.00,"tax":0.00,"note":"9:25 竞价挂单","sig_day":"2026-10-08"}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| line | str | 线名（`pead_pool`/`limitdown_deep`/`gold`/`rebalance`/`dividend_anchor`/`xrules`/`reversal`）|
| code / side / day | str | 6 位代码 / `buy`\|`sell` / BJT 交易日 |
| price | float | **成交价（原始价，禁止前复权）** |
| shares | int | 100 的整数倍；卖出可全部 |
| cash | float | `price*shares`（成交金额，不含费税）|
| fee / tax | float | 佣金+印花+过户（走 `taxfee`）/ 红利税等 |
| sig_day | str | 触发该笔的信号日（用于归因：T+1 入场）|

**不变量**：`cash = price*shares`；`shares % 100 == 0`；`(line, code, day, side)` 唯一（重复入账必须报错）。

---

## I2 净值曲线 NAV（`portfolio` · 全系统消费）

文件：`data/portfolio/nav.json`

```json
{"_meta": {"generated_at":"2026-10-09T21:10:00+08:00","cash0":200000.0,"lines":["pead_pool","limitdown_deep","gold","rebalance"],"params_hash":"ab12cd","data_snapshot":"2026-10-09","code_version":"5e7b82c"},
 "series": [
   {"date":"2026-10-09","nav":203450.12,"cash":12000.00,"mkt_value":191450.12,"exposure":0.94,
    "by_line":{"pead_pool":{"mkt_value":98000.0,"ret":0.0121},"gold":{"mkt_value":93450.12,"ret":0.0043}}}
 ]}
```

| 字段 | 说明 |
|---|---|
| nav | 总净值＝cash + mkt_value |
| exposure | mkt_value / nav（0~1；空仓期≈0）|
| by_line | 每线市值与当日收益（归因与风险层的输入）|

**不变量**：`nav == cash + mkt_value`（误差 < 0.01 元）；`series` 按日期升序无缺口（交易日历为准）。

---

## I3 信号记录 Signal（`lines/*` 生产输出）

文件：`data/signals/<line>_<YYYYMMDD>.json`

```json
{"line":"pead_pool","sig_day":"2026-10-08","entry_day":"2026-10-09","generated_at":"2026-10-08T19:35:00+08:00",
 "items":[{"code":"002384","name":"东山精密","reason":"预增50+ 低位 低价层","rank":1,
           "ref_price":4.85,"plan":"9:25 竞价挂单 2 万/槽","invalid_if":"开盘一字/停牌"}]}
```

| 字段 | 说明 |
|---|---|
| entry_day | 计划入场日（T+1）|
| ref_price | 信号日参考价（**原始价**，用于与对账比成交价）|
| plan / invalid_if | 执行方式与作废条件（人读 + 机器校验）|

---

## I4 券商成交明细 CSV（`recon` 输入，用户每周导出）

必需列（列名容错，但语义必须齐全）：
`成交日期, 证券代码, 买卖标志, 成交价格, 成交数量, 成交金额, 手续费, 印花税, 过户费, 其他费用, 成交时间`
可选列：`证券名称, 合同编号`
落地：`data/private/broker_trades/<YYYYMMDD>_<来源>.csv`（**私有，不进公开仓库**）

---

## I5 DQ 断言输出（`dq`）

文件：`data/dq/dq_<YYYYMMDD>.json`

```json
{"date":"2026-10-09","checks":[
  {"name":"kcache_coverage","scope":"big_kcache","value":0.945,"threshold":0.8,"ok":true},
  {"name":"freshness","scope":"index_sh000001","last_date":"2026-10-09","expected":"2026-10-09","ok":true},
  {"name":"m60_gap","scope":"m60_cache","missing_days":0,"ok":true}]}
```

`ok=false` 的项必须能被 `monitor/alerts.py` 转成推送（含冷却与分级）。

---

## I6 策略状态（`registry`）

文件：`data/registry/state.json`

```json
{"updated_at":"2026-10-09T21:00:00+08:00","items":[
  {"id":"预增低位池_v1","state":"SHADOW","since":"2026-10-03","evidence":"AGENTS#241",
   "rolling_excess_t":1.8,"rolling_sharpe":0.9,"next_review":"2026-11-01"}]}
```

`state ∈ {IDEA, RESEARCH, CANDIDATE, SHADOW, LIVE, ICU, DEAD}`；**生产脚本只能调用 LIVE/SHADOW（后者只记账）**。

---

## I7 私有/公开清单（配合 SEC-01）

| 面 | 允许内容 |
|---|---|
| **公开**（仓库/Pages） | 代码、方法论、已证伪结论、非敏感研究产物、本 `docs/plan/` |
| **私有**（`data/private/`，gitignore） | 真实持仓与成本、资金与槽位、台账 JSONL、委托单、对账输出、券商 CSV、key/凭证 |

---

## I8 结果文件 `_meta`（可复现锚，所有新结果文件必含）

```json
"_meta": {"generated_at":"...","params_hash":"...","data_snapshot":"YYYY-MM-DD","code_version":"<git short sha>","inputs":["data/..."],"owner":"engine.<module>"}
```

用途：任何结论可回答"这是哪版代码、哪套参数、哪天数据算出来的"（#263⑥）。
