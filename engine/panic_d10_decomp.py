#!/usr/bin/env python3
"""engine/panic_d10_decomp.py — 拆解 D10（跌停≥24家）内部结构（2026-10-19）

动机：剂量反应显示顶部两档明显更强（D9 +0.55%、D10 +1.29%），但 D10 区间
跨越 24-2047 家，极可能被少数全市场暴跌日撑起来。必须先拆开验证内部一致性，
否则「把门槛从 50 降到 24」就是在追噪声。

另测：分年度稳定性（2020/2024/2026 各年是否还有效）
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
cal = sorted({k['date'] for ks in data.values() for k in ks})
IDX = {c: {k['date']: i for i, k in enumerate(ks)} for c, ks in data.items()}


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

fwd = {}
for j, d in enumerate(cal):
    if j + 1 + HOLD >= len(cal):
        continue
    bd, sd = cal[j + 1], cal[j + 1 + HOLD]
    rs = []
    for c, ks in data.items():
        ix = IDX[c]
        if d in ix and bd in ix and sd in ix:
            bp, sp = ks[ix[bd]]['open'], ks[ix[sd]]['close']
            if bp > 0 and sp > 0:
                rs.append(sp / bp - 1 - COST)
    if len(rs) >= 100:
        fwd[d] = st.mean(rs) * 100

print(f'可测交易日 {len(fwd)}  ({cal[0]} ~ {cal[-1]})\n')

print('=== D10 内部拆解（跌停家数分桶）===')
print(f"{'区间':<14}{'天数':>6}{'T+5均值':>10}{'胜率':>8}{'最差日':>9}{'最好日':>9}")
for lo, hi, lab in ((24, 35, '24-35'), (35, 50, '35-50'), (50, 100, '50-100'),
                    (100, 300, '100-300'), (300, 99999, '300+')):
    sub = [(d, fwd[d]) for d in fwd if lo <= n_dn.get(d, 0) < hi]
    if len(sub) < 10:
        continue
    R = [x[1] for x in sub]
    print(f'  {lab:<12}{len(sub):>6}{st.mean(R):>+9.2f}%'
          f'{sum(1 for x in R if x>0)/len(R)*100:>7.1f}%{min(R):>+8.2f}%{max(R):>+8.2f}%')

print('\n=== 关键分界：24-35 vs ≥50 是不是同一种效应 ===')
a = [fwd[d] for d in fwd if 24 <= n_dn.get(d, 0) < 35]
b = [fwd[d] for d in fwd if n_dn.get(d, 0) >= 50]
if len(a) >= 10 and len(b) >= 10:
    import math
    d_ = st.mean(a) - st.mean(b)
    t_ = d_ / math.sqrt(st.variance(a)/len(a) + st.variance(b)/len(b))
    print(f'  24-35家: n={len(a):>3} {st.mean(a):+.2f}% (胜率 {sum(1 for x in a if x>0)/len(a)*100:.1f}%)')
    print(f'  ≥50家  : n={len(b):>3} {st.mean(b):+.2f}% (胜率 {sum(1 for x in b if x>0)/len(b)*100:.1f}%)')
    print(f'  差 {d_:+.2f}pp  t={t_:.2f}  → {"两档不同质，不能混" if abs(t_)>2 else "两档同质，24家起就是同一效应"}')

print('\n=== 分年度稳定性（跌停≥24 家）===')
print(f"{'年份':<8}{'信号日':>7}{'T+5均值':>10}{'胜率':>8}")
by_year = {}
for d in fwd:
    if n_dn.get(d, 0) >= 24:
        by_year.setdefault(d[:4], []).append(fwd[d])
pos = 0
for y in sorted(by_year):
    R = by_year[y]
    m = st.mean(R)
    pos += 1 if m > 0 else 0
    print(f'  {y:<6}{len(R):>7}{m:>+9.2f}%{sum(1 for x in R if x>0)/len(R)*100:>7.1f}%')
print(f'  → {pos}/{len(by_year)} 年为正')

print('\n=== 阈值敏感性（不作弊：全扫一遍看是不是只有一个点好）===')
print(f"{'门槛':<8}{'信号日':>7}{'T+5均值':>10}{'胜率':>8}")
for th in (10, 15, 20, 24, 30, 40, 50, 75, 100):
    R = [fwd[d] for d in fwd if n_dn.get(d, 0) >= th]
    if len(R) < 10:
        continue
    print(f'  ≥{th:<7}{len(R):>7}{st.mean(R):>+9.2f}%{sum(1 for x in R if x>0)/len(R)*100:>7.1f}%')
