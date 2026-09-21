import json
from collections import defaultdict
mmap = json.load(open('/opt/data/fenjue/data/industry_map.json'))
code2ind = {str(k).zfill(6): v['industry'] for k, v in mmap.items() if isinstance(v, dict) and v.get('industry')}
hits = defaultdict(list)
import os
p = '/opt/data/fenjue/data/news_archive.jsonl'
if os.path.exists(p):
    for line in open(p):
        try:
            r = json.loads(line)
        except Exception:
            continue
        txt = json.dumps(r, ensure_ascii=False)
        dt = r.get('date', r.get('time', ''))[:10]
        if dt < '2026-09-10':
            continue
        for nm in ('国光连锁', '中百集团', '天目湖', '创新医疗', '零售', '旅游', '医疗'):
            if nm in txt:
                hits[nm].append(f"{dt} {txt[:80]}")
else:
    print('news_archive.jsonl 不存在——归档管道待查')
batch = [('605188', '国光连锁'), ('000759', '中百集团'), ('603136', '天目湖'), ('002173', '创新医疗'),
         ('600666', '奥瑞德'), ('000010', '*ST美丽'), ('002842', '翔鹭钨业')]
for code, nm in batch:
    ind = code2ind.get(code, '?')
    print(f'{nm}({code}) 行业={ind}')
    for h in hits.get(nm, [])[:2]:
        print(f'   📰 {h}')
# 板块梯队（9/16 当日同行业涨停数——用 big_kcache 快算）
import glob
def boards_on(ind_target, day):
    n = 0
    for f in glob.glob('/opt/data/fenjue/data/big_kcache/*.json'):
        code = f.split('/')[-1][:6]
        if code2ind.get(code) != ind_target:
            continue
        ks = json.load(open(f))
        for j in range(1, len(ks)):
            if ks[j]['date'] == day and ks[j]['close'] / ks[j - 1]['close'] - 1 >= 0.098:
                n += 1
    return n
for code, nm in batch[:4]:
    ind = code2ind.get(code, '?')
    print(f'{nm}: 9/16 行业梯队 {boards_on(ind, "2026-09-16")} 只涨停')