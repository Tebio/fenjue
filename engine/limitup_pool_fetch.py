#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
抓取东方财富涨停池（主板），字段对齐 data/limit_up_mainboard_20250908_20260922.csv。
用法:
    python engine/limitup_pool_fetch.py --beg 2026-09-23 --end 2026-10-19 \
        --out data/limit_up_mainboard_20260923_20261019.csv
次日涨幅用本地前复权日线 (law_pipeline.load_universe) 计算，分子分母同一复权口径。
"""
import argparse
import csv
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, '/opt/data/fenjue/engine')
sys.path.insert(0, '/opt/data/python-libs')

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
URL = ('https://push2ex.eastmoney.com/getTopicZTPool?ut=7eea3edcaed734bea9cbfc24409ed989'
       '&dpt=wz.ztzt&Pageindex=0&pagesize=300&sort=fbt%3Aasc&date={date}')

FIELDS = ['日期', '代码', '名称', '首次封板时间', '最后封板时间', '炸板次数', '封单额(元)',
          '连板数', '涨停价', '涨跌幅(%)', '换手率(%)', '成交额(亿元)', '所属行业', '封板时段',
          '次日开盘涨幅(%)', '次日收盘涨幅(%)', '次日最高涨幅(%)', '流通市值(亿元)',
          '封单额/流通市值(%)', '涨停原因(同花顺)']


def fmt_hms(v):
    """fbt/lbt 为 HHMMSS 整数 -> HH:MM:SS"""
    if v in (None, '', 0):
        return ''
    s = f'{int(v):06d}'
    return f'{s[:2]}:{s[2:4]}:{s[4:6]}'


def time_bucket(hms):
    """按首次封板时间分桶（任务指定的 5 桶口径）"""
    if not hms:
        return ''
    if hms <= '09:35:00':
        return '<=09:35'
    if hms < '10:00:00':
        return '09:35-10:00'
    if hms <= '11:30:00':
        return '10:00-11:30'
    if hms <= '14:00:00':
        return '13:00-14:00'
    return '>14:00'


def fetch_pool(date8, retries=3):
    """date8: YYYYMMDD -> list of pool items (空表示非交易日或无数据)"""
    req = urllib.request.Request(URL.format(date=date8), headers=UA)
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read().decode('utf-8'))
            data = d.get('data') or {}
            return data.get('pool') or []
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(1 + i)


def load_universe():
    import law_pipeline as lp
    return lp.load_universe()


def next_day_returns(U, code, date_str):
    """返回 (次日开盘涨幅%, 次日收盘涨幅%, 次日最高涨幅%)，基于涨停日收盘价。
    全部用 U 内前复权价格。超出数据范围返回 ('','','')。"""
    if code not in U:
        return '', '', ''
    a = U[code]
    dates = [str(x)[:10] for x in a['date']]
    try:
        i = dates.index(date_str)
    except ValueError:
        return '', '', ''
    if i + 1 >= len(dates):
        return '', '', ''
    c0 = float(a['c'][i])
    if c0 <= 0:
        return '', '', ''
    o1 = float(a['o'][i + 1])
    c1 = float(a['c'][i + 1])
    h1 = float(a['h'][i + 1])
    return (round((o1 / c0 - 1) * 100, 2),
            round((c1 / c0 - 1) * 100, 2),
            round((h1 / c0 - 1) * 100, 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--beg', required=True, help='YYYY-MM-DD')
    ap.add_argument('--end', required=True, help='YYYY-MM-DD')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    beg = datetime.strptime(args.beg, '%Y-%m-%d')
    end = datetime.strptime(args.end, '%Y-%m-%d')

    print('加载本地日线 universe ...', flush=True)
    U = load_universe()
    print(f'  universe: {len(U)} 只', flush=True)

    rows = []
    failed = []
    empty = []
    day_counts = {}

    d = beg
    while d <= end:
        ds = d.strftime('%Y-%m-%d')
        d8 = d.strftime('%Y%m%d')
        try:
            pool = fetch_pool(d8)
        except Exception as e:
            failed.append((ds, repr(e)))
            print(f'[FAIL] {ds}: {e!r}', flush=True)
            d += timedelta(days=1)
            time.sleep(0.3)
            continue
        if not pool:
            empty.append(ds)
            d += timedelta(days=1)
            time.sleep(0.3)
            continue
        n = 0
        for it in pool:
            code = str(it.get('c', ''))
            # 主板过滤：60/00 开头，排除 68(科创)/30(创业)/8,4,9(北交)
            if not (code.startswith('60') or code.startswith('00')):
                continue
            fbt = fmt_hms(it.get('fbt'))
            lbt = fmt_hms(it.get('lbt'))
            p = it.get('p')
            zt_price = round(p / 1000, 2) if p else ''
            fund = it.get('fund') or 0
            ltsz = it.get('ltsz') or 0
            amt = it.get('amount') or 0
            o_pct, c_pct, h_pct = next_day_returns(U, code, ds)
            rows.append({
                '日期': ds,
                '代码': code,
                '名称': it.get('n', ''),
                '首次封板时间': fbt,
                '最后封板时间': lbt,
                '炸板次数': it.get('zbc', 0),
                '封单额(元)': fund,
                '连板数': it.get('lbc', 1),
                '涨停价': zt_price,
                '涨跌幅(%)': round(it.get('zdp', 0), 2),
                '换手率(%)': round(it.get('hs', 0), 2),
                '成交额(亿元)': round(amt / 1e8, 2) if amt else '',
                '所属行业': it.get('hybk', ''),
                '封板时段': time_bucket(fbt),
                '次日开盘涨幅(%)': o_pct,
                '次日收盘涨幅(%)': c_pct,
                '次日最高涨幅(%)': h_pct,
                '流通市值(亿元)': round(ltsz / 1e8, 2) if ltsz else '',
                '封单额/流通市值(%)': round(fund / ltsz * 100, 3) if ltsz else '',
                '涨停原因(同花顺)': '',
            })
            n += 1
        day_counts[ds] = n
        print(f'[OK] {ds}: {n} 只 (pool raw {len(pool)})', flush=True)
        d += timedelta(days=1)
        time.sleep(0.3)

    with open(args.out, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    print(f'\n写出 {args.out}: {len(rows)} 行, 覆盖 {len(day_counts)} 个交易日', flush=True)
    print('每日涨停数:', json.dumps(day_counts, ensure_ascii=False), flush=True)
    if empty:
        print(f'空池日期(非交易日或无数据): {empty}', flush=True)
    if failed:
        print(f'失败日期: {failed}', flush=True)


if __name__ == '__main__':
    main()
