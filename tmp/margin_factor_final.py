"""拥挤度因子正式终审 v2（性能版：预计算全股票 fwd20 映射，O(1) 查表）。"""
import glob
import json
import sqlite3
import statistics as st

FEE = 0.0015
fwd = {}  # (code, date) -> fwd20 net
for fp in glob.glob('/opt/data/fenjue/data/big_kcache/*.json'):
    code = fp.split('/')[-1].split('.')[0]
    if code[0] not in '06' or code.startswith(('300', '301', '688')):
        continue
    bars = json.load(open(fp))
    idx = {b['date']: i for i, b in enumerate(bars)}
    for i, b in enumerate(bars[:-21]):
        nb = bars[i + 1]
        if nb['open'] > 0:
            fwd[(code, b['date'])] = bars[i + 21]['close'] / nb['open'] - 1 - FEE
print(f"fwd 映射 {len(fwd)}")

con = sqlite3.connect('/opt/data/fenjue/data/margin_stock.db')
rows = con.execute("SELECT date, code, rzyezb, sz FROM m WHERE rzyezb IS NOT NULL AND sz > 0").fetchall()
con.close()
by_date = {}
for d, c, rz, sz in rows:
    if (c, d) in fwd:
        by_date.setdefault(d, []).append((c, rz, sz))
print(f"有效横截面 {len(by_date)} 日")

periods = {'全窗': ('2019-01-01', '2026-09-28'), '2019-2021': ('2019-01-01', '2021-12-31'),
           '2022-2024': ('2022-01-01', '2024-12-31'), '2025-2026': ('2025-01-01', '2026-09-28')}
agg = {p: {'rz': [[] for _ in range(5)], 'cap': [[] for _ in range(5)]} for p in periods}
yearly = {}
terc = {'小市值': [[] for _ in range(5)], '大市值': [[] for _ in range(5)]}

for d in sorted(by_date)[:-25]:
    items = by_date[d]
    if len(items) < 500:
        continue
    n = len(items)
    for p, (a, b) in periods.items():
        if not (a <= d <= b):
            continue
        for key, store in [('rz', agg[p]['rz']), ('cap', agg[p]['cap'])]:
            ki = 1 if key == 'rz' else 2
            srt = sorted(items, key=lambda x: x[ki])
            for i, x in enumerate(srt):
                store[min(4, i * 5 // n)].append(fwd[(x[0], d)])
    srt = sorted(items, key=lambda x: x[1])
    yearly.setdefault(d[:4], [[] for _ in range(5)])
    for i, x in enumerate(srt):
        yearly[d[:4]][min(4, i * 5 // n)].append(fwd[(x[0], d)])
    srt_sz = sorted(items, key=lambda x: x[2])
    for grp, lo, hi in [('小市值', 0, n // 3), ('大市值', 2 * n // 3, n)]:
        sub = sorted(srt_sz[lo:hi], key=lambda x: x[1])
        m = len(sub)
        for i, x in enumerate(sub):
            terc[grp][min(4, i * 5 // m)].append(fwd[(x[0], d)])

def show5(bkts, label):
    cells = []
    for b in bkts:
        if b:
            wr = sum(1 for x in b if x > 0) / len(b) * 100
            cells.append(f"{wr:.0f}%/{st.mean(b)*100:+.2f}")
        else:
            cells.append("-")
    print(f"  {label}: " + " | ".join(cells))

print("\n== 拥挤度五分位 → T+20（Q1低→Q5高）")
for p in periods:
    show5(agg[p]['rz'], p)
print("== 流通市值五分位 → T+20（Q1小→Q5大）")
show5(agg['全窗']['cap'], '全窗')
print("\n== 拥挤度分年（T+20 均值%）")
for y in sorted(yearly):
    print(f"  {y}: " + " | ".join(f"{st.mean(b)*100:+.2f}" if b else "-" for b in yearly[y]))
print("\n== 市值分层内拥挤度梯度")
for grp in terc:
    show5(terc[grp], grp)
