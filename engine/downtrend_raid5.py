#!/usr/bin/env python3
"""engine/downtrend_raid5.py — 下跌中继突袭：同日内对照终审（stage 5）

stage4 揭示：事件极度抱团在 62 个「K>=15」的日子（4620/6353=73% 的事件），
日历时间等权法（每事件日 1 票）给 T+5 日均超额 -1.02%/t_NW -3.2 —— 与事件加权 +1.22% 反号。

本版把事情钉死在同一日横截面里：
  ① 列出全部抱团日（日期、K、该日事件组 T+1/5/20 超额）
  ② 同日内三组对照：全市场当日 / 当日「MA60下方且MA60下行」非事件股 / 当日无大涨的同语境股
  ③ 抱团日 vs 非抱团日的日历时间结论分开报
  ④ 逐年抱团日分布（识别是不是全靠 2024 一段行情）
"""
import json
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp
from downtrend_raid import (ROOT, load_compact, collect, fwd, stats, raid_big7, START, FEE)

HS = [1, 5, 20]
DET = raid_big7


def main():
    stocks, cal = load_compact()
    print("stocks:", len(stocks), flush=True)

    # 逐日：全市场均值 + 同语境（MA60下方且MA60下行）非事件股均值
    all_sum = {h: defaultdict(float) for h in HS}; all_cnt = {h: defaultdict(int) for h in HS}
    ctx_sum = {h: defaultdict(float) for h in HS}; ctx_cnt = {h: defaultdict(int) for h in HS}
    for code, d in stocks.items():
        c, o, ma, n = d["c"], d["o"], d["ma60"], d["n"]
        for i in range(START, n - max(HS) - 1):
            ep = o[i + 1]
            if ep <= 0:
                continue
            dt = d["date"][i]
            r0 = c[i - 1] > 0 and (c[i] / c[i - 1] - 1 >= 0.07)
            ctx = (ma[i] is not None and ma[i - 5] is not None and ma[i] < ma[i - 5]
                   and c[i] <= ma[i])
            for h in HS:
                r = c[i + h] / ep - 1 - FEE
                all_sum[h][dt] += r; all_cnt[h][dt] += 1
                if ctx and not r0:
                    ctx_sum[h][dt] += r; ctx_cnt[h][dt] += 1
    allm = {h: {dt: all_sum[h][dt] / all_cnt[h][dt] for dt in all_sum[h]} for h in HS}
    ctxm = {h: {dt: ctx_sum[h][dt] / ctx_cnt[h][dt] for dt in ctx_sum[h]} for h in HS}
    print("daily means done", flush=True)

    ev = collect(stocks, xs=None, det=DET)
    byd = defaultdict(list)
    for e in ev:
        byd[e["date"]].append(e)
    kday = {dt: len(v) for dt, v in byd.items()}
    print("events:", len(ev), "days:", len(byd), flush=True)

    # ===== ① 抱团日清单 =====
    big = sorted([dt for dt, k in kday.items() if k >= 15])
    print("\n=== ① 抱团日（K>=15）清单 n=%d 日 ===" % len(big))
    rows = []
    for dt in big:
        es = byd[dt]
        ex = {}
        for h in HS:
            rs = [fwd(stocks[e["code"]], e["i"], h) for e in es]
            rs = [r for r in rs if r is not None]
            ex["T+%d" % h] = round(100 * (st.mean(rs) - allm[h].get(dt, 0)), 2) if rs else None
        rows.append({"date": dt, "K": kday[dt], "ex": ex,
                     "ctx_ex_T5": round(100 * (st.mean([r for r in (fwd(stocks[e["code"]], e["i"], 5) for e in es) if r is not None]) - ctxm[5].get(dt, 0)), 2)})
        print("  %s K=%3d  ex T+1 %+6.2f  T+5 %+6.2f  T+20 %+6.2f  (对同语境股 T+5 %+6.2f)" % (
            dt, kday[dt], ex["T+1"] or 0, ex["T+5"] or 0, ex["T+20"] or 0, rows[-1]["ctx_ex_T5"]), flush=True)

    # ===== ② 抱团日 vs 非抱团日 分开的日历时间结论 =====
    print("\n=== ② 日历时间（分抱团日/非抱团日） ===")
    B = {}
    for tag, dts in (("抱团日(K>=15)", set(big)), ("非抱团日(K<15)", set(kday) - set(big))):
        B[tag] = {}
        for h in HS:
            ser = []
            for dt in sorted(dts):
                if dt not in allm[h]:
                    continue
                rs = [fwd(stocks[e["code"]], e["i"], h) for e in byd[dt]]
                rs = [r for r in rs if r is not None]
                if rs:
                    ser.append(st.mean(rs) - allm[h][dt])
            if len(ser) < 30:
                continue
            s = stats(ser)
            sr = st.mean(ser) / st.stdev(ser) * 244 ** 0.5 if st.stdev(ser) > 0 else 0
            B[tag]["T+%d" % h] = {"天数": len(ser), "日均超额%": s["mean%"], "日胜率%": s["win%"],
                                  "t_朴素": s["t"], "t_NW": lp.nw_t(ser, h), "Sharpe": round(sr, 2)}
            print("  %-14s T+%-3d 天数=%3d 日均=%+6.3f%% 日胜率=%5.1f%% t_朴素=%5s t_NW=%5s Sharpe=%s" % (
                tag, h, len(ser), s["mean%"], s["win%"], s["t"], lp.nw_t(ser, h), round(sr, 2)), flush=True)

    # ===== ③ 逐年抱团日 =====
    print("\n=== ③ 逐年：事件数 / 抱团日数 ===")
    yr = defaultdict(lambda: {"ev": 0, "days": 0, "bigdays": 0, "ex5": []})
    for dt, es in byd.items():
        y = dt[:4]
        yr[y]["ev"] += len(es); yr[y]["days"] += 1
        if kday[dt] >= 15:
            yr[y]["bigdays"] += 1
        rs = [fwd(stocks[e["code"]], e["i"], 5) for e in es]
        rs = [r for r in rs if r is not None]
        if rs:
            yr[y]["ex5"].append(st.mean(rs) - allm[5].get(dt, 0))
    Y = {}
    for y in sorted(yr):
        v = yr[y]
        Y[y] = {"事件": v["ev"], "事件日": v["days"], "抱团日": v["bigdays"],
                "日均超额T+5%": round(100 * st.mean(v["ex5"]), 2) if v["ex5"] else None}
        print("  %s 事件=%5d 事件日=%4d 抱团日=%3d 日级T+5超额=%+6.2f%%（%d 日）" % (
            y, v["ev"], v["days"], v["bigdays"], Y[y]["日均超额T+5%"] or 0, len(v["ex5"])), flush=True)

    # ===== ④ 抱团日的超额是不是「选票」还是「当天全市场都行」 =====
    print("\n=== ④ 抱团日：事件股 vs 同语境非事件股（同日配对） ===")
    D = {}
    for h in HS:
        ev_rs, ctx_rs = [], []
        for dt in big:
            if dt not in ctxm[h]:
                continue
            rs = [fwd(stocks[e["code"]], e["i"], h) for e in byd[dt]]
            rs = [r for r in rs if r is not None]
            if not rs:
                continue
            ev_rs += [st.mean(rs)] * len(rs)
            ctx_rs += [ctxm[h][dt]] * len(rs)
        s1, s2 = stats(ev_rs), stats(ctx_rs)
        D["T+%d" % h] = {"事件股": s1, "同语境非事件股": s2,
                         "配对边际pp": round(s1["mean%"] - s2["mean%"], 2) if s1 and s2 else None}
        print("  T+%-3d 事件股 %+6.2f%% (n=%d) vs 同语境非事件股 %+6.2f%%  边际 %+6.2fpp" % (
            h, s1["mean%"], s1["n"], s2["mean%"], D["T+%d" % h]["配对边际pp"]), flush=True)

    out = {"抱团日": rows, "日历时间分组": B, "逐年": Y, "抱团日配对": D}
    (ROOT / "data/downtrend_raid_stage5.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved stage5")


if __name__ == "__main__":
    main()
