#!/usr/bin/env python3
"""engine/panic_dose_response.py — 崩盘抄底的连续剂量反应检验（2026-10-19）

为什么做这个：
  崩盘抄底线上只有 28 个事件（跌停≥50家），DSR=0.001，n 太小无法与噪声区分。
  但「恐慌日买入」的经济假设是连续的：越恐慌，未来反弹越强。
  如果成立，就不该是「≥50家才有效」的阶跃，而应是**单调剂量反应**。
  用 1900+ 个交易日做分层回归，比 28 个二元事件多两个数量级的统计功效。

设计（预登记，跑之前写死）：
  - 交易日 T：计算全市场跌停家数 n_dt（主板，收盘封死跌停）
  - 组合：T+1 开盘等权买入全主板可交易票，T+5 收盘卖出（扣 0.2%）
  - 分层：按 n_dt 分 10 档（十分位），看每档的前瞻收益是否单调
  - 证伪条件：若最高档不显著高于中位档，或分层不单调 → 恐慌度无预测力
"""
import json
import statistics as st
from pathlib import Path

ROOT = Path('/opt/data/fenjue')
KC = ROOT / 'data/big_kcache'
COST = 0.002
MB = ('600', '601', '603', '605', '000', '001', '002', '003')

# ── 载入 ──────────────────────────────────────────────
data = {}
for p in KC.glob('*.json'):
    code = p.stem
    if code[:3] not in MB:
        continue
    try:
        ks = json.loads(p.read_text())
    except Exception:
        continue
    if not isinstance(ks, list) or len(ks) < 130:
        continue
    data[code] = ks
print(f'股票 {len(data)} 只')

# 日历
cal = sorted({k['date'] for ks in data.values() for k in ks})
ci = {d: i for i, d in enumerate(cal)}
print(f'交易日 {len(cal)}  ({cal[0]} ~ {cal[-1]})')

# 每只票的 date→index
IDX = {c: {k['date']: i for i, k in enumerate(ks)} for c, ks in data.items()}


def limit_dn(ks, i):
    """第 i 根是否收盘封死跌停。"""
    if i < 1 or i >= len(ks):
        return False
    pc = ks[i - 1]['close']
    if pc <= 0:
        return False
    lim = round(pc * 0.9, 2)
    return ks[i]['close'] <= lim * 1.0005 and ks[i]['close'] >= lim * 0.994


# ── 每日跌停家数 ──────────────────────────────────────
n_dn = {}
for c, ks in data.items():
    for i in range(1, len(ks)):
        if limit_dn(ks, i):
            d = ks[i]['date']
            n_dn[d] = n_dn.get(d, 0) + 1
print(f'有跌停的交易日 {len(n_dn)}')

# ── 每日前瞻收益：T+1 开盘等权买全市场，T+5 收盘卖 ────────
HOLD = 5
fwd = {}
for j, d in enumerate(cal):
    if j + 1 + HOLD >= len(cal):
        continue
    bd, sd = cal[j + 1], cal[j + 1 + HOLD]
    rs = []
    for c, ks in data.items():
        ix = IDX[c]
        if d not in ix or bd not in ix or sd not in ix:
            continue
        bp = ks[ix[bd]]['open']
        sp = ks[ix[sd]]['close']
        if bp > 0 and sp > 0:
            rs.append(sp / bp - 1 - COST)
    if len(rs) >= 100:
        fwd[d] = st.mean(rs) * 100

print(f'可测交易日 {len(fwd)}')

# ── 分层 ─────────────────────────────────────────────
rows = [(d, n_dn.get(d, 0), fwd[d]) for d in fwd]
rows.sort(key=lambda x: x[1])
print(f'\n每日跌停家数分布: 中位 {st.median([r[1] for r in rows]):.0f}  '
      f'P90 {sorted(r[1] for r in rows)[int(len(rows)*0.9)]:.0f}  '
      f'最大 {max(r[1] for r in rows)}')

K = 10
size = len(rows) // K
print(f"\n{'十分位':<8}{'跌停家数区间':<16}{'天数':>6}{'T+5等权收益':>13}{'胜率':>8}")
buckets = []
for b in range(K):
    sub = rows[b * size: (b + 1) * size] if b < K - 1 else rows[(K - 1) * size:]
    if not sub:
        continue
    ns = [x[1] for x in sub]
    R = [x[2] for x in sub]
    buckets.append((b + 1, min(ns), max(ns), len(sub), st.mean(R),
                    sum(1 for x in R if x > 0) / len(R) * 100))
    print(f'  D{b+1:<6}{f"{min(ns)}-{max(ns)}":<16}{len(sub):>6}{st.mean(R):>+11.2f}%'
          f'{sum(1 for x in R if x>0)/len(R)*100:>7.1f}%')

print('\n=== 单调性检验（机制成不成立的核心）===')
ms = [b[4] for b in buckets]
print('  各档收益:', '  '.join(f'{x:+.2f}' for x in ms))
# Spearman 秩相关
n = len(buckets)
rank_r = list(range(1, n + 1))
rank_v = [sorted(ms).index(x) + 1 for x in ms]
d2 = sum((rank_r[i] - rank_v[i]) ** 2 for i in range(n))
rho = 1 - 6 * d2 / (n * (n * n - 1))
print(f'  Spearman ρ = {rho:+.3f}  → {"单调正向" if rho > 0.5 else ("单调负向" if rho < -0.5 else "无单调关系")}')

top = buckets[-1]
mid = buckets[len(buckets) // 2]
print(f'\n最高档 D{top[0]}（跌停 {top[1]}-{top[2]} 家）: {top[4]:+.2f}%')
print(f'中位档 D{mid[0]}（跌停 {mid[1]}-{mid[2]} 家）: {mid[4]:+.2f}%')
print(f'差 = {top[4]-mid[4]:+.2f}pp')

out = ROOT / 'research' / 'panic_dose_response.json'
out.write_text(json.dumps({'buckets': buckets, 'spearman': rho}, ensure_ascii=False))
print(f'\n已存 {out}')
