#!/usr/bin/env python3
"""engine/hac_crosscheck.py — statsmodels HAC 对账手写 Newey-West t（AGENTS #279③，任务卡 t_05a4241d）

背景：#262-F 实锤统计库全零命中、全部 t 检验手写。本脚本首次用 statsmodels 交叉验证
手写 nw_t（law_pipeline.py:128）。取三条已注册生产线，重建日历时间超额序列
（calendar_time 口径逐行复刻：horizon=5、fee=0.0015、next_open、全宇宙日度均值剔β）：
  ① 跌停接_MA60下   ② 反转族_MA60下   ③ 预增低位池_v1
手写 nw_t（含未取整原值）vs statsmodels OLS+HAC(maxlags=5) 的 t 并列报。
判据：|t_hand - t_sm| / |t_hand| > 10% 必须查原因。

law_pipeline 处于只读引擎状态，本脚本不改它，仅 import 复用：
  nw_t / _epx / _collect_sigs / load_universe / load_cap_quintiles / REGISTRY。

用法：.venv/bin/python engine/hac_crosscheck.py
产出：data/hac_crosscheck_20261016.json
"""
import json, math, statistics as st, sys, time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import law_pipeline as lp

OUT = lp.ROOT / "data/hac_crosscheck_20261016.json"
LINES = ["跌停接_MA60下", "反转族_MA60下", "预增低位池_v1"]
from costs import FLAT_RT  # TAX-01 唯一真源 engine/costs.py（AGENTS #287）
HORIZON, FEE = 5, FLAT_RT


def uni_mean_map(stocks):
    """calendar_time 的全宇宙日度均值段（与 lp.calendar_time 逐行同口径，算一次三线复用）。"""
    uni = defaultdict(list)
    for code, d in stocks.items():
        c, n = d["c"], d["n"]
        for i in range(lp.START, n - HORIZON - 1):
            e = lp._epx(d, i)
            if e > 0:
                uni[d["date"][i + 1]].append(c[i + HORIZON] / e - 1 - FEE)
    return {dt: st.mean(v) for dt, v in uni.items()}


def cal_series(sigs, stocks, uni_m):
    """calendar_time 的事件聚合段（同口径），返回日度超额序列。"""
    by_date = defaultdict(list)
    for dt, evs in sigs.items():
        for code, i in evs:
            d = stocks[code]
            by_date[d["date"][min(i + 1, d["n"] - 1)]].append(
                d["c"][i + HORIZON] / lp._epx(d, i) - 1 - FEE)
    return [st.mean(by_date[dt]) - uni_m[dt] for dt in sorted(by_date) if dt in uni_m]


def nw_t_raw(x, lag):
    """lp.nw_t 同公式不取整版（对账用原值）。"""
    n = len(x)
    if n < lag + 30:
        return None
    m = st.mean(x)
    g0 = sum((r - m) ** 2 for r in x) / n
    lrv = g0
    for k in range(1, lag + 1):
        gk = sum((x[t_] - m) * (x[t_ - k] - m) for t_ in range(k, n)) / n
        lrv += 2 * (1 - k / (lag + 1)) * gk
    return m / math.sqrt(lrv / n) if lrv > 0 else None


def sm_hac_t(x, lag):
    """statsmodels：x ~ const 的 OLS，HAC(Bartlett, maxlags=lag) 标准误下的 t。"""
    import statsmodels.api as sm
    y = np.asarray(x, dtype=float)
    res = sm.OLS(y, np.ones((len(y), 1))).fit(cov_type="HAC", cov_kwds={"maxlags": lag})
    return float(res.tvalues[0]), float(res.bse[0]), str(res.cov_kwds)


def main():
    t0 = time.time()
    stocks = lp.load_universe()
    lp._XCAP, _ = lp.load_cap_quintiles()   # 预增低位池_v1 的 PIT 市值依赖
    print(f"[hac] universe={len(stocks)} load={time.time()-t0:.0f}s", flush=True)
    uni_m = uni_mean_map(stocks)
    print(f"[hac] uni mean map {len(uni_m)} days, {time.time()-t0:.0f}s", flush=True)
    out = {"_meta": {"built": time.strftime("%Y-%m-%d %H:%M"), "task": "t_05a4241d / AGENTS #279③",
                     "口径": "日历时间超额序列, horizon=5, fee=0.0015, next_open; 手写nw_t vs statsmodels HAC(maxlags=5)"},
           "lines": {}}
    for name in LINES:
        detect = lp.REGISTRY[name]
        ta = time.time()
        sigs = lp._collect_sigs(detect, stocks)
        series = cal_series(sigs, stocks, uni_m)
        n_ev = sum(len(v) for v in sigs.values())
        t_hand_raw = nw_t_raw(series, HORIZON)
        t_hand_official = lp.nw_t(series, HORIZON)          # 生产手写版（取整）
        t_sm, se_sm, kw = sm_hac_t(series, HORIZON)
        diff_pct = (abs(t_hand_raw - t_sm) / abs(t_hand_raw) * 100) if t_hand_raw else None
        row = {"事件数": n_ev, "天数": len(series),
               "t_手写_raw": round(t_hand_raw, 4) if t_hand_raw else None,
               "t_手写_生产取整": t_hand_official,
               "t_statsmodels": round(t_sm, 4), "se_statsmodels": se_sm,
               "cov_kwds": kw,
               "差异%": round(diff_pct, 3) if diff_pct is not None else None,
               "判定": "PASS(≤10%)" if diff_pct is not None and diff_pct <= 10 else "需查原因",
               "耗时s": int(time.time() - ta)}
        out["lines"][name] = row
        print(f"[hac] {name}: n={n_ev} days={len(series)} t_hand={row['t_手写_raw']} "
              f"t_sm={row['t_statsmodels']} diff={row['差异%']}%", flush=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"[hac] DONE -> {OUT} elapsed={time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
