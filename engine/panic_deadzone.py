#!/usr/bin/env python3
"""engine/panic_deadzone.py — 35-50 家死区检验（上证指数口径，2026-10-19）

发现：全市场等权口径下 D10 内部出现 35-50 家死区（-0.07%），24-35 家反而 +1.40%。
若上证口径同样如此，则「门槛提到50」的真实理由不是「滤掉2026噪音」，
而是「跳过35-50这个死区」，且今日 25 家（落在 24-35 好档）应当交易。
"""
import json
import statistics as st
from pathlib import Path

ROOT = Path('/opt/data/fenjue')
KC = ROOT / 'data/big_kcache'
COST, HOLD = 0.002, 5
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


print('=== 上证指数口径：跌停家数分桶 ===')
print(f"{'家数区间':<12}{'信号':>5}{'可兑现':>7}{'均值':>9}{'胜率':>8}{'中位':>9}")
buckets = [(24, 35, '24-35'), (35, 50, '35-50'), (50, 100, '50-100'),
           (100, 300, '100-300'), (300, 999999, '300+'), (10, 24, '10-23')]
for lo, hi, lab in buckets:
    days = [d for d in n_dn if lo <= n_dn[d] < hi]
    R = [trade(d) for d in days]
    R = [x for x in R if x is not None]
    if len(R) < 8:
        print(f'  {lab:<10}{len(days):>5}{len(R):>7}  样本不足')
        continue
    print(f'  {lab:<10}{len(days):>5}{len(R):>7}{st.mean(R):>+8.2f}%'
          f'{sum(1 for x in R if x>0)/len(R)*100:>7.1f}%{st.median(R):>+8.2f}%')

print('\n=== 死区是否稳定：35-50 家分年 ===')
d35 = sorted(d for d in n_dn if 35 <= n_dn[d] < 50)
by_y = {}
for d in d35:
    r = trade(d)
    if r is not None:
        by_y.setdefault(d[:4], []).append(r)
for y in sorted(by_y):
    v = by_y[y]
    print(f'  {y}: {len(v):>2} 笔  {st.mean(v):>+6.2f}%  胜率 {sum(1 for x in v if x>0)/len(v)*100:>5.1f}%')

print('\n=== 24-35 家分年（今天 25 家所属档）===')
d24 = sorted(d for d in n_dn if 24 <= n_dn[d] < 35)
by_y2 = {}
for d in d24:
    r = trade(d)
    if r is not None:
        by_y2.setdefault(d[:4], []).append(r)
pos = 0
for y in sorted(by_y2):
    v = by_y2[y]
    pos += 1 if st.mean(v) > 0 else 0
    print(f'  {y}: {len(v):>2} 笔  {st.mean(v):>+6.2f}%  胜率 {sum(1 for x in v if x>0)/len(v)*100:>5.1f}%')
R24 = [x for v in by_y2.values() for x in v]
print(f'  → 24-35 合计 n={len(R24)} 均值 {st.mean(R24):+.2f}% 胜率 '
      f'{sum(1 for x in R24 if x>0)/len(R24)*100:.1f}%  {pos}/{len(by_y2)} 年为正')

print('\n=== 排除死区后的组合（24-35 或 ≥50）===')
keep = [d for d in n_dn if 24 <= n_dn[d] < 35 or n_dn[d] >= 50]
Rk = [trade(d) for d in sorted(keep)]
Rk = [x for x in Rk if x is not None]
print(f'  n={len(Rk)} 均值 {st.mean(Rk):+.2f}% 胜率 {sum(1 for x in Rk if x>0)/len(Rk)*100:.1f}%')
eq, peak, mdd, free, taken = 1.0, 1.0, 0.0, 0, 0
for d in sorted(keep):
    r = trade(d)
    if r is None:
        continue
    j = ci[d]
    if j + 1 < free:
        continue
    eq *= 1 + r / 100
    taken += 1
    free = j + 1 + HOLD
    peak = max(peak, eq)
    mdd = min(mdd, eq / peak - 1)
span = (ci[max(d for d in keep if trade(d) is not None)] - ci[min(keep)]) / 244.0
print(f'  建仓 {taken} 次  累计 {(eq-1)*100:+.1f}%  跨度 {span:.1f}年  年化 '
      f'{(eq**(1/span)-1)*100:+.1f}%  回撤 {mdd*100:.1f}%')
