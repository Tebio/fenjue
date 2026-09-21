"""v3 打法全史压力测试（2018→2026-09-18）+ 2026年2-9月切片。
输出：逐年明细、最大回撤（逐日盯市权益曲线）、单笔最大亏损、最长连亏、2-9月窗口。
口径与 v3 账本完全一致：10槽×5000、费0.3%、T+1开盘入场剔一字跌停、
T1强(≥+3%)→T+20 其余→T+10、恐慌期日豁免深档系成簇门、超跌最深选票。
"""
import sys, json, statistics as st, bisect
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
FEE = 0.003
IDXCAL = [k['date'] for k in json.loads(open('data/index_sh000001.json').read())]

# ── 全史信号收集 ──
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
print(f'全史原始命中 {len(raw)}')

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
print(f'闸门+去重后 {len(kept)}')


def run(win0, win1, label):
    openpos = []          # (exit_cal_idx)
    positions = []        # 在持 {'code','ep','entry_i_in_stock','exit_i','exit_d','scale'}
    cash = 50000.0
    equity_curve = []     # (date, equity)
    trades = []           # 完成的 {'entry_d','exit_d','ret','claim'}
    missed = 0
    cal = [d for d in IDXCAL if win0 <= d <= win1]
    c2i = {d: k for k, d in enumerate(cal)}
    # 预生成候选（入场日在窗口内）
    cands = []
    for r in kept:
        d = stocks[r['code']]
        ei = r['i'] + 1
        if ei >= d['n']:
            continue
        entry_d = d['date'][ei]
        if entry_d < win0 or entry_d > win1:
            continue
        r1 = d['c'][ei] / lp._epx(d, r['i']) - 1
        tgt = 20 if r1 >= 0.03 else 10
        xi = min(ei + tgt, d['n'] - 1)
        cands.append((entry_d, r['pos60'], r, ei, xi))
    cands.sort(key=lambda x: (x[0], x[1]))
    p = 0
    for day in cal:
        ci = c2i[day]
        # 出场
        for pos in [x for x in positions if x['exit_d'] == day]:
            d = stocks[pos['code']]
            cash += 5000 * (d['c'][pos['exit_i']] / pos['ep']) * (1 - FEE)
            trades.append({'entry_d': pos['entry_d'], 'exit_d': day,
                           'ret': d['c'][pos['exit_i']] / pos['ep'] - 1 - FEE,
                           'claim': pos['claim'], 'code': pos['code']})
        positions = [x for x in positions if x['exit_d'] != day]
        # 入场（当日候选）
        while p < len(cands) and cands[p][0] == day:
            _, _, r, ei, xi = cands[p]
            p += 1
            if len(positions) < 10 and cash >= 5000:
                d = stocks[r['code']]
                ep = lp._epx(d, r['i'])
                cash -= 5000
                positions.append({'code': r['code'], 'ep': ep, 'exit_i': xi,
                                  'exit_d': d['date'][xi], 'claim': r['claim'],
                                  'entry_d': day})
            else:
                missed += 1
        # 逐日盯市
        mtm = cash
        for pos in positions:
            d = stocks[pos['code']]
            j = bisect.bisect_left(d['date'], day)
            if j < d['n'] and d['date'][j] == day:
                mtm += 5000 * (d['c'][j] / pos['ep'])
            else:
                mtm += 5000  # 停牌按成本
        equity_curve.append((day, mtm))
    # 未平仓按窗口末收盘强平
    for pos in positions:
        d = stocks[pos['code']]
        trades.append({'entry_d': pos['entry_d'], 'exit_d': cal[-1],
                       'ret': d['c'][-1] / pos['ep'] - 1 - FEE,
                       'claim': pos['claim'], 'code': pos['code']})

    # 指标
    eq = [e for _, e in equity_curve]
    peak, mdd, mdd_d = eq[0], 0.0, ''
    for day, e in equity_curve:
        peak = max(peak, e)
        dd = (e - peak) / peak
        if dd < mdd:
            mdd, mdd_d = dd, day
    rets = [t['ret'] for t in trades]
    wins = sum(1 for r in rets if r > 0)
    worst = min(rets) if rets else 0
    # 最长连亏（按出场日序）
    trades.sort(key=lambda t: t['exit_d'])
    streak = mx_streak = 0
    for t in trades:
        streak = streak + 1 if t['ret'] <= 0 else 0
        mx_streak = max(mx_streak, streak)
    final = eq[-1] if eq else 50000
    print(f'\n===== {label} =====')
    print(f'成交 {len(trades)} 笔（容量/现金错过 {missed}）| 胜率 {100*wins/len(trades):.1f}% | 均笔 {100*st.mean(rets):+.2f}%')
    print(f'💰 期末权益 {final:,.0f} 元（{100*(final/50000-1):+.1f}%）')
    print(f'📉 最大回撤 {100*mdd:.1f}%（{mdd_d}）| 单笔最大亏损 {100*worst:+.1f}% | 最长连亏 {mx_streak} 笔')
    # 逐年
    by_year = {}
    for t in trades:
        by_year.setdefault(t['entry_d'][:4], []).append(t['ret'])
    print('逐年:', {y: f"{len(v)}笔 胜率{100*sum(1 for x in v if x>0)/len(v):.0f}% 均{100*st.mean(v):+.2f}% 合计{sum(v)*5000:+,.0f}元" for y, v in sorted(by_year.items())})
    # 分主张
    bc = {}
    for t in trades:
        bc.setdefault(t['claim'], []).append(t['ret'])
    print('分主张:', {k: f"{len(v)}笔 均{100*st.mean(v):+.2f}%" for k, v in sorted(bc.items())})
    return equity_curve, trades

run('2018-01-01', '2026-09-18', '全史 2018-2026/9（8年8个月）')
run('2026-02-01', '2026-09-18', '2026年2-9月')