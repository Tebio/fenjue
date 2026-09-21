import json, glob
from collections import Counter
stat = Counter()
for fp in glob.glob('data/m60_cache/*.json'):
    rows = json.load(open(fp))
    last = rows[-1]['day'] if rows else ''
    if last.startswith('2026-09-18'):
        stat[last[11:16]] += 1
    else:
        stat['older:' + last[:10]] += 1
print('9/18 最后 bar 时刻分布:', stat.most_common(10))
