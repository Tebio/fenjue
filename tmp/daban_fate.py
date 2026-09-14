"""冲板命运统计：冲到+7/+9.8没封上的当天回落多少？封上的次日继续红概率？
kcache 8年主板，分时代（19-22 / 23-26）"""
import json
from pathlib import Path
from collections import defaultdict

KC = Path('/opt/data/fenjue/data/big_kcache')
paths = [p for p in KC.glob('*.json') if p.stem[:2] in ('60', '00')]

def cell(): return {'n': 0, 'fade_sum': 0.0, 'red1': 0, 'ret1_sum': 0.0}
G = defaultdict(cell)

for fp in paths:
    try: ks = json.load(open(str(fp)))
    except Exception: continue
    for t in range(1, len(ks) - 1):
        prev = ks[t-1]['close']
        if prev <= 0: continue
        hi = ks[t]['high'] / prev - 1
        cl = ks[t]['close'] / prev - 1
        era = '19-22' if ks[t]['date'] < '2023' else '23-26'
        if hi >= 0.098 and cl < 0.095:   # 触板未封（炸板）
            c = G[f'炸板|{era}']
        elif cl >= 0.098:                 # 封板
            c = G[f'封板|{era}']
        elif 0.07 <= hi < 0.098 and cl < 0.07:  # 冲7%+未板
            c = G[f'冲7未板|{era}']
        else:
            continue
        c['n'] += 1
        c['fade_sum'] += (ks[t]['close'] / ks[t]['high'] - 1)  # 高点到收盘
        r1 = ks[t+1]['close'] / ks[t]['close'] - 1
        c['red1'] += r1 > 0
        c['ret1_sum'] += r1

print(f"{'组':16s}{'时代':7s}{'n':>8s} {'高点→收盘回落':>14s} {'次日收红率':>10s} {'次日均收':>9s}")
for k in sorted(G):
    c = G[k]
    g, era = k.split('|')
    print(f"{g:16s}{era:7s}{c['n']:>8d} {c['fade_sum']/c['n']*100:>13.2f}% {c['red1']/c['n']*100:>9.1f}% {c['ret1_sum']/c['n']*100:>8.2f}%")
