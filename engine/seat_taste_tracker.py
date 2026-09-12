#!/usr/bin/env python3
"""engine/seat_taste_tracker.py — 席位口味滚动 90 天跟踪器（2026-09-12）

背景：2026-09-12 半年切片实证——章盟主/成都系 H1 vs H2 概念 Top6 几乎零重叠，
静态概念画像有效期 ≤ 一个季度。本模块输出滚动 90 天窗口的席位口味快照：
  data/seat_taste_rolling.json  —— 每席位：近90天概念Top10、介入姿势、单票规模、T5衰减
  与 seat_gene.py 的区别：那是全窗测量底座；这是时效性跟踪（cron 每周末跑）。
"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
HT, KC = ROOT / "data/hithink", ROOT / "data/big_kcache"
WINDOW = 90  # 自然日
MIN_EVENTS = 8  # 窗口内少于此数不输出（噪音）

_kc = {}
def fwd_t5(code, d):
    if code not in _kc:
        f = KC / f"{code}.json"
        _kc[code] = json.loads(f.read_text()) if f.exists() else None
    ks = _kc[code]
    if not ks:
        return None
    idx = {k["date"]: i for i, k in enumerate(ks)}
    j = idx.get(d)
    if j is None or j + 5 >= len(ks):
        return None
    return (float(ks[j+5]["close"]) - float(ks[j]["close"])) / float(ks[j]["close"]) * 100


def main():
    days = sorted(p.name for p in HT.iterdir() if p.is_dir())
    cutoff = days[-1]
    import datetime
    c0 = (datetime.date.fromisoformat(cutoff) - datetime.timedelta(days=WINDOW)).isoformat()
    win = [d for d in days if d > c0]
    seats = defaultdict(lambda: {"n": 0, "concepts": defaultdict(int), "nets": [],
                                  "entry": defaultdict(int), "t5": [], "buys": 0})
    for d in win:
        f = HT / d / "lhb_hot.json"
        if not f.exists():
            continue
        for seat in json.loads(f.read_text())["data"].get("hot_money_items") or []:
            for r in seat.get("rows") or []:
                s = seats[seat["name"]]
                s["n"] += 1
                net = (r.get("hot_money_item_net_value") or 0) / 1e4
                s["nets"].append(abs(net))
                if net > 0:
                    s["buys"] += 1
                ch = (r.get("change") or 0) * 100
                k = "涨停" if ch >= 9.5 else "大涨" if ch >= 5 else "大跌" if ch <= -5 else "平盘"
                s["entry"][k] += 1
                for c in r.get("concept_list") or []:
                    s["concepts"][c["name"]] += 1
                t5 = fwd_t5(r["ticker"], d)
                if t5 is not None and net > 0:
                    s["t5"].append(t5)
    out = {"window": f"{c0}..{cutoff}", "days": len(win), "seats": {}}
    for name, s in seats.items():
        if s["n"] < MIN_EVENTS:
            continue
        t5 = s["t5"]
        out["seats"][name] = {
            "n": s["n"], "buy_ratio%": round(s["buys"] / s["n"] * 100, 1),
            "median_wan": round(sorted(s["nets"])[len(s["nets"])//2], 0),
            "top_concepts": sorted(s["concepts"].items(), key=lambda x: -x[1])[:10],
            "entry": dict(s["entry"]),
            "buy_dir_T5": {"n": len(t5), "avg%": round(sum(t5)/len(t5), 2)} if t5 else None,
        }
    out["seats"] = dict(sorted(out["seats"].items(), key=lambda x: -x[1]["n"]))
    (ROOT / "data/seat_gene_rolling.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"window {c0}..{cutoff} days={len(win)} seats={len(out['seats'])}")


if __name__ == "__main__":
    main()
