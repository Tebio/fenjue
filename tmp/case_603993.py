import json
from pathlib import Path

rows = json.load(open('data/big_kcache/603993.json'))
r25 = [r for r in rows if '2025-01-01' <= r['date'] <= '2025-12-31']
apr = [r for r in r25 if r['date'] <= '2025-04-30']
a0 = apr[0]
y0 = r25[0]; yend = r25[-1]
print(f"2025年初({y0['date']}) 收{y0['close']:.2f} → 4月初({a0['date']}) {a0['close']:.2f} → 年末({yend['date']}) {yend['close']:.2f}")
hi = max(r25, key=lambda r: r['close'])
print(f"年内高点 {hi['date']} {hi['close']:.2f}  vs4月初 {hi['close']/a0['close']-1:+.1%}  vs年初 {hi['close']/y0['close']-1:+.1%}")

# 4月前后现存信号族触发检查（日K代理）
sig = []
for i in range(1, len(rows)):
    p = rows[i-1]; t = rows[i]
    if not ('2025-03-01' <= p['date'] <= '2025-05-31'): continue
    pct_p = (p['close']/rows[i-2]['close']-1)*100 if i >= 2 else 0
    if pct_p <= -3:
        sig.append(('反转族候选(前日跌<=-3%)', p['date'], round(pct_p, 2)))
    gap = (t['open']/p['close']-1)*100
    if 5 <= gap <= 8:
        sig.append(('半路板代理(高开5-8%)', t['date'], round(gap, 2)))
print("2025年3-5月信号触发:", sig if sig else "零触发——现存短线信号族对它全程静默")

div = json.load(open('data/dividend_history.json')) if Path('data/dividend_history.json').exists() else {}
d993 = div.get('603993', [])
print("分红记录条数:", len(d993), d993[-3:] if d993 else "无")

# 4月时的趋势形态：4/1前的MA60方向+20日涨幅
i0 = next(i for i, r in enumerate(rows) if r['date'] >= '2025-04-01')
w = rows[i0-60:i0]
ma60 = sum(r['close'] for r in w)/60
c0 = rows[i0]['close']
print(f"2025-04-01: 收{c0:.2f} vs MA60 {ma60:.2f} ({c0/ma60-1:+.1%}), 前20日涨幅 {c0/rows[i0-20]['close']-1:+.1%}, 前60日涨幅 {c0/rows[i0-60]['close']-1:+.1%}")
