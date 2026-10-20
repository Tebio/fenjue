# 焚诀数据资产清单（2026-10-20 实测）

> 目的：回答"数据在不在本地、什么操作才会真拉 API"。**结论先说：日线级数据全在本地，研究/回测/回放零 API。**
> 本文所有数字来自 `data/` 目录实测，不是估计。

## 一、总量

| | |
|---|---|
| 文件数 | 42,156 |
| 体积 | **8.9 GB** |
| 位置 | `/opt/data/fenjue/data/`（全部本地，无外部数据库依赖） |

按目录（体积降序，前 10）：

| 目录 | 文件 | 体积 | 内容 |
|---|---|---|---|
| `(根目录散文件)` | 409 | 2661 MB | 分析产物 + 三个大库（见第四节） |
| `fund_cohold/` | 39 | 797 MB | 基金持仓明细 |
| `cache/` | 6 | 794 MB | 面板类 npz（k4_panel 等） |
| `m60_cache/` | 3377 | 757 MB | 每只票的 MA60/量能缓存 |
| `big_kcache_unadj/` | 3381 | 685 MB | **不复权**日线（算涨跌停/一字板必须用） |
| `big_kcache/` | 3377 | 668 MB | **前复权**日线（算收益必须用） |
| `big_kcache_unadj_bak0911/` | 2877 | 607 MB | 不复权的旧备份（2026-09-11 前） |
| `ann_stream/` | 186 | 532 MB | 公告流 |
| `fund_cache/` | 3377 | 486 MB | 财务指标缓存 |
| `holder_num_cache/` | 3195 | 171 MB | 股东户数 |
| `hithink/` | 3384 | 139 MB | 同花顺落盘（涨停池/龙虎榜等） |

## 二、核心数据仓库（可完全离线工作）

| 资产 | 规模 | 覆盖 | 谁能更新 |
|---|---|---|---|
| `big_kcache/*.json` | 3377 只 | 2018-01 ~ **2026-10-19**（94.4% 覆盖） | `engine/update_kcache.py`（cron 18:30/19:00/21:00） |
| `big_kcache_unadj/*.json` | 3381 只 | 同上 | 同上（同批产出） |
| `m60_cache/` | 3377 只 | 同上 | `engine/update_m60.py` |
| `fund_cache/` | 3377 只 | 季度财务 | `engine/fetch_fundamentals.py` |
| `holder_num_cache/` | 3195 只 | 股东户数 | `engine/fetch_*.py` |
| `cap_hist/` | 3368 只 | 市值历史 | `engine/fetch_cap_history.py` |
| `hithink/` | 3384 个 | 涨停池 2024-09 起 / 龙虎榜 1 年 | `engine/hithink_daily.py` |
| `index_sh000001.json` | 1 | 上证指数日线 | `engine/fetch_index_k.py` |
| `margin_stock.db` | 614 MB | 两融（覆盖主事件 46%） | `engine/margin_stock_daily.py` |
| `emotion_series.jsonl` | 2131 行 | 2018-01-02 ~ 2026-10-19 | `engine/emotion_series.py` |
| `regime_timeline_hcap.json` | 278 KB | 全历史四态时间轴 | `engine/regime_daily_append.py` |

**今天跑过的重活全是本地读**：RES-10 全宇宙回测（n=9754 事件、3.8 GB 峰值、153 s）只读 `big_kcache/`；
`claims_audit` 全量复跑（68 条主张）同样零 API。

## 三、真会拉外部数据的脚本（仅这些）

| 数据源 | 脚本数 | 代表 |
|---|---|---|
| baostock | 13 | `update_kcache.py`、`update_m60.py`、`fetch_index_k.py`、`fetch_fundamentals.py`、`fetch_cap_history.py`、`rebuild_unadj.py` |
| 同花顺 | 26 | `hithink_daily.py`、`limitup_pool_fetch.py`、`emotion_series.py` |
| 东财 HTTP | 10 | `margin_stock_daily.py`、`fetch_pead_events.py`、`guba_*`、`announcement_vet.py` |
| 新浪行情 | 4 | `dashboard_build.py`、`fast_close_update.py`、`shadow_today_mtm.py`、`watchlist_refresh.py` |
| 腾讯行情 | 4 | `console.py`、`market_data.py`、`theme_study.py` |

**纪律**：
1. 研究/回测/验证脚本**一律不许**调这些路径 —— 只读 `big_kcache/`（前复权算收益）、`big_kcache_unadj/`（不复权判涨跌停）。
2. 只有 cron 里的"生产者"作业能拉数据；拉数脚本互斥（baostock 禁双进程，kcache 两分片必须串行）。
3. 需要新数据时先查本地覆盖区间，别从头拉 —— `big_kcache` 已到 2026-10-19。

## 四、可回收空间（等你点头，不擅自删）

| 项 | 体积 | 说明 |
|---|---|---|
| `big_kcache_unadj_bak0911/` | 607 MB | 2026-09-11 的不复权旧备份，现役数据已覆盖 |
| `data/root 一次性研究产物` | ~400 MB | `research_reports_20260927.json`(136MB)、`graveyard_autopsy_20260926.json`(70MB)、`org_survey_20260927.json`(30MB)、`guba_sentiment_events_20261016.npz`(95MB) 等带日期文件 |
| `kcache_legacy_sina_停更20260904/` | 26 MB | 新浪口径旧缓存，已停更 |

合计可回收 **≈1.0 GB**（8.9 → 7.9 GB）。`similarity_features.npz`(446MB)、`factor_census_base.npz`(222MB)、
`margin_stock.db`(614MB)、`margin_daily.jsonl`(339MB) 是**在用**资产，不动。

## 五、审计与回测的 API 纪律（补充说明）

2026-10-20 主 agent 审计 DATA-07 时跑过 `preflight 601398`（下单前体检）。该脚本自称"只读拼合、不发明新信号"，
但它是**消费者**不是生产者，不写本地数据。今后所有验证性运行优先用**只读入口**；
必须跑生产者脚本时先确认它不会重拉全量。
