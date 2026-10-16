#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_costs.py — TAX-01 costs.py 验收测试（spec 正反例）。
运行：.venv/bin/python tests/test_costs.py  （无 pytest 依赖，直接断言）"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))
from costs import (  # noqa: E402
    FeeSchedule, buy_fee, sell_fee, roundtrip_cost,
    FLAT_RT, FLAT_RT_PCT,
    dividend_tax, dividend_tax_by_days, dividend_tax_rate,
)

fails = []


def check(name, got, want, tol=1e-9):
    ok = abs(got - want) <= tol if isinstance(want, float) else got == want
    if not ok:
        fails.append(f"{name}: got {got!r} want {want!r}")
    print(f"{'PASS' if ok else 'FAIL'}  {name} = {got}")


def test_costs_spec():
    # ── 正例（spec）────────────────────────────
    check("buy_fee(20000) 最低值边界", buy_fee(20000), 5.0 + 0.2)   # 佣金 5.0 + 过户费 0.2
    check("buy_fee(5000) 最低佣金生效", buy_fee(5000), 5.0 + 0.05)
    check("roundtrip_cost(20000)", roundtrip_cost(20000), 0.00102)  # 双边佣金+印花+过户
    check("roundtrip_cost(5000) 成本翻倍", roundtrip_cost(5000), 0.00252)
    check("dividend_tax_by_days(20)", dividend_tax_by_days(20, 1000), 200.0)
    check("dividend_tax_by_days(200)", dividend_tax_by_days(200, 1000), 100.0)
    check("dividend_tax_by_days(400)", dividend_tax_by_days(400, 1000), 0.0)

    # 日期版三档（含边界「含」字规则）
    check("恰满1月=20%", dividend_tax_rate("2026-01-15", "2026-02-15"), 0.20)
    check("超1月1天=10%", dividend_tax_rate("2026-01-15", "2026-02-16"), 0.10)
    check("恰满1年=10%", dividend_tax_rate("2025-01-15", "2026-01-15"), 0.10)
    check("超1年1天=0%", dividend_tax_rate("2025-01-15", "2026-01-16"), 0.0)
    check("月末钳制 1/31→2/28", dividend_tax_rate("2026-01-31", "2026-02-28"), 0.20)
    check("dividend_tax 日期版", dividend_tax("2026-01-15", "2026-06-01", 1000), 100.0)

    # 平口径兼容锚（数值冻结）
    check("FLAT_RT", FLAT_RT, 0.0015)
    check("FLAT_RT_PCT", FLAT_RT_PCT, 0.15)

    # 自定义费率表（冻结合规：不改默认，只演示可配置）
    s2 = FeeSchedule(commission_rate=0.0003, commission_min=5.0)
    check("自定义佣金率", buy_fee(100000, s2), 30.0 + 1.0)

    # ── 反例 ───────────────────────────────────
    for fn_name, fn, args in [
        ("buy_fee(0)", buy_fee, (0,)),
        ("buy_fee(-1)", buy_fee, (-1,)),
        ("sell_fee(0)", sell_fee, (0,)),
        ("roundtrip_cost(-5)", roundtrip_cost, (-5,)),
        ("dividend_tax 负分红", dividend_tax, ("2026-01-01", "2026-02-01", -1)),
        ("dividend_tax 卖早于买", dividend_tax, ("2026-06-01", "2026-01-01", 100)),
    ]:
        try:
            fn(*args)
            fails.append(f"{fn_name}: 未抛 ValueError")
            print(f"FAIL  {fn_name} 未抛错")
        except ValueError:
            print(f"PASS  {fn_name} 抛 ValueError")

    # 对照（spec）：limitup_capture_t0 的 FEE_RT=0.001 vs 本模块 2 万档，
    # 差额 = 过户费双边 0.002pp + 最低佣金边界（2 万佣金恰 5 元无差额）
    diff_pp = (roundtrip_cost(20000) - 0.001) * 10000
    print(f"INFO  2万档 roundtrip_cost - FEE_RT(0.001) = {diff_pp:.3f}pp（=过户费双边，已解释）")

    assert not fails, f"{len(fails)} 项失败: {fails}"


if __name__ == "__main__":
    test_costs_spec()
    print("\nALL PASS")
