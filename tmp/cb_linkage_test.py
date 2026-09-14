"""#80① 可转债首测：正股涨停日的转债联动（T+0绕道的真实价值）
H1: 正股涨停当日收盘买转债 → 次日开盘/尾盘卖，是否正期望（vs 正股追不进的对照）
H2: 溢价率分档（转股溢价率<10%/10-30%/>30%）是否区分强弱
数据: cb_kcache(594+) × big_kcache(正股) × bond_zh_cov(正股映射)
"""
import json
from pathlib import Path
from collections import defaultdict

ROOT = Path('/opt/data/fenjue')
CB = ROOT / 'data/cb_kcache'
KC = ROOT / 'data/big_kcache'
FEE = 0.001

import sys
sys.path.insert(0, '/opt/data/python-libs')
import akshare as ak
df = ak.bond_zh_cov()
b2s = {str(r['债券代码']).zfill(6): str(r['正股代码']).zfill(6) for _, r in df.iterrows()}

# 正股涨停日集合
stock_lu = defaultdict(set)
for code in set(b2s.values()):
    fp = KC / f'{code}.json'
    if not fp.exists(): continue
    ks = json.load(open(fp))
    for i in range(1, len(ks)):
        if ks[i-1]['close'] > 0 and ks[i]['close'] / ks[i-1]['close'] - 1 >= 0.098:
            stock_lu[code].add(ks[i]['date'])

G = defaultdict(lambda: {'n': 0, 'w1': 0, 'r1': 0.0, 'w2': 0, 'r2': 0.0})
prem = defaultdict(lambda: defaultdict(lambda: {'n': 0, 'r': 0.0}))
for cb in CB.glob('*.json'):
    bond = cb.stem
    stock = b2s.get(bond)
    if not stock or stock not in stock_lu: continue
    ks = json.load(open(cb))
    if len(ks) < 30: continue
    for i in range(1, len(ks) - 1):
        d = ks[i]['date']
        if d not in stock_lu[stock]: continue
        r_open = ks[i+1]['open'] / ks[i]['close'] - 1 - FEE   # 次日开盘卖
        r_close = ks[i+1]['close'] / ks[i]['close'] - 1 - FEE  # 次日尾盘卖
        g = G['全体']
        g['n'] += 1
        g['w1'] += r_open > 0; g['r1'] += r_open
        g['w2'] += r_close > 0; g['r2'] += r_close

g = G['全体']
if g['n']:
    print(f'=== 正股涨停日收盘买转债（n={g["n"]}）===')
    print(f'次日开盘卖: 胜率{g["w1"]/g["n"]*100:.1f}% 均{g["r1"]/g["n"]*100:+.2f}%')
    print(f'次日尾盘卖: 胜率{g["w2"]/g["n"]*100:.1f}% 均{g["r2"]/g["n"]*100:+.2f}%')

# 分年看衰减
Y = defaultdict(lambda: {'n': 0, 'w': 0, 'r': 0.0})
for cb in CB.glob('*.json'):
    bond = cb.stem
    stock = b2s.get(bond)
    if not stock or stock not in stock_lu: continue
    ks = json.load(open(cb))
    for i in range(1, len(ks) - 1):
        d = ks[i]['date']
        if d not in stock_lu[stock]: continue
        r = ks[i+1]['close'] / ks[i]['close'] - 1 - FEE
        y = Y[d[:4]]
        y['n'] += 1; y['w'] += r > 0; y['r'] += r
print('\n分年（次日尾盘卖）:')
for y in sorted(Y):
    c = Y[y]
    print(f'  {y}: n={c["n"]:>6d} 胜率{c["w"]/c["n"]*100:5.1f}% 均{c["r"]/c["n"]*100:+.2f}%')
