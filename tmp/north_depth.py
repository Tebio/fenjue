import json, glob
from collections import Counter
ends = Counter()
hkscc_names = Counter()
depths = []
for fp in glob.glob('data/north_holders/*.json'):
    rows = json.load(open(fp))
    qs = sorted({r['END_DATE'][:10] for r in rows})
    depths.append(len(qs))
    for r in rows:
        if '香港中央结算' in r['HOLDER_NAME']:
            hkscc_names[r['HOLDER_NAME']] += 1
            ends[r['END_DATE'][:10]] += 1
print('每股票覆盖季度数分布:', Counter(depths))
print('HKSCC 名称变体:', hkscc_names.most_common(5))
print('HKSCC 记录按季度分布(最近10):', sorted(ends.items())[-10:])
print('HKSCC 记录按季度分布(最早5):', sorted(ends.items())[:5])
