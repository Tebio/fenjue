import json, glob, re
from collections import Counter
# A. m60 每日 bar 数与时刻分布（尾盘 15:00 bar 是否缺失）
times = Counter()
bars_per_day = Counter()
for code in ['600519', '000001', '601137', '002163']:
    rows = json.load(open(f'data/m60_cache/{code}.json'))
    byday = {}
    for r in rows:
        byday.setdefault(r['day'][:10], []).append(r['day'][11:16])
    for dt, ts in list(byday.items())[-5:]:
        bars_per_day[len(ts)] += 1
        for t in ts:
            times[t] += 1
print('bar 时刻分布:', times.most_common(8))
print('每日 bar 数分布(最近5日x4只):', bars_per_day)
# B. PEAD 注册状态
import yaml
reg = yaml.safe_load(open('data/claims_registry.yaml'))['claims']
print('PEAD 主张:', [c['id'] for c in reg if 'PEAD' in c['id']])
# E. 影子桥是否动态读 claims_registry（新5条在不在）
