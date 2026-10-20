#!/usr/bin/env python3
"""engine/k3_deep_low_v2.py — 深档低位v2 三版重算（精确限价 + 重叠校正）。

口径（钉死，报告同文）：
  信号日 T 收盘出信号 → T+1 开盘买（前复权）→ T+5 收盘卖，毛收益减 0.15% 双边成本为净口径。
  入场日一字涨停（开=高=低=精确涨停价）或入/出场日无bar → 剔除并计数。
  超额基准按日对齐：减上证 = 指数同窗 T+1开→T+5收；减全市场等权 = 当日全库同窗均值（毛口径，成本相消）。
  样本期：2019-01-02 .. 2026-09-11（不复权库截止；之后限价不可知，截断）。
  ST/退剔除 = main_board_codes.json 当前名签（生产同款，前视局限报告声明）。

版本：
  oldproxy : pct(前复权)≤-9.5% 复刻（全3377只含缺库票，不剔一字）——对照旧 68%/+11.95%
  (a)      : 精确跌停 + 簇门(深档件≥5) + 深度≤MA60×0.65 top5
  (b)      : 簇门 → 当日精确跌停家数(剔ST)滚动250日分位≥q90/q95，±「深档件≥5」绝对下限
  (c)      : 深度 → close≤MA60−k·σ60价格 (k=2/2.5/3)；脚注 close/MA60≤1−k·σ60收益；
             或 close/MA60 ≤ 个股自身滚动250日(min125)5%分位
  趋势门 = 指数20日跌幅≤-3%（任务口径；每版给 含门/无门 两行）。

五项：原始净收益均值+胜率 / 减上证 / 减全市场等权 / HAC t（日级聚合 Newey-West lag=5，Bartlett）
      + 事件级 naive t 对照 / 超额>0 占比。另：逐年表、剔2024。
输出：data/k3_deep_low_v2_results.json + stdout 表。
"""
import json
import math
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

ROOT = "/opt/data/fenjue"
PANEL = os.path.join(ROOT, "data", "cache", "k3_panel.pkl")
OUT = os.path.join(ROOT, "data", "k3_deep_low_v2_results.json")
COST = 0.0015
SAMPLE_END = "2026-09-11"


def nw_tstat(x, lag=5):
    """Newey-West HAC t（Bartlett 权重），镜像 law_pipeline.py 的口径。"""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 8:
        return float("nan")
    e = x - x.mean()
    s = (e * e).mean()
    L = min(lag, n - 1)
    for l in range(1, L + 1):
        w = 1.0 - l / (L + 1)
        s += 2.0 * w * float((e[l:] * e[:-l]).mean())
    se = math.sqrt(max(s, 0.0) / n)
    return float(x.mean() / se) if se > 0 else float("nan")


def naive_t(x):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 2:
        return float("nan")
    sd = x.std(ddof=1)
    return float(x.mean() / (sd / math.sqrt(n))) if sd > 0 else float("nan")


def block_boot_t(x, block, reps=2000, seed=42):
    """循环块 bootstrap t（与策略A基线 block10/block20 同口径）：日序列按块重抽样，
    t = 均值 / 块抽样均值分布的 std。"""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < block + 3:
        return float("nan")
    rng = np.random.default_rng(seed)
    nb = int(math.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=(reps, nb))
    means = np.array([np.concatenate([x[s:s + block] for s in row])[:n].mean() for row in starts])
    se = float(means.std(ddof=1))
    return float(x.mean() / se) if se > 0 else float("nan")


def five_metrics(ev):
    """ev: list of dict(ret_net, ex_idx, ex_ew, day, year)。"""
    if not ev:
        return {"n": 0}
    ret = np.array([e["ret_net"] for e in ev])
    ex_i = np.array([e["ex_idx"] for e in ev])
    ex_e = np.array([e["ex_ew"] for e in ev])
    # 日级聚合（重叠校正主口径）：同一信号日的出手票等权平均 → 日序列
    byday = {}
    for e in ev:
        byday.setdefault(e["day"], []).append(e["ex_ew"])
    day_series = np.array([np.mean(v) for k, v in sorted(byday.items())])
    return {
        "n": len(ev),
        "n_days": len(byday),
        "wr": float((ret > 0).mean()),
        "mean_raw": float(ret.mean()),
        "med_raw": float(np.median(ret)),
        "mean_ex_idx": float(np.nanmean(ex_i)),
        "mean_ex_ew": float(np.nanmean(ex_e)),
        "t_naive": naive_t(ex_e),
        "t_hac_day": nw_tstat(day_series, lag=5),
        "t_boot10": block_boot_t(day_series, 10),
        "t_boot20": block_boot_t(day_series, 20),
        "share_ex_pos": float((ex_e > 0).mean()),
    }


def yearly(ev):
    out = {}
    for y in range(2019, 2027):
        sub = [e for e in ev if e["year"] == y]
        if not sub:
            continue
        ret = np.array([e["ret_net"] for e in sub])
        ex = np.array([e["ex_ew"] for e in sub])
        byday = {}
        for e in sub:
            byday.setdefault(e["day"], []).append(e["ex_ew"])
        ds = np.array([np.mean(v) for k, v in sorted(byday.items())])
        out[str(y)] = {"n": len(sub), "n_days": len(byday), "wr": float((ret > 0).mean()),
                       "mean_raw": float(ret.mean()), "mean_ex_ew": float(np.nanmean(ex)),
                       "t_hac_day": nw_tstat(ds, lag=5)}
    return out


def main():
    t0 = time.time()
    # DATA-07 熔断（R1-②展示型降级）：深档名单照算照写，产物带 data_stale 标记。
    _brk = {"data_stale": False, "stale_datasets": [], "reason": ""}
    try:
        sys.path.insert(0, ROOT)
        from engine import breaker
        _brk = breaker.stale_mark("深档名单")
    except Exception:
        pass
    p = pickle.load(open(PANEL, "rb"))
    codes, cal, mat, days = p["codes"], p["calendar"], p["mat"], p["days"]
    n_st, n_days = len(codes), len(cal)
    day_pos = {d: i for i, d in enumerate(cal)}
    end_pos = day_pos[SAMPLE_END]
    print(f"[v2] 面板 {n_st}只 × {n_days}天，样本截止 {SAMPLE_END}(pos {end_pos})，加载 {time.time()-t0:.0f}s")

    c_adj, o_adj = mat["c_adj"], mat["o_adj"]
    ma60, ma20 = mat["ma60"], mat["ma20"]
    sig60p, sig60r = mat["sig60p"], mat["sig60r"]
    is_ld = mat["is_ld"]
    st_arr, tui_arr, hasu = mat["st"], mat["tui"], mat["has_unadj"]
    ow = mat["ow_up_next"]
    exst_col = ((st_arr == 0) & (tui_arr == 0))
    hasu_col = (hasu == 1)

    ew_ret = days["ew_ret_t5"].to_numpy()
    idx_ret = days["idx_ret_t5"].to_numpy()
    gate_trend = days["gate_trend"].to_numpy().astype(bool)
    n_ld_exst = days["n_ld_new_exst"].to_numpy()
    n_deep_a = days["n_deep_a"].to_numpy()

    # 旧代理 pct（前复权，全宇宙）
    pct_adj = np.full((n_st, n_days), np.nan, np.float32)
    pct_adj[:, 1:] = c_adj[:, 1:] / c_adj[:, :-1] - 1.0

    depth = c_adj / ma60 - 1.0  # 相对MA60深度（负）
    # 深档件（簇门计数件）：信号层条件
    deep_exact = (is_ld == 1) & exst_col[:, None] & hasu_col[:, None] & \
                 np.isfinite(ma60) & (c_adj < ma60) & (depth <= -0.25)
    deep_old = (pct_adj <= -0.095) & exst_col[:, None] & np.isfinite(ma60) & \
               (c_adj < ma60) & (depth <= -0.25)
    n_deep_old = np.nansum(deep_old, axis=0).astype(np.int32)

    drops = {"ow_up": 0, "no_entry": 0, "no_exit": 0}

    def collect(pick_mask, sort_key, gate_days, use_ow=True):
        """gate_days: bool[n_days]；pick_mask/sort_key: (n_st,n_days)。逐日取 sort_key 最小 top5。"""
        events = []
        days_on = np.where(gate_days[:end_pos + 1])[0]
        for di in days_on:
            if di + 5 >= n_days:
                continue
            cand = np.where(pick_mask[:, di])[0]
            if not len(cand):
                continue
            sk = sort_key[cand, di]
            ok = np.isfinite(sk)
            cand, sk = cand[ok], sk[ok]
            if not len(cand):
                continue
            top = cand[np.argsort(sk, kind="stable")[:5]]
            for si in top:
                if use_ow and ow[si, di] == 1:
                    drops["ow_up"] += 1
                    continue
                o_in = o_adj[si, di + 1]
                c_out = c_adj[si, di + 5]
                if not np.isfinite(o_in):
                    drops["no_entry"] += 1
                    continue
                if not np.isfinite(c_out):
                    drops["no_exit"] += 1
                    continue
                gross = float(c_out / o_in - 1.0)
                events.append({
                    "code": codes[si], "date": cal[di], "day": cal[di],
                    "year": int(cal[di][:4]),
                    "ret_net": gross - COST,
                    "ex_idx": gross - float(idx_ret[di]),
                    "ex_ew": gross - float(ew_ret[di]),
                })
        return events

    results = {"口径": "T+1开盘买→T+5收盘卖，净-0.15%，超额减基准为毛口径(成本相消)；"
                      "样本期2019-01-02..2026-09-11；HAC=日级聚合NW(lag=5)",
               "versions": {}, "drops": {}}

    def add(name, ev):
        v = five_metrics(ev)
        v["yearly"] = yearly(ev)
        v["ex2024"] = five_metrics([e for e in ev if e["year"] != 2024])
        results["versions"][name] = v
        print(f"  {name:28s} n={v['n']:5d} days={v.get('n_days',0):4d} wr={v.get('wr',float('nan')):.3f} "
              f"raw={v.get('mean_raw',float('nan'))*100:+.2f}% exEW={v.get('mean_ex_ew',float('nan'))*100:+.2f}% "
              f"tHAC={v.get('t_hac_day',float('nan')):+.2f} ex2024_raw={v['ex2024'].get('mean_raw',float('nan'))*100:+.2f}%")

    # ---- oldproxy 对照行（复刻旧口径：pct≤-9.5、全宇宙、不剔一字）----
    print("[v2] 逐版本计算…")
    pick_old = deep_old & (depth <= -0.35)
    for tag, gt in (("trend", gate_trend), ("notrend", np.ones(n_days, bool))):
        gate = (n_deep_old >= 5) & gt
        ev = collect(pick_old, depth, gate, use_ow=False)
        add(f"oldproxy_{tag}", ev)

    # ---- (a) 精确限价原样 ----
    pick_a = deep_exact & (depth <= -0.35)
    for tag, gt in (("trend", gate_trend), ("notrend", np.ones(n_days, bool))):
        gate = (n_deep_a >= 5) & gt
        ev = collect(pick_a, depth, gate)
        add(f"a_exact_{tag}", ev)
    # 2×2 网格补全：无簇门（任何当日有 ≤0.65 锐化件即出手，含零星日）
    for tag, gt in (("trend", gate_trend), ("notrend", np.ones(n_days, bool))):
        ev = collect(pick_a, depth, gt)
        add(f"a_exact_nocluster_{tag}", ev)

    # ---- (b) 簇门滚动分位 ----
    cnt = pd.Series(n_ld_exst.astype(float))
    for q in (0.90, 0.95):
        roll_q = cnt.rolling(250, min_periods=125).quantile(q).to_numpy()
        gate_q = n_ld_exst >= np.nan_to_num(roll_q, nan=np.inf)
        for floor in (False, True):
            gate = gate_q & gate_trend
            if floor:
                gate = gate & (n_deep_a >= 5)
            ev = collect(pick_a, depth, gate)
            add(f"b_q{int(q*100)}{'_floor5' if floor else ''}", ev)

    # ---- (c1) 波动率归一（价格σ）----
    z_price = (c_adj - ma60) / sig60p
    for k in (2.0, 2.5, 3.0):
        pick = deep_exact & np.isfinite(sig60p) & (sig60p > 0) & (c_adj <= ma60 - k * sig60p)
        gate = (n_deep_a >= 5) & gate_trend
        ev = collect(pick, z_price, gate)
        add(f"c1_ksig{k}", ev)
    # ---- (c1b) 脚注：收益σ折算 ----
    sig60r_med_deep = float(np.nanmedian(sig60r[deep_exact & np.isfinite(sig60r)]))
    print(f"[v2] c1b 实证锚点：深档件上 σ60r 中位数={sig60r_med_deep*100:.2f}%"
          f"（1-2.5σ 阈值≈{1-2.5*sig60r_med_deep:.3f}，入池要求 ratio≤0.75，差一个数量级→阈值不绑）")
    results["sig60r_median_deep"] = sig60r_med_deep
    z_ret = (c_adj / ma60 - 1.0) / sig60r
    for k in (2.0, 2.5, 3.0):
        pick = deep_exact & np.isfinite(sig60r) & (sig60r > 0) & (c_adj / ma60 <= 1.0 - k * sig60r)
        gate = (n_deep_a >= 5) & gate_trend
        ev = collect(pick, z_ret, gate)
        add(f"c1b_kretsig{k}", ev)

    # ---- (c2) 个股自身历史 5% 分位 ----
    ratio = c_adj / ma60
    cand_stocks = np.where((deep_exact & np.isfinite(ratio)).any(axis=1))[0]
    print(f"[v2] c2: {len(cand_stocks)} 只有候选日，逐票算滚动分位…")
    pick_c2 = np.zeros((n_st, n_days), bool)
    rank_c2 = np.full((n_st, n_days), np.nan, np.float32)
    for si in cand_stocks:
        s = pd.Series(ratio[si])
        q05 = s.rolling(250, min_periods=125).quantile(0.05).shift(1).to_numpy()
        hit = np.isfinite(q05) & np.isfinite(ratio[si]) & (ratio[si] <= q05)
        pick_c2[si] = hit & deep_exact[si]
        with np.errstate(invalid="ignore", divide="ignore"):
            rank_c2[si] = np.where(hit, ratio[si] / q05, np.nan)
    gate = (n_deep_a >= 5) & gate_trend
    ev = collect(pick_c2, rank_c2, gate)
    add("c2_ownpct5", ev)

    results["drops"] = drops
    results["data_stale"] = bool(_brk.get("data_stale"))  # DATA-07 熔断降级标记
    results["stale_datasets"] = _brk.get("stale_datasets") or []
    results["sample"] = {"start": cal[0], "end": SAMPLE_END,
                         "truncated_days_after": n_days - 1 - end_pos}
    with open(OUT, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print(f"[v2] 落盘 {OUT}；剔除统计 {drops}；总耗时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
