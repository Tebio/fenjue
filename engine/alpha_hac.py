#!/usr/bin/env python3
"""engine/alpha_hac.py — 策略A 的 alpha：日度组合 + Newey-West HAC（2026-10-19）

前一次用「间隔>5交易日=新簇」聚簇得 25 个 episode，该方法有缺陷：
跌停几乎每个交易日都有，连续信号日必然连成一片，8 年会被并成 1 个簇。
正确做法是不依赖任意聚簇，直接用日度持仓组合 + HAC 标准误（滞后=持有期）。

策略A定义（不含 MA60，因 MA60 只是过滤；这里测「跌停即买」与「跌停×MA60下买」两种）
  在持仓期内（买入后 5 个交易日）每天持有该股，等权组合日收益 = 组合内个股日收益均值
  超额 = 组合日收益 - 全市场等权日收益
"""
import json
import math
import statistics as st
from pathlib import Path

ROOT = Path('/opt/data/fenjue')
UNADJ = ROOT / 'data/big_kcache_unadj'
FQ = ROOT / 'data/big_kcache'
HOLD = 5
MB = ('600', '601', '603', '605', '000', '001', '002', '003')
EPS = 0.0015


def lim_price(pc, rate):
    return round(pc * rate + 1e-9, 2)


def match(a, b):
    return abs(a - b) <= EPS


pos_days = {'ld': {}, 'ld_ma60': {}}
mkt_acc = {}
cal_set = set()

for p in FQ.glob('*.json'):
    c = p.stem
    if c[:3] not in MB:
        continue
    uf = UNADJ / f'{c}.json'
    if not uf.exists():
        continue
    try:
        fk = json.loads(p.read_text())
        uk = json.loads(uf.read_text())
    except Exception:
        continue
    if not isinstance(fk, list) or len(fk) < 130 or not isinstance(uk, list):
        continue
    ud = {k['date']: k for k in uk}
    cal_set.update(k['date'] for k in fk)
    n = len(fk)

    # 全市场等权日收益
    mret = {}
    for i in range(1, n):
        pc = fk[i - 1]['close']
        if pc > 0:
            r = fk[i]['close'] / pc - 1
            mret[fk[i]['date']] = r
            a = mkt_acc.setdefault(fk[i]['date'], [0.0, 0])
            a[0] += r
            a[1] += 1

    # 滚动 MA60（前复权）
    closes = [k['close'] for k in fk]
    ma60 = [None] * n
    s = 0.0
    for i in range(n):
        s += closes[i]
        if i >= 60:
            s -= closes[i - 60]
        if i >= 59:
            ma60[i] = s / 60

    for i in range(60, n - 1 - HOLD):
        u0 = ud.get(fk[i - 1]['date'])
        u1 = ud.get(fk[i]['date'])
        if not u0 or not u1 or u0['close'] <= 0:
            continue
        if not (match(u1['close'], lim_price(u0['close'], 0.9))
                or match(u1['close'], lim_price(u0['close'], 0.95))):
            continue
        # 次日买得到（非一字涨停封板）
        un = ud.get(fk[i + 1]['date'])
        if not un:
            continue
        rate_up = 1.1 if match(u1['close'], lim_price(u0['close'], 0.9)) else 1.05
        if un['open'] >= lim_price(u1['close'], rate_up) - EPS:
            continue
        bi = i + 1
        keys = ['ld']
        if ma60[i] is not None and closes[i] <= ma60[i]:
            keys.append('ld_ma60')
        # 持仓期 = 买入日次日起 5 个交易日的日收益
        for k in keys:
            for j in range(bi + 1, min(bi + 1 + HOLD, n)):
                d = fk[j]['date']
                pcj = fk[j - 1]['close']
                if pcj <= 0:
                    continue
                pos_days[k].setdefault(d, []).append(fk[j]['close'] / pcj - 1)

mkt = {d: v[0] / v[1] for d, v in mkt_acc.items() if v[1] >= 500}
cal = sorted(cal_set)
print(f'主日历 {len(cal)} 日  {cal[0]} ~ {cal[-1]}')


def hac_t(seq, L):
    n = len(seq)
    mu = st.mean(seq)
    g0 = sum((x - mu) ** 2 for x in seq) / n
    var = g0
    for l in range(1, L + 1):
        gl = sum((seq[i] - mu) * (seq[i - l] - mu) for i in range(l, n)) / n
        var += 2 * (1 - l / (L + 1)) * gl
    se = math.sqrt(max(var, 1e-18) / n)
    return mu / se if se > 0 else 0.0, mu


for k, lab in (('ld', '跌停即买（无双条件）'), ('ld_ma60', '跌停 × 收盘≤MA60')):
    pd_ = pos_days[k]
    days = sorted(pd_)
    if len(days) < 100:
        continue
    port = [st.mean(pd_[d]) for d in days]
    mk = [mkt.get(d, 0.0) for d in days]
    exc = [a - b for a, b in zip(port, mk)]
    # 复利累计
    cum_p = math.prod(1 + x for x in port) - 1
    cum_e = math.prod(1 + x for x in exc) - 1
    print(f'\n=== {lab} ===')
    print(f'  持仓日 {len(days)}  日均组合收益 {st.mean(port)*100:+.4f}%  '
          f'日均市场 {st.mean(mk)*100:+.4f}%  日均超额 {st.mean(exc)*100:+.4f}%')
    print(f'  累计（组合，复利）{cum_p*100:+.1f}%   累计（超额，复利）{cum_e*100:+.1f}%')
    for L in (0, 5, 10, 20):
        t_p, _ = hac_t(port, L)
        t_e, _ = hac_t(exc, L)
        print(f'  HAC lag={L:<3} t(组合)={t_p:>6.2f}   t(超额)={t_e:>6.2f}')
    nul = sum(1 for x in exc if x > 0)
    print(f'  超额为正的交易日 {nul}/{len(exc)} = {nul/len(exc)*100:.1f}%')
