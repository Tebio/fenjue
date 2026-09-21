"""H3 2-9月全账+当前持仓明细+计划出场日；v1 现行 2-9月对照（5种子随机）。"""
import sys, json, statistics as st
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
names = {str(s['code']).zfill(6): s.get('name', '')
         for s in json.loads(open('data/main_board_codes.json').read()).get('stocks', [])}
CLAIMS = {
    '跌停底座': '组合_跌停低_三连阴', '复活门': '反转族_跌停潮50', '摇篮': '妖股摇篮_成簇',
    '缺口低': '组合_缺口低开_低位阳线_避周一',
    'TD9输家': '组合_跌停低_TD9买_输家250', 'TD9超跌': '组合_跌停低_TD9买_超跌20',
}
PANIC_ONLY = {'跌停底座', '复活门', '摇篮', 'TD9输家', 'TD9超跌'}
ALL = set(CLAIMS)
GATED = {'跌停底座', 'TD9输家', 'TD9超跌'}
FEE = 0.003
IDXCAL = [k['date'] for k in json.loads(open('data/index_sh000001.json').read())]

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


def build(kept_families, panic_exempt, shallow):
    cl = {}
    for r in raw:
        if r['claim'] in GATED:
            cl.setdefault(r['dt'], set()).add(r['code'])
    kept, seen = [], set()
    keyf = (lambda x: (x['dt'], -x['pos60'])) if shallow else (lambda x: (x['dt'], x['pos60']))
    for r in sorted(raw, key=keyf):
        if r['claim'] not in kept_families:
            continue
        if r['claim'] in GATED and len(cl.get(r['dt'], set())) < 5 and not (panic_exempt and r['rg'] == '恐慌期'):
            continue
        key = (r['dt'], r['code'])
        if key not in seen:
            seen.add(key)
            kept.append(r)
    return kept


def sim(kept, day_cap, regime_gate, w0, w1, track_open=False):
    cands = []
    for r in kept:
        d = stocks[r['code']]
        ei = r['i'] + 1
        if ei >= d['n']:
            continue
        entry_d = d['date'][ei]
        if not (w0 <= entry_d <= w1):
            continue
        ep = lp._epx(d, r['i'])
        xi = min(ei + 5, d['n'] - 1)
        cands.append({'entry_d': entry_d, 'pos60': r['pos60'], 'claim': r['claim'],
                      'code': r['code'], 'rg': r['rg'], 'ep': ep, 'xi': xi, 'sig_d': r['dt']})
    cands.sort(key=lambda x: (x['entry_d'], -x['pos60']))
    cash = 50000.0
    positions, trades = [], []
    p = 0
    for day in [d for d in IDXCAL if w0 <= d <= w1]:
        for pos in [x for x in positions if x['exit_d'] == day]:
            d = stocks[pos['code']]
            cash += 5000 * (d['c'][pos['xi']] / pos['ep']) * (1 - FEE)
            trades.append(d['c'][pos['xi']] / pos['ep'] - 1 - FEE)
        positions = [x for x in positions if x['exit_d'] != day]
        entered = 0
        while p < len(cands) and cands[p]['entry_d'] == day:
            cd = cands[p]
            p += 1
            if entered >= day_cap:
                continue
            if regime_gate and cd['rg'] not in ('妖股期', '恐慌期'):
                continue
            if len(positions) < 10 and cash >= 5000:
                d = stocks[cd['code']]
                cash -= 5000
                positions.append({'code': cd['code'], 'ep': cd['ep'], 'xi': cd['xi'],
                                  'exit_d': d['date'][cd['xi']], 'entry_d': day,
                                  'claim': cd['claim'], 'sig_d': cd['sig_d']})
                entered += 1
    # 期末在途盯市
    open_pos = []
    for pos in positions:
        d = stocks[pos['code']]
        last_px = d['c'][-1]
        open_pos.append({**pos, 'last_d': d['date'][-1], 'last_px': last_px,
                         'mtm_ret': last_px / pos['ep'] - 1 - FEE})
    realized = sum(trades)
    return cash, trades, open_pos, realized


W0, W1 = '2026-02-01', '2026-09-18'
print('========== H3（现定策略）：恐慌族+浅跌+T+5+日限3+regime启停 ==========')
kept_h3 = build(PANIC_ONLY, panic_exempt=True, shallow=True)
cash, trades, open_pos, _ = sim(kept_h3, 3, True, W0, W1)
wins = sum(1 for r in trades if r > 0)
print(f'2-9月：已结算 {len(trades)} 笔 胜率{100*wins/len(trades):.0f}% 均{100*st.mean(trades):+.2f}%')
print(f'💰 期末总权益 {cash + sum(p["mtm_ret"]*5000 + 5000 for p in open_pos):,.0f} 元'
      f'（现金 {cash:,.0f} + 在途 {len(open_pos)} 仓）')
print(f'\n当前在途持仓（9/18 收盘盯市，T+5 计划出场日在本周）:')
tot_mtm = 0
for p in sorted(open_pos, key=lambda x: x['exit_d']):
    tot_mtm += p['mtm_ret'] * 5000
    nm = names.get(p['code'], '')[:6]
    print(f"  {p['code']} {nm:<8} {p['claim']:<6} 信号{p['sig_d']} 入场{p['entry_d']}@{p['ep']:.2f} "
          f"现价{p['last_px']:.2f} 浮{p['mtm_ret']*100:+.2f}% | 计划出场 {p['exit_d']}")
print(f'在途浮盈合计 {tot_mtm:+,.0f} 元')

print('\n========== v1 现行（全主张+深跌随机+T+5+成簇门无豁免）==========')
import random
res = []
for seed in (1, 2, 3, 4, 5):
    random.seed(seed)
    kept_v1 = build(ALL, panic_exempt=False, shallow=False)
    random.shuffle(kept_v1)
    cash1, trades1, open1, _ = sim(kept_v1, 99, False, W0, W1)
    fin = cash1 + sum(p['mtm_ret'] * 5000 + 5000 for p in open1)
    res.append(fin)
print(f'5 种子期末均值 {st.mean(res):,.0f} 元（{100*(st.mean(res)/50000-1):+.1f}%）')