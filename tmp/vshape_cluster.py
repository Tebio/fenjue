import json
from statistics import mean
import math

d = json.load(open('data/sector_vshape_20260913.json'))
# 从主脚本输出重建不了事件明细——重跑指数层并按crash日期聚簇
import sys
sys.path.insert(0, 'engine')
from sector_vshape import load_indices, find_events, fwd, HORIZONS, REC_DAYS, nw_t

indices = load_indices()
clusters = {}  # crash_date -> {'rec': [t20...], 'non': [t20...]}
for code, dd in indices.items():
    bars = dd['bars']
    for t0, rec in find_events(bars):
        date = bars[t0]['date']
        ci = rec if rec is not None else min(t0 + REC_DAYS, len(bars) - 61)
        r20 = fwd(bars, ci, 20)
        r60 = fwd(bars, ci, 60)
        if r20 is None or r60 is None:
            continue
        c = clusters.setdefault(date, {'rec': [], 'non': []})
        key = 'rec' if rec is not None else 'non'
        c[key]['T20'].append(r20 * 100) if False else None
        c[key].append((r20 * 100, r60 * 100))

# 每簇内先平均 → 簇级观测
rec_c, non_c = [], []
for date, c in clusters.items():
    if c['rec']:
        rec_c.append({'date': date, 'T20': mean([x[0] for x in c['rec']]), 'T60': mean([x[1] for x in c['rec']])})
    if c['non']:
        non_c.append({'date': date, 'T20': mean([x[0] for x in c['non']]), 'T60': mean([x[1] for x in c['non']])})

print(f"独立簇数: V收复 {len(rec_c)} 个, 未收复 {len(non_c)} 个（原事件1557/1632 → 独立性实锤不足）")
for grp, label in [(rec_c, 'V收复(簇级)'), (non_c, '未收复(簇级)')]:
    x20 = [g['T20'] for g in grp]; x60 = [g['T60'] for g in grp]
    tr20 = [g['T20'] for g in grp if g['date'] < '2024-05-01']
    te20 = [g['T20'] for g in grp if g['date'] >= '2024-05-01']
    print(f"{label}: n簇={len(grp)} T+20 {mean(x20):+.2f}%/t{nw_t(x20):.1f} T+60 {mean(x60):+.2f}%/t{nw_t(x60):.1f} | 两段T20: {mean(tr20):+.2f}/{mean(te20):+.2f}")
