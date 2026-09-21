import json, statistics as st
from collections import defaultdict
rows = [json.loads(l) for l in open('data/claims_shadow.jsonl')]
week = [r for r in rows if '2026-09-14' <= r.get('signal_date', '') <= '2026-09-18']
print('本周信号日登记:', len(week))
by_claim = defaultdict(lambda: defaultdict(list))
for r in week:
    for k in ('r1', 'r5'):
        if r.get(k) is not None:
            by_claim[r['claim']][k].append(r[k])
for claim, d in sorted(by_claim.items()):
    out = {}
    for k, rs in d.items():
        if rs:
            wins = sum(1 for x in rs if x > 0)
            out[k] = f"n={len(rs)} 胜率{100*wins/len(rs):.0f}% 均值{100*st.mean(rs):+.2f}%"
    print(f"  {claim}: {out}")
# 本周每天的深档低位信号数 vs 成簇门
days = defaultdict(int)
for r in rows:
    if '2026-09-14' <= r.get('signal_date', '') <= '2026-09-18' and 'LIMITDOWN' in r['claim']:
        days[r['signal_date']] += 1
print('本周深档低位信号数/日（成簇门≥5）:', dict(sorted(days.items())))
