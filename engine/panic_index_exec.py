#!/usr/bin/env python3
"""engine/panic_index_exec.py — 恐慌日买宽基指数，效应还在吗？（2026-10-19）

已知：跌停≥24家时，T+1开盘买「全市场等权」→ T+5 收盘，每笔 +1.32%，年化 +14.5%。
但等权全市场散户买不了。本脚本检验可执行版本：买宽基指数。
如果指数上效应消失，说明+1.32%是小盘股噪声，策略不可执行，早点知道。
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

# 指数
idx = {}
for name, fn in (('上证指数', 'index_sh000001.json'),):
    p = ROOT / 'data' / fn
    if p.exists():
        j = json.loads(p.read_text())
        idx[name] = {r['date']: r for r in j}

print('本地指数:', {k: len(v) for k, v in idx.items()})

# 等权全市场 fwd（对照）
cal = sorted({k['date'] for ks in data.values() for k in ks})
ci = {d: i for i, d in enumerate(cal)}
IDX = {c: {k['date']: i for i, k in enumerate(ks)} for c, ks in data.items()}


def fwd_ew(d):
    j = ci.get(d)
    if j is None or j + 1 + HOLD >= len(cal):
        return None
    bd, sd = cal[j + 1], cal[j + 1 + HOLD]
    rs = []
    for c, ks in data.items():
        ix = IDX[c]
        if d in ix and bd in ix and sd in ix:
            bp, sp = ks[ix[bd]]['open'], ks[ix[sd]]['close']
            if bp > 0 and sp > 0:
                rs.append(sp / bp - 1 - COST)
    return st.mean(rs) * 100 if len(rs) >= 100 else None


def fwd_idx(d, name):
    m = idx[name]
    j = ci.get(d)
    if j is None or j + 1 + HOLD >= len(cal):
        return None
    bd, sd = cal[j + 1], cal[j + 1 + HOLD]
    if bd not in m or sd not in m:
        return None
    bp, sp = m[bd]['open'], m[sd]['close']
    if bp <= 0 or sp <= 0:
        return None
    return (sp / bp - 1 - COST) * 100


print(f"\n=== 恐慌日（跌停≥24家）各标的 T+1开盘→T+5收盘 ===")
print(f"{'门槛':<8}{'标的':<12}{'天数':>6}{'均值':>9}{'胜率':>8}{'最差':>9}")
for th in (24, 50):
    days = [d for d in n_dn if n_dn[d] >= th]
    ev_ew, ev_ix = [], []
    for d in days:
        a = fwd_ew(d)
        b = fwd_idx(d, '上证指数')
        if a is not None:
            ev_ew.append(a)
        if b is not None:
            ev_ix.append(b)
    for lab, R in (('全市场等权', ev_ew), ('上证指数', ev_ix)):
        if len(R) < 10:
            continue
        print(f"  ≥{th:<6}{lab:<12}{len(R):>6}{st.mean(R):>+8.2f}%"
              f"{sum(1 for x in R if x>0)/len(R)*100:>7.1f}%{min(R):>+8.1f}%")

print('\n=== 全样本对照：所有交易日的基准（无恐慌条件）===')
all_ix = [fwd_idx(d, '上证指数') for d in cal]
all_ix = [x for x in all_ix if x is not None]
print(f'  上证指数 全样本 T+5: n={len(all_ix)} 均值 {st.mean(all_ix):+.3f}%')
all_ew = [fwd_ew(d) for d in cal]
all_ew = [x for x in all_ew if x is not None]
print(f'  全市场等权 全样本 T+5: n={len(all_ew)} 均值 {st.mean(all_ew):+.3f}%')
