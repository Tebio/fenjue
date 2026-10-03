"""多头占比温度终审（2026-09-29）：分年验尸+双段+多窗口+退市股口径一致。
判生死：Q5过热档（减仓侧）与Q1冰点档（加仓侧）是否分年稳定。
"""
import glob
import json
import statistics as st

idx_rows = json.load(open('/opt/data/fenjue/data/index_sh000001.json'))
idx = {r['date']: r['close'] for r in idx_rows}
idates = sorted(idx)

breadth = {}
for fp in glob.glob('/opt/data/fenjue/data/big_kcache/*.json'):
    code = fp.split('/')[-1].split('.')[0]
    if code[0] not in '06' or code.startswith(('300', '301', '688')):
        continue
    bars = json.load(open(fp))
    c = [b['close'] for b in bars]
    for i in range(60, len(bars)):
        d = bars[i]['date']
        if d < '2019-06-01':
            continue
        m5 = sum(c[i - 4:i + 1]) / 5
        m10 = sum(c[i - 9:i + 1]) / 10
        m20 = sum(c[i - 19:i + 1]) / 20
        m60 = sum(c[i - 59:i + 1]) / 60
        b = breadth.setdefault(d, [0, 0])
        b[0] += 1
        if m5 > m10 > m20 > m60:
            b[1] += 1

series = [{'date': d, 'bp': m / t} for d, (t, m) in breadth.items() if t > 1000]
series.sort(key=lambda x: x['date'])
n = len(series)
print(f"序列 {n} 日")

def fwd(d, k):
    i = idates.index(d)
    return idx[idates[i + k]] / idx[d] - 1 if i + k < len(idates) else None

# 滚动250日分位（防全史前视）
rk = {}
for i, s in enumerate(series):
    lo = max(0, i - 250)
    win = [series[j]['bp'] for j in range(lo, i)]
    if len(win) >= 120:
        rk[s['date']] = sum(1 for v in win if v < s['bp']) / len(win)

for K in (5, 10, 20):
    cold, hot, base = [], [], []
    for s in series:
        r = fwd(s['date'], K)
        if r is None or s['date'] not in rk:
            continue
        base.append(r)
        if rk[s['date']] >= 0.90:
            hot.append(r)
        elif rk[s['date']] <= 0.10:
            cold.append(r)
    def f(v):
        return f"胜率{sum(1 for x in v if x > 0) / len(v) * 100:.0f}% 均值{st.mean(v) * 100:+.2f}%" if v else "n=0"
    print(f"T+{K}: 冰点(≤10%分位) {f(cold)} | 基线 {f(base)} | 过热(≥90%分位) {f(hot)}")

print("\n== 分年（T+10，过热档 vs 当年基线）")
years = {}
for s in series:
    r = fwd(s['date'], 10)
    if r is None or s['date'] not in rk:
        continue
    y = s['date'][:4]
    years.setdefault(y, {'hot': [], 'base': []})
    years[y]['base'].append(r)
    if rk[s['date']] >= 0.90:
        years[y]['hot'].append(r)
for y in sorted(years):
    h, b = years[y]['hot'], years[y]['base']
    if h:
        print(f"  {y}: 过热档 n={len(h)} {st.mean(h)*100:+.2f}% vs 基线 {st.mean(b)*100:+.2f}%")
    else:
        print(f"  {y}: 过热档 n=0")

print("\n== 分年（T+10，冰点档 vs 当年基线）")
years2 = {}
for s in series:
    r = fwd(s['date'], 10)
    if r is None or s['date'] not in rk:
        continue
    y = s['date'][:4]
    years2.setdefault(y, {'cold': [], 'base': []})
    years2[y]['base'].append(r)
    if rk[s['date']] <= 0.10:
        years2[y]['cold'].append(r)
for y in sorted(years2):
    c, b = years2[y]['cold'], years2[y]['base']
    if c:
        print(f"  {y}: 冰点档 n={len(c)} {st.mean(c)*100:+.2f}% vs 基线 {st.mean(b)*100:+.2f}%")
