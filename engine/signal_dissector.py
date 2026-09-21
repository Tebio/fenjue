"""信号解剖台（2026-09-22 夜班，用户令「细分优化」）：四条生产线逐维解剖。

思路：每条线的入场事件（生产口径选票）→ 15 维特征 → 逐维透视（T+出场口径各线不同）→
活格判定（预登记：n≥300 且 t≥3 且 2019-2022/2023-2026 双段同号为正）。
目标：找出每条线内部「长肉的细胞」和「拖后腿的细胞」——优化=只在活格里开火。

线配置（生产保真）：
  T1-MEGA: 妖股/恐慌期缺口低簇≥20 日，排序(梯队≥3优先,量比)，取前10，T+3 硬出，费0.3%
  X2:      妖股/恐慌期大簇日，恐慌族浅跌按pos60取前三，T+5/-12%止损
  X3:      恐慌期streak≥2大簇日，同上，T+5/-12%
  深档DEEP: 跌停×MA60下×距MA60≤-25%，成簇≥5，深度最深前5，T+5
"""
import collections
import json
import math
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.003

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
stock_cap, qs = lp.load_cap_quintiles()
idx = json.loads(open(f"{ROOT}/data/index_sh000001.json").read())
cal = [k["date"] for k in idx]
iclose = {k["date"]: k["close"] for k in idx}
ipos = {d: j for j, d in enumerate(cal)}

mmap = json.loads(open(f"{ROOT}/data/industry_map.json").read())
code2ind = {str(k).zfill(6): v["industry"] for k, v in mmap.items() if isinstance(v, dict) and v.get("industry")}

streak = {}
s = 0
for d in cal:
    s = s + 1 if regime.get(d) == "恐慌期" else 0
    streak[d] = s

DET_GAP = lp.REGISTRY["组合_缺口低开_低位阳线_避周一"]
DETS_PANIC = {k: lp.REGISTRY[v] for k, v in
              {"跌停底座": "组合_跌停低_三连阴", "复活门": "反转族_跌停潮50", "摇篮": "妖股摇篮_成簇",
               "TD9输家": "组合_跌停低_TD9买_输家250", "TD9超跌": "组合_跌停低_TD9买_超跌20"}.items()}
GATED = {"跌停底座", "TD9输家", "TD9超跌"}
DET_DEEP = lp.REGISTRY["组合_跌停低_深跌"]
print("universe", len(stocks), flush=True)
for d in stocks.values():
    if "_didx" not in d:
        d["_didx"] = {x: j for j, x in enumerate(d["date"])}

# ── 事件池（全量信号，选票在下一步按日做）──
raw = {"gap": collections.defaultdict(list), "pan": collections.defaultdict(list),
       "deep": collections.defaultdict(list)}
for code, d in stocks.items():
    n = d["n"]
    c, o, h, l, v, ma = d["c"], d["o"], d["h"], d["l"], d["v"], d["ma60"]
    for i in range(lp.START, n - 6):
        dt = d["date"][i]
        if lp._epx(d, i) <= 0:
            continue
        hi60 = max(h[max(0, i - 60):i]) if i >= 1 else 0
        pos60 = c[i - 1] / hi60 - 1 if hi60 > 0 else 0
        vols = [v[x] for x in range(max(1, i - 5), i)]
        vr = v[i] / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 1
        ind = code2ind.get(code, "")
        gapv = c[i - 1] > 0 and o[i] / c[i - 1] - 1 or 0
        feat = {"code": code, "i": i, "date": dt, "year": dt[:4],
                "seg": "2019-2022" if dt < "2023" else "2023-2026",
                "regime": regime.get(dt, "?"), "ind": ind,
                "wd": dt, "vr": vr, "pos60": pos60, "gap": gapv,
                "pct": c[i] / c[i - 1] - 1 if c[i - 1] > 0 else 0,
                "depth": c[i] / ma[i] - 1 if ma[i] else None,
                "prior5": c[i] / c[i - 5] - 1 if i >= 5 and c[i - 5] > 0 else None,
                "prior20": c[i] / c[i - 20] - 1 if i >= 20 and c[i - 20] > 0 else None,
                }
        try:
            if DET_GAP(d, i):
                raw["gap"][dt].append({**feat, "ladder": 0})  # 梯队按日补
        except Exception:
            pass
        for cn, dn in DETS_PANIC.items():
            try:
                if dn(d, i):
                    raw["pan"][dt].append({**feat, "claim": cn})
            except Exception:
                pass
        try:
            if DET_DEEP(d, i):
                raw["deep"][dt].append(feat)
        except Exception:
            pass
print("gap日", len(raw["gap"]), "pan日", len(raw["pan"]), "deep日", len(raw["deep"]), flush=True)

# 行业梯队按日补算（当日同行业涨停数）
for dt, rows in raw["gap"].items():
    p = ipos.get(dt)
    boards = collections.Counter()
    if p is not None:
        for code2, d2 in stocks.items():
            j = d2["_didx"].get(dt)
            if j and j >= 1 and d2["c"][j] / d2["c"][j - 1] - 1 >= 0.098:
                boards[code2ind.get(code2, "")] += 1
    for r in rows:
        r["ladder"] = boards.get(r["ind"], 0)

# ── 按线生成入场事件（生产选票规则）──
def moo_events():
    evs = {"T1-MEGA": [], "X2": [], "X3": [], "深档DEEP": []}
    for dt in cal:
        rg = regime.get(dt, "?")
        ldc = lp._XLDC.get(dt, 0)
        gap = raw["gap"].get(dt, [])
        pan = raw["pan"].get(dt, [])
        pan_cl = len({r["code"] for r in pan if r["claim"] in GATED})
        big = pan_cl >= 5 or len(gap) >= 8 or ldc >= 30
        if len(gap) >= 20:
            for r in sorted(gap, key=lambda x: (-(x["ladder"] >= 3), -x["vr"]))[:10]:
                evs["T1-MEGA"].append(r)
        shallow = sorted(pan, key=lambda x: -x["pos60"])
        if rg == "恐慌期" and streak.get(dt, 0) >= 2 and big:
            evs["X3"].extend(shallow[:3])
        if rg in ("妖股期", "恐慌期") and big:
            evs["X2"].extend(shallow[:3])
        deep = raw["deep"].get(dt, [])
        if len(deep) >= 5:
            for r in sorted(deep, key=lambda x: x["depth"])[:5]:
                evs["深档DEEP"].append(r)
    return evs


events = moo_events()
print({k: len(v) for k, v in events.items()}, flush=True)


# ── 收益计算（各线出场口径）──
def attach_returns(evs, hold, stop12):
    out = []
    for e in evs:
        d = stocks[e["code"]]
        i = e["i"]
        if i + 1 >= d["n"]:
            continue
        ep = d["o"][i + 1]
        if ep <= 0:
            continue
        xi, how = min(i + 1 + hold, d["n"] - 1), "到期"
        if stop12:
            for j in range(i + 1, min(i + 1 + hold + 1, d["n"])):
                if d["c"][j] <= ep * 0.88:
                    xi, how = j, "止损"
                    break
        r = d["c"][xi] / ep - 1 - FEE
        out.append({**e, "ret": r, "how": how, "entry": d["date"][i + 1]})
    return out


LINES = {"T1-MEGA": (3, False), "X2": (5, True), "X3": (5, True), "深档DEEP": (5, False)}
DIMS = [
    ("year", lambda e: e["year"]),
    ("regime", lambda e: e["regime"]),
    ("capQ", lambda e: e.get("capQ", "?")),
    ("vr量比", lambda e: ("<1" if e["vr"] < 1 else "1-2" if e["vr"] < 2 else "≥2")),
    ("pos60距高", lambda e: ("≤-40%" if e["pos60"] <= -0.4 else "-40~-20%" if e["pos60"] <= -0.2 else ">-20%")),
    ("depth深度", lambda e: ("≤-35%" if e["depth"] is not None and e["depth"] <= -0.35 else
                             "-35~-25%" if e["depth"] is not None and e["depth"] <= -0.25 else ">-25%")),
    ("prior5", lambda e: ("≤-10%" if e["prior5"] is not None and e["prior5"] <= -0.10 else
                          "-10~0%" if e["prior5"] is not None and e["prior5"] <= 0 else ">0%")),
    ("gap幅度", lambda e: ("≤-5%" if e["gap"] <= -0.05 else "-5~-3%" if e["gap"] <= -0.03 else ">-3%")),
    ("ladder梯队", lambda e: ("≥3板" if e.get("ladder", 0) >= 3 else "<3")),
    ("claim来源", lambda e: e.get("claim", "-")),
    ("月份", lambda e: e["date"][5:7]),
    ("周几", lambda e: e["date"] and str(__import__("datetime").date(int(e["date"][:4]), int(e["date"][5:7]), int(e["date"][8:10])).weekday())),
]

results = {}
for line, (hold, stop12) in LINES.items():
    evs = attach_returns(events[line], hold, stop12)
    # cap quintile
    for e in evs:
        cap = lp.cap_at_date(stock_cap, e["code"], e["date"])
        b = qs.get(e["date"][:7])
        e["capQ"] = f"Q{sum(cap > x for x in b)}" if cap is not None and b else "?"
    n = len(evs)
    wins = sum(1 for e in evs if e["ret"] > 0)
    mean_r = st.mean([e["ret"] for e in evs]) if evs else 0
    print(f"\n═══════ {line}（n={n} 全样本 {wins / n * 100:.0f}%/{mean_r * 100:+.2f}%）═══════", flush=True)
    results[line] = {"n": n, "win": round(wins / n, 4) if n else 0, "mean": round(mean_r, 5), "dims": {}}
    for dname, fn in DIMS:
        g = collections.defaultdict(list)
        for e in evs:
            try:
                g[fn(e)].append(e["ret"])
            except Exception:
                pass
        dim_out = {}
        for k, xs in sorted(g.items()):
            if len(xs) < 80:
                continue
            m = st.mean(xs)
            sd = st.stdev(xs) if len(xs) > 1 else 0
            t = m / (sd / math.sqrt(len(xs))) if sd else 0
            dim_out[k] = {"n": len(xs), "win": round(sum(1 for x in xs if x > 0) / len(xs), 3),
                          "mean": round(m, 5), "t": round(t, 1)}
        results[line]["dims"][dname] = dim_out
        top = sorted(dim_out.items(), key=lambda kv: -kv[1]["mean"])[:3]
        bot = sorted(dim_out.items(), key=lambda kv: kv[1]["mean"])[:2]
        ts = " | ".join(f"{k}:{v['win'] * 100:.0f}%/{v['mean'] * 100:+.2f}%(n{v['n']},t{v['t']})" for k, v in top)
        bs = " | ".join(f"{k}:{v['mean'] * 100:+.2f}%" for k, v in bot)
        print(f"  {dname:<8} 强: {ts}  ‖ 弱: {bs}", flush=True)

json.dump(results, open(f"{ROOT}/data/signal_dissection_20260922.json", "w"), ensure_ascii=False, indent=1, default=str)
print("\nsaved data/signal_dissection_20260922.json")
