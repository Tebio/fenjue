"""#80② 组合层仓位数学初测：底仓(指数代理)×进攻策略 配比扫描
验证 60-70/0-30 是拍脑袋还是接近合理区间。
策略日收益 = 当日信号等权T+1(open→close)均值（无信号日=0，空仓）。
底仓 = 上证指数日收益（红利底仓的低波代理，口径注记：真红利宇宙更低波）。
"""
import json
from pathlib import Path
from collections import defaultdict

ROOT = Path('/opt/data/fenjue')
KC = ROOT / 'data/big_kcache'
paths = [p for p in KC.glob('*.json') if p.stem[:2] in ('60', '00')]
FEE = 0.0015

sig_day = defaultdict(lambda: defaultdict(list))  # strategy -> date -> [rets]
for fp in paths:
    try: ks = json.load(open(str(fp)))
    except Exception: continue
    for t in range(2, len(ks) - 1):
        prev = ks[t-1]['close']
        if prev <= 0 or ks[t+1]['open'] <= 0: continue
        d = ks[t]['date']
        r1 = ks[t+1]['close'] / ks[t+1]['open'] - 1 - FEE
        rc = ks[t+1]['close'] / ks[t]['close'] - 1 - FEE
        pct1 = ks[t]['close'] / prev - 1
        if pct1 <= -0.03: sig_day['反转'][d].append(r1)
        if pct1 <= -0.098: sig_day['跌停接'][d].append(r1)
        if pct1 >= 0.098 and ks[t-1]['close'] / ks[t-2]['close'] - 1 < 0.098:
            sig_day['打板隔夜'][d].append(rc)

# 2026-09-14 修正：big_kcache/000001.json 是平安银行不是指数（撞代码事故）→ baostock 拉真指数
import sys as _s
_s.path.insert(0, '/opt/data/python-libs')
import baostock as _bs
_bs.login()
rs = _bs.query_history_k_data_plus('sh.000001', 'date,close', start_date='2019-01-01', frequency='d')
rows = []
while rs.error_code == '0' and rs.next():
    rows.append(rs.get_row_data())
_bs.logout()
idx_ret = {rows[i][0]: float(rows[i][1]) / float(rows[i-1][1]) - 1 for i in range(1, len(rows))}
dates = sorted(idx_ret)[-1500:]  # 近6年

def series(name):
    return [ (sum(sig_day[name].get(d, [0])) / len(sig_day[name][d])) if sig_day[name].get(d) else 0.0 for d in dates ]

def metrics(rets):
    import math
    n = len(rets)
    mean = sum(rets) / n * 252
    var = sum((r - sum(rets)/n) ** 2 for r in rets) / n
    sd = math.sqrt(var * 252) or 1e-9
    sharpe = mean / sd
    eq = 1.0; peak = 1.0; dd = 0.0
    for r in rets:
        eq *= 1 + r
        peak = max(peak, eq)
        dd = min(dd, eq / peak - 1)
    return mean * 100, dd * 100, sharpe, (eq - 1) * 100

import math
strategies = ['反转', '跌停接', '打板隔夜']
S = {s: series(s) for s in strategies}
I = [idx_ret[d] for d in dates]

print('=== 单策略（近6年，年化/最大回撤/夏普/累计）===')
for s in strategies:
    m = metrics(S[s])
    print(f'  {s:8s} {m[0]:+.1f}%  DD{m[1]:.1f}%  夏普{m[2]:.2f}  累计{m[3]:+.0f}%')
print(f'  {"纯指数底仓":8s} {metrics(I)[0]:+.1f}%  DD{metrics(I)[1]:.1f}%  夏普{metrics(I)[2]:.2f}')

# 相关性
def corr(a, b):
    ma, mb = sum(a)/len(a), sum(b)/len(b)
    cov = sum((x-ma)*(y-mb) for x, y in zip(a, b))
    va = sum((x-ma)**2 for x in a); vb = sum((y-mb)**2 for y in b)
    return cov / math.sqrt(va * vb + 1e-18)
print('\n=== 进攻策略间相关性 ===')
for i, a in enumerate(strategies):
    for b in strategies[i+1:]:
        print(f'  {a} × {b}: {corr(S[a], S[b]):.2f}')

print('\n=== 配比扫描（底仓×进攻，进攻=三策略等权合成）===')
mix = [(S['反转'][i] + S['跌停接'][i] + S['打板隔夜'][i]) / 3 for i in range(len(dates))]
for w_base in (0.5, 0.6, 0.65, 0.7, 0.8, 1.0):
    combo = [w_base * I[i] + (1 - w_base) * mix[i] for i in range(len(dates))]
    m = metrics(combo)
    print(f'  底仓{int(w_base*100)}%/进攻{int((1-w_base)*100)}%: 年化{m[0]:+.1f}%  DD{m[1]:.1f}%  夏普{m[2]:.2f}  累计{m[3]:+.0f}%')
