#!/usr/bin/env python3
"""engine/m5_fill_model.py — 用 5 分钟线实测「涨停价上能不能买到」（2026-10-19）

背景：打板线的全部数学都建立在一个猜的数字上——成交率 44.2%（假设"炸板过就能成交"）。
这个脚本用真实盘中数据把它换成实测。

输出三块：
  A. 涨停日的盘中结构（首封时间 / 封板时长 / 炸板次数 / 板上换手）
  B. 分档的成交概率代理（板上换手 × 首封时间 × 是否炸板）
  C. 真实期望：P(成交)×E[收益|成交]，与"全成交"假设的差距
"""
import json
import statistics as st
from pathlib import Path

ROOT = Path('/opt/data/fenjue')
KC = ROOT / 'data/big_kcache'
CH = ROOT / 'data/cap_hist'
M5 = ROOT / 'data/m5'

COST = 0.002


def load_daily(code):
    p = KC / f'{code}.json'
    if not p.exists():
        return None
    ks = json.loads(p.read_text())
    if not isinstance(ks, list) or len(ks) < 130:
        return None
    return ks


def shares(code):
    p = CH / f'{code}.json'
    if not p.exists():
        return None
    j = json.loads(p.read_text())
    if not isinstance(j, list) or not j:
        return None
    px, mc = float(j[-1][1]), float(j[-1][2])
    if px <= 0 or mc <= 0:
        return None
    return mc * 1e8 / px


def day_structure(bars5, limit):
    """单日 5 分钟线 → 盘中结构。bars5 = [(time, o,h,l,c,vol,amt), ...]"""
    sealed = [i for i, b in enumerate(bars5) if b[4] >= limit * 0.9995]
    if not sealed:
        return None
    first = sealed[0]
    vol_on = sum(bars5[i][5] for i in sealed)
    # 炸板次数：板上→板下 的切换数
    breaks = 0
    for i in range(1, len(bars5)):
        was = bars5[i - 1][4] >= limit * 0.9995
        now = bars5[i][4] >= limit * 0.9995
        if was and not now:
            breaks += 1
    return {
        'first_seal_bar': first,             # 0 = 09:35, 越早封越硬
        'seal_bars': len(sealed),
        'seal_minutes': len(sealed) * 5,
        'breaks': breaks,
        'vol_on_limit': vol_on,
        'vol_total': sum(b[5] for b in bars5),
    }


def main():
    files = sorted(M5.glob('*.json'))
    print(f'5min 样本 {len(files)} 只\n')
    events = []
    for fp in files:
        code = fp.stem
        ks = load_daily(code)
        sh = shares(code)
        if not ks or not sh:
            continue
        try:
            m5 = json.loads(fp.read_text())
        except Exception:
            continue
        by_day = {}
        for b in m5:
            d = b[0][:8]              # 20250105093500000 → 20250105
            by_day.setdefault(f'{d[:4]}-{d[4:6]}-{d[6:8]}', []).append(b)
        idx = {k['date']: i for i, k in enumerate(ks)}
        for d, bars in by_day.items():
            i = idx.get(d)
            if i is None or i < 1 or i + 1 >= len(ks):
                continue
            pc = ks[i - 1]['close']
            if pc <= 0:
                continue
            lim = round(pc * 1.1, 2)
            # 当日必须触及涨停
            if ks[i]['high'] < lim * 0.9995 or ks[i]['high'] > lim * 1.005:
                continue
            s = day_structure(bars, lim)
            if not s:
                continue
            nxt = ks[i + 1]['open']
            if nxt <= 0:
                continue
            events.append({
                'code': code, 'date': d,
                'sealed': int(ks[i]['close'] >= lim * 0.9995),
                'ret_if_filled': (nxt / lim - 1 - COST) * 100,   # 涨停价买、次日开盘卖
                'on_turn': s['vol_on_limit'] / sh * 100,
                'first_seal_bar': s['first_seal_bar'],
                'seal_minutes': s['seal_minutes'],
                'breaks': s['breaks'],
                'share_on_limit': s['vol_on_limit'] / s['vol_total'] if s['vol_total'] else 0,
            })
    print(f'触及涨停事件 {len(events)} 个（样本股范围内）\n')
    if not events:
        return
    sealed = [e for e in events if e['sealed']]
    print(f'  收盘封住 {len(sealed)}  ({len(sealed)/len(events)*100:.1f}%)')

    print('\n=== A. 盘中结构（按首封时间分档）===')
    print(f"{'首封时段':<14}{'n':>7}{'封板分钟中位':>12}{'板上换手中位':>13}{'炸板率':>9}{'封板率':>9}")
    bands = [(0, 1, '09:35 开盘即封'), (1, 7, '09:40-10:25'), (7, 25, '10:30-11:55'),
             (25, 49, '13:05-15:00'), (49, 99, '尾盘/未封')]
    for lo, hi, lab in bands:
        sub = [e for e in events if lo <= e['first_seal_bar'] < hi]
        if len(sub) < 20:
            continue
        print(f"  {lab:<14}{len(sub):>7}{st.median([e['seal_minutes'] for e in sub]):>11.0f}m"
              f"{st.median([e['on_turn'] for e in sub]):>12.2f}%"
              f"{sum(1 for e in sub if e['breaks']>0)/len(sub)*100:>8.1f}%"
              f"{sum(1 for e in sub if e['sealed'])/len(sub)*100:>8.1f}%")

    print('\n=== B. 成交概率代理：板上换手（这是唯一能观测到的"队被消耗"证据）===')
    for lo, hi, lab in ((0, 0.2, '<0.2%'), (0.2, 0.5, '0.2-0.5%'), (0.5, 1.5, '0.5-1.5%'),
                        (1.5, 4.0, '1.5-4%'), (4.0, 999, '>4%')):
        sub = [e for e in sealed if lo <= e['on_turn'] < hi]
        if len(sub) < 20:
            continue
        brk = sum(1 for e in sub if e['breaks'] > 0) / len(sub) * 100
        print(f"  板上换手 {lab:<10} n={len(sub):>6}  炸板率 {brk:>5.1f}%  "
              f"次日开盘溢价均值 {st.mean([e['ret_if_filled'] for e in sub]):+.2f}%")

    print('\n=== C. 三种成交假设下的期望对比 ===')
    allr = [e['ret_if_filled'] for e in events]
    brk_only = [e['ret_if_filled'] for e in events if e['breaks'] > 0]
    lo_turn = [e['ret_if_filled'] for e in events if e['breaks'] > 0 and e['on_turn'] >= 0.5]
    print(f'  (i)   全成交假设（旧口径）      n={len(allr):>6}  均值 {st.mean(allr):+.2f}%')
    print(f'  (ii)  炸板过才成交（我原用44.2%）n={len(brk_only):>6}  均值 {st.mean(brk_only):+.2f}%   '
          f'成交率 {len(brk_only)/len(events)*100:.1f}%')
    print(f'  (iii) 炸板且板上换手≥0.5%（更严）n={len(lo_turn):>6}  均值 {st.mean(lo_turn):+.2f}%   '
          f'成交率 {len(lo_turn)/len(events)*100:.1f}%')
    print('\n  真实期望 = 成交率 × 均值：')
    for lab, R in (('(i) 全成交', allr), ('(ii) 炸板过', brk_only), ('(iii) 炸板+换手', lo_turn)):
        p = len(R) / len(events)
        print(f'    {lab:<18} {p*100:>5.1f}% × {st.mean(R):+.2f}% = {p*st.mean(R):+.2f}%')

    out = ROOT / 'research' / 'm5_fill_events.json'
    out.write_text(json.dumps(events))
    print(f'\n已存 {out}  ({len(events)} 条)')


if __name__ == '__main__':
    main()
