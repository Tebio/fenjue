#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine/limitup_exit_dig.py — 打板线卖出端深挖：日内振幅到底能不能吃到

动机（2026-10-19）：观察到期涨停票的次日日内最高相对最低有十几个点的空间，
而现行规则只在开盘卖（+2.57%/笔）。本脚本回答：**这些日内空间，用可执行的挂单规则能吃到多少？**

数据：data/big_kcache_unadj/<code>.json（不复权日线，含 O/H/L/C，与涨停价同口径）
      打板样本 = 33 个月（2024-01~2026-10），回补 CSV + 生产 CSV 合并

铁律：
  1. 只用 T+1 的 O/H/L/C，绝不用未来数据。
  2. 「挂限价单」的成交判定：T+1 high ≥ 挂价 即成交在该价，否则按收盘卖。
     这是唯一诚实的假设——日内路径未知，但「最高价触及过某价位」是确定事实。
  3. 涉及「先涨后跌 / 先跌后涨」路径的规则（移动止盈），给出双向区间，
     不当成确定收益。

输出：data/limitup_exit_dig_20261019.txt
"""
import csv
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path('/opt/data/fenjue')
KDIR = ROOT / 'data/big_kcache_unadj'
COST = 0.002
OUT = ROOT / 'data/limitup_exit_dig_20261019.txt'

MB = ('600', '601', '603', '605', '000', '001', '002', '003')


def mb(code):
    return code[:3] in MB


def num(v):
    try:
        return float(v)
    except Exception:
        return None


def rule_pass(r):
    hs, fu, lb = num(r.get('换手率(%)')), num(r.get('封单额/流通市值(%)')), num(r.get('连板数'))
    if hs is None or fu is None or lb is None:
        return False
    fbt = (r.get('首次封板时间') or '')[:5]
    return hs < 4.0 and fu < 1.0 and fbt != '' and fbt <= '10:00' and lb <= 2


_K = {}


def kline(code):
    if code in _K:
        return _K[code]
    p = KDIR / f'{code}.json'
    d = None
    if p.exists():
        try:
            j = json.loads(p.read_text())
            if isinstance(j, list):
                d = {x['date']: x for x in j}
            elif isinstance(j, dict):
                dd = j.get('data') or j
                if isinstance(dd, dict) and 'date' in dd:
                    d = {a: {'open': o, 'high': h, 'low': l, 'close': c}
                         for a, o, h, l, c in zip(dd['date'], dd['open'], dd['high'],
                                                  dd['low'], dd['close'])}
                elif isinstance(dd, dict):
                    d = dd
        except Exception:
            d = None
    _K[code] = d
    return d


def load_samples():
    """→ [(date, code, buy_px, next_open, next_high, next_low, next_close)]
    buy_px = T 日涨停价（不复权收盘），next_* = T+1 不复权 OHLC"""
    rows = []
    for fn in ('data/limitup_pool_backfill_2024_2025.csv',
               'data/limit_up_mainboard_20250908_20260922.csv',
               'data/limit_up_mainboard_20260923_20261019.csv'):
        p = ROOT / fn
        if not p.exists():
            continue
        with p.open(encoding='utf-8-sig') as fh:
            for r in csv.DictReader(fh):
                if not rule_pass(r):
                    continue
                code = (r.get('代码') or '').strip()
                d = (r.get('日期') or '').strip()
                if not mb(code) or len(d) != 10:
                    continue
                rows.append((d, code))
    out, miss = [], 0
    for d, code in rows:
        k = kline(code)
        if not k:
            miss += 1
            continue
        keys = sorted(k)
        if d not in k:
            miss += 1
            continue
        i = keys.index(d)
        if i + 1 >= len(keys):
            continue
        t, n = k[d], k[keys[i + 1]]
        try:
            buy = float(t['close'])
            o, h, l, c = float(n['open']), float(n['high']), float(n['low']), float(n['close'])
        except Exception:
            miss += 1
            continue
        if buy <= 0 or o <= 0 or c <= 0 or h <= 0:
            miss += 1
            continue
        out.append((d, code, buy, o, h, l, c))
    return out, miss


def main():
    S, miss = load_samples()
    L = []
    L.append('打板线卖出端深挖 — 日内空间能不能吃到')
    L.append(f'样本 n={len(S)}  缺K线跳过 {miss}  区间 {min(s[0] for s in S)} ~ {max(s[0] for s in S)}')
    L.append('买价 = T 日涨停价（不复权收盘）；T+1 用不复权 OHLC；全部扣 0.2% 成本')
    L.append('')

    # ---------- 一、日内结构 ----------
    L.append('=' * 76)
    L.append('一、T+1 日内结构（全部相对买入价 = T 日涨停价）')
    L.append('=' * 76)
    def g(s, idx):
        return (s[idx] / s[2] - 1) * 100
    for name, idx in (('开盘价', 3), ('最高价', 4), ('最低价', 5), ('收盘价', 6)):
        v = [g(s, idx) for s in S]
        L.append(f'  {name}  均值 {st.mean(v):>+6.2f}%  中位 {st.median(v):>+6.2f}%  '
                 f'p10 {sorted(v)[len(v)//10]:>+6.2f}%  p90 {sorted(v)[len(v)*9//10]:>+6.2f}%')
    span = [g(s, 4) - g(s, 5) for s in S]
    L.append(f'  日内振幅(最高-最低)  均值 {st.mean(span):>6.2f}%  中位 {st.median(span):>6.2f}%  '
             f'p90 {sorted(span)[len(span)*9//10]:>6.2f}%')
    up_from_open = [(s[4] / s[3] - 1) * 100 for s in S]
    dn_from_open = [(s[5] / s[3] - 1) * 100 for s in S]
    L.append(f'  最高价相对开盘  均值 {st.mean(up_from_open):>+6.2f}%  中位 {st.median(up_from_open):>+6.2f}%')
    L.append(f'  最低价相对开盘  均值 {st.mean(dn_from_open):>+6.2f}%  中位 {st.median(dn_from_open):>+6.2f}%')
    L.append('')

    # ---------- 二、可执行卖出规则 ----------
    L.append('=' * 76)
    L.append('二、可执行卖出规则对比（挂限价单，high≥挂价即成交，否则收盘卖）')
    L.append('=' * 76)

    def stat(name, rets):
        rets = sorted(rets)
        n = len(rets)
        L.append(f'  {name:<34} n={n:<5} 均值 {st.mean(rets):+6.2f}%  中位 {st.median(rets):+6.2f}%  '
                 f'胜率 {sum(1 for x in rets if x > 0) / n * 100:5.1f}%  p1 {rets[n // 100]:+6.2f}%  '
                 f'最差 {rets[0]:+6.2f}%')
        return st.mean(rets)

    base = stat('A 开盘卖（现行基准）', [(s[3] / s[2] - 1 - COST) * 100 for s in S])
    L.append('')
    best = ('A', base)
    for X in (1, 2, 3, 4, 5, 6, 8, 10):
        rets, filled = [], 0
        for s in S:
            lim = s[2] * (1 + X / 100)
            if s[4] >= lim:
                rets.append((max(lim, s[3]) / s[2] - 1 - COST) * 100)   # 跳空高开则以开盘价卖出
                filled += 1
            else:
                rets.append((s[6] / s[2] - 1 - COST) * 100)
        m = stat(f'B 挂 +{X}% 限价，未触及收盘卖', rets)
        L.append(f'      成交率 {filled / len(S) * 100:.1f}%')
        if m > best[1]:
            best = (f'B+{X}%', m)
    L.append('')
    for X in (3, 5, 8):
        for half in (0.5,):
            rets = []
            for s in S:
                lim = s[2] * (1 + X / 100)
                r1 = s[3] / s[2] - 1 - COST
                r2 = (max(lim, s[3]) / s[2] - 1 - COST) if s[4] >= lim else (s[6] / s[2] - 1 - COST)
                rets.append(((r1 * half + r2 * (1 - half))) * 100)
            m = stat(f'C 开盘卖半仓 + 半仓挂 +{X}%', rets)
            if m > best[1]:
                best = (f'C+{X}%', m)
    L.append('')
    # 移动止盈：路径未知 → 双向区间
    for X in (3, 5):
        lo_list, hi_list = [], []
        for s in S:
            open_r = s[3] / s[2] - 1 - COST
            peak_r = s[4] / s[2] - 1 - COST
            # 上界：先冲最高再回落 X 点卖出
            hi_list.append((peak_r - X / 100) * 100)
            # 下界：直接跌到收盘（没触发）
            lo_list.append(open_r * 100 if peak_r - X / 100 < open_r else open_r * 100)
        L.append(f'  D 从最高回落 {X}% 止盈   上界均值 {st.mean(hi_list):+6.2f}%  '
                 f'下界均值 {st.mean(lo_list):+6.2f}%（路径未知，实际落在两者之间，不可当确定收益）')
    L.append('')

    # ---------- 三、分年 ----------
    L.append('=' * 76)
    L.append('三、最优规则的分年稳定性')
    L.append('=' * 76)
    byy = {}
    for s in S:
        byy.setdefault(s[0][:4], []).append(s)
    tag = best[0]
    L.append(f'  最优规则 = {tag}（均值 {best[1]:+.2f}%），分年对照 A 开盘卖：')
    L.append(f'  {"年份":<6}{"n":>6}{"A开盘":>10}{tag:>12}{"差":>10}')
    for y in sorted(byy):
        sub = byy[y]
        ra = st.mean([(s[3] / s[2] - 1 - COST) * 100 for s in sub])
        if tag.startswith('B+'):
            X = float(tag[2:].rstrip('%'))
            rb = st.mean([((s[2] * (1 + X / 100)) / s[2] - 1 - COST) * 100
                          if s[4] >= s[2] * (1 + X / 100) else (s[6] / s[2] - 1 - COST) * 100 for s in sub])
        elif tag.startswith('C+'):
            X = float(tag[2:].rstrip('%'))
            rb = st.mean([((s[3] / s[2] - 1 - COST) * 0.5 +
                           ((((s[2] * (1 + X / 100)) / s[2] - 1 - COST) if s[4] >= s[2] * (1 + X / 100)
                             else (s[6] / s[2] - 1 - COST)) * 0.5)) * 100 for s in sub])
        else:
            rb = ra
        L.append(f'  {y:<6}{len(sub):>6}{ra:>+9.2f}%{rb:>+11.2f}%{rb - ra:>+9.2f}pp')
    L.append('')

    # ---------- 四、触达概率 ----------
    L.append('=' * 76)
    L.append('四、T+1 盘中触达各档涨幅的概率（决定限价单能不能成交）')
    L.append('=' * 76)
    for X in (1, 2, 3, 4, 5, 6, 8, 10, 15):
        k = sum(1 for s in S if s[4] >= s[2] * (1 + X / 100))
        L.append(f'  最高触及 +{X:>2}%：{k:>5}/{len(S)} = {k / len(S) * 100:>5.1f}%')
    L.append('')
    txt = '\n'.join(L)
    print(txt)
    OUT.write_text(txt + '\n', encoding='utf-8')
    print(f'\n已写入 {OUT.name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
