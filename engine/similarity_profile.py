#!/usr/bin/env python3
"""engine/similarity_profile.py — GridCF 分桶反推存活线信号日共性画像（第三波任务③）

与金股卡共享方法（各做各的线）：用 514 万股票日特征矩阵反推三条存活线
（深档v2簇门后 / 预增低位池 / 反转族）信号日的状态画像，回答
「注册口径有没有漏变量」——某特征在线内事件 vs 全宇宙有强分离（|Cohen d|≥0.3），
但该变量不在注册探测器口径里 = 漏变量候选（只登记，不进生产，要走 REGISTRY+闸门）。

注册口径用的变量（判漏基准）：
  深档v2     = day_pct(≤-9.8%) + depth60(≤-0.35) + 簇门≥5
  预增低位池 = 预增事件 + dhigh60(≤-20%) + log_cap(<50亿)
  反转族     = day_pct(≤-3%) + dhigh60(≤-20%)
口径外的画像分离只是「描述」不是 edge（#画像≠edge 纪律），输出供假设生成。

产出 data/similarity_profile_20261016.json
用法：.venv/bin/python engine/similarity_profile.py
"""
import json, time, sys
from pathlib import Path
from collections import Counter

import numpy as np

ROOT = Path("/opt/data/fenjue")
FEAT_NPZ = ROOT / "data/similarity_features.npz"
OUT = ROOT / "data/similarity_profile_20261016.json"
NCONT = 11

sys.path.insert(0, str(ROOT / "engine"))
import similarity_engine as se

FEATS = se.FEATURE_NAMES
DETECTOR_VARS = {
    "深档v2_簇门后": {"day_pct", "depth60"},
    "预增低位池": {"dhigh60", "log_cap"},
    "反转族": {"day_pct", "dhigh60"},
}


def _profile(mask, F, reg):
    """事件组 vs 全宇宙的逐特征画像：mean/median/Cohen d + 十分档富集度。"""
    n_ev = int(mask.sum())
    prof = {"n": n_ev, "features": {}}
    for ci, name in enumerate(FEATS):
        a = F[mask, ci]
        u = F[:, ci]
        a, u = a[np.isfinite(a)], u[np.isfinite(u)]
        if len(a) < 50:
            continue
        sd = float(u.std()) or 1.0
        d = float((a.mean() - u.mean()) / sd)
        # 十分档富集：事件落入全宇宙顶/底十分档的占比
        lo, hi = np.quantile(u, [0.1, 0.9])
        prof["features"][name] = {
            "事件均值": round(float(a.mean()), 4), "宇宙均值": round(float(u.mean()), 4),
            "事件中位": round(float(np.median(a)), 4),
            "cohen_d": round(d, 3),
            "底10%档占比%": round(100 * float((a <= lo).mean()), 1),
            "顶10%档占比%": round(100 * float((a >= hi).mean()), 1),
        }
    rc = Counter(reg[mask].tolist())
    prof["regime分布%"] = {se.REGIMES[k]: round(100 * v / n_ev, 1) for k, v in sorted(rc.items())}
    return prof


def main():
    t0 = time.time()
    z = np.load(FEAT_NPZ)
    F, flags, didx = z["F"], z["flags"], z["didx"]
    se._prep(F, didx, z["ind"], z["day_pct"], z["eidx"], z["R"])  # 补 ind_pct 列
    fg = se._flags_gated(flags, didx)
    reg = np.argmax(F[:, NCONT:], 1)
    print(f"[profile] rows={len(F)} load={time.time()-t0:.0f}s", flush=True)

    LINES = {"深档v2_簇门后": (fg & 1) != 0, "预增低位池": (flags & 2) != 0,
             "反转族": (flags & 4) != 0}
    out = {"_meta": {"built": time.strftime("%Y-%m-%d %H:%M"),
                     "口径": "全历史 2019-2026 信号日画像；cohen_d=事件均值-宇宙均值/宇宙std；"
                            "漏变量=|d|>=0.3 且不在注册探测器口径（仅假设生成，非 edge 证据）",
                     "detector_vars": {k: sorted(v) for k, v in DETECTOR_VARS.items()}}}
    for lname, mask in LINES.items():
        prof = _profile(mask, F, reg)
        used = DETECTOR_VARS[lname]
        leaks = []
        for name, p in prof["features"].items():
            if name in used:
                continue
            if abs(p["cohen_d"]) >= 0.3:
                leaks.append({"feature": name, "cohen_d": p["cohen_d"],
                              "底档%": p["底10%档占比%"], "顶档%": p["顶10%档占比%"]})
        prof["漏变量候选(|d|>=0.3且口径外)"] = sorted(leaks, key=lambda x: -abs(x["cohen_d"]))
        out[lname] = prof
        print(f"[profile] {lname} n={prof['n']} 漏变量候选={len(leaks)} {time.time()-t0:.0f}s", flush=True)
        for lk in prof["漏变量候选(|d|>=0.3且口径外)"]:
            print(f"    {lk['feature']:<10} d={lk['cohen_d']:+.2f} 底档{lk['底档%']}% 顶档{lk['顶档%']}%")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[profile] DONE -> {OUT} elapsed={time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
