# 数据破壁·公开端点清单与实测（2026-10-15，卡 t_fd5a5b97）

四类「目前无法研究」维度的公开端点逆向结果。全部为免费公开端点（akshare 同款），无 VIP/登录态/付费反代。
**fetcher 已落地 `engine/datawall_fetcher.py`（PIT 安全缓存 `data/research/<kind>/<YYYY-MM-DD>.json`）。**

## 网络面结论（先读，影响所有东财端点）

| 事实 | 实测 |
|---|---|
| 本容器出网走 Clash 代理（192.168.2.15:7890），但**代理节点 IP 被东财风控**：push2his 经代理全灭，直连同灭（RST） | 2026-10-15 curl/python 双路 5 子域全 ConnectionError |
| **东财 push2 / push2ex / datacenter-web 直连可用**（必须 `trust_env=False` 绕开代理） | 全部实测 200 |
| 东财 **push2his（分钟K线/历史trends2）本网络不可用**（直连+代理+1./33./72./92. 编号子域全灭）——akshare 分钟历史接口在此网络是死路 | 台账旧记「push2his 全封」仍然成立 |
| 腾讯 gtimg 直连可用（NO_PROXY 已含）；**web.ifzq.gtimg.cn 会 301 到 web3.ifzq.gtimg.cn（不通），必须用 `ifzq.gtimg.cn` 直连主机** | 实测 |

## ① 历史竞价（9:25 量/价/强度）—— verdict: unlockable（配额限速）

| 端点 | URL 模式 | 历史深度 | 限流 |
|---|---|---|---|
| **问财 iwencai（主力）** | CLI `hithink-insresearch-query` → `iwencai.com/unifiedwap/chat`，NL 查询「YYYY年M月D日涨停股的集合竞价」/「…集合竞价成交金额排名前N」 | **实测 2024-06 任意日可查**（更深未穷举，问财口径无明确截止） | 免费 key ~100-150 次/日（滚动 24h），耗尽返回纯文本「您今天的次数已用完」→ fetcher 抛 QuotaExhausted 不毒缓存 |
| 东财 push2 trends2（当日补充） | `https://push2.eastmoney.com/api/qt/stock/trends2/get?secid={mkt}.{code}&ndays=1&iscr=1` | **仅当日**；竞价段 09:15-09:25 为虚拟撮合价（量 0），**09:26 bar = 竞价撮合量/价** | 路径级风控不稳定（时通时断），只作补充 |
| 腾讯 minute（当日补充） | `https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=sh600000` | 仅当日；**09:30 首 bar = 竞价成交量/价** | 稳 |

**字段校准证据（浦发银行 600000，2026-10-15）**：问财竞价量 565,000 股 = 东财 09:26 bar 5,650 手 = 腾讯 09:30 bar 5,650 手，三源一致；竞价匹配价 9.65 = 当日开盘价。
**字段清单（问财，按日键后缀 [YYYYMMDD]）**：竞价匹配价/竞价量/竞价金额(或匹配金额)/竞价涨幅/竞价未匹配量/竞价未匹配金额/竞价异动类型/竞价评级；涨停宇宙查询额外带 **涨停封单额/封成比/封流比/开板次数/首次+最终涨停时间/几天几板/涨停原因**。
**覆盖验证**：「10-14 涨停股的集合竞价」39 只与 HiThink 涨停池 39/39 全对齐。
**用法边界**：适合「目标宇宙 × 历史日」回填（每日 1-3 发，涨停池/信号名单级），**不适合全市场×全历史**（5000 只×N 日远超日配额）。历史回填按日断点续跑，配额守望复用 gold_monthly 模式。

## ② 分时/分钟历史—— verdict: unlockable（5 分钟级及以上 ≥1 年；1 分钟级仅近日）

| 端点 | URL 模式 | 历史深度（600000 实测） | 限流 |
|---|---|---|---|
| **baostock（主力，≥1年）** | `query_history_k_data_plus(frequency="5/15/30/60", adjustflag="3")`（/opt/data/python-libs，**禁双进程**） | **2020-01-02 起≈6 年**（5 分 78,816 根 / 30 分 13,136 根） | 温柔模式 1s/只（台账纪律） |
| 新浪 getKLineData（近端快拉） | `https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData?symbol=sh600000&scale={5,15,30,60}&ma=no&datalen=1970` | 5分≈2月(08-11起)、15分≈6月(04-13起)、**30分≈1年(2025-10-09起)**、60分≈2年(2024-09-27起)；datalen>~2000 返回空 | 温和 |
| 腾讯 mkline（补充） | `https://ifzq.gtimg.cn/appstock/app/kline/mkline?param=sh600000,{m1,m5,m15,m30,m60},,{count}` | m1≈3 交易日(800)、m5≈1 月(800)；**count>800 只回 320 根** | 温和 |

**字段校准**：baostock vs 新浪同刻 5 分 bar（2026-10-15 09:35）：开/低/收一致（9.65/9.58/9.59），高差 3 分（9.66 vs 9.69）、量差 0.3%——厂商聚合口径差，**同一序列别跨源拼接**。
**结论**：「分钟级、至少近一年」由 baostock（5 分起 6 年）+ 新浪 30 分（1 年）双源满足；1 分钟级免费源只有近 3 日（腾讯）——分钟级择时研究可做，tick/1 分微观结构不做。

## ③ 涨停板封单—— verdict: unlockable（准历史=日度收盘快照，2020-08 起已在库）

| 端点 | URL 模式 | 历史深度 | 限流 |
|---|---|---|---|
| **HiThink 涨停池（已在库，权威）** | `data/hithink/<date>/limit_up_pool.json`（seal_money/max_seal_money/limit_up_time/reason/continue_day_cnt） | **2020-08-03 起 1503 个交易日目录**（缺口全为法定长假，已扫描验证） | 已在库 |
| 东财 push2ex 涨停池（近端备份+对账） | `https://push2ex.eastmoney.com/getTopicZTPool?ut=…&dpt=wz.ztzt&Pageindex=0&pagesize=10000&sort=fbt:asc&date=YYYYMMDD`（**直连**） | **仅近 3-4 周**（2026-09-17 起有数，更早空池） | 15 连发全 200（~50-100ms），无感 |
| 问财（按日全字段） | 同①（封单额/封成比/封流比/开板次数随竞价查询附赠） | 任意历史日 | 配额共享 |

**字段校准证据**：东财 fund vs HiThink seal_money 同日同股 ratio 中位 1.0（10-14 全池 36 只逐分一致）；问财封单额 vs HiThink 39/39 一致；问财「封成比」原始值是**百分数**（321.9=3.219x=封单额÷成交额），fetcher 已归一小数并与东财 fund/amount 对平（3.2190661 vs 3.2191）。
**封成比**=封单额/成交额（东财 amount、问财/HiThink 可 join kcache 日成交额）。**无盘中 tick 级封单历史**（那是 L2 领域，台账已判物理缺）。

## ④ 龙虎榜席位明细—— verdict: unlockable（东财 2004 年起，深过 HiThink 20 倍）

| 端点 | URL 模式 | 历史深度 | 限流 |
|---|---|---|---|
| 个股明细 | `datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_DAILYBILLBOARD_DETAILSNEW&columns=ALL&filter=(TRADE_DATE<='D')(TRADE_DATE>='D')`（**直连**） | **2004-06-25 起 269,446 行** | 12 连发 100 行/页全 200 |
| **席位级明细** | 同上 `reportName=RPT_OPERATEDEPT_TRADE_DETAILSNEW` | **2004-06-25 起 2,188,528 行**（营业部代码/名称/买卖额/净额/上榜原因 EXPLANATION，附 D1/D2/D3/D5/D10/D20/D30 后验涨跌幅） | 同上 |

**字段校准证据（2026-10-14）**：东财 76 行 vs HiThink 73 行，代码集 68 只全交集；逐股金额完全一致（冰山冷热 000530：net 72,107,732 / buy 103,060,526 / sell 30,952,794 两源逐分相同）。
**注意**：`sortColumns` 传非法列名会**静默毒化整个响应返 0 行**（台账两融条目同款坑）——按日过滤用法不传 sortColumns。

## 死端点登记（别再试）

- 东财 push2his（kline/trends2 历史分钟）：本网络全灭，编号子域同样灭。
- 腾讯 web.ifzq.gtimg.cn：301 到不通的 web3；用 ifzq.gtimg.cn。
- 问财作全市场全历史回填：配额物理不够，不是端点问题。
- 盘中 tick 级封单/逐笔：L2 数据，免费面不存在（台账 #258 已封档）。

## 落地物

- `engine/datawall_fetcher.py`：五类 fetcher（auction_zt/auction_top/zt_pool_em/lhb_em/lhb_seats_em + 分钟三源函数），PIT 安全缓存、原子写、比率小数、_meta 锚（INTERFACES I0/I8）。
- 样本落盘（一周量级，`data/research/`）：`auction_zt/` 5 个交易日（72/48/70/39/36 只）、`zt_pool_em/` 5 日、`lhb_em/` 5 日、`lhb_seats_em/` 2 日（492/402 席位行）。
