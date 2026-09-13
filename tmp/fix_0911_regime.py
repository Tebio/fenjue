import json
from pathlib import Path
from collections import Counter

ROOT = Path('/opt/data/fenjue')
DAY = '2026-09-11'

# 全主板名单
codes = [str(s['code']).zfill(6) for s in json.load(open(ROOT / 'data/main_board_codes.json'))['stocks']]
# 行业映射
imap = json.load(open(ROOT / 'data/industry_map.json'))
def sector_of(c):
    v = imap.get(c) or imap.get(c.lstrip('0')) or ''
    if isinstance(v, dict): v = v.get('industry', '')
    return v or '其他'

boards, limit_downs = [], 0
for c in codes:
    fp = ROOT / 'data' / 'big_kcache' / f'{c}.json'
    if not fp.exists(): continue
    try: ks = json.load(open(fp))
    except Exception: continue
    if len(ks) < 2 or ks[-1]['date'] != DAY: continue
    pct = (ks[-1]['close'] / ks[-2]['close'] - 1) * 100
    if pct >= 9.8:
        boards.append({'code': c, 'name': '', 'pct': round(pct, 3), 'cap': 0})
    elif pct <= -9.8:
        limit_downs += 1

sec = Counter(sector_of(b['code']) for b in boards)
top_conc = max(sec.values()) / len(boards) if boards else 0
stats = {'limit_ups': len(boards), 'limit_downs': limit_downs,
         'small_cap_board_ratio': None, 'top_sector_concentration': round(top_conc, 2)}
print(f"9/11 真实重算: 涨停 {len(boards)} 跌停 {limit_downs} 集中度 {top_conc:.2f}")
print('top sectors:', sec.most_common(5))

# 与污染条目对比
log = [json.loads(l) for l in open(ROOT / 'data/regime_log.jsonl') if l.strip()]
bad = [r for r in log if r['date'] == DAY][0]
print(f"污染条目: 涨停 {bad['stats']['limit_ups']} 跌停 {bad['stats']['limit_downs']} regime={bad['regime']}")

# regime 重判（对齐 regime_meter 规则：读源码阈值）
import re
src = open(ROOT / 'engine/regime_meter.py').read()
m = re.search(r'def judge.*?(?=\ndef )', src, re.S)
print('--- judge 规则片段 ---')
print(m.group(0)[:800] if m else 'judge not found')
