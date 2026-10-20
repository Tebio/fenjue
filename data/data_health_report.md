# 数据面监控 · 2026-10-20（体检基准 ref=2026-10-20，auto(最近已收盘交易日)）

注册 14 项：ok 2 · stale 7 · fatal_lag 4 · unknown_date 1
version=data_health/1.0 (2026-10-20, DATA-01) · registry=1.1 (2026-10-20, DATA-09) · generated_at=2026-10-20T17:00:52+08:00

## 🚨 致命（4 项，断供=下游结论不可信）
- **big_kcache** `fatal_lag`：滞后 1 交易日 > max_lag 0（末端 2026-10-19，基准 2026-10-20）（连续 1 天）
  阻塞：深档名单、影子盘、周期仪、权威时间轴、X规则线 ｜ owner：engine/update_kcache.py（18:30/19:00 分片 + 21:00 兜漏）
- **emotion_series** `fatal_lag`：滞后 1 交易日 > max_lag 0（末端 2026-10-19，基准 2026-10-20）（连续 1 天）
  阻塞：周期仪、权威时间轴 ｜ owner：engine/emotion_series.py（15:40 周期仪班）
- **index_sh000001** `fatal_lag`：滞后 1 交易日 > max_lag 0（末端 2026-10-19，基准 2026-10-20）（连续 1 天）
  阻塞：权威时间轴、周期仪 ｜ owner：engine/update_kcache.py（update_index 段）
- **regime_timeline_hcap** `fatal_lag`：滞后 1 交易日 > max_lag 0（末端 2026-10-19，基准 2026-10-20）（连续 1 天）
  阻塞：面板20:40、日度状态包、回测族 ｜ owner：engine/regime_daily_append.py（18:35 班）

## ⚠️ 滞后/日期异常（8 项）
- **cap_hist** `stale`：滞后 16 交易日 > max_lag 5（末端 2026-09-18，基准 2026-10-20） ｜ owner：engine/fetch_cap_history.py（手动抓取，无 cron）
- **claims_shadow** `stale`：滞后 2 交易日 > max_lag 1（末端 2026-10-16，基准 2026-10-20） ｜ owner：engine/claims_shadow.py（stock_claims_shadow.py 班 82e54a0a812f）
- **fund_cache** `stale`：滞后 16 交易日 > max_lag 1（末端 2026-09-18，基准 2026-10-20） ｜ owner：engine/fetch_fundamentals.py（手动分片抓取，无 cron；最近一批 2026-09-18，tmp/launch_fund.sh）
- **industry_map** `unknown_date`：date_expr="none"：该数据集无机器可读日期，显式不做新鲜度检查（freshness_unknown，靠人工复核；见注册表 note） ｜ owner：内部维护（人工；engine/scripts 无自动生产者，2026-10-20 实测 grep 零命中）
- **kcache** `stale`：滞后 1 交易日 > max_lag 0（末端 2026-10-19，基准 2026-10-20） ｜ owner：fen_shadow.py（线1影子随取随更）
- **line_health** `stale`：滞后 1 交易日 > max_lag 0（末端 2026-10-19，基准 2026-10-20） ｜ owner：engine/line_health.py
- **regime_log** `stale`：滞后 1 交易日 > max_lag 0（末端 2026-10-19，基准 2026-10-20） ｜ owner：engine/regime_daily_append.py（18:35 班）
- **xrules_state** `stale`：滞后 1 交易日 > max_lag 0（末端 2026-10-19，基准 2026-10-20） ｜ owner：engine/xrules_daily.py

## 明细

| key | status | severity | 末端日期 | lag(交易日) | max_lag | owner |
|---|---|---|---|---|---|---|
| big_kcache | fatal_lag | fatal | 2026-10-19 | 1 | 0 | engine/update_kcache.py（18:30/19:00 分片 + 21:00 兜漏） |
| cap_hist | stale | warn | 2026-09-18 | 16 | 5 | engine/fetch_cap_history.py（手动抓取，无 cron） |
| claims_shadow | stale | warn | 2026-10-16 | 2 | 1 | engine/claims_shadow.py（stock_claims_shadow.py 班 82e54a0a812f） |
| emotion_series | fatal_lag | fatal | 2026-10-19 | 1 | 0 | engine/emotion_series.py（15:40 周期仪班） |
| fund_cache | stale | warn | 2026-09-18 | 16 | 1 | engine/fetch_fundamentals.py（手动分片抓取，无 cron；最近一批 2026-09-18，tmp/launch_fund.sh） |
| index_sh000001 | fatal_lag | fatal | 2026-10-19 | 1 | 0 | engine/update_kcache.py（update_index 段） |
| industry_map | unknown_date | info | — | — | 0 | 内部维护（人工；engine/scripts 无自动生产者，2026-10-20 实测 grep 零命中） |
| kcache | stale | warn | 2026-10-19 | 1 | 0 | fen_shadow.py（线1影子随取随更） |
| line_health | stale | warn | 2026-10-19 | 1 | 0 | engine/line_health.py |
| ops_state | ok | fatal | 2026-10-20 | 0 | 0 | engine/dashboard_build.py（20:40 面板班写出） |
| regime_log | stale | warn | 2026-10-19 | 1 | 0 | engine/regime_daily_append.py（18:35 班） |
| regime_timeline_hcap | fatal_lag | fatal | 2026-10-19 | 1 | 0 | engine/regime_daily_append.py（18:35 班） |
| watch_pool | ok | info | 2026-10-20 | 0 | 1 | engine/watch_pool.py |
| xrules_state | stale | warn | 2026-10-19 | 1 | 0 | engine/xrules_daily.py |
