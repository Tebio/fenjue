"""PEAD T+20 细分×重组全矩阵（2026-09-22 夜班，用户令「细分/组合/细分后再组合」）。

对象：PEAD_首亏/扭亏/预增50 三变体（T+5 已死，T+20 有苗头）。
流程：事件级特征全量提取（一次宇宙扫描）→ 单维细分透视 → 与存活信号族重组 →
      活格（n≥300, t≥3, 双段同号）→ matched_marginal 位置匹配终审。
预登记评判规则（防钓鱼）：活格必须同时满足 n≥300、t≥3、2019-2022 与 2023-2026 双段均值同号为正、
位置匹配边际>0。任何一项不过=死格。全矩阵如实上报（含死格）。
"""
import collections
import json
import math
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015

stocks = lp.load_universe()
lp.build_xsection(stocks)  # _XLDC 跌停计数等截面上下文
regime = lp.load_regime()
stock_cap, qs = lp.load_cap_quintiles()
idx = json.loads(open(f"{ROOT}/data/index_sh000001.json").read())
ical = [k["date"] for k in idx]
iclose = {k["date"]: k["close"] for k in idx}
ipos = {d: i for i, d in enumerate(ical)}
print(f"universe {len(stocks)}", flush=True)

EVENTS = []
for name, types, min_inc in (("首亏", {"首亏"}, None), ("扭亏", {"扭亏"}, None), ("预增50", {"预增"}, 50)):
    det = lp.REGISTRY[f"PEAD_{name}"]
    for code, d in stocks.items():
        n = d["n"]
        for i in range(lp.START, n - 21):
            if lp._epx(d, i) <= 0 or not det(d, i):
                continue
            dt = d["date"][i]
            p = ipos.get(dt)
            ma = d["ma60"][i]
            r20 = None
            e = {
                "sig": name, "code": code, "i": i, "date": dt, "year": dt[:4],
                "seg": "2019-2022" if dt < "2023" else "2023-2026",
                "regime": regime.get(dt, "?"),
                "capQ": None, "pos": None, "depth": None,
                "prior20": None, "idx5": None, "ldc": lp._XLDC.get(dt, 0),
                "annual_season": dt[5:7] in ("01", "02", "03", "04"),
            }
            cap = lp.cap_at_date(stock_cap, code, dt)
            b = qs.get(dt[:7])
            if cap is not None and b:
                e["capQ"] = sum(cap > x for x in b)
            if ma:
                e["pos"] = "low" if d["c"][i] <= ma else "high"
                e["depth"] = d["c"][i] / ma - 1
            if i >= 20 and d["c"][i - 20] > 0:
                e["prior20"] = d["c"][i] / d["c"][i - 20] - 1
            if p is not None and p >= 5:
                e["idx5"] = iclose[ical[p]] / iclose[ical[p - 5]] - 1
            e["T20"] = d["c"][i + 20] / lp._epx(d, i) - 1 - FEE
            e["T5"] = d["c"][i + 5] / lp._epx(d, i) - 1 - FEE
            EVENTS.append(e)
    print(f"{name} 累计 {len(EVENTS)}", flush=True)

# 同日 PEAD 事件簇数
cl = collections.Counter(e["date"] for e in EVENTS)
for e in EVENTS:
    e["pead_cluster"] = cl[e["date"]]


def blk(rows):
    if len(rows) < 30:
        return {"n": len(rows)}
    xs = [r["T20"] for r in rows]
    m = st.mean(xs)
    sd = st.stdev(xs)
    return {"n": len(xs), "win": round(sum(1 for x in xs if x > 0) / len(xs), 4),
            "mean": round(m, 5), "t": round(m / (sd / math.sqrt(len(xs))), 1) if sd else None}


def seg_ok(rows):
    a = [r["T20"] for r in rows if r["seg"] == "2019-2022"]
    b = [r["T20"] for r in rows if r["seg"] == "2023-2026"]
    return (len(a) >= 100 and len(b) >= 100
            and st.mean(a) > 0 and st.mean(b) > 0)


# ── 单维细分 ──
def cut(rows, keyfn, label):
    g = collections.defaultdict(list)
    for r in rows:
        g[keyfn(r)].append(r)
    return {label: {str(k): blk(v) for k, v in sorted(g.items())}}


results = {"events_n": len(EVENTS)}
by_sig = {s: [e for e in EVENTS if e["sig"] == s] for s in ("首亏", "扭亏", "预增50")}

print("\n═══ 单维细分（T+20）═══", flush=True)
for sig, rows in by_sig.items():
    print(f"\n── {sig}（n={len(rows)}）──", flush=True)
    for label, fn in (
        ("year", lambda r: r["year"]),
        ("regime", lambda r: r["regime"]),
        ("capQ", lambda r: f"Q{r['capQ']}" if r["capQ"] is not None else "?"),
        ("position", lambda r: r["pos"] or "?"),
        ("depth", lambda r: ("≤-25%" if r["depth"] is not None and r["depth"] <= -0.25 else
                             "-25~0%" if r["depth"] is not None and r["depth"] <= 0 else ">0%")),
        ("prior20", lambda r: ("≤-15%" if r["prior20"] is not None and r["prior20"] <= -0.15 else
                               "-15~0%" if r["prior20"] is not None and r["prior20"] <= 0 else ">0%")),
        ("idx5", lambda r: ("<-3%" if r["idx5"] is not None and r["idx5"] < -0.03 else "≥-3%")),
        ("ldc", lambda r: ("≥50" if r["ldc"] >= 50 else "30-49" if r["ldc"] >= 30 else "<30")),
        ("annual_season", lambda r: "年报季1-4月" if r["annual_season"] else "其他季"),
    ):
        c = cut(rows, fn, label)
        results.setdefault(sig, {}).update(c)
        for k, v in list(c.values())[0].items():
            if v.get("n", 0) >= 100:
                print(f"  {label}={k}: n={v['n']} {v['win'] * 100:.0f}%/{v['mean'] * 100:+.2f}% t={v['t']}", flush=True)

# ── 重组（×存活信号族条件）──
print("\n═══ 重组格（T+20）═══", flush=True)
COMBOS = [
    ("首亏×恐慌期", lambda e: e["sig"] == "首亏" and e["regime"] == "恐慌期"),
    ("首亏×妖股期", lambda e: e["sig"] == "首亏" and e["regime"] == "妖股期"),
    ("首亏×深跌位", lambda e: e["sig"] == "首亏" and e["depth"] is not None and e["depth"] <= -0.25),
    ("首亏×已崩20日", lambda e: e["sig"] == "首亏" and e["prior20"] is not None and e["prior20"] <= -0.15),
    ("首亏×跌停潮≥50", lambda e: e["sig"] == "首亏" and e["ldc"] >= 50),
    ("首亏×小市值Q01", lambda e: e["sig"] == "首亏" and e["capQ"] is not None and e["capQ"] <= 1),
    ("首亏×深跌位×恐慌期", lambda e: e["sig"] == "首亏" and e["depth"] is not None and e["depth"] <= -0.25 and e["regime"] == "恐慌期"),
    ("扭亏×深跌位", lambda e: e["sig"] == "扭亏" and e["depth"] is not None and e["depth"] <= -0.25),
    ("扭亏×恐慌期", lambda e: e["sig"] == "扭亏" and e["regime"] == "恐慌期"),
    ("预增50×妖股期×高位", lambda e: e["sig"] == "预增50" and e["regime"] == "妖股期" and e["pos"] == "high"),
    ("首亏×非年报季", lambda e: e["sig"] == "首亏" and not e["annual_season"]),
    ("首亏×年报季", lambda e: e["sig"] == "首亏" and e["annual_season"]),
]
combo_hits = {}
for label, fn in COMBOS:
    rows = [e for e in EVENTS if fn(e)]
    b = blk(rows)
    ok = b.get("n", 0) >= 300 and (b.get("t") or 0) >= 3 and seg_ok(rows)
    b["双段同号为正"] = seg_ok(rows)
    b["预审存活"] = ok
    combo_hits[label] = b
    flag = "🟢" if ok else "·"
    print(f"  {flag} {label}: n={b.get('n')} {b.get('win', 0) * 100:.0f}%/{b.get('mean', 0) * 100:+.2f}% t={b.get('t')} 双段正={b['双段同号为正']}", flush=True)
results["重组格"] = combo_hits

# ── 终审：预审活格过位置匹配 ──
alive = [label for label, b in combo_hits.items() if b.get("预审存活")]
print(f"\n═══ 位置匹配终审（{len(alive)} 格）═══", flush=True)
if alive:
    # 把格条件翻成 detector 闭包（事件日命中 + 条件）。深度/前20日/ldc/regime 在 detect 内现算。
    def make_det(fn):
        def det(d, i):
            if not (lp._pead(d, i, {"首亏"}) or lp._pead(d, i, {"扭亏"}) or lp._pead(d, i, {"预增"}, min_inc=50)):
                return False
            dt = d["date"][i]
            ma = d["ma60"][i]
            e = {"date": dt, "regime": regime.get(dt, "?"),
                 "depth": (d["c"][i] / ma - 1) if ma else None,
                 "prior20": (d["c"][i] / d["c"][i - 20] - 1) if i >= 20 and d["c"][i - 20] > 0 else None,
                 "ldc": lp._XLDC.get(dt, 0), "annual_season": dt[5:7] in ("01", "02", "03", "04"),
                 "pos": ("low" if ma and d["c"][i] <= ma else "high") if ma else None,
                 "capQ": None}
            cap = lp.cap_at_date(stock_cap, d["code"], dt)
            bq = qs.get(dt[:7])
            if cap is not None and bq:
                e["capQ"] = sum(cap > x for x in bq)
            # 判定信号类型
            pe = lp._pead_set().get(d["code"], {}).get(dt)
            e["sig"] = ("首亏" if pe and pe.get("FORECASTTYPE") == "首亏" else
                        "扭亏" if pe and pe.get("FORECASTTYPE") == "扭亏" else
                        "预增50" if pe and pe.get("FORECASTTYPE") == "预增" and (pe.get("INCREASEL") or 0) >= 50 else None)
            return e["sig"] is not None and fn(e)
        return det

    for label, fn in COMBOS:
        if label not in alive:
            continue
        marg = lp.matched_marginal(make_det(fn), stocks, [20])
        combo_hits[label]["位置匹配边际T20pp"] = round(marg.get(20, 0), 2)
        combo_hits[label]["终审"] = combo_hits[label]["位置匹配边际T20pp"] > 0
        print(f"  {label}: 边际 T+20 {marg.get(20):+.2f}pp → {'✅终审过' if combo_hits[label]['终审'] else '❌位置beta'}", flush=True)

json.dump(results, open(f"{ROOT}/data/pead_s4_matrix_20260922.json", "w"), ensure_ascii=False, indent=1, default=str)
print("\nsaved data/pead_s4_matrix_20260922.json")
