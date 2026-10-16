#!/usr/bin/env python3
"""三连阴金股变体 KNN 邻居审计·低内存版（2026-10-15 卡 t_60428c85）。

口径与 engine/similarity_engine.py KNN 一致：连续 11 维学习期标准化 + regime one-hot，
K=2000，w=1/(1+d²/15)，T+1/5/20 加权均值。学习池 = didx < 2026-01-01。
低内存：复合键 searchsorted 代替 dict、LB=16384 分块、C/D 组确定性抽 3000。
"""
import json, time, bisect, gc
import numpy as np

ROOT = "/opt/data/fenjue"
NDIM, K, LB = 15, 2000, 16384

z = np.load(f"{ROOT}/data/similarity_features.npz")
F = z["F"]; R = z["R"]; didx = z["didx"]; code = z["code"]
cal = z["calendar"].tolist()
cut = bisect.bisect_left(cal, "2026-01-01")

pool_mask = didx < cut
Xl = F[pool_mask].copy()          # 290MB，唯一大副本
Rl = R[pool_mask]
mu = Xl[:, :11].mean(0); sd = Xl[:, :11].std(0); sd[sd == 0] = 1.0
Xl[:, :11] = (Xl[:, :11] - mu) / sd
nl2 = (Xl ** 2).sum(1)
print(f"学习池 {len(Xl)} 行", flush=True)

ckey = code.astype(np.int64) * 100000 + didx.astype(np.int64)
order = np.argsort(ckey)
ckey_s = ckey[order]
del ckey; gc.collect()

def rows_of(pairs):
    q = []
    for c, d in pairs:
        i = bisect.bisect_left(cal, d)
        q.append(int(c) * 100000 + i if i < len(cal) and cal[i] == d else -1)
    q = np.array(q, dtype=np.int64)
    pos = np.searchsorted(ckey_s, q)
    pos = np.minimum(pos, len(ckey_s) - 1)
    ok = (q >= 0) & (ckey_s[pos] == q)
    return order[pos[ok]], int((~ok).sum())

def knn_predict(Xt_rows):
    Xt = F[Xt_rows].copy()
    Xt[:, :11] = (Xt[:, :11] - mu) / sd
    n = len(Xt)
    out = np.full((n, 3), np.nan, dtype=np.float64)
    for s in range(0, n, 512):
        blk = Xt[s:s + 512]
        bd = np.full((len(blk), K), np.inf, dtype=np.float32)
        bi = np.zeros((len(blk), K), dtype=np.int32)
        first = True
        for t in range(0, len(Xl), LB):
            L = Xl[t:t + LB]
            d = ((blk ** 2).sum(1)[:, None] + nl2[t:t + LB][None, :] - 2 * blk @ L.T).astype(np.float32)
            if first:
                kth = np.argpartition(d, K, axis=1)[:, :K]
                bd = np.take_along_axis(d, kth, 1)
                bi = np.take_along_axis(np.broadcast_to(np.arange(t, t + len(L), dtype=np.int32), d.shape), kth, 1)
                first = False
                continue
            cand = d < bd.max(axis=1)[:, None]
            for r in np.where(cand.any(axis=1))[0]:
                ci = np.where(cand[r])[0]
                alld = np.concatenate([bd[r], d[r, ci]])
                alli = np.concatenate([bi[r], ci + t])
                k = np.argpartition(alld, K)[:K]
                bd[r], bi[r] = alld[k], alli[k]
        w = 1.0 / (1.0 + np.maximum(bd, 0) / NDIM)
        for hi in range(3):
            rn = Rl[bi, hi]
            mm = np.isfinite(rn)
            ws = (w * mm).sum(1)
            out[s:s + len(bd), hi] = np.where(ws > 1e-6, (w * np.where(mm, rn, 0)).sum(1) / np.maximum(ws, 1e-12), np.nan)
        del bd, bi
        gc.collect()
    return out

shadow = [json.loads(l) for l in open(f"{ROOT}/data/claims_shadow.jsonl") if "THREE_DOWN_GOLD" in l]
pairsA = [(r["code"], r["signal_date"]) for r in shadow]
ev = json.load(open(f"{ROOT}/data/tdgold_full_events_20261015.json"))
pairsB = [(r["code"], r["date"]) for r in ev if r["date"] >= "2026-01-01"]
pairsC = [(r["code"], r["date"]) for r in ev if "2023-01-01" <= r["date"] < "2026-01-01"]
pairsD = [(r["code"], r["date"]) for r in ev if r["date"] < "2023-01-01"]
rng = np.random.default_rng(42)
if len(pairsC) > 3000:
    pairsC = [pairsC[i] for i in rng.choice(len(pairsC), 3000, replace=False)]
if len(pairsD) > 3000:
    pairsD = [pairsD[i] for i in rng.choice(len(pairsD), 3000, replace=False)]

groups = {"A_shadow_0928+": pairsA, "B_2026": pairsB, "C_2023_25": pairsC, "D_2020_22": pairsD}
report = {}
for name, pairs in groups.items():
    rows, miss = rows_of(pairs)
    t0 = time.time()
    pred = knn_predict(rows)
    out = {"n_pairs": len(pairs), "matched": int(len(rows)), "miss": miss}
    for hi, tag in enumerate(("r1", "r5", "r20")):
        p = pred[:, hi]; p = p[np.isfinite(p)]
        out[f"knn_{tag}_mean"] = round(float(np.mean(p)), 5) if len(p) else None
        out[f"knn_{tag}_win"] = round(float(np.mean(p > 0)), 4) if len(p) else None
        rr = R[rows, hi]; rr = rr[np.isfinite(rr)]
        out[f"real_{tag}_mean"] = round(float(np.mean(rr)), 5) if len(rr) else None
        out[f"real_{tag}_win"] = round(float(np.mean(rr > 0)), 4) if len(rr) else None
        out[f"real_{tag}_n"] = int(len(rr))
    fq = F[rows]
    out["feat_depth60"] = round(float(np.mean(fq[:, 0])), 4)
    out["feat_ret20"] = round(float(np.mean(fq[:, 3])), 4)
    out["feat_volr5"] = round(float(np.mean(fq[:, 6])), 4)
    out["feat_regime"] = {g: round(float(np.mean(fq[:, 11 + q])), 3) for q, g in enumerate(["平淡期", "妖股期", "恐慌期", "主线期"])}
    report[name] = out
    print(f"{name}: matched {len(rows)}/{len(pairs)} miss={miss} {time.time()-t0:.0f}s", flush=True)
    json.dump(report, open(f"{ROOT}/data/tdgold_knn_audit_20261015.json", "w"), ensure_ascii=False, indent=1)
    del rows, pred
    gc.collect()

r1s = [r["r1"] for r in shadow if r["r1"] is not None]
r5s = [r["r5"] for r in shadow if r["r5"] is not None]
report["A_shadow_0928+"]["shadow_real"] = {
    "r1": {"n": len(r1s), "mean": round(float(np.mean(r1s)), 5), "win": round(float(np.mean(np.array(r1s) > 0)), 4)},
    "r5": {"n": len(r5s), "mean": round(float(np.mean(r5s)), 5), "win": round(float(np.mean(np.array(r5s) > 0)), 4)}}

json.dump(report, open(f"{ROOT}/data/tdgold_knn_audit_20261015.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(report, ensure_ascii=False, indent=1))
