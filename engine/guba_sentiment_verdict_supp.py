#!/usr/bin/env python3
# engine/guba_sentiment_verdict_supp.py — 唯一存活格 below60×热20% T+20 的加固体检（预登记外，属终审件）
# 检查项: ①两段同号 ②日内 rank 洗牌置换 1000 次 ③不重叠窗口（每 20 交易日抽样）去自相关 ④与深档 v2 事件重叠
# 输出: 追加 data/guba_sentiment_verdict_<today>.json 的 survivor_hardening 段
import glob, json, math, time, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from guba_sentiment_study import nw_t  # noqa: E402

CELL = "below60×热20%"
H = 20
N_PERM = 1000
SEED = 20261016


def main():
    t0 = time.time()
    z = np.load(ROOT / "data" / "guba_sentiment_events_20261016.npz", allow_pickle=True)
    A = {k: z[k] for k in z.files if k not in ("days", "codes", "caliber")}
    days = [str(x) for x in z["days"].tolist()]
    ND = int(A["di"].max()) + 1
    hot20 = A["rank_pct"] >= 0.8
    b60 = A["below60"] == 1
    M = b60 & hot20
    v = A[f"exo{H}"]

    # ① 两段（四段更细）同号
    segs = {}
    for lbl, lo, hi in (("H1", 0, ND // 2), ("H2", ND // 2, ND),
                        ("Q1", 0, ND // 4), ("Q2", ND // 4, ND // 2),
                        ("Q3", ND // 2, 3 * ND // 4), ("Q4", 3 * ND // 4, ND)):
        m = M & (A["di"] >= lo) & (A["di"] < hi)
        x = v[m]; x = x[~np.isnan(x)]
        t, nd = nw_t(A["di"][m][~np.isnan(v[m])], x, ND)
        segs[lbl] = {"n": int(len(x)), "mean_pp": round(float(x.mean()) * 100, 4),
                     "win": round(float((x > 0).mean()), 4),
                     "t_nw": (round(t, 2) if t == t else None), "days": nd}

    # ② 日内 rank 洗牌置换: 被打散的是「谁在热榜」标签, 保留 below60 与超额
    rp = A["rank_pct"]
    order = np.argsort(A["di"], kind="stable")
    cnt = np.bincount(A["di"], minlength=ND)
    starts, pos = [], 0
    for d in range(ND):
        starts.append(pos); pos += cnt[d]
    obs = float(v[M & ~np.isnan(v)].mean())
    rng = np.random.default_rng(SEED)
    perm = []
    for _ in range(N_PERM):
        sh = rp[order].copy()
        for d in range(ND):
            n = cnt[d]
            if n < 2:
                continue
            seg = sh[starts[d]:starts[d] + n]
            rng.shuffle(seg)
        inv = np.empty_like(order); inv[order] = np.arange(len(order))
        rp_p = sh[inv]
        m = b60 & (rp_p >= 0.8) & ~np.isnan(v)
        if m.sum() < 500:
            continue
        perm.append(float(v[m].mean()))
    pa = np.array(perm)
    p2 = round(float((np.abs(pa) >= abs(obs)).mean()), 4)  # 双侧
    p_left = round(float((pa <= obs).mean()), 4)  # 负尾（本格方向为负）

    # ③ 不重叠窗口: T+20 只取每 20 交易日的信号日, 消自相关
    keep = set(range(0, ND, H))
    m = M & np.isin(A["di"], list(keep)) & ~np.isnan(v)
    x_nov = v[m]
    t_nov, nd_nov = nw_t(A["di"][m], x_nov, ND)

    # ④ 与深档 v2 事件重叠（深档=跌停+收≤MA60×0.65+簇≥5, 事件文件）
    ov = {"note": "深档 v2 事件清单未找到专用产物时留空"}
    for pat in ("data/deep_low_events*.json", "data/limitdown_deep*.json", "data/depth_events*.json"):
        fps = sorted(glob.glob(str(ROOT / pat)))
        if fps:
            ov = {"file": fps[-1], "note": "文件存在, 结构未解析(本卡不做深档重叠定量)"}
            break

    out = {
        "cell": f"{CELL} T+{H} (open 口径)",
        "segments": segs,
        "all_segments_same_sign": all(s["mean_pp"] < 0 for s in segs.values() if s["n"] > 500),
        "placebo_within_day_rank_shuffle": {"n_perm": len(perm), "seed": SEED,
                                            "obs_mean_pp": round(obs * 100, 4),
                                            "perm_mean_pp": round(float(pa.mean()) * 100, 4),
                                            "perm_p_left(负尾)": p_left, "perm_p_two_sided": p2},
        "non_overlapping_T20": {"n": int(len(x_nov)), "mean_pp": round(float(x_nov.mean()) * 100, 4),
                                "win": round(float((x_nov > 0).mean()), 4),
                                "t_nw": (round(t_nov, 2) if t_nov == t_nov else None), "days": nd_nov},
        "deep_low_overlap": ov,
        "_meta": {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
                  "data_snapshot": days[-1], "owner": "engine.guba_sentiment_verdict_supp",
                  "elapsed_s": round(time.time() - t0, 1)},
    }
    fp = sorted(glob.glob(str(ROOT / "data" / "guba_sentiment_verdict_*.json")))[-1]
    res = json.loads(Path(fp).read_text())
    res["survivor_hardening"] = out
    Path(fp).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps(out, ensure_ascii=False, indent=1))
    print("updated", fp)


if __name__ == "__main__":
    main()
