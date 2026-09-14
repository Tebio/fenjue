"""#87 转债溢价率因子：溢价率分档的次日收益结构（纯日线，今晚可测）
premium = 债价 / (正股价/转股价×100) - 1；转股价用最新值近似（下修历史未逐日跟踪=口径注记）
事件：每日全转债截面，按溢价率分档 → 次日 open→close / close→close
"""
import json, sys
from pathlib import Path
from collections import defaultdict

ROOT = Path('/opt/data/fenjue')
CB = ROOT / 'data/cb_kcache'
KC = ROOT / 'data/big_kcache'
sys.path.insert(0, '/opt/data/python-libs')
import akshare as ak

df = ak.bond_zh_cov()
info = {}
for _, r in df.iterrows():
    try:
        info[str(r['债券代码']).zfill(6)] = (str(r['正股代码']).zfill(6), float(r['转股价']))
    except Exception:
        pass

G = defaultdict(list)   # 档 -> [(r_next_oc, stock_pct_prev)]
for cb in CB.glob('*.json'):
    bond = cb.stem
    if bond not in info: continue
    stock, cvp = info[bond]
    sp = KC / f'{stock}.json'
    if not sp.exists() or cvp <= 0: continue
    bks = json.load(open(cb))
    sks = {k['date']: k for k in json.load(open(sp))}
    for i in range(1, len(bks) - 1):
        d = bks[i]['date']
        st = sks.get(d)
        if not st or st['close'] <= 0: continue
        conv_val = st['close'] / cvp * 100
        if conv_val <= 0: continue
        prem = bks[i]['close'] / conv_val - 1
        r_next = bks[i+1]['close'] / bks[i+1]['open'] - 1 if bks[i+1]['open'] > 0 else None  # 修正锚点:次日开盘买(昨收盘信息)
        if r_next is None: continue
        # 条件：正股前日涨幅（联动环境的代理）
        st_prev = sks.get(bks[i-1]['date'])
        spct = (st['close'] / st_prev['close'] - 1) if st_prev else 0
        band = ('负溢价(<0%)' if prem < 0 else '低(0-10%)' if prem < 0.10 else
                '中(10-30%)' if prem < 0.30 else '高(≥30%)')
        G[band].append(r_next - 0.001)

print(f'{"溢价率档":14s}{"n":>8s}{"次日胜率":>8s}{"次日均收":>9s}')
for band in ('负溢价(<0%)', '低(0-10%)', '中(10-30%)', '高(≥30%)'):
    v = G.get(band, [])
    if not v: continue
    n = len(v)
    print(f'{band:14s}{n:>8d}{sum(1 for r in v if r>0)/n*100:>7.1f}%{sum(v)/n*100:>+8.3f}%')

# 交叉：正股前日大涨(≥5%)时的溢价率分档（联动日的真考场）
G2 = defaultdict(list)
for cb in CB.glob('*.json'):
    bond = cb.stem
    if bond not in info: continue
    stock, cvp = info[bond]
    sp = KC / f'{stock}.json'
    if not sp.exists() or cvp <= 0: continue
    bks = json.load(open(cb))
    sks = {k['date']: k for k in json.load(open(sp))}
    for i in range(1, len(bks) - 1):
        d = bks[i]['date']
        st = sks.get(d)
        st_prev = sks.get(bks[i-1]['date'])
        if not st or not st_prev or st_prev['close'] <= 0: continue
        if st['close'] / st_prev['close'] - 1 < 0.05: continue  # 只看正股大涨日
        conv_val = st['close'] / cvp * 100
        if conv_val <= 0: continue
        prem = bks[i]['close'] / conv_val - 1
        r_next = bks[i+1]['close'] / bks[i+1]['open'] - 1 if bks[i+1]['open'] > 0 else None  # 修正锚点:次日开盘买(昨收盘信息)
        if r_next is None: continue
        band = ('负/低(<10%)' if prem < 0.10 else '中(10-30%)' if prem < 0.30 else '高(≥30%)')
        G2[band].append(r_next - 0.001)
print('\n正股前日涨≥5%的次日转债（联动日）:')
for band in ('负/低(<10%)', '中(10-30%)', '高(≥30%)'):
    v = G2.get(band, [])
    if not v: continue
    n = len(v)
    print(f'{band:14s}{n:>8d}{sum(1 for r in v if r>0)/n*100:>7.1f}%{sum(v)/n*100:>+8.3f}%')
