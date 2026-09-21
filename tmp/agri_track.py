"""农业板块 2026 轨迹 + 「板块起色必有后文」假设检验。
Part1: 农业（A01+A03+A04+A05+C13）等权日指数 2026YTD，找底部/启动/疯狂各阶段。
Part2: 全行业「起色日」跟进测试：板块日涨幅≥+2% 且全行业排名前5 → 5/10/20日后
       该板块超额收益 vs 全行业均值。检验「有起色→还有动静」是否统计成立。
"""
import json, glob, statistics as st
from collections import defaultdict

m = json.load(open('data/industry_map.json'))
AGRI = {'A01农业', 'A03畜牧业', 'A04渔业', 'A05农、林、牧、渔专业及辅助性活动', 'C13农副食品加工业'}
code2ind = {str(k).zfill(6): v['industry'] for k, v in m.items() if isinstance(v, dict) and v.get('industry')}
agri_codes = [c for c, i in code2ind.items() if i in AGRI]
print(f'农业标的 {len(agri_codes)} 只')

# 每日板块收益（等权）
stock_daily = {}
for f in glob.glob('data/big_kcache/*.json'):
    code = f.split('/')[-1][:6]
    if code not in code2ind:
        continue
    ks = json.load(open(f))
    rows = []
    for j in range(1, len(ks)):
        if ks[j]['date'] < '2025-11-01':
            continue
        pc = float(ks[j - 1]['close'])
        if pc > 0:
            rows.append((ks[j]['date'], float(ks[j]['close']) / pc - 1))
    if rows:
        stock_daily[code] = dict(rows)

days = sorted({d for rows in stock_daily.values() for d in rows if d >= '2026-01-01'})
ind_daily = defaultdict(dict)  # ind -> day -> mean pct
for d in days:
    buckets = defaultdict(list)
    for code, rmap in stock_daily.items():
        if d in rmap:
            buckets[code2ind[code]].append(rmap[d])
    for ind, v in buckets.items():
        if len(v) >= 5:
            ind_daily[ind][d] = st.mean(v)

# 农业合并
agri_daily = {}
for d in days:
    v = [stock_daily[c][d] for c in agri_codes if d in stock_daily.get(c, {})]
    if v:
        agri_daily[d] = st.mean(v)

# 指数化（2026-01-02=100）
idx = 100.0
curve = []
for d in days:
    r = agri_daily.get(d, 0)
    idx *= (1 + r)
    curve.append((d, idx, r))
lo = min(curve, key=lambda x: x[1])
hi = max(curve, key=lambda x: x[1])
print(f'\n== 农业等权指数 2026（1/2=100）==')
print(f'底部: {lo[0]} @ {lo[1]:.1f}')
print(f'最高: {hi[0]} @ {hi[1]:.1f}')
print(f'最新: {curve[-1][0]} @ {curve[-1][1]:.1f}')
print('\n关键月份:')
month_mark = {}
for d, v, r in curve:
    mk = d[:7]
    month_mark.setdefault(mk, []).append((d, v))
for mk, rows in sorted(month_mark.items()):
    print(f'  {mk}: {rows[0][1]:.1f} → {rows[-1][1]:.1f} ({100*(rows[-1][1]/rows[0][1]-1):+.1f}%)')
print('\n农业日涨幅≥+2% 的日子:')
for d, v, r in curve:
    if r >= 0.02:
        print(f'  {d} {100*r:+.1f}%')

# Part2: 起色日跟进测试（2026YTD，全行业）
print('\n== 「起色日」跟进测试（板块日涨≥2%且排名前5）==')
fw = {5: [], 10: [], 20: []}
base = {5: [], 10: [], 20: []}
events = []
di = {d: i for i, d in enumerate(days)}
for d in days[:-20]:
    ranked = sorted(ind_daily.keys(), key=lambda k: ind_daily[k].get(d, -9), reverse=True)
    mkt = st.mean(ind_daily[k][d] for k in ind_daily if d in ind_daily[k])
    for ind in ranked[:5]:
        r = ind_daily[ind].get(d, 0)
        if r < 0.02:
            continue
        i = di[d]
        ev = {'day': d, 'ind': ind}
        for h in (5, 10, 20):
            if i + h >= len(days):
                continue
            d2 = days[i + h]
            # 板块区间收益 vs 市场区间收益
            sr = sum(ind_daily[ind].get(days[i + k], 0) for k in range(1, h + 1))
            mr = sum(st.mean(ind_daily[x].get(days[i + k], 0) for x in ind_daily if days[i + k] in ind_daily[x]) for k in range(1, h + 1))
            fw[h].append(sr - mr)
            ev[h] = sr - mr
        events.append(ev)
print(f'起色事件 {len(events)} 次')
for h in (5, 10, 20):
    v = fw[h]
    if v:
        w = sum(1 for x in v if x > 0)
        print(f'  {h}日后超额: 均值 {100*st.mean(v):+.2f}% 胜率(跑赢市场) {100*w/len(v):.0f}% (n={len(v)})')
print('\n农业的起色事件:')
for ev in events:
    if ev['ind'] in AGRI:
        print(f"  {ev['day']} {ev['ind']}: " + ' '.join(f"{h}日{100*ev[h]:+.1f}%" for h in (5, 10, 20) if h in ev))