"""v3：T1弱不早割（强→T+20，其余→T+10），超跌选票，恐慌豁免。对照 v2/v1 + 8-9月基准。"""
import sys, json, statistics as st, random, bisect
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()

CLAIMS = {
    '跌停底座': '组合_跌停低_三连阴', '复活门': '反转族_跌停潮50', '摇篮': '妖股摇篮_成簇',
    '缺口低': '组合_缺口低开_低位阳线_避周一',
    'TD9输家': '组合_跌停低_TD9买_输家250', 'TD9超跌': '组合_跌停低_TD9买_超跌20',
}
PANIC_FAM = {'跌停底座', 'TD9输家', 'TD9超跌'}
WIN = ('2026-08-01', '2026-09-18')
FEE = 0.003
IDXCAL = [k['date'] for k in json.loads(open('data/index_sh000001.json').read())]

raw = []
for cname, dn in CLAIMS.items():
    det = lp.REGISTRY[dn]
    for code, d in stocks.items():
        n = d['n']
        c, h = d['c'], d['h']
        for i in range(lp.START, n - 1):
            dt = d['date'][i]
            if dt < WIN[0] or dt > WIN[1] or lp._epx(d, i) <= 0:
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

def exits_v3(d, i):
    n = d['n']
    ep = lp._epx(d, i)
    ei = i + 1
    if ei >= n:
        return None, None
    r1 = d['c'][ei] / ep - 1
    tgt, tag = (20, 'T1强→T+20') if r1 >= 0.03 else (10, 'T1余→T+10')
    if ei + tgt < n:
        return d['c'][ei + tgt] / ep - 1 - FEE, tag + '结算'
    return d['c'][-1] / ep - 1 - FEE, tag + '盯市'

cl = {}
for r in raw:
    if r['claim'] in PANIC_FAM:
        cl.setdefault(r['dt'], set()).add(r['code'])
kept, seen = [], set()
for r in sorted(raw, key=lambda x: (x['dt'], x['pos60'])):
    if r['claim'] in PANIC_FAM and len(cl.get(r['dt'], set())) < 5 and r['rg'] != '恐慌期':
        continue
    key = (r['dt'], r['code'])
    if key not in seen:
        seen.add(key)
        kept.append(r)

openpos, pnl, taken, missed, daily = [], 0.0, 0, 0, []
for r in kept:
    d = stocks[r['code']]
    ret, tag = exits_v3(d, r['i'])
    if ret is None:
        continue
    holdn = 20 if 'T+20' in tag else 10
    entry_d = d['date'][r['i'] + 1]
    exit_d = d['date'][min(r['i'] + 1 + holdn, d['n'] - 1)]
    ei = bisect.bisect_left(IDXCAL, entry_d)
    xi = bisect.bisect_left(IDXCAL, exit_d)
    openpos = [x for x in openpos if x > ei]
    if len(openpos) < 10:
        openpos.append(xi)
        pnl += ret * 5000
        taken += 1
        daily.append({**r, 'ret': ret, 'tag': tag})
    else:
        missed += 1

settled = [t for t in daily if '结算' in t['tag']]
mtm = [t for t in daily if '盯市' in t['tag']]
print(f'== v3：T1强→T+20/其余→T+10（不早割）+ 超跌选票 + 恐慌豁免 ==')
print(f'入场 {taken} 笔（错过 {missed}）| 结算 {len(settled)} 盯市 {len(mtm)}')
if settled:
    rs = [t['ret'] for t in settled]
    print(f'已结算 胜率{100*sum(1 for x in rs if x>0)/len(rs):.0f}% 均{100*st.mean(rs):+.2f}%')
if mtm:
    rs = [t['ret'] for t in mtm]
    print(f'盯市 胜率{100*sum(1 for x in rs if x>0)/len(rs):.0f}% 均{100*st.mean(rs):+.2f}%')
print(f'💰 总盈亏 {pnl:+.0f} 元 = {pnl/500:+.2f}%')
tg = {}
for t in daily:
    tg.setdefault(t['tag'].replace('结算', '').replace('盯市', ''), []).append(t['ret'])
print('分档:', {k: f"{len(v)}笔 均{100*st.mean(v):+.2f}%" for k, v in sorted(tg.items())})
bc = {}
for t in daily:
    bc.setdefault(t['claim'], []).append(t['ret'])
print('分主张:', {k: f"{len(v)}笔 均{100*st.mean(v):+.2f}%" for k, v in sorted(bc.items())})

# 基准
idx = json.loads(open('data/index_sh000001.json').read())
seg = [k for k in idx if '2026-08-01' <= k['date'] <= '2026-09-18']
prev = [k for k in idx if k['date'] < '2026-08-01'][-1]
print(f"\n基准：上证 8-9月 {(seg[-1]['close']/prev['close']-1)*100:+.2f}%")