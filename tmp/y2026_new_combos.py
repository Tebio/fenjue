import json, sys, statistics as st
sys.path.insert(0, 'engine')
import law_pipeline as lp

FEE = 0.0015
stocks = lp.load_universe()
lp.build_xsection(stocks)
NAMES = ["跌停接_MA60下", "组合_跌停低_TD9买_输家250", "组合_跌停低_TD9买_超跌20",
         "组合_缺口低_剔亏ST_超跌20_输家250", "组合_触板低_TD9买_剔亏ST_超跌20",
         "组合_缺口低开_低位阳线_避周一"]
for nm in NAMES:
    det = lp.REGISTRY[nm]
    rs5, rs20 = [], []
    for code, d in stocks.items():
        c, o, n = d["c"], d["o"], d["n"]
        for i in range(lp.START, n - 22):
            if o[i + 1] <= 0 or d["date"][i] < "2026-01-01":
                continue
            try:
                if not det(d, i):
                    continue
            except Exception:
                continue
            ei = i + 1
            if o[ei] <= c[i] * 0.905:
                continue
            if ei + 5 < n:
                rs5.append(c[ei + 5] / o[ei] - 1 - FEE)
            if ei + 20 < n:
                rs20.append(c[ei + 20] / o[ei] - 1 - FEE)
    def stat(rs):
        if len(rs) < 10: return f"n={len(rs)} 样本不足"
        wins = [r for r in rs if r > 0]
        return f"n={len(rs)} 胜率{100*len(wins)/len(rs):.1f}% 均值{100*st.mean(rs):+.2f}%"
    print(f"{nm} 2026年: T+5 {stat(rs5)} | T+20 {stat(rs20)}")
