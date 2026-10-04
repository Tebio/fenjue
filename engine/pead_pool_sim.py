#!/usr/bin/env python3
"""预增低位池·组合级历史模拟（2019-2026）——事件研究→实盘净值曲线的翻译层
规则逐字复刻 engine/pead_pool.py 生产口径：
  池=主板非ST(当代名单近似) 60自然日内预增/扭亏(略增≥50) + 距60日高≤-20% + 流通市值<50亿(cap_hist PIT)
  10万本金/5槽×2万; T日收盘入选(低价<5元优先,层内深→浅) → T+1开盘买(费双边0.15%)
  卖: ①浮盈≥10%后收盘自峰值回撤10%→当日收盘卖 ②满20交易日→收盘卖
  满仓跳过; 持有期内不重复买
输出: data/pead_pool_sim_20261004.json (净值曲线/年度/回撤/暴露度/逐笔)
已知限制: ST过滤用当代名单(历史ST不可辨); 停牌票按最后价持有; 退市票若停更=末价结算(偏差记档)
"""
import json, glob, os, bisect, sys
from datetime import date as _date, timedelta as _td

ROOT = '/opt/data/fenjue'
sys.path.insert(0, os.path.join(ROOT, 'engine'))
import pead_pool as pp   # 复用 pead_map/cap_at(带缓存)

START, END = '2019-01-02', '2026-09-30'
SLOT, SLOTS, FEE_RT = 20000.0, 5, 0.0015
HOLD_DAYS = 20

# ---- 数据预载（一次性构建索引）----
nm = pp.names()
K = {}
for f in glob.glob(f'{ROOT}/data/big_kcache/*.json'):
    code = os.path.basename(f)[:6]
    if not code.startswith(('60', '00')): continue
    n = nm.get(code, '')
    if 'ST' in n or '退' in n: continue
    bars = json.load(open(f))
    K[code] = (bars, {b['date']: j for j, b in enumerate(bars)})
CAL = pp.trading_days()
CAL = [d for d in CAL if START <= d <= END]
print(f'宇宙 {len(K)} 只, 交易日 {len(CAL)} 天', flush=True)

pead = pp.pead_map()
def has_pead60(code, dstr):
    ds = pead.get(code)
    if not ds: return False
    y, m, dd = map(int, dstr.split('-'))
    lo = str(_date(y, m, dd) - _td(days=60)); hi = str(_date(y, m, dd) - _td(days=1))
    i = bisect.bisect_left(ds, lo)
    return i < len(ds) and ds[i] <= hi

# ---- 组合状态 ----
cash = 100000.0
slots = []          # {code, shares, entry_price, entry_i, peak_close, active_stop}
pending = []        # [(code, pos)] 次日开盘买
trades = []         # 逐笔
equity_curve = []   # (date, equity, n_slots)
skipped_full = 0

def close_of(code, d):
    bars, idx = K[code]
    j = idx.get(d)
    return bars[j]['close'] if j is not None else None

for di, d in enumerate(CAL):
    # 1) 开盘成交待买
    if pending and slots.__len__() < SLOTS:
        for code, pos in list(pending):
            if len(slots) >= SLOTS: skipped_full += 1; continue
            bars, idx = K[code]
            j = idx.get(d)
            if j is None or bars[j]['volume'] == 0:
                pending.remove((code, pos)); continue   # 停牌=放弃
            o = bars[j]['open']
            shares = SLOT / o
            cash -= SLOT   # 买入扣款
            slots.append({'code': code, 'shares': shares, 'entry': o, 'entry_i': di,
                          'peak': o, 'stop_on': False})
            pending.remove((code, pos))
    # 2) 收盘检查卖出
    for s in list(slots):
        c = close_of(s['code'], d)
        if c is None: continue
        s['peak'] = max(s['peak'], c)
        if c >= s['entry'] * 1.10: s['stop_on'] = True
        sell = None
        if s['stop_on'] and c <= s['peak'] * 0.90: sell = 'trailing'
        elif di - s['entry_i'] >= HOLD_DAYS: sell = 'hold20'
        if sell:
            gross = s['shares'] * c
            net = gross - (SLOT + gross) * FEE_RT / 2   # 双边合计0.15%
            cash += net
            trades.append({'code': s['code'], 'entry_d': CAL[s['entry_i']], 'exit_d': d,
                           'ret': net / SLOT - 1, 'why': sell, 'days': di - s['entry_i']})
            slots.remove(s)
    # 3) 收盘选新池入队
    if len(slots) + len(pending) < SLOTS:
        cands = []
        for code, (bars, idx) in K.items():
            j = idx.get(d)
            if j is None or j < 59: continue
            b = bars[j]
            if b['volume'] == 0: continue
            cap = pp.cap_at(code, d)
            if cap is None or cap >= 50: continue
            h60 = max(x['high'] for x in bars[j - 59:j + 1])
            if h60 <= 0: continue
            pos = b['close'] / h60 - 1
            if pos > -0.20: continue
            if not has_pead60(code, d): continue
            if any(s['code'] == code for s in slots) or any(p[0] == code for p in pending): continue
            cands.append((code, b['close'], pos))
        cands.sort(key=lambda r: (0 if r[1] < 5 else 1, r[2]))
        for code, _, pos in cands[:SLOTS - len(slots) - len(pending)]:
            pending.append((code, pos))
    # 4) 记净值
    eq = cash + sum(s['shares'] * (close_of(s['code'], d) or s['entry']) for s in slots)
    equity_curve.append((d, round(eq, 0), len(slots)))
    if di % 200 == 0: print(f'[{di}/{len(CAL)}] {d} eq={eq:.0f} slots={len(slots)} trades={len(trades)}', flush=True)

# ---- 汇总 ----
eq0, eq1 = equity_curve[0][1], equity_curve[-1][1]
years = {}
for d, e, n in equity_curve:
    y = d[:4]
    years.setdefault(y, []).append(e)
ann = {y: (v[-1] / v[0] - 1) for y, v in years.items()}
peak = 0; mdd = 0
for _, e, _ in equity_curve:
    peak = max(peak, e); mdd = min(mdd, e / peak - 1)
rets = [t['ret'] for t in trades]
from statistics import mean
expo = sum(n for _, _, n in equity_curve) / len(equity_curve) / SLOTS
out = {
    'total_ret': eq1 / eq0 - 1, 'years': ann, 'max_dd': mdd,
    'n_trades': len(trades), 'win': sum(1 for r in rets if r > 0) / max(len(rets), 1),
    'avg_ret': mean(rets) if rets else 0, 'avg_days': mean([t['days'] for t in trades]) if trades else 0,
    'exposure': expo, 'skipped_full': skipped_full,
    'sell_why': {w: sum(1 for t in trades if t['why'] == w) for w in ('trailing', 'hold20')},
    'curve_tail': equity_curve[-5:], 'start': equity_curve[0], 'end': equity_curve[-1],
}
json.dump(out, open(f'{ROOT}/data/pead_pool_sim_20261004.json', 'w'), ensure_ascii=False, indent=1)
json.dump(equity_curve, open(f'{ROOT}/data/pead_pool_sim_curve.json', 'w'))
json.dump(trades, open(f'{ROOT}/data/pead_pool_sim_trades.json', 'w'), ensure_ascii=False)
print('\n=== 组合级模拟 2019-2026 ===')
print(f"总收益 {out['total_ret']:.1%} | 最大回撤 {mdd:.1%} | 仓位暴露 {expo:.0%}")
print(f"交易 {len(trades)} 笔 | 胜率 {out['win']:.0%} | 均笔 {out['avg_ret']:+.2%} | 均持 {out['avg_days']:.1f} 天")
print('卖出原因:', out['sell_why'])
for y, r in sorted(ann.items()): print(f'  {y}: {r:+.1%}')
