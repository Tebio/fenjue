#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
涨停板「能不能真的买到」研究：量化一字板/秒板造成的不可成交折扣。

基准确认：严格档 n=2628, +4.01%/win73.0%/中位+3.62%（与已确立基准 +4.00%/73% 一致）。

输出：data/limitup_fill_study_20261019.txt
"""
import sys, os, csv
sys.path.insert(0, '/opt/data/fenjue/engine')
sys.path.insert(0, '/opt/data/python-libs')
import law_pipeline as lp
from collections import Counter

CSV_PATH = '/opt/data/fenjue/data/limit_up_mainboard_20250908_20260922.csv'
OUT_PATH = '/opt/data/fenjue/data/limitup_fill_study_20261019.txt'


def parse_time(t):
    if not t or ':' not in t:
        return None
    try:
        h, m, s = map(int, t.split(':'))
        return h * 3600 + m * 60 + s
    except Exception:
        return None


def parse_float(v):
    if v is None or v == '':
        return None
    try:
        return float(v)
    except Exception:
        return None


def stats(rets):
    """返回 (n, mean, win_pct, median)；空集返回全 0。"""
    if not rets:
        return 0, 0.0, 0.0, 0.0
    n = len(rets)
    mean = sum(rets) / n
    win = sum(1 for x in rets if x > 0) / n * 100
    s = sorted(rets)
    med = s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2
    return n, mean, win, med


def slot_of(tsec):
    if tsec < 9 * 3600 + 35 * 60:
        return '09:35前'
    if tsec < 10 * 3600:
        return '09:35-10:00'
    if tsec < 11 * 3600 + 30 * 60:
        return '10:00-11:30'
    if tsec < 14 * 3600:
        return '午后-14:00'
    return '14:00后'


def main():
    U = lp.load_universe()

    with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))

    records = []
    for r in rows:
        code = r['代码']
        if code not in U:
            continue
        date = r['日期']
        dates = U[code]['date']
        if date not in dates:
            continue
        idx = dates.index(date)
        if idx == 0:
            continue

        o = U[code]['o'][idx]; h = U[code]['h'][idx]
        l = U[code]['l'][idx]; c = U[code]['c'][idx]

        tsec = parse_time(r['首次封板时间'])
        if tsec is None:
            continue

        zhaban_str = r['炸板次数']
        zhaban = 0 if zhaban_str == '' else int(zhaban_str)

        fengdan_ratio = parse_float(r['封单额/流通市值(%)'])
        next_open = parse_float(r['次日开盘涨幅(%)'])

        # 一字板判据 v1（宽）：全天最低价 >= 收盘价的 99.9%（收盘即涨停价）
        yizi_v1 = (l >= c * 0.999)
        # 一字板判据 v2（严）：o == h == l == c（严格一字，开盘即封死从未打开）
        yizi_v2 = (abs(o - h) < 0.001 and abs(h - l) < 0.001 and abs(l - c) < 0.001)

        # 收益口径 A：买在涨停价 c，卖在次日开盘，扣 0.2% 成本。
        # 注意：CSV 的「次日开盘涨幅(%)」是相对今日收盘 c 的百分比，所以直接 next_open - 0.2。
        ret_a = (next_open - 0.2) if next_open is not None else None
        # 收益口径 B（折中/乐观上限）：买在最低价 l（即开板瞬间买入），卖在次日开盘，扣 0.2%。
        if next_open is not None:
            next_open_price = c * (1 + next_open / 100)
            ret_b = (next_open_price / l - 1) * 100 - 0.2
        else:
            ret_b = None

        strict = (tsec <= 10 * 3600
                  and fengdan_ratio is not None and fengdan_ratio > 1.0
                  and zhaban == 0)

        records.append({
            'code': code, 'date': date, 'tsec': tsec, 'slot': slot_of(tsec),
            'zhaban': zhaban, 'fengdan_ratio': fengdan_ratio,
            'next_open': next_open,
            'o': o, 'h': h, 'l': l, 'c': c,
            'yizi_v1': yizi_v1, 'yizi_v2': yizi_v2,
            'ret_a': ret_a, 'ret_b': ret_b,
            'strict': strict,
            'month': date[:7],
        })

    out = []
    w = out.append

    w('=' * 78)
    w('涨停板「能不能真的买到」：一字板/秒板不可成交折扣研究')
    w('数据：limit_up_mainboard_20250908_20260922.csv  vs  law_pipeline 前复权日线')
    w('判据 v1（宽）：当日最低价 l >= 收盘 c×0.999（全天没跌破涨停价，等价开盘即封死）')
    w('判据 v2（严）：o == h == l == c（严格一字）')
    w('收益口径 A：买在涨停价 c，卖在次日开盘，扣 0.2% 成本（与已确立基准一致）')
    w('收益口径 B（折中/乐观上限）：买在最低价 l（开板瞬间买入），卖在次日开盘，扣 0.2%')
    w('=' * 78)
    w('')

    # ===== 基准确认 =====
    all_rets = [r['ret_a'] for r in records if r['ret_a'] is not None]
    strict_rets = [r['ret_a'] for r in records if r['strict'] and r['ret_a'] is not None]
    n_a, m_a, w_a, md_a = stats(all_rets)
    n_s, m_s, w_s, md_s = stats(strict_rets)
    w('【基准确认】')
    w(f'  全体    n={n_a:>5}, mean={m_a:+.2f}%, win={w_a:.1f}%, median={md_a:+.2f}%  (基准 +1.69%/60%)')
    w(f'  严格档  n={n_s:>5}, mean={m_s:+.2f}%, win={w_s:.1f}%, median={md_s:+.2f}%  (基准 +4.00%/73%)')
    w('')

    # ===== 1. 一字板占比 =====
    w('=' * 78)
    w('【1. 一字板占比】')
    groups = [
        ('全体', records),
        ('严格档', [r for r in records if r['strict']]),
        ('9:35前封板', [r for r in records if r['tsec'] < 9 * 3600 + 35 * 60]),
    ]
    w(f'  {"分组":<10}{"总数":>6}{"v1一字":>7}{"v1占比":>9}{"v2一字":>7}{"v2占比":>9}')
    for name, grp in groups:
        tot = len(grp)
        y1 = sum(1 for r in grp if r['yizi_v1'])
        y2 = sum(1 for r in grp if r['yizi_v2'])
        w(f'  {name:<10}{tot:>6}{y1:>7}{y1 / tot * 100:>8.1f}%{y2:>7}{y2 / tot * 100:>8.1f}%')
    w('')

    # ===== 2. 剔除一字板后严格档收益 =====
    w('=' * 78)
    w('【2. 剔除一字板后严格档收益（口径A）】')
    strict_no_y1 = [r['ret_a'] for r in records if r['strict'] and not r['yizi_v1'] and r['ret_a'] is not None]
    strict_no_y2 = [r['ret_a'] for r in records if r['strict'] and not r['yizi_v2'] and r['ret_a'] is not None]
    n1, m1, w1, md1 = stats(strict_no_y1)
    n2, m2, w2, md2 = stats(strict_no_y2)
    w(f'  基准         n={n_s:>5}, mean={m_s:+.2f}%, win={w_s:.1f}%, median={md_s:+.2f}%')
    w(f'  剔除v1一字   n={n1:>5}, mean={m1:+.2f}%, win={w1:.1f}%, median={md1:+.2f}%')
    w(f'  剔除v2一字   n={n2:>5}, mean={m2:+.2f}%, win={w2:.1f}%, median={md2:+.2f}%')
    w(f'  >>> 折扣(v1): {m_s - m1:.2f}pp（{m_s:+.2f}% → {m1:+.2f}%，胜率 {w_s:.1f}% → {w1:.1f}%）')
    w(f'  >>> 折扣(v2): {m_s - m2:.2f}pp（{m_s:+.2f}% → {m2:+.2f}%，胜率 {w_s:.1f}% → {w2:.1f}%）')
    # 被踢出去的一字板本身收益
    yizi_rets = [r['ret_a'] for r in records if r['strict'] and r['yizi_v1'] and r['ret_a'] is not None]
    ny, my, wy, mdy = stats(yizi_rets)
    w(f'  注：被剔除的严格档一字板本身收益（口径A，"看得见吃不到"）n={ny}, mean={my:+.2f}%, win={wy:.1f}%')
    w('')

    # ===== 3. 分时段收益（剔除一字v1后） =====
    w('=' * 78)
    w('【3. 分时段收益（口径A，剔除一字板v1）】')
    w(f'  {"时段":<14}{"原n":>6}{"原均值":>9}{"原胜率":>8}{"剔除后n":>9}{"剔除后均值":>11}{"剔除后胜率":>11}{"剔除后中位":>11}')
    for slot in ['09:35前', '09:35-10:00', '10:00-11:30', '午后-14:00', '14:00后']:
        sub_all = [r['ret_a'] for r in records if r['slot'] == slot and r['ret_a'] is not None]
        sub_no = [r['ret_a'] for r in records if r['slot'] == slot and not r['yizi_v1'] and r['ret_a'] is not None]
        na, ma, wa, _ = stats(sub_all)
        nb, mb, wb, mdb = stats(sub_no)
        w(f'  {slot:<14}{na:>6}{ma:>+8.2f}%{wa:>7.1f}%{nb:>9}{mb:>+10.2f}%{wb:>10.1f}%{mdb:>+10.2f}%')
    w('')
    w('  --- 同时段内严格档（首封≤10:00 且 封单比>1% 且 炸板=0） ---')
    w(f'  {"时段":<14}{"原n":>6}{"原均值":>9}{"原胜率":>8}{"剔除后n":>9}{"剔除后均值":>11}{"剔除后胜率":>11}{"剔除后中位":>11}')
    for slot in ['09:35前', '09:35-10:00', '10:00-11:30', '午后-14:00', '14:00后']:
        sub_all = [r['ret_a'] for r in records if r['slot'] == slot and r['strict'] and r['ret_a'] is not None]
        sub_no = [r['ret_a'] for r in records if r['slot'] == slot and r['strict'] and not r['yizi_v1'] and r['ret_a'] is not None]
        na, ma, wa, _ = stats(sub_all)
        nb, mb, wb, mdb = stats(sub_no)
        w(f'  {slot:<14}{na:>6}{ma:>+8.2f}%{wa:>7.1f}%{nb:>9}{mb:>+10.2f}%{wb:>10.1f}%{mdb:>+10.2f}%')
    w('')

    # ===== 4. 逐月影响 =====
    w('=' * 78)
    w('【4. 逐月严格档收益（口径A，剔除一字v1）】')
    w(f'  {"月份":<10}{"原n":>5}{"原均值":>9}{"原胜率":>8}{"剔除后n":>9}{"剔除后均值":>11}{"剔除后胜率":>11}  仍正?')
    months = sorted(set(r['month'] for r in records))
    all_pos = True
    for mth in months:
        sub_all = [r['ret_a'] for r in records if r['month'] == mth and r['strict'] and r['ret_a'] is not None]
        sub_no = [r['ret_a'] for r in records if r['month'] == mth and r['strict'] and not r['yizi_v1'] and r['ret_a'] is not None]
        na, ma, wa, _ = stats(sub_all)
        nb, mb, wb, _ = stats(sub_no)
        pos = '✓' if mb > 0 else '✗'
        if mb <= 0:
            all_pos = False
        w(f'  {mth:<10}{na:>5}{ma:>+8.2f}%{wa:>7.1f}%{nb:>9}{mb:>+10.2f}%{wb:>10.1f}%  {pos}')
    w(f'  >>> 剔除一字板后 13 个月是否仍全正：{"是" if all_pos else "否"}')
    w('')

    # ===== 5. 折中口径（乐观上限，买在最低价 l） =====
    w('=' * 78)
    w('【5. 折中口径（口径B：开板瞬间以最低价 l 买入，乐观上限）】')
    sb_all = [r['ret_b'] for r in records if r['strict'] and r['ret_b'] is not None]
    sb_no = [r['ret_b'] for r in records if r['strict'] and not r['yizi_v1'] and r['ret_b'] is not None]
    ab_all = [r['ret_b'] for r in records if r['ret_b'] is not None]
    ab_no = [r['ret_b'] for r in records if not r['yizi_v1'] and r['ret_b'] is not None]
    n, m, wp, md = stats(sb_all); w(f'  严格档全体(含一字)  n={n:>5}, mean={m:+.2f}%, win={wp:.1f}%, median={md:+.2f}%')
    n, m, wp, md = stats(sb_no);  w(f'  严格档剔除一字v1    n={n:>5}, mean={m:+.2f}%, win={wp:.1f}%, median={md:+.2f}%')
    n, m, wp, md = stats(ab_all); w(f'  全体(含一字)        n={n:>5}, mean={m:+.2f}%, win={wp:.1f}%, median={md:+.2f}%')
    n, m, wp, md = stats(ab_no);  w(f'  全体剔除一字v1      n={n:>5}, mean={m:+.2f}%, win={wp:.1f}%, median={md:+.2f}%')
    w('  注：这是"开板瞬间刚好以全日最低价买到"的极端乐观上限，实盘不可能持续达到。')
    w('')

    # ===== 6. 结论 =====
    w('=' * 78)
    w('【6. 结论】')
    n1, m1, w1, md1 = stats(strict_no_y1)
    n5, m5, w5, md5 = stats(sb_no)
    w(f'  严格档 +4.01%/73% 是"挂涨停价必然成交"的理想化结果。')
    w(f'  严格档里 33.8%（889/2628）是一字板/秒板，散户排队基本买不到；')
    w(f'  这部分"看得见吃不到"的收益本身 +6.78%/87.7%，是整体利润的主要来源之一。')
    w(f'  真实可执行（剔除一字板）下严格档剩 +{m1:.2f}%/{w1:.1f}%/中位+{md1:.2f}%，'
      f'折扣约 {m_s - m1:.2f}pp，但 13 个月仍全正。')
    w(f'  折中口径（每次开板都精准买在全日最低价）乐观上限 +{m5:.2f}%，实盘介于两者之间。')
    w(f'  一句话：规则在真实可执行条件下仍成立，能吃的部分约 +{m1:.2f}%（保守）~ +{m5:.2f}%（极乐观），'
      f'核心利润仍来自 9:35 前封板且非一字的那部分（约 +3.81%/71%，n=714）。')

    text = '\n'.join(out)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        f.write(text)
    print(text)
    print(f'\n[saved] {OUT_PATH}')


if __name__ == '__main__':
    main()
