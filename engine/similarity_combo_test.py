#!/usr/bin/env python3
"""engine/similarity_combo_test.py — 信号级组合验证（第三波任务②）

回答用户「新搞的（协同过滤打分/RES-08 影子因子）和之前的（三条存活线）能不能组合」。

方法：
  事件底座 = similarity_features.npz 行（514 万股票日，flags 携带三条存活线口径：
    bit0 深档个股件→簇门≥5 后 = 深档低位v2 生产口径、bit1 预增低位池、bit2 反转族）。
  过滤器/排序器 = factor_census_base.npz 的逐日横截面十分档：
    knn_vote（GridCF OOS 打分，tail=high）+ RES-08 四条影子候选
    （ivol20 / pv_corr_ov10 / pv_corr_cv20 / volcv20，tail 全=low 取低十分档）。
  样本窗 = OOS 2023-01 起（knn_vote 样本外段；knn 过滤器全表只在此窗有效）。
  增量 = 「信号触发且过滤通过」vs「信号触发全部」的 T+1/T+5 均值差（pp），
  日历时间 t_NW（lag=5，日度组合超额=过滤组日均-当日宇宙均，防同日扎堆稀释假象）。

纪律：多重检验计数如实报（3线 × 8过滤 × 2持有期 = 48 格 + 排序器 3 格 = 51 次）；
只读既有数据资产，零生产改动。产出 data/similarity_combo_20261016.json。
用法：.venv/bin/python engine/similarity_combo_test.py
"""
import json, math, bisect, sys, time
from pathlib import Path
from collections import defaultdict

import numpy as np

ROOT = Path("/opt/data/fenjue")
FEAT_NPZ = ROOT / "data/similarity_features.npz"
BASE_NPZ = ROOT / "data/factor_census_base.npz"
OUT = ROOT / "data/similarity_combo_20261016.json"
OOS_START = "2023-01-01"
MIN_N = 100          # 格最小样本（信号线×过滤器交叉后容易碎）
N_TRIALS = 3 * 8 * 2 + 3

sys.path.insert(0, str(ROOT / "engine"))
import similarity_engine as se


def _nw_t(x, lag=5):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < lag + 30:
        return None
    m = x.mean()
    lrv = ((x - m) ** 2).mean()
    for k in range(1, lag + 1):
        lrv += 2 * (1 - k / (lag + 1)) * ((x[k:] - m) * (x[:-k] - m)).mean()
    return round(float(m / math.sqrt(lrv / n)), 2) if lrv > 0 else None


def _stats(rs):
    rs = rs[np.isfinite(rs)]
    if len(rs) < MIN_N:
        return None
    return {"n": int(len(rs)), "win%": round(100 * float((rs > 0).mean()), 1),
            "mean%": round(100 * float(rs.mean()), 3),
            "med%": round(100 * float(np.median(rs)), 3)}


def _cal_t(sel_mask, r, eidx, uni):
    """日历时间口径：入选事件的日度等权组合 - 当日宇宙均值，NW t。"""
    by = defaultdict(list)
    for e, rr in zip(eidx[sel_mask], r[sel_mask]):
        if np.isfinite(rr):
            by[int(e)].append(float(rr))
    series = np.array([np.mean(v) - uni[d] for d, v in sorted(by.items()) if d in uni])
    return {"天数": int(len(series)), "日均超额pp": round(100 * float(series.mean()), 3),
            "t_NW": _nw_t(series)} if len(series) else None


def main():
    t0 = time.time()
    z = np.load(FEAT_NPZ)
    didx, eidx, code, flags = z["didx"], z["eidx"], z["code"], z["flags"]
    R = z["R"]
    calendar = z["calendar"].tolist()
    fg = se._flags_gated(flags, didx)
    del z

    zb = np.load(BASE_NPZ)
    assert zb["calendar"].tolist() == calendar, "日历不一致"
    c2j = {int(c): j for j, c in enumerate(zb["codes"].tolist())}
    js = np.array([c2j.get(int(c), -1) for c in code])
    okmap = js >= 0

    DEC = {}
    for f in ["knn_vote", "ivol20", "pv_corr_ov10", "pv_corr_cv20", "volcv20"]:
        M = zb[f"dec_{f}"]
        d = np.full(len(didx), 255, dtype=np.uint8)
        d[okmap] = M[didx[okmap], js[okmap]]
        DEC[f] = d
    print(f"[combo] rows={len(didx)} mapped={okmap.mean():.2%} load={time.time()-t0:.0f}s", flush=True)

    sp = bisect.bisect_left(calendar, OOS_START)
    oos = didx >= sp
    uni = {}  # 每持有期: eidx -> 当日宇宙均值
    for hi in (0, 1):
        r = R[:, hi]
        ok = np.isfinite(r) & okmap
        ue, uinv = np.unique(eidx[ok], return_inverse=True)
        um = np.bincount(uinv, weights=r[ok]) / np.maximum(np.bincount(uinv), 1)
        uni[hi] = dict(zip(ue.tolist(), um.tolist()))

    LINES = {"深档v2_簇门后": (fg & 1) != 0, "预增低位池": (flags & 2) != 0,
             "反转族": (flags & 4) != 0}
    knn = DEC["knn_vote"].astype(int)
    FILTERS = {   # dec 编码 0..9（0=最低档, 9=最高档）, 255=NaN（<= 比较天然排除）
        "全部信号": np.ones(len(didx), dtype=bool),
        "knn_top20%(dec≥8)": knn >= 8,
        "knn_top10%(dec=9)": knn == 9,
        "knn_bottom20%(dec≤1,反向别碰)": (knn <= 1),
        "ivol20_low(dec≤2)": DEC["ivol20"] <= 2,
        "pv_corr_cv20_low(dec≤2)": DEC["pv_corr_cv20"] <= 2,
        "pv_corr_ov10_low(dec≤2)": DEC["pv_corr_ov10"] <= 2,
        "volcv20_low(dec≤2)": DEC["volcv20"] <= 2,
    }

    out = {"_meta": {"built": time.strftime("%Y-%m-%d %H:%M"), "oos_start": OOS_START,
                     "min_cell_n": MIN_N, "n_trials": N_TRIALS,
                     "口径": "次日开盘入/一字开剔/净0.15%；knn_vote=GridCF OOS(2023+)；RES-08 四因子取低十分档(档≤3)",
                     "判读": "t_NW>=3 且事件级增量>0 才算过滤真增量；多重检验 51 格，需 DSR 意识"}}
    for lname, lmask in LINES.items():
        base_mask = lmask & oos & okmap
        res = {"events_oos": int(base_mask.sum()), "filters": {}}
        base_t = {}
        for fname, fmask in FILTERS.items():
            m = base_mask & fmask
            cell = {"n": int(m.sum())}
            for hi, hh in ((0, "T+1"), (1, "T+5")):
                r = R[:, hi]
                s = _stats(r[m])
                if s is None:
                    cell[hh] = None
                    continue
                ct = _cal_t(m, r, eidx, uni[hi])
                if fname == "全部信号":
                    base_t[hh] = s["mean%"]
                s["增量pp_vs全部"] = round(s["mean%"] - base_t.get(hh, s["mean%"]), 3) if fname != "全部信号" else 0.0
                s["日历"] = ct
                cell[hh] = s
            res["filters"][fname] = cell
        # 排序器视角：线内 knn 高分半 vs 低分半（dec 0..9，≥5 vs ≤4 对半切）
        hi_m = base_mask & (knn >= 5)
        lo_m = base_mask & (knn <= 4)
        r5 = R[:, 1]
        res["排序器_knn高分半vs低分半_T5"] = {
            "高分半(dec≥5)": _stats(r5[hi_m]), "低分半(dec≤4)": _stats(r5[lo_m]),
            "日历_t_NW_高分半": _cal_t(hi_m, r5, eidx, uni[1])}
        out[lname] = res
        print(f"[combo] {lname} n={res['events_oos']} done {time.time()-t0:.0f}s", flush=True)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[combo] DONE -> {OUT} elapsed={time.time()-t0:.0f}s")

    # 控制台摘要矩阵
    for lname in LINES:
        print(f"\n== {lname} (OOS n={out[lname]['events_oos']})")
        for fname, cell in out[lname]["filters"].items():
            t5 = cell.get("T+5")
            if t5 is None:
                print(f"  {fname:<28} n={cell['n']:<6} 样本不足")
                continue
            cal = t5["日历"] or {}
            print(f"  {fname:<28} n={t5['n']:<6} T+5 {t5['mean%']:+.3f}% ({t5['增量pp_vs全部']:+.3f}pp) "
                  f"win {t5['win%']}%  日历超额 {cal.get('日均超额pp')}pp t_NW={cal.get('t_NW')}")


if __name__ == "__main__":
    main()
