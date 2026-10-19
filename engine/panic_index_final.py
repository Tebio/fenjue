#!/usr/bin/env python3
"""engine/panic_index_final.py — 恐慌日买上证指数ETF 的最终验证（2026-10-19）

策略（可执行版）：
  信号：T 日全市场主板跌停封死 ≥ 24 只
  执行：T+1 开盘买入上证指数 ETF（如 510210/510050），持有 5 个交易日，T+5 收盘卖出
  资金：同一时刻只占一份，重叠信号顺延（不做杠杆、不加仓）

本脚本给出：分年度稳定性、资金约束年化、最大回撤、DSR、以及当前信号状态。
"""
import json
import math
import statistics as st
from pathlib import Path

ROOT = Path('/opt/data/fenjue')
KC = ROOT / 'data/big_kcache'
COST, HOLD, TH = 0.002, 5, 24
MB = ('600', '601', '603', '605', '000', '001', '002', '003')

data = {}
for p in KC.glob('*.json'):
    c = p.stem
    if c[:3] not in MB:
        continue
    try:
        ks = json.loads(p.read_text())
    except Exception:
        continue
    if isinstance(ks, list) and len(ks) >= 130:
        data[c] = ks


def is_ld(ks, i):
    if i < 1 or i >= len(ks):
        return False
    pc = ks[i - 1]['close']
    if pc <= 0:
        return False
    lim = round(pc * 0.9, 2)
    return lim * 0.994 <= ks[i]['close'] <= lim * 1.0005


n_dn = {}
for c, ks in data.items():
    for i in range(1, len(ks)):
        if is_ld(ks, i):
            n_dn[ks[i]['date']] = n_dn.get(ks[i]['date'], 0) + 1

IX = {r['date']: r for r in json.loads((ROOT / 'data/index_sh000001.json').read_text())}
cal = sorted({k['date'] for ks in data.values() for k in ks})
ci = {d: i for i, d in enumerate(cal)}


def trade(d):
    j = ci.get(d)
    if j is None or j + 1 + HOLD >= len(cal):
        return None
    bd, sd = cal[j + 1], cal[j + 1 + HOLD]
    if bd not in IX or sd not in IX:
        return None
    bp, sp = IX[bd]['open'], IX[sd]['close']
    if bp <= 0 or sp <= 0:
        return None
    return (sp / bp - 1 - COST) * 100


sig = sorted(d for d in n_dn if n_dn[d] >= TH)
trades = [(d, trade(d)) for d in sig]
trades = [(d, r) for d, r in trades if r is not None]
R = [r for _, r in trades]
print(f'门槛 ≥{TH} 家：信号 {len(sig)} 个，可兑现 {len(R)} 个')
print(f'  每笔均值 {st.mean(R):+.2f}%  胜率 {sum(1 for x in R if x>0)/len(R)*100:.1f}%  '
      f'标准差 {st.stdev(R):.2f}%')

print('\n=== 分年度 ===')
by_y = {}
for d, r in trades:
    by_y.setdefault(d[:4], []).append(r)
pos = 0
for y in sorted(by_y):
    v = by_y[y]
    m = st.mean(v)
    pos += 1 if m > 0 else 0
    print(f'  {y}: {len(v):>3} 次  {m:>+6.2f}%  胜率 {sum(1 for x in v if x>0)/len(v)*100:>5.1f}%')
print(f'  → {pos}/{len(by_y)} 年为正')

print('\n=== 资金约束（重叠顺延，同一时刻一份资金）===')
eq, peak, mdd, free, taken = 1.0, 1.0, 0.0, 0, 0
equity = [1.0]
for d, r in trades:
    j = ci[d]
    if j + 1 < free:
        continue
    eq *= 1 + r / 100
    taken += 1
    free = j + 1 + HOLD
    equity.append(eq)
    peak = max(peak, eq)
    mdd = min(mdd, eq / peak - 1)
span = (ci[trades[-1][0]] - ci[trades[0][0]]) / 244.0
ann = (eq ** (1 / span) - 1) * 100
print(f'  实际建仓 {taken}/{len(R)} 次   累计 {(eq-1)*100:+.1f}%   '
      f'跨度 {span:.2f} 年   年化 {ann:+.1f}%')
print(f'  最大回撤 {mdd*100:.1f}%   （单笔最差 {min(R):+.1f}%）')

print('\n=== DSR（N=实测 trial：门槛 10/15/20/24/30/40/50/75/100 共 9 个）===')
srs = []
for th in (10, 15, 20, 24, 30, 40, 50, 75, 100):
    rr = [trade(d) for d in sorted(x for x in n_dn if n_dn[x] >= th)]
    rr = [x for x in rr if x is not None]
    if len(rr) > 10 and st.stdev(rr) > 0:
        srs.append(st.mean(rr) / st.stdev(rr))
m, sd, n = st.mean(R), st.stdev(R), len(R)
sr = m / sd
sk = sum((x - m) ** 3 for x in R) / n / sd ** 3
ku = sum((x - m) ** 4 for x in R) / n / sd ** 4


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def phi_inv(p):
    lo, hi = -10.0, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if phi(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


N = len(srs)
vsr = st.stdev(srs)
g = 0.5772156649
sr0 = math.sqrt(vsr) * ((1 - g) * phi_inv(1 - 1 / N) + g * phi_inv(1 - 1 / (N * math.e)))
den = math.sqrt(max(1e-9, 1 - sk * sr + (ku - 1) / 4 * sr * sr))
z = (sr - sr0) * math.sqrt(n - 1) / den
print(f'  n={n}  SR={sr:.4f}  偏度{sk:+.2f} 峰度{ku:.2f}')
print(f'  N={N}  Var(SR_trials)={vsr**2:.4f}  SR0={sr0:.4f}  DSR={phi(z):.4f}'
      f'  → {"通过 0.95" if phi(z) > 0.95 else "不通过 0.95"}')

print('\n=== 今日状态 ===')
ov = json.loads((ROOT / 'data/kcache_today_overlay.json').read_text())
today = max(v['date'] for v in ov.values())
ld = 0
for c, ks in data.items():
    o = ov.get(c)
    if not o or ks[-1]['close'] <= 0:
        continue
    lim = round(ks[-1]['close'] * 0.9, 2)
    if lim * 0.994 <= o['close'] <= lim * 1.0005:
        ld += 1
print(f'  {today} 主板跌停封死 {ld} 只   门槛 {TH}  → {"★ 触发：明日开盘买上证指数ETF" if ld >= TH else "不触发"}')
