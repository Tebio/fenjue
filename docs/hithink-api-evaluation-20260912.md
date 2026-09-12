# HiThink（同花顺官方）API 实测与迁移清单（2026-09-12 凌晨）

> 来源：github.com/HiThink-Tech/Financial-API（官方维护，3.1k star，活跃）。
> Key 已存 /opt/data/.env `HITHINK_API_KEY`。限流：响应头 X-RateLimit-Limit: 20（窗口极短，连发5次 Remaining 不掉），超限返 4001 指数退避≤3 次。无文档化日额度。

## 端点实测结论

| 能力 | 实测 | 判决 |
|---|---|---|
| 行情快照（全市场分页） | ✅ 200 可用 | 可作 hq.sinajs 备用通道 |
| 历史K线（≤10年，adjust=forward/backward） | 文档确认 | 可交叉验证 baostock 缓存 |
| 涨停/跌停/炸板池（按交易日） | ✅ 但**参数要 `date_ms` 毫秒戳**（date 字符串返回空！）；实证映射：**date_ms = 交易日 16:00 BJT（收盘时刻）**（9/11池40只与自家涨停交集38/40内容级验证）；size≤200 需分页 | 池子历史回填+每日对账可用 |
| 连板天梯 | 近 30 交易日 | 周期仪晋级率的官方源 |
| **龙虎榜** | ✅ 参数用 `date` 字符串（与池子相反！），**深度仅1年**（"date must be within one year"），分 all/org/hot_money，带 concept_list | 近1年席位分析可用；8年回测不行 |
| **个股异动原因**（当日全市场） | ✅ | 催化剂定位自动化 |
| 集合竞价 | ⚠️ **只有快照（live/final），无历史端点** | "竞价无历史"欠账**销不了**，只能靠自家 9:26 cron 向前积累 |
| 板块/概念成分 | ✅ 走同花顺指数 catalog + constituents（`/api/a-share-index/...`）；龙虎榜个股也带 concept_list | **板块概念群聚合欠账可销** |
| market-dumps（全市场 Parquet） | 未实测 | 下次全量重建底座的首选通道 |

## 迁移优先级（爬虫→官方源）

1. **每日涨停/跌停/炸板池落盘**（regime 宽度+打板溢价的对账源）——新建 cron 19:05 BJT（等官方池就绪）
2. **龙虎榜日更落盘**（向前积累，1年深度限制倒逼我们自建历史）
3. **板块成分快照**（周更，销"概念群聚合"欠账）
4. 竞价快照：维持自家 9:26 cron 积累，HiThink 无历史可补
5. market-dumps 评估：下次底座重建时用

## 已入库的坑

- 池子用 `date_ms`（**交易日 16:00 BJT 收盘时刻的毫秒戳**，内容级实证），龙虎榜用 `date`（字符串）——同一套 API 两种日期约定，文档原话"不可互换"
- ~~最新交易日数据次日就绪~~（此结论系我误用时间戳所致，已作废——收盘后即可查）
- 龙虎榜仅 1 年深度
- 池子 size≤200（1003 越界），需分页
- 业绩预告**没有**端点（PEAD 走东财 RPT_PUBLIC_OP_PREDICT，11万条全历史，已建 data/pead_events.json）

## 已落地

- `engine/hithink_daily.py` + cron `2ced2427a56e`（每交易日 20:30 BJT）：涨停/跌停/炸板池+连板天梯+龙虎榜三榜落盘 `data/hithink/<date>/`（9/11 全量 7/7 验证通过）
- PEAD 事件库：`engine/fetch_pead_events.py`，39451 条（2019-2026），增量式
