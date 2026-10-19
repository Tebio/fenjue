#!/usr/bin/env python3
"""engine/limitdown_exact.py — 不复权精确判跌停 + ST 5% 纳入（2026-10-19 v2）

K3 指出的两个上游错误：
  ① 前复权价 round(fq_close*0.9,2) 对不上真实限价 → 跌停判定精度错
  ② ST/*ST 是 5% 限价，-10% 公式永不触发 → 事件样本系统性排除 ST

v2 修正：以「前复权日历」为唯一主日历（收益/市场/聚簇全用它），
不复权价只作 date→价格 的字典查表用于判限价，避免两套日历错位。
"""
import json
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


ev10, ev5, evall = [], [], []
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

    for i in range(1, len(fk)):
        pc = fk[i - 1]['close']
        if pc > 0:
            a = mkt_acc.setdefault(fk[i]['date'], [0.0, 0])
            a[0] += fk[i]['close'] / pc - 1
            a[1] += 1

    for i in range(60, len(fk) - 1 - HOLD):
        d0 = fk[i - 1]['date']
        d = fk[i]['date']
        u0, u1 = ud.get(d0), ud.get(d)
        if not u0 or not u1:
            continue
        pc_u = u0['close']
        cl_u = u1['close']
        if pc_u <= 0 or cl_u <= 0:
            continue
        is10 = match(cl_u, lim_price(pc_u, 0.9))
        is5 = match(cl_u, lim_price(pc_u, 0.95))
        if not (is10 or is5):
            continue
        # 次日可成交性（不复权判一字/封涨停）
        nd = fk[i + 1]['date']
        un = ud.get(nd)
        if not un:
            continue
        up = lim_price(cl_u, 1.1) if is10 else lim_price(cl_u, 1.05)
        if un['open'] >= up - EPS:
            continue
        bi = i + 1
        si = bi + HOLD
        if si >= len(fk):
            continue
        bpx, spx = fk[bi]['open'], fk[si]['close']
        if bpx <= 0 or spx <= 0:
            continue
        rec = (d, fk[bi]['date'], fk[si]['date'], spx / bpx - 1)
        if is10:
            ev10.append(rec)
        else:
            ev5.append(rec)
        evall.append(rec)

mkt = {d: v[0] / v[1] for d, v in mkt_acc.items() if v[1] >= 500}
cal = sorted(cal_set)
ci = {d: i for i, d in enumerate(cal)}
print(f'主日历（前复权）{len(cal)} 日  {cal[0]} ~ {cal[-1]}')
print(f'不复权精确判跌停：10% 档 {len(ev10)}  5% 档(ST) {len(ev5)}  合计 {len(evall)}')


def summarize(lab, evs):
    if not evs:
        print(f'\n  {lab}: 无样本')
        return
    R = [e[3] * 100 for e in evs]
    days = sorted({e[0] for e in evs})
    cl = [[days[0]]]
    for d in days[1:]:
        if ci[d] - ci[cl[-1][-1]] <= HOLD:
            cl[-1].append(d)
        else:
            cl.append([d])
    cmap = {d: k for k, cc in enumerate(cl) for d in cc}
    exc, miss = [], 0
    for d, bd, sd, r in evs:
        jb, js = ci.get(bd), ci.get(sd)
        if jb is None or js is None:
            miss += 1
            continue
        acc, ok = 1.0, True
        for k in range(jb, js + 1):
            v = mkt.get(cal[k])
            if v is None:
                ok = False
                break
            acc *= 1 + v
        if ok:
            exc.append(((r - (acc - 1)) * 100, cmap[d]))
        else:
            miss += 1
    byc = {}
    for v, c in exc:
        byc.setdefault(c, []).append(v)
    means = [st.mean(v) for v in byc.values()]
    t = st.mean(means) / st.stdev(means) * (len(means) ** 0.5) if len(means) > 2 else 0.0
    print(f'\n  {lab}')
    print(f'    事件 {len(R)}  原始 {st.mean(R):+.2f}%  胜率 {sum(1 for x in R if x>0)/len(R)*100:.1f}%'
          f'  (市场窗口缺失 {miss})')
    print(f'    独立 episode {len(cl)}  →  有效 {len(means)}   簇级超额 {st.mean(means):+.2f}%  '
          f'簇级 t {t:.2f}  正超额 {sum(1 for x in means if x>0)}/{len(means)}')
    return len(cl), t


summarize('仅 10% 档（旧口径的精确版）', ev10)
summarize('仅 5% 档（ST，旧口径完全漏掉）', ev5)
summarize('全部（10% + ST 5%）', evall)
