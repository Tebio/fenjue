"""#80① 股债联动 m60 终审：正股封板时刻买转债（无未来函数口径）
事件：正股 m60 首次触及涨停（bar close ≥ 昨收×1.098）→ 转债下一根 60min bar 开盘买 → 当日尾盘卖
昨收：big_kcache 日线。窗口：m60 两年。费用 0.1%。样本 top150 转债。
"""
import json, time, sys, urllib.request
from pathlib import Path
from collections import defaultdict

ROOT = Path('/opt/data/fenjue')
CB = ROOT / 'data/cb_kcache'
M60 = ROOT / 'data/m60_cache'
KC = ROOT / 'data/big_kcache'
sys.path.insert(0, '/opt/data/python-libs')
import akshare as ak

df = ak.bond_zh_cov()
b2s = {str(r['债券代码']).zfill(6): str(r['正股代码']).zfill(6) for _, r in df.iterrows()}

def sina_m60(symbol):
    url = ('https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/'
           f'CN_MarketData.getKLineData?symbol={symbol}&scale=60&ma=no&datalen=1970')
    req = urllib.request.Request(url, headers={'Referer': 'https://finance.sina.com.cn/'})
    for _ in range(3):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=15).read())
        except Exception:
            time.sleep(2)
    return None

import os
for k in list(os.environ):
    if 'proxy' in k.lower(): os.environ.pop(k)

FEE = 0.001
G = defaultdict(lambda: {'n': 0, 'w': 0, 'r': 0.0})
G_seal = defaultdict(lambda: {'n': 0, 'w': 0, 'r': 0.0})

events_cnt = []
for cb in CB.glob('*.json'):
    stock = b2s.get(cb.stem)
    if not stock: continue
    events_cnt.append((len(json.load(open(cb))), cb.stem, stock))
events_cnt.sort(reverse=True)
todo = events_cnt[:150]

for rank, (_, bond, stock) in enumerate(todo):
    sp = M60 / f'{stock}.json'
    dp = KC / f'{stock}.json'
    if not sp.exists() or not dp.exists(): continue
    daily = json.load(open(dp))
    prev_close = {daily[i]['date']: daily[i-1]['close'] for i in range(1, len(daily))}
    sms = json.load(open(sp))
    bp = sina_m60(('sh' if bond.startswith('11') else 'sz') + bond)
    if not bp: continue
    time.sleep(0.7)
    bday = defaultdict(list)
    for b in bp: bday[b['day'][:10]].append(b)
    sday = defaultdict(list)
    for b in sms: sday[b['day'][:10]].append(b)
    for d, bars in sday.items():
        pc = prev_close.get(d)
        if not pc or d not in bday: continue
        sealed = None
        for bi, b in enumerate(bars):
            if float(b['close']) / pc - 1 >= 0.098:
                sealed = bi
                break
        if sealed is None: continue
        bbars = bday[d]
        if len(bbars) < 2: continue
        ei = min(sealed + 1, len(bbars) - 1)
        entry = float(bbars[ei]['open'])
        exitp = float(bbars[-1]['close'])
        if entry <= 0: continue
        r = exitp / entry - 1 - FEE
        g = G['全体']; g['n'] += 1; g['w'] += r > 0; g['r'] += r
        held = float(bars[-1]['close']) / pc - 1 >= 0.098  # 正股封到收盘?
        g2 = G_seal['封住' if held else '炸开']
        g2['n'] += 1; g2['w'] += r > 0; g2['r'] += r
    if (rank + 1) % 30 == 0:
        print(f'[{rank+1}/{len(todo)}] 事件n={G["全体"]["n"]}', flush=True)

for k in ('全体',):
    g = G[k]
    if g['n']:
        print(f'\n=== 正股封板时刻下一根bar买转债→尾盘（n={g["n"]}）===')
        print(f'胜率 {g["w"]/g["n"]*100:.1f}%  均 {g["r"]/g["n"]*100:+.2f}%')
for k, g in G_seal.items():
    if g['n']:
        print(f'{k}: n={g["n"]:>5d} 胜率{g["w"]/g["n"]*100:5.1f}% 均{g["r"]/g["n"]*100:+.2f}%')
