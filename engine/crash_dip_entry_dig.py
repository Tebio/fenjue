#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine/crash_dip_entry_dig.py — 崩盘抄底线的买入端深挖：低吸挂单能不能降成本

动机（2026-10-19）：崩盘次日这批票日内振幅大，开盘往往不是当天最低点。
本脚本回答：**挂低吸限价单（相对 T 日收盘价下浮 X%），能不能比开盘价买更便宜，
且便宜到足以抵消「没成交就错过」的代价？**

数据：law_pipeline.load_universe()（前复权，含 O/H/L/C，主板 3335 只 2018~2026-10）
信号：当日跌停（≤-9.8%）且收盘 ≤ MA60，当日信号数 ≥ 50 才出手（与生产一致）
卖点：买入后第 5 个交易日收盘（与生产一致），扣 0.2%

四种买入方案（全部可执行，无未来函数）：
  A 开盘价买（现行基准）
  B1 挂 T日收盘×(1-X%) 限价；未成交则**放弃**（样本缩水，但成本确实降了）
  B2 挂 T日收盘×(1-X%) 限价；未成交则**以开盘价买**（全样本，部分降成本）
  C  以 T+1 最低价买（**不可执行**，仅作理论上限，用来衡量还剩多少空间）
  D  以 T+1 最低价和开盘价的均值买（介于两者，参考）

输出：data/crash_dip_entry_dig_20261019.txt
"""
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, '/opt/data/fenjue/engine')
sys.path.insert(0, '/opt/data/python-libs')
import law_pipeline as lp  # noqa: E402

ROOT = Path('/opt/data/fenjue')
OUT = ROOT / 'data/crash_dip_entry_dig_20261019.txt'
COST = 0.002
THRESHOLD = 50
LIMIT_DOWN = -0.098
HOLD = 5


def main():
    U = lp.load_universe()
    cal = sorted({d for c, x in U.items() if c[:2] in ('60', '00') for d in x['date']})
    ci = {d: i for i, d in enumerate(cal)}
    idx = {c: {dt: i for i, dt in enumerate(d['date'])}
           for c, d in U.items() if c[:2] in ('60', '00')}

    # 信号
    sig = {}
    for c, d in U.items():
        if c[:2] not in ('60', '00'):
            continue
        cn, ma, n, dt = d['c'], d['ma60'], d['n'], d['date']
        for i in range(61, n):
            if cn[i - 1] <= 0 or cn[i] <= 0 or not ma[i]:
                continue
            if cn[i] / cn[i - 1] - 1 <= LIMIT_DOWN and cn[i] <= ma[i]:
                sig.setdefault(dt[i], []).append(c)
    trig = sorted(d for d in sig if len(sig[d]) >= THRESHOLD)

    # 每笔明细：只取价格最低 20 只（可执行子集，见 AGENTS #314）
    trades = []   # (date, code, ref_px=T日收盘, o, h, l, sell_close)
    for dt in trig:
        i = ci[dt]
        if i + 1 + HOLD >= len(cal):
            continue
        buy_d, sell_d = cal[i + 1], cal[i + 1 + HOLD]
        cs = sorted(sig[dt], key=lambda c: U[c]['c'][idx[c][dt]])[:20]
        for c in cs:
            d = U[c]
            j = idx[c]
            if buy_d not in j or sell_d not in j:
                continue
            ref = d['c'][j[dt]]
            o, h, l = d['o'][j[buy_d]], d['h'][j[buy_d]], d['l'][j[buy_d]]
            sc = d['c'][j[sell_d]]
            if ref <= 0 or o <= 0 or l <= 0 or sc <= 0:
                continue
            trades.append((dt, c, ref, o, h, l, sc))

    L = []
    L.append('崩盘抄底线买入端深挖 — 低吸挂单能不能降成本')
    L.append(f'触发日 {len(trig)} 个，样本 {len(trades)} 笔（每次取价格最低 20 只）')
    L.append(f'区间 {trig[0]} ~ {trig[-1]}；卖点 = 买入后第 {HOLD} 个交易日收盘；扣 0.2%')
    L.append('')

    L.append('=' * 78)
    L.append('一、买入日的日内结构（相对 T 日收盘价，即信号日收盘）')
    L.append('=' * 78)
    for name, k in (('开盘价', 3), ('最高价', 4), ('最低价', 5)):
        v = [(t[k] / t[2] - 1) * 100 for t in trades]
        v.sort()
        L.append(f'  {name}  均值 {st.mean(v):>+6.2f}%  中位 {st.median(v):>+6.2f}%  '
                 f'p10 {v[len(v) // 10]:>+6.2f}%  p90 {v[len(v) * 9 // 10]:>+6.2f}%')
    # 开盘是不是当天最低
    at_low = sum(1 for t in trades if t[5] >= t[3] * 0.999)
    L.append(f'  开盘价就是当日最低价：{at_low}/{len(trades)} = {at_low / len(trades) * 100:.1f}%'
             f'  → 另外 {100 - at_low / len(trades) * 100:.1f}% 的日子开盘后还能更低')
    gap = [(t[3] / t[2] - 1) * 100 for t in trades]
    L.append(f'  开盘相对信号日收盘的低开幅度 均值 {st.mean(gap):+.2f}%'
             f'（{sum(1 for x in gap if x < 0) / len(gap) * 100:.0f}% 是低开）')
    L.append('')

    # 每笔按日分组，算日等权组合
    def report(label, picker):
        byd = {}
        for t in trades:
            px = picker(t)
            if px is None:
                continue
            byd.setdefault(t[0], []).append(t[6] / px - 1 - COST)
        if not byd:
            return None, None, 0
        daily = [st.mean(v) for v in byd.values()]
        eq = 1.0
        for r in daily:
            eq *= 1 + r
        allr = [x for v in byd.values() for x in v]
        yrs = 7.31
        L.append(f'  {label:<40} 日数 {len(byd):>3}  笔数 {len(allr):>5}  '
                 f'单笔 {st.mean(allr) * 100:+6.2f}%  日组合均 {st.mean(daily) * 100:+6.2f}%  '
                 f'胜率 {sum(1 for x in allr if x > 0) / len(allr) * 100:5.1f}%  复利 {(eq - 1) * 100:+7.0f}%  '
                 f'年化 {(eq ** (1 / yrs) - 1) * 100:+6.1f}%')
        return eq, st.mean(allr), len(allr)

    L.append('=' * 78)
    L.append('二、四种买入方案（日等权组合口径，复利按全部触发日滚）')
    L.append('=' * 78)
    base = report('A 开盘价买（现行基准）', lambda t: t[3])
    L.append('')
    for X in (1, 2, 3, 4, 5, 6, 8):
        # B1: 未成交放弃
        def p_b1(t, X=X):
            lim = t[2] * (1 - X / 100)
            if t[5] <= lim:                       # 最低价触及挂价 → 成交
                return min(lim, t[3])             # 跳空低开时以更优的开盘价成交
            return None

        def p_b2(t, X=X):
            lim = t[2] * (1 - X / 100)
            if t[5] <= lim:
                return min(lim, t[3])
            return t[3]

        filled = sum(1 for t in trades if t[5] <= t[2] * (1 - X / 100))
        L.append(f'  —— 下浮 {X}%（成交率 {filled / len(trades) * 100:.1f}%）——')
        report(f'B1 挂 -{X}% 限价，未成交放弃', p_b1)
        report(f'B2 挂 -{X}% 限价，未成交按开盘买', p_b2)
    L.append('')
    L.append(f'  —— 理论上限（不可执行，只看还剩多少空间）——')
    report('C 以当日最低价买（不可执行）', lambda t: t[5])
    report('D 以开盘与最低的均值买（不可执行）', lambda t: (t[3] + t[5]) / 2)
    L.append('')

    # 分年：最优方案 vs 基准
    L.append('=' * 78)
    L.append('三、最优可执行方案的分年稳定性（对比 A 开盘买）')
    L.append('=' * 78)
    cands = []
    for X in (1, 2, 3, 4, 5, 6, 8):
        for tag, fn in (('B1', lambda t, X=X: min(t[2] * (1 - X / 100), t[3]) if t[5] <= t[2] * (1 - X / 100) else None),
                        ('B2', lambda t, X=X: min(t[2] * (1 - X / 100), t[3]) if t[5] <= t[2] * (1 - X / 100) else t[3])):
            byd = {}
            for t in trades:
                px = fn(t)
                if px is None:
                    continue
                byd.setdefault(t[0], []).append(t[6] / px - 1 - COST)
            if byd:
                cands.append((tag + f'-{X}%', st.mean([st.mean(v) for v in byd.values()])))
    L.append('  各可执行方案日组合均值：' + '  '.join(f'{n}={v * 100:+.2f}%' for n, v in cands))
    best = max(cands, key=lambda x: x[1])
    L.append(f'  最优 = {best[0]}（{best[1] * 100:+.2f}% vs 基准 {base[1] * 100 if base[1] else 0:+.2f}%）')
    tag, _ = best
    kind, xp = tag.split('-')
    X = float(xp.rstrip('%'))
    L.append(f'  {"年份":<8}{"n":>6}{"A开盘":>10}{tag:>12}{"差":>10}')
    byy = {}
    for t in trades:
        byy.setdefault(t[0][:4], []).append(t)
    for y in sorted(byy):
        sub = byy[y]
        ra = st.mean([(t[6] / t[3] - 1 - COST) * 100 for t in sub])
        rs = []
        for t in sub:
            lim = t[2] * (1 - X / 100)
            if t[5] <= lim:
                px = min(lim, t[3])
            else:
                px = None if kind == 'B1' else t[3]
            if px:
                rs.append((t[6] / px - 1 - COST) * 100)
        rb = st.mean(rs) if rs else float('nan')
        L.append(f'  {y:<8}{len(sub):>6}{ra:>+9.2f}%{rb:>+11.2f}%{rb - ra:>+9.2f}pp')
    L.append('')
    L.append('注：B1 的日组合只统计成交的日子，样本会少于基准，复利不可直接横向比；'
             '以「单笔均值」和「分年方向一致」为准。')

    txt = '\n'.join(L)
    print(txt)
    OUT.write_text(txt + '\n', encoding='utf-8')
    print(f'\n已写入 {OUT.name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
