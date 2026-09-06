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

1. ~~复权混用~~ **已销（2026-09-07 凌晨）**：2500 只 baostock 前复权重拉完成零失败，序列已重建。regime 分布几乎不变（分类鲁棒），宽度/MA 精度提升。
2. ~~回测无手续费~~ **已销**：entryexit_matrix 全量重跑已带净口径（毛-0.15%）。全市场 2019-2026 净结论：反转开盘买→次日尾盘 净+0.16%/50.1%（n=46 万）仍正；其余全负。旧 JSON 里的毛值读时先扣 0.15%。
3. ~~regime 阈值 2026 单年标定~~ **已销**：2019-2025 样本外复验完成（data/regime_oos_validation.json）。结论：结构型周期（主线/妖股）老数据有效（2021末-2022 妖股时代、2026-06 主线峰都读对）；指数型行情（2019Q1 权重牛、2020-03 急跌）不在量程内——口径边界已记录，阈值未硬调。
4. **市值是常数近似**：历史小市值占比用 2026-09-04 快照，早年大市值票当年可能还是小的。
5. ~~股息率锚牛市偏差~~ **已销（分段验证）**：2019-2022 非牛市段 买入区 50%/+1.3% vs 对照 31%/-2.8%；2023-2026 牛市段 79%/+9.3% vs 69%/+5.5%——两段买入区都跑赢对照 ~+4pp，锚的方向性穿越牛熊成立。残留警告：窗口重叠（非独立样本），幅度别当精确值。
6. **中证红利成分股是当期名单**：回测用的宇宙有指数存活者偏差（被剔除的烂票不在里面）。
7. ~~周期仪没有盘中间隔版本~~ **已补**（stock_regime_intraday.py，10:30/14:30 看门狗）。
