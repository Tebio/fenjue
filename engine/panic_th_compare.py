#!/usr/bin/env python3
"""engine/panic_th_compare.py — 门槛 24 vs 50 的分年稳定性对决（2026-10-19）

K3 建议把门槛从 24 提到 50，理由是 24 会把 2026 那种「日常退潮日」当信号。
它自己也说判别检验做一个就够：看高恐慌子集是否跨年稳定。
本脚本做这个检验。
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


print('=== 分年对决：门槛 24 / 30 / 40 / 50 ===')
print(f"{'年份':<7}{'≥24':>18}{'≥30':>16}{'≥40':>16}{'≥50':>16}")
allyear = {}
for th in (24, 30, 40, 50):
    tr = [(d, trade(d)) for d in sorted(x for x in n_dn if n_dn[x] >= th)]
    tr = [(d, r) for d, r in tr if r is not None]
    by_y = {}
    for d, r in tr:
        by_y.setdefault(d[:4], []).append(r)
    allyear[th] = (tr, by_y)

years = sorted({y for th in allyear for y in allyear[th][1]})
for y in years:
    row = f'  {y:<5}'
    for th in (24, 30, 40, 50):
        v = allyear[th][1].get(y, [])
        row += f'{(f"{len(v)}笔{st.mean(v):+.2f}%" if v else "-"):>18}' if th == 24 else \
               f'{(f"{len(v)}笔{st.mean(v):+.2f}%" if v else "-"):>16}'
    print(row)

print()
for th in (24, 30, 40, 50):
    tr, by_y = allyear[th]
    R = [r for _, r in tr]
    pos = sum(1 for y in by_y if st.mean(by_y[y]) > 0)
    neg_years = [f'{y}({st.mean(v):+.2f}%)' for y, v in sorted(by_y.items()) if st.mean(v) <= 0]
    eq, peak, mdd, free, taken = 1.0, 1.0, 0.0, 0, 0
    for d, r in tr:
        j = ci[d]
        if j + 1 < free:
            continue
        eq *= 1 + r / 100
        taken += 1
        free = j + 1 + HOLD
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    span = (ci[tr[-1][0]] - ci[tr[0][0]]) / 244.0
    ann = (eq ** (1 / span) - 1) * 100
    print(f'≥{th}: n={len(R):>3} 均值{st.mean(R):>+.2f}% 胜率{sum(1 for x in R if x>0)/len(R)*100:>5.1f}% '
          f'| {pos}/{len(by_y)}年为正 | 建仓{taken:>3}次 年化{ann:>+5.1f}% 回撤{mdd*100:>6.1f}%'
          f'{"" if not neg_years else "  负年: " + ",".join(neg_years)}')

print('\n=== K3 的判别检验：高恐慌子集是否跨年稳定 ===')
print('（看 ≥50 各年是否比 ≥24 更均匀；若 ≥50 也有负年，则「提门槛」救不了）')
