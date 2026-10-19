#!/usr/bin/env python3
"""engine/rebuild_breadth_signal.py — 跌停家数序列重算 + 策略B 全部重跑（2026-10-19）

审计：#325 的口径修正是否影响已发布的策略B 结果。

旧序列（错误）：前复权价 round(fq_close×0.9,2) 判跌停，仅 10% 档
新序列（正确）：不复权价精确匹配限价，分 10% 档 / 10%+ST 两版

输出：
  A. 三个家数序列的逐日对比（相关性、阈值穿越差异）
  B. 策略B（买上证ETF持有5日）在三个序列下的结果
  C. 结论是否翻转
"""
import json
import statistics as st
from pathlib import Path

ROOT = Path('/opt/data/fenjue')
UNADJ = ROOT / 'data/big_kcache_unadj'
FQ = ROOT / 'data/big_kcache'
COST, HOLD = 0.002, 5
MB = ('600', '601', '603', '605', '000', '001', '002', '003')
EPS = 0.0015


def lp(pc, r):
    return round(pc * r + 1e-9, 2)


def mt(a, b):
    return abs(a - b) <= EPS


old_cnt, new10, newall = {}, {}, {}
cal_set = set()

for p in FQ.glob('*.json'):
    c = p.stem
    if c[:3] not in MB:
        continue
    try:
        fk = json.loads(p.read_text())
    except Exception:
        continue
    if not isinstance(fk, list) or len(fk) < 130:
        continue
    cal_set.update(k['date'] for k in fk)
    # 旧口径：前复权价
    for i in range(1, len(fk)):
        pc = fk[i - 1]['close']
        if pc <= 0:
            continue
        lim = round(pc * 0.9, 2)
        if lim * 0.994 <= fk[i]['close'] <= lim * 1.0005:
            old_cnt[fk[i]['date']] = old_cnt.get(fk[i]['date'], 0) + 1

    uf = UNADJ / f'{c}.json'
    if not uf.exists():
        continue
    try:
        uk = json.loads(uf.read_text())
    except Exception:
        continue
    if not isinstance(uk, list) or len(uk) < 130:
        continue
    for i in range(1, len(uk)):
        pc = uk[i - 1]['close']
        if pc <= 0:
            continue
        cl = uk[i]['close']
        d = uk[i]['date']
        if mt(cl, lp(pc, 0.9)):
            new10[d] = new10.get(d, 0) + 1
            newall[d] = newall.get(d, 0) + 1
        elif mt(cl, lp(pc, 0.95)):
            newall[d] = newall.get(d, 0) + 1

IX = {r['date']: r for r in json.loads((ROOT / 'data/index_sh000001.json').read_text())}
cal = sorted(cal_set)
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


print('=== A. 三个家数序列对比 ===')
print(f"{'口径':<22}{'有跌停天数':>10}{'日均家数':>10}{'≥24天数':>9}{'最大':>7}")
for lab, s in (('旧：前复权10%', old_cnt), ('新：不复权10%', new10), ('新：不复权10%+ST', newall)):
    v = [s.get(d, 0) for d in cal]
    print(f'  {lab:<20}{sum(1 for x in v if x>0):>10}{st.mean(v):>10.1f}'
          f'{sum(1 for x in v if x>=24):>9}{max(v):>7}')

pairs = [('旧 vs 新10%', old_cnt, new10), ('新10% vs 新全', new10, newall)]
for lab, a, b in pairs:
    va = [a.get(d, 0) for d in cal]
    vb = [b.get(d, 0) for d in cal]
    diff = sum(1 for x, y in zip(va, vb) if (x >= 24) != (y >= 24))
    both = [(x, y) for x, y in zip(va, vb) if max(x, y) > 0]
    if len(both) > 10:
        mx = st.mean([x for x, _ in both]); my = st.mean([y for _, y in both])
        cov = sum((x - mx) * (y - my) for x, y in both)
        sx = sum((x - mx) ** 2 for x, _ in both) ** 0.5
        sy = sum((y - my) ** 2 for _, y in both) ** 0.5
        corr = cov / (sx * sy) if sx * sy > 0 else 0.0
    else:
        corr = 0.0
    print(f'  {lab}: ≥24 判定不一致 {diff} 天 / {len(cal)}   家数均值 {st.mean(va):.1f} → {st.mean(vb):.1f}   相关 {corr:.3f}')

print('\n=== B. 策略B 在三个序列下的结果 ===')
print(f"{'序列':<20}{'门槛':<10}{'信号':>6}{'均值':>9}{'胜率':>8}{'年化':>8}{'回撤':>8}")
for lab, s in (('旧 前复权10%', old_cnt), ('新 不复权10%', new10), ('新 不复权10%+ST', newall)):
    for th in (24,):
        days = sorted(d for d in cal if s.get(d, 0) >= th)
        tr = [(d, trade(d)) for d in days]
        tr = [(d, r) for d, r in tr if r is not None]
        if len(tr) < 20:
            continue
        R = [r for _, r in tr]
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
        print(f'  {lab:<18}≥{th:<9}{len(R):>6}{st.mean(R):>+8.2f}%'
              f'{sum(1 for x in R if x>0)/len(R)*100:>7.1f}%{ann:>+7.1f}%{mdd*100:>7.1f}%')

print('\n=== C. 滚动分位口径（≥95 / ≥97）在正确序列下重跑 ===')
for lab, s in (('旧 前复权10%', old_cnt), ('新 不复权10%', new10), ('新 不复权10%+ST', newall)):
    seq = [s.get(d, 0) for d in cal]
    for q in (95, 97):
        days = []
        for j in range(len(cal)):
            if j < 120:
                continue
            hist = seq[max(0, j - 250):j]
            cur = seq[j]
            if cur == 0:
                continue
            p = sum(1 for x in hist if x < cur) / len(hist) * 100
            if p >= q:
                days.append(cal[j])
        tr = [(d, trade(d)) for d in days]
        tr = [(d, r) for d, r in tr if r is not None]
        if len(tr) < 15:
            print(f'  {lab:<18}≥{q} 分位: 样本不足 ({len(tr)})')
            continue
        R = [r for _, r in tr]
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
        print(f'  {lab:<18}≥{q} 分位 {len(R):>4}笔 {st.mean(R):>+6.2f}% '
              f'胜率{sum(1 for x in R if x>0)/len(R)*100:>5.1f}% 年化{ann:>+6.1f}% 回撤{mdd*100:>6.1f}%')
