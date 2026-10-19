#!/usr/bin/env python3
"""深度体检（读 peer_momentum_study.json，不重跑网络）：
1. MA60 上方带内的分层价差（该带是全样本唯一有梯度处）+ 带内再控自身动量。
2. 信号与自身动量的截面秩相关（按位置带分组）→ 判断是否自身动量代理。
3. 邻居数分档（3-4 / 5-7 / 8-10）的价差 —— 网络紧密度是否单调。
4. 分段（前段/后段）稳定度。
产物 data/fund_cohold/deep_check.json
用法: .venv/bin/python engine/fund_cohold_deep.py
"""
import json, math
from collections import defaultdict
import numpy as np

DC = "/opt/data/fenjue/data/fund_cohold"


def nw_t(x, lag=3):
    x = np.asarray(x, float); x = x[np.isfinite(x)]; n = len(x)
    if n < 6: return float("nan")
    d = x - x.mean(); s = (d * d).mean()
    for L in range(1, min(lag, n - 1) + 1):
        s += 2 * (1 - L / (lag + 1)) * (d[L:] * d[:-L]).mean()
    return float(x.mean() / math.sqrt(s / n)) if s > 0 else float("nan")


def spearman(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 5: return float("nan")
    ra = np.argsort(np.argsort(a)).astype(float); rb = np.argsort(np.argsort(b)).astype(float)
    ra -= ra.mean(); rb -= rb.mean()
    den = math.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / den) if den > 0 else float("nan")


def month_spread(lst, key, min_n=30):
    lst = sorted(lst, key=lambda e: e[key]); n = len(lst)
    q1 = [e["ex"] for e in lst[:n // 5]]; q5 = [e["ex"] for e in lst[-n // 5:]]
    return float(np.mean(q5)) - float(np.mean(q1))


def main():
    ev = json.load(open(f"{DC}/peer_momentum_study.json"))["events"]
    out = {"n_events": len(ev)}
    print(f"事件 {len(ev)}")

    # --- 1. 位置带 ---------------------------------------------------------
    def band(p):
        if p is None: return None
        if p >= 0: return "above_ma60"
        if p >= -0.10: return "0_to_-10"
        if p >= -0.25: return "-10_to_-25"
        return "below_-25"
    for b in ["above_ma60", "0_to_-10", "-10_to_-25", "below_-25"]:
        sub = [e for e in ev if band(e["pos"]) == b]
        mg = defaultdict(list)
        for e in sub: mg[e["m"]].append(e)
        sp = [month_spread(l, "sig") for l in mg.values() if len(l) >= 30]
        out[f"band_{b}"] = {"n": len(sub), "months": len(sp),
                            "spread_pp": round(float(np.mean(sp)) * 100, 3) if sp else None,
                            "hit": round(float(np.mean([x > 0 for x in sp])), 3) if sp else None,
                            "nw_t": round(nw_t(np.array(sp) * 100), 2) if len(sp) > 5 else None}
        print(f"  带 {b}: {out[f'band_{b}']}")

    # --- 1b. 上方带内再控自身动量 -----------------------------------------
    above = [e for e in ev if band(e["pos"]) == "above_ma60" and e["own"] is not None]
    mg = defaultdict(list)
    for e in above: mg[e["m"]].append(e)
    inner = defaultdict(list)
    for m, lst in mg.items():
        lst.sort(key=lambda e: e["own"]); n = len(lst)
        if n < 45: continue
        for t in range(3):
            sub = sorted(lst[n * t // 3: n * (t + 1) // 3], key=lambda e: e["sig"])
            nn = len(sub)
            if nn < 15: continue
            inner[t].append(float(np.mean([e["ex"] for e in sub[-max(nn // 5, 1):]]))
                            - float(np.mean([e["ex"] for e in sub[:max(nn // 5, 1)]])))
    out["above_ctrl_own_momentum"] = {f"own_tercile_{k+1}": {
        "spread_pp": round(float(np.mean(v)) * 100, 3), "months": len(v),
        "nw_t": round(nw_t(np.array(v) * 100), 2),
        "hit": round(float(np.mean([x > 0 for x in v])), 3)} for k, v in sorted(inner.items())}

    # --- 2. 信号 vs 自身动量 ----------------------------------------------
    by_mb = defaultdict(lambda: defaultdict(list))
    for e in ev:
        if e["own"] is not None and band(e["pos"]):
            by_mb[e["m"]][band(e["pos"])].append(e)
    corr = defaultdict(list)
    for m, bands in by_mb.items():
        for b, lst in bands.items():
            if len(lst) >= 20:
                corr[b].append(spearman([e["sig"] for e in lst], [e["own"] for e in lst]))
    out["sig_vs_own_spearman"] = {b: {"mean_rho": round(float(np.nanmean(v)), 4),
        "median_rho": round(float(np.nanmedian(v)), 4), "months": len(v)}
        for b, v in sorted(corr.items())}

    # --- 3. 邻居数分档（上方带内） ----------------------------------------
    nb = defaultdict(list)
    for e in above:
        k = "3-4" if e["nbr"] <= 4 else ("5-7" if e["nbr"] <= 7 else "8-10")
        nb[k].append(e)
    out["neighbor_count_bands"] = {}
    for k, sub in sorted(nb.items()):
        mg2 = defaultdict(list)
        for e in sub: mg2[e["m"]].append(e)
        sp = [month_spread(l, "sig", 20) for l in mg2.values() if len(l) >= 20]
        out["neighbor_count_bands"][k] = {"n": len(sub), "months": len(sp),
            "spread_pp": round(float(np.mean(sp)) * 100, 3) if sp else None,
            "hit": round(float(np.mean([x > 0 for x in sp])), 3) if sp else None}

    # --- 4. 分段稳定度（全样本 + 上方带） ---------------------------------
    ms = sorted(set(e["m"] for e in ev))
    mid = ms[len(ms) // 2]
    segs = {"first_half": [e for e in ev if e["m"] < mid],
            "second_half": [e for e in ev if e["m"] >= mid]}
    out["segments"] = {}
    for name, sub in segs.items():
        mg3 = defaultdict(list)
        for e in sub: mg3[e["m"]].append(e)
        sp = [month_spread(l, "sig") for l in mg3.values() if len(l) >= 30]
        out["segments"][name] = {"months": len(sp), "range": f"{sub[0]['m']}..{sub[-1]['m']}",
            "spread_pp": round(float(np.mean(sp)) * 100, 3) if sp else None,
            "hit": round(float(np.mean([x > 0 for x in sp])), 3) if sp else None}
    json.dump(out, open(f"{DC}/deep_check.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:2500])
    print("DEEP_DONE")


if __name__ == "__main__":
    main()
