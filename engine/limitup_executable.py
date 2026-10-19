#!/usr/bin/env python
"""涨停打板「真实可执行收益」终审：成交可行性分层 + 位置匹配对照 + 8年长历史 + 尾部/组合。

三问：
  1. 哪些板真能买到？（一字板买不到；封死后未开板排不上队；只有开过板(炸板≥1)才确定成交）
  2. 扣掉"同日/同位置/同规模"的对照组后还剩多少 alpha？
  3. 13 个月牛市样本之外，8 年逐年是否仍成立？幅度在衰减吗？

跑法： cd /opt/data/fenjue && PYTHONPATH=/opt/data/python-libs:/opt/data/fenjue/engine .venv/bin/python engine/limitup_executable.py
"""
import csv
import collections
import statistics as st
import sys

sys.path.insert(0, '/opt/data/fenjue/engine')
sys.path.insert(0, '/opt/data/python-libs')
import law_pipeline as lp  # noqa: E402

COST = 0.002
POOLS = (
    '/opt/data/fenjue/data/limit_up_mainboard_20250908_20260922.csv',
    '/opt/data/fenjue/data/limit_up_mainboard_20260923_20261019.csv',
)


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def dist_bin(x):
    if x > -0.02:
        return 0
    if x > -0.05:
        return 1
    if x > -0.10:
        return 2
    if x > -0.20:
        return 3
    return 4


DBL = ['>-2%', '-2~-5%', '-5~-10%', '-10~-20%', '<-20%']


def load_events(U):
    out = []
    for path in POOLS:
        for r in csv.DictReader(open(path, encoding='utf-8-sig')):
            d = U.get(r['代码'])
            if not d or r['日期'] not in d['date']:
                continue
            i = d['date'].index(r['日期'])
            if i + 1 >= d['n'] or d['o'][i + 1] <= 0 or i < 60:
                continue
            out.append(dict(
                dt=r['日期'], code=r['代码'], name=r['名称'],
                t1=(r['首次封板时间'] or '15:00')[:5],
                fund=num(r['封单额/流通市值(%)']) or 0,
                zbc=int(r['炸板次数'] or 0),
                ret=d['o'][i + 1] / d['c'][i] - 1 - COST,
                yizi=d['l'][i] >= d['c'][i] * 0.999,
                dist60=d['c'][i] / max(d['c'][i - 59:i + 1]) - 1,
                amt=(d['v'][i] or 0) * d['c'][i],
            ))
    return out


def stat_line(label, g, width=42):
    if len(g) < 20:
        print(f"  {label:<{width}}{len(g):>6}   样本不足")
        return
    v = [x['ret'] for x in g]
    print(f"  {label:<{width}}{len(g):>6}  {st.mean(v) * 100:>+7.2f}%"
          f"  {sum(1 for y in v if y > 0) / len(v) * 100:>5.1f}%  {st.median(v) * 100:>+7.2f}%")


def main():
    U = lp.load_universe()
    ev = load_events(U)
    base = lambda x: x['t1'] <= '10:00' and x['fund'] > 1  # noqa: E731  首封早+封单强
    strict = lambda x: base(x) and x['zbc'] == 0  # noqa: E731            严格档=再加"一次没炸"

    print('=' * 104)
    print('涨停打板真实可执行收益终审 (2026-10-19)')
    print(f'样本: {len(ev)} 笔涨停 / {len({x["dt"] for x in ev})} 个交易日 / 买涨停价 → 次日开盘卖 / 扣 {COST*100:.1f}%')
    print('成交判据: 一字板(l≥收盘)=排不上队; 炸板=0=封死后未开板, 挂涨停价也难成交; 炸板≥1=开过板, 确定能成交')
    print('=' * 104)

    print('\n【1. 成交可行性分层】')
    print(f"  {'分组':<42}{'n':>6}{'均值':>9}{'胜率':>7}{'中位':>9}")
    stat_line('全体涨停', ev)
    stat_line('严格档(首封≤10:00+封单>1%+炸板0)', [x for x in ev if strict(x)])
    stat_line('  ├ 一字板（买不到）', [x for x in ev if strict(x) and x['yizi']])
    stat_line('  ├ 非一字', [x for x in ev if strict(x) and not x['yizi']])
    stat_line('  ├ 基数档(首封≤10:00+封单>1%)', [x for x in ev if base(x)])
    stat_line('  ├ 炸板=0（封死后没打开→排不上队）', [x for x in ev if base(x) and x['zbc'] == 0])
    stat_line('  └ 炸板≥1（开过板→确定成交）', [x for x in ev if base(x) and x['zbc'] >= 1])
    stat_line('     其中 炸板=1', [x for x in ev if base(x) and x['zbc'] == 1])
    stat_line('     其中 炸板≥2', [x for x in ev if base(x) and x['zbc'] >= 2])
    stat_line('全涨停 炸板≥1（不加筛选的能成交全体）', [x for x in ev if x['zbc'] >= 1])

    # ---------- 2. 位置匹配对照 ----------
    print('\n【2. 位置匹配对照：同日 × 同距60日高档 × 同成交额档】')
    rows = []
    for c, d in U.items():
        if c[:2] not in ('60', '00'):
            continue
        n, cn, op, vv = d['n'], d['c'], d['o'], d['v']
        for i in range(60, n - 1):
            if cn[i] <= 0 or op[i + 1] <= 0 or cn[i - 1] <= 0 or vv[i] <= 0:
                continue
            rows.append((d['date'][i], cn[i] / max(cn[i - 59:i + 1]) - 1,
                         vv[i] * cn[i], op[i + 1] / cn[i] - 1 - COST,
                         cn[i] / cn[i - 1] - 1, vv[i] * cn[i]))
    byday = collections.defaultdict(list)
    for r in rows:
        byday[r[0]].append(r)
    ctrl, qs = {}, {}
    for dt, lst in byday.items():
        amts = sorted(x[2] for x in lst)
        if len(amts) < 100:
            continue
        q1, q2 = amts[len(amts) // 3], amts[2 * len(amts) // 3]
        qs[dt] = (q1, q2)
        for x in lst:
            if x[4] >= 0.097:      # 剔除当日涨停股，只留对照
                continue
            ab = 0 if x[2] <= q1 else (1 if x[2] <= q2 else 2)
            ctrl.setdefault((dt, dist_bin(x[1]), ab), []).append(x[3])
    for lab, sel in (('严格档非一字', lambda x: strict(x) and not x['yizi']),
                     ('基数档炸板≥1', lambda x: base(x) and x['zbc'] >= 1)):
        raw, exc, miss = [], [], 0
        for x in [e for e in ev if sel(e)]:
            if x['dt'] not in qs:
                miss += 1
                continue
            q1, q2 = qs[x['dt']]
            ab = 0 if x['amt'] <= q1 else (1 if x['amt'] <= q2 else 2)
            g = ctrl.get((x['dt'], dist_bin(x['dist60']), ab))
            if not g or len(g) < 5:
                miss += 1
                continue
            raw.append(x['ret'])
            exc.append(x['ret'] - st.mean(g))
        if not raw:
            print(f'  {lab}: 无可用样本')
            continue
        t = st.mean(exc) / (st.stdev(exc) / len(exc) ** 0.5)
        print(f"  {lab}: n={len(raw)}（对照缺失{miss}） 原始 {st.mean(raw)*100:+.2f}%"
              f" | 同格对照 {st.mean([a - b for a, b in zip(raw, exc)])*100:+.2f}%"
              f" | 超额 {st.mean(exc)*100:+.2f}pp 胜率(超额>0) {sum(1 for y in exc if y>0)/len(exc)*100:.1f}%"
              f" 中位 {st.median(exc)*100:+.2f}pp t={t:.2f}")

    # ---------- 3. 八年长历史 ----------
    print('\n【3. 八年长历史（kcache 全市场，涨停收盘买→次日开盘卖，无封单/炸板字段）】')
    buck = collections.defaultdict(lambda: {'all': [], 'yz': [], 'nyz': []})
    for c, d in U.items():
        if c[:2] not in ('60', '00'):
            continue
        cn, op, lo = d['c'], d['o'], d['l']
        for i in range(1, d['n'] - 1):
            if cn[i - 1] <= 0 or cn[i] <= 0 or op[i + 1] <= 0:
                continue
            if cn[i] / cn[i - 1] - 1 <= 0.097:
                continue
            r = op[i + 1] / cn[i] - 1 - COST
            y = d['date'][i][:4]
            buck[y]['all'].append(r)
            (buck[y]['yz'] if lo[i] >= cn[i] * 0.999 else buck[y]['nyz']).append(r)
    print(f"  {'年':<6}{'涨停n':>7}{'全体':>9}{'胜率':>6}{'一字占比':>8}{'一字':>9}{'非一字':>9}{'非一字胜率':>9}{'非一字中位':>10}")
    ta, tn = [], []
    for y in sorted(buck):
        b = buck[y]
        a, z, nz = b['all'], b['yz'], b['nyz']
        ta += a
        tn += nz
        print(f"  {y:<6}{len(a):>7}{st.mean(a)*100:>+8.2f}%{sum(1 for x in a if x>0)/len(a)*100:>5.0f}%"
              f"{len(z)/len(a)*100:>7.1f}%{st.mean(z)*100:>+8.2f}%{st.mean(nz)*100:>+8.2f}%"
              f"{sum(1 for x in nz if x>0)/len(nz)*100:>8.0f}%{st.median(nz)*100:>+9.2f}%")
    print(f"  {'合计':<6}{len(ta):>7}{st.mean(ta)*100:>+8.2f}%{sum(1 for x in ta if x>0)/len(ta)*100:>5.0f}%"
          f"{'':>7}{'':>9}{st.mean(tn)*100:>+8.2f}%{sum(1 for x in tn if x>0)/len(tn)*100:>8.0f}%{st.median(tn)*100:>+9.2f}%")
    print(f"  非一字涨停逐年为正: {sum(1 for y in buck if st.mean(buck[y]['nyz'])>0)}/{len(buck)} 年")

    # ---------- 4. 尾部 + 组合 ----------
    print('\n【4. 尾部风险与组合层面（基数档 炸板≥1 = 确定能成交那一档）】')
    g = [x for x in ev if base(x) and x['zbc'] >= 1]
    R = sorted(x['ret'] for x in g)
    q = lambda p: R[int(p * len(R))]  # noqa: E731
    print(f"  单笔: n={len(R)} 均值{st.mean(R)*100:+.2f}% p1 {q(.01)*100:+.1f}% p5 {q(.05)*100:+.1f}%"
          f" p25 {q(.25)*100:+.1f}% 中位{st.median(R)*100:+.2f}% p75 {q(.75)*100:+.1f}% p95 {q(.95)*100:+.1f}%"
          f" 最差{min(R)*100:+.1f}%")
    print(f"  盈亏比 {abs(st.mean([x for x in R if x>0])/st.mean([x for x in R if x<=0])):.2f}"
          f"（均赢{st.mean([x for x in R if x>0])*100:+.2f}% / 均亏{st.mean([x for x in R if x<=0])*100:+.2f}%）")
    bd = collections.defaultdict(list)
    for x in g:
        bd[x['dt']].append(x['ret'])
    days = sorted(bd)
    daily = [st.mean(bd[d]) for d in days]
    print(f"  组合: 日均{st.mean([len(bd[d]) for d in days]):.1f}只 日收益均值{st.mean(daily)*100:+.2f}%"
          f" 日胜率{sum(1 for x in daily if x>0)/len(daily)*100:.1f}% 日波动{st.stdev(daily)*100:.2f}%")
    eq = peak = 1.0
    mdd = 0.0
    for x in daily:
        eq *= 1 + x
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    print(f"  >>> 理论满仓复利 {len(daily)} 天 = {(eq-1)*100:+.0f}%，最大回撤 {mdd*100:.1f}%")
    print('  >>> 该复利数不可采信：未计入「成交率<100%」「越买得到的板越差」两项逆向选择，见报告结论')
    per = collections.defaultdict(list)
    for d in days:
        per[d[:7]].append(st.mean(bd[d]))
    print('  逐月组合: ' + '  '.join(f'{m}:{st.mean(v)*len(v)*100:+.1f}%' for m, v in sorted(per.items())))

    print('\n【5. 结论】')
    print('  (1) 一字板 +6.7~7.7% 与「封死后未开板」+4.0% 都是看得见吃不到，真实门槛在成交。')
    print('  (2) 确定能成交的（开过板/炸板≥1）严格档 +2.42%/胜63%/中位+1.86%；不加筛选的能成交全体只 +1.16%。')
    print('  (3) 位置匹配后仍有 +3pp 级超额（t≈30），alpha 不是 beta。')
    print('  (4) 八年 99880 笔：非一字涨停 +1.68%/胜63%，8/8 年全正，但幅度自 2019 的 +1.75% 衰减到 2026 的 +1.18%。')
    print('  (5) 复利数字是数学产物，不是可达收益；实盘要按「你能成交的那几笔」重算。')


if __name__ == '__main__':
    main()
