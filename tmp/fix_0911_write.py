import json
from pathlib import Path
from collections import Counter

ROOT = Path('/opt/data/fenjue')
DAY = '2026-09-11'

pool = {str(s['code']).zfill(6): s.get('name', '') for s in json.load(open(ROOT / 'data/main_board_codes.json'))['stocks']}
imap = json.load(open(ROOT / 'data/industry_map.json'))
def sector_of(c):
    v = imap.get(c) or ''
    if isinstance(v, dict): v = v.get('industry', '')
    return v or '其他'

boards, limit_downs = [], 0
for c, nm in pool.items():
    fp = ROOT / 'data' / 'big_kcache' / f'{c}.json'
    if not fp.exists(): continue
    try: ks = json.load(open(fp))
    except Exception: continue
    if len(ks) < 2 or ks[-1]['date'] != DAY: continue
    pct = (ks[-1]['close'] / ks[-2]['close'] - 1) * 100
    if pct >= 9.8:
        boards.append({'code': c, 'name': nm, 'pct': round(pct, 3), 'cap': 0})
    elif pct <= -9.8:
        limit_downs += 1

sec = Counter(sector_of(b['code']) for b in boards)
top_conc = round(max(sec.values()) / len(boards), 2) if boards else 0

# 指数
idx = json.load(open(ROOT / 'data/big_kcache/000001.json'))
i = next(j for j, r in enumerate(idx) if r['date'] == DAY)
idx_pct = round((idx[i]['close'] / idx[i-1]['close'] - 1) * 100, 2)

stats = {'limit_ups': len(boards), 'limit_downs': limit_downs,
         'small_cap_board_ratio': 0.74,  # 沿用污染条目的cap分布口径无法重建，标注不可信
         'top_sector_concentration': top_conc, 'index_pct': idx_pct,
         'top_sectors': [[k, v] for k, v in sec.most_common(5)]}

# classify 复刻（engine/regime_meter.py 规则）
n_board = len(boards)
if n_board >= 60 and top_conc >= 0.22: regime = '主线期'
elif n_board >= 40 and top_conc < 0.22: regime = '妖股期'
elif limit_downs >= 20 or (n_board < 30 and idx_pct < -1.0): regime = '恐慌期'
else: regime = '平淡期'

fixed = {'date': DAY, 'regime': regime, 'stats': stats, 'boards': boards,
         '_corrected': '2026-09-13 夜 K3 修复：原条目吃 9/10 缓存快照（boards/跌停数错），'
                       '本条由 big_kcache 重建；small_cap_board_ratio 沿用原值仅供参考'}

logp = ROOT / 'data/regime_log.jsonl'
lines = [json.loads(l) for l in open(logp) if l.strip()]
out = [fixed if r['date'] == DAY else r for r in lines]
open(logp, 'w').write(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in out))
print(f"9/11 修正完成: 平淡期 → {regime}（涨停{n_board} 跌停{limit_downs} 指数{idx_pct}% 集中{top_conc}）")
print(f"top5: {stats['top_sectors']}")
