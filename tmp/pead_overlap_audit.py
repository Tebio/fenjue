"""PEAD 存活格 × 存活主张重叠度审计（2026-09-22 夜班第三层）。

问题：首亏×恐慌期/妖股期/已崩20日 等格，与体系已有触发器（X2/X3/T1-MEGA 的同族探测器、
深档低位 DEEP 件、恐慌深度剂量）吃的是不是同一批票？
重叠率>60%=同一批交易换个标签（重复计权，不算新 alpha 层）；<20%=真新层。
口径：逐事件检查同一 (股票, 信号日) 是否同时命中各存活探测器。
"""
import collections
import json
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
print(f"universe {len(stocks)}", flush=True)

LIVE = {
    "跌停接_MA60下(裸底座)": lp.REGISTRY["跌停接_MA60下"],
    "组合_跌停低_深跌(DEEP件)": lp.REGISTRY["组合_跌停低_深跌"],
    "恐慌深度_≤-9.5": lp.REGISTRY["恐慌深度_≤-9.5"],
    "组合_缺口低开_低位阳线_避周一(T1/X2族)": lp.REGISTRY["组合_缺口低开_低位阳线_避周一"],
    "强势回调_MA60上": lp.REGISTRY["强势回调_MA60上"],
}

CELLS = {
    "首亏×恐慌期": ("首亏", lambda ctx: ctx["rg"] == "恐慌期"),
    "首亏×妖股期": ("首亏", lambda ctx: ctx["rg"] == "妖股期"),
    "首亏×已崩20日": ("首亏", None),
    "扭亏×恐慌期": ("扭亏", lambda ctx: ctx["rg"] == "恐慌期"),
    "预增50×妖股期×高位": ("预增50", None),
}

overlap = {k: collections.Counter() for k in CELLS}
totals = collections.Counter()
pead = lp._pead_set()

for code, d in stocks.items():
    n = d["n"]
    evmap = pead.get(code)
    if not evmap:
        continue
    for i in range(lp.START, n - 21):
        dt = d["date"][i]
        pe = evmap.get(dt)
        if not pe or lp._epx(d, i) <= 0:
            continue
        ft = pe.get("FORECASTTYPE")
        sig = ("首亏" if ft == "首亏" else "扭亏" if ft == "扭亏"
               else "预增50" if ft == "预增" and (pe.get("INCREASEL") or 0) >= 50 else None)
        if sig is None:
            continue
        ma = d["ma60"][i]
        ctx = {"rg": regime.get(dt, "?"),
               "pos": ("low" if d["c"][i] <= ma else "high") if ma else None,
               "prior20": (d["c"][i] / d["c"][i - 20] - 1) if i >= 20 and d["c"][i - 20] > 0 else None}
        cell_hit = None
        for label, (want_sig, cond) in CELLS.items():
            ok = sig == want_sig
            if ok and label == "首亏×已崩20日":
                ok = ctx["prior20"] is not None and ctx["prior20"] <= -0.15
            elif ok and label == "预增50×妖股期×高位":
                ok = ctx["rg"] == "妖股期" and ctx["pos"] == "high"
            elif ok and cond is not None:
                ok = cond(ctx)
            if ok:
                cell_hit = label
                totals[label] += 1
                for lname, det in LIVE.items():
                    try:
                        if det(d, i):
                            overlap[label][lname] += 1
                    except Exception:
                        pass
print("═══ 重叠率（事件命中存活探测器的比例）═══")
out = {}
for label in CELLS:
    t = totals[label]
    if t == 0:
        continue
    row = {}
    for lname in LIVE:
        cnt = overlap[label][lname]
        row[lname] = f"{cnt}/{t} ({cnt / t * 100:.0f}%)"
    any_overlap = sum(overlap[label][l] for l in LIVE)
    out[label] = {"n": t, **row}
    print(f"\n  {label}（n={t}）:")
    for lname, v in row.items():
        print(f"    × {lname}: {v}")

json.dump(out, open(f"{ROOT}/data/pead_overlap_audit_20260922.json", "w"), ensure_ascii=False, indent=1)
print("\nsaved data/pead_overlap_audit_20260922.json")
