#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
打板卖出端风险四项测试：
  任务一：次日开盘能不能卖掉（跌停/一字跌停/低开>5% 比例；卖不掉顺延到收盘/T+2 的收益）
  任务二：用成交额/流通市值反推可成交性，构造评分并分档看收益
  任务三：开盘卖 vs 盘中卖 vs 收盘卖 vs T+2 开盘卖；开盘价在当日振幅中的分位
  任务四：按日组合的连亏风险（连续亏损天数、最大连续亏损笔数、最差 5 天累计、本金测算）

样本：散户真能排到队的档 = 炸板>=1 + 首封<=10:00 + 封单/流通<1%，非一字。
对照也给全体/严格档。
买在涨停价 c，卖出规则各口径，统一扣 0.2% 成本。

输出：data/limitup_exit_risk_20261019.txt
"""
import sys, os, csv
sys.path.insert(0, '/opt/data/fenjue/engine')
sys.path.insert(0, '/opt/data/python-libs')
import law_pipeline as lp
from collections import Counter, defaultdict

CSV_PATHS = [
    '/opt/data/fenjue/data/limit_up_mainboard_20250908_20260922.csv',
    '/opt/data/fenjue/data/limit_up_mainboard_20260923_20261019.csv',
]
OUT_PATH = '/opt/data/fenjue/data/limitup_exit_risk_20261019.txt'
COST = 0.2  # 单边综合成本 %


def parse_time(t):
    if not t or ':' not in t:
        return None
    try:
        h, m, s = map(int, t.split(':'))
        return h * 3600 + m * 60 + s
    except Exception:
        return None


def pf(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def stats(rets):
    if not rets:
        return 0, 0.0, 0.0, 0.0, 0.0
    n = len(rets)
    mean = sum(rets) / n
    win = sum(1 for x in rets if x > 0) / n * 100
    s = sorted(rets)
    med = s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2
    return n, mean, win, med, s[0]


def fmt_stats(rets):
    n, m, w, md, mn = stats(rets)
    return f'n={n:<5} mean={m:+.2f}% win={w:.1f}% med={md:+.2f}% min={mn:+.2f}%'


def main():
    U = lp.load_universe()

    rows = []
    for p in CSV_PATHS:
        with open(p, 'r', encoding='utf-8-sig') as f:
            rows.extend(csv.DictReader(f))

    records = []
    skipped_no_next = 0
    for r in rows:
        code = r['代码']
        if code not in U:
            continue
        date = r['日期']
        d = U[code]
        if date not in d['date']:
            continue
        idx = d['date'].index(date)
        if idx == 0:
            continue
        if idx + 1 >= len(d['date']):
            skipped_no_next += 1
            continue

        tsec = parse_time(r['首次封板时间'])
        if tsec is None:
            continue
        zhaban = 0 if r['炸板次数'] == '' else int(r['炸板次数'])
        fengdan_ratio = pf(r['封单额/流通市值(%)'])
        float_mv = pf(r['流通市值(亿元)'])      # 亿元
        turnover = pf(r['换手率(%)'])
        lb = 0 if r['连板数'] in ('', None) else int(r['连板数'])

        o0, h0, l0, c0 = d['o'][idx], d['h'][idx], d['l'][idx], d['c'][idx]
        pc0 = d['c'][idx - 1]  # 前收
        # 当日一字板（全天最低价 >= 收盘价×0.999）
        yizi = (l0 >= c0 * 0.999)
        # 当日成交额（kcache，前复权量价 → 近似真实成交额）
        amt0 = d['v'][idx] * c0

        # 次日数据
        o1, h1, l1, c1 = d['o'][idx+1], d['h'][idx+1], d['l'][idx+1], d['c'][idx+1]
        has_t2 = idx + 2 < len(d['date'])
        o2 = d['o'][idx+2] if has_t2 else None

        # 次日跌停价（主板 ±10%，前收为 c0；前复权口径下直接用 0.9 倍）
        limit_dn1 = round(c0 * 0.9, 4)
        # 一字跌停：次日 o==h==l==c 且跌幅 <= -9.5%（容忍复权/四舍五入）
        yizi_dn = (abs(o1 - h1) < 1e-6 and abs(h1 - l1) < 1e-6
                   and abs(l1 - c1) < 1e-6 and (o1 / c0 - 1) <= -0.095)
        # 次日开盘即跌停卖不掉：开盘价 <= 跌停价×1.001（容忍 0.1%）
        open_at_limitdn = o1 <= limit_dn1 * 1.001
        # 次日盘中曾触及跌停
        touch_limitdn = l1 <= limit_dn1 * 1.001

        # 收益口径（买在 c0，扣 0.2%）
        ret_open = (o1 / c0 - 1) * 100 - COST
        ret_high = (h1 / c0 - 1) * 100 - COST   # 乐观上限：卖在次日最高价
        ret_close = (c1 / c0 - 1) * 100 - COST
        ret_t2open = ((o2 / c0 - 1) * 100 - COST) if has_t2 else None
        # 次日开盘跌停卖不掉：顺延到次日收盘卖
        ret_close_if = ret_close if open_at_limitdn else None
        # 再卖不掉（次日一字跌停）：顺延到 T+2 开盘
        ret_t2_if = ret_t2open if (yizi_dn and has_t2) else None

        # 开盘价在次日振幅中的分位：(o1 - l1) / (h1 - l1)，1 = 开在最高点
        pos_pct = ((o1 - l1) / (h1 - l1)) if h1 > l1 else None

        # 可成交性指标：当日成交额 / 流通市值
        amt_ratio = (amt0 / (float_mv * 1e8) * 100) if (float_mv and float_mv > 0) else None

        strict = (tsec <= 10 * 3600 and fengdan_ratio is not None
                  and fengdan_ratio > 1.0 and zhaban == 0)
        executable = (tsec <= 10 * 3600 and fengdan_ratio is not None
                      and fengdan_ratio < 1.0 and zhaban >= 1 and not yizi)

        records.append({
            'code': code, 'date': date, 'tsec': tsec, 'zhaban': zhaban,
            'fengdan_ratio': fengdan_ratio, 'float_mv': float_mv, 'lb': lb,
            'turnover': turnover, 'amt_ratio': amt_ratio, 'yizi': yizi,
            'yizi_dn': yizi_dn, 'open_at_limitdn': open_at_limitdn,
            'touch_limitdn': touch_limitdn,
            'next_open_pct': (o1 / c0 - 1) * 100,
            'ret_open': ret_open, 'ret_high': ret_high, 'ret_close': ret_close,
            'ret_t2open': ret_t2open, 'ret_close_if': ret_close_if,
            'ret_t2_if': ret_t2_if, 'pos_pct': pos_pct,
            'strict': strict, 'executable': executable,
        })

    out = []
    w = out.append
    w('=' * 78)
    w('打板卖出端风险四项测试')
    w('数据：涨停池 15442+569 行 vs law_pipeline 前复权日线（kcache 至 2026-10-16）')
    w(f'有效样本 {len(records)} 条（无次日数据跳过 {skipped_no_next} 条，属 10-15 后样本）')
    w('口径：买在涨停价 c0，卖出见各任务，统一扣 0.2%；跌停判定=开盘<=前收×0.9×1.001')
    w('=' * 78)
    w('')

    # 三个样本组
    groups = {
        '全体': records,
        '严格档(首封<=10:00+封单>1%+炸板0)': [r for r in records if r['strict']],
        '可执行档(炸板>=1+首封<=10:00+封单<1%+非一字)': [r for r in records if r['executable']],
    }

    # ===== 任务一：次日开盘能不能卖掉 =====
    w('=' * 78)
    w('【任务一】次日开盘能不能卖掉')
    w('-' * 78)
    w(f'{"分组":<34}{"n":>6}{"开盘跌停":>9}{"一字跌停":>9}{"低开>5%":>9}{"盘中触跌停":>11}')
    for name, grp in groups.items():
        n = len(grp)
        if n == 0:
            continue
        n_open_dn = sum(1 for r in grp if r['open_at_limitdn'])
        n_yizi_dn = sum(1 for r in grp if r['yizi_dn'])
        n_low5 = sum(1 for r in grp if r['next_open_pct'] <= -5)
        n_touch = sum(1 for r in grp if r['touch_limitdn'])
        w(f'{name:<34}{n:>6}{n_open_dn / n * 100:>8.2f}%{n_yizi_dn / n * 100:>8.2f}%'
          f'{n_low5 / n * 100:>8.2f}%{n_touch / n * 100:>10.2f}%')
    w('')
    w('开盘卖不掉的后果（仅统计开盘跌停样本，顺延卖出）：')
    w(f'{"分组":<34}{"情形":<16}{"n":>5}  {"收益"}')
    for name, grp in groups.items():
        stuck = [r for r in grp if r['open_at_limitdn']]
        r_close = [r['ret_close'] for r in stuck]
        stuck_yizi = [r for r in stuck if r['yizi_dn']]
        r_t2 = [r['ret_t2open'] for r in stuck_yizi if r['ret_t2open'] is not None]
        if stuck:
            w(f'{name:<34}{"顺延收盘卖":<16}{len(r_close):>5}  {fmt_stats(r_close)}')
            w(f'{name:<34}{"一字跌停→T+2卖":<16}{len(r_t2):>5}  {fmt_stats(r_t2)}')
    w('')
    # 修正后的期望收益：开盘能卖的按开盘卖，卖不掉的顺延收盘
    w('修正后期望收益（开盘跌停者顺延收盘卖；一字跌停者顺延T+2开盘卖）：')
    for name, grp in groups.items():
        fixed = []
        for r in grp:
            if r['yizi_dn'] and r['ret_t2open'] is not None:
                fixed.append(r['ret_t2open'])
            elif r['open_at_limitdn']:
                fixed.append(r['ret_close'])
            else:
                fixed.append(r['ret_open'])
        naive = [r['ret_open'] for r in grp]
        w(f'  {name}')
        w(f'    理想(都能开盘卖): {fmt_stats(naive)}')
        w(f'    修正(卖不掉顺延): {fmt_stats(fixed)}')
    w('')

    # ===== 任务二：成交额/流通市值 反推可成交性 =====
    w('=' * 78)
    w('【任务二】当日成交额/流通市值 = 可成交性评分（值越大排队越容易成交）')
    w('-' * 78)
    exec_recs = [r for r in records if r['executable'] and r['amt_ratio'] is not None]
    exec_recs.sort(key=lambda r: r['amt_ratio'])
    n = len(exec_recs)
    w(f'可执行档有效 n={n}，按 成交额/流通市值(%) 分五档：')
    w(f'{"档位":<8}{"区间(%)":<16}{"n":>5}  {"次日开盘卖":<40}  {"次日收盘卖"}')
    qs = [exec_recs[int(n * q / 5): int(n * (q + 1) / 5)] for q in range(5)]
    for qi, grp in enumerate(qs):
        lo, hi = grp[0]['amt_ratio'], grp[-1]['amt_ratio']
        ro = [r['ret_open'] for r in grp]
        rc = [r['ret_close'] for r in grp]
        dn = sum(1 for r in grp if r['open_at_limitdn']) / len(grp) * 100
        w(f'Q{qi + 1}({"低" if qi == 0 else "高" if qi == 4 else ""})    '
          f'{lo:>6.2f}-{hi:<6.2f}{len(grp):>5}  {fmt_stats(ro)}  开盘跌停率{dn:.1f}%')
    w('')
    # 相关性
    xs = [r['amt_ratio'] for r in exec_recs]
    ys = [r['ret_open'] for r in exec_recs]
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    corr = cov / (vx * vy) ** 0.5 if vx > 0 and vy > 0 else 0
    w(f'成交额/流通市值 与次日开盘收益的 Pearson 相关: {corr:+.3f}')
    w('解读：实际为负相关——当日成交额/流通市值越大，次日收益越差、开盘跌停率越高。')
    w('即"封板后还能放出巨量"不是排队容易成交，而是分歧大/板上被砸，是负面信号。')
    w('反向使用：成交额/流通市值 <4%（Q1档）才是既买得到又赚得动的区间。')
    w('')

    # ===== 任务三：开盘卖 vs 盘中卖 =====
    w('=' * 78)
    w('【任务三】四种卖出时点对比（可执行档）')
    w('-' * 78)
    grp = groups['可执行档(炸板>=1+首封<=10:00+封单<1%+非一字)']
    w(f'{"卖出时点":<22}{"收益"}')
    w(f'{"次日开盘卖":<22}{fmt_stats([r["ret_open"] for r in grp])}')
    w(f'{"次日最高价卖(乐观上限)":<22}{fmt_stats([r["ret_high"] for r in grp])}')
    w(f'{"次日收盘卖":<22}{fmt_stats([r["ret_close"] for r in grp])}')
    t2 = [r['ret_t2open'] for r in grp if r['ret_t2open'] is not None]
    w(f'{"T+2开盘卖":<22}{fmt_stats(t2)}')
    w('')
    # 开盘价在次日振幅中的分位
    pos = sorted(r['pos_pct'] for r in grp if r['pos_pct'] is not None)
    npos = len(pos)
    def qtile(p):
        return pos[min(npos - 1, int(npos * p))]
    w(f'开盘价在次日振幅中的分位 (o-l)/(h-l)，1.0=开在全天最高：')
    w(f'  均值 {sum(pos)/npos:.3f}，中位 {qtile(0.5):.3f}，'
      f'25%分位 {qtile(0.25):.3f}，75%分位 {qtile(0.75):.3f}')
    pct_top20 = sum(1 for x in pos if x >= 0.8) / npos * 100
    pct_top50 = sum(1 for x in pos if x >= 0.5) / npos * 100
    pct_bot20 = sum(1 for x in pos if x <= 0.2) / npos * 100
    w(f'  开在振幅上 20% 区间的比例: {pct_top20:.1f}%；开在上半区: {pct_top50:.1f}%；'
      f'开在下 20%: {pct_bot20:.1f}%')
    w('')

    # ===== 任务四：连亏风险 =====
    w('=' * 78)
    w('【任务四】按日组合的连亏风险（可执行档，每日等权组合，按开盘卖+顺延修正）')
    w('-' * 78)
    by_day = defaultdict(list)
    for r in grp:
        if r['yizi_dn'] and r['ret_t2open'] is not None:
            ret = r['ret_t2open']
        elif r['open_at_limitdn']:
            ret = r['ret_close']
        else:
            ret = r['ret_open']
        by_day[r['date']].append(ret)
    days = sorted(by_day)
    day_ret = {d: sum(v) / len(v) for d, v in by_day.items()}
    day_list = [day_ret[d] for d in days]
    lose_days = [d for d in days if day_ret[d] <= 0]
    w(f'交易天数 {len(days)}，日均标的数 {sum(len(v) for v in by_day.values())/len(days):.1f}，'
      f'亏损天数占比 {len(lose_days)/len(days)*100:.1f}%')
    # 连续亏损天数分布
    streaks = []
    cur = 0
    for d in days:
        if day_ret[d] <= 0:
            cur += 1
        else:
            if cur > 0:
                streaks.append(cur)
            cur = 0
    if cur > 0:
        streaks.append(cur)
    sc = Counter(streaks)
    w(f'连续亏损天数分布: ' + ', '.join(f'{k}天×{sc[k]}次' for k in sorted(sc)))
    w(f'最大连续亏损天数: {max(streaks) if streaks else 0}')
    # 逐笔连亏（按时间顺序全部交易的连亏笔数）
    seq = []
    for d in days:
        seq.extend(by_day[d])
    max_ls, cur_ls = 0, 0
    for x in seq:
        if x <= 0:
            cur_ls += 1
            max_ls = max(max_ls, cur_ls)
        else:
            cur_ls = 0
    w(f'逐笔最大连续亏损笔数: {max_ls}')
    # 最差 5 天累计（滑动窗口）
    worst5 = None
    for i in range(len(days)):
        acc = 0
        for j in range(i, min(i + 5, len(days))):
            acc += day_list[j]
            if j - i == 4:
                if worst5 is None or acc < worst5[0]:
                    worst5 = (acc, days[i], days[j])
    # 最差单日
    worst_day = min(day_ret.items(), key=lambda kv: kv[1])
    w(f'最差单日组合收益: {worst_day[1]:+.2f}% ({worst_day[0]})')
    if worst5:
        w(f'最差连续 5 天累计: {worst5[0]:+.2f}% ({worst5[1]} ~ {worst5[2]})')
    # 最大回撤（按日累计净值，每天等权全仓）
    nav, peak, mdd = 1.0, 1.0, 0.0
    for d in days:
        nav *= (1 + day_ret[d] / 100)
        peak = max(peak, nav)
        mdd = min(mdd, nav / peak - 1)
    w(f'按日等权全仓累计: 最大回撤 {mdd * 100:+.2f}%，终值 {nav:.3f}')
    w(f'本金测算: 若每日全仓等权，承受最差5天 {worst5[0]:+.2f}% 回撤，'
      f'10 万本金浮亏约 {-worst5[0] * 1000:.0f} 元；'
      f'要单周浮亏≤1 万需本金 ≤ {1e4 / (-worst5[0] / 100):.0f} 元')
    w('')

    text = '\n'.join(out)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        f.write(text)
    print(text)
    print(f'\n[saved] {OUT_PATH}')


if __name__ == '__main__':
    main()
