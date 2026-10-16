#!/usr/bin/env python3
# engine/guba_sentiment_study.py — 股吧人气热度 × 前向收益 截面事件研究（RES-09 先导）
# 数据: data/guba_rank/<code>.json (东财人气榜 366 历日历史, 晨间公布=PIT安全)
# 口径: 主口径 close[t]→close[t+h] 超额(剔当日全宇宙均值=剔β); fwd returns 另外存原始值
# 窗口: 2025-10-16..2026-10-15 (kcache 最后一根 bar) —— 仅 1 年, 先导级非 8 年级
# 内存策略: 流式逐文件读 kcache + numpy 紧凑数组(不 load_universe, 避免 15GB 机器 OOM)
# 输出: data/guba_sentiment_study_<today>.json
import json, math, time, glob
from pathlib import Path
from collections import defaultdict
from datetime import date as _d, timedelta

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RANK_DIR = ROOT / "data" / "guba_rank"
KC = ROOT / "data" / "big_kcache"
HORIZONS = [1, 2, 3, 5, 10, 20]
W0, W1 = "2025-10-16", "2026-10-15"

def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")

def nw_t(day_ids, vals, n_days, lag=5):
    """日历时间 Newey-West t: 先按日聚合均值成序列"""
    s = np.bincount(day_ids, weights=vals, minlength=n_days)
    c = np.bincount(day_ids, minlength=n_days).astype(float)
    ok = c > 0
    x = s[ok] / c[ok]
    n = len(x)
    if n < 30:
        return float("nan"), n
    m = x.mean()
    d = x - m
    var0 = (d ** 2).mean()
    lrv = var0
    for l in range(1, lag + 1):
        cov = (d[l:] * d[:-l]).mean()
        lrv += 2 * (1 - l / (lag + 1)) * cov
    if lrv <= 0:
        return float("nan"), n
    return float(m / math.sqrt(lrv / n)), n

def main():
    t0 = time.time()
    # 载入人气历史(轻)
    rank_map = {}
    for fp in RANK_DIR.glob("*.json"):
        d = json.loads(fp.read_text())
        rank_map[d["code"]] = {r[0]: r[1] for r in d["rows"]}
    print(f"rank files {len(rank_map)}, {time.time()-t0:.0f}s", flush=True)

    # 全宇宙交易日历(窗口内) — 从参考票取
    ref = json.loads((KC / "000001.json").read_text())
    days_all = [k["date"] for k in ref if W0 <= k["date"] <= W1]
    day_idx = {d: i for i, d in enumerate(days_all)}
    ND = len(days_all)
    print(f"trading days {ND}: {days_all[0]}..{days_all[-1]}", flush=True)

    cols = {k: [] for k in ["di", "code_i", "rank", "rkc", "vr", "r20", "pct", "below60", "reg"]
            + [f"fcc{h}" for h in HORIZONS] + [f"foc{h}" for h in HORIZONS]}
    codes = sorted(rank_map)
    code_i = {c: i for i, c in enumerate(codes)}

    for n, code in enumerate(codes):
        rm = rank_map[code]
        fp = KC / f"{code}.json"
        if not fp.exists():
            continue
        ks = json.loads(fp.read_text())
        if len(ks) < 300:
            continue
        dates = [k["date"] for k in ks]
        c = [k["close"] for k in ks]
        o = [k["open"] for k in ks]
        v = [k.get("volume", 0) or 0 for k in ks]
        didx = {d: i for i, d in enumerate(dates)}
        pre = [0.0]
        for x in c:
            pre.append(pre[-1] + x)
        for d in days_all:
            i = didx.get(d)
            if i is None or i + 1 >= len(ks) or c[i] <= 0 or d not in rm:
                continue
            rk = rm[d]
            y, m, dd = int(d[:4]), int(d[5:7]), int(d[8:10])
            lags = [rm[p] for p in ((_d(y, m, dd) - timedelta(days=k)).isoformat() for k in range(1, 6)) if p in rm]
            rkc = (mean(lags) - rk) if len(lags) >= 3 else None
            v5 = [x for x in v[max(0, i - 5):i] if x > 0]
            vr = (v[i] / mean(v5)) if v5 and v[i] > 0 else None
            r20 = (c[i] / c[i - 20] - 1) if i >= 20 and c[i - 20] > 0 else None
            ma60 = (pre[i + 1] - pre[i - 59]) / 60 if i >= 59 else None
            cols["di"].append(day_idx[d]); cols["code_i"].append(code_i[code])
            cols["rank"].append(rk); cols["rkc"].append(rkc if rkc is not None else np.nan)
            cols["vr"].append(vr if vr is not None else np.nan)
            cols["r20"].append(r20 if r20 is not None else np.nan)
            cols["pct"].append(c[i] / c[i - 1] - 1 if i > 0 and c[i - 1] > 0 else np.nan)
            cols["below60"].append(1 if (ma60 is not None and c[i] < ma60) else 0)
            cols["reg"].append(-1)  # 回填
            for h in HORIZONS:
                cols[f"fcc{h}"].append(c[i + h] / c[i] - 1 if i + h < len(ks) else np.nan)
                o1 = o[i + 1]
                cols[f"foc{h}"].append(c[i + h] / o1 - 1 if (o1 > c[i] * 0.905 and i + h < len(ks)) else np.nan)
        if (n + 1) % 500 == 0:
            print(f"  scan {n+1}/{len(codes)} rows={len(cols['di'])} {time.time()-t0:.0f}s", flush=True)

    A = {k: np.array(v_, dtype=np.float32) for k, v_ in cols.items()}
    A["di"] = A["di"].astype(np.int32); A["code_i"] = A["code_i"].astype(np.int32)
    A["below60"] = A["below60"].astype(np.int8)
    N = len(A["di"])
    print(f"events {N}, {time.time()-t0:.0f}s", flush=True)

    # regime
    tl = json.loads((ROOT / "data" / "regime_timeline.json").read_text())
    reg_days = {r["date"]: r["regime"] for r in tl}
    reg_names = sorted(set(reg_days.values()))
    reg_i = {r: i for i, r in enumerate(reg_names)}
    A["reg"] = np.array([reg_i.get(reg_days.get(days_all[int(i)]), -1) for i in A["di"]], dtype=np.int16)
    # 按日截面 rank_pct + 剔β(次日等权均值)
    order = np.lexsort((A["rank"], A["di"]))
    rank_pct = np.empty(N, dtype=np.float32)
    cnt = np.bincount(A["di"], minlength=ND)
    starts = np.concatenate([[0], np.cumsum(cnt)[:-1]])
    for d in range(ND):
        n = cnt[d]
        if n == 0:
            continue
        sl = order[starts[d]:starts[d] + n]
        m = max(n - 1, 1)
        rank_pct[sl] = 1 - np.arange(n, dtype=np.float32) / m
    A["rank_pct"] = rank_pct
    for h in HORIZONS:
        v = A[f"fcc{h}"]
        ok = ~np.isnan(v)
        s = np.bincount(A["di"][ok], weights=v[ok], minlength=ND)
        c = np.bincount(A["di"][ok], minlength=ND).astype(float)
        mu = np.divide(s, c, out=np.full(ND, np.nan), where=c > 0)
        A[f"ex{h}"] = v - mu[A["di"]]
        vo = A[f"foc{h}"]
        oko = ~np.isnan(vo)
        so = np.bincount(A["di"][oko], weights=vo[oko], minlength=ND)
        co = np.bincount(A["di"][oko], minlength=ND).astype(float)
        muo = np.divide(so, co, out=np.full(ND, np.nan), where=co > 0)
        A[f"exo{h}"] = vo - muo[A["di"]]

    # 落紧凑事件矩阵（供 verdict/placebo/复算复用，不必二次重扫 kcache）
    npz_keys = ["di", "code_i", "rank", "rank_pct", "below60", "reg", "vr", "r20", "pct", "rkc"]
    npz_keys += [f"ex{h}" for h in HORIZONS] + [f"exo{h}" for h in HORIZONS]
    savez = {k: A[k] for k in npz_keys if k in A}
    savez["days"] = np.array(days_all, dtype=object)
    savez["codes"] = np.array(codes, dtype=object)
    savez["caliber"] = np.array(["open=T+1开盘买(exo*), close=T收盘买(ex*)"], dtype=object)
    np.savez(str(ROOT / "data" / "guba_sentiment_events_20261016.npz"), **savez)
    print("saved events npz", flush=True)

    def stats(mask, label, caliber="open"):
        """caliber='open' = 信号日 T 排名(当日 23:00 发布) → T+1 开盘买 → T+h 收盘卖 (PIT 合法主口径)
           caliber='close' = T 收盘买 (偷看当日 23:00 发布的信息, 仅作上界参考)"""
        pre = "exo" if caliber == "open" else "ex"
        out = {"label": label, "caliber": caliber, "n": int(mask.sum())}
        for h in HORIZONS:
            x = A[f"{pre}{h}"][mask]
            x = x[~np.isnan(x)]
            if len(x) == 0:
                out[f"T{h}"] = None
                continue
            w = x[x > 0]; l = x[x <= 0]
            t, nd = nw_t(A["di"][mask][~np.isnan(A[f"{pre}{h}"][mask])], x, ND)
            out[f"T{h}"] = {"n": int(len(x)), "win": round(float((x > 0).mean()), 4),
                            "mean_pp": round(float(x.mean()) * 100, 3),
                            "odds": round(float(w.mean() / abs(l.mean())), 2) if len(w) and len(l) else None,
                            "t_cal": (round(t, 2) if t == t else None), "days": nd}
        return out

    res = {"window": [W0, W1], "n_events": N, "n_stocks": len(codes),
           "caliber": "主口径=信号日人气排名(当日23:00发布,getHisProfileList 实证) → 次日开盘买(剔一字跌停开) → T+h 收盘卖, 超额=剔当日全宇宙等权均值; close 口径仅作含前视上界参考",
           "tables": {}}
    dec = {}
    for b in range(10):
        dec[b] = (A["rank_pct"] >= b / 10) & (A["rank_pct"] < (b + 1) / 10 + (1e-6 if b == 9 else 0))
    for cal in ("open", "close"):
        res["tables"][f"decile_cold_to_hot_{cal}"] = [
            stats(dec[b], f"D{b}" + ("(最冷)" if b == 0 else "(最热)" if b == 9 else ""), cal)
            for b in range(10)]
        res["tables"][f"extreme_{cal}"] = [
            stats(A["rank"] <= 100, "top100", cal),
            stats((A["rank"] > 100) & (A["rank"] <= 500), "top101-500", cal),
            stats(A["rank"] > 3000, "rank>3000冷门", cal),
            stats(np.nan_to_num(A["rkc"], nan=-1e9) >= 500, "5日排名飙升≥500位", cal),
            stats(np.nan_to_num(A["rkc"], nan=1e9) <= -500, "5日排名暴跌≥500位", cal),
        ]
    for pos, cond in [("below_ma60", A["below60"] == 1), ("above_ma60", A["below60"] == 0)]:
        res["tables"][f"pos_{pos}"] = [stats(cond & (A["rank_pct"] >= 0.8), f"{pos}×最热20%"),
                                       stats(cond & (A["rank_pct"] <= 0.2), f"{pos}×最冷20%"),
                                       stats(cond, f"{pos}×全部")]
    for i, rg in enumerate(reg_names):
        sub = A["reg"] == i
        res["tables"][f"regime_{rg}"] = [
            stats(sub & (A["rank_pct"] >= 0.8), f"{rg}×最热20%"),
            stats(sub & (A["rank_pct"] <= 0.2), f"{rg}×最冷20%"),
            stats(sub, f"{rg}×全部")]
    # 双变量正交体检(open 口径): 热度三分 × 量比三分 / 位置内热度 的 T+5 超额
    def tertile(v):
        """按日截面三分位: 0/1/2; NaN → -1"""
        out = np.full(len(v), -1, dtype=np.int8)
        for d in range(ND):
            m = (A["di"] == d) & ~np.isnan(v)
            if m.sum() < 30:
                continue
            x = v[m]
            q1, q2 = np.nanquantile(x, [1 / 3, 2 / 3])
            ii = np.where(m)[0]
            out[ii] = np.where(x <= q1, 0, np.where(x <= q2, 1, 2))
        return out
    triple = {}
    for name, v in [("vr", A["vr"]), ("r20", A["r20"]), ("pct", A["pct"])]:
        t3 = tertile(v)
        a3 = tertile(A["rank_pct"])
        for i in range(3):
            for j in range(3):
                m = (t3 == j) & (a3 == i)
                x = A["exo5"][m]; x = x[~np.isnan(x)]
                if len(x) < 200:
                    continue
                triple[f"{name}_Q{j+1}×热度_Q{i+1}"] = {
                    "n": int(len(x)), "T5_pp": round(float(x.mean()) * 100, 3),
                    "win": round(float((x > 0).mean()), 4)}
    res["tables"]["two_way_orthogonality_T5"] = triple

    # 正交性: rank_pct 与 vr / r20 / 当日涨跌 的日截面 spearman 均值
    def daily_spearman(a, b):
        cors = []
        for d in range(ND):
            m = (A["di"] == d) & ~np.isnan(a) & ~np.isnan(b)
            if m.sum() < 50:
                continue
            xa, xb = a[m], b[m]
            ra = np.argsort(np.argsort(xa)).astype(float); rb = np.argsort(np.argsort(xb)).astype(float)
            ra -= ra.mean(); rb -= rb.mean()
            den = math.sqrt((ra ** 2).sum() * (rb ** 2).sum())
            if den > 0:
                cors.append(float((ra * rb).sum() / den))
        return (round(mean(cors), 4), len(cors))
    res["orthogonality"] = {
        "spearman(rank_pct,vr)": daily_spearman(A["rank_pct"], A["vr"]),
        "spearman(rank_pct,r20)": daily_spearman(A["rank_pct"], A["r20"]),
        "spearman(rank_pct,当日涨跌)": daily_spearman(A["rank_pct"], A["pct"]),
        "top100中MA60下占比": round(float((A["below60"][A["rank"] <= 100]).mean()), 4),
        "全样本MA60下占比": round(float(A["below60"].mean()), 4),
    }
    res["_meta"] = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
                    "data_snapshot": W1, "inputs": ["data/guba_rank/*", "data/big_kcache/*",
                                                    "data/regime_timeline.json"],
                    "owner": "engine.guba_sentiment_study"}
    out = ROOT / "data" / f"guba_sentiment_study_{time.strftime('%Y%m%d')}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print("saved", out, f"{time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main()
