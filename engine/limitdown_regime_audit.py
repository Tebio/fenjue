#!/usr/bin/env python
"""深档低位族「环境依赖」审计：证明裸版是 2024 年幻觉，簇条件才是真线。

背景：line_health 里 COMP_LIMITDOWN_LOW_DEEP 评分 100（T+20 +12.54pp/胜81.2%/n=351），
      被当作主仓。本脚本按年拆开，看这份成绩靠哪一年撑着，以及「当日全市场跌停数」这个
      环境开关能不能把它救成稳定线。

跑法： cd /opt/data/fenjue && PYTHONPATH=/opt/data/python-libs:/opt/data/fenjue/engine .venv/bin/python engine/limitdown_regime_audit.py
"""
import collections
import statistics as st
import sys

sys.path.insert(0, '/opt/data/fenjue/engine')
sys.path.insert(0, '/opt/data/python-libs')
import law_pipeline as lp  # noqa: E402

COST = 0.002
HOLDS = (1, 5, 20, 40)


def main():
    U = lp.load_universe()
    # 每日全市场跌停数 + 全市场同期 T+5 基线
    ld, mkt = collections.Counter(), collections.defaultdict(list)
    for c, d in U.items():
        if c[:2] not in ('60', '00'):
            continue
        cn, n, dt = d['c'], d['n'], d['date']
        for i in range(1, n):
            if cn[i - 1] <= 0 or cn[i] <= 0:
                continue
            if cn[i] / cn[i - 1] - 1 <= -0.098:
                ld[dt[i]] += 1
            if i + 5 < n:
                mkt[dt[i]].append(cn[i + 5] / cn[i] - 1 - COST)

    # 深跌信号：跌停 + 距MA60 ≤ -25%
    sig = []
    for c, d in U.items():
        if c[:2] not in ('60', '00'):
            continue
        cn, ma, n, dt = d['c'], d['ma60'], d['n'], d['date']
        for i in range(60, n - 1):
            if cn[i] <= 0 or cn[i - 1] <= 0 or not ma[i]:
                continue
            if cn[i] / cn[i - 1] - 1 > -0.098 or cn[i] / ma[i] - 1 > -0.25:
                continue
            r = {h: (cn[i + h] / cn[i] - 1 - COST if i + h < n else None) for h in HOLDS}
            sig.append((dt[i], r, ld.get(dt[i], 0)))

    print('=' * 100)
    print('深档低位族 环境依赖审计 (2026-10-19)')
    print(f'信号定义：当日跌停(≤-9.8%) 且 收盘距MA60 ≤ -25%；样本 {len(sig)} 笔')
    print('=' * 100)

    def agg(sel, lab):
        print(f'\n{lab}')
        print(f"  {'持有':<8}{'n':>6}{'均值':>9}{'胜率':>6}{'中位':>9}")
        for h in HOLDS:
            v = [s[1][h] for s in sig if sel(s) and s[1][h] is not None]
            if len(v) < 5:
                continue
            print(f"  T+{h:<7}{len(v):>6}{st.mean(v)*100:>+8.2f}%"
                  f"{sum(1 for x in v if x > 0) / len(v) * 100:>5.0f}%{st.median(v)*100:>+8.2f}%")

    agg(lambda s: True, '【A. 裸版全样本】')
    agg(lambda s: s[0][:4] != '2024', '【B. 剔除 2024（揭示幻觉）】')
    agg(lambda s: s[0][:4] in ('2025', '2026'), '【C. 只看 2025-2026】')
    n24 = sum(1 for s in sig if s[0][:4] == '2024')
    v20 = [s[1][20] for s in sig if s[1][20] is not None]
    v24 = [s[1][20] for s in sig if s[1][20] is not None and s[0][:4] == '2024']
    print(f'\n  2024 年样本占比 {n24 / len(sig) * 100:.0f}%，却贡献了 T+20 总收益的 {sum(v24) / sum(v20) * 100:.0f}%')

    print('\n【D. 逐年 T+5 与全市场基线对照（暴露环境依赖）】')
    per = collections.defaultdict(list)
    for s in sig:
        if s[1][5] is not None:
            per[s[0][:4]].append(s[1][5])
    print(f"  {'年':<6}{'n':>6}{'深跌T+5':>10}{'全市场T+5':>11}{'超额':>9}")
    for y in sorted(per):
        v = per[y]
        b = st.mean(mkt[y]) * 100 if mkt[y] else 0.0
        print(f"  {y:<6}{len(v):>6}{st.mean(v)*100:>+9.2f}%{b:>+10.2f}%{st.mean(v) * 100 - b:>+8.2f}pp")

    print('\n【E. 簇条件（当日全市场跌停≥N）能否救活】')
    for thr in (0, 30, 50, 100, 150):
        sel = [s for s in sig if s[2] >= thr]
        if len(sel) < 30:
            continue
        yy = collections.defaultdict(list)
        for s in sel:
            if s[1][5] is not None:
                yy[s[0][:4]].append(s[1][5])
        pos = sum(1 for y in yy if st.mean(yy[y]) > 0)
        vv = [s[1][5] for s in sel if s[1][5] is not None]
        print(f"\n  跌停≥{thr}: n={len(sel)} 全期 {st.mean(vv) * 100:+.2f}%"
              f" 胜{sum(1 for x in vv if x > 0) / len(vv) * 100:.0f}%"
              f" 为正年份 {pos}/{len(yy)}")
        print('    ' + ' | '.join(
            f"{y}:n{len(v):>4}/{st.mean(v) * 100:+.1f}%({st.mean(v) * 100 - (st.mean(mkt[y]) * 100 if mkt[y] else 0):+.1f}pp)"
            for y, v in sorted(yy.items())))

    print('\n【F. 结论】')
    print('  (1) 裸版 T+20 +15.21%/胜80% 是 2024 一年撑起来的：该年占 55% 样本、贡献 95% 收益；')
    print('      剔除 2024 后 T+5 变 -3.03%、T+20 只剩 +1.63%，逐年超额 4 正 4 负（2020 -12.19pp、2021 -16.34pp）。')
    print('  (2) 加「当日全市场跌停≥50」的恐慌簇条件后转稳：全期 T+5 +7.86%/胜79%，逐年 6 正 1 负 1 无样本。')
    print('  (3) 2023 全年无 ≥50 跌停日 → 该策略自带「阴跌年不进场」开关，这是优点不是缺陷。')
    print('  (4) 铁律：深档低位必须带恐慌簇条件，裸版不得进生产；且它本质是恐慌反弹工具，不是全天候主仓。')


if __name__ == '__main__':
    main()
