#!/usr/bin/env python3
"""engine/k4_deep_v2.py — K4 任务四：深档低位v2（生产信号）三版定稿重算。

定义（dashboard_build.py:232-277 真实定义 + 任务书）：
  深档件 = 当日 pct_true ≤ -9.5%（除权还原真实跌幅）且 收<MA60 且 收≤MA60×0.75，剔 ST(v1∪v2)/退/nolimit
  簇门   = 当日深档件数 ≥ 5
  出手票 = 深档件中 收≤MA60×0.65（depth≤-35%）按 depth 最深 top5
  趋势门 = 指数20日跌幅 ≤ -3%（gate_trend）
执行（k3 lineage）：信号日 T → T+1 开盘买（日历对齐，缺 bar 剔除计数）→ T+5 收盘卖（cal[di+5]），
  一字涨停剔除（ow 掩码）。净 -0.2%（旧 k3 轮为 -0.15%，对照时注明）。
三版：
  (a) 新地基原样重建（绝对深度 ×0.75/×0.65 保留）
  (b) 簇门 → 深档件数滚动250日(min125)分位 ≥90 / ≥95（± 保留 ≥5 绝对下限）
  (c) 深度 → 波动率归一：收 ≤ MA60 − k·σ60价格（k=2/2.5/3），按 z 排序
每项：五项指标（原始净/减上证/减全市场等权/HAC t(日级聚合 lag5)/超额为正占比）+
  block bootstrap t(10/20，日级) + naive t + 逐年表 + 剔2024。
旧数对照：72~75% / +7.9~9.5%（毛或-0.15%口径），naive t 1.7~2.9、HAC 0.78~2.04、bootstrap 0.2~1.9。
输出：research/k4_out/k4_deep_v2.json + stdout。
"""
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.k4_utils import nw_tstat, naive_t, block_boot_t

ROOT = "/opt/data/fenjue"
OUT = os.path.join(ROOT, "research", "k4_out")
COST = 0.002
HOLD = 5


def five_metrics(ev):
    if not ev:
        return {"n": 0}
    ret = np.array([e["ret_net"] for e in ev])
    ex_i = np.array([e["ex_idx"] for e in ev], float)
    ex_e = np.array([e["ex_ew"] for e in ev], float)
    byday = {}
    for e in ev:
        byday.setdefault(e["day"], []).append(e["ex_ew"])
    ds = np.array([np.mean(v) for k, v in sorted(byday.items())])
    byday_raw = {}
    for e in ev:
        byday_raw.setdefault(e["day"], []).append(e["ret_net"])
    dsr = np.array([np.mean(v) for k, v in sorted(byday_raw.items())])
    return {
        "n": len(ev), "n_days": len(byday),
        "wr": float((ret > 0).mean()), "mean_net": float(ret.mean()),
        "med_net": float(np.median(ret)), "std": float(ret.std(ddof=1)),
        "worst": float(ret.min()), "mean_ex_idx": float(np.nanmean(ex_i)),
        "mean_ex_ew": float(np.nanmean(ex_e)),
        "share_ex_pos": float((ex_e > 0).mean()),
        "t_naive": naive_t(ex_e), "t_hac_day": nw_tstat(ds, lag=5),
        "t_hac_day_raw": nw_tstat(dsr, lag=5),
        "t_boot10": block_boot_t(ds, 10), "t_boot20": block_boot_t(ds, 20),
    }


def yearly(ev):
    out = {}
    for e in ev:
        out.setdefault(e["year"], []).append(e)
    r = {}
    for y, sub in sorted(out.items()):
        ret = np.array([e["ret_net"] for e in sub])
        ex = np.array([e["ex_ew"] for e in sub], float)
        r[str(y)] = {"n": len(sub), "wr": float((ret > 0).mean()),
                     "mean_net": float(ret.mean()), "mean_ex_ew": float(np.nanmean(ex))}
    return r


def main():
    os.makedirs(OUT, exist_ok=True)
    # DATA-07 熔断（R1-②展示型降级）：深档名单照算照写，产物带 data_stale 标记。
    _brk = {"data_stale": False, "stale_datasets": [], "reason": ""}
    try:
        from engine import breaker
        _brk = breaker.stale_mark("深档名单")
    except Exception:
        pass
    p = pickle.load(open(os.path.join(ROOT, "data", "cache", "k4_days.pkl"), "rb"))
    codes, cal, days = p["codes"], p["calendar"], p["days"]
    npz = np.load(os.path.join(ROOT, "data", "cache", "k4_panel.npz"))
    n_st, n_days = len(codes), len(cal)
    qo, qc, ma60, sig60p = npz["qo"], npz["qc"], npz["ma60"], npz["sig60p"]
    pct_true, st_v1, st_v2, nolimit, ow = npz["pct_true"], npz["st_v1"], npz["st_v2"], npz["nolimit"], npz["ow"]
    o_c = npz["o_c"]
    has = o_c > 0
    ew_all = days["ew_ret_t5_all"].to_numpy(float)
    idx_ret5 = days["idx_ret_t5"].to_numpy(float)
    gate_trend = days["gate_trend"].to_numpy().astype(bool)

    exst = (st_v1 == 0) & (st_v2 == 0)
    depth = qc / ma60 - 1.0
    with np.errstate(invalid="ignore"):
        deep = (pct_true <= -0.095) & exst & (nolimit == 0) & has & \
               np.isfinite(ma60) & (qc < ma60) & (depth <= -0.25)
    n_deep = deep.sum(axis=0).astype(np.int32)
    pick_a = deep & (depth <= -0.35)

    drops = {"ow_up": 0, "no_entry": 0, "no_exit": 0}

    def collect(pick_mask, sort_key, gate_days):
        ev = []
        for di in np.where(gate_days)[0]:
            if di + HOLD >= n_days:
                continue
            cand = np.where(pick_mask[:, di])[0]
            if not len(cand):
                continue
            sk = sort_key[cand, di]
            okk = np.isfinite(sk)
            cand, sk = cand[okk], sk[okk]
            if not len(cand):
                continue
            top = cand[np.argsort(sk, kind="stable")[:5]]
            for si in top:
                if ow[si, di] == 1:
                    drops["ow_up"] += 1
                    continue
                o_in, c_out = qo[si, di + 1], qc[si, di + HOLD]
                if not np.isfinite(o_in) or o_in <= 0:
                    drops["no_entry"] += 1
                    continue
                if not np.isfinite(c_out):
                    drops["no_exit"] += 1
                    continue
                gross = float(c_out / o_in - 1.0)
                ev.append({"code": codes[si], "day": cal[di], "year": int(cal[di][:4]),
                           "ret_net": gross - COST, "gross": gross,
                           "ex_idx": gross - float(idx_ret5[di]) if np.isfinite(idx_ret5[di]) else np.nan,
                           "ex_ew": gross - float(ew_all[di]) if np.isfinite(ew_all[di]) else np.nan})
        return ev

    res = {"口径": "深档件=pct_true≤-9.5%&收<MA60&收≤MA60×0.75(剔ST/退/nolimit)；簇门≥5；出手=×0.65 top5；"
                  "T+1开盘→T+5收盘(日历)；净-0.2%(旧k3为-0.15%)；趋势门=指数20日跌≤-3%",
           "versions": {}, "drops": {}}

    def add(name, ev):
        v = five_metrics(ev)
        v["yearly"] = yearly(ev)
        v["ex2024"] = five_metrics([e for e in ev if e["year"] != 2024])
        res["versions"][name] = v
        print(f"  {name:26s} n={v['n']:5d} days={v.get('n_days',0):4d} wr={v.get('wr',float('nan')):.3f} "
              f"net={v.get('mean_net',float('nan'))*100:+.2f}% exEW={v.get('mean_ex_ew',float('nan'))*100:+.2f}% "
              f"tHAC={v.get('t_hac_day',float('nan')):+.2f} tB10={v.get('t_boot10',float('nan')):+.2f} "
              f"ex24={v['ex2024'].get('mean_net',float('nan'))*100:+.2f}%", flush=True)

    # (a) 原样重建
    for tag, gt in (("trend", gate_trend), ("notrend", np.ones(n_days, bool))):
        ev = collect(pick_a, depth, (n_deep >= 5) & gt)
        add(f"a_exact_{tag}", ev)
    # (a) 无簇门诊断
    ev = collect(pick_a, depth, gate_trend)
    add("a_nocluster_trend", ev)

    # (b) 簇门滚动分位
    cnt = pd.Series(n_deep.astype(float))
    for q in (0.90, 0.95):
        rq = cnt.rolling(250, min_periods=125).quantile(q).shift(1).to_numpy()
        gate_q = n_deep >= np.nan_to_num(rq, nan=np.inf)
        for floor in (False, True):
            gate = gate_q & gate_trend
            if floor:
                gate = gate & (n_deep >= 5)
            ev = collect(pick_a, depth, gate)
            add(f"b_q{int(q*100)}{'_floor5' if floor else ''}", ev)

    # (c) 波动率归一深度
    z_price = (qc - ma60) / sig60p
    for k in (2.0, 2.5, 3.0):
        pick = deep & np.isfinite(sig60p) & (sig60p > 0) & (qc <= ma60 - k * sig60p)
        ev = collect(pick, z_price, (n_deep >= 5) & gate_trend)
        add(f"c_ksig{k}", ev)

    res["drops"] = drops
    res["data_stale"] = bool(_brk.get("data_stale"))  # DATA-07 熔断降级标记
    res["stale_datasets"] = _brk.get("stale_datasets") or []
    res["n_deep_series"] = {"mean": float(n_deep.mean()), "p95": float(np.percentile(n_deep, 95)),
                            "max": int(n_deep.max()), "days_ge5": int((n_deep >= 5).sum())}
    with open(os.path.join(OUT, "k4_deep_v2.json"), "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(f"\n落盘 {OUT}/k4_deep_v2.json; drops={drops}")


if __name__ == "__main__":
    main()
