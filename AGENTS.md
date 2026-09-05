# 焚诀仓库导航（AI/人类必读，防三条线混淆）

> 2026-09-06 立。本仓库存在**三条互相独立的线**，混淆它们是历史事故的高发区。

## 三条线（名字、路径、能干什么）

### 1. 短线焚诀（旧版 V2 CLI 线）— 测量对象，不是真理
- **代码**：`fenjue_fast.py`、`screen_pool.py`、`screen_pool2.py`、`build_pool.py`；CLI 在 `/opt/data/skills/fenjue-screening/`（`.venv/bin/python -m fenjue`）
- **定位**：短线候选扫描器。8 年大样本回测已证明其追高门**全周期跑输随机**（45.8%/+0.14% vs 48.3%/+0.21%，data/big_backtest.json）
- **能对它做**：修 bug（如 2026-09-06 修的 load_pool 未来函数）、加数据源、影子测量
- **不能**：把它当盈利系统直接照抄买卖

### 2. 长线焚诀（V3 评分引擎，冻结中 ~2026-10-08）— 别碰
- **代码**：`engine/scoring/`、`engine/moneyflow/`、`engine/macro_industry.py`、`engine/event_registry.py`
- **冻结纪律**：不调权重、不改公式、新因子旁路一个月再投票（详见 skills/research/fenjue）
- **新增模块一律放 `engine/` 下新文件**，禁止 import 进评分管线

### 3. 测量/操作台旁路线（2026-09-06 新建）— 只读验证 + 玩法工具
- `engine/console.py` — 板块操作台（股息率锚价格带/强度灯/明日委托单）
- `engine/dividend_universe.py` — 高股息全宇宙（中证红利∪红利低波 115 只）
- `engine/doubler.py` — 翻倍摇篮扫描 + 首板基率
- `engine/regime_meter.py` — 情绪周期仪（盘后全市场状态判定）
- `engine/entryexit_matrix.py` / `ma_cycle_test.py` / `dipbuy_backtest.py` — 回测族
- `fen_shadow.py` / `fen_shadow_universe.py` / `fen_big_backtest.py` — 影子回测编排
- **铁律**：这条线只产出「测量结论 + 工具输出」，永不改写线 1 和线 2 的规则

## 数据源速查
- 实时行情：腾讯 `qt.gtimg.cn`（PE/PB/市值在 f[39]/f[45]/f[44]）
- 历史日K：baostock（缓存 `data/big_kcache/`）、新浪 getKLineData（`data/kcache/`）
- 分红：akshare `stock_history_dividend_detail`（缓存 `data/dividend_cache.json` 7 天）
- 全主板池：a-stock MCP `localhost:8767`（挂了走 NAS `docker compose up -d` 重建，缓存 `data/main_board_codes.json` 1 天）
- 东财 push2 被代理拦，datacenter 主机可用

## Cron
- `焚诀短线影子验证`：每交易日 09:45 BJT 记影子单+回填，20 天自终止（stock_shadow_record.py）
- `焚诀盘后周期仪`：每交易日 15:40 BJT regime_meter + 打板溢价积累，10 天产出六态分类器报告后终止（stock_regime_1540.py）
- `焚诀盘中转折触发器`：每交易日 10:30/14:30 BJT，转折信号（跌停潮/启动日/晋级率崩）触发才说话，否则静默（stock_regime_intraday.py，看门狗模式）

## 已知欠账（2026-09-06 自查，诚实记账——别把半成品当完成品）

1. **复权混用（修复中）**：big_kcache 318 只 baostock 前复权 + 2873 只曾是不复权（除权跳空污染宽度/MA）。腾讯 fqkline 限流（501）后走 baostock 温柔重拉（1s/只+退避）。未重跑前，`emotion_series.json`/`regime_timeline.json` 的 5-7 月分红季数据有 ADR 偏低偏差。
2. **回测无手续费**：所有 T+1 均值是毛收益。双边 ~0.15%：反转 +0.31%→净 +0.16%（还是正）；追高 +0.14%→净负。读任何旧结论先扣成本。
3. **regime 阈值是 2026 单年标定**：链集中 22%/涨停 60 这些线是 2026 数据里量出来的，2019-2025 老数据（新浪只留 300 天）补不上 = 样本内标定风险在。baostock 全历史补齐后必须做 2019-2025 样本外复验。
4. **市值是常数近似**：历史小市值占比用 2026-09-04 快照，早年大市值票当年可能还是小的。
5. **股息率锚验证存在存活者/牛市偏差**：15 行 2020-2026 买入区 78.6%/+9.31% 的好看数字恰逢银行 2023-2026 牛市段，且 7340 个事件日期高度重叠（非独立样本）。方向可信，幅度别当真。
6. **中证红利成分股是当期名单**：回测用的宇宙有指数存活者偏差（被剔除的烂票不在里面）。
7. **周期仪没有盘中间隔版本**：现在只有盘后判定，盘中转折（如上午 10:30 跌停潮）要等收盘才知道。
