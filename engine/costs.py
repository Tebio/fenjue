#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine/costs.py — 税费唯一真源（TAX-01，AGENTS #287，2026-10-16）

全仓库任何「算钱」的常数与规则只许从这里取。`0.15` / `0.0015` / `COST=`
这类字面量在研究代码里出现即视为 bug（#262-C：曾散落 109 个文件）。

三部分
------
1. 真实费目 FeeSchedule（佣金/最低佣金/印花税/过户费）：
   - 佣金 0.025% 双边、单笔最低 5 元（散户主流档，账户真实费率若有出入
     改这里一处即可）；
   - 印花税 0.05% 仅卖出（2023-08-28 起减半后口径）；
   - 过户费 0.001% 双边（2022-04 起沪深统一）。
   按此口径：2 万元单往返 ≈ 0.102%；5 千元单往返 ≈ 0.252%
   （最低佣金生效，成本翻倍——#263④ 的小额单敏感性）。
2. 研究平口径常量（历史结论的兼容锚，数值冻结）：
   - FLAT_RT     = 0.0015  分数形式（`ret = exit/entry - 1 - FLAT_RT`）
   - FLAT_RT_PCT = 0.15    百分形式（`pct = (exit/entry-1)*100 - FLAT_RT_PCT`）
   ⚠️ 双口径差异（如实记录，不在本模块裁决）：多数脚本单笔净扣一次
   FLAT_RT（往返合计 0.15%），dividend_core_satellite 等少数脚本扣
   2×FLAT_RT（双边各 0.15%）。统一口径属待裁决项，迁移时逐文件保留
   原语义，对拍纪律=数字逐位一致。
   平口径 vs 真实费目：2 万单真实 ≈0.102% < 平口径 0.15%（平口径偏保守），
   5 千单真实 ≈0.252% > 平口径（平口径低估小单成本）。
   limitup_capture_t0 的 FEE_RT=0.001（佣金 0.025%×2 + 印花 0.05%，
   无最低佣金/过户费）与 FeeSchedule 在 2 万档差 0.002pp，差额来源=
   过户费双边 0.002%。
3. 红利税三档（#263③，持有期按卖出时算，股息率锚线税后口径用）：
   持有 <1 个月 20% / 1 个月~1 年 10% / ≥1 年免征。
   主 API 按日期精确算（日历月）；dividend_tax_by_days 是研究近似
   （月按 30 天），边界日请以日期版为准。

非目标：不建模滑点（执行层 recon 实测回填）；不做税筹建议（只如实计算）。
"""
from dataclasses import dataclass
from datetime import date, datetime
from calendar import monthrange

__all__ = [
    "FeeSchedule", "DEFAULT_SCHED",
    "buy_fee", "sell_fee", "roundtrip_fee", "roundtrip_cost",
    "FLAT_RT", "FLAT_RT_PCT",
    "dividend_tax_rate", "dividend_tax",
    "dividend_tax_rate_by_days", "dividend_tax_by_days",
]

# ── 2. 研究平口径（数值冻结，改=全部历史结论对不上）────────────────────
FLAT_RT = 0.0015      # 分数形式，往返净扣（多数脚本单扣一次）
FLAT_RT_PCT = 0.15    # 百分形式，等价同上


# ── 1. 真实费目 ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class FeeSchedule:
    commission_rate: float = 0.00025   # 佣金，双边
    commission_min: float = 5.0        # 单笔最低 5 元
    stamp_sell: float = 0.0005         # 印花税，仅卖出（2023-08 减半后）
    transfer_rate: float = 0.00001     # 过户费，双边（沪深统一 0.001%）


DEFAULT_SCHED = FeeSchedule()


def _check_amount(amount: float) -> None:
    if amount is None or amount <= 0:
        raise ValueError(f"amount 必须为正数, got {amount!r}")


def buy_fee(amount: float, sched: FeeSchedule = DEFAULT_SCHED) -> float:
    """买入费用（元）：佣金（保底 5 元）+ 过户费。买入无印花税。"""
    _check_amount(amount)
    return max(amount * sched.commission_rate, sched.commission_min) \
        + amount * sched.transfer_rate


def sell_fee(amount: float, sched: FeeSchedule = DEFAULT_SCHED) -> float:
    """卖出费用（元）：佣金（保底 5 元）+ 印花税 + 过户费。"""
    _check_amount(amount)
    return max(amount * sched.commission_rate, sched.commission_min) \
        + amount * sched.stamp_sell + amount * sched.transfer_rate


def roundtrip_fee(amount: float, sched: FeeSchedule = DEFAULT_SCHED) -> float:
    """等金额买+卖的费用合计（元）。近似口径：卖出额≈买入额。"""
    return buy_fee(amount, sched) + sell_fee(amount, sched)


def roundtrip_cost(amount: float, sched: FeeSchedule = DEFAULT_SCHED) -> float:
    """往返费用率 = 费用合计 / 成交额。小单被最低佣金显著抬高。"""
    _check_amount(amount)
    return roundtrip_fee(amount, sched) / amount


# ── 3. 红利税三档 ──────────────────────────────────────────────────────
def _add_months(d: date, n: int) -> date:
    """日期加 n 个日历月（月末钳制：1 月 31 日 +1 月 = 2 月末）。"""
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))


def _as_date(d) -> date:
    if isinstance(d, date):
        return d
    return datetime.strptime(str(d)[:10], "%Y-%m-%d").date()


def dividend_tax_rate(buy_date, sell_date) -> float:
    """A 股红利税率（卖出时按持有期补扣）：
    ≤1 个月（含）20% / 1 个月~1 年（含）10% / >1 年 0%。日历月口径。"""
    b, s = _as_date(buy_date), _as_date(sell_date)
    if s < b:
        raise ValueError(f"sell_date {s} 早于 buy_date {b}")
    if s <= _add_months(b, 1):
        return 0.20
    if s <= _add_months(b, 12):
        return 0.10
    return 0.0


def dividend_tax(buy_date, sell_date, gross_dividend: float) -> float:
    """持有期红利税额（元）。"""
    if gross_dividend < 0:
        raise ValueError(f"gross_dividend 不能为负, got {gross_dividend!r}")
    return gross_dividend * dividend_tax_rate(buy_date, sell_date)


def dividend_tax_rate_by_days(holding_days: int) -> float:
    """研究近似（月按 30 天）：<30 天 20% / 30-359 天 10% / ≥360 天 0。
    边界 ±2 天内的判断请改用日期版 dividend_tax_rate。"""
    if holding_days < 0:
        raise ValueError(f"holding_days 不能为负, got {holding_days!r}")
    if holding_days < 30:
        return 0.20
    if holding_days < 360:
        return 0.10
    return 0.0


def dividend_tax_by_days(holding_days: int, gross_dividend: float) -> float:
    if gross_dividend < 0:
        raise ValueError(f"gross_dividend 不能为负, got {gross_dividend!r}")
    return gross_dividend * dividend_tax_rate_by_days(holding_days)


if __name__ == "__main__":
    # 自测（对拍锚，数字变更=事故）
    assert buy_fee(20000) == 5.0 + 0.2          # 佣金恰在最低值边界 + 过户费
    assert buy_fee(5000) == 5.0 + 0.05          # 最低佣金生效
    assert abs(roundtrip_cost(20000) - 0.00102) < 1e-9
    assert abs(roundtrip_cost(5000) - 0.00252) < 1e-9
    assert dividend_tax_by_days(20, 1000) == 200
    assert dividend_tax_by_days(200, 1000) == 100
    assert dividend_tax_by_days(400, 1000) == 0
    assert dividend_tax_rate("2026-01-15", "2026-02-14") == 0.20
    assert dividend_tax_rate("2026-01-15", "2026-02-15") == 0.20  # 恰满 1 个月（含）
    assert dividend_tax_rate("2026-01-15", "2026-02-16") == 0.10
    assert dividend_tax_rate("2025-01-15", "2026-01-15") == 0.10  # 恰满 1 年（含）
    assert dividend_tax_rate("2025-01-15", "2026-01-16") == 0.0   # 超 1 年免征
    for bad in (0, -100):
        for fn in (buy_fee, sell_fee, roundtrip_cost):
            try:
                fn(bad)
                raise AssertionError("应抛 ValueError")
            except ValueError:
                pass
    print("costs.py selftest OK  "
          f"roundtrip: 2万={roundtrip_cost(20000)*100:.3f}%  "
          f"5千={roundtrip_cost(5000)*100:.3f}%  "
          f"5万={roundtrip_cost(50000)*100:.3f}%  "
          f"flat={FLAT_RT*100:.2f}%")
