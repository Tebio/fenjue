#!/usr/bin/env python3
"""engine/similarity_engine.py — 协同过滤式「相似样本抄作业」引擎（2026-10-15 过夜研究）

思想（用户纲领）：不猜股票为什么涨，只检索历史上「状态最像」的一批股票日，
抄它们后来 T+1/5/20 的作业。状态向量全部在信号日收盘可知（PIT）：

  连续维（11）：depth60(收/MA60-1) dhigh60(距60日高) ret60 ret20 ret5 day_pct
                volr5(量比=当日量/前5日均量) log_turn(换手log10) log_cap(流通市值log10,PIT)
                ind_pct(板块当日均涨幅) age_norm(regime段龄/10封顶)
  类别维（4）：regime（平淡/妖股/恐慌/主线）

双引擎（任务书允许「标准化欧氏或分桶精确匹配」）：
  ① GridCF 分桶精确匹配（主引擎，O(N) 全量）：regime(4)×depth60(10)×ret60(10)×volr5(5)×log_cap(5)
     复合格，分箱边界=学习期分位数（无泄漏），稀疏格层级回退，格内学习期均值=预测。
  ② KNN 标准化欧氏（验证引擎，方向 A 抽 20 万行）：精确 K=2000 近邻 1/(1+d²/D) 加权，
     阈值剪枝提速，验证两引擎结论一致性。

验证四方向：A=2019-22学→2023-26测，B=反向，C=最后250交易日存活检查，D=无 regime 轴敏感。
每方向产出：lift 十分档单调性表（T+1/5/20）、日历时间组合 NW t、depth 分层内判别力
（防「深档马甲」对照）、已注册存活线重叠审计（深档v2簇门后/预增池/反转族）、随机洗牌对照。

口径：入场=次日开盘，离场=入场+horizon 收盘，净费 0.0015；一字开（|跳空|≥9.5%）剔除；
ST/退（现名）剔除；市值 PIT（不晚于当日的最近日值，law_pipeline 同款）。

用法：
  python3 engine/similarity_engine.py build     # 特征矩阵（每400票全量快照断点续跑）
  python3 engine/similarity_engine.py grid      # GridCF 全方向（分钟级）
  python3 engine/similarity_engine.py knn       # KNN 抽样验证（阈值剪枝）
"""
import json, glob, math, bisect, sys, time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/opt/data/fenjue")
KC, CAP = ROOT / "data/big_kcache", ROOT / "data/cap_hist"
FEAT_NPZ = ROOT / "data/similarity_features.npz"
OUT_JSON = ROOT / "data/similarity_engine_20261015.json"
FEE = 0.0015
REGIMES = ["平淡期", "妖股期", "恐慌期", "主线期"]
NCONT, NDIM = 11, 15
KNN_K = 2000
KNN_ENGINE = "tree"   # KNN 引擎开关：brute(暴力/原始) | tree(sklearn KD/Ball树) | numba(njit合并)；三引擎同结果对拍见 #279（2万点：tree 770s < numba 890s < brute 952s，高负载）
GRID_MIN_N = 200      # 格内最小学习样本数（不足回退上层）
HORIZONS = (1, 5, 20)
FEATURE_NAMES = ["depth60", "dhigh60", "ret60", "ret20", "ret5", "day_pct",
                 "volr5", "log_turn", "log_cap", "ind_pct", "age_norm"]


# ---------------- build ----------------

def _load_json(p):
    return json.loads(open(p).read())


def build():
    t0 = time.time()
    calendar = [k["date"] for k in _load_json(KC / "600000.json")]  # 交易日历锚定参照股（台账纪律）
    d2i = {d: i for i, d in enumerate(calendar)}
    regime_tl = {r["date"]: r["regime"] for r in _load_json(ROOT / "data/regime_timeline_hcap.json")}
    ages = _load_json(ROOT / "data/regime_age.json").get("ages", {})
    ind_map = _load_json(ROOT / "data/industry_map.json")
    ind2i = {s: i for i, s in enumerate(sorted({v["industry"] for v in ind_map.values() if v["industry"]}))}

    pead = defaultdict(list)  # 预增预告事件（重叠审计用）：预增/扭亏/略增≥50%
    for e in _load_json(ROOT / "data/pead_events.json"):
        t, inc = e.get("FORECASTTYPE"), e.get("INCREASEL")
        if t in ("预增", "扭亏") or (t == "略增" and inc is not None and inc >= 50):
            pead[e["SECURITY_CODE"]].append(e["NOTICE_DATE"][:10])

    if FEAT_NPZ.exists():  # 断点：完整快照，续跑直接在数组上 append
        z = np.load(FEAT_NPZ)
        F_l, R_l, D_l, E_l = [z["F"]], [z["R"]], [z["didx"]], [z["eidx"]]
        C_l, G_l, I_l, P_l = [z["code"]], [z["flags"]], [z["ind"]], [z["day_pct"]]
        done = set(z["done"].tolist())
        print(f"[build] resume {len(done)} stocks / {len(F_l[0])} rows")
    else:
        F_l = R_l = D_l = E_l = C_l = G_l = I_l = P_l = []
        done = set()

    files = sorted(glob.glob(str(KC / "*.json")))
    for fp in files:
        code = Path(fp).stem
        if code in done:
            continue
        info = ind_map.get(code)
        name = info["name"] if info else ""
        if "ST" in name or "退" in name:
            continue
        ks = _load_json(fp)
        n = len(ks)
        if n < 300:
            continue
        c = np.array([k["close"] for k in ks])
        o = np.array([k["open"] for k in ks])
        h = np.array([k["high"] for k in ks])
        v = np.array([k.get("volume", 0.0) for k in ks])
        dates = np.array([k["date"] for k in ks])
        didx = np.array([d2i.get(d, -1) for d in dates], dtype=np.int32)

        sc, sv, sh = pd.Series(c), pd.Series(v), pd.Series(h)
        ma60 = sc.rolling(60).mean().to_numpy()
        hh60 = sh.rolling(60).max().to_numpy()
        base5 = sv.shift(1).rolling(5).mean().to_numpy()  # v[i-5..i-1]
        with np.errstate(all="ignore"):
            depth60 = c / ma60 - 1
            dhigh60 = c / hh60 - 1
            ret60 = c / sc.shift(60).to_numpy() - 1
            ret20 = c / sc.shift(20).to_numpy() - 1
            ret5 = c / sc.shift(5).to_numpy() - 1
            day_pct = c / sc.shift(1).to_numpy() - 1
            volr5 = np.where(base5 > 0, v / base5, np.nan)

        capf = CAP / f"{code}.json"
        caps = np.full(n, np.nan)
        if capf.exists():
            rows = sorted(_load_json(capf), key=lambda r: r[0])
            j = np.searchsorted([r[0] for r in rows], dates, side="right") - 1
            ok = j >= 0
            caps[ok] = np.array([r[2] for r in rows])[j[ok]]
        with np.errstate(all="ignore"):
            turn = np.where(caps > 0, v * c / (caps * 1e8), np.nan)
            log_turn = np.where(turn > 0, np.log10(turn), np.nan)
            log_cap = np.where(caps > 0, np.log10(caps), np.nan)

        reg = np.array([REGIMES.index(regime_tl[d]) if regime_tl.get(d) in REGIMES else -1 for d in dates], dtype=np.int8)
        age = np.array([min(ages[d]["age"], 10) / 10.0 if d in ages else np.nan for d in dates])

        f_pead = np.zeros(n, dtype=bool)  # 60日窗内有预增预告+距60日高≤-20%+流通<50亿（公告严格早于信号日）
        ev = sorted(pead.get(code, []))
        if ev:
            for e in ev:
                lo = (pd.Timestamp(e) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                hi = (pd.Timestamp(e) + pd.Timedelta(days=60)).strftime("%Y-%m-%d")
                f_pead[np.searchsorted(dates, lo, "right"):np.searchsorted(dates, hi, "right")] = True
            f_pead &= (dhigh60 <= -0.20) & (caps < 50)
        f_rev = (day_pct <= -0.03) & (dhigh60 <= -0.20)          # bit2 反转族
        deep_stock = (day_pct <= -0.098) & (depth60 <= -0.35)    # bit0 深档个股件（簇门 eval 补）

        R = np.full((n, 3), np.nan, dtype=np.float32)
        trad = np.zeros(n, dtype=bool)
        for hi, hh in enumerate(HORIZONS):
            up_to = n - 2 - hh
            if up_to <= 65:
                continue
            idx = np.arange(66, up_to + 1)
            ent = o[idx + 1]
            ok = (ent > 0) & (ent < c[idx] * 1.095) & (ent > c[idx] * 0.905)  # 一字开剔
            with np.errstate(all="ignore"):
                R[idx[ok], hi] = c[idx[ok] + 1 + hh] / ent[ok] - 1 - FEE
            if hh == 1:
                trad[idx[ok]] = True

        valid = (np.isfinite(depth60) & np.isfinite(ret60) & np.isfinite(volr5)
                 & np.isfinite(log_cap) & np.isfinite(log_turn) & np.isfinite(age)
                 & (reg >= 0) & (didx >= 0) & trad)
        sel = np.where(valid)[0]
        if len(sel) == 0:
            continue
        F = np.empty((len(sel), NDIM), dtype=np.float32)
        for ci, arr in enumerate([depth60, dhigh60, ret60, ret20, ret5, day_pct,
                                  volr5, log_turn, log_cap, np.zeros(n), age]):
            F[:, ci] = arr[sel]
        for q in range(4):
            F[:, NCONT + q] = (reg[sel] == q).astype(np.float32)
        flags = (deep_stock[sel].astype(np.uint8) | (f_pead[sel].astype(np.uint8) << 1)
                 | (f_rev[sel].astype(np.uint8) << 2))
        ind = ind2i.get(info["industry"], -1) if info else -1
        F_l.append(F); R_l.append(R[sel])
        D_l.append(didx[sel])
        E_l.append(np.array([d2i.get(dates[min(i + 1, n - 1)], -1) for i in sel], dtype=np.int32))
        C_l.append(np.full(len(sel), int(code), dtype=np.int32))
        G_l.append(flags); I_l.append(np.full(len(sel), ind, dtype=np.int16))
        P_l.append(day_pct[sel].astype(np.float32))
        done.add(code)
        if len(done) % 400 == 0:
            _snapshot(F_l, R_l, D_l, E_l, C_l, G_l, I_l, P_l, done, calendar)
            print(f"[build] ckpt {len(done)}/{len(files)} stocks, {time.time()-t0:.0f}s", flush=True)

    _snapshot(F_l, R_l, D_l, E_l, C_l, G_l, I_l, P_l, done, calendar)
    print(f"[build] DONE {len(done)} stocks, elapsed={time.time()-t0:.0f}s")


def _snapshot(F_l, R_l, D_l, E_l, C_l, G_l, I_l, P_l, done, calendar):
    np.savez(FEAT_NPZ,
             F=np.concatenate(F_l), R=np.concatenate(R_l), didx=np.concatenate(D_l),
             eidx=np.concatenate(E_l), code=np.concatenate(C_l), flags=np.concatenate(G_l),
             ind=np.concatenate(I_l), day_pct=np.concatenate(P_l),
             done=np.array(sorted(done)), calendar=np.array(calendar),
             feature_names=np.array(FEATURE_NAMES), regimes=np.array(REGIMES))


# ---------------- 统计小件 ----------------

def _stats(rs):
    rs = rs[np.isfinite(rs)]
    if len(rs) < 30:
        return None
    return {"n": int(len(rs)), "win%": round(100 * float((rs > 0).mean()), 1),
            "mean%": round(100 * float(rs.mean()), 3), "med%": round(100 * float(np.median(rs)), 3)}


def _nw_t(x, lag):
    n = len(x)
    if n < lag + 30:
        return None
    m = x.mean()
    lrv = ((x - m) ** 2).mean()
    for k in range(1, lag + 1):
        lrv += 2 * (1 - k / (lag + 1)) * ((x[k:] - m) * (x[:-k] - m)).mean()
    return round(float(m / math.sqrt(lrv / n)), 2) if lrv > 0 else None


def _spearman(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    a, b = a[m], b[m]
    if len(a) < 100:
        return None
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    ra -= ra.mean(); rb -= rb.mean()
    den = math.sqrt(float((ra ** 2).sum() * (rb ** 2).sum()))
    return round(float((ra * rb).sum() / den), 4) if den > 0 else None


def _decile_table(pred, real, base_mean):
    m = np.isfinite(pred) & np.isfinite(real)
    pred, real = pred[m], real[m]
    edges = np.quantile(pred, np.linspace(0, 1, 11))
    rows = []
    for q in range(10):
        sel = (pred >= edges[q]) & (pred <= edges[q + 1]) if q == 9 else (pred >= edges[q]) & (pred < edges[q + 1])
        s = _stats(real[sel])
        if s:
            s["lift_pp"] = round(s["mean%"] - base_mean, 3)
            rows.append({"d": q + 1, **s})
    means = [r["mean%"] for r in rows]
    return {"rows": rows, "单调步数(9为全单调)": sum(1 for a, b in zip(means, means[1:]) if b >= a),
            "top-bottom_pp": round(means[-1] - means[0], 3) if len(means) == 10 else None}


# ---------------- GridCF 引擎 ----------------

def _grid_predict(F, R, li, ti, use_regime=True):
    """层级回退分桶精确匹配。返回 (len(ti),4)：pred1/5/20 + 所用层级。分箱边界全来自学习期。"""
    Fl, Ft = F[li], F[ti]
    e_d = np.nanquantile(Fl[:, 0], np.linspace(0.05, 0.95, 10))   # depth60
    e_r = np.nanquantile(Fl[:, 2], np.linspace(0.05, 0.95, 10))   # ret60
    e_v = np.nanquantile(Fl[:, 6], np.linspace(0.1, 0.9, 5))      # volr5
    e_c = np.nanquantile(Fl[:, 8], np.linspace(0.1, 0.9, 5))      # log_cap
    regl = np.argmax(Fl[:, NCONT:], 1).astype(np.int64)
    regt = np.argmax(Ft[:, NCONT:], 1).astype(np.int64)
    al = [regl] + [np.clip(np.searchsorted(e, Fl[:, c]), 0, len(e)).astype(np.int64)
                   for e, c in [(e_d, 0), (e_r, 2), (e_v, 6), (e_c, 8)]]
    at = [regt] + [np.clip(np.searchsorted(e, Ft[:, c]), 0, len(e)).astype(np.int64)
                   for e, c in [(e_d, 0), (e_r, 2), (e_v, 6), (e_c, 8)]]
    widths = [4, 10, 10, 5, 5]
    levels = [(0, 1, 2, 3, 4), (0, 1, 2, 4), (0, 1, 4), (0, 1), (0,)] if use_regime else \
             [(1, 2, 3, 4), (1, 2, 4), (1, 4), (1,)]
    Rl = R[li]
    pred = np.full((len(ti), 4), np.nan, dtype=np.float32)
    remaining = np.ones(len(ti), dtype=bool)
    for lv, use in enumerate(levels):
        kl = np.zeros(len(li), dtype=np.int64)
        kt = np.zeros(len(ti), dtype=np.int64)
        for a in use:
            kl = kl * widths[a] + al[a]
            kt = kt * widths[a] + at[a]
        nk = int(kl.max()) + 1
        cnt = np.bincount(kl, minlength=nk)
        take = remaining & (cnt[kt] >= GRID_MIN_N)
        if not take.any():
            continue
        for hi in range(3):
            finite = np.isfinite(Rl[:, hi])
            rr = np.where(finite, Rl[:, hi], 0.0)
            cn = np.bincount(kl, weights=finite.astype(float), minlength=nk)
            means = np.bincount(kl, weights=rr, minlength=nk) / np.maximum(cn, 1)
            good = take & (cn[kt] >= GRID_MIN_N)
            pred[good, hi] = means[kt[good]]
        pred[take, 3] = lv
        remaining &= ~take
    if remaining.any():  # 全局兜底
        for hi in range(3):
            pred[remaining, hi] = np.nanmean(Rl[:, hi])
        pred[remaining, 3] = len(levels)
    return pred


# ---------------- KNN 引擎（brute/tree/numba 三实现，同结果对拍 #279） ----------------

def _fill_from_neighbors(out, s, bd, bi, Rl):
    """三引擎共享的邻居加权后处理（口径唯一真源）：w=1/(1+d²/NDIM) 加权 T+1/5/20。
    bd=平方距离（float32，可含 argpartition 乱序），bi=学习集行号。"""
    w = 1.0 / (1.0 + np.maximum(bd, 0) / NDIM)
    for hi in range(3):
        rn = Rl[bi, hi]
        mm = np.isfinite(rn)
        ws = (w * mm).sum(1)
        out[s:s + len(bd), hi] = np.where(ws > 1e-6, (w * np.where(mm, rn, 0)).sum(1) / np.maximum(ws, 1e-12), np.nan)
    out[s:s + len(bd), 3] = np.sqrt(np.maximum(bd, 0)).mean(1) / NDIM


def _knn_predict_pruned(Xl, Rl, Xt, return_nb=False):
    """精确 top-K + 阈值剪枝：首块建立每行第 K 小距离门槛，后续块只合并越过门槛的少数候选。"""
    K = min(KNN_K, len(Xl))
    nl2 = (Xl ** 2).sum(1)
    out = np.full((len(Xt), 4), np.nan, dtype=np.float32)
    NB = (np.full((len(Xt), K), np.inf, dtype=np.float32),
          np.zeros((len(Xt), K), dtype=np.int32)) if return_nb else None
    B, LB = 512, 65536
    t0 = time.time()
    for s in range(0, len(Xt), B):
        blk = Xt[s:s + B]
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
        _fill_from_neighbors(out, s, bd, bi, Rl)
        if return_nb:
            NB[0][s:s + B], NB[1][s:s + B] = bd, bi
        if (s // B) % 50 == 0:
            print(f"    knn {s}/{len(Xt)} {time.time()-t0:.0f}s", flush=True)
    return (out, NB) if return_nb else out


# --- numba 版：距离块仍走 numpy BLAS（数值与暴力版逐位同源），只把阈值合并 python 循环 njit 化 ---
try:
    from numba import njit, prange
    _HAS_NUMBA = True
except ImportError:
    _HAS_NUMBA = False

if _HAS_NUMBA:
    @njit(parallel=True, cache=True)
    def _merge_topk_njit(bd, bi, d, offset):
        """逐块合并：收集本块 < 当前第 K 门槛的候选，与现有 top-K 拼接后 argsort 取前 K。
        与暴力版逐块 argpartition 合并同为精确 top-K（结果集一致，并列距离才可能有界差）。
        首版「每次插入重算 max」是 O(cnt×K)，实测比暴力还慢（1119s vs 952s），已改。
        行内临时数组（prange 每行一份，~1.3MB/行），避免大块常驻缓冲。"""
        n, K = bd.shape
        LB = d.shape[1]
        for r in prange(n):
            thr = bd[r, 0]
            for k in range(1, K):
                if bd[r, k] > thr:
                    thr = bd[r, k]
            cnt = 0
            tmp_d = np.empty(LB, dtype=np.float32)
            tmp_i = np.empty(LB, dtype=np.int32)
            for j in range(LB):
                dj = d[r, j]
                if dj < thr:
                    tmp_d[cnt] = dj
                    tmp_i[cnt] = j + offset
                    cnt += 1
            if cnt == 0:
                continue
            cat_d = np.empty(K + cnt, dtype=np.float32)
            cat_i = np.empty(K + cnt, dtype=np.int32)
            for k in range(K):
                cat_d[k] = bd[r, k]
                cat_i[k] = bi[r, k]
            for k in range(cnt):
                cat_d[K + k] = tmp_d[k]
                cat_i[K + k] = tmp_i[k]
            order = np.argsort(cat_d)
            for k in range(K):
                bd[r, k] = cat_d[order[k]]
                bi[r, k] = cat_i[order[k]]


def _knn_predict_numba(Xl, Rl, Xt, return_nb=False):
    """numba 引擎：首块 argpartition 建门槛（同暴力版），后续块 _merge_topk_njit 合并。"""
    if not _HAS_NUMBA:
        raise RuntimeError("numba 未安装")
    K = min(KNN_K, len(Xl))
    nl2 = (Xl ** 2).sum(1)
    out = np.full((len(Xt), 4), np.nan, dtype=np.float32)
    NB = (np.full((len(Xt), K), np.inf, dtype=np.float32),
          np.zeros((len(Xt), K), dtype=np.int32)) if return_nb else None
    B, LB = 512, 65536
    t0 = time.time()
    for s in range(0, len(Xt), B):
        blk = Xt[s:s + B]
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
            _merge_topk_njit(bd, bi, d, t)
        _fill_from_neighbors(out, s, bd, bi, Rl)
        if return_nb:
            NB[0][s:s + B], NB[1][s:s + B] = bd, bi
        if (s // B) % 50 == 0:
            print(f"    knn-numba {s}/{len(Xt)} {time.time()-t0:.0f}s", flush=True)
    return (out, NB) if return_nb else out


def _knn_predict_tree(Xl, Rl, Xt, algorithm="auto", return_nb=False):
    """树版引擎：sklearn NearestNeighbors（KD/Ball 由 algorithm 控制），精确欧氏 top-K。
    返回的欧氏距离平方后与暴力版 d² 同口径进 _fill_from_neighbors。"""
    from sklearn.neighbors import NearestNeighbors
    K = min(KNN_K, len(Xl))
    nn = NearestNeighbors(n_neighbors=K, algorithm=algorithm, n_jobs=-1)
    nn.fit(Xl)
    out = np.full((len(Xt), 4), np.nan, dtype=np.float32)
    NB = (np.full((len(Xt), K), np.inf, dtype=np.float32),
          np.zeros((len(Xt), K), dtype=np.int32)) if return_nb else None
    B = 4096
    t0 = time.time()
    for s in range(0, len(Xt), B):
        dist, idx = nn.kneighbors(Xt[s:s + B])
        bd = (dist ** 2).astype(np.float32)
        bi = idx.astype(np.int32)
        _fill_from_neighbors(out, s, bd, bi, Rl)
        if return_nb:
            NB[0][s:s + len(bd)], NB[1][s:s + len(bd)] = bd, bi
        if (s // B) % 10 == 0:
            print(f"    knn-tree[{algorithm}] {s}/{len(Xt)} {time.time()-t0:.0f}s", flush=True)
    return (out, NB) if return_nb else out


KNN_ENGINES = {"brute": _knn_predict_pruned, "numba": _knn_predict_numba, "tree": _knn_predict_tree}

def _standardize(Xl, Xt):
    ql = np.nanpercentile(Xl, 1, axis=0)
    qh = np.nanpercentile(Xl, 99, axis=0)
    mu = np.nanmean(Xl, axis=0)
    sd = np.nanstd(Xl, axis=0)
    sd[sd == 0] = 1
    lo, hi = (ql - mu) / sd, (qh - mu) / sd
    return np.clip((Xl - mu) / sd, lo, hi), np.clip((Xt - mu) / sd, lo, hi)


# ---------------- 评估公共段 ----------------

def _report_block(res, pred, Rt, eidx_t, depth_t, uni5):
    """lift 表 + 洗牌对照 + 日历时间 + depth 分层。返回 (res, p5m, r5m, thr, m)。"""
    for hi, hh in enumerate(HORIZONS):
        base = _stats(Rt[:, hi])
        res[f"T+{hh}"] = {"base": base, "deciles": _decile_table(pred[:, hi], Rt[:, hi], base["mean%"])}
    rng = np.random.default_rng(7)
    pf = pred[:, 1].copy()
    rng.shuffle(pf)
    res["随机洗牌对照_T5_top-bottom_pp"] = _decile_table(pf, Rt[:, 1], _stats(Rt[:, 1])["mean%"])["top-bottom_pp"]

    p5, r5 = pred[:, 1], Rt[:, 1]
    m = np.isfinite(p5) & np.isfinite(r5)
    e5, p5m, r5m = eidx_t[m], p5[m], r5[m]
    thr = np.nanquantile(p5m, 0.9)
    by = defaultdict(list)
    for e, rr, p in zip(e5, r5m, p5m):
        if p >= thr:
            by[int(e)].append(float(rr))
    series = np.array([np.mean(by[d]) - uni5[d] for d in sorted(by) if d in uni5])
    res["日历时间_T5_top10%"] = {"天数": int(len(series)),
                                 "日均超额pp": round(100 * float(series.mean()), 3),
                                 "年化Sharpe": round(float(series.mean() / series.std() * math.sqrt(244)), 2) if series.std() > 0 else None,
                                 "t_NW": _nw_t(series, 5)}
    edges = np.nanquantile(depth_t, np.linspace(0, 1, 6))
    strata = []
    for q in range(5):
        s = (depth_t >= edges[q]) & (depth_t <= edges[q + 1]) if q == 4 else (depth_t >= edges[q]) & (depth_t < edges[q + 1])
        pm, rm = p5[s], r5[s]
        mm = np.isfinite(pm) & np.isfinite(rm)
        pm, rm = pm[mm], rm[mm]
        if len(pm) < 500:
            continue
        med = np.median(pm)
        strata.append({"depth档": q + 1, "n": int(len(pm)), "spearman": _spearman(pm, rm),
                       "预测上半实测%": round(100 * float(rm[pm >= med].mean()), 3),
                       "预测下半实测%": round(100 * float(rm[pm < med].mean()), 3)})
    res["depth分层内判别_T5"] = strata
    return res, p5m, r5m, thr, m


def _overlap_block(p5m, r5m, thr, fl_t):
    sel = p5m >= thr
    top_fl, top_r5 = fl_t[sel], r5m[sel]
    return {"n": int(len(top_fl)),
            "深档v2(簇门后)%": round(100 * float(((top_fl & 1) != 0).mean()), 1),
            "预增低位池%": round(100 * float(((top_fl & 2) != 0).mean()), 1),
            "反转族%": round(100 * float(((top_fl & 4) != 0).mean()), 1),
            "任一注册线%": round(100 * float((top_fl != 0).mean()), 1),
            "未被任何线覆盖者_T5": _stats(top_r5[top_fl == 0]),
            "被覆盖者_T5": _stats(top_r5[top_fl != 0])}


def _load_all():
    z = np.load(FEAT_NPZ)
    return z["F"], z["R"], z["didx"], z["eidx"], z["flags"], z["ind"], z["day_pct"], z["calendar"].tolist()


def _prep(F, didx, ind, day_pct, eidx, R):
    key = didx.astype(np.int64) * 100000 + ind.astype(np.int64)   # 板块温度二次过
    okp = np.isfinite(day_pct)
    uk, inv = np.unique(key[okp], return_inverse=True)
    means = np.bincount(inv, weights=day_pct[okp]) / np.maximum(np.bincount(inv), 1)
    lut = dict(zip(uk.tolist(), means.tolist()))
    F[:, 9] = np.array([lut.get(k, np.nan) for k in key], dtype=np.float32)
    r5 = R[:, 1]
    ok5 = np.isfinite(r5)
    ue, uinv = np.unique(eidx[ok5], return_inverse=True)
    umean = np.bincount(uinv, weights=r5[ok5]) / np.maximum(np.bincount(uinv), 1)
    return dict(zip(ue.tolist(), umean.tolist()))


def _flags_gated(flags, didx):
    deep_mask = (flags & 1) != 0
    cnt = np.bincount(didx[deep_mask].astype(np.int64), minlength=int(didx.max()) + 1)
    return (flags & 0b110) | (deep_mask & (cnt[didx] >= 5)).astype(np.uint8)  # bit0 换簇门后口径


def _save(out):
    out["_meta"] = {"built": time.strftime("%Y-%m-%d %H:%M"), "engine": "GridCF+KNN抽样",
                    "min_cell_n": GRID_MIN_N, "K": KNN_K, "fee": FEE, "features": FEATURE_NAMES,
                    "口径": "次日开盘入,一字开剔,净0.15%,分箱边界=学习期分位数"}
    with open(OUT_JSON, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


def evaluate_grid():
    t0 = time.time()
    F, R, didx, eidx, flags, ind, day_pct, calendar = _load_all()
    uni5 = _prep(F, didx, ind, day_pct, eidx, R)
    fg = _flags_gated(flags, didx)
    print(f"[grid] rows={len(F)}", flush=True)
    sp = bisect.bisect_left(calendar, "2023-01-01")
    T = len(calendar)
    dirs = [("A_学19-22测23-26", didx < sp, didx >= sp, True),
            ("B_学23-26测19-22", didx >= sp, didx < sp, True),
            ("C_最近250日存活", didx < T - 250, didx >= T - 250, True),
            ("D_无regime轴敏感", didx < sp, didx >= sp, False)]
    out = json.loads(open(OUT_JSON).read()) if OUT_JSON.exists() else {"directions": {}}
    for name, lm, tm, use_reg in dirs:
        if f"grid_{name}" in out["directions"]:
            continue
        li, ti = np.where(lm)[0], np.where(tm)[0]
        ta = time.time()
        pred = _grid_predict(F, R, li, ti, use_regime=use_reg)
        res = {"learn_n": int(len(li)), "test_n": int(len(ti)), "耗时s": int(time.time() - ta),
               "层级分布": {str(int(k)): int(v) for k, v in zip(*np.unique(pred[:, 3], return_counts=True))}}
        res, p5m, r5m, thr, m = _report_block(res, pred, R[ti], eidx[ti], F[ti, 0], uni5)
        res["重叠审计_top10%"] = _overlap_block(p5m, r5m, thr, fg[ti][m])
        out["directions"][f"grid_{name}"] = res
        _save(out)
        print(f"[grid] {name} done ({time.time()-t0:.0f}s)", flush=True)
    print(f"[grid] ALL DONE elapsed={time.time()-t0:.0f}s")


def evaluate_knn_sample(engine=None):
    """KNN 欧氏引擎抽样验证：方向 A 抽 20 万测试行，学习集 1/4 等距抽样（61 万点密度足够）。
    engine: brute|tree|numba，默认读 KNN_ENGINE 开关。"""
    engine = engine or KNN_ENGINE
    t0 = time.time()
    F, R, didx, eidx, flags, ind, day_pct, calendar = _load_all()
    uni5 = _prep(F, didx, ind, day_pct, eidx, R)
    fg = _flags_gated(flags, didx)
    sp = bisect.bisect_left(calendar, "2023-01-01")
    li = np.where(didx < sp)[0][::4]
    ti_all = np.where(didx >= sp)[0]
    rng = np.random.default_rng(11)
    ti = np.sort(ti_all[rng.choice(len(ti_all), min(200000, len(ti_all)), replace=False)])
    print(f"[knn:{engine}] learn={len(li)} test={len(ti)}", flush=True)
    Xl, Xt = _standardize(F[li, :NCONT], F[ti, :NCONT])
    Xl = np.concatenate([Xl, F[li, NCONT:]], 1)
    Xt = np.concatenate([Xt, F[ti, NCONT:]], 1)
    pred = KNN_ENGINES[engine](Xl, R[li], Xt)
    res = {"learn_n": int(len(li)), "test_n": int(len(ti)), "耗时s": int(time.time() - t0),
           "engine": engine}
    res, p5m, r5m, thr, m = _report_block(res, pred, R[ti], eidx[ti], F[ti, 0], uni5)
    res["重叠审计_top10%"] = _overlap_block(p5m, r5m, thr, fg[ti][m])
    out = json.loads(open(OUT_JSON).read()) if OUT_JSON.exists() else {"directions": {}}
    out["directions"][f"knn_A抽样20万_{engine}"] = res
    _save(out)
    print(f"[knn:{engine}] DONE elapsed={time.time()-t0:.0f}s")


def _knn_sample_mats(n_test, seed=11):
    """方向 A 同口径取学习/测试矩阵（对拍与基准共用，保证同一批查询点）。"""
    F, R, didx, eidx, flags, ind, day_pct, calendar = _load_all()
    sp = bisect.bisect_left(calendar, "2023-01-01")
    li = np.where(didx < sp)[0][::4]
    ti_all = np.where(didx >= sp)[0]
    rng = np.random.default_rng(seed)
    ti = np.sort(ti_all[rng.choice(len(ti_all), min(n_test, len(ti_all)), replace=False)])
    Xl, Xt = _standardize(F[li, :NCONT], F[ti, :NCONT])
    Xl = np.concatenate([Xl, F[li, NCONT:]], 1)
    Xt = np.concatenate([Xt, F[ti, NCONT:]], 1)
    return Xl, R[li], Xt


def knn_check(n_test=20000):
    """三引擎同参数对拍（#279 验收）：同一批查询点，top-K 重合度 + 预测值最大差 + 各自耗时。
    内存纪律：每引擎的 (out,bd,bi) 算完即落盘 scratch npz 并释放，不同时驻留多引擎结果
    （15GB 机器多卡并发实证 OOM 过一回）。"""
    import gc
    scratch = Path("/opt/data/cache/scratch")
    t0 = time.time()
    Xl, Rl, Xt = _knn_sample_mats(n_test)
    print(f"[check] learn={len(Xl)} test={len(Xt)} load={time.time()-t0:.0f}s", flush=True)
    ela = {}
    prev = json.loads(open(OUT_JSON).read()).get("directions", {}).get("knn_三引擎对拍", {}) if OUT_JSON.exists() else {}
    for eng in ("brute", "numba", "tree"):
        fp = scratch / f"knn_check_{eng}.npz"
        if fp.exists() and np.load(fp)["bi"].shape[0] == n_test:   # 断点续跑：同规模旧结果直接复用
            ela[eng] = prev.get("耗时s", {}).get(eng)
            print(f"[check] {eng} reuse {fp.name} ({ela[eng]}s)", flush=True)
            continue
        ta = time.time()
        out_e, nb = KNN_ENGINES[eng](Xl, Rl, Xt, return_nb=True)
        np.savez(fp, out=out_e, bd=nb[0], bi=nb[1])
        del out_e, nb
        gc.collect()
        ela[eng] = round(time.time() - ta, 1)
        print(f"[check] {eng} done {ela[eng]}s", flush=True)
    zb = np.load(scratch / "knn_check_brute.npz")
    ob, bib = zb["out"], zb["bi"]
    K = min(KNN_K, len(Xl))
    rep = {"learn_n": int(len(Xl)), "test_n": int(len(Xt)), "K": K, "耗时s": ela}
    for name in ("numba", "tree"):
        z2 = np.load(scratch / f"knn_check_{name}.npz")
        ov = np.array([len(set(a.tolist()) & set(b.tolist())) for a, b in zip(bib, z2["bi"])])
        rep[f"topK重合_{name}"] = {"mean%": round(100 * float(ov.mean()) / K, 4),
                                   "min%": round(100 * float(ov.min()) / K, 4)}
        d = np.abs(ob[:, :3].astype(float) - z2["out"][:, :3].astype(float))
        rep[f"预测最大差_{name}"] = float(np.nanmax(d))
        rep[f"预测均方根差_{name}"] = float(np.sqrt(np.nanmean(d ** 2)))
        del z2
        gc.collect()
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    out = json.loads(open(OUT_JSON).read()) if OUT_JSON.exists() else {"directions": {}}
    out["directions"]["knn_三引擎对拍"] = rep
    _save(out)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "build":
        build()
    elif cmd == "grid":
        evaluate_grid()
    elif cmd == "knn":
        evaluate_knn_sample(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "knn_check":
        knn_check(int(sys.argv[2]) if len(sys.argv) > 2 else 20000)
