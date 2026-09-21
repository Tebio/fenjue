"""深跌板块首起色→篮子买入 全史检验（2019→2026/9，无前视）。
触发：行业等权日涨≥2% 且当日行业排名前5 且行业指数距120日高点≤-20% 且20交易日内首次
入场：次日开盘 买行业全部成分等权（费0.15%）出场：T+5/T+10/T+20收盘
对照A：全市场等权同期；对照B：同样触发但位置≥-5%（高位置起色，验证位置是第一变量）
"""
import sys, json, statistics as st
from collections import defaultdict
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
m = json.load(open('data/industry_map.json'))
code2ind = {str(k).zfill(6): v['industry'] for k, v in m.items() if isinstance(v, dict) and v.get('industry')}
IDX = json.loads(open('data/index_sh000001.json').read())
CAL = [k['date'] for k in IDX if '2019-01-01' <= k['date'] <= '2026-09-18']
FEE = 0.0015

# 每股：date->i 索引
for code, d in stocks.items():
    d['didx'] = {dt: i for i, dt in enumerate(d['date'])}

# 行业日收益（等权）+ 行业指数
inds = sorted({v for v in code2ind.values() if v})
ind_codes = defaultdict(list)
for c, i in code2ind.items():
    if c in stocks:
        ind_codes[i].append(c)
inds = [i for i in inds if len(ind_codes[i]) >= 8]

ind_ret = {i: {} for i in inds}   # ind -> day -> 等权日收益
for d in CAL:
    pass
for ind in inds:
    for code in ind_codes[ind]:
        d = stocks[code]
        c = d['c']
        for dt, i in d['didx'].items():
            if dt < CAL[0] or i < 1 or i >= len(c):
                continue
            pc = c[i - 1]
            if pc > 0:
                r = c[i] / pc - 1
                if dt in ind_ret[ind]:
                    ind_ret[ind][dt].append(r)
                else:
                    ind_ret[ind][dt] = [r]
ind_mean = {ind: {dt: st.mean(v) for dt, v in ind_ret[ind].items() if len(v) >= max(5, len(ind_codes[ind]) // 3)}
            for ind in inds}

# 行业指数 + 120日高点位置
ind_pos = {ind: {} for ind in inds}
for ind in inds:
    idx = 1.0
    hist = []
    for dt in CAL:
        idx *= (1 + ind_mean[ind].get(dt, 0))
        hist.append(idx)
        if len(hist) > 120:
            hist.pop(0)
        ind_pos[ind][dt] = idx / max(hist) - 1

# 市场等权日收益
mkt_ret = {}
for dt in CAL:
    v = [ind_mean[ind][dt] for ind in inds if dt in ind_mean[ind]]
    mkt_ret[dt] = st.mean(v) if v else 0

def basket_fwd(ind, dt, h):
    """次日开盘买行业篮子，h 交易日收盘卖。返回行业篮子收益与市场篮子收益。"""
    i0 = CAL.index(dt)
    if i0 + 1 + h >= len(CAL):
        return None
    ed, xd = CAL[i0 + 1], CAL[i0 + 1 + h]
    rs, mrs = [], []
    for code in ind_codes[ind]:
        d = stocks[code]
        j1, j2 = d['didx'].get(ed), d['didx'].get(xd)
        if j1 is None or j2 is None:
            continue
        o = d['o'][j1] if 'o' in d else None
        if o is None or o <= 0:
            continue
        rs.append(d['c'][j2] / o - 1)
    # 市场篮子
    for code in list(stocks)[:400]:
        d = stocks[code]
        j1, j2 = d['didx'].get(ed), d['didx'].get(xd)
        if j1 is None or j2 is None:
            continue
        o = d['o'][j1] if 'o' in d else None
        if o is None or o <= 0:
            continue
        mrs.append(d['c'][j2] / o - 1)
    if not rs or not mrs:
        return None
    return st.mean(rs) - FEE, st.mean(mrs) - FEE

# 触发扫描
def scan(pos_max, first_n=20):
    events = []
    for dt in CAL[130:]:
        ranked = sorted((ind for ind in inds if dt in ind_mean[ind]),
                        key=lambda k: ind_mean[k][dt], reverse=True)
        for ind in ranked[:5]:
            r = ind_mean[ind][dt]
            pos = ind_pos[ind].get(dt, 0)
            if r < 0.02 or pos > pos_max:
                continue
            # 20 交易日内首次
            i0 = CAL.index(dt)
            prior = CAL[max(0, i0 - first_n):i0]
            dup = any(ind_mean[ind].get(p, 0) >= 0.02 and ind_pos[ind].get(p, 0) <= pos_max for p in prior)
            if not dup:
                events.append((dt, ind))
    return events

for label, pos_max in (('深跌≤-20%', -0.20), ('高位置≥-5%', -0.05)):
    evs = scan(pos_max)
    print(f'\n== {label}起色 → 篮子买入（{len(evs)} 次）==')
    for h in (5, 10, 20):
        diffs, rets = [], []
        for dt, ind in evs:
            fw = basket_fwd(ind, dt, h)
            if fw:
                rets.append(fw[0])
                diffs.append(fw[0] - fw[1])
        if diffs:
            w = sum(1 for x in diffs if x > 0)
            t = st.mean(diffs) / (st.stdev(diffs) / len(diffs) ** 0.5) if len(diffs) > 2 else 0
            print(f'  T+{h}: 篮子均值 {100*st.mean(rets):+.2f}% | 超额 {100*st.mean(diffs):+.2f}% '
                  f'跑赢率 {100*w/len(diffs):.0f}% | t={t:.1f} (n={len(diffs)})')
    if label.startswith('深跌'):
        print('  事件清单（前 12）:', [(d, i[:8]) for d, i in evs[:12]])
        # 农业案例验证
        agri = [(d, i) for d, i in evs if '农' in i or '畜' in i or '渔' in i]
        print('  农业系事件:', [(d, i[:10]) for d, i in agri])