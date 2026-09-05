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
