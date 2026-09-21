"""PEAD 重组格的条件内终审（2026-09-22 夜班，第二阶段）。

第一阶段 9 格过了位置匹配终审，但位置匹配的对照组跨全部 regime——
而「首亏×恐慌期 +4.92%」这类格，对照组没有卡在恐慌期内，edge 可能全是恐慌期 T+20 普涨的 beta。
本阶段：条件内对照。格=「条件 C × PEAD事件」；对照=同条件 C 下无 PEAD 事件的全部股票日
（同股同位置）。边际 = 格均值 - 条件内对照均值。>1.5pp 才算 PEAD 在条件上真加料。

单遍扫描同时算 9 格的信号桶+对照桶。
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
lp.build_xsection(stocks)
regime = lp.load_regime()
stock_cap, qs = lp.load_cap_quintiles()
print(f"universe {len(stocks)}", flush=True)

CELLS = {
    "首亏×恐慌期": lambda s, c: s == "首亏" and c["regime"] == "恐慌期",
    "首亏×妖股期": lambda s, c: s == "首亏" and c["regime"] == "妖股期",
    "首亏×已崩20日": lambda s, c: s == "首亏" and c["prior20"] is not None and c["prior20"] <= -0.15,
    "首亏×跌停潮≥50": lambda s, c: s == "首亏" and c["ldc"] >= 50,
    "首亏×小市值Q01": lambda s, c: s == "首亏" and c["capQ"] is not None and c["capQ"] <= 1,
    "扭亏×恐慌期": lambda s, c: s == "扭亏" and c["regime"] == "恐慌期",
    "预增50×妖股期×高位": lambda s, c: s == "预增50" and c["regime"] == "妖股期" and c["pos"] == "high",
    "首亏×非年报季": lambda s, c: s == "首亏" and not c["annual"],
    "首亏×年报季": lambda s, c: s == "首亏" and c["annual"],
}
# 每格的对照条件 = 去掉 PEAD 类型条件的纯环境条件
COND_ONLY = {
    "首亏×恐慌期": lambda c: c["regime"] == "恐慌期",
    "首亏×妖股期": lambda c: c["regime"] == "妖股期",
    "首亏×已崩20日": lambda c: c["prior20"] is not None and c["prior20"] <= -0.15,
    "首亏×跌停潮≥50": lambda c: c["ldc"] >= 50,
    "首亏×小市值Q01": lambda c: c["capQ"] is not None and c["capQ"] <= 1,
    "扭亏×恐慌期": lambda c: c["regime"] == "恐慌期",
    "预增50×妖股期×高位": lambda c: c["regime"] == "妖股期" and c["pos"] == "high",
    "首亏×非年报季": lambda c: not c["annual"],
    "首亏×年报季": lambda c: c["annual"],
}
sig_bucket = collections.defaultdict(list)
ctl_bucket = collections.defaultdict(list)

pead = lp._pead_set()
for code, d in stocks.items():
    n = d["n"]
    c_arr, ma_arr = d["c"], d["ma60"]
    evmap = pead.get(code, {})
    for i in range(lp.START, n - 21):
        ma = ma_arr[i]
        if ma is None or lp._epx(d, i) <= 0:
            continue
        dt = d["date"][i]
        cap = lp.cap_at_date(stock_cap, code, dt)
        bq = qs.get(dt[:7])
        ctx = {
            "regime": regime.get(dt, "?"),
            "pos": "low" if c_arr[i] <= ma else "high",
            "depth": c_arr[i] / ma - 1,
            "prior20": (c_arr[i] / c_arr[i - 20] - 1) if i >= 20 and c_arr[i - 20] > 0 else None,
            "ldc": lp._XLDC.get(dt, 0),
            "annual": dt[5:7] in ("01", "02", "03", "04"),
            "capQ": (sum(cap > x for x in bq) if cap is not None and bq else None),
        }
        pe = evmap.get(dt)
        sig = None
        if pe:
            ft = pe.get("FORECASTTYPE")
            sig = ("首亏" if ft == "首亏" else "扭亏" if ft == "扭亏"
                   else "预增50" if ft == "预增" and (pe.get("INCREASEL") or 0) >= 50 else None)
        r20 = c_arr[i + 20] / lp._epx(d, i) - 1 - FEE
        for label, fn in CELLS.items():
            if COND_ONLY[label](ctx):
                if sig and fn(sig, ctx):
                    sig_bucket[label].append(r20)
                else:
                    # 对照桶：同条件、无「该格对应类型」事件（有任何 PEAD 都剔除更干净）
                    if sig is None:
                        ctl_bucket[label].append(r20)

print("\n═══ 条件内终审（T+20）═══")
out = {}
for label in CELLS:
    s, c0 = sig_bucket[label], ctl_bucket[label]
    if len(s) < 100 or len(c0) < 500:
        print(f"  {label}: 样本不足 sig={len(s)} ctl={len(c0)}")
        continue
    ms, mc = st.mean(s), st.mean(c0)
    marg = (ms - mc) * 100
    sd = st.stdev(s)
    t = ms / (sd / math.sqrt(len(s)))
    verdict = "✅条件内真加料" if marg > 1.5 else ("🟡贴线" if marg > 0 else "❌全是条件beta")
    out[label] = {"sig_n": len(s), "sig_mean%": round(ms * 100, 2), "ctl_n": len(c0),
                  "ctl_mean%": round(mc * 100, 2), "条件内边际pp": round(marg, 2), "t": round(t, 1),
                  "verdict": verdict}
    print(f"  {label}: 信号 {ms * 100:+.2f}%(n={len(s)}) vs 条件内对照 {mc * 100:+.2f}%(n={len(c0)}) "
          f"→ 边际 {marg:+.2f}pp {verdict}")

json.dump(out, open(f"{ROOT}/data/pead_s4_within_cond_20260922.json", "w"), ensure_ascii=False, indent=1)
print("\nsaved data/pead_s4_within_cond_20260922.json")
