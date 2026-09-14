"""#78 季节调制层验证：月份是独立alpha还是beta代理？
方法：每月信号收益 - 同日全市场均值（beta剥离），看超额是否跨年稳定。
"""
import json
from pathlib import Path
from collections import defaultdict

KC = Path('/opt/data/fenjue/data/big_kcache')
paths = [p for p in KC.glob('*.json') if p.stem[:2] in ('60', '00')]
FEE = 0.0015

# 第一遍：全市场每日均值（T+1 open→close）
day_uni = defaultdict(lambda: [0, 0.0])
# 信号事件
sig = defaultdict(lambda: [0, 0.0])  # (strategy, date) → [n, ret_sum]

for fp in paths:
    try: ks = json.load(open(str(fp)))
    except Exception: continue
    for t in range(2, len(ks) - 1):
        prev = ks[t-1]['close']
        if prev <= 0 or ks[t+1]['open'] <= 0: continue
        r = ks[t+1]['close'] / ks[t+1]['open'] - 1 - FEE
        d = ks[t]['date']
        day_uni[d][0] += 1
        day_uni[d][1] += r
        pct1 = ks[t]['close'] / prev - 1
        if pct1 <= -0.03: sig[('反转', d)][0] += 1; sig[('反转', d)][1] += r
        if pct1 <= -0.098: sig[('跌停接', d)][0] += 1; sig[('跌停接', d)][1] += r

# 按月×年聚合超额
exc = defaultdict(lambda: [0, 0.0, 0.0])  # (strategy, year, month) → [n, sig_r_sum, uni_r_sum(按信号日加权)]
for (name, d), (n, rs) in sig.items():
    if not n or d not in day_uni: continue
    y, m = d[:4], d[5:7]
    k = (name, y, m)
    exc[k][0] += n
    exc[k][1] += rs
    exc[k][2] += (day_uni[d][1] / day_uni[d][0]) * n  # 同日beta×n

for name in ('反转', '跌停接'):
    print(f'\n=== {name}：月度超额（信号-同beta），每年一行 ===')
    print(f'{"月份":5s}' + ''.join(f'{y:>9d}' for y in range(2019, 2027)))
    for m in [f'{i:02d}' for i in range(1, 13)]:
        row = f'{m}月  '
        for y in range(2019, 2027):
            k = (name, str(y), m)
            c = exc.get(k)
            if c and c[0] >= 50:
                e = (c[1] - c[2]) / c[0] * 100
                row += f'{e:>+8.2f}%'
            else:
                row += f'{"--":>9s}'
        print(row)
