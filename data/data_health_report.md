# 数据面监控 · 2026-10-20（体检基准 ref=2026-10-19，--ref-date）

注册 10 项：ok 9 · stale 1
version=data_health/1.0 (2026-10-20, DATA-01) · registry=1.0 (2026-10-20, DATA-01) · generated_at=2026-10-20T12:07:45+08:00

## 🚨 致命（0 项，断供=下游结论不可信）
（无）

## ⚠️ 滞后/日期异常（1 项）
- **xrules_state** `stale`：滞后 1 交易日 > max_lag 0（末端 2026-10-16，基准 2026-10-19） ｜ owner：engine/xrules_daily.py

## 明细

| key | status | severity | 末端日期 | lag(交易日) | max_lag | owner |
|---|---|---|---|---|---|---|
| big_kcache | ok | fatal | 2026-10-19 | 0 | 0 | engine/update_kcache.py（18:30/19:00 分片 + 21:00 兜漏） |
| emotion_series | ok | fatal | 2026-10-19 | 0 | 0 | engine/emotion_series.py（15:40 周期仪班） |
| index_sh000001 | ok | fatal | 2026-10-19 | 0 | 0 | engine/update_kcache.py（update_index 段） |
| kcache | ok | warn | 2026-10-19 | 0 | 0 | fen_shadow.py（线1影子随取随更） |
| line_health | ok | warn | 2026-10-19 | 0 | 0 | engine/line_health.py |
| ops_state | ok | fatal | 2026-10-19 | 0 | 0 | engine/dashboard_build.py（20:40 面板班写出） |
| regime_log | ok | warn | 2026-10-19 | 0 | 0 | engine/regime_daily_append.py（18:35 班） |
| regime_timeline_hcap | ok | fatal | 2026-10-19 | 0 | 0 | engine/regime_daily_append.py（18:35 班） |
| watch_pool | ok | info | 2026-10-19 | 0 | 1 | engine/watch_pool.py |
| xrules_state | stale | warn | 2026-10-16 | 1 | 0 | engine/xrules_daily.py |
