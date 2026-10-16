#!/usr/bin/env python3
"""engine/walkforward.py — 滚动前推（walk-forward）验证框架（#263-B② / #265⑥ 落地）

动机：静态双段（2019-22 / 2023-26）被反复复用调参，不等于样本外。
本框架对同一条线分别跑「静态双段」与「滚动前推」，报两者判决差异。

窗口：
  rolling  —— 学 3 年 / 测 6 个月 / 步进 6 个月（knn 类线数据只有 2023+，学 2 年）
  anchored —— 锚定起点，学习窗逐段扩张，测试窗与 rolling 相同
每段输出：n / 胜率 / 均值 / 中位 / 朴素 t / t_NW(HAC, lag=h) / 日历时间日度超额 + t_NW
  + block bootstrap 95% CI（block=20 交易日聚类，B=2000）
参数稳定性：每段学习窗内重选参数（网格见各线），报告选中参数与其 OOS 表现
  （生产参数另列一行对照）——选中参数漂移=过拟合信号。
edge 衰减曲线：各测试段 T+5 事件均值 + 日历日度超额序列，落 JSON。
trials 纪律：前推测试段数计入 DSR trials 分母，如实报（base=7491 见 law_pipeline）。

首测线：
  deep_low_v2   混档低位v2（生产原口径重建：簇门=深档件[≤-9.5%且收<MA60且收≤MA60×0.75]≥5，
                出手票=其中 depth≤-35% 按深度最深 top5；全命运结算：越界按最后收盘，
                对齐 #280 P2 口径）——kcache 精益逐票扫描（用完即弃，峰值远低于 0.9GB）
  pead_low_pool 预增低位池（npz bit1，生产口径复刻件）
  rev_knn_excl  knn_vote 排除层×反转族（npz bit2 × dec_knn_vote，剔 dec≤1=「别碰」层）
  pead_knn_excl knn_vote 排除层×预增池
  （择时线按父卡 t_316237a5 结论无存活变体，不进前推队列。）

用法：
  .venv/bin/python engine/walkforward.py                 # 全四线
  .venv/bin/python engine/walkforward.py --only deep_low_v2 rev_knn_excl
产出：data/walkforward_20261016.json
"""
import json, math, bisect, sys, time, argparse
from pathlib import Path
from collections import defaultdict

import numpy as np

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data/big_kcache"
FEAT_NPZ = ROOT / "data/similarity_features.npz"
BASE_NPZ = ROOT / "data/factor_census_base.npz"
OUT = ROOT / "data/walkforward_20261016.json"
FEE = 0.0015
H_LIST = (1, 5, 10, 20)          # deep 线全 horizon；npz 线只有 (1,5,20)
NPZ_H = (1, 5, 20)
BOOT_B = 2000
BOOT_BLOCK = 20                  # 交易日
MIN_N = 30
sys.path.insert(0, str(ROOT / "engine"))
from law_pipeline import nw_t, deflated_sharpe  # 共享 helper，不抄实现（#262-C 纪律）

TRIALS_BASE = 7491               # law_pipeline.deflated_sharpe 默认口径


# ---------------- 窗口机 ----------------
def _add_month(y, m, k):
    m2 = m - 1 + k
    return y + m2 // 12, m2 % 12 + 1


def make_segments(cal, start, end, train_months, test_months=6, step_months=6):
    """返回 [{'train':(a,b),'test':(a,b)}]，日期为字符串，test 右端闭区间截到 end。"""
    y0, m0 = int(start[:4]), int(start[5:7])
    ty, tm = _add_month(y0, m0, train_months)
    segs = []
    while True:
        t0 = f"{ty:04d}-{tm:02d}-01"
        if t0 > end:
            break
        ey, em = _add_month(ty, tm, test_months)
        t1 = min(f"{ey:04d}-{em:02d}-01", end)
        # train 起点（rolling 在调用处再截）
        ay, am = _add_month(ty, tm, -train_months)
        segs.append({"train_full": (f"{ay:04d}-{am:02d}-01", t0), "test": (t0, t1)})
        ty, tm = _add_month(ty, tm, step_months)
    return segs


def _d2i(cal):
    return {d: i for i, d in enumerate(cal)}


def _mask_range(didx, cal, a, b):
    """didx（信号日索引）落在 [a,b] 日期窗的布尔掩码"""
    ia = bisect.bisect_left(cal, a)
    ib = bisect.bisect_right(cal, b)
    return (didx >= ia) & (didx < ib)


# ---------------- 统计件 ----------------
def _basic(rs, lag):
    rs = rs[np.isfinite(rs)]
    n = len(rs)
    if n < 5:
        return {"n": int(n)}
    m = float(rs.mean())
    sd = float(rs.std(ddof=1)) if n > 1 else 0.0
    out = {"n": int(n), "win%": round(100 * float((rs > 0).mean()), 1),
           "mean%": round(100 * m, 3), "med%": round(100 * float(np.median(rs)), 3),
           "t": round(m / (sd / math.sqrt(n)), 2) if sd > 0 else None}
    if n >= lag + 30:
        out["t_NW"] = nw_t(rs.tolist(), lag)
    return out


def _cal_series(rets, eidx, uni_mean):
    """日度等权组合 - 当日宇宙均值 → 日度超额序列"""
    by = defaultdict(list)
    for e, r in zip(eidx, rets):
        if np.isfinite(r):
            by[int(e)].append(float(r))
    ser = [float(np.mean(by[d])) - uni_mean[d] for d in sorted(by) if d in uni_mean]
    return ser


def _cal_stats(series, lag):
    if len(series) < 30:
        return {"天数": len(series)}
    x = np.asarray(series)
    m, sd = float(x.mean()), float(x.std(ddof=1))
    sr_d = m / sd if sd > 0 else 0.0
    skew = float(((x - m) ** 3).mean() / sd ** 3) if sd > 0 else 0.0
    kurt = float(((x - m) ** 4).mean() / sd ** 4) if sd > 0 else 3.0
    return {"天数": len(series), "日均超额pp": round(100 * m, 3),
            "t_NW": nw_t(series, lag), "sr_daily": round(sr_d, 4),
            "年化Sharpe": round(sr_d * math.sqrt(244), 2),
            "skew": round(skew, 2), "kurt": round(kurt, 2)}


def _boot_ci(rets, eidx, B=BOOT_B):
    """block bootstrap：block=eidx//20 交易日聚类，重抽样 block 得均值 95% CI"""
    ok = np.isfinite(rets)
    r, e = rets[ok], eidx[ok]
    if len(r) < 30:
        return None
    blk = e // BOOT_BLOCK
    ub, inv = np.unique(blk, return_inverse=True)
    sums = np.bincount(inv, weights=r)
    cnts = np.bincount(inv).astype(float)
    nb = len(ub)
    rng = np.random.default_rng(7)
    idx = rng.integers(0, nb, size=(B, nb))
    est = sums[idx].sum(1) / np.maximum(cnts[idx].sum(1), 1)
    lo, hi = np.percentile(est, [2.5, 97.5])
    return {"block": BOOT_BLOCK, "B": B, "mean%": round(100 * float(r.mean()), 3),
            "ci95%": [round(100 * float(lo), 3), round(100 * float(hi), 3)]}


def _seg_metrics(sel, R, hcols, eidx, uni):
    """sel=事件布尔掩码；返回 {horizon: {...}}"""
    out = {}
    for h, col in hcols.items():
        r = R[sel, col]
        e = eidx[sel]
        st = _basic(r, h)
        ser = _cal_series(r, e, uni[h])
        st["日历"] = _cal_stats(ser, h)
        st["boot"] = _boot_ci(r, e)
        out[f"T+{h}"] = st
    return out


# ---------------- 数据装载：npz 线 ----------------
def load_npz():
    z = np.load(FEAT_NPZ, mmap_mode="r")
    didx = np.asarray(z["didx"]); eidx = np.asarray(z["eidx"])
    code = np.asarray(z["code"]); flags = np.asarray(z["flags"])
    R = np.asarray(z["R"])  # (N,3) float32, horizons=(1,5,20)
    cal = z["calendar"].tolist()
    # 宇宙日均（可成交行口径，对齐 similarity_combo_test）
    uni = {}
    for hi, hh in enumerate(NPZ_H):
        r = R[:, hi]
        ok = np.isfinite(r)
        ue, uinv = np.unique(eidx[ok], return_inverse=True)
        um = np.bincount(uinv, weights=r[ok]) / np.maximum(np.bincount(uinv), 1)
        uni[hh] = dict(zip(ue.tolist(), um.tolist()))
    return cal, didx, eidx, code, flags, R, uni


def load_knn_dec(cal, code):
    zb = np.load(BASE_NPZ, mmap_mode="r")
    assert zb["calendar"].tolist() == cal
    c2j = {int(c): j for j, c in enumerate(zb["codes"].tolist())}
    js = np.array([c2j.get(int(c), -1) for c in code])
    M = np.asarray(zb["dec_knn_vote"])  # (days, codes) uint8, 255=NaN, 仅 2023+ 有效（OOS）
    return M, js


# ---------------- 深档低位v2：kcache 精益重建（生产原口径） ----------------
def deep_events():
    """逐票扫描，返回 dict:
       events: (didx, eidx, code, depth, rets[4])  —— deep35 出手候选
       cnt25:  np.array(1886) 每日 deep25 件数（簇门计数口径）
       uni:    {h: {eidx: 当日宇宙均}}（全主板可成交口径）
       cal:    交易日历
    """
    t0 = time.time()
    cal = [k["date"] for k in json.loads((KC / "600000.json").read_text())]
    d2i = _d2i(cal)
    nd = len(cal)
    cnt25 = np.zeros(nd, dtype=np.int32)
    ev = []  # (didx, code, depth, eidx, r1, r5, r10, r20)
    usum = {h: np.zeros(nd) for h in H_LIST}
    ucnt = {h: np.zeros(nd, dtype=np.int32) for h in H_LIST}
    import glob as _g
    files = sorted(_g.glob(str(KC / "*.json")))
    nsc = 0
    for fp in files:
        code = Path(fp).stem
        ks = json.loads(open(fp).read())
        n = len(ks)
        if n < 300:
            continue
        nsc += 1
        c = np.array([k["close"] for k in ks])
        o = np.array([k["open"] for k in ks])
        dates = [k["date"] for k in ks]
        di = np.array([d2i.get(d, -1) for d in dates], dtype=np.int32)
        # ma60 逐字复刻 law_pipeline.load_universe（前 60 根 None，ma60[i]=mean(c[i-60..i-1])）——
        # 65 批台账/#280 基线同源口径；注意比 dashboard_build 的含当日口径滞后一根，勿混用。
        cs = np.concatenate([[0.0], np.cumsum(c)])
        ma60 = np.full(n, np.nan)
        _idx = np.arange(60, n)
        ma60[_idx] = (cs[_idx] - cs[_idx - 60]) / 60
        with np.errstate(all="ignore"):
            pct = c / np.concatenate([[np.nan], c[:-1]]) - 1
            depth = c / ma60 - 1
        # ---- 宇宙基线（可成交口径：一字开剔，与 npz 一致）----
        for h in H_LIST:
            up = n - 2 - h
            if up <= 65:
                continue
            idx = np.arange(66, up + 1)
            ent = o[idx + 1]
            okm = (ent > 0) & (ent < c[idx] * 1.095) & (ent > c[idx] * 0.905)
            ii = idx[okm]
            rr = c[ii + 1 + h] / ent[okm] - 1 - FEE
            de = di[ii + 1]
            okd = de >= 0
            np.add.at(usum[h], de[okd], rr[okd])
            np.add.at(ucnt[h], de[okd], 1)
        # ---- 深档事件 ----
        for i in range(65, n - 1):   # law_pipeline START=65 / delist_bias range(65, n-1) 同口径
            if di[i] < 0 or not np.isfinite(ma60[i]) or not np.isfinite(pct[i]):
                continue
            if pct[i] <= -0.095 and c[i] < ma60[i] and c[i] <= ma60[i] * 0.75:
                cnt25[di[i]] += 1
                if depth[i] <= -0.35:
                    ent = o[i + 1]
                    buyable = bool(ent > 0 and ent > c[i] * 0.905)  # 次日一字跌停开=买不到
                    if ent <= 0:
                        continue
                    rets = []
                    for h in H_LIST:
                        xi = i + 1 + h
                        xc = c[xi] if xi < n else c[-1]   # 全命运结算（#280 P2）
                        rets.append(xc / ent - 1 - FEE)
                    ev.append((di[i], di[min(i + 1, n - 1)], code, float(depth[i]), *rets, buyable))
        if nsc % 800 == 0:
            print(f"[deep] {nsc} stocks {time.time()-t0:.0f}s", flush=True)
    uni = {h: {i: usum[h][i] / ucnt[h][i] for i in range(nd) if ucnt[h][i] > 0} for h in H_LIST}
    print(f"[deep] scanned={nsc} deep35_events={len(ev)} elapsed={time.time()-t0:.0f}s", flush=True)
    return {"cal": cal, "cnt25": cnt25, "events": ev, "uni": uni}


def deep_select(dep, cluster_gate, depth_gate, topn=5, require_buyable=False):
    """按台账口径选出手票：簇日（cnt25>=gate）上 depth<=depth_gate 的按深度最深取 top5。
    require_buyable=False=65批台账口径（一字跌停开也计，r 按开盘价）；True=可成交口径（#280/#282）。
    返回 (sel布尔(np over events), batch_map{didx: [event_idx...]})"""
    evs = dep["events"]
    cnt25 = dep["cnt25"]
    by_day = defaultdict(list)
    for k, e in enumerate(evs):
        if require_buyable and not e[8]:
            continue
        if cnt25[e[0]] >= cluster_gate and e[3] <= depth_gate:
            by_day[e[0]].append(k)
    sel = np.zeros(len(evs), dtype=bool)
    batches = {}
    for d, ks in by_day.items():
        ks.sort(key=lambda k: evs[k][3])  # depth 最深优先
        picks = ks[:topn]
        for k in picks:
            sel[k] = True
        batches[d] = picks
    return sel, batches


# ---------------- 线定义 ----------------
def line_deep(dep, cal):
    evs = dep["events"]
    didx = np.array([e[0] for e in evs], dtype=np.int32)
    eidx = np.array([e[1] for e in evs], dtype=np.int32)
    R = np.array([[e[4], e[5], e[6], e[7]] for e in evs], dtype=np.float64)
    hcols = {h: j for j, h in enumerate(H_LIST)}

    def sel_fn(cluster_gate=5, depth_gate=-0.35):
        sel, _ = deep_select(dep, cluster_gate, depth_gate)
        return sel

    def param_grid():
        return [(cg, dg) for cg in (3, 5, 8) for dg in (-0.30, -0.35, -0.40)]

    def param_metric(sel, train_mask, hcol):
        r = R[sel & train_mask, hcol]
        r = r[np.isfinite(r)]
        if len(r) < 10:   # 深档事件稀疏，10 件即可参与学习窗比选（如实报 n）
            return None
        return float(r.mean())

    return {"didx": didx, "eidx": eidx, "R": R, "hcols": hcols,
            "sel_fn": sel_fn, "param_grid": param_grid(), "param_metric": param_metric,
            "prod_params": (5, -0.35), "param_fmt": lambda p: f"簇门≥{p[0]}×depth≤{p[1]:.2f}",
            "uni": dep["uni"], "min_n": 5}


def line_npz(name, npz, flagbit, knn=None, excl_dec=None):
    cal, didx, eidx, code, flags, R64, uni = npz
    R = R64.astype(np.float64)
    hcols = {h: j for j, h in enumerate(NPZ_H)}
    base = (flags & flagbit) != 0
    if knn is not None:
        M, js = knn
        ok = js >= 0
        dec = np.full(len(didx), 255, dtype=np.uint8)
        dec[ok] = M[didx[ok], js[ok]]
        base = base & (dec < 255)  # knn OOS 段外天然排除
        # 生产（提案）口径：剔 dec≤1
        cur = np.asarray(dec)
        def sel_fn(th=1):
            return base & (cur > th)
        def param_grid():
            return [0, 1, 2]
        full_R = R
        def param_metric(th, train_mask, hcol):
            kept = base & (cur > th) & train_mask
            allm = base & train_mask
            rk = full_R[kept, hcol]; ra = full_R[allm, hcol]
            rk = rk[np.isfinite(rk)]; ra = ra[np.isfinite(ra)]
            if len(rk) < 100 or len(ra) < 100:
                return None
            return float(rk.mean() - ra.mean())  # 排除层增量
        return {"didx": didx, "eidx": eidx, "R": R, "hcols": hcols,
                "sel_fn": sel_fn, "param_grid": param_grid(), "param_metric": param_metric,
                "prod_params": 1, "param_fmt": lambda p: f"剔dec≤{p}",
                "uni": uni, "_base_mask": base}
    return {"didx": didx, "eidx": eidx, "R": R, "hcols": hcols,
            "sel_fn": lambda: base, "param_grid": [], "param_metric": None,
            "prod_params": None, "param_fmt": str, "uni": uni}


# ---------------- 主流程 ----------------
def run_line(name, L, cal, start, end, train_months):
    didx, eidx, R, hcols, uni = L["didx"], L["eidx"], L["R"], L["hcols"], L["uni"]
    segs = make_segments(cal, start, end, train_months)
    prod_sel = L["sel_fn"](*L["prod_params"]) if isinstance(L["prod_params"], tuple) else \
        L["sel_fn"](L["prod_params"]) if L["prod_params"] is not None else L["sel_fn"]()
    res = {"events_total": int(prod_sel.sum()), "segments": [], "anchored": []}

    # --- 静态双段（同一批事件、生产/提案口径）---
    # 数据起点晚于 2023 的线（knn OOS 类）：第一段必空，改按事件可用窗中点切两半，如实标注。
    ev_dates = cal[int(didx[prod_sel].min())] if prod_sel.any() else start
    if ev_dates > "2022-12-31":
        mid = f"{(int(ev_dates[:4]) + int(end[:4])) // 2}-07-01"
        seg_masks = {f"{ev_dates}~{mid}": _mask_range(didx, cal, ev_dates, mid),
                     f"{mid}~{end}": _mask_range(didx, cal, mid, end)}
        res["static_note"] = f"数据自 {ev_dates} 起（knn OOS），静态双段按可用窗中点切半"
    else:
        seg_masks = {"2019-2022": _mask_range(didx, cal, start, "2022-12-31"),
                     "2023-2026": _mask_range(didx, cal, "2023-01-01", end)}
    res["static_two_segment"] = {k: _seg_metrics(prod_sel & m, R, hcols, eidx, uni)
                                 for k, m in seg_masks.items()}

    # --- 滚动前推 ---
    for sg in segs:
        ta, tb = sg["train_full"]
        tea, teb = sg["test"]
        if ta < start:
            ta = start  # anchored 由 start 控制；rolling 保持 3 年窗
        row = {"test": [tea, teb]}
        for mode in ("rolling", "anchored"):
            tr_a = sg["train_full"][0] if mode == "rolling" else start
            tr_mask = _mask_range(didx, cal, tr_a, tb)
            te_mask = _mask_range(didx, cal, tea, teb)
            entry = {"train": [tr_a, tb], "prod": _seg_metrics(prod_sel & te_mask, R, hcols, eidx, uni)}
            # 参数稳定性：学习窗内重选 → OOS 评分
            if L["param_grid"]:
                hcol = hcols[5]
                scored = []
                for p in L["param_grid"]:
                    sel_p = L["sel_fn"](p) if not isinstance(p, tuple) else L["sel_fn"](*p)
                    v = L["param_metric"](p, tr_mask, hcol) if not isinstance(p, tuple) else \
                        L["param_metric"](sel_p, tr_mask, hcol)
                    if v is not None:
                        scored.append((v, p, sel_p))
                if scored:
                    scored.sort(key=lambda x: -x[0])
                    best_v, best_p, best_sel = scored[0]
                    entry["train_best"] = {"params": L["param_fmt"](best_p),
                                           "train_value%": round(100 * best_v, 3)}
                    entry["train_best_oos"] = _seg_metrics(best_sel & te_mask, R, hcols, eidx, uni)
                    entry["prod_params"] = L["param_fmt"](L["prod_params"])
                    # 生产参数在全部候选中的名次
                    ranks = [i for i, (_, p, _) in enumerate(scored)
                             if (p == L["prod_params"])]
                    entry["prod_rank_in_train"] = (ranks[0] + 1) if ranks else None
                    entry["n_param_candidates"] = len(scored)
            row[mode] = entry
        res["segments"].append(row)

    # --- 全样本 DSR（日历口径，T+5）+ trials 记账 ---
    r5 = R[prod_sel, hcols[5]]
    e5 = eidx[prod_sel]
    ser = _cal_series(r5, e5, uni[5])
    n_seg = len(segs)
    res["trials"] = {"前推测试段数": n_seg, "dsr_base": TRIALS_BASE,
                     "trials_total": TRIALS_BASE + n_seg}
    if len(ser) >= 30:
        x = np.asarray(ser)
        m, sd = float(x.mean()), float(x.std(ddof=1))
        sr_d = m / sd if sd > 0 else 0
        skew = float(((x - m) ** 3).mean() / sd ** 3) if sd > 0 else 0
        kurt = float(((x - m) ** 4).mean() / sd ** 4) if sd > 0 else 3
        res["dsr"] = {"T": len(ser), "sr_daily": round(sr_d, 4),
                      "DSR(base)": deflated_sharpe(sr_d, len(ser), skew, kurt, TRIALS_BASE),
                      "DSR(+segments)": deflated_sharpe(sr_d, len(ser), skew, kurt,
                                                        TRIALS_BASE + n_seg)}

    # --- edge 衰减曲线（rolling 生产口径，T+5）---
    curve = []
    for row in res["segments"]:
        st = row["rolling"]["prod"].get("T+5", {})
        curve.append({"test": row["test"], "n": st.get("n", 0),
                      "mean%": st.get("mean%"), "win%": st.get("win%"),
                      "cal_excess_pp": (st.get("日历") or {}).get("日均超额pp"),
                      "cal_t_NW": (st.get("日历") or {}).get("t_NW")})
    res["edge_decay_rolling_t5"] = curve

    # --- 判决：静态双段 vs 前推 ---
    seg_keys = list(seg_masks)
    s1 = res["static_two_segment"][seg_keys[0]].get("T+5", {})
    s2 = res["static_two_segment"][seg_keys[1]].get("T+5", {})
    static_alive = ((s1.get("mean%", 0) or 0) > 0 and (s2.get("mean%", 0) or 0) > 0) \
        if (s1.get("n", 0) >= 5 and s2.get("n", 0) >= 5) else None
    min_n = L.get("min_n", MIN_N)
    tested = [c for c in curve if c["n"] >= min_n]
    neg_ratio = (sum(1 for c in tested if (c["mean%"] or 0) <= 0) / len(tested)) if tested else None
    last2 = tested[-2:]
    wf_dead = bool(tested) and (
        (len(last2) == 2 and all((c["mean%"] or 0) <= 0 for c in last2)) or
        (neg_ratio is not None and neg_ratio >= 0.6))
    res["verdict"] = {
        "static_two_segment_alive": static_alive,
        "wf_min_n": min_n,
        "wf_segments_tested": len(tested),
        "wf_neg_segment_ratio": round(neg_ratio, 2) if neg_ratio is not None else None,
        "wf_last_two_neg": [((c["mean%"] or 0) <= 0) for c in last2],
        "walkforward_dead": wf_dead,
        "divergence": ("静态不可比(单段数据)" if static_alive is None
                       else "双段说活·前推说死" if (static_alive and wf_dead)
                       else "双段说死·前推说活" if ((not static_alive) and not wf_dead and tested)
                       else "一致" if tested else "前推样本不足"),
    }
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()
    t0 = time.time()
    out = {"_meta": {"built": time.strftime("%Y-%m-%d %H:%M"), "fee": FEE,
                     "horizons_deep": list(H_LIST), "horizons_npz": list(NPZ_H),
                     "rolling": "学3年/测6月/步进6月（knn线 2023+ 学2年）",
                     "bootstrap": f"block={BOOT_BLOCK}交易日聚类, B={BOOT_B}",
                     "min_seg_n": MIN_N,
                     "trials纪律": "前推测试段数计入 DSR 分母（7491+段数）",
                     "deep口径": "生产原口径重建（簇门=≤-9.5%且收<MA60且≤MA60×0.75件数≥5，"
                                 "出手票=depth≤-35%最深top5，全命运结算P2）",
                     "择时线": "父卡 t_316237a5 无存活变体，不进前推队列"}}
    npz = load_npz()
    cal = npz[0]
    end = cal[-1]

    jobs = {}
    dep = None
    if args.only is None or "deep_low_v2" in args.only:
        dep = deep_events()
        jobs["deep_low_v2"] = (line_deep(dep, cal), "2019-01-02", 36)
    if args.only is None or "pead_low_pool" in args.only:
        jobs["pead_low_pool"] = (line_npz("pead_low_pool", npz, 2), "2019-01-02", 36)
    if args.only is None or "rev_knn_excl" in args.only or "pead_knn_excl" in args.only:
        knn = load_knn_dec(cal, npz[3])
        if args.only is None or "rev_knn_excl" in args.only:
            jobs["rev_knn_excl"] = (line_npz("rev_knn_excl", npz, 4, knn=knn), "2023-01-03", 24)
        if args.only is None or "pead_knn_excl" in args.only:
            jobs["pead_knn_excl"] = (line_npz("pead_knn_excl", npz, 2, knn=knn), "2023-01-03", 24)

    for name, (L, start, tm) in jobs.items():
        print(f"[wf] {name} ...", flush=True)
        out[name] = run_line(name, L, cal, start, end, tm)
        if name == "deep_low_v2" and dep is not None:
            # 批次层（生产单位=簇日出手的「批」）：逐批日期/票数/T+5/T+10 均值，供衰减判读
            _, batches = deep_select(dep, 5, -0.35)
            bl = []
            for d0 in sorted(batches):
                ks = batches[d0]
                bl.append({"date": cal[d0], "n": len(ks),
                           "t5%": round(100 * float(np.mean([dep["events"][k][5] for k in ks])), 2),
                           "t10%": round(100 * float(np.mean([dep["events"][k][6] for k in ks])), 2)})
            out[name]["batches"] = bl
            out[name]["batch_summary"] = {
                "批数": len(bl), "批胜率T+5": round(100 * sum(b["t5%"] > 0 for b in bl) / max(len(bl), 1), 1),
                "批均T+5%": round(float(np.mean([b["t5%"] for b in bl])), 2) if bl else None,
                "批均T+10%": round(float(np.mean([b["t10%"] for b in bl])), 2) if bl else None,
                "最差批T+5%": min((b["t5%"] for b in bl), default=None)}
            # 对照：可成交口径（剔次日一字跌停开，#282 已量化其剔除价值约 +0.9pp）
            _, bb = deep_select(dep, 5, -0.35, require_buyable=True)
            rb = [np.mean([dep["events"][k][5] for k in ks]) for ks in bb.values()]
            out[name]["batch_summary"]["对照_剔一字跌停开"] = {
                "批数": len(bb), "批均T+5%": round(100 * float(np.mean(rb)), 2) if rb else None,
                "批胜率T+5": round(100 * float(np.mean([x > 0 for x in rb])), 1) if rb else None}
        v = out[name]["verdict"]
        print(f"[wf] {name}: {v['divergence']}  static_alive={v['static_two_segment_alive']} "
              f"wf_dead={v['walkforward_dead']} neg_ratio={v['wf_neg_segment_ratio']}", flush=True)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[wf] DONE -> {OUT} elapsed={time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
