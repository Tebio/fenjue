#!/usr/bin/env python3
# engine/guba_sentiment_orthogonality.py — 人气热度与既有通道(资金流/GridCF-D/regime/深档)的正交性体检
# 输入: data/guba_sentiment_study_*.json (首跑产出) + data/similarity_gridscore.npz (GridCF-D) + cap_hist
# 输出: 追加写回 data/guba_sentiment_study_<today>.json 的 orthogonality_vs_channels 段
import json, glob, math, time
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
KC = ROOT / "data" / "big_kcache"
W0, W1 = "2025-10-16", "2026-10-15"

def main():
    t0 = time.time()
    zb = np.load(ROOT / "data" / "factor_census_base.npz", allow_pickle=True)
    codes = [str(c) for c in zb["codes"].tolist()]
    calendar = [str(c) for c in zb["calendar"].tolist()]
    print("base matrix", len(codes), len(calendar))
    S = np.load(ROOT / "data" / "similarity_gridscore.npz")["score"]
    di = {d: i for i, d in enumerate(calendar)}
    days = [d for d in calendar if W0 <= d <= W1]

    # 人气 rank_pct (按日截面, 用同一批票)
    rank_map = {}
    for fp in (ROOT / "data" / "guba_rank").glob("*.json"):
        d = json.loads(fp.read_text())
        rank_map[d["code"]] = {r[0]: r[1] for r in d["rows"]}

    cors = []
    cover = []
    for d in days:
        j = di[d]
        rk = np.full(len(codes), np.nan)
        for k, c in enumerate(codes):
            v = rank_map.get(c, {}).get(d)
            if v is not None:
                rk[k] = v
        sc = S[j, :]
        m = ~np.isnan(rk) & ~np.isnan(sc)
        if m.sum() < 50:
            continue
        a = np.argsort(np.argsort(rk[m])).astype(float)
        b = sc[m]
        a -= a.mean(); b = b - b.mean()
        den = math.sqrt((a ** 2).sum() * (b ** 2).sum())
        if den > 0:
            cors.append(float((a * b).sum() / den))
        cover.append(float(m.sum() / len(codes)))
    out = {
        "gridcf_d_daily_spearman(rank_pct, knn_t5_score)": [round(float(np.mean(cors)), 4), len(cors)],
        "note": "GridCF-D 覆盖仅 OOS(2023+) 且需学习期分箱; 负相关=热度高↔引擎低分(反向)",
        "guba_rank_coverage_of_universe": round(float(np.mean(cover)), 4),
        "elapsed_s": round(time.time() - t0),
    }
    fp = sorted(glob.glob(str(ROOT / "data" / "guba_sentiment_study_*.json")))[-1]
    res = json.loads(Path(fp).read_text())
    res["orthogonality_vs_channels"] = out
    Path(fp).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps(out, ensure_ascii=False, indent=1))
    print("updated", fp)

if __name__ == "__main__":
    main()
