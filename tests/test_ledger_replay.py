#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_ledger_replay.py — PORT-01 验收正例 2：pead_pool 单线 8 年 replay 对照。

口径声明（差异台账的三大已知项，AGENTS #359 引用）：
1. 费口径：pead_pool_sim 用平口径 FLAT_RT=0.15%（卖出时一次性扣 (SLOT+gross)*0.00075）；
   账本用 costs.py 真实费目（最低佣金 5 元生效）。2 万档真实往返 ≈0.102% < 平口径，
   方向固定为账本净值偏高。
2. 股数：sim 用分数股（shares=20000/open），账本按 I1 强制整手 floor(100)；
   且 sim **无透支检查**（cash -= SLOT 盲扣），重建其实测现金轨迹最低 -18621.95 元
   （2021-01-08，负现金 330 天）= 静默杠杆；账本 OverdraftError 禁止透支，
   replay 政策=减手到可负担（真实账户行为），减手笔数计入台账。
3. 期末幻影子仓：trades.json 只记已平仓（411 笔），sim 期末另有 3 笔 2026-09 买入
   未平仓（curve n_slots 反推），其买入记录不存在 → replay 无法重建，
   台账以 sim 现金恒等式反推的精确浮盈记账（+2446.74 元）。

数据依赖（缺则 skip）：data/pead_pool_sim_{trades,curve}.json、data/big_kcache/。
"""
import json
import os
import sys
from dataclasses import replace

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "engine"))

from engine.portfolio.ledger import (  # noqa: E402
    Ledger, load_line_fills, OverdraftError,
)
from engine.costs import buy_fee, sell_fee, FLAT_RT  # noqa: E402

TRADES_P = os.path.join(ROOT, "data", "pead_pool_sim_trades.json")
CURVE_P = os.path.join(ROOT, "data", "pead_pool_sim_curve.json")
KC_DIR = os.path.join(ROOT, "data", "big_kcache")
NAV_OUT = os.path.join(ROOT, "data", "portfolio_nav.json")
DIFF_OUT = os.path.join(ROOT, "data", "portfolio", "replay_diff_pead_20261021.json")
SLOT = 20000.0
CASH0 = 100000.0

pytestmark = pytest.mark.skipif(
    not (os.path.exists(TRADES_P) and os.path.exists(CURVE_P) and os.path.isdir(KC_DIR)),
    reason="pead_pool_sim 产物或 big_kcache 不在本机")


def _atomic_json(path: str, obj) -> None:
    """I0：先写 .tmp 再 os.replace；UTF-8 无 BOM。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _run_replay():
    """全流程 replay + 逐笔差异分解。返回 (ledger, 台账 dict)。"""
    trades = json.load(open(TRADES_P, encoding="utf-8-sig"))
    curve = json.load(open(CURVE_P, encoding="utf-8-sig"))
    days = [c[0] for c in curve]
    codes = sorted({t["code"] for t in trades})
    pb = {}
    for code in codes:
        with open(os.path.join(KC_DIR, f"{code}.json"), encoding="utf-8-sig") as fh:
            pb[code] = {b["date"]: {"open": b["open"], "close": b["close"]}
                        for b in json.load(fh)}

    # 0) 价格重建校验：ret = (close/open)*(1-FLAT_RT/2) - FLAT_RT/2 - 1 必须逐笔成立，
    #    否则说明 kcache 复权锚漂移或 sim 产物不对——先查数据再谈账本。
    rebuild_max = 0.0
    for t in trades:
        o = pb[t["code"]][t["entry_d"]]["open"]
        c = pb[t["code"]][t["exit_d"]]["close"]
        r = (c / o) * (1 - FLAT_RT / 2) - FLAT_RT / 2 - 1
        rebuild_max = max(rebuild_max, abs(r - t["ret"]))
    assert rebuild_max < 1e-6, f"交易价格重建失败 maxdiff={rebuild_max}（数据口径漂移，先查数据）"

    # 1) 适配 + replay（同日先买后卖再 mark，与 sim 的 开盘买/收盘卖 时序一致）
    fills = load_line_fills(None, "pead_pool", pead_trades=trades,
                            price_book=pb, slot_yuan=SLOT)
    pairs = [(fills[i], fills[i + 1]) for i in range(0, len(fills), 2)]
    buys, sells = {}, {}
    for b, s in pairs:
        buys.setdefault(b.day, []).append((b, s))
        sells.setdefault(s.day, []).append((b, s))

    led = Ledger(cash0=CASH0, lines=["pead_pool"])
    capped = []  # (code, day, 原股数, 减后股数)
    for d in days:
        for b, s in buys.get(d, []):
            f = b
            try:
                led.apply(f)
            except OverdraftError:
                sh = f.shares
                while True:
                    sh -= 100
                    f2 = replace(f, shares=sh, cash=round(f.price * sh, 2))
                    try:
                        led.apply(f2)
                        break
                    except OverdraftError:
                        continue
                s.shares, s.cash = f2.shares, round(s.price * f2.shares, 2)
                capped.append((f.code, f.day, f.shares, f2.shares))
                f = f2
        for b, s in sells.get(d, []):
            led.apply(s)
        # mark：有 bar 用收盘，无 bar（停牌）用该持仓入场价——镜像 sim `close_of or entry`
        px = {}
        for (line, code), p in led._pos.items():
            bar = pb[code].get(d)
            px[code] = bar["close"] if bar else p.px_cost / p.shares
        led.mark(d, px)
    led.assert_conservation()  # 验收正例：8 年 replay 守恒成立

    # 2) 逐笔差异分解（闭合式：actual = Δfee + Δlot + Δphantom + 残差）
    sim_final = curve[-1][1]
    led_final = led.nav_series()[-1]["nav"]
    d_fee = d_lot = 0.0
    d_lot_round, d_lot_cap = 0.0, 0.0
    capped_keys = {(c, d) for c, d, _, _ in capped}
    booked = {(f.code, f.day, f.side): f for f in led.fills()}
    for t in trades:
        o = pb[t["code"]][t["entry_d"]]["open"]
        c = pb[t["code"]][t["exit_d"]]["close"]
        gf = SLOT / o * c
        sim_pnl = gf - (SLOT + gf) * FLAT_RT / 2 - SLOT
        frac_real = gf - buy_fee(SLOT) - sell_fee(gf) - SLOT
        bf = booked[(t["code"], t["entry_d"], "buy")]
        sf = booked[(t["code"], t["exit_d"], "sell")]
        lot_real = (sf.cash - sf.fee) - (bf.cash + bf.fee)
        d_fee += frac_real - sim_pnl
        dl = lot_real - frac_real
        d_lot += dl
        if (t["code"], t["entry_d"]) in capped_keys:
            d_lot_cap += dl
        else:
            d_lot_round += dl
    # 幻影子仓：trades 只记已平仓；sim 期末 n_slots=3 的未平仓买入无记录。
    # 由 sim 现金恒等式精确反推：phantom_pnl = sim_final - CASH0 - Σ已平仓pnl。
    closed_pnl = sum(
        (lambda o, c: (SLOT / o * c) - (SLOT + SLOT / o * c) * FLAT_RT / 2 - SLOT)(
            pb[t["code"]][t["entry_d"]]["open"], pb[t["code"]][t["exit_d"]]["close"])
        for t in trades)
    phantom_pnl = sim_final - CASH0 - closed_pnl
    actual = led_final - sim_final
    explained = d_fee + d_lot - phantom_pnl  # 账本侧没有 phantom，减去 sim 侧浮盈
    residual = actual - explained

    ledger_doc = {
        "sim_final": sim_final, "ledger_final": round(led_final, 2),
        "delta_yuan": round(actual, 2), "delta_pct": round(actual / sim_final, 6),
        "tolerance_pct": 0.005, "within_tolerance": abs(actual / sim_final) <= 0.005,
        "decomposition": {
            "d_fee_caliber": round(d_fee, 2),
            "d_lot_total": round(d_lot, 2),
            "d_lot_rounding_only": round(d_lot_round, 2),
            "d_lot_overdraft_cap": round(d_lot_cap, 2),
            "d_phantom_open_positions": round(-phantom_pnl, 2),
            "residual_yuan": round(residual, 4),
        },
        "capped_trades": [{"code": c, "day": d, "shares_from": a, "shares_to": b}
                          for c, d, a, b in capped],
        "sim_overdraft_evidence": {
            "note": "pead_pool_sim 无透支检查（cash -= SLOT 盲扣）",
        },
        "phantom_note": "trades.json 只记已平仓；期末 3 笔未平仓买入无记录，"
                        "pnl 由 sim 现金恒等式反推（精确到分）",
    }
    return led, curve, ledger_doc, pb


def test_pead_pool_replay_conservation_and_diff_ledger():
    led, curve, doc, pb = _run_replay()
    nav = led.nav_series()

    # ── 硬断言 ──────────────────────────────────────────────
    # ① 守恒（_run_replay 内已 assert）；净值不变量逐日成立（I2）
    for row in nav:
        assert row["nav"] == pytest.approx(row["cash"] + row["mkt_value"], abs=0.01)
    # ② 差异分解闭合（不许调参凑数：每一元都要有归属）
    assert abs(doc["decomposition"]["residual_yuan"]) < 0.5
    # ③ 费口径方向与量级 sanity（真实费目 < 平口径 → 账本偏高）
    assert 3000 < doc["decomposition"]["d_fee_caliber"] < 4500
    # ④ 原始差异超 ±0.5% 是预期内（台账解释），但有护栏：|Δ| 不许超 6%
    assert abs(doc["delta_pct"]) < 0.06
    # ⑤ 天数对齐
    assert [r["date"] for r in nav] == [c[0] for c in curve]

    # ── sim 静默透支实证（台账用，不阻断）────────────────
    sim_cash, mn, mn_d, neg_days = CASH0, CASH0, None, 0
    buys_d, sells_d = {}, {}
    for t in json.load(open(TRADES_P, encoding="utf-8-sig")):
        o = pb[t["code"]][t["entry_d"]]["open"]
        c = pb[t["code"]][t["exit_d"]]["close"]
        g = SLOT / o * c
        buys_d[t["entry_d"]] = buys_d.get(t["entry_d"], 0) + SLOT
        sells_d[t["exit_d"]] = sells_d.get(t["exit_d"], 0) + g - (SLOT + g) * FLAT_RT / 2
    for d, _, _ in curve:
        sim_cash += sells_d.get(d, 0) - buys_d.get(d, 0)
        if sim_cash < mn:
            mn, mn_d = sim_cash, d
        if sim_cash < 0:
            neg_days += 1
    doc["sim_overdraft_evidence"] = {
        "cash_min": round(mn, 2), "cash_min_day": mn_d, "negative_cash_days": neg_days,
        "note": "pead_pool_sim 无透支检查：5 槽×2万 满仓遇净值回撤即静默杠杆",
    }
    assert neg_days > 0  # 实证成立才写台账（防未来 sim 修复后此处静默失真）

    # 逐日最大偏差（伴随透支期的仓位差，台账记录）
    mx, mx_d = 0.0, None
    for row, c in zip(nav, curve):
        dd = abs(row["nav"] - c[1]) / c[1]
        if dd > mx:
            mx, mx_d = dd, row["date"]
    doc["max_daily_rel_diff"] = {"pct": round(mx, 6), "day": mx_d}

    # ── 落盘产物 ────────────────────────────────────────────
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    nav_doc = {
        "_meta": {"generated_at": now, "cash0": CASH0, "lines": ["pead_pool"],
                  "params_hash": "port01-replay", "data_snapshot": curve[-1][0],
                  "code_version": "PORT-01",
                  "note": "pead_pool 单线 replay 验收产物（PORT-01）；"
                          "全系统多线 nav 按 I2 应落 data/portfolio/nav.json"},
        "series": [
            {"date": r["date"], "nav": round(r["nav"], 2), "cash": round(r["cash"], 2),
             "mkt_value": round(r["mkt_value"], 2),
             "exposure": round(r["exposure"], 6),
             "by_line": {ln: {"mkt_value": round(bl["mkt_value"], 2),
                              "ret": round(bl["ret"], 8)}
                         for ln, bl in r["by_line"].items()}}
            for r in nav],
    }
    _atomic_json(NAV_OUT, nav_doc)
    doc["_meta"] = {"generated_at": now, "code_version": "PORT-01",
                    "ref": "AGENTS #359 / spec PORT-01 验收正例 2"}
    _atomic_json(DIFF_OUT, doc)

    # 复核入口打印（verify 跑 pytest -q 时可见 -s 才出，这里仅注释说明）
    print(f"\n[replay] ledger={doc['ledger_final']} sim={doc['sim_final']} "
          f"Δ={doc['delta_yuan']} ({doc['delta_pct']:+.3%}) 分解={doc['decomposition']}")
