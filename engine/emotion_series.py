#!/usr/bin/env python3
"""engine/emotion_series.py — 情绪周期四指标全市场日度序列 (2026-09-06)

学术+实战公认的周期四指标（雪球量化研判框架）：
  涨停/跌停数、涨跌家数比（宽度）、连板高度、晋级率（昨板→今板）、两市成交额
用全主板 3191 只日K重建 2026 全年序列，回答：周期转变时哪个指标最先动。
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

KC = Path("/opt/data/fenjue/data/big_kcache")


def main() -> None:
    daily = defaultdict(lambda: {"up": 0, "down": 0, "limit_up": [], "limit_down": 0, "amount": 0.0})
    for f in sorted(KC.glob("*.json")):
        if f.stem == "000001":
            continue
        ks = json.loads(f.read_text())
        for j in range(1, len(ks)):
            d = ks[j]["date"]
            if d < "2026-01-01":
                continue
            pc, tc = float(ks[j - 1]["close"]), float(ks[j]["close"])
            if pc <= 0 or tc <= 0:
                continue
            p = (tc - pc) / pc * 100
            rec = daily[d]
            if p > 0:
                rec["up"] += 1
            elif p < 0:
                rec["down"] += 1
            if p >= 9.8:
                rec["limit_up"].append(f.stem)
            elif p <= -9.8:
                rec["limit_down"] += 1
            rec["amount"] += float(ks[j]["volume"]) * tc

    dates = sorted(daily)
    out = []
    prev_boards: set[str] = set()
    streak = {}  # code -> 连板数
    for d in dates:
        rec = daily[d]
        boards = set(rec["limit_up"])
        # 连板：昨板 ∩ 今板 → 高度+1；首板 = 1
        new_streak = {}
        for c in boards:
            new_streak[c] = streak.get(c, 0) + 1
        streak = new_streak
        max_streak = max(streak.values()) if streak else 0
        promoted = len(boards & prev_boards)
        rate = promoted / len(prev_boards) * 100 if prev_boards else None
        out.append({
            "date": d,
            "up": rec["up"], "down": rec["down"],
            "adr": round(rec["up"] / max(1, rec["down"]), 2),
            "limit_up": len(boards), "limit_down": rec["limit_down"],
            "max_streak": max_streak,
            "promote%": round(rate, 1) if rate is not None else None,
            "amount_yi": round(rec["amount"] / 1e8 / 1e4, 2),  # 万亿
        })
        prev_boards = boards
    (KC.parent / "emotion_series.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for r in out:
        if r["date"] >= "2026-05-25":
            print(f"{r['date']} 涨/跌 {r['up']}/{r['down']} ADR {r['adr']:.2f} | 涨停 {r['limit_up']:>3} 跌停 {r['limit_down']:>3} | "
                  f"最高板 {r['max_streak']} 晋级 {str(r['promote%']):>5}% | 成交 {r['amount_yi']}万亿")


if __name__ == "__main__":
    main()
