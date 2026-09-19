import json, sys, itertools
sys.path.insert(0, 'engine')
import law_pipeline as lp

ROOT = '/opt/data/fenjue'
FEE = 0.0015
HORIZONS = [1, 2, 3, 5, 10, 20]

BASES = {"跌停低": lp.REGISTRY["跌停接_MA60下"], "缺口低": lp.REGISTRY["组合_缺口低开_低位阳线"],
         "触板低": lp.REGISTRY["组合_触板未封_低位"]}
CONFS = {"输家250": lp._loser250, "超跌20": lp._oversold20_60d, "三连阴": lp._three_down,
         "缩量": lambda d, i: lp._volratio(d, i) < 0.8, "TD9买": lp._td9buy,
         "避雷针低": lp._bigupper, "大长腿低": lp._biglower, "剔亏ST": lp._fund_healthy}

stocks = lp.load_universe()
lp.build_xsection(stocks)
hi = max(lp.HORIZONS) + 1
bnames, bdet = list(BASES), list(BASES.values())
cnames, cdet = list(CONFS), list(CONFS.values())
combos = {}
for code, d in stocks.items():
    n = d["n"]; o = d["o"]
    for i in range(lp.START, n - hi):
        if o[i + 1] <= 0:
            continue
        hit_bases = []
        for bi, bd in enumerate(bdet):
            try:
                if bd(d, i): hit_bases.append(bnames[bi])
            except Exception: pass
        if not hit_bases:
            continue
        hits = set()
        for ci, cd in enumerate(cdet):
            try:
                if cd(d, i): hits.add(cnames[ci])
            except Exception: pass
        if len(hits) < 4:
            continue
        for b in hit_bases:
            for cs in itertools.combinations(sorted(hits), 4):
                combos.setdefault((b, cs), []).append((code, i))

print(f"五条件(底座+4确认)非空格: {len(combos)} / 理论 {3*70}")
import statistics as st
cells = {}
for (b, cs), ev in sorted(combos.items()):
    name = f"穷举5_{b}_{'_'.join(cs)}"
    out = {"n": len(ev)}
    for h in (5, 20):
        rs = []
        for code, i in ev:
            d = stocks[code]; ei = i + 1
            if ei + h >= d["n"] or d["o"][ei] <= 0 or d["o"][ei] <= d["c"][i] * 0.905:
                continue
            rs.append(d["c"][ei + h] / d["o"][ei] - 1 - FEE)
        if rs:
            wins = [r for r in rs if r > 0]
            out[f"T+{h}"] = {"胜率%": round(100*len(wins)/len(rs),1), "均值%": round(100*st.mean(rs),2), "n": len(rs)}
        else:
            out[f"T+{h}"] = None
    cells[name] = out
    if out["n"] >= 200 and out.get("T+5") and out["T+5"]["均值%"] > 0:
        print(f"  {name}: n={out['n']} T+5={out['T+5']} T+20={out['T+20']}")
json.dump(cells, open(f"{ROOT}/data/triples5_exhaustive_20260919.json", "w"), ensure_ascii=False, indent=1)
n200 = sum(1 for v in cells.values() if v["n"] >= 200)
print(f"n>=200 的格: {n200} / {len(cells)}")
