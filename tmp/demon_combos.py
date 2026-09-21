import json, sys, statistics as st
sys.path.insert(0, 'engine')
import law_pipeline as lp
from doubler import first_board_events

ROOT = '/opt/data/fenjue'
FEE = 0.0015
stocks = lp.load_universe()
lp.build_xsection(stocks)
capm, ldc = lp._XCAP, lp._XLDC

def pre(d, j):
    c, h, v = d['c'], d['h'], d['v']
    hi60 = max(h[max(0, j - 60):j])
    base5 = [v[k] for k in range(max(0, j - 5), j) if v[k] > 0]
    vr = v[j] / (sum(base5) / len(base5)) if base5 and v[j] > 0 else 0
    return (c[j - 1] / hi60 - 1) * 100 if hi60 > 0 else None, vr

def fwd(d, j, h):
    ei = j + 1
    if ei + h >= d['n'] or d['o'][ei] <= 0:
        return None
    return d['c'][ei + h] / d['o'][ei] - 1 - FEE

events = []
for code, d in stocks.items():
    ks = [{'close': c, 'open': o} for c, o in zip(d['c'], d['o'])]
    for j in first_board_events(ks):
        if j + 21 >= d['n']:
            continue
        dh, vr = pre(d, j)
        fwd_max = max(d['c'][j + 1:j + 26])
        events.append({'code': code, 'date': d['date'][j], '距60高': dh, '量比': vr,
                       '市值': lp.cap_at_date(capm, code, d['date'][j]),
                       '跌停': ldc.get(d['date'][j], 0) if ldc else 0,
                       '妖': fwd_max / d['c'][j] >= 1.8,
                       'r1': fwd(d, j, 1), 'r5': fwd(d, j, 5), 'r20': fwd(d, j, 20)})
base = sum(1 for e in events if e['妖']) / len(events)
print(f'事件 {len(events)} 基率 {100*base:.2f}%')

COMBOS = {
    '缩量<1.5': lambda e: 0 < e['量比'] < 1.5,
    '缩量+贴高>-15': lambda e: 0 < e['量比'] < 1.5 and (e['距60高'] or -99) > -15,
    '缩量+市值<50': lambda e: 0 < e['量比'] < 1.5 and e['市值'] is not None and e['市值'] < 50,
    '缩量+贴高+市值<50': lambda e: 0 < e['量比'] < 1.5 and (e['距60高'] or -99) > -15 and e['市值'] is not None and e['市值'] < 50,
    '缩量+贴高+市值<80': lambda e: 0 < e['量比'] < 1.5 and (e['距60高'] or -99) > -15 and e['市值'] is not None and e['市值'] < 80,
    '缩量<1.2+贴高+市值<50': lambda e: 0 < e['量比'] < 1.2 and (e['距60高'] or -99) > -15 and e['市值'] is not None and e['市值'] < 50,
}
for nm, sel in COMBOS.items():
    sub = [e for e in events if sel(e)]
    if len(sub) < 80:
        print(f'{nm}: n={len(sub)} 太少')
        continue
    nd = sum(1 for e in sub if e['妖'])
    def stat(key):
        rs = [e[key] for e in sub if e[key] is not None]
        if not rs: return None
        wins = sum(1 for x in rs if x > 0)
        return f'{100*wins/len(rs):.0f}%/{100*st.mean(rs):+.2f}%'
    print(f"{nm}: n={len(sub)} 妖率{100*nd/len(sub):.2f}% lift={nd/len(sub)/base:.2f} | 次日开盘买 T1 {stat('r1')} T5 {stat('r5')} T20 {stat('r20')}")
