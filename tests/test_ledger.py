#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_ledger.py — PORT-01 统一组合账本验收测试（spec 正反例）。

运行：cd /opt/data/fenjue && .venv/bin/python -m pytest tests/test_ledger.py -q
"""
import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "engine"))

from engine.portfolio.ledger import (  # noqa: E402
    Fill, Ledger,
    OverdraftError, DuplicateFillError, FeeInjectionError, ConservationError,
)
from engine.costs import buy_fee, sell_fee, dividend_tax  # noqa: E402


def buy(day, code="600000", price=10.0, shares=1000, line="L1"):
    return Fill(line=line, code=code, side="buy", day=day,
                price=price, shares=shares, cash=round(price * shares, 2))


def sell(day, code="600000", price=10.0, shares=1000, line="L1"):
    return Fill(line=line, code=code, side="sell", day=day,
                price=price, shares=shares, cash=round(price * shares, 2))


# ── Task 1：核心记账 + 守恒 + 反例 ─────────────────────────────────────

def test_buy_deducts_cash_and_fee():
    led = Ledger(cash0=100000.0, lines=["L1"])
    led.apply(buy("2026-01-05"))
    want = 100000.0 - 10000.0 - buy_fee(10000.0)
    assert led.cash() == pytest.approx(want, abs=1e-9)


def test_sell_adds_cash_minus_fee_tax():
    led = Ledger(cash0=100000.0, lines=["L1"])
    led.apply(buy("2026-01-05"))
    led.apply(sell("2026-01-08", price=11.0))
    amt = 11.0 * 1000
    want = 100000.0 - 10000.0 - buy_fee(10000.0) + amt - sell_fee(amt) - 0.0
    assert led.cash() == pytest.approx(want, abs=1e-9)
    assert led.positions() == {}  # 全部卖出后无持仓


def test_dividend_adds_cash_minus_tax():
    # 守恒第三分支：分红加 cash-tax。持有 <1 个月 → 红利税 20%（costs.py 日历月口径）
    led = Ledger(cash0=100000.0, lines=["L1"])
    led.apply(buy("2026-01-05"))
    led.apply(Fill(line="L1", code="600000", side="div", day="2026-01-20",
                   price=0.10, shares=1000, cash=100.0))
    tax = dividend_tax("2026-01-05", "2026-01-20", 100.0)
    want = 100000.0 - 10000.0 - buy_fee(10000.0) + 100.0 - tax
    assert tax == pytest.approx(20.0)
    assert led.cash() == pytest.approx(want, abs=1e-9)
    led.assert_conservation()


def test_conservation_passes_on_simple_sequence():
    led = Ledger(cash0=100000.0, lines=["L1"])
    led.apply(buy("2026-01-05", code="600000", price=10.0, shares=1000))
    led.apply(buy("2026-01-06", code="000001", price=20.0, shares=500))
    led.apply(sell("2026-01-09", code="600000", price=10.5, shares=1000))
    led.assert_conservation()  # 不 raise 即过


def test_conservation_detects_tampering():
    # 反例：现金被场外篡改（#249 同类账房 bug 的探针）→ assert_conservation 必须 raise
    led = Ledger(cash0=100000.0, lines=["L1"])
    led.apply(buy("2026-01-05"))
    led._cash += 1.0  # 模拟记账路径之外的现金漂移
    with pytest.raises(ConservationError):
        led.assert_conservation()


def test_overdraft_raises():
    led = Ledger(cash0=5000.0, lines=["L1"])
    with pytest.raises(OverdraftError):
        led.apply(buy("2026-01-05", price=10.0, shares=1000))  # 需 10000+费 > 5000


def test_overdraft_via_fee_raises():
    # 成交金额刚好等于现金，但费用使总支出透支 → 仍须 raise（费也算进透支判定）
    led = Ledger(cash0=10000.0, lines=["L1"])
    with pytest.raises(OverdraftError):
        led.apply(buy("2026-01-05", price=10.0, shares=1000))  # 10000 + fee > 10000


def test_failed_apply_leaves_no_trace():
    # 反例回归：透支 raise 后同键重试必须能成功（失败的 apply 不许占用重复检测键位）
    led = Ledger(cash0=10000.0, lines=["L1"])
    with pytest.raises(OverdraftError):
        led.apply(buy("2026-01-05", price=10.0, shares=1000))
    led.apply(buy("2026-01-05", price=10.0, shares=900))  # 同 (line,code,day,side) 减手重试
    assert led.positions()["600000"]["shares"] == 900
    led.assert_conservation()


def test_duplicate_fill_raises():
    led = Ledger(cash0=100000.0, lines=["L1"])
    led.apply(buy("2026-01-05"))
    with pytest.raises(DuplicateFillError):
        led.apply(buy("2026-01-05"))  # 同 (line, code, day, side)


def test_duplicate_guard_is_per_line():
    # 不同线同日同码同向 = 合法（跨线合并场景），不许误杀
    led = Ledger(cash0=100000.0, lines=["L1", "L2"])
    led.apply(buy("2026-01-05", line="L1"))
    led.apply(buy("2026-01-05", line="L2"))
    led.assert_conservation()


def test_shares_must_be_100_multiple():
    led = Ledger(cash0=100000.0, lines=["L1"])
    with pytest.raises(ValueError):
        led.apply(Fill(line="L1", code="600000", side="buy", day="2026-01-05",
                       price=10.0, shares=150, cash=1500.0))


def test_oversell_raises():
    led = Ledger(cash0=100000.0, lines=["L1"])
    led.apply(buy("2026-01-05", shares=1000))
    with pytest.raises(ValueError):
        led.apply(sell("2026-01-08", shares=1100))  # 卖出超过持仓


def test_fee_injection_rejected():
    # 费用只能由账本经 costs.py 计算（D-07/C6.1）：外部传入非零 fee/tax 必须拒绝
    led = Ledger(cash0=100000.0, lines=["L1"])
    with pytest.raises(FeeInjectionError):
        led.apply(Fill(line="L1", code="600000", side="buy", day="2026-01-05",
                       price=10.0, shares=1000, cash=10000.0, fee=1.0))


def test_fee_matches_costs_py():
    # 对拍：账本记下的 fee 与直接调 costs.py 同参数输出逐分相等
    led = Ledger(cash0=100000.0, lines=["L1"])
    led.apply(buy("2026-01-05", price=9.53, shares=2100))
    led.apply(sell("2026-01-12", price=9.88, shares=2100))
    booked = led.fills()
    assert booked[0].fee == pytest.approx(buy_fee(9.53 * 2100), abs=1e-9)
    assert booked[0].tax == 0.0
    assert booked[1].fee == pytest.approx(sell_fee(9.88 * 2100), abs=1e-9)
    led.assert_conservation()


# ── Task 2：mark-to-market 与净值序列 ──────────────────────────────────

def test_nav_series_columns():
    led = Ledger(cash0=100000.0, lines=["L1"])
    led.apply(buy("2026-01-05"))
    led.mark("2026-01-05", {"600000": 10.0})
    led.mark("2026-01-06", {"600000": 10.5})
    series = led.nav_series()
    assert len(series) == 2
    for row in series:
        for k in ("date", "nav", "cash", "mkt_value", "exposure"):
            assert k in row, f"nav_series 缺键 {k}"
    assert series[0]["date"] == "2026-01-05" and series[1]["date"] == "2026-01-06"


def test_mark_updates_mkt_value():
    led = Ledger(cash0=100000.0, lines=["L1"])
    led.apply(buy("2026-01-05", price=10.0, shares=1000))
    led.mark("2026-01-05", {"600000": 10.0})
    led.mark("2026-01-06", {"600000": 12.0})
    s = led.nav_series()
    assert s[0]["mkt_value"] == pytest.approx(10000.0)
    assert s[1]["mkt_value"] == pytest.approx(12000.0)
    # nav = cash + mkt_value；exposure = mkt_value / nav
    assert s[1]["nav"] == pytest.approx(s[1]["cash"] + 12000.0)
    assert s[1]["exposure"] == pytest.approx(12000.0 / s[1]["nav"])
    # nav 不变量：nav == cash + mkt_value（I2）
    for row in s:
        assert row["nav"] == pytest.approx(row["cash"] + row["mkt_value"], abs=0.01)


def test_mark_missing_price_falls_back_to_cost():
    # 停牌日无报价 → 用成本价兜底（与 pead_pool_sim 的 `close_of or entry` 同义的保守口径）
    led = Ledger(cash0=100000.0, lines=["L1"])
    led.apply(buy("2026-01-05", price=10.0, shares=1000))
    led.mark("2026-01-06", {})  # 无报价
    row = led.nav_series()[0]
    assert row["mkt_value"] == pytest.approx(10000.0)


def test_contributions_split_by_line():
    # 两线各一笔完整往返，贡献分线且合计=总盈亏（守恒一致）
    led = Ledger(cash0=100000.0, lines=["L1", "L2"])
    led.apply(buy("2026-01-05", code="600000", price=10.0, shares=1000, line="L1"))
    led.apply(buy("2026-01-05", code="000001", price=20.0, shares=500, line="L2"))
    led.apply(sell("2026-01-12", code="600000", price=11.0, shares=1000, line="L1"))
    led.apply(sell("2026-01-12", code="000001", price=19.0, shares=500, line="L2"))
    led.mark("2026-01-12", {})
    c = led.contributions()
    assert set(c) == {"L1", "L2"}
    l1 = 11000.0 - sell_fee(11000.0) - 10000.0 - buy_fee(10000.0)
    l2 = 9500.0 - sell_fee(9500.0) - 10000.0 - buy_fee(10000.0)
    assert c["L1"]["yuan"] == pytest.approx(l1)
    assert c["L2"]["yuan"] == pytest.approx(l2)
    assert c["L1"]["pct"] == pytest.approx(l1 / 100000.0)
    # 合计贡献 = 期末净值 - 初始资金
    assert c["L1"]["yuan"] + c["L2"]["yuan"] == pytest.approx(led.cash() - 100000.0)
    led.assert_conservation()


# ── Task 3：跨线喂入与合并 ─────────────────────────────────────────────

def test_load_line_fills_roundtrip(tmp_path):
    from engine.portfolio.ledger import load_line_fills
    led = Ledger(cash0=100000.0, lines=["L1"])
    led.apply(buy("2026-01-05", code="600000", price=10.0, shares=1000))
    led.apply(sell("2026-01-12", code="600000", price=11.0, shares=1000))
    # 落盘 jsonl（I1 字段；fee/tax 是账本输出值）
    p = tmp_path / "fills_L1.jsonl"
    import json as _json
    with open(p, "w", encoding="utf-8") as fh:  # I0：写不带 BOM
        for f in led.fills():
            fh.write(_json.dumps(vars(f), ensure_ascii=False) + "\n")
    # 读回：fee/tax 被丢弃（真源是 costs.py，由账本重算），其余字段原样
    fills = load_line_fills(str(p), "L1")
    assert len(fills) == 2
    assert fills[0].side == "buy" and fills[0].fee == 0.0 and fills[0].tax == 0.0
    assert fills[0].cash == pytest.approx(10000.0) and fills[0].shares == 1000
    # 重新入账后与原账本逐分一致
    led2 = Ledger(cash0=100000.0, lines=["L1"])
    for f in fills:
        led2.apply(f)
    assert led2.cash() == pytest.approx(led.cash(), abs=1e-9)
    assert [f.fee for f in led2.fills()] == [pytest.approx(f.fee, abs=1e-9) for f in led.fills()]
    led2.assert_conservation()


def test_load_line_fills_pead_branch():
    # pead_pool_sim 真实输出格式适配：trades.json 只有 code/entry_d/exit_d/ret/why/days，
    # 无价格——必须配 price_book（调用方给，不硬编码路径），重建 buy@entry_d开盘 /
    # sell@exit_d收盘 两笔，股数=floor(slot/开盘价/100)*100
    from engine.portfolio.ledger import load_line_fills
    import json as _json
    fx = _json.load(open(os.path.join(os.path.dirname(__file__), "fixtures",
                                      "pead_pool_sample.json"),
                         encoding="utf-8-sig"))
    fills = load_line_fills(None, "pead_pool", pead_trades=fx["trades"],
                            price_book=fx["price_book"], slot_yuan=20000.0)
    assert len(fills) == 2 * len(fx["trades"])
    t0, pb = fx["trades"][0], fx["price_book"]
    b, s = fills[0], fills[1]
    assert b.side == "buy" and b.day == t0["entry_d"] and b.code == t0["code"]
    assert b.price == pytest.approx(pb[t0["code"]][t0["entry_d"]]["open"])
    assert b.shares == int(20000.0 / b.price) // 100 * 100
    assert b.cash == pytest.approx(b.price * b.shares)
    assert s.side == "sell" and s.day == t0["exit_d"] and s.shares == b.shares
    assert s.price == pytest.approx(pb[t0["code"]][t0["exit_d"]]["close"])
    # 缺 price_book 必须 raise（不许猜价）
    with pytest.raises(ValueError):
        load_line_fills(None, "pead_pool", pead_trades=fx["trades"], slot_yuan=20000.0)


def test_combine_conservation(tmp_path):
    from engine.portfolio.ledger import combine
    import json as _json
    # 两条线各一份 jsonl
    pa = tmp_path / "fills_A.jsonl"
    pb = tmp_path / "fills_B.jsonl"
    pa.write_text(_json.dumps({"line": "A", "code": "600000", "side": "buy",
                               "day": "2026-01-05", "price": 10.0, "shares": 1000,
                               "cash": 10000.0, "fee": 0, "tax": 0, "note": ""}) + "\n",
                  encoding="utf-8")
    pb.write_text(_json.dumps({"line": "B", "code": "000001", "side": "buy",
                               "day": "2026-01-06", "price": 20.0, "shares": 500,
                               "cash": 10000.0, "fee": 0, "tax": 0, "note": ""}) + "\n",
                  encoding="utf-8")
    led = combine({"A": str(pa), "B": str(pb)}, cash0=40000.0, slot_yuan=20000.0)
    led.mark("2026-01-06", {"600000": 10.0, "000001": 20.0})
    led.assert_conservation()
    c = led.contributions()
    # pct 分母 = 各线 slot_yuan（20000），不是总 cash0
    assert c["A"]["pct"] == pytest.approx(c["A"]["yuan"] / 20000.0)
    assert set(led.positions()) == {"600000", "000001"}
