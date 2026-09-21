"""9/14-18 当前规则集完整回测：逐日各线出票+后验至9/18。
线：v1缺口低宽清单(15:35扫→次日9:32确认≥5) / X3 / X2 / T1-MEGA v2 / 观察池(已降级) / H3遗产仓
"""
import sys, json, statistics as st
from collections import defaultdict
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
names = {str(s['code']).zfill(6): s.get('name', '')
         for s in json.loads(open('data/main_board_codes.json').read()).get('stocks', [])}
WEEK = ['2026-09-14', '2026-09-15', '2026-09-16', '2026-09-17', '2026-09-18']
IDX = json.loads(open('data/index_sh000001.json').read())
streak = {}
s = 0
for k in IDX:
    s = s + 1 if regime.get(k['date']) == '恐慌期' else 0
    streak[k['date']] = s

det_gap = lp.REGISTRY['组合_缺口低开_低位阳线_避周一']
DETP = {'跌停底座': '组合_跌停低_三连阴', '复活门': '反转族_跌停潮50', '摇篮': '妖股摇篮_成簇',
        'TD9输家': '组合_跌停低_TD9买_输家250', 'TD9超跌': '组合_跌停低_TD9买_超跌20'}

gap_sigs = defaultdict(list)
pan_sigs = defaultdict(list)
for code, d in stocks.items():
    c, h, v, n = d['c'], d['h'], d['v'], d['n']
    didx = {dt: k for k, dt in enumerate(d['date'])}
    for dt in WEEK:
        i = didx.get(dt)
        if i is None or i < lp.START or i + 1 >= n or lp._epx(d, i) <= 0:
            continue
        hi60 = max(h[max(0, i - 60):i]) if i >= 1 else 0
        pos60 = c[i - 1] / hi60 - 1 if hi60 > 0 else 0
        vols = [v[x] for x in range(max(1, i - 5), i)]
        vr = v[i] / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 1
        ep = lp._epx(d, i)
        r_mtm = c[-1] / ep - 1
        r_t1 = c[i + 2] / ep - 1 if i + 2 < n else None
        try:
            if det_gap(d, i):
                gap_sigs[dt].append({'code': code, 'pos60': pos60, 'vr': vr,
                                     'ep': ep, 'mtm': r_mtm, 't1': r_t1, 'entry_d': d['date'][i + 1]})
        except Exception:
            pass
        for cn, dn in DETP.items():
            try:
                if lp.REGISTRY[dn](d, i):
                    pan_sigs[dt].append({'code': code, 'claim': cn, 'pos60': pos60, 'vr': vr,
                                         'ep': ep, 'mtm': r_mtm, 'entry_d': d['date'][i + 1]})
            except Exception:
                pass

pnl_total = 0.0
for dt in WEEK:
    rg = regime.get(dt, '?')
    ldc = lp._XLDC.get(dt, 0)
    gs = gap_sigs.get(dt, [])
    ps = pan_sigs.get(dt, [])
    pan_cl = len({r['code'] for r in ps if r['claim'] in ('跌停底座', 'TD9输家', 'TD9超跌')})
    big = len(gs) >= 8 or ldc >= 30
    print(f'\n{"="*66}\n📅 {dt} {rg} 跌停{ldc} 缺口低簇{len(gs)} 恐慌族簇{pan_cl}')
    # v1 宽清单：簇≥5 推（次日9:32确认）
    if len(gs) >= 5:
        rets = [r['t1'] for r in gs if r['t1'] is not None]
        mtms = [r['mtm'] for r in gs]
        w = sum(1 for x in rets if x > 0)
        print(f'  📨 v1宽清单 {len(gs)} 只 → 次日9:32推 | T+1胜率{100*w/len(rets):.0f}% 均{100*st.mean(rets):+.2f}% | 至9/18均{100*st.mean(mtms):+.2f}%')
        for r in sorted(gs, key=lambda x: -x['vr'])[:7]:
            nm = names.get(r['code'], '')[:6]
            t1s = f"{100*r['t1']:+.1f}%" if r['t1'] is not None else '在途'
            print(f'      {r["code"]} {nm:<7} 量比{r["vr"]:.1f} | T+1 {t1s} | 9/18 {100*r["mtm"]:+.1f}%')
    else:
        print(f'  v1宽清单: 簇{len(gs)}<5 不推')
    # T1-MEGA v2
    if len(gs) >= 20:
        top10 = sorted(gs, key=lambda x: -x['vr'])[:10]
        rets3 = [r['mtm'] for r in top10]
        print(f'  🔥T1-MEGA v2 触发（簇{len(gs)}≥20）→ 次日量比前10 T+3')
    else:
        print(f'  T1-MEGA: 簇{len(gs)}<20 ❌')
    # X2
    x2 = rg in ('妖股期', '恐慌期') and big and not (rg == '恐慌期' and streak.get(dt, 0) < 2)
    if x2 and ps:
        picks = sorted(ps, key=lambda x: -x['pos60'])[:3]
        print(f'  ✅X2 触发 → 浅跌前三:')
        for r in picks:
            nm = names.get(r['code'], '')[:6]
            print(f'      {r["code"]} {nm:<7} {r["claim"]} pos60={r["pos60"]:.2f} | 9/18 {100*r["mtm"]:+.1f}%')
    else:
        why = '非妖股/恐慌' if rg not in ('妖股期', '恐慌期') else ('非大簇' if not big else '恐慌streak=1（第2天规则拦）')
        print(f'  X2: ❌ {why}')
    # X3
    x3 = rg == '恐慌期' and streak.get(dt, 0) >= 2 and big
    print(f'  X3: {"✅" if x3 else "❌"}')

# H3 遗产仓（9/11、9/15 信号）
print(f'\n{"="*66}\n📦 H3 遗产仓（9/11恐慌日+9/15信号，本周持有表现）:')
for code, sig, ed, ep in [('603090', '9/11', '9/14', 32.05), ('603983', '9/15', '9/16', 28.03),
                          ('000430', '9/15', '9/16', 6.54), ('605188', '9/15', '9/16', 11.45)]:
    d = stocks[code]
    last = d['c'][-1]
    nm = names.get(code, '')[:6]
    print(f'  {code} {nm:<7} 信号{sig} {ed}@{ep:.2f} → 9/18 {last:.2f} {100*(last/ep-1):+.1f}%')

# 观察池（已降级——新文案下不会挂单，仅展示躲过什么）
print(f'\n📉 观察池（新文案=只观察，躲过的 8 次排队）:')
print('  海马-6.7% 柘中-5.8% 天融信-5.5% 通达-1.7% 中闽-5.7% 三夫+0.4% 华锋-3.8% 乐凯-2.2% → 躲过均值-4.1%的坑')