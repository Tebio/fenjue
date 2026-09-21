"""H3 回撤解剖：全史逐日权益曲线，找出前 3 大回撤段的构成（时间/持仓/市场状态）。"""
import sys, json, statistics as st
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
names = {str(s['code']).zfill(6): s.get('name', '')
         for s in json.loads(open('data/main_board_codes.json').read()).get('stocks', [])}
CLAIMS = {'跌停底座': '组合_跌停低_三连阴', '复活门': '反转族_跌停潮50', '摇篮': '妖股摇篮_成簇',
          'TD9输家': '组合_跌停低_TD9买_输家250', 'TD9超跌': '组合_跌停低_TD9买_超跌20'}
GATED = {'跌停底座', 'TD9输家', 'TD9超跌'}
FEE = 0.003
WIN0, WIN1 = '2018-01-01', '2026-09-18'
IDX = json.loads(open('data/index_sh000001.json').read())
IDXCAL = [k['date'] for k in IDX]
CAL = [d for d in IDXCAL if WIN0 <= d <= WIN1]

raw = []
for cname, dn in CLAIMS.items():
    det = lp.REGISTRY[dn]
    for code, d in stocks.items():
        n = d['n']
        c, h = d['c'], d['h']
        for i in range(lp.START, n - 1):
            if lp._epx(d, i) <= 0:
                continue
            try:
                if not det(d, i):
                    continue
            except Exception:
                continue
            hi60 = max(h[max(0, i - 60):i]) if i >= 1 else 0
            raw.append({'dt': d['date'][i], 'code': code, 'i': i, 'claim': cname,
                        'rg': regime.get(d['date'][i], '?'),
                        'pos60': c[i - 1] / hi60 - 1 if hi60 > 0 else 0})
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

# H3 模拟（带逐日权益+完整交易记录）
cands = []
for r in kept:
    d = stocks[r['code']]
    ei = r['i'] + 1
    if ei >= d['n']:
        continue
    entry_d = d['date'][ei]
    if not (WIN0 <= entry_d <= WIN1):
        continue
    ep = lp._epx(d, r['i'])
    cands.append({'entry_d': entry_d, 'pos60': r['pos60'], 'claim': r['claim'],
                  'code': r['code'], 'rg': r['rg'], 'ep': ep, 'xi': min(ei + 5, d['n'] - 1)})
cands.sort(key=lambda x: (x['entry_d'], -x['pos60']))

cash = 50000.0
positions, trades, eq = [], [], []
p = 0
for day in CAL:
    for pos in [x for x in positions if x['exit_d'] == day]:
        d = stocks[pos['code']]
        cash += 5000 * (d['c'][pos['xi']] / pos['ep']) * (1 - FEE)
        trades.append({**pos, 'ret': d['c'][pos['xi']] / pos['ep'] - 1 - FEE})
    positions = [x for x in positions if x['exit_d'] != day]
    entered = 0
    while p < len(cands) and cands[p]['entry_d'] == day:
        cd = cands[p]
        p += 1
        if entered >= 3 or cd['rg'] not in ('妖股期', '恐慌期'):
            continue
        if len(positions) < 10 and cash >= 5000:
            d = stocks[cd['code']]
            cash -= 5000
            positions.append({'code': cd['code'], 'ep': cd['ep'], 'xi': cd['xi'],
                              'exit_d': d['date'][cd['xi']], 'entry_d': day,
                              'claim': cd['claim'], 'rg': cd['rg']})
            entered += 1
    mtm = cash
    for pos in positions:
        d = stocks[pos['code']]
        try:
            j = d['date'].index(day)
            mtm += 5000 * (d['c'][j] / pos['ep'])
        except ValueError:
            mtm += 5000
    eq.append((day, mtm, len(positions)))

# 回撤段识别：peak→trough→recovery
peak, peak_d = eq[0][1], eq[0][0]
dds = []
cur = None
for day, e, npos in eq:
    if e >= peak:
        if cur:
            dds.append(cur)
            cur = None
        peak, peak_d = e, day
    else:
        dd = (e - peak) / peak
        if cur is None:
            cur = {'peak_d': peak_d, 'peak': peak, 'trough': dd, 'trough_d': day, 'end': day}
        if dd < cur['trough']:
            cur['trough'], cur['trough_d'] = dd, day
        cur['end'] = day
if cur:
    dds.append(cur)
dds.sort(key=lambda x: x['trough'])
print('== 前 4 大回撤段 ==')
for s in dds[:4]:
    print(f"{s['peak_d']} 顶 {s['peak']:,.0f} → {s['trough_d']} 底 {100*s['trough']:.1f}% → {'未修复' if s['end']==CAL[-1] else s['end']+'修复'}")

# 最大回撤段的凶手：该段内出场的交易
worst = dds[0]
print(f"\n== 最大回撤段（{worst['peak_d']}→{worst['trough_d']}）内出场的交易 ==")
seg = [t for t in trades if worst['peak_d'] <= t['exit_d'] <= worst['trough_d']]
seg.sort(key=lambda t: t['ret'])
tot = 0
for t in seg:
    tot += t['ret'] * 5000
    nm = names.get(t['code'], '')[:6]
    print(f"  {t['entry_d']}入 {t['exit_d']}出 {t['code']} {nm:<8} {t['claim']:<6} regime={t['rg']:<4} {100*t['ret']:+.1f}%")
print(f"段内交易合计 {tot:+,.0f} 元（{len(seg)} 笔）")
# 该段指数表现
i0 = IDXCAL.index(worst['peak_d'])
i1 = IDXCAL.index(worst['trough_d'])
print(f"同期指数 {100*(IDX[i1]['close']/IDX[i0]['close']-1):+.1f}%")
# 段内 regime 分布
from collections import Counter
rgc = Counter(regime.get(d, '?') for d in IDXCAL[i0:i1+1])
print('段内 regime 分布:', dict(rgc))