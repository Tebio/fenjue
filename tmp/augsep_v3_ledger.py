"""v3 打法 8-9月全账本：逐笔明细（票/信号日/入场/出场/收益），含在途盯市。"""
import sys, json, statistics as st, bisect
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

openpos, daily, missed = [], [], 0
for r in kept:
    d = stocks[r['code']]
    n = d['n']
    ep = lp._epx(d, r['i'])
    ei = r['i'] + 1
    if ei >= n:
        continue
    r1 = d['c'][ei] / ep - 1
    tgt, tag = (20, 'T1强→T+20') if r1 >= 0.03 else (10, 'T1余→T+10')
    xi_idx = min(ei + tgt, n - 1)
    settled = ei + tgt < n
    xp = d['c'][xi_idx]
    ret = xp / ep - 1 - FEE
    entry_d, exit_d = d['date'][ei], d['date'][xi_idx]
    ci = bisect.bisect_left(IDXCAL, entry_d)
    xi = bisect.bisect_left(IDXCAL, exit_d)
    openpos = [x for x in openpos if x > ci]
    if len(openpos) < 10:
        openpos.append(xi)
        daily.append({**r, 'ep': ep, 'xp': xp, 'ret': ret, 'tag': tag,
                      'entry_d': entry_d, 'exit_d': exit_d, 'settled': settled,
                      'r1': r1})
    else:
        missed += 1

daily.sort(key=lambda t: t['entry_d'])
pnl = 0.0
print(f'{"信号日":<12}{"入场日":<12}{"出场日":<12}{"代码":<8}{"名称":<10}{"主张":<10}{"入场价":>7}{"出场价":>7}{"T1":>7}{"收益":>8}{"状态"}')
for t in daily:
    pnl += t['ret'] * 5000
    nm = names.get(t['code'], '')[:6]
    print(f"{t['dt']:<12}{t['entry_d']:<12}{t['exit_d']:<12}{t['code']:<8}{nm:<10}{t['claim']:<10}"
          f"{t['ep']:>7.2f}{t['xp']:>7.2f}{t['r1']*100:>6.1f}%{t['ret']*100:>7.2f}%  {'✅结算' if t['settled'] else '⏳在途'}")
print(f'\n成交 {len(daily)} 笔，槽满错过 {missed} 笔')
print(f'💰 总盈亏 {pnl:+.0f} 元（每笔5000，本金5万 → {pnl/500:+.2f}%）')
settled = [t for t in daily if t['settled']]
open_t = [t for t in daily if not t['settled']]
sp = sum(t['ret'] for t in settled) * 5000
op = sum(t['ret'] for t in open_t) * 5000
print(f'   已落袋 {sp:+.0f} 元 | 在途浮盈 {op:+.0f} 元')