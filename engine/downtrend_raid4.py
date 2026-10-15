#!/usr/bin/env python3
"""engine/downtrend_raid4.py — 下跌中继突袭：终审四件（stage 4）

修 stage3 缺陷：industry_map 的行业涨停梯队按 up 日历索引存、却按日期字符串查 → 全落 0，
本版统一按日期字符串存。

四件必查：
  A 逐年超额（治「全靠 2024 一段行情」——样本 50% 落在 2024）
  B 日历时间组合法（Fama-French；治同一天扎堆的横截面相关，给真 t_NW）
  C 簇剂量分解（K=当日全市场同族事件数，看是否只在成簇日有效）
  D 重叠审计（与 跌停次日接 / 深档(≤MA60×0.65) / T1-MEGA 的明确关系）
另 report 行业联动（修好后）与市值五分位已由 stage3 覆盖。
"""
import json
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp
from downtrend_raid import (ROOT, HORIZONS, load_compact, collect, fwd, stats,
                            raid_big7, raid_limitup, bottom_flush_big7, START,
                            downtrend_ctx, FEE)

HS = [1, 5, 20]
DET = raid_big7


def main():
    stocks, cal = load_compact()
    print("stocks:", len(stocks), flush=True)

    # ---- 全宇宙逐日横截面均值（按日 sum/count，避免 6×1.9M float list 爆内存）
    usum = {h: defaultdict(float) for h in HS}
    ucnt = {h: defaultdict(int) for h in HS}
    for code, d in stocks.items():
        c, o, n = d["c"], d["o"], d["n"]
        for i in range(START, n - max(HS) - 1):
            ep = o[i + 1]
            if ep <= 0:
                continue
            dt = d["date"][i]
            for h in HS:
                usum[h][dt] += c[i + h] / ep - 1 - FEE
                ucnt[h][dt] += 1
    uni = {h: {dt: usum[h][dt] / ucnt[h][dt] for dt in usum[h]} for h in HS}
    print("universe daily means done", flush=True)

    ev = collect(stocks, xs=None, det=DET)
    print("events:", len(ev), flush=True)

    # ============ A. 逐年超额 ============
    print("\n=== A 逐年超额（事件 - 同日全宇宙等权，pp） ===")
    A = {}
    for h in HS:
        by_y_raw = defaultdict(list)
        by_y_ex = defaultdict(list)
        for e in ev:
            r = fwd(stocks[e["code"]], e["i"], h)
            if r is None:
                continue
            y = e["date"][:4]
            by_y_raw[y].append(r)
            by_y_ex[y].append(r - uni[h].get(e["date"], 0.0))
        rows = {}
        line = "  T+%-3d" % h
        for y in sorted(by_y_raw):
            ex = by_y_ex[y]
            s = stats(ex)
            rows[y] = {"n": len(ex), "raw%": round(100 * st.mean(by_y_raw[y]), 2),
                       "ex%": s["mean%"] if s else None, "win_ex%": s["win%"] if s else None}
            line += "  %s n=%4d raw%+6.2f ex%+6.2f" % (y, len(ex), rows[y]["raw%"], rows[y]["ex%"] or 0)
        print(line, flush=True)
        A[f"T+{h}"] = rows

    # ============ B. 日历时间组合法（真 t_NW） ============
    print("\n=== B 日历时间组合法（事件日等权组合 - 同日全宇宙） ===")
    B = {}
    for h in HS:
        byd = defaultdict(list)
        for e in ev:
            r = fwd(stocks[e["code"]], e["i"], h)
            if r is not None:
                byd[e["date"]].append(r)
        dates = [dt for dt in sorted(byd) if dt in uni[h]]
        ser = [st.mean(byd[dt]) - uni[h][dt] for dt in dates]
        if len(ser) < 30:
            continue
        s = stats(ser)
        t_nw = lp.nw_t(ser, h)
        sr = (st.mean(ser) / st.stdev(ser) * (244 ** 0.5)) if st.stdev(ser) > 0 else 0
        B[f"T+{h}"] = {"天数": len(ser), "日均超额%": s["mean%"], "日胜率%": s["win%"],
                       "t_naive": s["t"], "t_NW": t_nw, "年化Sharpe": round(sr, 2)}
        print("  T+%-3d 天数=%4d 日均超额=%+6.3f%% 日胜率=%5.1f%%  t_朴素=%s  t_NW=%s  Sharpe=%s" % (
            h, len(ser), s["mean%"], s["win%"], s["t"], t_nw, round(sr, 2)), flush=True)

    # ============ C. 簇剂量分解（K=当日全市场同族事件数） ============
    print("\n=== C 簇剂量（K=当日 下跌中继大涨7 事件数） ===")
    kday = defaultdict(int)
    for e in ev:
        kday[e["date"]] += 1
    C = {}
    for h in HS:
        buckets = defaultdict(list)
        for e in ev:
            r = fwd(stocks[e["code"]], e["i"], h)
            if r is None:
                continue
            k = kday[e["date"]]
            key = "1" if k == 1 else ("2-4" if k < 5 else ("5-14" if k < 15 else ">=15"))
            buckets[key].append(r - uni[h].get(e["date"], 0.0))
        rows = {}
        line = "  T+%-3d" % h
        for key in ["1", "2-4", "5-14", ">=15"]:
            s = stats(buckets[key])
            if s:
                rows[key] = s
                line += "  K%-5s n=%4d %+6.2f%%/%5.1f%%" % (key, s["n"], s["mean%"], s["win%"])
        print(line, flush=True)
        C[f"T+{h}"] = rows
    kdist = defaultdict(int)
    for dt, k in kday.items():
        kdist["1" if k == 1 else ("2-4" if k < 5 else ("5-14" if k < 15 else ">=15"))] += 1
    print("  事件日 K 分布（日数）:", dict(kdist), flush=True)

    # ============ D. 重叠审计 ============
    print("\n=== D 重叠审计（同一事件被多少既有族命中） ===")
    def deep_dip(d, i):
        """深档低位v2 的条件：跌停 + 收≤MA60×0.65（生产规则 9/22 起）"""
        if i < 66:
            return False
        c, ma = d["c"], d["ma60"]
        if c[i - 1] <= 0 or ma[i] is None or ma[i] <= 0:
            return False
        ld = c[i - 1] / d["c"][i - 2] - 1 <= -0.095 if i >= 2 else False
        return ld and c[i] <= ma[i] * 0.65

    def limitdown_next(d, i):
        """跌停次日接_剔一字：信号日=跌停，入场日=次日"""
        if d["c"][i - 1] <= 0:
            return False
        return d["c"][i] / d["c"][i - 1] - 1 <= -0.095

    def t1_mega(d, i):
        """T1-MEGA 近似：跌停 + 缩量（vr<1，实际门槛另在大盘条件）"""
        if i < 70 or d["c"][i - 1] <= 0:
            return False
        if d["c"][i] / d["c"][i - 1] - 1 > -0.095:
            return False
        b = d["v"][i - 20:i]
        if not all(x > 0 for x in b):
            return False
        mb = sum(b) / 20
        return mb > 0 and d["v"][i] / mb < 1

    n = len(ev)
    hits = {"跌停日（=被跌停族/深档/T1-MEGA 覆盖）": 0, "深档低位v2（跌停+≤MA60×0.65）": 0,
            "T1-MEGA（跌停+缩量）": 0, "三者皆不命中": 0}
    for e in ev:
        d = stocks[e["code"]]
        a = limitdown_next(d, e["i"]); b = deep_dip(d, e["i"]); c = t1_mega(d, e["i"])
        if a:
            hits["跌停日（=被跌停族/深档/T1-MEGA 覆盖）"] += 1
        if b:
            hits["深档低位v2（跌停+≤MA60×0.65）"] += 1
        if c:
            hits["T1-MEGA（跌停+缩量）"] += 1
        if not (a or b or c):
            hits["三者皆不命中"] += 1
    D = {k: {"n": v, "占比%": round(100 * v / n, 1)} for k, v in hits.items()}
    print("  事件总数", n, json.dumps(D, ensure_ascii=False), flush=True)

    out = {"n_events": n, "A_逐年超额": A, "B_日历时间": B, "C_簇剂量": C, "D_重叠": D}
    (ROOT / "data/downtrend_raid_stage4.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1))
    print("saved stage4")


if __name__ == "__main__":
    main()
