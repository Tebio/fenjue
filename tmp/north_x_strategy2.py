import json, sys, statistics as st
from collections import defaultdict
sys.path.insert(0, 'engine')
exec(open('tmp/north_x_strategy.py').read().split("stocks = lp.load_universe()")[0])
import law_pipeline as lp

FEE = 0.0015
stocks = lp.load_universe()
lp.build_xsection(stocks)
WINDOW = ("2026-05-01", "2026-09-18")
groups = defaultdict(lambda: defaultdict(list))
for cname, det in (("跌停底座", lp.REGISTRY["跌停接_MA60下"]),
                   ("TD9旗舰", lp.REGISTRY["组合_跌停低_TD9买_输家250"])):
    for code, d in stocks.items():
        n = d["n"]; c, o = d["c"], d["o"]
        for i in range(lp.START, n - 22):
            if o[i + 1] <= 0 or not (WINDOW[0] <= d["date"][i] <= WINDOW[1]):
                continue
            try:
                if not det(d, i):
                    continue
            except Exception:
                continue
            nd = north_at(code, d["date"][i])
            ei = i + 1
            for h in (5, 20):
                if ei + h < n and o[ei] > c[i] * 0.905:
                    groups[cname][(nd, h)].append(c[ei + h] / o[ei] - 1 - FEE)

def stat(rs):
    if len(rs) < 15: return {"n": len(rs), "注": "样本不足"}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    odds = st.mean(wins)/abs(st.mean(losses)) if wins and losses else None
    return {"n": len(rs), "胜率%": round(100*len(wins)/len(rs),1),
            "均值%": round(100*st.mean(rs),2), "赔率": round(odds,2) if odds else None}
print(f"窗口限定 {WINDOW[0]}→{WINDOW[1]}（北向信号同窗口可比）")
for cname in groups:
    print(f"== {cname} ==")
    for nd, label in ((1, "北向增持"), (-1, "北向减持"), (0, "不变"), (None, "无北向记录")):
        for h in (5, 20):
            print(f"  {label} T+{h}: {stat(groups[cname][(nd, h)])}")
