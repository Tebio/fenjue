#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""engine/limitup_history_extend.py — 历史涨停池回补 + 低换手打板规则跨周期重验

数据源（全部本地落盘，不回测未来函数）：
  涨停池   : data/hithink/<date>/limit_up_pool.json   (HiThink 日更落盘，2020-08 起)
  行情     : data/big_kcache_unadj/<code>.json        (不复权日线，含 volume/amount)
  流通市值 : data/cap_hist/<code>.json                ([date, raw_close, 流通市值亿] 日频)

字段推导：
  换手率%      = 当日成交量 / (流通市值亿*1e8 / 当日不复权收盘价) * 100
  封单额/流通% = seal_money / (流通市值亿*1e8) * 100
  次日开盘涨幅% = (T+1 不复权开盘 / T 不复权收盘 - 1) * 100   （与生产 CSV 的前复权口径差异<0.1%，已抽样核对）

规则（与生产一致）：主板(60/000/001/002/003/605) + 非ST + 换手率<4% + 封单/流通<1%
  + 首次封板<=10:00 + 连板数<=2；T 日封板价(=收盘价)买，T+1 开盘卖，双边扣 0.2%。

用法:
  python engine/limitup_history_extend.py --beg 2024-01-01 --end 2025-09-07 \
      --out data/limitup_history_extend_20261019.txt --csv data/limitup_pool_backfill_2024_2025.csv
"""
import argparse
import csv
import json
import sys
from bisect import bisect_left
from pathlib import Path

ROOT = Path('/opt/data/fenjue')
HITHINK = ROOT / 'data/hithink'
KDIR = ROOT / 'data/big_kcache_unadj'
CAPD = ROOT / 'data/cap_hist'

MAIN_PREFIX = ('600', '601', '603', '605', '000', '001', '002', '003')

_kcache, _capcache = {}, {}


def load_k(code):
    if code not in _kcache:
        fp = KDIR / f'{code}.json'
        if not fp.exists():
            _kcache[code] = None
        else:
            rows = json.loads(fp.read_text())
            _kcache[code] = ([r['date'] for r in rows], rows)
    return _kcache[code]


def load_cap(code):
    if code not in _capcache:
        fp = CAPD / f'{code}.json'
        if not fp.exists():
            _capcache[code] = None
        else:
            rows = json.loads(fp.read_text())
            _capcache[code] = ([r[0] for r in rows], rows)
    return _capcache[code]


def k_on(code, date):
    d = load_k(code)
    if not d:
        return None, None
    dates, rows = d
    i = bisect_left(dates, date)
    if i < len(dates) and dates[i] == date:
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        return rows[i], nxt
    return None, None


def cap_on(code, date):
    d = load_cap(code)
    if not d:
        return None
    dates, rows = d
    i = bisect_left(dates, date)
    if i < len(dates) and dates[i] == date:
        return rows[i]
    # 市值允许取最近前一个交易日（停牌等）
    return rows[i - 1] if i > 0 else None


def pool_dates(beg, end):
    return sorted(d for d in (p.name for p in HITHINK.iterdir() if p.is_dir())
                  if d.startswith('20') and beg <= d <= end
                  and (HITHINK / d / 'limit_up_pool.json').exists())


def build_rows(beg, end):
    """回补区间全部主板涨停记录（未过规则），带推导字段。"""
    out, skipped = [], {'no_k': 0, 'no_cap': 0, 'no_next': 0}
    for dt in pool_dates(beg, end):
        items = json.loads((HITHINK / dt / 'limit_up_pool.json').read_text())
        items = (items.get('data') or {}).get('item') or []
        for it in items:
            code = it.get('ticker', '')
            if not code.startswith(MAIN_PREFIX):
                continue
            if it.get('is_st'):
                continue
            kt, kn = k_on(code, dt)
            if not kt:
                skipped['no_k'] += 1
                continue
            cap = cap_on(code, dt)
            if not cap:
                skipped['no_cap'] += 1
                continue
            mcap_y = cap[2]                      # 流通市值（亿）
            float_sh = mcap_y * 1e8 / kt['close'] if kt['close'] else 0
            turnover = kt['volume'] / float_sh * 100 if float_sh else None
            seal = it.get('seal_money') or 0
            seal_ratio = seal / (mcap_y * 1e8) * 100 if mcap_y else None
            if kn and kt['close']:
                next_open = (kn['open'] / kt['close'] - 1) * 100
            else:
                next_open = None
                skipped['no_next'] += 1
            out.append({
                '日期': dt, '代码': code, '名称': it.get('name', ''),
                '首次封板时间': (it.get('limit_up_time') or '') + ':00' if it.get('limit_up_time') else '',
                '连板数': it.get('continue_day_cnt') or 1,
                '封单额(元)': round(seal, 0),
                '换手率(%)': round(turnover, 2) if turnover is not None else '',
                '流通市值(亿元)': round(mcap_y, 2),
                '封单额/流通市值(%)': round(seal_ratio, 3) if seal_ratio is not None else '',
                '次日开盘涨幅(%)': round(next_open, 2) if next_open is not None else '',
            })
    return out, skipped


def rule_pass(r):
    try:
        return (float(r['换手率(%)']) < 4.0
                and float(r['封单额/流通市值(%)']) < 1.0
                and r['首次封板时间'] and r['首次封板时间'] <= '10:00:00'
                and int(r['连板数']) <= 2
                and r['次日开盘涨幅(%)'] != '')
    except (ValueError, TypeError):
        return False


def stats(rows):
    rets = sorted(float(r['次日开盘涨幅(%)']) - 0.2 for r in rows)
    n = len(rets)
    if not n:
        return None
    mean = sum(rets) / n
    win = sum(1 for x in rets if x > 0) / n * 100
    med = rets[n // 2] if n % 2 else (rets[n // 2 - 1] + rets[n // 2]) / 2
    return n, mean, win, med


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--beg', default='2024-01-01')
    ap.add_argument('--end', default='2025-09-07')
    ap.add_argument('--out', default='data/limitup_history_extend_20261019.txt')
    ap.add_argument('--csv', default='data/limitup_pool_backfill_2024_2025.csv')
    a = ap.parse_args()

    dates = pool_dates(a.beg, a.end)
    rows, skipped = build_rows(a.beg, a.end)
    picks = [r for r in rows if rule_pass(r)]

    # 写回补 CSV（全部主板涨停记录，不只过规则的）
    csv_path = ROOT / a.csv
    with csv_path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        w.writeheader()
        w.writerows(rows)

    # 分年统计
    lines = []
    lines.append('=' * 72)
    lines.append('历史涨停池回补 + 低换手打板规则跨周期重验')
    lines.append(f'回补区间: {a.beg} ~ {a.end}  池交易日: {len(dates)}  ({dates[0]} ~ {dates[-1]})')
    lines.append(f'主板非ST涨停记录: {len(rows)}  (缺K线 {skipped["no_k"]}, 缺市值 {skipped["no_cap"]}, 缺次日 {skipped["no_next"]})')
    lines.append(f'过规则记录: {len(picks)}')
    lines.append(f'回补CSV: {a.csv}')
    lines.append('')
    lines.append('规则: 主板 换手<4% 封单/流通<1% 首封<=10:00 连板<=2; T封板价买 T+1开盘卖 扣0.2%')
    lines.append('-' * 72)
    lines.append(f'{"年份":<8}{"n":>6}{"均值%":>9}{"胜率%":>9}{"中位%":>9}')
    by_year = {}
    for r in picks:
        by_year.setdefault(r['日期'][:4], []).append(r)
    for y in sorted(by_year):
        s = stats(by_year[y])
        lines.append(f'{y:<8}{s[0]:>6}{s[1]:>9.2f}{s[2]:>9.1f}{s[3]:>9.2f}')
    s = stats(picks)
    lines.append(f'{"合计":<8}{s[0]:>6}{s[1]:>9.2f}{s[2]:>9.1f}{s[3]:>9.2f}')
    lines.append('-' * 72)

    # 退化版验证：2024 年只看「换手<4%」一个条件（全部主板涨停, 不限首封/封单）
    lines.append('')
    lines.append('退化版验证: 2024 年主板涨停中仅按换手率分层的次日开盘表现(扣0.2%)')
    y24 = [r for r in rows if r['日期'][:4] == '2024' and r['次日开盘涨幅(%)'] != '']
    for lo, hi, tag in [(0, 4, '换手<4%'), (4, 8, '4-8%'), (8, 100, '>=8%')]:
        sub = [r for r in y24 if lo <= float(r['换手率(%)']) < hi]
        if sub:
            s = stats(sub)
            lines.append(f'  {tag:<8} n={s[0]:<5} 均值{s[1]:>7.2f}%  胜率{s[2]:>5.1f}%  中位{s[3]:>6.2f}%')

    # 月明细（看阴跌段是否连续亏损）
    lines.append('')
    lines.append('2024 年逐月明细(过规则):')
    by_m = {}
    for r in picks:
        if r['日期'][:4] == '2024':
            by_m.setdefault(r['日期'][:7], []).append(r)
    for m in sorted(by_m):
        s = stats(by_m[m])
        lines.append(f'  {m}  n={s[0]:<4} 均值{s[1]:>7.2f}%  胜率{s[2]:>5.1f}%')

    report = '\n'.join(lines)
    (ROOT / a.out).write_text(report, encoding='utf-8')
    print(report)


if __name__ == '__main__':
    sys.path.insert(0, '/opt/data/fenjue/engine')
    main()
