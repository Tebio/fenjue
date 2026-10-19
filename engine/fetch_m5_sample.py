#!/usr/bin/env python3
"""engine/fetch_m5_sample.py — 5分钟线抽样拉取（2026-10-19）

目的：把「涨停价上能不能买到」从假设改成实测。
样本：主板随机 200 只（固定 seed），区间 2025-01-01 ~ 2026-10-16。
输出：data/m5/{code}.json = [[datetime, open, high, low, close, volume, amount], ...]
可续跑：已存在的文件跳过。
纪律：baostock 单进程（禁双进程，见 AGENTS）。不碰现有 data/ 目录下任何文件。
"""
import json
import os
import random
import sys
import time
from pathlib import Path

for _k in list(os.environ):
    if 'proxy' in _k.lower():
        os.environ.pop(_k, None)
sys.path.insert(0, '/opt/data/python-libs')

ROOT = Path('/opt/data/fenjue')
KC = ROOT / 'data/big_kcache'
OUT = ROOT / 'data/m5'
OUT.mkdir(parents=True, exist_ok=True)

START, END = '2025-01-01', '2026-10-16'
N_SAMPLE = 200
SEED = 20261019
MB = ('600', '601', '603', '605', '000', '001', '002', '003')

codes = sorted(p.stem for p in KC.glob('*.json') if p.stem[:3] in MB)
random.Random(SEED).shuffle(codes)
sample = sorted(codes[:N_SAMPLE])
print(f'主板 {len(codes)} 只，随机抽 {len(sample)} 只（seed={SEED}）', flush=True)

todo = [c for c in sample if not (OUT / f'{c}.json').exists()]
print(f'已完成 {len(sample) - len(todo)}，待拉 {len(todo)}', flush=True)

import baostock as bs
lg = bs.login()
if lg.error_code != '0':
    print('LOGIN FAIL', lg.error_msg, flush=True)
    sys.exit(1)

ok = fail = 0
t_start = time.time()
for n, code in enumerate(todo, 1):
    sym = ('sh.' if code.startswith('6') else 'sz.') + code
    rows = []
    try:
        rs = bs.query_history_k_data_plus(
            sym, 'date,time,open,high,low,close,volume,amount',
            start_date=START, end_date=END, frequency='5', adjustflag='3')
        if rs.error_code != '0':
            raise RuntimeError(rs.error_msg)
        while rs.next():
            rows.append(rs.get_row_data())
    except Exception as e:
        fail += 1
        print(f'[{n}/{len(todo)}] {code} FAIL {e}', flush=True)
        continue
    clean = [[r[1], float(r[2] or 0), float(r[3] or 0), float(r[4] or 0),
              float(r[5] or 0), float(r[6] or 0), float(r[7] or 0)] for r in rows]
    (OUT / f'{code}.json').write_text(json.dumps(clean))
    ok += 1
    if n % 10 == 0 or n == len(todo):
        el = time.time() - t_start
        eta = el / n * (len(todo) - n) / 60
        print(f'[{n}/{len(todo)}] {code} {len(clean)}根  '
              f'elapsed {el/60:.1f}min  eta {eta:.0f}min', flush=True)

bs.logout()
print(f'DONE ok={ok} fail={fail}', flush=True)
