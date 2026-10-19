#!/usr/bin/env python3
"""engine/alpha_vs_beta.py — 策略A 是同日市场调整后的 alpha 还是纯 beta？（2026-10-19）

K3 的致命一问：策略A「跌停×MA60下」T+5 +5.28% 没做同日市场调整。
若减去同期市场收益后≈0，则它与策略B（ETF beta择时）是同一笔交易，
14274 个"信号"只是少数独立下注的杠杆重述，样本量高估两个数量级。

本脚本输出：
  1. 策略A 原始 T+5 均值
  2. 减同期上证指数收益 → 超额
  3. 减同期全市场等权收益 → 超额（更严格，剔除小盘风格）
  4. 事件聚簇后的独立事件数（K3 断言 20-30 个）
"""
import json
import statistics as st
from pathlib import Path

ROOT = Path('/opt/data/fenjue')
KC = ROOT / 'data/big_kcache'
HOLD = 5
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

IX = {r['date']: r for r in json.loads((ROOT / 'data/index_sh000001.json').read_text())}
cal = sorted({k['date'] for ks in data.values() for k in ks})
ci = {d: i for i, d in enumerate(cal)}
IDX = {c: {k['date']: i for i, k in enumerate(ks)} for c, ks in data.items()}

# 交易日 → 每只股票的日收益（用于全市场等权）
dret = {}
for c, ks in data.items():
    for i in range(1, len(ks)):
        pc = ks[i - 1]['close']
        if pc > 0:
            dret.setdefault(ks[i]['date'], []).append(ks[i]['close'] / pc - 1)
mkt = {d: st.mean(v) for d, v in dret.items() if len(v) >= 500}


def ma(ks, i, n=60):
    if i + 1 < n:
        return None
    return sum(k['close'] for k in ks[i + 1 - n:i + 1]) / n


events = []
for c, ks in data.items():
    ix = IDX[c]
    for i in range(60, len(ks) - 1):
        pc = ks[i - 1]['close']
        if pc <= 0:
            continue
        lim = round(pc * 0.9, 2)
        if not (lim * 0.994 <= ks[i]['close'] <= lim * 1.0005):
            continue
        m = ma(ks, i)
        if m is None or ks[i]['close'] > m:
            continue
        bi = i + 1
        if bi >= len(ks):
            continue
        # 剔一字板：次日开盘即涨停买不到
        lim_up = round(ks[i]['close'] * 1.1, 2)
        if ks[bi]['open'] >= lim_up * 0.999:
            continue
        bp = ks[bi]['open']
        if bp <= 0:
            continue
        # 卖出日：从买入日起第 HOLD 个交易日
        si = bi + HOLD
        if si >= len(ks):
            continue
        sp = ks[si]['close']
        if sp <= 0:
            continue
        events.append((c, ks[i]['date'], ks[bi]['date'], ks[si]['date'], sp / bp - 1))

print(f'策略A 事件 n={len(events)}')

raw = [e[4] * 100 for e in events]

# 同期上证收益
ix_ex = []
for c, d, bd, sd, r in events:
    if bd in IX and sd in IX:
        bp, sp = IX[bd]['open'], IX[sd]['close']
        if bp > 0 and sp > 0:
            ix_ex.append((r - (sp / bp - 1)) * 100)

# 同期全市场等权收益
ew_ex = []
for c, d, bd, sd, r in events:
    jb, js = ci.get(bd), ci.get(sd)
    if jb is None or js is None:
        continue
    acc = 1.0
    ok = True
    for k in range(jb, js + 1):
        v = mkt.get(cal[k])
        if v is None:
            ok = False
            break
        acc *= 1 + v
    if ok:
        ew_ex.append((r - (acc - 1)) * 100)


def rep(lab, R):
    if not R:
        return
    m = st.mean(R)
    sd = st.stdev(R)
    t = m / sd * (len(R) ** 0.5)
    print(f'  {lab:<22}{len(R):>7}{m:>+9.2f}%{sum(1 for x in R if x>0)/len(R)*100:>8.1f}%'
          f'{st.median(R):>+9.2f}%{t:>8.2f}')


print(f"\n{'口径':<22}{'n':>7}{'均值':>9}{'胜率':>8}{'中位':>9}{'t':>8}")
rep('策略A 原始', raw)
rep('减 上证指数', ix_ex)
rep('减 全市场等权', ew_ex)

# 独立事件数
print('\n=== 事件聚簇：独立 episode 数（连续信号日=同一簇，间隔>5交易日=新簇）===')
days = sorted({e[1] for e in events})
cl = [[days[0]]]
for d in days[1:]:
    if ci[d] - ci[cl[-1][-1]] <= HOLD:
        cl[-1].append(d)
    else:
        cl.append([d])
print(f'  独立 episode 数 = {len(cl)}  （K3 断言 20-30 个）')
print(f'  平均每簇 {len(days)/len(cl):.1f} 个信号日')
# 按月看集中度
by_m = {}
for d in days:
    by_m[d[:7]] = by_m.get(d[:7], 0) + 1
top = sorted(by_m.items(), key=lambda x: -x[1])[:5]
print(f'  最集中的 5 个月: ' + ', '.join(f'{k}({v})' for k, v in top)
      + f'  合计占 {sum(v for _, v in top)/len(days)*100:.1f}%')
