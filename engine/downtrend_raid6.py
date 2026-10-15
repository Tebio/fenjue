#!/usr/bin/env python3
"""engine/downtrend_raid6.py — 下跌中继突袭：日级配对边际 + 抱团日归因 + G7 容量（stage 6）

stage5 发现正超额**全部**来自 62 个抱团日（K>=15），且事件加权会骗人（几个超大日主导）。
本版做三件不骗人的事：
  ① 日级配对边际：逐日算「事件股均值 − 同语境非事件股均值」，对**日序列**做 NW t
     （事件加权 = 100 个同日样本当独立，是双重计数；日序列才是真样本量 62）
  ② 抱团日归因：把每个抱团日对总超额日数/-幅度排序，看是不是 2024/2026 几次踩踏包办
  ③ G7 容量：槽位 10、hold 5，cluster_k=1（无条件）vs cluster_k=15（只在抱团日出手）
"""
import json
import math
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

    # ===== ① 日级配对边际（真 t）=====
    print("\n=== ① 日级配对边际 = 逐日(事件股均值 − 同语境非事件股均值)，对日序列 NW t ===")
    R1 = {}
    for scope, dts in (("全事件日", sorted(byd)), ("仅抱团日K>=15", sorted(dt for dt in byd if kday[dt] >= 15)),
                       ("仅非抱团日K<15", sorted(dt for dt in byd if kday[dt] < 15))):
        R1[scope] = {}
        print("  [%s] n_days=%d" % (scope, len(dts)))
        for h in HS:
            ser = []
            for dt in dts:
                if dt not in ctxm[h]:
                    continue
                rs = [fwd(stocks[e["code"]], e["i"], h) for e in byd[dt]]
                rs = [r for r in rs if r is not None]
                if not rs:
                    continue
                ser.append(st.mean(rs) - ctxm[h][dt])
            if len(ser) < 30:
                print("    T+%-3d 天数不足(%d)" % (h, len(ser)))
                continue
            s = stats(ser)
            t_nw = lp.nw_t(ser, h)
            sr = st.mean(ser) / st.stdev(ser) * 244 ** 0.5 if st.stdev(ser) > 0 else 0
            R1[scope]["T+%d" % h] = {"天数": len(ser), "日均边际%": s["mean%"], "日胜率%": s["win%"],
                                     "中位%": s["med%"], "t_朴素": s["t"], "t_NW": t_nw, "Sharpe": round(sr, 2)}
            print("    T+%-3d 天数=%4d 日均边际=%+6.3f%% 日胜率=%5.1f%% 中位=%+6.2f%% t_朴素=%5s t_NW=%5s Sharpe=%5s" % (
                h, len(ser), s["mean%"], s["win%"], s["med%"], s["t"], t_nw, round(sr, 2)), flush=True)

    # ===== ② 抱团日归因 =====
    print("\n=== ② 抱团日归因（对当日全市场超额，T+5） ===")
    rows = []
    for dt in sorted(dt for dt in byd if kday[dt] >= 15):
        rs = [fwd(stocks[e["code"]], e["i"], 5) for e in byd[dt]]
        rs = [r for r in rs if r is not None]
        ex = st.mean(rs) - allm[5].get(dt, 0)
        rows.append((dt, kday[dt], round(100 * ex, 2), round(100 * ex * len(rs))))
    rows.sort(key=lambda x: -x[3])
    tot = sum(r[3] for r in rows)
    cum = 0
    for dt, k, ex, contrib in rows[:12]:
        cum += contrib
        print("  %s K=%3d 日超额=%+7.2f%% 加权贡献=%+9.1fpp 累计占比=%5.1f%%" % (
            dt, k, ex, contrib, 100 * cum / tot if tot else 0), flush=True)
    yr_c = defaultdict(float); yr_n = defaultdict(int)
    for dt, k, ex, contrib in rows:
        yr_c[dt[:4]] += contrib; yr_n[dt[:4]] += 1
    print("  按年: " + "  ".join("%s 日数=%d 贡献=%+.0fpp" % (y, yr_n[y], yr_c[y]) for y in sorted(yr_c)), flush=True)

    # ===== ③ G7 容量 =====
    print("\n=== ③ G7 容量（槽10, hold 5, seeds 5） ===")
    sigs = defaultdict(list)
    for e in ev:
        sigs[e["date"]].append((e["code"], e["i"]))
    print("  信号日数=%d 总信号=%d" % (len(sigs), sum(len(v) for v in sigs.values())), flush=True)
    R3 = {}
    for k in (1, 15, 30):
        r = lp.capacity_sim(dict(sigs), stocks, slots=10, hold=5, seeds=5, cluster_k=k)
        R3["cluster_k=%d" % k] = r
        print("  cluster_k=%-3d %s" % (k, json.dumps(r, ensure_ascii=False)), flush=True)

    out = {"日级配对边际": R1, "抱团日归因": rows, "G7容量": R3}
    (ROOT / "data/downtrend_raid_stage6.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved stage6")


if __name__ == "__main__":
    main()
