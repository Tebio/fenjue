#!/usr/bin/env python3
"""engine/seat_gene.py — 席位基因库 v1：游资/机构席位画像 + 上榜后表现测量（2026-09-12）

数据源：data/hithink/<date>/lhb_hot.json（命名游资席位）+ lhb_org.json（机构专用聚合）。
口径纪律：
- 信号日=龙虎榜公布日（盘后），可执行入场=T+1 开盘；T1_oc=次日开→收（可执行），
  T1_cc=当日收→次日收（公告漂移），T5_cc=当日收→5日后收。净口径 -0.15% 仅标于 T1_oc。
- 席位在某股的净额取 hot_money_item_net_value（正=该席位净买入）。
- cap_hist 提供信号日流通市值分档；big_kcache 提供前向收益（主板口径，300/688 缺记 missing）。
本模块是测量层：只产出画像与基率，不构成主张；具体假设另行过 law_pipeline submit。
"""
import json, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
HT, KC, CAP = ROOT/"data/hithink", ROOT/"data/big_kcache", ROOT/"data/cap_hist"
NET_FEE = 0.15  # T1_oc 净口径扣费

_kcache, _cap = {}, {}

def kcache(code):
    if code not in _kcache:
        f = KC / f"{code}.json"
        if f.exists():
            ks = json.loads(f.read_text())
            _kcache[code] = (ks, {k["date"]: i for i, k in enumerate(ks)})
        else:
            _kcache[code] = None
    return _kcache[code]

def cap_at(code, d):
    if code not in _cap:
        f = CAP / f"{code}.json"
        _cap[code] = json.loads(f.read_text()) if f.exists() else []
    rows = _cap[code]
    lo, hi = 0, len(rows) - 1
    best = None
    for r in rows:  # 小数据线性即可
        if r[0] <= d:
            best = r[2]
        else:
            break
    return best

def fwd(code, d):
    """返回 (T1_oc%, T1_cc%, T5_cc%) 或 None"""
    e = kcache(code)
    if not e:
        return None
    ks, idx = e
    j = idx.get(d)
    if j is None or j + 1 >= len(ks):
        return None
    o1, c1 = float(ks[j+1]["open"]), float(ks[j+1]["close"])
    c0 = float(ks[j]["close"])
    if o1 <= 0 or c0 <= 0:
        return None
    t5 = (float(ks[j+5]["close"]) - c0) / c0 * 100 if j + 5 < len(ks) else None
    return ((c1 - o1) / o1 * 100, (c1 - c0) / c0 * 100, t5)


def collect():
    seats = defaultdict(list)   # seat -> [event]
    org_rows = []               # 机构聚合行
    missing = 0
    for ddir in sorted(HT.iterdir()):
        f = ddir / "lhb_hot.json"
        if f.exists():
            data = json.loads(f.read_text())["data"]
            for seat in data.get("hot_money_items") or []:
                for r in seat.get("rows") or []:
                    ev = {
                        "date": ddir.name, "seat": seat["name"], "code": r["ticker"],
                        "name": r["name"], "concepts": [c["name"] for c in r.get("concept_list") or []],
                        "change": round((r.get("change") or 0) * 100, 2),
                        "seat_net_wan": round((r.get("hot_money_item_net_value") or 0) / 1e4, 1),
                        "range_days": r.get("range_days"),
                    }
                    fr = fwd(ev["code"], ev["date"])
                    if fr is None:
                        missing += 1
                    else:
                        ev["T1_oc"], ev["T1_cc"], ev["T5_cc"] = (round(x, 2) if x is not None else None for x in fr)
                    ev["cap_yi"] = cap_at(ev["code"], ev["date"])
                    seats[seat["name"]].append(ev)
        fo = ddir / "lhb_org.json"
        if fo.exists():
            for r in json.loads(fo.read_text())["data"].get("stock_items") or []:
                fr = fwd(r["ticker"], ddir.name)
                row = {"date": ddir.name, "code": r["ticker"], "name": r["name"],
                       "concepts": [c["name"] for c in r.get("concept_list") or []],
                       "change": round((r.get("change") or 0) * 100, 2),
                       "org_net_wan": round((r.get("org_net_value") or 0) / 1e4, 1),
                       "org_buy_num": r.get("org_buy_num"), "org_sell_num": r.get("org_sell_num"),
                       "cap_yi": cap_at(r["ticker"], ddir.name)}
                if fr:
                    row["T1_oc"], row["T1_cc"], row["T5_cc"] = (round(x, 2) if x is not None else None for x in fr)
                else:
                    missing += 1
                org_rows.append(row)
    return seats, org_rows, missing


def stats(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "win%": round(sum(1 for x in xs if x > 0) / len(xs) * 100, 1),
            "avg%": round(sum(xs) / len(xs), 2)}


def profile(name, evs):
    buys = [e for e in evs if e["seat_net_wan"] > 0]
    caps = [e["cap_yi"] for e in evs if e.get("cap_yi")]
    concept_freq = defaultdict(int)
    for e in evs:
        for c in e["concepts"]:
            concept_freq[c] += 1
    cap_bands = {"<50": 0, "50-100": 0, "100-200": 0, "200-400": 0, ">400": 0}
    for c in caps:
        band = "<50" if c < 50 else "50-100" if c < 100 else "100-200" if c < 200 else "200-400" if c < 400 else ">400"
        cap_bands[band] += 1
    entry_pos = {"涨停介入(>=9.5)": 0, "大涨(5~9.5)": 0, "平盘(-5~5)": 0, "大跌(<=-5)": 0}
    for e in evs:
        ch = e["change"]
        k = "涨停介入(>=9.5)" if ch >= 9.5 else "大涨(5~9.5)" if ch >= 5 else "大跌(<=-5)" if ch <= -5 else "平盘(-5~5)"
        entry_pos[k] += 1
    return {
        "n_events": len(evs), "active_days": len({e["date"] for e in evs}),
        "buy_ratio%": round(len(buys) / len(evs) * 100, 1) if evs else 0,
        "median_net_wan": sorted(abs(e["seat_net_wan"]) for e in evs)[len(evs)//2] if evs else 0,
        "top_concepts": sorted(concept_freq.items(), key=lambda x: -x[1])[:8],
        "cap_bands": cap_bands, "entry_position": entry_pos,
        "buy_dir_T1_oc_net": stats([e.get("T1_oc") - NET_FEE if e.get("T1_oc") is not None else None for e in buys]),
        "buy_dir_T1_cc": stats([e.get("T1_cc") for e in buys]),
        "buy_dir_T5_cc": stats([e.get("T5_cc") for e in buys]),
    }


def main():
    seats, org_rows, missing = collect()
    print(f"seats={len(seats)} org_rows={len(org_rows)} no_kcache={missing}")
    profiles = {}
    for name, evs in seats.items():
        if len(evs) >= 20:
            profiles[name] = profile(name, evs)
    # 全席位买入方向基线
    all_buys = [e for evs in seats.values() for e in evs if e["seat_net_wan"] > 0]
    org_buy = [r for r in org_rows if (r["org_net_wan"] or 0) > 0]
    out = {
        "meta": {"window": "2025-09-12..2026-09-11", "built": "2026-09-12",
                 "fee_note": "buy_dir_T1_oc_net 已扣 0.15%"},
        "baseline_all_seat_buys": {
            "T1_oc_net": stats([e.get("T1_oc") - NET_FEE if e.get("T1_oc") is not None else None for e in all_buys]),
            "T1_cc": stats([e.get("T1_cc") for e in all_buys]),
            "T5_cc": stats([e.get("T5_cc") for e in all_buys]),
        },
        "baseline_org_buys": {
            "T1_oc_net": stats([r.get("T1_oc") - NET_FEE if r.get("T1_oc") is not None else None for r in org_buy]),
            "T1_cc": stats([r.get("T1_cc") for r in org_buy]),
            "T5_cc": stats([r.get("T5_cc") for r in org_buy]),
        },
        "profiles": dict(sorted(profiles.items(), key=lambda x: -x[1]["n_events"])),
    }
    (ROOT/"data/seat_gene_20260912.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    # 控制台头条
    print("\n== 全席位买入方向基线 ==", json.dumps(out["baseline_all_seat_buys"], ensure_ascii=False))
    print("== 机构净买入基线 ==", json.dumps(out["baseline_org_buys"], ensure_ascii=False))
    for nm, p in list(out["profiles"].items())[:12]:
        print(f"\n[{nm}] n={p['n_events']} 买向比={p['buy_ratio%']}% 中位净额={p['median_net_wan']}万")
        print("  T1_oc净:", p["buy_dir_T1_oc_net"], " T5:", p["buy_dir_T5_cc"])
        print("  概念:", [c for c, _ in p["top_concepts"][:5]], " 市值档:", p["cap_bands"])
    for tgt in ["章盟主", "炒股养家"]:
        if tgt in profiles:
            print(f"\n★ {tgt}:", json.dumps(profiles[tgt], ensure_ascii=False)[:600])


if __name__ == "__main__":
    main()
