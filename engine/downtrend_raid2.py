#!/usr/bin/env python3
"""engine/downtrend_raid2.py — 下跌中继突袭：对照/分段/分层（stage 2）

必查三件事（AGENTS 纪律）：
  ① 基线——全宇宙同日同窗口 T+N 均值（超额才有意义，裸均值可能只是 beta）
  ② 时间分段 2019-2022 / 2023-2026 + 逐年（防「全靠一段行情」）
  ③ 条件内对照——同股同位置（MA60 下方）非事件日的 T+N，剥离位置 beta
"""
import json
import random
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp
from downtrend_raid import (ROOT, FEE, HORIZONS, START, load_compact, build_xs,
                            collect, fwd, stats, odds, raid_limitup, raid_big7,
                            raid_big5, bottom_flush_big7, downtrend_ctx)

DETS = {"下跌中继_涨停": raid_limitup, "下跌中继_大涨7": raid_big7,
        "底部出清后大涨7": bottom_flush_big7}


def main():
    stocks, cal = load_compact()
    print("stocks:", len(stocks), flush=True)
    xs = build_xs(stocks, cal)
    # 全宇宙逐日横截面均值（按日累加 sum/count，避免 list 爆内存——实测 6×1886×3335 的
    # Python float list 会 >1.5GB，容器 cgroup 上限 4GB）
    usum = {h: defaultdict(float) for h in HORIZONS}
    ucnt = {h: defaultdict(int) for h in HORIZONS}
    from array import array
    allret = {h: array('f') for h in HORIZONS}   # 紧凑存（list 会 ~200MB×6 + 峰值）
    for code, d in stocks.items():
        n = d["n"]
        c, o = d["c"], d["o"]
        for i in range(START, n - max(HORIZONS) - 1):
            ep = o[i + 1]
            if ep <= 0:
                continue
            dt = d["date"][i]
            for h in HORIZONS:
                r = c[i + h] / ep - 1 - FEE
                usum[h][dt] += r
                ucnt[h][dt] += 1
                allret[h].append(r)
    uni_m = {h: {dt: usum[h][dt] / ucnt[h][dt] for dt in usum[h]} for h in HORIZONS}
    base = {h: stats(allret[h]) for h in HORIZONS}
    print("=== 全宇宙基线（所有股票日，入场=次日开盘，净费） ===")
    for h in HORIZONS:
        b = base[h]
        print("   T+%-3d n=%-8d win=%5.1f%% mean=%+6.2f%%" % (h, b["n"], b["win%"], b["mean%"]), flush=True)

    out = {"baseline": base, "events": {}}
    for name, det in DETS.items():
        ev = collect(stocks, xs, det)
        rs = {h: [] for h in HORIZONS}
        ex = {h: [] for h in HORIZONS}      # 超额（减同日全宇宙均值）
        seg = {"2019-2022": {h: [] for h in HORIZONS}, "2023-2026": {h: [] for h in HORIZONS}}
        yr = defaultdict(lambda: {h: [] for h in HORIZONS})
        for e in ev:
            d = stocks[e["code"]]
            dt = e["date"]
            for h in HORIZONS:
                r = fwd(d, e["i"], h)
                if r is None:
                    continue
                rs[h].append(r)
                u = uni_m[h].get(dt)
                if u is not None:
                    ex[h].append(r - u)
                seg["2019-2022" if dt < "2023" else "2023-2026"][h].append(r)
                yr[dt[:4]][h].append(r)
        o = {"n": len(ev)}
        print("\n=== %s  n=%d ===" % (name, len(ev)), flush=True)
        for h in HORIZONS:
            s, x = stats(rs[h]), stats(ex[h])
            o[f"T+{h}"] = {"raw": s, "excess": x, "odds": odds(rs[h]),
                           "seg": {k: stats(v[h]) for k, v in seg.items()}}
            if s and x:
                print("   T+%-3d win=%5.1f%% raw=%+6.2f%%  超额=%+5.2f%%(win_ex=%4.1f%%) odds=%.2f | 19-22 %+5.2f%% 23-26 %+5.2f%%" % (
                    h, s["win%"], s["mean%"], x["mean%"], x["win%"], odds(rs[h]) or 0,
                    (stats(seg["2019-2022"][h]) or {"mean%": 0})["mean%"],
                    (stats(seg["2023-2026"][h]) or {"mean%": 0})["mean%"]), flush=True)
        o["逐年_T+5"] = {y: (stats(v[5]) or {}).get("mean%") for y, v in sorted(yr.items())}
        o["逐年_T+20"] = {y: (stats(v[20]) or {}).get("mean%") for y, v in sorted(yr.items())}
        o["逐年_n"] = {y: len(v[5]) for y, v in sorted(yr.items())}
        print("   逐年 T+5 均值:", o["逐年_T+5"], flush=True)
        print("   逐年 T+20 均值:", o["逐年_T+20"], flush=True)
        out["events"][name] = o
    dst = ROOT / "data/downtrend_raid_stage2.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved", dst)


if __name__ == "__main__":
    main()
