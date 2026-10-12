# SPEC · PORT-01 统一组合账本 `engine/portfolio/ledger.py`（P0，3 天）

## 目标
一条**所有线共用**的账本：逐笔记录买入/卖出/费用/税费/分红，**逐笔现金守恒**，输出净值曲线、
逐年贡献、资金占用、空仓期。它是后面所有东西（风险、归因、tearsheet、前端）的**唯一输入**。

## 非目标
- 不做资金分配决策（那是 `allocator.py`，PORT-02）
- 不做风险指标（那是 `risk/`）

## 现状证据
- 模拟/组合脚本 **14 个各写各的**：`pead_pool_sim.py`、`allocation_sim.py`、`dividend_sim.py`、`dividend_sim_unadj.py`、
  `sim_audit.py`、`sim_play.py`、`sim_regime_split.py`、`sim_retest_t1.py`、`sim_tournament.py` +
  仓库外 `/opt/data/tmp/{gold_portfolio_sim,portfolio_math,sept_50k_sim,sept_50k_sim2}.py`
- 历史事故：#249 首跑"买入漏扣现金"导致 8 年净值 8377%（账房 bug）；#253 口径漂移跑出 -184%
- `SEC-01` 之后持仓台账转入私有目录 → 账本要能从私有路径读

## 接口契约（demo，未实现）
```python
# engine/portfolio/ledger.py
from dataclasses import dataclass, field
from datetime import date

@dataclass
class Fill:
    line: str          # 线名: pead_pool / limitdown_deep / gold / rebalance ...
    code: str
    side: str          # buy / sell
    day: str           # YYYY-MM-DD
    price: float
    shares: int        # A股 100 股整数倍
    cash: float        # 成交金额 = price*shares
    fee: float         # 走 taxfee
    tax: float         # 卖出现金红利税补扣等
    note: str = ""

class Ledger:
    def __init__(self, cash0: float, lines: list[str]) -> None: ...
    def apply(self, f: Fill) -> None:
        """记一笔：校验现金守恒（cash + fee + tax 不得让余额为负），落到账本"""
    def mark(self, day: str, prices: dict[str, float]) -> None:
        """收盘 mark-to-market：更新持仓市值与净值"""
    def cash(self) -> float: ...
    def positions(self) -> dict[str, dict]: ...   # code -> {shares, cost, line}
    def nav_series(self) -> list[dict]: ...       # [{date, nav, cash, mkt_value, exposure}]
    def contributions(self) -> dict[str, float]: ...  # 线 -> 累计贡献（元 + %）
    def assert_conservation(self) -> None:
        """现金守恒：cash0 + Σ(卖出回款) - Σ(买入支出) - Σ(费用) + Σ(分红&现金收益) == 当前现金，
        允许误差 < 0.01 元；不成立直接 raise"""
```

**跨线合并入口**（把现有各线模拟输出统一喂进来）
```python
def load_line_fills(path: str, line: str) -> list[Fill]: ...
def combine(lines: list[str], cash0: float, slot_yuan: float) -> Ledger: ...
```

## 验收（正反例）
- 正例：`assert_conservation()` 在 4 线 8 年 replay 上通过（误差 < 0.01 元）
- 正例：`pead_pool` 单线 replay 的净值与 `pead_pool_sim.py` 原结果一致（±0.5%）；不一致处必须能解释（差异台账）
- 正例：`nav_series()` 输出含 `exposure`，可直接喂 `risk/` 与 tearsheet
- 反例：构造"买入金额 > 可用现金"的 Fill → 必须 `raise`，**不许静默透支**
- 反例：构造重复 `(line, code, day, side)` 的 Fill → 必须 `raise`（重复入账是历史 bug 源）
- 反例：把 `price` 传成前复权价与原始价混用 → 账本不做复权，调用方负责（在 docstring 明确：**账本一律用成交价/原始价**）

## 依赖 / 风险
- 依赖：`TAX-01`（费用与税费）
- 风险：现有模拟脚本"分红按除权日记账、到账时滞与红利税未建模" → 账本第一版先如实记账（除权日扣税），
  时滞影响列入 `CASH-01`
- 风险：**不要在账本里塞业务规则**（排序、止损）；它只记账，规则留在 `lines/`

## 工期
账本 1.5 天 + 跨线接入 1 天 + 验收与对照 0.5 天
