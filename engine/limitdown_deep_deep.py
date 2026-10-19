#!/usr/bin/env python
"""四条「跌停×MA60下深跌」线终审（2026-10-19）—— 性能版：
先一次性为每只股票预计算 跌停/三连阴/距MA60≤-25%/次日数据 向量，
四条线 = 向量的与组合；对照池与退市/年分布同理向量化。

跑法： cd /opt/data/fenjue && PYTHONPATH=/opt/data/python-libs:/opt/data/fenjue/engine .venv/bin/python engine/limitdown_deep_deep.py
"""
import collections
import json
import statistics as st
import sys
sys.path.insert(0, '/opt/data/fenjue/engine')
sys.path.insert(0, '/opt/data/python-libs')
import law_pipeline as lp  # noqa: E402

COST = 0.002
MAX_HOLD = 20
STOP_LOSS, TAKE_PROFIT = -0.08, 0.15

LINES = {
    'COMP_LIMITDOWN_LOW_DEEP': ('deep',),
    'COMP_LIMITDOWN_LOW_DEEP_LDC100': ('deep', 'ldc100'),
    'COMP_LIMITDOWN_LOW_3DOWN': ('limitdown_low', 'three_down'),
    'COMP_LIMITDOWN_LOW_3DOWN_DEEP': ('deep', 'three_down'),
}
EXIT_NAMES = {'t1o': 'T+1开盘', 't1c': 'T+1收', 't2c': 'T+2收', 't3c': 'T+3收',
              't5c': 'T+5收', 't10c': 'T+10收', 't20c': 'T+20收', 'sl': '止损8/盈15'}
BUY_NAMES = {'close_t': '信号日收盘', 'open_t1': '次日开盘', 'close_t1': '次日收盘', 'ma5_pull': '回踩MA5'}


def dist_bin(x):
    if x > -0.02: return 0
    if x > -0.05: return 1
    if x > -0.10: return 2
    if x > -0.20: return 3
    return 4


def main():
    U = lp.load_universe()
    lp.build_xsection(U)
    xldc = lp._XLDC
    delisted = set(json.loads(open('/opt/data/fenjue/data/delisted_codes.json').read())['codes'])
    main_codes = [c for c in U if c[:2] in ('60', '00')]
    print(f"全市场股票数: {len(U)}（主板60/00: {len(main_codes)}），后来退市标记: {len(delisted)}", flush=True)

    # ---------- 预计算每只股票的特征向量 ----------
    print("预计算特征向量...", flush=True)
    FEAT = {}   # code -> dict of lists (只保留有效 i 的行)
    cal_set = set()
    for code in main_codes:
        d = U[code]
        c, o, h, l, v, ma60, dates, n = d['c'], d['o'], d['h'], d['l'], d['v'], d['ma60'], d['date'], d['n']
        cal_set.update(dates)
        rec = dict(dt=[], yr=[], i=[], ld=[], low=[], deep=[], td=[], ldc100=[],
                   px=[], no=[], nc=[], dist60=[], amt=[],
                   t1o=[], t1c=[], t2c=[], t3c=[], t5c=[], t10c=[], t20c=[], sl=[],
                   ma5pull_px=[], ma5pull_i=[])
        for i in range(max(lp.START, 60), n - 1):
            if c[i] <= 0 or c[i-1] <= 0 or o[i+1] <= 0:
                continue
            r = c[i]/c[i-1] - 1
            ld = (r <= -0.095) and not (o[i]/c[i-1]-1 <= -0.09 and (h[i]-l[i])/c[i-1] < 0.01)
            if not ld:
                continue
            m = ma60[i]
            if m is None or m <= 0:
                continue
            low = c[i] <= m
            deep = c[i] <= m*0.75
            td = i >= 3 and c[i] < o[i] and c[i-1] < o[i-1] and c[i-2] < o[i-2]
            if not (low or deep):
                continue
            rec['dt'].append(dates[i]); rec['yr'].append(dates[i][:4]); rec['i'].append(i)
            rec['ld'].append(ld); rec['low'].append(low); rec['deep'].append(deep)
            rec['td'].append(td); rec['ldc100'].append(xldc.get(dates[i], 0) >= 100)
            rec['px'].append(c[i]); rec['no'].append(o[i+1])
            rec['nc'].append(c[i+1] if c[i+1] > 0 else None)
            rec['dist60'].append(c[i]/max(c[i-59:i+1]) - 1)
            rec['amt'].append(v[i]*c[i])
            # 卖出曲线（信号日收盘买）
            for tag, k in (('t1o', 1),):
                rec[tag].append(o[i+1]/c[i] - 1 - 2*COST if o[i+1] > 0 else None)
            for tag, k in (('t1c', 1), ('t2c', 2), ('t3c', 3), ('t5c', 5), ('t10c', 10), ('t20c', 20)):
                j = i + k
                rec[tag].append(c[j]/c[i] - 1 - 2*COST if j < n and c[j] > 0 else None)
            # 止损止盈
            rsl = None
            for j in range(i+1, min(i+MAX_HOLD+1, n)):
                if l[j] <= c[i]*(1+STOP_LOSS):
                    rsl = STOP_LOSS - 2*COST
                    break
                if h[j] >= c[i]*(1+TAKE_PROFIT):
                    rsl = TAKE_PROFIT - 2*COST
                    break
            if rsl is None:
                j = min(i+MAX_HOLD, n-1)
                if j > i and c[j] > 0:
                    rsl = c[j]/c[i] - 1 - 2*COST
            rec['sl'].append(rsl)
            # 回踩MA5买点
            m5px, m5i = None, None
            for j in range(i+1, min(i+11, n)):
                if j >= 4 and all(x > 0 for x in c[j-4:j+1]):
                    ma5 = sum(c[j-4:j+1])/5
                    if 0 < c[j] <= ma5:
                        m5px, m5i = c[j], j
                        break
            rec['ma5pull_px'].append(m5px); rec['ma5pull_i'].append(m5i)
        if rec['i']:
            FEAT[code] = rec
    cal = sorted(cal_set)
    cidx = {dt: k for k, dt in enumerate(cal)}
    print(f"有跌停×低位记录的股票 {len(FEAT)}，交易日总数 {len(cal)}", flush=True)

    # ---------- 组合四条线 ----------
    S = {}
    for cid, conds in LINES.items():
        sigs = []
        for code, f in FEAT.items():
            for k in range(len(f['i'])):
                ok = True
                for cd in conds:
                    if cd == 'deep' and not f['deep'][k]: ok = False; break
                    if cd == 'limitdown_low' and not (f['ld'][k] and f['low'][k]): ok = False; break
                    if cd == 'three_down' and not f['td'][k]: ok = False; break
                    if cd == 'ldc100' and not f['ldc100'][k]: ok = False; break
                if ok:
                    sigs.append(dict(code=code, k=k, dt=f['dt'][k], yr=f['yr'][k], i=f['i'][k],
                                     px=f['px'][k], no=f['no'][k], nc=f['nc'][k],
                                     dist60=f['dist60'][k], amt=f['amt'][k]))
        S[cid] = sorted(sigs, key=lambda x: (x['dt'], x['code']))
        print(f"  {cid}: n={len(S[cid])}", flush=True)

    # ---------- 1. 每年次数 ----------
    print('\n' + '='*100)
    print('【1. 信号复现 & 每年次数】')
    years = sorted({x['yr'] for s in S.values() for x in s})
    print(f"  {'线':<38}{'总n':>7}{'首个':>12}{'末个':>12}{'信号日数':>9}")
    for cid, sigs in S.items():
        dts = [x['dt'] for x in sigs]
        print(f"  {cid:<38}{len(sigs):>7}{dts[0]:>12}{dts[-1]:>12}{len(set(dts)):>9}")
    print(f"\n  每年信号笔数：")
    print(f"  {'线':<38}" + ''.join(f'{y:>7}' for y in years) + f"{'年均(≤25)':>10}")
    for cid, sigs in S.items():
        by = collections.Counter(x['yr'] for x in sigs)
        fy = [y for y in years if int(y) <= 2025]
        avg = sum(by.get(y, 0) for y in fy)/len(fy)
        print(f"  {cid:<38}" + ''.join(f'{by.get(y,0):>7}' for y in years) + f"{avg:>10.1f}")
    print(f"\n  每年信号日(去重交易日)数：")
    for cid, sigs in S.items():
        by = collections.defaultdict(set)
        for x in sigs:
            by[x['yr']].add(x['dt'])
        print(f"  {cid:<38}" + ''.join(f'{len(by.get(y,set())):>7}' for y in years))
    for cid, sigs in S.items():
        d26 = sorted(set(x['dt'] for x in sigs if x['yr'] == '2026'))
        print(f"  2026 {cid}: {len(d26)} 天 → {d26}")

    # ---------- 2. 卖出规则曲线 ----------
    print('\n' + '='*100)
    print('【2. 卖出规则曲线（信号日收盘买入，扣双边 0.4%）】')
    print(f"  {'线':<38}{'规则':>10}{'n':>6}{'均值':>9}{'胜率':>7}{'中位':>9}")
    EXITS = ['t1o', 't1c', 't2c', 't3c', 't5c', 't10c', 't20c', 'sl']
    for cid, sigs in S.items():
        for tag in EXITS:
            v = []
            for x in sigs:
                val = FEAT[x['code']][tag][x['k']]
                if val is not None:
                    v.append(val)
            if not v:
                continue
            print(f"  {cid:<38}{EXIT_NAMES[tag]:>10}{len(v):>6}{st.mean(v)*100:>+8.2f}%"
                  f"{sum(1 for y in v if y>0)/len(v)*100:>6.1f}%{st.median(v)*100:>+8.2f}%")

    # ---------- 3. 买入时点 ----------
    print('\n【3. 买入时点对比（卖出 T+20收 / T+5收）】')
    print(f"  {'线':<38}{'买点':>10}{'n':>6}{'T+20均':>9}{'胜':>6}{'T+5均':>9}{'胜':>6}")
    for cid, sigs in S.items():
        acc = {k: {'t20': [], 't5': []} for k in BUY_NAMES}
        for x in sigs:
            d, i = U[x['code']], x['i']
            c, o, n = d['c'], d['o'], d['n']
            for bp in BUY_NAMES:
                if bp == 'close_t':
                    bi, bpx = i, c[i]
                elif bp == 'open_t1':
                    bi, bpx = i+1, o[i+1] if i+1 < n else None
                elif bp == 'close_t1':
                    bi, bpx = i+1, (c[i+1] if i+1 < n and c[i+1] > 0 else None)
                else:
                    bpx = FEAT[x['code']]['ma5pull_px'][x['k']]
                    bi = FEAT[x['code']]['ma5pull_i'][x['k']]
                if not bpx or bi is None:
                    continue
                for tag, k in (('t20', 20), ('t5', 5)):
                    j = bi + k
                    if j < n and c[j] > 0:
                        acc[bp][tag].append(c[j]/bpx - 1 - 2*COST)
        for bp in BUY_NAMES:
            v20, v5 = acc[bp]['t20'], acc[bp]['t5']
            if not v20:
                continue
            print(f"  {cid:<38}{BUY_NAMES[bp]:>10}{len(v20):>6}{st.mean(v20)*100:>+8.2f}%"
                  f"{sum(1 for y in v20 if y>0)/len(v20)*100:>5.1f}%"
                  f"{st.mean(v5)*100 if v5 else float('nan'):>+8.2f}%"
                  f"{sum(1 for y in v5 if y>0)/len(v5)*100 if v5 else 0:>5.1f}%")

    # ---------- 4. 位置匹配对照 ----------
    print('\n' + '='*100)
    print('【4. 位置匹配对照：同日 × 同距60日高档 × 同成交额三分位 的非跌停股（T+20收卖口径）】')
    print("建对照池（两遍扫描，低内存）...", flush=True)
    # 第一遍：只收集每日成交额序列 → 三分位
    amt_byday = collections.defaultdict(list)
    for code in main_codes:
        d = U[code]
        n, cn, vv = d['n'], d['c'], d['v']
        for i in range(60, n-21):
            if cn[i] <= 0 or cn[i-1] <= 0 or vv[i] <= 0:
                continue
            amt_byday[d['date'][i]].append(vv[i]*cn[i])
    qs = {}
    for dt, amts in amt_byday.items():
        if len(amts) < 100:
            continue
        amts.sort()
        qs[dt] = (amts[len(amts)//3], amts[2*len(amts)//3])
    del amt_byday
    print(f"  有效对照交易日 {len(qs)}", flush=True)
    # 第二遍：直接落入 ctrl 格
    ctrl20 = {}
    for code in main_codes:
        d = U[code]
        n, cn, vv = d['n'], d['c'], d['v']
        dates = d['date']
        for i in range(60, n-21):
            if cn[i] <= 0 or cn[i-1] <= 0 or vv[i] <= 0 or cn[i+20] <= 0:
                continue
            dt = dates[i]
            qq = qs.get(dt)
            if qq is None:
                continue
            if cn[i]/cn[i-1]-1 <= -0.095:
                continue
            a = vv[i]*cn[i]
            ab = 0 if a <= qq[0] else (1 if a <= qq[1] else 2)
            key = (dt, dist_bin(cn[i]/max(cn[i-59:i+1])-1), ab)
            g = ctrl20.get(key)
            if g is None:
                ctrl20[key] = [cn[i+20]/cn[i]-1-2*COST]
            else:
                g.append(cn[i+20]/cn[i]-1-2*COST)
    print(f"  对照格数 {len(ctrl20)}", flush=True)
    print(f"  {'线':<38}{'n':>6}{'缺':>5}{'原始':>9}{'对照':>9}{'超额pp':>9}{'超额胜':>7}{'t':>7}")
    for cid, sigs in S.items():
        raw, exc, miss = [], [], 0
        for x in sigs:
            if x['dt'] not in qs:
                miss += 1
                continue
            q1, q2 = qs[x['dt']]
            ab = 0 if x['amt'] <= q1 else (1 if x['amt'] <= q2 else 2)
            g = ctrl20.get((x['dt'], dist_bin(x['dist60']), ab))
            if not g or len(g) < 5:
                miss += 1
                continue
            r20 = FEAT[x['code']]['t20c'][x['k']]
            if r20 is None:
                miss += 1
                continue
            raw.append(r20)
            exc.append(r20 - st.mean(g))
        if not raw:
            print(f'  {cid}: 无可用样本')
            continue
        t = st.mean(exc)/(st.stdev(exc)/len(exc)**0.5) if len(exc) > 1 else 0
        ctrl_mean = st.mean([a-b for a, b in zip(raw, exc)])
        print(f"  {cid:<38}{len(raw):>6}{miss:>5}{st.mean(raw)*100:>+8.2f}%"
              f"{ctrl_mean*100:>+8.2f}%{st.mean(exc)*100:>+8.2f}"
              f"{sum(1 for y in exc if y>0)/len(exc)*100:>6.1f}%{t:>7.2f}")

    # ---------- 5. 幸存偏差 ----------
    print('\n' + '='*100)
    print('【5. 幸存偏差：信号里后来退市股占比；剔除后 T+20 子样本】')
    print(f"  {'线':<38}{'总n':>6}{'退市n':>6}{'占比':>7}{'全样本':>9}{'剔退市':>9}{'剔退市胜':>9}")
    for cid, sigs in S.items():
        de = [x for x in sigs if x['code'] in delisted]
        va = [FEAT[x['code']]['t20c'][x['k']] for x in sigs if FEAT[x['code']]['t20c'][x['k']] is not None]
        vk = [FEAT[x['code']]['t20c'][x['k']] for x in sigs
              if x['code'] not in delisted and FEAT[x['code']]['t20c'][x['k']] is not None]
        print(f"  {cid:<38}{len(sigs):>6}{len(de):>6}{len(de)/max(len(sigs),1)*100:>6.1f}%"
              f"{st.mean(va)*100 if va else 0:>+8.2f}%{st.mean(vk)*100 if vk else 0:>+8.2f}%"
              f"{sum(1 for y in vk if y>0)/len(vk)*100 if vk else 0:>8.1f}%")
        if de:
            by = collections.Counter(x['yr'] for x in de)
            print(f"    退市信号年分布: {dict(sorted(by.items()))}")

    # ---------- 6. 分年稳定性 ----------
    print('\n' + '='*100)
    print('【6. 分年稳定性（信号日收盘买 → T+20收卖）】')
    for cid, sigs in S.items():
        by = collections.defaultdict(list)
        for x in sigs:
            v = FEAT[x['code']]['t20c'][x['k']]
            if v is not None:
                by[x['yr']].append(v)
        print(f"  {cid}")
        print(f"    {'年':<6}{'n':>6}{'均值':>9}{'胜率':>7}{'中位':>9}{'正收益年':>9}")
        for y in sorted(by):
            v = by[y]
            print(f"    {y:<6}{len(v):>6}{st.mean(v)*100:>+8.2f}%"
                  f"{sum(1 for z in v if z>0)/len(v)*100:>6.1f}%{st.median(v)*100:>+8.2f}%"
                  f"{'正' if st.mean(v)>0 else '负':>9}")

    # ---------- 7. 组合容量 ----------
    print('\n' + '='*100)
    print('【7. 组合容量（信号日收盘满仓买入，T+20收盘卖出）】')
    yr_days = collections.Counter(dt[:4] for dt in cal)
    for cid, sigs in S.items():
        byday = collections.defaultdict(int)
        for x in sigs:
            byday[x['dt']] += 1
        days = sorted(byday)
        if not days:
            continue
        occupied = set()
        for x in sigs:
            k0 = cidx.get(x['dt'])
            if k0 is not None:
                for k in range(k0, min(k0+21, len(cal))):
                    occupied.add(cal[k])
        occ_yr = collections.Counter(dt[:4] for dt in occupied)
        gaps = [cidx[days[k+1]]-cidx[days[k]] for k in range(len(days)-1)]
        allyears = sorted(set(x[:4] for x in days))
        print(f"  {cid}: 信号日 {len(days)} 天 / 日均 {len(sigs)/len(days):.2f} 只")
        print(f"    年占用: " + ', '.join(f"{y}:{occ_yr.get(y,0)}/{yr_days.get(y,0)}" for y in allyears))
        if gaps:
            print(f"    资金占用率(全期): {len(occupied)/len(cal)*100:.1f}%"
                  f"  信号日间隔: 中位{st.median(gaps):.0f} 最大{max(gaps)} 均值{st.mean(gaps):.1f} 交易日")
            # 最长空窗段
            mk, mi = max(gaps), gaps.index(max(gaps))
            print(f"    最长空窗: {days[mi]} → {days[mi+1]}（{mk} 个交易日）")

    # ---------- 8. 结论汇总 ----------
    print('\n' + '='*100)
    print('【8. 结论汇总（单笔期望=信号日收盘买 T+20收卖，扣双边 0.4%）】')
    print(f"  {'线':<38}{'年均笔':>8}{'年均日':>8}{'单笔期望':>10}{'胜率':>7}{'占用率':>8}{'2026n':>6}")
    for cid, sigs in S.items():
        v = [FEAT[x['code']]['t20c'][x['k']] for x in sigs if FEAT[x['code']]['t20c'][x['k']] is not None]
        fy = [y for y in sorted(set(x['yr'] for x in sigs)) if int(y) <= 2025]
        nfull = sum(1 for x in sigs if x['yr'] in fy)
        dfull = len(set(x['dt'] for x in sigs if x['yr'] in fy))
        occupied = set()
        for x in sigs:
            k0 = cidx.get(x['dt'])
            if k0 is not None:
                for k in range(k0, min(k0+21, len(cal))):
                    occupied.add(cal[k])
        print(f"  {cid:<38}{nfull/max(len(fy),1):>8.1f}{dfull/max(len(fy),1):>8.1f}"
              f"{st.mean(v)*100 if v else 0:>+9.2f}%{sum(1 for y in v if y>0)/len(v)*100 if v else 0:>6.1f}%"
              f"{len(occupied)/len(cal)*100:>7.1f}%{sum(1 for x in sigs if x['yr']=='2026'):>6}")


if __name__ == '__main__':
    main()
