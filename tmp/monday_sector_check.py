import json, glob
from pathlib import Path
from statistics import mean

ROOT = Path('/opt/data/fenjue')
IDX = ROOT / 'data/hithink/index_hist'
sec_map = json.load(open(sorted(glob.glob(str(ROOT / 'data/hithink/sectors/stock_sectors_*.json')))[-1]))
catalog = {e['thscode']: e['name'] for e in json.load(open(sorted(glob.glob(str(ROOT / 'data/hithink/sectors/catalog_*.json')))[-1]))['item']}

def idx_bars(code):
    fp = IDX / f'{code}.json'
    if not fp.exists(): return None
    return json.load(open(fp))['item']

def trend(bars):
    if not bars or len(bars) < 61: return None
    c = bars[-1]['close']
    ma60 = mean(b['close'] for b in bars[-60:])
    ma20 = mean(b['close'] for b in bars[-20:])
    r5 = c / bars[-6]['close'] - 1
    r20 = c / bars[-21]['close'] - 1
    last5 = [(b['date'], round((b['close']/bars[i-1]['close']-1)*100, 2)) for i, b in enumerate(bars[-5:], start=len(bars)-5)]
    return dict(close=c, vs_ma60=(c/ma60-1)*100, vs_ma20=(c/ma20-1)*100, r5=r5*100, r20=r20*100, last5=last5)

# ① 周五 B5 五票的板块体检
sig = [json.loads(l) for l in open(ROOT / 'data/banlu_signals.jsonl') if l.strip()]
fri = [s for s in sig if s['date'] == '2026-09-11']
print('=== 周五 B5 信号票板块体检（指数数据至9/10）===')
for s in fri:
    secs = [e for e in sec_map.get(s['code'], []) if e.get('name') not in
            {'融资融券','沪股通','深股通','国企改革','专精特新','MSCI概念','标普概念','富时罗素','证金持股'}]
    print(f"\n{s['name']}({s['code']}) 触发价{s['trigger_px']} 收{s['close']} {'已封板' if s['sealed'] else '未封'}")
    for e in secs[:3]:
        t = trend(idx_bars(e['thscode']))
        if t:
            print(f"  {e['name']}: MA60{t['vs_ma60']:+.1f}% 20日{t['r20']:+.1f}% 5日{t['r5']:+.1f}%")

# ② 全市场板块截面：9/10 单日暴跌≥4% 的板块（9/11个股大跌的板块背景）
print('\n=== 9/10 板块跌幅榜（≤-3%，共扫描390个）===')
drops = []
for fp in sorted(IDX.glob('*.json')):
    bars = json.load(open(fp))['item']
    if len(bars) < 2: continue
    pct = (bars[-1]['close']/bars[-2]['close']-1)*100
    if pct <= -3:
        drops.append((pct, catalog.get(fp.stem, fp.stem)))
drops.sort()
for pct, name in drops[:15]:
    print(f'  {name} {pct:+.2f}%')
print(f'共 {len(drops)} 个板块 9/10 跌超3%')
