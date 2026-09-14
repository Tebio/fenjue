"""10:37 梯队实况：哪些板块≥3只涨停、池内票在其中、能买不能买（封死=买不进）"""
import json, sys, urllib.request, time
from pathlib import Path
sys.path.insert(0, '/opt/data/scripts')
from stock_radar import hq, clear_proxy, _SECTOR_STOP

ROOT = Path('/opt/data/fenjue')
clear_proxy()
stocks = json.loads((ROOT / 'data/main_board_codes.json').read_text())['stocks']
codes = [s['code'] for s in stocks]
names = {s['code']: s.get('name', '') for s in stocks}
q = hq([('sh' if c.startswith('6') else 'sz') + c for c in codes])

rows = []
for c in codes:
    d = q.get(c)
    if not d or d['prev'] <= 0 or d['price'] <= 0: continue
    d['code'] = c
    d['pct'] = (d['price'] / d['prev'] - 1) * 100
    d['limit'] = round(d['prev'] * (1.05 if 'ST' in d['name'] else 1.1), 2)
    d['sealed'] = d['pct'] >= 9.8 and abs(d['price'] - d['limit']) < 0.011
    rows.append(d)

lu = [r for r in rows if r['sealed']]
sec_map = json.loads(sorted(Path(ROOT / 'data/hithink/sectors').glob('stock_sectors_*.json'))[-1].read_text())
sec_lu = {}
for r in lu:
    for e in sec_map.get(r['code'], []):
        nm = e.get('name')
        if nm and nm not in _SECTOR_STOP:
            sec_lu.setdefault(nm, []).append(r)

wp = json.loads((ROOT / 'data/watch_pool.json').read_text()).get('pool', [])
pool_codes = {str(e['code']).zfill(6): e for e in wp}

print(f"涨停总数: {len(lu)}  跌停: {sum(1 for r in rows if r['pct'] <= -9.8)}")
print(f"\n=== 梯队成型板块（≥3只涨停）共 {sum(1 for v in sec_lu.values() if len(v) >= 3)} 个 ===")
for nm, arr in sorted(sec_lu.items(), key=lambda x: -len(x[1])):
    if len(arr) < 3: continue
    members = sorted(arr, key=lambda x: -x['amt'])[:5]
    # 池内票
    pool_in = []
    for c0, e0 in pool_codes.items():
        if any(x.get('name') == nm for x in sec_map.get(c0, [])):
            d0 = q.get(c0)
            if d0:
                p0 = (d0['price'] / d0['prev'] - 1) * 100
                # 能买吗：已封死=买不进；未封+涨幅5-9.8=排队窗口；<5%=还没动
                if d0['pct'] >= 9.8 and abs(d0['price'] - round(d0['prev']*1.1, 2)) < 0.011:
                    can = '❌已封死买不进'
                elif 5 <= p0 < 9.8:
                    can = '🟡冲板中·可排队（开缝才成交）'
                elif p0 < 2:
                    can = '⚪还没动（梯队热它没动=弱，别碰）'
                else:
                    can = f'⚪+{p0:.1f}% 跟随中（非首板不追）'
                pool_in.append(f"{e0['name']} {p0:+.1f}% {can}")
    print(f"\n「{nm}」{len(arr)}只涨停: {'/'.join(m['name'] for m in members)}")
    for p in pool_in[:4]:
        print(f"   池内: {p}")
