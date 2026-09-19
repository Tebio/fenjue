import json, glob, sys, statistics as st
from collections import defaultdict
sys.path.insert(0, 'engine')
import law_pipeline as lp

FEE = 0.0015
QEND = {"03-31": "05-01", "06-30": "09-01", "09-30": "11-01", "12-31": "99-99"}
# 披露截止（保守PIT）：Q1→5/1，中报→9/1，Q3→11/1，年报→次年5/1
def usable_from(end):
    y, md = end[:4], end[5:10]
    suf = QEND.get(md)
    if suf is None:
        return None
    if suf == "99-99":
        return f"{int(y)+1}-05-01"
    return f"{y}-{suf}"

def chg_dir(r):
    c = r.get("HOLD_NUM_CHANGE")
    if c in (None, "不变", ""):
        return 0
    if c == "新进":
        return 1
    try:
        v = float(c)
        return 1 if v > 0 else (-1 if v < 0 else 0)
    except (TypeError, ValueError):
        return 0

# 每股票：[(usable_date, dir)]（只看 HKSCC 有限公司本体，剔除(H股)代理人变体——B-N1 教训）
north = {}
for fp in glob.glob('data/north_holders/*.json'):
    code = fp.split('/')[-1][:6]
    recs = []
    for r in json.load(open(fp)):
        if r["HOLDER_NAME"] not in ("香港中央结算有限公司", "香港中央结算有限公司(A股)"):
            continue
        end = r["END_DATE"][:10]
        u = usable_from(end)
        if u:
            recs.append((u, chg_dir(r), end))
    if recs:
        recs.sort()
        north[code] = recs

def north_at(code, dt):
    recs = north.get(code)
    if not recs:
        return None
    cur = None
    for u, d, e in recs:
        if u <= dt:
            cur = d
        else:
            break
    return cur

stocks = lp.load_universe()
lp.build_xsection(stocks)
groups = defaultdict(lambda: defaultdict(list))
for cname, det in (("跌停底座", lp.REGISTRY["跌停接_MA60下"]),
                   ("TD9旗舰", lp.REGISTRY["组合_跌停低_TD9买_输家250"])):
    for code, d in stocks.items():
        n = d["n"]; c, o = d["c"], d["o"]
        for i in range(lp.START, n - 22):
            if o[i + 1] <= 0:
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
                    r = c[ei + h] / o[ei] - 1 - FEE
                    groups[cname][(nd, h)].append(r)

def stat(rs):
    if len(rs) < 15: return None
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    odds = st.mean(wins)/abs(st.mean(losses)) if wins and losses else None
    return {"n": len(rs), "胜率%": round(100*len(wins)/len(rs),1),
            "均值%": round(100*st.mean(rs),2), "赔率": round(odds,2) if odds else None}
for cname in groups:
    print(f"== {cname} ==")
    for nd, label in ((1, "北向增持"), (0, "不变/无变动"), (-1, "北向减持"), (None, "无北向记录")):
        for h in (5, 20):
            s = stat(groups[cname][(nd, h)])
            print(f"  {label} T+{h}: {s}")
