"""盘中板块轮动警报回测（m60，2024-08-30→2026-09-18，严格无前视）。
警报规则（bar t 时刻只知道 ≤t 的数据）：
  市场弱：指数 000001 在 bar t 的涨幅 ≤ -0.3%
  板块热：行业均值涨幅 top5 且 ≥2 只 ≥+5%（R1严）或 ≥1 只 ≥+7%（R2宽）且超指数+1.5pp
  龙头=板块内涨幅最高且未封板（pct<9.8）的票（可成交近似）
入场=下一根 bar 开盘价（14:00 警报=15:00 bar 开盘≈尾盘）
出场=T+1 收盘 / T+2 收盘。费 0.3%。
对照：同日同 bar 随机票；同日收盘买龙头。
附：8/17（金健米业）、8/28（国芳）案发日逐 bar 复盘。
"""
import json, glob, statistics as st, random
from collections import defaultdict

BARTS = ('10:30', '11:30', '14:00')
SECTORS = json.loads(open('data/industry_map.json').read())
SECTORS = {str(k).zfill(6): (v['industry'] if isinstance(v, dict) else v) for k, v in SECTORS.items()}
SECTORS = {k: v for k, v in SECTORS.items() if v}

# ── 数据装载：每股每日每 bar 状态（无前视：pct 用昨日收盘，量能同比昨同时段）──
# recs[(day, t)] = list of (code, pct, cumvol_ratio)
recs = defaultdict(list)
# fwd[code][day] = {'bars': {t: (o,c)}, 'prev': prev_day_close}
files = glob.glob('data/m60_cache/*.json')
print(f'{len(files)} 只票装载中...')
for fi, f in enumerate(files):
    code = f.split('/')[-1][:6]
    try:
        bars = json.load(open(f))
    except Exception:
        continue
    days = defaultdict(list)
    for b in bars:
        days[b['day'][:10]].append(b)
    for v in days.values():
        v.sort(key=lambda b: b['day'])
    dts = sorted(days)
    for di, dt in enumerate(dts):
        if di == 0:
            continue
        prev_close = float(days[dts[di - 1]][-1]['close'])
        if prev_close <= 0:
            continue
        cum = 0.0
        ycum = {}
        cy = 0.0
        for b in days[dts[di - 1]]:
            cy += float(b['volume'])
            ycum[b['day'][11:16]] = cy
        for b in days[dt]:
            t = b['day'][11:16]
            cum += float(b['volume'])
            if t in BARTS:
                pct = float(b['close']) / prev_close - 1
                yv = ycum.get(t, 0)
                vr = cum / yv if yv > 0 else 1.0
                recs[(dt, t)].append((code, pct, vr))
print(f'装载完成 {len(recs)} 个 (日,bar) 切片')

# 指数切片
idx_bars = json.load(open('data/m60_cache/000001.json'))
idx_days = defaultdict(list)
for b in idx_bars:
    idx_days[b['day'][:10]].append(b)
for v in idx_days.values():
    v.sort(key=lambda b: b['day'])
IDT = sorted(idx_days)
idx_pct = {}
for di, dt in enumerate(IDT):
    if di == 0:
        continue
    pc = float(idx_days[IDT[di - 1]][-1]['close'])
    for b in idx_days[dt]:
        idx_pct[(dt, b['day'][11:16])] = float(b['close']) / pc - 1

# 前向收益：同一 m60 数据里找入场 bar 的下一 bar open、T+1/T+2 收盘
m60 = {}
for f in files:
    code = f.split('/')[-1][:6]
    try:
        bars = json.load(open(f))
    except Exception:
        continue
    days = defaultdict(dict)
    for b in bars:
        days[b['day'][:10]][b['day'][11:16]] = (float(b['open']), float(b['close']))
    m60[code] = dict(days)
ALLDAYS = IDT
day_idx = {d: i for i, d in enumerate(ALLDAYS)}
NEXTBAR = {'10:30': '11:30', '11:30': '14:00', '14:00': '15:00'}


def forward(code, day, t):
    """入场=下一bar open；返回 (T+1收盘收益, T+2收盘收益) 相对入场价，数据缺则 None。"""
    nb = NEXTBAR[t]
    ent = m60.get(code, {}).get(day, {}).get(nb)
    if not ent or ent[0] <= 0:
        return None
    ep = ent[0]
    i = day_idx.get(day)
    if i is None or i + 1 >= len(ALLDAYS):
        return None
    d1 = m60.get(code, {}).get(ALLDAYS[i + 1], {})
    c1 = d1.get('15:00', (0, 0))[1]
    if c1 <= 0:
        return None
    r1 = c1 / ep - 1 - 0.003
    r2 = None
    if i + 2 < len(ALLDAYS):
        c2 = m60.get(code, {}).get(ALLDAYS[i + 2], {}).get('15:00', (0, 0))[1]
        if c2 > 0:
            r2 = c2 / ep - 1 - 0.003
    return r1, r2


def scan(rule):
    alerts = []
    for (dt, t), rows in sorted(recs.items()):
        ip = idx_pct.get((dt, t))
        if ip is None or ip > -0.003:
            continue
        sec = defaultdict(list)
        for code, pct, vr in rows:
            s = SECTORS.get(code)
            if s:
                sec[s].append((code, pct, vr))
        mkt_mean = st.mean(p for _, p, _ in rows)
        ranks = sorted(sec, key=lambda s: st.mean(p for _, p, _ in sec[s]), reverse=True)
        for s in ranks[:8]:
            rows_s = sec[s]
            if len(rows_s) < 10:
                continue
            sm = st.mean(p for _, p, _ in rows_s)
            if s not in ranks[:5] and rule == 'R1':
                continue
            hot5 = [r for r in rows_s if r[1] >= 0.05]
            hot7 = [r for r in rows_s if r[1] >= 0.07]
            if sm - mkt_mean < 0.015:
                continue
            if rule == 'R1' and len(hot5) < 2:
                continue
            if rule == 'R2' and len(hot7) < 1:
                continue
            # 龙头=未封板最强票
            cands = [r for r in rows_s if 0.05 <= r[1] < 0.098]
            if not cands:
                continue
            leader = max(cands, key=lambda r: r[1])
            alerts.append({'day': dt, 't': t, 'sector': s, 'code': leader[0],
                           'pct': leader[1], 'vr': leader[2], 'idx': ip})
            break  # 每 bar 只报最强板块
    return alerts


random.seed(7)
res = {}
for rule in ('R1', 'R2'):
    alerts = scan(rule)
    r1s, r2s, ctrl = [], [], []
    days_seen = set()
    for a in alerts:
        fw = forward(a['code'], a['day'], a['t'])
        if fw is None:
            continue
        r1s.append(fw[0])
        if fw[1] is not None:
            r2s.append(fw[1])
        days_seen.add((a['day'], a['t']))
        # 对照：同切片随机票
        rows = recs[(a['day'], a['t'])]
        rc = random.choice(rows)[0]
        fw2 = forward(rc, a['day'], a['t'])
        if fw2:
            ctrl.append(fw2[0])
    res[rule] = (alerts, r1s, r2s, ctrl)
    print(f'\n== {rule} ==')
    print(f'警报 {len(alerts)} 次（{len(alerts)/len(days_seen) if days_seen else 0:.1f}/有弱市bar）')
    if r1s:
        w = sum(1 for x in r1s if x > 0)
        print(f'T+1: 胜率 {100*w/len(r1s):.0f}% 均值 {100*st.mean(r1s):+.2f}% (n={len(r1s)})')
    if r2s:
        w = sum(1 for x in r2s if x > 0)
        print(f'T+2: 胜率 {100*w/len(r2s):.0f}% 均值 {100*st.mean(r2s):+.2f}% (n={len(r2s)})')
    if ctrl:
        w = sum(1 for x in ctrl if x > 0)
        print(f'对照(随机票T+1): 胜率 {100*w/len(ctrl):.0f}% 均值 {100*st.mean(ctrl):+.2f}% (n={len(ctrl)})')

# 案发日复盘
print('\n== 案发日复盘 ==')
for dt, code, nm in [('2026-08-17', '600127', '金健米业'), ('2026-08-28', '601086', '国芳集团')]:
    for t in BARTS:
        rows = recs.get((dt, t), [])
        hit = [r for r in rows if r[0] == code]
        ip = idx_pct.get((dt, t), 0)
        if hit:
            s = SECTORS.get(code, '?')
            sec_rows = [r for r in rows if SECTORS.get(r[0]) == s]
            sm = st.mean(p for _, p, _ in sec_rows) if sec_rows else 0
            hot5 = sum(1 for r in sec_rows if r[1] >= 0.05)
            print(f'{dt} {t} {nm}: 涨幅{100*hit[0][1]:+.1f}% 量比{hit[0][2]:.1f} | 指数{100*ip:+.2f}% | {s}板块 均值{100*sm:+.2f}% ≥5%有{hot5}只')