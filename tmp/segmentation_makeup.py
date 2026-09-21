"""细分补课：X3（活）与 缺口低T+1（死）按 regime×市值五分位×位置 切片。
X3 规则复刻（97笔全史口径）；T+1=缺口低_避周一信号次日开盘买第三天收盘卖。
每格报 n/胜率/均值——检验「全量判决」在细分后是否成立。
"""
import sys, json, statistics as st
from datetime import date
from collections import defaultdict
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
CLAIMS5 = {'跌停底座': '组合_跌停低_三连阴', '复活门': '反转族_跌停潮50', '摇篮': '妖股摇篮_成簇',
           'TD9输家': '组合_跌停低_TD9买_输家250', 'TD9超跌': '组合_跌停低_TD9买_超跌20'}
GATED = {'跌停底座', 'TD9输家', 'TD9超跌'}
FEE = 0.003
WIN0, WIN1 = '2019-01-01', '2026-09-18'
IDX = json.loads(open('data/index_sh000001.json').read())
IDXCAL = [k['date'] for k in IDX]
streak = {}
s = 0
for k in IDX:
    s = s + 1 if regime.get(k['date']) == '恐慌期' else 0
    streak[k['date']] = s

def cap_q(code, dt):
    cap = lp.cap_at_date(lp._XCAP, code, dt) if lp._XCAP else None
    if not cap:
        return '?'
    # 全市场当日分位（近似用固定阈值：小<50亿 中50-150 大>150）
    return '小' if cap < 50 else ('中' if cap < 150 else '大')

def wd(ds):
    return date(int(ds[:4]), int(ds[5:7]), int(ds[8:10])).weekday()

# ── X3 交易切片 ──
raw = []
for cname, dn in CLAIMS5.items():
    det = lp.REGISTRY[dn]
    for code, d in stocks.items():
        n = d['n']
        c, h = d['c'], d['h']
        for i in range(lp.START, n - 1):
            dt = d['date'][i]
            if dt < WIN0 or dt > WIN1 or lp._epx(d, i) <= 0:
                continue
            try:
                if not det(d, i):
                    continue
            except Exception:
                continue
            hi60 = max(h[max(0, i - 60):i]) if i >= 1 else 0
            raw.append({'dt': dt, 'code': code, 'i': i, 'claim': cname,
                        'rg': regime.get(dt, '?'),
                        'pos60': c[i - 1] / hi60 - 1 if hi60 > 0 else 0})
cl = {}
for r in raw:
    if r['claim'] in GATED:
        cl.setdefault(r['dt'], set()).add(r['code'])
day_cl = {}
for r in raw:
    day_cl[r['dt']] = day_cl.get(r['dt'], 0) + 1
LDC = lp._XLDC
big = lambda dt: day_cl.get(dt, 0) >= 8 or LDC.get(dt, 0) >= 30
kept, seen = [], set()
for r in sorted(raw, key=lambda x: (x['dt'], -x['pos60'])):
    if r['claim'] in GATED and len(cl.get(r['dt'], set())) < 5 and r['rg'] != '恐慌期':
        continue
    key = (r['dt'], r['code'])
    if key not in seen:
        seen.add(key)
        kept.append(r)

x3_trades = []
day_cnt = defaultdict(int)
for r in sorted(kept, key=lambda x: (x['dt'], -x['pos60'])):
    d = stocks[r['code']]
    ei = r['i'] + 1
    if ei >= d['n']:
        continue
    entry_d = d['date'][ei]
    if entry_d > WIN1:
        continue
    day_cnt[entry_d] += 0  # 日限3按日模拟
for r in kept:
    pass
# 简化：X3 取候选规则同 #125/127（只恐慌期+第2天+大簇+非周一+浅跌日限3）
entered_per_day = defaultdict(int)
for r in sorted(kept, key=lambda x: (x['dt'], -x['pos60'])):
    d = stocks[r['code']]
    ei = r['i'] + 1
    if ei >= d['n']:
        continue
    entry_d = d['date'][ei]
    if entry_d > WIN1 or r['rg'] != '恐慌期':
        continue
    if streak.get(r['dt'], 0) < 2 or not big(r['dt']) or wd(entry_d) == 0:
        continue
    if entered_per_day[entry_d] >= 3:
        continue
    entered_per_day[entry_d] += 1
    xi = min(ei + 5, d['n'] - 1)
    ret = d['c'][xi] / lp._epx(d, r['i']) - 1 - FEE
    x3_trades.append({'ret': ret, 'rg': r['rg'], 'cap': cap_q(r['code'], r['dt']),
                      'pos60': r['pos60']})

print(f'== X3 细分（n={len(x3_trades)}）==')
cells = defaultdict(list)
for t in x3_trades:
    cells[('市值', t['cap'])].append(t['ret'])
    cells[('位置', '深' if t['pos60'] < -0.3 else ('中' if t['pos60'] < -0.1 else '浅'))].append(t['ret'])
for (dim, k), v in sorted(cells.items()):
    w = sum(1 for x in v if x > 0)
    print(f'  {dim}={k}: n={len(v)} 胜率{100*w/len(v):.0f}% 均{100*st.mean(v):+.2f}%')

# ── 缺口低 T+1 细分（死策略验尸：有没有哪格是活的）──
det = lp.REGISTRY['组合_缺口低开_低位阳线_避周一']
t1_cells = defaultdict(list)
for code, d in stocks.items():
    n = d['n']
    c, h = d['c'], d['h']
    for i in range(lp.START, n - 2):
        dt = d['date'][i]
        if dt < WIN0 or dt > WIN1 or lp._epx(d, i) <= 0:
            continue
        try:
            if not det(d, i):
                continue
        except Exception:
            continue
        hi60 = max(h[max(0, i - 60):i]) if i >= 1 else 0
        pos60 = c[i - 1] / hi60 - 1 if hi60 > 0 else 0
        ret = c[i + 2] / lp._epx(d, i) - 1 - FEE
        rg = regime.get(dt, '?')
        t1_cells[('regime', rg)].append(ret)
        t1_cells[('市值', cap_q(code, dt))].append(ret)
        t1_cells[('位置', '深' if pos60 < -0.3 else ('中' if pos60 < -0.1 else '浅'))].append(ret)
        t1_cells[('regime×位置', f"{rg}|{'深' if pos60 < -0.3 else '浅'}")].append(ret)

print(f'\n== 缺口低 T+1 细分验尸 ==')
for (dim, k), v in sorted(t1_cells.items()):
    if len(v) >= 200:
        w = sum(1 for x in v if x > 0)
        print(f'  {dim}={k}: n={len(v)} 胜率{100*w/len(v):.0f}% 均{100*st.mean(v):+.3f}%')