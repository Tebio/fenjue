#!/usr/bin/env python3
"""engine/ma_cycle_test.py — 周K/月K MA5 站上测试：银行 vs 科技 (2026-09-06)

大佬方法论验证：「月K/周K站上5日线才有大行情」对银行股有效？科技股波动大 MACD/均线没参考价值？
设计：日K聚合周K/月K → 事件=本周(月)收盘站上 MA5（上周(月)在下方或首次站上）
     → 前向 4周/12周收益。分组：银行 vs 科技 vs 其他（全主板分层样本）。
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
KCACHE = ROOT / "data" / "big_kcache"
sys.path.insert(0, str(ROOT))
from engine.entryexit_matrix import BANKS, TECH_SEC, load_sectors  # noqa: E402


def to_weekly(ks: list[dict]) -> list[dict]:
    """日K→周K（ISO 周聚合）"""
    weeks = {}
    order = []
    for k in ks:
        y, w, _ = __import__("datetime").date.fromisoformat(k["date"]).isocalendar()
        key = f"{y}-W{w:02d}"
        if key not in weeks:
            weeks[key] = {"date": k["date"], "open": float(k["open"]), "close": float(k["close"]),
                          "high": float(k["high"]), "low": float(k["low"])}
            order.append(key)
        wk = weeks[key]
        wk["close"] = float(k["close"])
        wk["high"] = max(wk["high"], float(k["high"]))
        wk["low"] = min(wk["low"], float(k["low"]))
    return [weeks[k] for k in order]


def to_monthly(ks: list[dict]) -> list[dict]:
    months = {}
    order = []
    for k in ks:
        key = k["date"][:7]
        if key not in months:
            months[key] = {"date": k["date"], "open": float(k["open"]), "close": float(k["close"])}
            order.append(key)
        months[key]["close"] = float(k["close"])
    return [months[k] for k in order]


def ma_cross_events(bars: list[dict], fwd: int) -> list[float]:
    """收盘上穿 MA5 → 下一根 bar 开盘价入场，前向 fwd 根 bar 收益%
    （2026-09-06 R2 审查修复：旧版用信号 bar 收盘价同时当确认点和买入价，
    与 dividend_anchor_oos 发现#7同类，统一为下一根 bar 开盘价口径）"""
    closes = [b["close"] for b in bars]
    out = []
    for j in range(6, len(closes) - fwd):
        ma_now = sum(closes[j - 4:j + 1]) / 5
        ma_prev = sum(closes[j - 5:j]) / 5
        if closes[j] > ma_now and closes[j - 1] <= ma_prev:
            entry = float(bars[j + 1]["open"]) if j + 1 < len(bars) else 0.0
            if entry > 0:
                out.append((closes[j + fwd] - entry) / entry * 100)
    return out


def main() -> None:
    sectors = load_sectors()
    stats = defaultdict(list)
    for f in sorted(KCACHE.glob("*.json")):
        if f.stem == "000001":
            continue
        ks = json.loads(f.read_text())
        if len(ks) < 250:
            continue
        grp = ("银行" if f.stem in BANKS else
               "科技" if sectors.get(f.stem, "") in TECH_SEC else "其他")
        wk = to_weekly(ks)
        mo = to_monthly(ks)
        for r in ma_cross_events(wk, 4):
            stats[("周K", grp)].append(r)
        for r in ma_cross_events(mo, 3):
            stats[("月K", grp)].append(r)
    print(f"{'周期':<6}{'票型':<6}{'n':>7}{'胜率':>8}{'均值':>9}")
    for (per, grp), v in sorted(stats.items()):
        if len(v) < 10:
            continue
        print(f"{per:<6}{grp:<6}{len(v):>7}{sum(1 for x in v if x > 0)/len(v)*100:>7.1f}%{sum(v)/len(v):>+8.2f}%")
    json.dump({f"{p}-{g}": v for (p, g), v in stats.items()},
              open(ROOT / "data" / "ma_cycle_test.json", "w"))


if __name__ == "__main__":
    main()
