"""全栈周推演 2026-09-14→09-18：每条线逐日过闸+出票后验。
线：X3 / X2 / T1-MEGA v2 / 观察池触发 / 缺口低宽清单(v1)
"""
import sys, json, statistics as st
from datetime import date
from collections import defaultdict
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
mmap = json.load(open('data/industry_map.json'))
code2ind = {str(k).zfill(6): v['industry'] for k, v in mmap.items() if isinstance(v, dict) and v.get('industry')}
names = {str(s['code']).zfill(6): s.get('name', '')
         for s in json.loads(open('data/main_board_codes.json').read()).get('stocks', [])}
WEEK = ['2026-09-14', '2026-09-15', '2026-09-16', '2026-09-17', '2026-09-18']
IDX = json.loads(open('data/index_sh000001.json').read())
streak = {}
s = 0
for k in IDX:
    s = s + 1 if regime.get(k['date']) == '恐慌期' else 0
    streak[k['date']] = s

def wd(ds):
    return ['一', '二', '三', '四', '五'][date(int(ds[:4]), int(ds[5:7]), int(ds[8:10])).weekday()]

# 行业→日→涨停数
sec_board = defaultdict(lambda: defaultdict(int))
for code, d in stocks.items():
    ind = code2ind.get(code)
    if not ind:
        continue
    c = d['c']
    for i in range(1, d['n']):
        if d['date'][i] >= '2026-09-01' and c[i] / c[i - 1] - 1 >= 0.098:
            sec_board[ind][d['date'][i]] += 1

# 各主张信号（周窗口）
DETS = {'跌停底座': '组合_跌停低_三连阴', '复活门': '反转族_跌停潮50', '摇篮': '妖股摇篮_成簇',
        'TD9输家': '组合_跌停低_TD9买_输家250', 'TD9超跌': '组合_跌停低_TD9买_超跌20',
        '缺口低': '组合_缺口低开_低位阳线_避周一'}
sigs = defaultdict(list)   # day -> [(code, claim, pos60, vr)]
for cname, dn in DETS.items():
    det = lp.REGISTRY[dn]
    for code, d in stocks.items():
        c, h, v, n = d['c'], d['h'], d['v'], d['n']
        for i in range(lp.START, n - 1):
            dt = d['date'][i]
            if dt not in WEEK:
                continue
            if lp._epx(d, i) <= 0:
                continue
            try:
                if not det(d, i):
                    continue
            except Exception:
                continue
            hi60 = max(h[max(0, i - 60):i]) if i >= 1 else 0
            vols = [v[x] for x in range(max(1, i - 5), i)]
            vr = v[i] / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 1
            sigs[dt].append({'code': code, 'claim': cname,
                             'pos60': c[i - 1] / hi60 - 1 if hi60 > 0 else 0, 'vr': vr})

def fwd(code, sig_dt, days_n):
    d = stocks[code]
    i = d['didx'].get(sig_dt) if 'didx' in d else None
    if i is None:
        didx = {dt: k for k, dt in enumerate(d['date'])}
        i = didx.get(sig_dt)
        d['didx'] = didx
    if i is None or i + 1 >= d['n']:
        return None
    ep = lp._epx(d, i)
    xi = min(i + 1 + days_n, d['n'] - 1)
    return {'entry_d': d['date'][i + 1], 'ep': ep,
            'exit_d': d['date'][xi], 'ret': d['c'][xi] / ep - 1,
            'last': d['c'][-1] / ep - 1}

GATED = {'跌停底座', 'TD9输家', 'TD9超跌'}
for dt in WEEK:
    rows = sigs.get(dt, [])
    rg = regime.get(dt, '?')
    ldc = lp._XLDC.get(dt, 0)
    gap_n = sum(1 for r in rows if r['claim'] == '缺口低')
    pan_cl = len({r['code'] for r in rows if r['claim'] in GATED})
    big = gap_n >= 8 or ldc >= 30
    print(f'\n{"="*70}\n{dt} 周{wd(dt)} | regime={rg} 跌停{ldc} 缺口低簇{gap_n} 恐慌族簇{pan_cl} 恐慌streak={streak.get(dt, 0)}')
    # T1-MEGA v2
    if gap_n >= 20:
        print(f'  🔥T1-MEGA v2 触发！缺口低簇{gap_n}≥20 → 次日开盘量比前10，T+3卖')
    else:
        print(f'  T1-MEGA: ❌ 簇{gap_n}<20')
    # X3
    x3_ok = rg == '恐慌期' and streak.get(dt, 0) >= 2 and big
    print(f'  X3: {"✅" if x3_ok else "❌"}（需恐慌期+streak≥2+大簇，当前{rg}/streak{streak.get(dt,0)}/大簇{big}）')
    # X2
    x2_ok = rg in ('妖股期', '恐慌期') and big and not (rg == '恐慌期' and streak.get(dt, 0) < 2)
    print(f'  X2: {"✅" if x2_ok else "❌"}（需妖股/恐慌+大簇，恐慌需streak≥2）')
    # 出票模拟（X2 若触发，浅跌前三）
    if x2_ok:
        cands = sorted([r for r in rows if r['claim'] != '缺口低'], key=lambda r: -r['pos60'])
        pan_cands = [r for r in cands if r['claim'] in GATED and (rg == '恐慌期' or pan_cl >= 5)] + \
                    [r for r in cands if r['claim'] in ('复活门', '摇篮')]
        for r in pan_cands[:3]:
            f = fwd(r['code'], dt, 5)
            nm = names.get(r['code'], '')[:6]
            if f:
                print(f'    →X2票 {r["code"]} {nm} {r["claim"]} | {f["entry_d"]}@{f["ep"]:.2f} → 9/18 {100*f["last"]:+.1f}%')

# 观察池触发（池内票周内涨停+板块≥3涨停）
print(f'\n{"="*70}\n观察池触发事件（池内票涨停+行业≥3板）:')
wp = json.load(open('data/watch_pool.json'))
pool_items = wp if isinstance(wp, list) else wp.get('pool', wp.get('items', []))
pool_codes = {it['code']: it.get('name', '') for it in pool_items}
trig = 0
for dt in WEEK:
    for code, nm0 in pool_codes.items():
        d = stocks.get(code)
        if not d:
            continue
        didx = d.get('didx') or {x: k for k, x in enumerate(d['date'])}
        d['didx'] = didx
        i = didx.get(dt)
        if i is None or i < 1:
            continue
        if d['c'][i] / d['c'][i - 1] - 1 < 0.098:
            continue
        ind = code2ind.get(code, '')
        nbd = sec_board[ind].get(dt, 0)
        if nbd >= 3:
            nxt = d['c'][min(i + 2, d['n'] - 1)] / d['c'][i] - 1 if i + 1 < d['n'] else 0
            print(f'  {dt} {code} {nm0[:6]} 封板（{ind} {nbd}板）→ T+2 {100*nxt:+.1f}%')
            trig += 1
print(f'共 {trig} 次触发')