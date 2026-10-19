#!/usr/bin/env python3
"""engine/k3_verify_panic.py — 逐条实测 K3 的指控（2026-10-19）

K3 的可测断言：
  ① P&L 集中度：前 2 个事件簇占总收益多少？>50% 则真实样本是「几个事件」不是 195 笔
  ② t=4.13 虚高：用日历时间组合 + Newey-West HAC 重算，应落到 2-3
  ③ 2020+2021+2024 贡献约七成
  ④ ST 口径：ST 跌停 5%，我的公式要求 -10% → 会漏掉 ST（K3 说会「算进去」，方向可能反了）
  ⑤ 门槛提到 50 后效果
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


def is_ld(ks, i, rate=0.9):
    if i < 1 or i >= len(ks):
        return False
    pc = ks[i - 1]['close']
    if pc <= 0:
        return False
    lim = round(pc * rate, 2)
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

print(f'信号 {len(trades)} 笔  均值 {st.mean(R):+.2f}%  t_naive = '
      f'{st.mean(R)/st.stdev(R)*math.sqrt(len(R)):.2f}')

# ── ① 事件簇集中度 ──────────────────────────────────
print('\n=== ① 事件簇集中度（连续信号日 = 同一个簇，间隔>5交易日算新簇）===')
clusters = []
cur = [trades[0]]
for d, r in trades[1:]:
    if ci[d] - ci[cur[-1][0]] <= HOLD:
        cur.append((d, r))
    else:
        clusters.append(cur)
        cur = [(d, r)]
clusters.append(cur)
tot = sum(R)
cl = []
for c in clusters:
    cl.append((c[0][0], c[-1][0], len(c), sum(x[1] for x in c), st.mean([x[1] for x in c])))
cl.sort(key=lambda x: -abs(x[3]))
print(f'  簇数 {len(cl)}  总 P&L(单利合计) {tot:+.0f}%')
print(f"{'起始':<12}{'结束':<12}{'笔数':>5}{'P&L合计':>10}{'簇均值':>9}{'占总':>8}")
for s, e, n, ssum, m in cl[:8]:
    print(f'  {s:<12}{e:<12}{n:>5}{ssum:>+9.1f}%{m:>+8.2f}%{ssum/tot*100:>7.1f}%')
top2 = sum(x[3] for x in cl[:2])
print(f'\n  前 2 簇占总 P&L: {top2:.1f}%  前 3 簇: {sum(x[3] for x in cl[:3]):.1f}%')
top2n = sum(x[2] for x in cl[:2])
print(f'  前 2 簇笔数 {top2n}/{len(R)}  → K3 断言「>50% 则真实样本是几个事件」: '
      f'{"成立（样本降级）" if abs(top2/tot)>0.5 else "不成立（收益分散）"}')

# 剔除前 2 簇后
rest = [r for c in clusters[clusters.index([t for t in clusters if t[0][0]==cl[0][0]][0]):] for r in []]
restR = [r for d, r in trades if d not in {x[0] for x in cl[:2]} and d not in {x[1] for x in cl[:2]}]
# 更稳：按簇序号排除
top2_keys = {(x[0], x[1]) for x in cl[:2]}
restR = []
for c in clusters:
    if (c[0][0], c[-1][0]) in top2_keys:
        continue
    restR += [x[1] for x in c]
print(f'  剔除前 2 簇后：n={len(restR)} 均值 {st.mean(restR):+.2f}% '
      f'胜率 {sum(1 for x in restR if x>0)/len(restR)*100:.1f}%  '
      f't={st.mean(restR)/st.stdev(restR)*math.sqrt(len(restR)):.2f}')

# ── ② 日历时间组合 + Newey-West HAC ──────────────────
print('\n=== ② 日历时间组合法 + Newey-West HAC（AGENTS #262 标准做法）===')
daily = {}
for d, r in trades:
    j = ci[d]
    bd_i, sd_i = j + 1, j + 1 + HOLD
    for k in range(bd_i, min(sd_i + 1, len(cal))):
        daily.setdefault(cal[k], []).append(r / (HOLD + 1))
seq = [st.mean(v) for d, v in sorted(daily.items())]
n = len(seq)
mu = st.mean(seq)
sd = st.stdev(seq)
print(f'  组合日序列 n={n}  日均 {mu:+.4f}%  日波动 {sd:.4f}%')
for L in (0, 5, 10, 20):
    # NW 方差
    g0 = sum((x - mu) ** 2 for x in seq) / n
    var = g0
    for l in range(1, L + 1):
        gl = sum((seq[i] - mu) * (seq[i - l] - mu) for i in range(l, n)) / n
        var += 2 * (1 - l / (L + 1)) * gl
    se = math.sqrt(max(var, 1e-12) / n)
    print(f'  NW lag={L:<3} t = {mu/se:>6.2f}')

# ── ③ 分年贡献 ───────────────────────────────────
print('\n=== ③ 分年 P&L 贡献 ===')
by_y = {}
for d, r in trades:
    by_y.setdefault(d[:4], []).append(r)
for y in sorted(by_y):
    s = sum(by_y[y])
    print(f'  {y}: {len(by_y[y]):>3} 笔  P&L合计 {s:>+7.1f}%  占总 {s/tot*100:>5.1f}%')
top3 = sum(sum(by_y[y]) for y in ('2020', '2021', '2024'))
print(f'  2020+2021+2024 合计 {top3:.1f}%  占总 {top3/tot*100:.1f}%  '
      f'→ K3 断言「约七成」: {"成立" if abs(top3/tot*100-70)<15 else "偏差较大"}')

# ── ④ ST 口径方向 ────────────────────────────────
print('\n=== ④ ST 口径（K3 说会「算进去」，验证方向）===')
st_codes = [c for c in data if c[:3] in ('600', '601', '603', '605', '000', '001', '002', '003')]
# 用证券名不可得，改用：ST 跌停 5% 的票在我的 -10% 公式下会不会被算成跌停
# 逻辑检验：-5% 的收盘不可能满足 -10% 判定 → 必然被漏掉，不可能被算进去
hit5 = 0
for c, ks in data.items():
    for i in range(1, len(ks)):
        if is_ld(ks, i, 0.95):
            hit5 += 1
print(f'  用 -5% 判定（ST 真实跌停幅度）能识别出 {hit5} 个「跌停」')
print(f'  用 -10% 判定（我的公式）识别出 {sum(1 for k in n_dn)} 天 / {sum(n_dn.values())} 个')
print('  → 我的公式要求 -10%，ST 的 -5% 必然被**漏掉**（低估跌停家数），')
print('     K3 说「会把 ST 算进去、抬高基数」方向反了。信号门槛因此偏保守，不是偏激进。')
