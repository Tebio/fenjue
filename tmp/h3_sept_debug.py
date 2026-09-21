import sys, json
sys.path.insert(0, 'engine')
import law_pipeline as lp
stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
CLAIMS = {'跌停底座': '组合_跌停低_三连阴', '复活门': '反转族_跌停潮50', '摇篮': '妖股摇篮_成簇',
          'TD9输家': '组合_跌停低_TD9买_输家250', 'TD9超跌': '组合_跌停低_TD9买_超跌20'}
GATED = {'跌停底座', 'TD9输家', 'TD9超跌'}
FEE = 0.003
raw = []
for cname, dn in CLAIMS.items():
    det = lp.REGISTRY[dn]
    for code, d in stocks.items():
        n = d['n']
        c, h = d['c'], d['h']
        for i in range(lp.START, n - 1):
            dt = d['date'][i]
            if dt < '2026-09-01' or lp._epx(d, i) <= 0:
                continue
            try:
                if not det(d, i):
                    continue
            except Exception:
                continue
            hi60 = max(h[max(0, i - 60):i]) if i >= 1 else 0
            raw.append({'dt': dt, 'code': code, 'i': i, 'claim': cname,
                        'rg': regime.get(dt, '?'), 'pos60': c[i - 1] / hi60 - 1 if hi60 > 0 else 0})
cl = {}
for r in raw:
    if r['claim'] in GATED:
        cl.setdefault(r['dt'], set()).add(r['code'])
kept, seen = [], set()
for r in sorted(raw, key=lambda x: (x['dt'], -x['pos60'])):
    if r['claim'] in GATED and len(cl.get(r['dt'], set())) < 5 and r['rg'] != '恐慌期':
        continue
    key = (r['dt'], r['code'])
    if key not in seen:
        seen.add(key)
        kept.append(r)
print(f'9月合格信号 {len(kept)}:')
for r in kept:
    d = stocks[r['code']]
    ei = r['i'] + 1
    if ei >= d['n']:
        continue
    ep = lp._epx(d, r['i'])
    xi = min(ei + 5, d['n'] - 1)
    mtm = 100 * (d['c'][-1] / ep - 1 - FEE)
    print(f"  信号{r['dt']} {r['code']} pos60={r['pos60']:.3f} → 入场{d['date'][ei]}@{ep:.2f} "
          f"计划出场{d['date'][xi]} 现{d['c'][-1]:.2f}(9/18) 盯市{mtm:+.2f}%")