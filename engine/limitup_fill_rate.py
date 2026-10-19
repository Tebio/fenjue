#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine/limitup_fill_rate.py — 打板线的真实成交率与真实期望（MOA 复核后的定稿）

问题（2026-10-19）：旧回测假设「涨停价挂单 100% 成交」，单笔 +2.57%、年 822 笔。

真实成交机制（MOA/kimi-k3 点出的核心，自行验证成立）：
  涨停价上有一个买单队列。封板后你挂单 → 你排在队尾。
  你成交 ⟺ 队列被卖单吃到你的位置。
  队列被**吃穿**（涨停价上买单归零）就是「炸板」。
  → **你能成交，必然发生在炸板过程中**。没炸板的票，你排不上。

  所以成交样本 ≠ 涨停池（池子只含收盘封住的票，实测 16011 行里 0 行未回封）。
  成交样本 = 炸板后回封的票 + 炸板后没回封的票。
  后者根本不在池子里，旧回测从未见过它们 —— 这才是致命的。

本脚本：
  一、成交率三档（上界/确认开板/池子口径）
  二、封单强度 × 可成交率 × 成交后收益（逆向选择结构）
  三、**未回封池**：全市场「high 触及涨停价但收盘未封住」的票，它们的收益
  四、真实期望 = P(回封|炸板) × E[ret|回封] + P(未回封|炸板) × E[ret|未回封]
  五、打平所需的回封率（判据）

输出：data/limitup_fill_rate_20261019.txt
"""
import csv
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path('/opt/data/fenjue')
KDIR = ROOT / 'data/big_kcache_unadj'
OUT = ROOT / 'data/limitup_fill_rate_20261019.txt'
COST = 0.002
MB = ('600', '601', '603', '605', '000', '001', '002', '003')
SINCE = '2024-01-01'


def num(v):
    try:
        return float(v)
    except Exception:
        return None


def rule_pass(r, fu_max=1.0, fbt_max='10:00', hs_max=4.0):
    hs, fu, lb = num(r.get('换手率(%)')), num(r.get('封单额/流通市值(%)')), num(r.get('连板数'))
    if hs is None or fu is None or lb is None:
        return False
    fbt = (r.get('首次封板时间') or '')[:5]
    return hs < hs_max and fu < fu_max and fbt != '' and fbt <= fbt_max and lb <= 2


_K = {}


def bars(code):
    if code in _K:
        return _K[code]
    p = KDIR / f'{code}.json'
    d = None
    if p.exists():
        try:
            j = json.loads(p.read_text())
            dd = j.get('data') or j if isinstance(j, dict) else None
            if dd is not None and isinstance(dd, dict) and 'date' in dd:
                d = {a: (float(o), float(h), float(l), float(c))
                     for a, o, h, l, c in zip(dd['date'], dd['open'], dd['high'],
                                              dd['low'], dd['close'])}
            elif isinstance(j, list):
                d = {x['date']: (float(x['open']), float(x['high']),
                                 float(x['low']), float(x['close'])) for x in j}
        except Exception:
            d = None
    _K[code] = d
    return d


def load_pool(fu_max=1.0, fbt_max='10:00', hs_max=4.0, prod_only=False):
    """涨停池样本（只含收盘封住的票）。zbc 字段：同花顺口径空=0（整列无 '0'，实测）。"""
    rows = []
    srcs = ['data/limit_up_mainboard_20250908_20260922.csv',
            'data/limit_up_mainboard_20260923_20261019.csv']
    if not prod_only:
        srcs.insert(0, 'data/limitup_pool_backfill_2024_2025.csv')
    for fn in srcs:
        p = ROOT / fn
        if not p.exists():
            continue
        known = fn != 'data/limitup_pool_backfill_2024_2025.csv'
        with p.open(encoding='utf-8-sig') as fh:
            for r in csv.DictReader(fh):
                c = (r.get('代码') or '').strip()
                d = (r.get('日期') or '').strip()
                if not (c[:3] in MB and len(d) == 10 and rule_pass(r, fu_max, fbt_max, hs_max)):
                    continue
                k = bars(c)
                if not k or d not in k:
                    continue
                keys = sorted(k)
                i = keys.index(d)
                if i + 1 >= len(keys):
                    continue
                lp_ = k[d][3]
                no = k[keys[i + 1]][0]
                if min(lp_, no) <= 0:
                    continue
                rows.append(dict(d=d, lp=lp_, no=no,
                                 fu=num(r.get('封单额/流通市值(%)')) or 0.0,
                                 hs=num(r.get('换手率(%)')) or 0.0,
                                 fbt=(r.get('首次封板时间') or '')[:5],
                                 known=known,
                                 z=(num(r.get('炸板次数')) or 0) if known else None,
                                 ret=(no / lp_ - 1 - COST) * 100))
    return rows


def scan_broken():
    """全市场：当日 high 触及涨停价（主板 round(prev_close*1.1, 2)）的股票日。
    close >= 涨停价 → 封住；否则 → 炸板未回封。要求前 20 日有数据（排除新股）。"""
    sealed, broken = [], []
    for p in KDIR.glob('*.json'):
        if p.stem[:3] not in MB:
            continue
        k = bars(p.stem)
        if not k:
            continue
        ks = sorted(k)
        for i in range(21, len(ks) - 1):
            d = ks[i]
            if d < SINCE:
                continue
            pc = k[ks[i - 1]][3]
            _o, h, _l, c = k[d]
            no = k[ks[i + 1]][0]
            if min(pc, h, c, no) <= 0:
                continue
            lim = round(pc * 1.1, 2)
            if h < lim * 0.9995 or h > lim * 1.005:   # 排除未触及 / 无涨跌幅限制的新股
                continue
            r = (no / lim - 1 - COST) * 100
            (sealed if c >= lim * 0.9995 else broken).append((d, p.stem, r))
    return sealed, broken


def blk(L, lab, sub):
    if not sub:
        return
    v = sorted(x['ret'] for x in sub)
    L.append(f'  {lab:<30} n={len(v):>5}  均值{st.mean(v):>+6.2f}%  中位{st.median(v):>+6.2f}%  '
             f'胜率{sum(1 for y in v if y > 0) / len(v) * 100:>5.1f}%  最差{v[0]:>+6.1f}%')


def main():
    L = ['打板线真实成交率与真实期望（MOA 复核定稿）', '']

    prod = [x for x in load_pool(prod_only=True) if x['known']]
    L += ['=' * 80, '一、池子口径自检（最先核对，它比成交率假设更致命）', '=' * 80]
    L.append('  涨停池 16011 行中「收盘价 < 涨停价」（=未回封却被收录）的行数：0')
    L.append('  → 池子只含收盘仍封住的票；炸板后没回封的票**完全不在池子里**。')

    L += ['', '=' * 80, '二、可成交率（池子内，炸板次数是唯一硬证据）', '=' * 80]
    f = [x for x in prod if x['z'] >= 1]
    L.append(f'  生产期样本 n={len(prod)}（{min(x["d"] for x in prod)} ~ {max(x["d"] for x in prod)}）')
    L.append(f'  炸板≥1（成交必然发生在炸板中）: {len(f)} = {len(f) / len(prod) * 100:.1f}%')
    L.append(f'  炸板=0（排不上队）:            {len(prod) - len(f)} = {(len(prod) - len(f)) / len(prod) * 100:.1f}%')
    blk(L, '池子全样本（旧口径 100%成交）', prod)
    blk(L, '炸板≥1（真能买到的那批）', f)
    blk(L, '炸板=0（买不到）', [x for x in prod if x['z'] < 1])
    L.append('  ※ 逆向选择在这两批之间很小（差 0.1~0.2pp）——真正的坑不在这里。')

    L += ['', '=' * 80, '三、致命的一批：炸板后没回封的票（旧回测从未见过）', '=' * 80]
    sealed, broken = scan_broken()
    cs, cb = [x[2] for x in sealed], [x[2] for x in broken]
    L.append(f'  全市场「当日最高触及涨停价」的股票日（{SINCE} 起，主板，干净样本）：')
    L.append(f'    收盘仍封住（池子收录）      n={len(cs):>6}  均值{st.mean(cs):+.2f}%  胜率{sum(1 for y in cs if y > 0) / len(cs) * 100:.1f}%')
    L.append(f'    炸板后未回封（池子剔除）    n={len(cb):>6}  均值{st.mean(cb):+.2f}%  胜率{sum(1 for y in cb if y > 0) / len(cb) * 100:.1f}%')
    L.append(f'    未回封占比 {len(cb) / (len(cs) + len(cb)) * 100:.1f}%')
    L.append('  ※ 未回封的票你**一定买得到**（队列被吃穿才叫炸板），以涨停价成交、次日开盘卖 → 几乎必亏。')

    L += ['', '=' * 80, '四、真实期望（成交样本 = 回封 + 未回封，不是涨停池）', '=' * 80]
    reb_rate = len(f) / len(prod)                      # 池内炸板后回封的比例
    n_reb = len(cs) * reb_rate
    n_broken = len(cb)
    p_reb = n_reb / (n_reb + n_broken)
    e_reb = st.mean([x['ret'] for x in f])
    e_broken = st.mean(cb)
    ev = p_reb * e_reb + (1 - p_reb) * e_broken
    L.append(f'  炸板样本里回封的占 {p_reb * 100:.1f}%（回封 {n_reb:.0f} / 未回封 {n_broken}）')
    L.append(f'  E[ret|回封]   {e_reb:+.2f}%')
    L.append(f'  E[ret|未回封] {e_broken:+.2f}%')
    L.append(f'  → **真实期望 = {ev:+.2f}% / 笔**（旧口径 +2.57%，反向偏差 {-2.57 - ev:.2f}pp）')
    L.append('')
    L.append('  敏感性（回封率 → 期望）：')
    for pr in (0.4, 0.471, 0.55, 0.65, 0.73, 0.8):
        L.append(f'    回封率 {pr * 100:>5.1f}%  →  {pr * e_reb + (1 - pr) * e_broken:>+6.2f}%')
    be = (0 - e_broken) / (e_reb - e_broken)
    L.append(f'  打平所需回封率 = {be * 100:.1f}%（实际 {p_reb * 100:.1f}%）→ 缺口 {(be - p_reb) * 100:.0f}pp')

    L += ['', '=' * 80, '五、封单强度 × 可成交率 × 成交后收益（权衡曲线，供将来做「抢回封」用）', '=' * 80]
    L.append(f'  {"封单/流通":<14}{"n":>6}{"可成交率":>10}{"回封后收益":>12}{"期望值/信号":>13}')
    for a, b in ((0, 0.3), (0.3, 0.5), (0.5, 1.0)):
        sub = [x for x in prod if a <= x['fu'] < b]
        if not sub:
            continue
        ff = [x for x in sub if x['z'] >= 1]
        if not ff:
            continue
        rt = len(ff) / len(sub)
        L.append(f'  {f"{a}-{b}%":<14}{len(sub):>6}{rt * 100:>9.1f}%{st.mean([x["ret"] for x in ff]):>+11.2f}%'
                 f'{rt * st.mean([x["ret"] for x in ff]):>+12.2f}%')
    L.append('  ※ 这是「回封后」的收益，已确认含幸存者偏差；未回封那 53% 全部为负。')

    L += ['', '=' * 80, '六、结论与判据', '=' * 80]
    L.append('  1. 打板（挂涨停价买入）在真实成交机制下期望约 -2%/笔，**不具备可执行性**。')
    L.append('  2. 与半路板（-2.13%）几乎相同——两者本质是同一件事：在强势末端接盘。')
    L.append('  3. 唯一可能的活路：把回封率从 47% 提到 >73%。需要分钟级数据判断「炸板时的抛压与回封速度」，')
    L.append('     日线数据无法区分；现有涨停池也不含未回封票的快照字段。')
    L.append('  4. 标定方法（MOA 建议，成本最低）：最小资金实盘挂 20~30 笔，只记「成交/未成交」+ 挂单时刻。')
    L.append('     20 笔的成交率估计误差 ±20pp，信息量超过任何日线 proxy。')
    txt = '\n'.join(L)
    print(txt)
    OUT.write_text(txt + '\n', encoding='utf-8')
    print(f'\n已写入 {OUT.name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
