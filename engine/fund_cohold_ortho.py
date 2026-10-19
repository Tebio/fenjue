#!/usr/bin/env python3
"""正交性体检：邻居动量信号 vs GridCF-D knn_score（截面 Spearman）。
在每月信号参考日上，取当日有 knn 分数的同批事件，算 sig 与 knn 的秩相关。
产物 data/fund_cohold/orthogonality.json
用法: .venv/bin/python engine/fund_cohold_ortho.py
"""
import json, math
from collections import defaultdict
import numpy as np

ROOT = "/opt/data/fenjue"
DC = f"{ROOT}/data/fund_cohold"


def spearman(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 5: return float("nan")
    ra = np.argsort(np.argsort(a)).astype(float); rb = np.argsort(np.argsort(b)).astype(float)
    ra -= ra.mean(); rb -= rb.mean()
    den = math.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / den) if den > 0 else float("nan")


def main():
    ev = json.load(open(f"{DC}/peer_momentum_study.json"))["events"]
    base = np.load(f"{ROOT}/data/factor_census_base.npz", allow_pickle=True)
    codes = [str(c) for c in base["codes"]]; cal = [str(d) for d in base["calendar"]]
    cidx = {c: i for i, c in enumerate(codes)}; didx = {d: i for i, d in enumerate(cal)}
    score = np.load(f"{ROOT}/data/similarity_gridscore.npz")["score"]
    by_ref = defaultdict(list)
    for e in ev: by_ref[e["ref"]].append(e)
    rows = []
    for ref, evs in sorted(by_ref.items()):
        di = didx.get(ref)
        if di is None: continue
        xs, ys = [], []
        for e in evs:
            c = cidx.get(e["A"])
            if c is None: continue
            s = score[di, c]
            if not np.isfinite(s): continue
            xs.append(e["sig"]); ys.append(float(s))
        if len(xs) >= 30:
            rows.append({"ref": ref, "n": len(xs), "rho": round(spearman(xs, ys), 4)})
    rhos = [r["rho"] for r in rows]
    out = {"probe": "peermom_sig vs GridCF-D knn_score（同日截面）",
           "per_month": rows,
           "months": len(rhos),
           "mean_rho": round(float(np.mean(rhos)), 4) if rhos else None,
           "median_rho": round(float(np.median(rhos)), 4) if rhos else None,
           "abs_mean_rho": round(float(np.mean([abs(r) for r in rhos])), 4) if rhos else None,
           "max_abs_rho": round(float(max(abs(r) for r in rhos)), 4) if rhos else None,
           "frac_negative": round(float(np.mean([r < 0 for r in rhos])), 3) if rhos else None}
    json.dump(out, open(f"{DC}/orthogonality.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    print("ORTHO_DONE")


if __name__ == "__main__":
    main()
