"""严格分层：冲+7% → 摸板(+9.8%) → 封死(收≥+9.5%) vs 炸开。分时代。"""
import json
from pathlib import Path
from collections import defaultdict

KC = Path('/opt/data/fenjue/data/big_kcache')
paths = [p for p in KC.glob('*.json') if p.stem[:2] in ('60', '00')]
G = defaultdict(lambda: {'rush': 0, 'touch': 0, 'seal': 0, 'break': 0,
                         'seal_next_red': 0, 'seal_next_sum': 0.0,
                         'break_next_red': 0, 'break_next_sum': 0.0,
                         'break_fade': 0.0})
for fp in paths:
    try: ks = json.load(open(str(fp)))
    except Exception: continue
    for t in range(1, len(ks) - 1):
        prev = ks[t-1]['close']
        if prev <= 0: continue
        hi = ks[t]['high'] / prev - 1
        cl = ks[t]['close'] / prev - 1
        if hi < 0.07: continue
        era = '19-22' if ks[t]['date'] < '2023' else '23-26'
        c = G[era]
        c['rush'] += 1
        if hi < 0.098: continue
        c['touch'] += 1
        r1 = ks[t+1]['close'] / ks[t]['close'] - 1
        if cl >= 0.095:
            c['seal'] += 1
            c['seal_next_red'] += r1 > 0
            c['seal_next_sum'] += r1
        else:
            c['break'] += 1
            c['break_next_red'] += r1 > 0
            c['break_next_sum'] += r1
            c['break_fade'] += (ks[t]['close'] / ks[t]['high'] - 1)

print(f"{'时代':6s}{'冲7%':>9s}{'摸板':>9s}{'摸板率':>8s}{'封死':>9s}{'炸开':>9s}{'封死率':>8s}{'炸开率':>8s}")
for era in ('19-22', '23-26'):
    c = G[era]
    print(f"{era:6s}{c['rush']:>9d}{c['touch']:>9d}{c['touch']/c['rush']*100:>7.1f}%"
          f"{c['seal']:>9d}{c['break']:>9d}{c['seal']/c['touch']*100:>7.1f}%{c['break']/c['touch']*100:>7.1f}%")
    print(f"       封死次日: 收红{c['seal_next_red']/c['seal']*100:.1f}% 均{c['seal_next_sum']/c['seal']*100:+.2f}%  |  "
          f"炸开次日: 收红{c['break_next_red']/c['break']*100:.1f}% 均{c['break_next_sum']/c['break']*100:+.2f}%  |  "
          f"炸开当天板价→收盘 {c['break_fade']/c['break']*100:+.2f}%")
