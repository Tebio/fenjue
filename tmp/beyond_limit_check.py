import json, sys, statistics as st
sys.path.insert(0, 'engine')
import law_pipeline as lp

FEE = 0.0015
stocks = lp.load_universe()
lp.build_xsection(stocks)
det = lp.REGISTRY["跌停接_MA60下"]
hi = max(lp.HORIZONS) + 1
normal, beyond = [], []
for code, d in stocks.items():
    c, o, n = d["c"], d["o"], d["n"]
    for i in range(lp.START, n - hi):
        if o[i + 1] <= 0:
            continue
        try:
            if not det(d, i):
                continue
        except Exception:
            continue
        pct = c[i] / c[i - 1] - 1
        ei = i + 1
        if ei + 5 >= n or o[ei] <= 0 or o[ei] <= c[i] * 0.905:
            continue
        r = c[ei + 5] / o[ei] - 1 - FEE
        # 主板普通跌停 -10%（ST -5% 已名义剔除不了），<-11.5% = 物理上不可能是普通跌停
        # = 复牌首日/退市整理/除权假摔
        (beyond if pct < -0.115 else normal).append(r)

def stat(rs):
    wins = [r for r in rs if r > 0]
    return {"n": len(rs), "胜率%": round(100*len(wins)/len(rs),1), "均值%": round(100*st.mean(rs),2)} if rs else None
print("普通跌停(≥-11.5%):", stat(normal))
print("超限暴跌(<-11.5%，复牌/退市整理/除权):", stat(beyond))
print(f"超限占比: {len(beyond)/(len(normal)+len(beyond))*100:.2f}%")
