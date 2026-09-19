import json, sys, statistics as st
from collections import defaultdict
sys.path.insert(0, 'engine')
import law_pipeline as lp

FEE = 0.0015
stocks = lp.load_universe()
lp.build_xsection(stocks)
det = lp.REGISTRY["跌停接_MA60下"]
hi = max(lp.HORIZONS) + 1
days = defaultdict(list)
for code, d in stocks.items():
    n = d["n"]; o = d["o"]
    for i in range(lp.START, n - hi):
        if o[i + 1] <= 0:
            continue
        try:
            if det(d, i):
                days[d["date"][i]].append((code, i))
        except Exception:
            pass

def fwd(code, i, h):
    d = stocks[code]; ei = i + 1
    if ei + h >= d["n"] or d["o"][ei] <= 0 or d["o"][ei] <= d["c"][i] * 0.905:
        return None
    return d["c"][ei + h] / d["o"][ei] - 1 - FEE

def stat(rs):
    if len(rs) < 10: return None
    wins = [r for r in rs if r > 0]
    return {"n": len(rs), "胜率%": round(100*len(wins)/len(rs),1), "均值%": round(100*st.mean(rs),2)}

from datetime import datetime
groups = defaultdict(list)   # (入场wd, 信号日成簇?) -> T+5 returns
for dt, evs in days.items():
    cluster = len(evs) >= 5
    for code, i in evs:
        d = stocks[code]; ei = i + 1
        if ei >= d["n"]: continue
        wd = datetime.strptime(d["date"][ei], "%Y-%m-%d").weekday()
        if wd > 4: continue
        r = fwd(code, i, 5)
        if r is not None:
            groups[(wd, cluster)].append(r)

for wd in range(5):
    for cl in (True, False):
        s = stat(groups[(wd, cl)])
        print(f"入场周{'一二三四五'[wd]} 信号日{'成簇≥5' if cl else '零星<5'}: {s}")
# 关键对照：周一入场拆成簇 vs 零星
print("\n== 悖论检验核心 ==")
print("周一入场·信号日成簇:", stat(groups[(0, True)]))
print("周一入场·信号日零星:", stat(groups[(0, False)]))
print("周五入场·信号日成簇:", stat(groups[(4, True)]))
print("周五入场·信号日零星:", stat(groups[(4, False)]))
