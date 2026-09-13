import json
from pathlib import Path
from collections import Counter

ROOT = Path('/opt/data/fenjue')
DAY = '2026-09-11'

# ① 周五恐慌深度 roster（PANIC_DEPTH 档位，周一开盘候选）
codes = [str(s['code']).zfill(6) for s in json.load(open(ROOT / 'data/main_board_codes.json'))['stocks']]
bands = Counter()
deep = []
for c in codes:
    fp = ROOT / 'data' / 'big_kcache' / f'{c}.json'
    if not fp.exists(): continue
    try: ks = json.load(open(fp))
    except Exception: continue
    if len(ks) < 61 or ks[-1]['date'] != DAY: continue
    pct = (ks[-1]['close'] / ks[-2]['close'] - 1) * 100
    if pct <= -3: bands['-3~-5' if pct > -5 else '-5~-7' if pct > -7 else '-7~-9.5' if pct > -9.5 else '≤-9.5'] += 1
    if pct <= -9.5:
        ma60 = sum(k['close'] for k in ks[-60:]) / 60
        deep.append((c, round(pct, 2), round((ks[-1]['close']/ma60 - 1)*100, 1)))

print('=== 周五(9/11)恐慌深度 roster ===')
for b in ['-3~-5', '-5~-7', '-7~-9.5', '≤-9.5']:
    print(f'  {b}%: {bands.get(b, 0)} 只')
print(f'深档(≤-9.5%) {len(deep)} 只: {deep[:15]}')

# ② B5 分 regime 实测（现有回测json）
bt = json.load(open(ROOT / 'data/banlu_backtest_20260913.json'))
for k in bt:
    if 'regime' in k.lower() or 'B5' in k:
        print(f'\n{k}:', json.dumps(bt[k], ensure_ascii=False)[:300])
