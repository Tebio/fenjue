#!/usr/bin/env python3
"""engine/crash_dip_sensitivity.py — 「极端崩盘日抄底」二维参数敏感性扫描

信号：当日跌停(≤-9.8%) 且 收盘≤MA60（主板）
执行：次日开盘买，T+H 收盘卖，扣双边 0.2%
任务：
  1. 门槛 N ∈ {20,30,40,50,60,80,100,150} × T+5：触发次数/年均/均收益/胜率/累计/年化/最大回撤/逐年明细
  2. 持有期 H ∈ {1,3,5,10,20} × 门槛 30/50
  3. 双口径：每笔均值 + 每日等权组合（信号日分组，组内等权）
  4. 现实约束（门槛50, T+5）：(a) 日限随机20只×200次  (b) 只买跌幅最深20只
产出：data/crash_dip_sensitivity_20261019.txt
"""
import json, math, random, statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
OUT = ROOT / "data/crash_dip_sensitivity_20261019.txt"
FEE = 0.002  # 双边合计扣 0.2%

import sys
sys.path.insert(0, "/opt/data/fenjue/engine")
sys.path.insert(0, "/opt/data/python-libs")
import law_pipeline as lp


def collect_signals(U):
    """返回 sigs_by_date: {date: [(code, i)]}，信号=当日跌≤-9.8% 且 收盘≤MA60"""
    sigs = defaultdict(list)
    for code, d in U.items():
        c, ma, dates, n = d["c"], d["ma60"], d["date"], d["n"]
        for i in range(1, n):
            if ma[i] is None:
                continue
            ret = c[i] / c[i - 1] - 1.0
            if ret <= -0.098 and c[i] <= ma[i]:
                sigs[dates[i]].append((code, i))
    return dict(sigs)


def trade_ret(d, i, H):
    """次日开盘买，i+1+H 收盘卖；越界返回 None"""
    n = d["n"]
    if i + 1 + H >= n:
        return None
    entry = d["o"][i + 1]
    exitp = d["c"][i + 1 + H]
    if entry <= 0:
        return None
    return exitp / entry - 1.0 - FEE


def run_grid(U, sigs, threshold, H):
    """返回 trades=[(date, ret)]，每日等权日收益 dict"""
    trades = []
    daily = defaultdict(list)
    for date, lst in sigs.items():
        if len(lst) < threshold:
            continue
        for code, i in lst:
            r = trade_ret(U[code], i, H)
            if r is not None:
                trades.append((date, r))
                daily[date].append(r)
    daily_ret = {d: sum(v) / len(v) for d, v in daily.items()}
    return trades, daily_ret


def yearly_stats(trades):
    by_year = defaultdict(list)
    for date, r in trades:
        by_year[date[:4]].append(r)
    return {y: (len(v), sum(v) / len(v)) for y, v in sorted(by_year.items())}


def yearly_daily(daily_ret):
    by_year = defaultdict(list)
    for date, r in daily_ret.items():
        by_year[date[:4]].append(r)
    return {y: (len(v), sum(v) / len(v), sum(1 for x in v if x > 0) / len(v)) for y, v in sorted(by_year.items())}


def summarize(trades, daily_ret, label, lines):
    """trades=每笔口径, daily_ret=每日等权口径"""
    lines.append(f"\n--- {label} ---")
    if not trades:
        lines.append("  无触发")
        return
    # 每笔口径
    rets = [r for _, r in trades]
    n = len(rets)
    mean_r = sum(rets) / n
    win = sum(1 for r in rets if r > 0) / n
    worst, best = min(rets), max(rets)
    lines.append(f"  [每笔口径] 触发{len(set(d for d,_ in trades))}日 {n}笔 | 均 {mean_r*100:+.2f}% | 胜率 {win*100:.1f}% | 最差 {worst*100:+.2f}% | 最好 {best*100:+.2f}%")
    ys = yearly_stats(trades)
    ys_s = " ".join(f"{y}:{m*100:+.1f}%" for y, (c, m) in ys.items())
    lines.append(f"    逐年均收益: {ys_s}")

    # 每日等权口径：日收益序列按日期排序，复利累计
    dates = sorted(daily_ret)
    nav, peak, mdd = 1.0, 1.0, 0.0
    for d in dates:
        nav *= 1.0 + daily_ret[d]
        peak = max(peak, nav)
        mdd = min(mdd, nav / peak - 1.0)
    cum = nav - 1.0
    # 年化：按 8 年区间（用实际首末日期）
    y0, y1 = int(dates[0][:4]), int(dates[-1][:4])
    years = max(y1 - y0 + 1, 1)
    ann = (1.0 + cum) ** (1.0 / 8.0) - 1.0  # 项目惯例：8年
    dmean = sum(daily_ret.values()) / len(dates)
    dwin = sum(1 for v in daily_ret.values() if v > 0) / len(dates)
    lines.append(f"  [每日等权] 触发{len(dates)}日(年均{len(dates)/8.0:.1f}) | 日均 {dmean*100:+.2f}% | 日胜率 {dwin*100:.1f}% | 8年累计 {cum*100:+.1f}% | 年化 {ann*100:+.1f}% | 最大回撤 {mdd*100:.1f}%")
    yd = yearly_daily(daily_ret)
    yd_s = " ".join(f"{y}:{m*100:+.1f}%({'赚' if m>0 else '亏'})" for y, (c, m, w) in yd.items())
    lines.append(f"    逐年日均: {yd_s}")
    return cum, ann, mdd


def main():
    random.seed(42)
    U = lp.load_universe()
    lines = []
    lines.append(f"极端崩盘日抄底 参数敏感性扫描 | 样本={len(U)}只 | 信号=跌停(≤-9.8%)且收盘≤MA60 | 次日开盘买 T+H收盘卖 费0.2%")
    lines.append(f"数据区间: 2019-01 ~ 2026-10-16 (前复权主板)")

    sigs = collect_signals(U)
    total_days = len(sigs)
    lines.append(f"有信号的交易日总数: {total_days} (信号数分布: min={min(len(v) for v in sigs.values())}, max={max(len(v) for v in sigs.values())})")

    # ====== 维度1：门槛 ======
    lines.append("\n" + "=" * 80)
    lines.append("维度1：信号数门槛敏感性 (持有期 T+5)")
    lines.append("=" * 80)
    thresh_results = {}
    for N in [20, 30, 40, 50, 60, 80, 100, 150]:
        trades, daily_ret = run_grid(U, sigs, N, 5)
        thresh_results[N] = summarize(trades, daily_ret, f"门槛 N≥{N}", lines)

    # 断崖检测
    lines.append("\n  [断崖检测] 门槛 40/50/60 相邻对比（每日等权 年化）:")
    for N in [40, 50, 60]:
        if thresh_results.get(N):
            lines.append(f"    N={N}: 累计 {thresh_results[N][0]*100:+.1f}% 年化 {thresh_results[N][1]*100:+.1f}% 回撤 {thresh_results[N][2]*100:.1f}%")

    # ====== 维度2：持有期 ======
    lines.append("\n" + "=" * 80)
    lines.append("维度2：持有期敏感性 (门槛 30 和 50)")
    lines.append("=" * 80)
    hold_results = {}
    for N in [30, 50]:
        for H in [1, 3, 5, 10, 20]:
            trades, daily_ret = run_grid(U, sigs, N, H)
            hold_results[(N, H)] = summarize(trades, daily_ret, f"门槛 N≥{N} 持有 T+{H}", lines)

    # ====== 维度3：现实约束（门槛50, T+5）======
    lines.append("\n" + "=" * 80)
    lines.append("维度3：现实约束 (门槛50, T+5)")
    lines.append("=" * 80)
    N, H = 50, 5
    # 符合条件的信号日
    days = {d: lst for d, lst in sigs.items() if len(lst) >= N}
    lines.append(f"触发日: {len(days)} 天, 平均信号数 {sum(len(v) for v in days.values())/len(days):.0f}")

    # (a) 日限随机20只 × 200 次
    rng = random.Random(42)
    cum_list, ann_list = [], []
    for trial in range(200):
        daily_ret = {}
        for d, lst in days.items():
            pick = rng.sample(lst, min(20, len(lst)))
            rs = [trade_ret(U[c], i, H) for c, i in pick]
            rs = [r for r in rs if r is not None]
            if rs:
                daily_ret[d] = sum(rs) / len(rs)
        if not daily_ret:
            continue
        nav = 1.0
        for d in sorted(daily_ret):
            nav *= 1.0 + daily_ret[d]
        cum = nav - 1.0
        cum_list.append(cum)
        ann_list.append((1 + cum) ** (1 / 8.0) - 1.0)
    cum_list.sort()
    lines.append(f"\n  (a) 日限随机20只 ×200次:")
    lines.append(f"    8年累计: 均值 {st.mean(cum_list)*100:+.1f}% | 中位 {st.median(cum_list)*100:+.1f}% | P5 {cum_list[10]*100:+.1f}% | P95 {cum_list[190]*100:+.1f}%")
    lines.append(f"    年化:    均值 {st.mean(ann_list)*100:+.1f}%")
    full_cum = thresh_results[50][0]
    lines.append(f"    对比「买全部」累计 {full_cum*100:+.1f}% → 损失 {(full_cum - st.mean(cum_list))*100:+.1f} 个百分点 ({(1-st.mean(cum_list)/full_cum)*100:.0f}%)")

    # (b) 只买当天跌幅最深20只
    daily_ret_b = {}
    for d, lst in days.items():
        # 按信号日跌幅排序（c[i]/c[i-1]-1 最小者）
        scored = []
        for code, i in lst:
            day_ret = U[code]["c"][i] / U[code]["c"][i - 1] - 1.0
            scored.append((day_ret, code, i))
        scored.sort()
        rs = [trade_ret(U[c], i, H) for _, c, i in scored[:20]]
        rs = [r for r in rs if r is not None]
        if rs:
            daily_ret_b[d] = sum(rs) / len(rs)
    nav, peak, mdd = 1.0, 1.0, 0.0
    for d in sorted(daily_ret_b):
        nav *= 1.0 + daily_ret_b[d]
        peak = max(peak, nav)
        mdd = min(mdd, nav / peak - 1.0)
    cum_b = nav - 1.0
    ann_b = (1 + cum_b) ** (1 / 8.0) - 1.0
    lines.append(f"\n  (b) 只买当天跌幅最深20只:")
    lines.append(f"    8年累计 {cum_b*100:+.1f}% | 年化 {ann_b*100:+.1f}% | 最大回撤 {mdd*100:.1f}%")
    lines.append(f"    对比「买全部」累计 {full_cum*100:+.1f}% → 损失 {(full_cum-cum_b)*100:+.1f} 个百分点")

    # ====== 结论 ======
    lines.append("\n" + "=" * 80)
    lines.append("结论")
    lines.append("=" * 80)
    txt = "\n".join(lines)
    OUT.write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
