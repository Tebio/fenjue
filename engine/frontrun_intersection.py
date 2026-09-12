#!/usr/bin/env python3
"""engine/frontrun_intersection.py — 抢跑交集假说回测（2026-09-12 用户立项「都搞」#1）

假说：首板当日上车 × 板块梯队 × 市值带 → 隔夜/后续收益。
背景：#38 测得 T-1首板→次日大涨 20.9%(8.9x)；doubler 测得首板当日识别隔夜溢价
+1.29%/55.3%（妖股期口径）。本模块把「板块梯队+市值带」条件加上，8 年全宇宙测。

口径（两种入场，物理可执行性不同，分开报）：
  close-entry = 信号日（首板当日）收盘买入：c[i+1]/c[i]（T+1）、c[i+5]/c[i]（T+5）、
                gap=o[i+1]/c[i]（隔夜溢价）。⚠️ 前提=打板成交，封死板可能买不进（口径乐观）。
  open-entry  = 次日开盘追：c[i+1]/o[i+1]。#38 已知 -0.45%，作对照复验。
信号定义：
  首板：当日涨幅≥+9.8% 且前 60 日无 ≥+9.8% 日（doubler 同口径；自动排除 ST 5% 板）
  可买：开盘涨幅 <+9.5%（一字板买不进，剔除）
  梯队：同行业（industry_map）当日 ≥3 只涨停（≥9.8%，含自己）
  市值带：信号月流通市值 20-400 亿（cap_hist 月度）
变体：V0 首板 baseline / V1 +梯队 / V2 +梯队+市值带 / V3 首板+市值带（无梯队）
检验：双段（2019-2022/2023-2026）、regime 分段、位置匹配对照（同票同MA60侧随机日，
同 close-entry 口径）、NW-HAC t。费 0.15%。
"""
import json, sys, math, random, statistics as st
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = Path("/opt/data/fenjue")
FEE = 0.0015
GAIN = 9.8
CAP_LO, CAP_HI = 20, 400


def S(rs):
    if len(rs) < 30:
        return None
    m = st.mean(rs)
    return {"n": len(rs), "win%": round(100*sum(r > 0 for r in rs)/len(rs), 1),
            "mean%": round(100*m, 2), "med%": round(100*st.median(rs), 2)}


def main():
    stocks = lp.load_universe()
    regime = lp.load_regime()
    stock_cap, _qs = lp.load_cap_quintiles()
    ind = json.loads((ROOT/"data/industry_map.json").read_text())

    # 第一遍：全宇宙每日涨停集合 → 行业梯队计数
    ladder = defaultdict(lambda: defaultdict(int))  # date -> industry -> n
    for code, d in stocks.items():
        c = d["c"]
        for i in range(1, d["n"]):
            if c[i-1] > 0 and (c[i]/c[i-1]-1)*100 >= GAIN:
                industry = ind.get(code, {}).get("industry") or "?"
                ladder[d["date"][i]][industry] += 1

    # 第二遍：信号检测
    variants = {"V0": [], "V1": [], "V2": [], "V3": []}  # (code, i)
    for code, d in stocks.items():
        c, o, dates, n = d["c"], d["o"], d["date"], d["n"]
        industry = ind.get(code, {}).get("industry") or "?"
        sc = stock_cap.get(code, {})
        last_board = -10**9
        for i in range(61, n - 6):
            g = (c[i]/c[i-1]-1)*100 if c[i-1] > 0 else 0
            if g >= GAIN:
                first = (i - last_board) > 60
                last_board = i
                if not first:
                    continue
                if o[i] > 0 and (o[i]/c[i-1]-1)*100 >= 9.5:
                    continue  # 一字板买不进
                variants["V0"].append((code, i))
                lad = ladder[dates[i]][industry] >= 3
                cap = sc.get(dates[i][:7])
                band = cap is not None and CAP_LO <= cap <= CAP_HI
                if lad:
                    variants["V1"].append((code, i))
                if lad and band:
                    variants["V2"].append((code, i))
                if band:
                    variants["V3"].append((code, i))

    out = {"meta": {"universe": len(stocks), "fee": FEE,
                    "note": "close-entry=打板成交口径(乐观)；open-entry=次日追"}}
    for name, evs in variants.items():
        res = {}
        for label, fn in {
            "T1_close": lambda c, o, i: c[i+1]/c[i]-1-FEE,
            "T5_close": lambda c, o, i: c[i+5]/c[i]-1-FEE,
            "gap_overnight": lambda c, o, i: o[i+1]/c[i]-1,
            "T1_open": lambda c, o, i: c[i+1]/o[i+1]-1-FEE if o[i+1] > 0 else None,
        }.items():
            rs = []
            for code, i in evs:
                d = stocks[code]
                v = fn(d["c"], d["o"], i)
                if v is not None:
                    rs.append(v)
            s = S(rs)
            if s and label in ("T1_close", "T5_close"):
                s["t_NW"] = lp.nw_t(rs, 5)
            res[label] = s
        # 分段（T5_close）
        seg_t, seg_r = defaultdict(list), defaultdict(list)
        for code, i in evs:
            d = stocks[code]
            r = d["c"][i+5]/d["c"][i]-1-FEE
            dt = d["date"][i]
            seg_t["2019-2022" if dt < "2023" else "2023-2026"].append(r)
            seg_r[regime.get(dt, "?")].append(r)
        res["seg_time_T5"] = {k: S(v) for k, v in seg_t.items()}
        res["seg_regime_T5"] = {k: S(v) for k, v in sorted(seg_r.items()) if S(v)}
        out[name] = res
        print(f"=== {name} ===", json.dumps(res, ensure_ascii=False), flush=True)

    # V2 位置匹配对照（close-entry，同票同MA60侧）
    rnd = random.Random(7)
    for h in (1, 5):
        sig, ctl = [], []
        ev_by_code = defaultdict(list)
        for code, i in variants["V2"]:
            ev_by_code[code].append(i)
        for code, days in ev_by_code.items():
            d = stocks[code]
            c, ma, n = d["c"], d["ma60"], d["n"]
            lows, highs = [], []
            for i in range(61, n - h - 1):
                if ma[i] is None:
                    continue
                (lows if c[i] <= ma[i] else highs).append(i)
            lo_n = sum(1 for i in days if ma[i] is not None and c[i] <= ma[i])
            for i in days:
                sig.append(c[i+h]/c[i]-1-FEE)
            for pool, k in ((lows, lo_n), (highs, len(days)-lo_n)):
                if pool and k:
                    for i in rnd.sample(pool, min(k, len(pool))):
                        ctl.append(c[i+h]/c[i]-1-FEE)
        if len(sig) >= 30 and len(ctl) >= 30:
            out["V2"][f"matched_T{h}"] = {"sig%": round(100*st.mean(sig), 2),
                "ctl%": round(100*st.mean(ctl), 2),
                "marginal_pp": round(100*(st.mean(sig)-st.mean(ctl)), 2), "n": len(sig)}
    print("V2 matched:", json.dumps({k: v for k, v in out["V2"].items() if k.startswith("matched")}, ensure_ascii=False))

    (ROOT/"data/frontrun_intersection_20260912.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str))
    print("SAVED data/frontrun_intersection_20260912.json")


if __name__ == "__main__":
    main()
