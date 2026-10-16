#!/usr/bin/env python3
# engine/guba_sentiment_verdict.py — 股吧舆情（东财人气榜）可回测性裁决 + 门槛检验（RES-09 先导收口）
#
# 输入: data/guba_sentiment_events_20261016.npz（engine/guba_sentiment_study.py 落盘）
#       字段: di(日序) code_i rank rank_pct below60 reg vr r20 pct ex{h}(close口径超额) exo{h}(open口径超额) days codes
# 窗口: 2025-10-16..2026-10-15（366 历日 / 241 交易日）—— 深度上限=东财 getHisList 只给 366 历日
#
# 【预登记假设族，跑前写死（不得事后挑格）】共 23 条：
#   A 热端反向（5）: D9 T+5 / D9 T+10 / top100 T+5 / top100 T+10 / top100 T+20
#   B 冷端正向（5）: D0 T+5 / D0 T+10 / D0 T+20 / rank>3000 T+10 / rank>3000 T+20
#   C 位置交互（6）: below_ma60×热20% T+5/T+10/T+20 ; above_ma60×冷20% T+5/T+10/T+20
#   D 排名变动（4）: 5日飙升≥500 T+1/T+5 ; 5日暴跌≥500 T+1/T+5
#   E 双变量正交（3）: vr_Q3×热度_Q3 T+5 ; r20_Q3×热度_Q3 T+5 ; pct_Q3×热度_Q3 T+5
# 存活判据（三闸，与项目 #291 同门槛）: |t_NW|≥3.0（Harvey, 23 条正式假设）+ 两段同号 + 置换 p≤0.05
# 置换: 1000 次「日内 rank 洗牌」（保留每日截面样本数与超额分布，只打散热度↔收益的配对）——
#       检验的是「热度标签本身有信息」而不是「样本被切过」
# 输出: data/guba_sentiment_verdict_<today>.json（含 _meta 可复现锚）
import json, math, time, sys
from pathlib import Path
from collections import defaultdict

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from guba_sentiment_study import nw_t  # noqa: E402  复用 NW 日历 t

HORIZONS = [1, 2, 3, 5, 10, 20]
NPZ = ROOT / "data" / "guba_sentiment_events_20261016.npz"
N_PERM = 1000
SEED = 20261016


def load():
    z = np.load(NPZ, allow_pickle=True)
    A = {k: z[k] for k in z.files if k not in ("days", "codes", "caliber")}
    days = [str(x) for x in z["days"].tolist()]
    return A, days


def tercile_by_day(A, v):
    """按日截面三分位 0/1/2, NaN→-1"""
    out = np.full(len(v), -1, dtype=np.int8)
    di = A["di"]
    for d in range(int(di.max()) + 1):
        m = (di == d) & ~np.isnan(v)
        if m.sum() < 30:
            continue
        x = v[m]
        q1, q2 = np.nanquantile(x, [1 / 3, 2 / 3])
        ii = np.where(m)[0]
        out[ii] = np.where(x <= q1, 0, np.where(x <= q2, 1, 2))
    return out


def build_masks(A):
    rp, rk = A["rank_pct"], A["rank"]
    hot20, cold20 = rp >= 0.8, rp <= 0.2
    rkc = A["rkc"] if "rkc" in A else None
    b60 = A["below60"] == 1
    M = {
        "D9热端": rp >= 0.9,
        "top100": rk <= 100,
        "rank>3000": rk > 3000,
        "below60×热20%": b60 & hot20,
        "above60×冷20%": (~b60) & cold20,
    }
    if rkc is not None:
        M["5日飙升≥500"] = np.nan_to_num(rkc, nan=-1e9) >= 500
        M["5日暴跌≥500"] = np.nan_to_num(rkc, nan=1e9) <= -500
    t3 = {}
    for nm, v in (("vr", A["vr"]), ("r20", A["r20"]), ("pct", A["pct"])):
        t3[nm] = tercile_by_day(A, v)
    hot3 = tercile_by_day(A, rp)
    for nm in ("vr", "r20", "pct"):
        M[f"{nm}_Q3×热度_Q3"] = (t3[nm] == 2) & (hot3 == 2)
    return M


def cell(A, mask, h, cal):
    pre = "exo" if cal == "open" else "ex"
    x = A[f"{pre}{h}"][mask]
    ok = ~np.isnan(x)
    if ok.sum() == 0:
        return None
    xs = x[ok]
    t, nd = nw_t(A["di"][mask][ok], xs, int(A["di"].max()) + 1)
    return {"n": int(ok.sum()), "mean_pp": round(float(xs.mean()) * 100, 4),
            "win": round(float((xs > 0).mean()), 4), "t_nw": (round(t, 2) if t == t else None),
            "days": nd}


def main():
    t0 = time.time()
    A, days = load()
    ND = int(A["di"].max()) + 1
    M = build_masks(A)

    # ---- 预登记 23 条 ----
    HYP = ([("D9热端", h) for h in (5, 10)] + [("top100", h) for h in (5, 10, 20)]
           + [("D0冷端", h) for h in (5, 10, 20)] + [("rank>3000", h) for h in (10, 20)]
           + [("below60×热20%", h) for h in (5, 10, 20)]
           + [("above60×冷20%", h) for h in (5, 10, 20)]
           + [("5日飙升≥500", h) for h in (1, 5)] + [("5日暴跌≥500", h) for h in (1, 5)]
           + [(k, 5) for k in ("vr_Q3×热度_Q3", "r20_Q3×热度_Q3", "pct_Q3×热度_Q3")])
    M["D0冷端"] = A["rank_pct"] <= 0.1
    assert len(HYP) == 23, len(HYP)

    rows = []
    for name, h in HYP:
        r_open = cell(A, M[name], h, "open")
        r_close = cell(A, M[name], h, "close")
        rows.append({"bucket": name, "T": h, "open": r_open, "close": r_close,
                     "survive_harvey": bool(r_open and r_open["t_nw"] is not None and abs(r_open["t_nw"]) >= 3.0),
                     "direction": ("负向(反向)" if r_open and r_open["mean_pp"] < 0 else "正向(动量)")})

    # ---- 两段切分（窗口只有 1 年 → 半段 ≈ 120 交易日）----
    half = ND // 2
    seg = {}
    for name, h in HYP:
        s = {}
        for lbl, lo, hi in (("H1(前半年)", 0, half), ("H2(后半年)", half, ND)):
            m = M[name] & (A["di"] >= lo) & (A["di"] < hi)
            s[lbl] = cell(A, m, h, "open")
        seg[f"{name}|T{h}"] = s

    # ---- 置换检验: 日内 rank 洗牌 1000 次（对 top100 与 D9 的 T+5/T+10 均值）----
    rng = np.random.default_rng(SEED)
    di, rp = A["di"], A["rank_pct"]
    order = np.argsort(di, kind="stable")
    starts, cnt = {}, np.bincount(di, minlength=ND)
    pos = 0
    for d in range(ND):
        starts[d] = pos
        pos += cnt[d]
    obs_stats = {}
    for h in (5, 10):
        v = A[f"exo{h}"]
        for nm, thr in (("top100", 0.9),):
            m = rp >= thr
            x = v[m]; x = x[~np.isnan(x)]
            obs_stats[f"{nm}_T{h}"] = float(x.mean())
    perm = {k: [] for k in obs_stats}
    perm_p = {k: [] for k in obs_stats}
    for _ in range(N_PERM):
        shuffled = rp[order].copy()
        # 逐日 Fisher-Yates 洗牌 rank_pct（保持每日样本集合、只打散热度标签）
        for d in range(ND):
            n = cnt[d]
            if n < 2:
                continue
            seg_ = shuffled[starts[d]:starts[d] + n]
            rng.shuffle(seg_)
        inv = np.empty_like(order)
        inv[order] = np.arange(len(order))
        rp_p = shuffled[inv]
        for h in (5, 10):
            v = A[f"exo{h}"]
            for nm, thr in (("top100", 0.9),):
                m = rp_p >= thr
                x = v[m]; x = x[~np.isnan(x)]
                if len(x) < 50:
                    continue
                perm[f"{nm}_T{h}"].append(float(x.mean()))
    for k in perm_p:
        obs = obs_stats[k]
        arr = np.array(perm[k])
        perm_p[k] = round(float((np.abs(arr) >= abs(obs)).mean()), 4) if len(arr) else None

    # ---- DSR（对最强候选按日历时间口径）----
    from law_pipeline import deflated_sharpe
    dsr = {}
    for name, h in HYP:
        m = M[name]
        v = A[f"exo{h}"]
        ok = ~np.isnan(v) & m
        if ok.sum() < 300:
            continue
        s = np.bincount(A["di"][ok], weights=v[ok], minlength=ND)
        c = np.bincount(A["di"][ok], minlength=ND).astype(float)
        ser = s[c > 0] / c[c > 0]
        if len(ser) < 30:
            continue
        mu, sd = ser.mean(), ser.std()
        sk = ((ser - mu) ** 3).mean() / sd ** 3
        ku = ((ser - mu) ** 4).mean() / sd ** 4
        dsr[f"{name}|T{h}"] = {"days": int(len(ser)), "sr_daily": round(float(mu / sd), 4),
                               "DSR(trials=23)": deflated_sharpe(mu / sd, len(ser), sk, ku, trials=23),
                               "DSR(trials=7491+23)": deflated_sharpe(mu / sd, len(ser), sk, ku, trials=7514)}

    # ---- 样本独立性体检 ----
    indep = {}
    for nm in ("top100", "D9热端", "below60×热20%"):
        m = M[nm]
        codes = A["code_i"][m]
        dd = A["di"][m]
        indep[nm] = {"n_events": int(m.sum()), "n_stocks": int(len(np.unique(codes))),
                     "n_days": int(len(np.unique(dd))),
                     "events_per_stock": round(float(m.sum() / max(len(np.unique(codes)), 1)), 1),
                     "top5_stock_share": round(float(np.sort(np.bincount(codes))[::-1][:5].sum() / m.sum()), 4)}

    survivors = [r for r in rows if r["survive_harvey"]]
    out = {
        "window": [days[0], days[-1]], "n_events": int(len(di)), "n_days": ND,
        "history_depth_limit": "东财 getHisList yearType=5 上限 366 历日（实测 yearType=3/4/5/6/10 全 366，yearType=1 仅 182，无更长档）",
        "prereg_hypotheses": len(HYP),
        "gate": "|t_NW|>=3.0 (Harvey, 23 正式假设) + 两段同号 + 日内 rank 洗牌置换 p<=0.05",
        "harvey_survivors_open_caliber": [{k: r[k] for k in ("bucket", "T", "open", "direction")} for r in survivors],
        "rows": rows,
        "segments_half": seg,
        "placebo_within_day_rank_shuffle": {"n_perm": N_PERM, "seed": SEED,
                                            "obs_mean_pp": {k: round(v * 100, 4) for k, v in obs_stats.items()},
                                            "perm_p_two_sided": perm_p},
        "dsr": dsr,
        "sample_independence": indep,
        "_meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "data_snapshot": days[-1],
            "inputs": ["data/guba_sentiment_events_20261016.npz"],
            "owner": "engine.guba_sentiment_verdict",
            "note": "口径 open=信号日(23:00 公布)次日开盘买→T+h 收盘卖, 超额剔当日全宇宙等权均值; close=当日收盘买(含前视上界)",
            "elapsed_s": round(time.time() - t0, 1),
        },
    }
    fp = ROOT / "data" / f"guba_sentiment_verdict_{time.strftime('%Y%m%d')}.json"
    fp.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"saved {fp} ({time.time()-t0:.0f}s)")
    print(f"预登记 {len(HYP)} 条, 过 Harvey 3.0 = {len(survivors)}")
    for r in survivors:
        print(f"  [{r['direction']}] {r['bucket']} T+{r['T']}: {r['open']}")
    strongest = sorted([r for r in rows if r["open"] and r["open"]["t_nw"] is not None],
                       key=lambda r: -abs(r["open"]["t_nw"]))[:5]
    print("最强 5 格:")
    for r in strongest:
        print(f"  {r['bucket']} T+{r['T']} {r['open']['mean_pp']}pp t={r['open']['t_nw']} days={r['open']['days']}")


if __name__ == "__main__":
    main()
