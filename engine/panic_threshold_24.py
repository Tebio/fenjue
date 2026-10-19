#!/usr/bin/env python3
"""engine/panic_threshold_24.py — 门槛 24 vs 50 的资金约束实盘口径对比 + DSR（2026-10-19）

前提（已实证）：
  1. 跌停家数与 T+5 前瞻收益单调（≥10→≥100 递增，无孤峰）
  2. 24-35 家与 ≥50 家同质（t=-1.21）
  3. ≥24 家 8/8 年为正
遗留问题：以上测的是「全市场等权」，不是「最便宜20只」，也不是资金约束口径。
本脚本做三件事：
  A. 两种组合构造 × 两个门槛的对比（全市场等权 / 最便宜20只 / 低吸-5%）
  B. 资金约束模拟（同一时刻只占一份资金，重叠信号顺延）
  C. DSR（用实测 trial 离散度）
"""
import json
import math
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
ci = {d: i for i, d in enumerate(cal)}
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


def sim(threshold, pick, low_dip):
    """返回 [(date, ret)]。pick='all'全市场等权 / 'cheap20'最便宜20只。"""
    days = sorted(d for d in n_dn if n_dn[d] >= threshold)
    out = []
    for d in days:
        j = ci.get(d)
        if j is None or j + 1 + HOLD >= len(cal):
            continue
        bd, sd = cal[j + 1], cal[j + 1 + HOLD]
        cand = []
        for c, ks in data.items():
            ix = IDX[c]
            if d not in ix or bd not in ix or sd not in ix:
                continue
            ref = ks[ix[d]]['close']
            o = ks[ix[bd]]['open']
            lo = ks[ix[bd]]['low']
            sp = ks[ix[sd]]['close']
            if min(ref, o, lo, sp) <= 0:
                continue
            if low_dip:
                lim = ref * 0.95
                px = min(lim, o) if lo <= lim else o * 1.005
            else:
                px = o
            cand.append((ref, c, sp / px - 1 - COST))
        if len(cand) < 20:
            continue
        if pick == 'cheap20':
            use = sorted(cand, key=lambda x: x[0])[:20]
        else:
            use = cand
        out.append((d, st.mean([x[2] for x in use])))
    return out


print('=== A. 组合构造 × 门槛 对比（每笔均值，已扣0.2%）===')
print(f"{'口径':<28}{'笔数':>6}{'均值':>9}{'胜率':>8}{'最差':>9}{'最好':>9}")
res = {}
for th in (24, 50):
    for pick, ld, lab in (('all', False, '全市场等权 开盘买'),
                          ('cheap20', False, '最便宜20只 开盘买'),
                          ('cheap20', True, '最便宜20只 低吸-5%')):
        r = sim(th, pick, ld)
        if not r:
            continue
        R = [x[1] * 100 for x in r]
        key = f'≥{th} {lab}'
        res[key] = R
        print(f'  {key:<26}{len(R):>6}{st.mean(R):>+8.2f}%'
              f'{sum(1 for x in R if x>0)/len(R)*100:>7.1f}%{min(R):>+8.1f}%{max(R):>+8.1f}%')

print('\n=== B. 资金约束模拟（重叠信号顺延，同一时刻只占一份）===')
for th in (24, 50):
    for pick, ld, lab in (('all', False, '全市场等权'), ('cheap20', True, '最便宜20只低吸')):
        r = sim(th, pick, ld)
        if not r:
            continue
        free = 0
        eq = 1.0
        taken = 0
        for d, ret in r:
            j = ci[d]
            if j + 1 < free:
                continue                      # 资金占用中，跳过
            eq *= 1 + ret
            taken += 1
            free = j + 1 + HOLD
        yrs = (cal.index(r[0][0]) and 0) or 0
        span = (cal.index(r[-1][0]) - cal.index(r[0][0])) / 244
        ann = (eq ** (1 / span) - 1) * 100 if span > 0 else 0
        print(f'  ≥{th} {lab:<14} 实际建仓 {taken:>3} 次/{len(r)} 信号   '
              f'累计 {(eq-1)*100:>+7.1f}%  跨度 {span:.1f}年  年化 {ann:>+6.1f}%')

print('\n=== C. DSR（≥24 最便宜20只低吸，用实测 trial 离散度）===')
best = res.get('≥24 最便宜20只 低吸-5%') or res.get('≥24 最便宜20只 开盘买')
if best:
    srs = []
    for k, R in res.items():
        if len(R) > 5 and st.stdev(R) > 0:
            srs.append(st.mean(R) / st.stdev(R))
    m, sd, n = st.mean(best), st.stdev(best), len(best)
    sr = m / sd
    sk = sum((x - m) ** 3 for x in best) / n / sd ** 3
    ku = sum((x - m) ** 4 for x in best) / n / sd ** 4

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
    vsr = st.stdev(srs) if N > 1 else 1.0
    g = 0.5772156649
    sr0 = math.sqrt(vsr) * ((1 - g) * phi_inv(1 - 1 / N) + g * phi_inv(1 - 1 / (N * math.e)))
    den = math.sqrt(max(1e-9, 1 - sk * sr + (ku - 1) / 4 * sr * sr))
    z = (sr - sr0) * math.sqrt(n - 1) / den
    print(f'  n={n}  SR={sr:.3f}  偏度{sk:+.2f} 峰度{ku:.2f}')
    print(f'  N={N} trials  Var(SR_trials)={vsr**2:.4f}  SR0={sr0:.3f}  DSR={phi(z):.4f}'
          f'  → {"通过 0.95" if phi(z) > 0.95 else "不通过 0.95"}')
