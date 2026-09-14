"""策略×月份胜率：2026逐月 + 2019-2025同月均值（季节规律）
口径：收盘信号→次日开盘买→次日尾盘卖（T+1，净-0.15%）
策略：反转族(跌≥3%) / 深档(跌≥7%) / 跌停接(≤-9.8%) / 首板次日追 / 打板隔夜(封板买)
"""
import json
from pathlib import Path
from collections import defaultdict

KC = Path('/opt/data/fenjue/data/big_kcache')
paths = [p for p in KC.glob('*.json') if p.stem[:2] in ('60', '00')]

# G[(strategy, 'YYYY-MM')] = [n, win, ret_sum]
G = defaultdict(lambda: [0, 0, 0.0])
FEE = 0.0015

for fp in paths:
    try: ks = json.load(open(str(fp)))
    except Exception: continue
    for t in range(2, len(ks) - 1):
        prev = ks[t-1]['close']
        if prev <= 0 or ks[t]['open'] <= 0: continue
        pct1 = ks[t]['close'] / prev - 1       # 信号日涨幅
        pct0 = ks[t-1]['close'] / ks[t-2]['close'] - 1 if ks[t-2]['close'] > 0 else 0
        ym = ks[t]['date'][:7]
        r_open = ks[t+1]['close'] / ks[t+1]['open'] - 1 - FEE  # 修:次日开盘价(原误用信号日开盘=未来函数)   # 次日开盘买→尾盘
        r_close = ks[t+1]['close'] / ks[t]['close'] - 1 - FEE  # 信号日收盘买→次日尾盘
        sigs = []
        if pct1 <= -0.03: sigs.append(('反转', r_open))
        if pct1 <= -0.07: sigs.append(('深档', r_open))
        if pct1 <= -0.098: sigs.append(('跌停接', r_open))
        if pct1 >= 0.098 and pct0 < 0.098:
            sigs.append(('首板次日追', r_open))
            sigs.append(('打板隔夜', r_close))
        for name, r in sigs:
            c = G[(name, ym)]
            c[0] += 1; c[1] += r > 0; c[2] += r

months26 = [f'2026-{m:02d}' for m in range(1, 10)]
strategies = ['反转', '深档', '跌停接', '首板次日追', '打板隔夜']

def stat(name, ym):
    c = G.get((name, ym))
    if not c or c[0] < 30: return None
    return c[0], c[1] / c[0] * 100, c[2] / c[0] * 100

for name in strategies:
    print(f'\n=== {name}（开盘买→T+1尾盘，打板隔夜=收盘买）===')
    print(f'{"月份":9s}{"n":>7s}{"胜率":>7s}{"均笔":>7s}   {"19-25同月":>14s}')
    for ym in months26:
        s = stat(name, ym)
        # 19-25 同月聚合
        mm = ym[5:]
        n0 = w0 = 0; r0 = 0.0
        for y in range(2019, 2026):
            c = G.get((name, f'{y}-{mm}'))
            if c: n0 += c[0]; w0 += c[1]; r0 += c[2]
        hist = f'{w0/n0*100:5.1f}%/{r0/n0*100:+5.2f}%' if n0 >= 100 else '  --'
        if s:
            print(f'{ym:9s}{s[0]:>7d}{s[1]:>6.1f}%{s[2]:>+6.2f}%   {hist:>14s}')
        else:
            print(f'{ym:9s}{"--":>7s}{"--":>7s}{"--":>7s}   {hist:>14s}')
