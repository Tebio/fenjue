#!/usr/bin/env python3
"""engine/similarity_daily.py — 协同过滤每日工具化（第三波·产品化，#276 排序层落地）

读取既有日度产物 JSON（只读对接，不重判信号、不改 radar/任何上游代码）：
  docs/ops-state.json          -> deep_low      深档触发（个股件）
  data/reversal_confirmed.json -> executable    反转族确认名单
  data/watch_pool.json         -> pool          观察池
对每只触发票用 GridCF（无 regime 轴 D 口径，#276 实测最强/#277 knn_vote 同口径）打分：
  learn = similarity_features.npz 全部历史行（信号日之前的股票日，PIT 安全），
  分箱边界=学习期分位数，稀疏格层级回退（与 similarity_engine._grid_predict 逐行一致，
  本文件附带自校验：抽样对比两实现输出必须相等）。
输出 data/similarity_daily_YYYYMMDD.json，字段设计供 stock_radar.py / 晨报只读引用：
  每票: knn_t1/t5/t20_pct（期望净收益%）、pct_rank_hist（历史分位 0-1）、top_decile、
        n_neighbors（最终格内学习样本数）、grid_level（回退层级 0=最细）。
用法：.venv/bin/python engine/similarity_daily.py [--date YYYY-MM-DD]
"""
import json, sys, time, math, argparse
from pathlib import Path

import numpy as np

ROOT = Path("/opt/data/fenjue")
KC, CAP = ROOT / "data/big_kcache", ROOT / "data/cap_hist"
FEAT_NPZ = ROOT / "data/similarity_features.npz"
GRID_MIN_N = 200          # 与 similarity_engine 一致
FEE = 0.0015

SRC_FILES = {
    "deep_low": ("docs/ops-state.json", lambda j, d: [x for x in j.get("deep_low", [])] if j.get("sig_date") == d else []),
    "reversal_confirmed": ("data/reversal_confirmed.json", lambda j, d: j.get("executable", []) if j.get("date") == d else []),
    "watch_pool": ("data/watch_pool.json", lambda j, d: j.get("pool", [])),  # 池为状态制，无单日日期
}


def _load_json(p):
    return json.loads(open(p, encoding="utf-8").read())


# ---------------- GridCF 打分（口径逐行复刻 similarity_engine._grid_predict, use_regime=False） ----------------

def _grid_bins(Fl):
    """学习期分位数边界（无泄漏）：返回 depth60/ret60/volr5/log_cap 四轴边界。"""
    return [np.nanquantile(Fl[:, 0], np.linspace(0.05, 0.95, 10)),
            np.nanquantile(Fl[:, 1], np.linspace(0.05, 0.95, 10)),
            np.nanquantile(Fl[:, 2], np.linspace(0.1, 0.9, 5)),
            np.nanquantile(Fl[:, 3], np.linspace(0.1, 0.9, 5))]


def _grid_score(Fl, Rl, Ft):
    """Fl/Rl=学习集(只取4轴+T+1/5/20收益), Ft=测试行(N,4)。
    返回 (pred[N,3]=T+1/5/20 净收益预测, level[N], cell_n[N])。
    层级回退链 = [(depth,ret60,volr5,cap),(depth,ret60,cap),(depth,cap),(depth,)]，与 D 方向一致。"""
    edges = _grid_bins(Fl)
    widths = [10, 10, 5, 5]
    al = [np.clip(np.searchsorted(e, Fl[:, c]), 0, len(e)).astype(np.int64) for e, c in zip(edges, range(4))]
    at = [np.clip(np.searchsorted(e, Ft[:, c]), 0, len(e)).astype(np.int64) for e, c in zip(edges, range(4))]
    levels = [(0, 1, 2, 3), (0, 1, 3), (0, 3), (0,)]
    pred = np.full((len(Ft), 3), np.nan, dtype=np.float32)
    level = np.full(len(Ft), -1, dtype=np.int8)
    cell_n = np.zeros(len(Ft), dtype=np.int32)
    remaining = np.ones(len(Ft), dtype=bool)
    for lv, use in enumerate(levels):
        kl = np.zeros(len(Fl), dtype=np.int64)
        kt = np.zeros(len(Ft), dtype=np.int64)
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
        level[take] = lv
        cell_n[take] = cnt[kt[take]]
        remaining &= ~take
    if remaining.any():  # 全局兜底
        for hi in range(3):
            pred[remaining, hi] = np.nanmean(Rl[:, hi])
        level[remaining] = len(levels)
        cell_n[remaining] = len(Fl)
    return pred, level, cell_n


def _selfcheck(se, F, R, li, Ft):
    """抽样校验本文件 _grid_score 与 similarity_engine._grid_predict 口径一致（防口径漂移）。"""
    rng = np.random.default_rng(3)
    ti = np.sort(rng.choice(len(F), min(3000, len(F)), replace=False))
    pred_ref = se._grid_predict(F, R, li, ti, use_regime=False)
    Fsub = F[:, [0, 2, 6, 8]]
    pred_mine, _, _ = _grid_score(Fsub[li], R[li], F[ti][:, [0, 2, 6, 8]])
    a, b = pred_ref[:, :3], pred_mine
    fa, fb = np.isfinite(a), np.isfinite(b)
    ok = fa & fb
    assert (fa == fb).all() and np.abs(a[ok] - b[ok]).max() < 1e-5, \
        f"口径自校验失败: max|diff|={np.abs(a[ok] - b[ok]).max()} finite_mismatch={(fa != fb).sum()}"
    print(f"[selfcheck] grid 口径一致 (3000 抽样 max|diff|<1e-5)")


# ---------------- 单票单日特征（复刻 build() 的当日取值，只取 grid 四轴） ----------------

def _features_at(code, date):
    """返回 (depth60, ret60, volr5, log_cap) 或 None（数据不足/当日无 bar）。"""
    f = KC / f"{code}.json"
    if not f.exists():
        return None
    ks = _load_json(f)
    n = len(ks)
    dates = [k["date"] for k in ks]
    if date not in dates:
        return None
    i = dates.index(date)
    if i < 66:
        return None
    c = np.array([k["close"] for k in ks])
    v = np.array([k.get("volume", 0.0) for k in ks])
    ma60 = c[i - 59:i + 1].mean()
    depth60 = c[i] / ma60 - 1
    ret60 = c[i] / c[i - 60] - 1
    base5 = v[i - 5:i].mean() if i >= 5 else np.nan
    volr5 = v[i] / base5 if base5 and base5 > 0 else np.nan
    log_cap = np.nan
    capf = CAP / f"{code}.json"
    if capf.exists():
        rows = sorted(_load_json(capf), key=lambda r: r[0])
        j = np.searchsorted([r[0] for r in rows], date, side="right") - 1
        if j >= 0 and rows[j][2] > 0:
            log_cap = math.log10(rows[j][2])
    return np.array([depth60, ret60, volr5, log_cap], dtype=np.float32)


# ---------------- 主流程 ----------------

def run(target_date):
    t0 = time.time()
    ind_map = _load_json(ROOT / "data/industry_map.json")

    # 1) 读当日触发集（只读，带日期新鲜度闸：文件日期≠目标日则记 stale 跳过）
    triggers = {}
    src_meta = {}
    for src, (rel, pick) in SRC_FILES.items():
        p = ROOT / rel
        if not p.exists():
            src_meta[src] = {"file": rel, "status": "missing"}
            continue
        rows = pick(_load_json(p), target_date)
        src_meta[src] = {"file": rel, "n": len(rows),
                         "status": "ok" if rows or src == "watch_pool" else "stale_or_empty"}
        for r in rows:
            code = str(r.get("code", "")).zfill(6)
            if not code:
                continue
            e = triggers.setdefault(code, {"code": code, "name": r.get("name") or "", "sources": []})
            e["sources"].append(src)
            if not e["name"]:
                e["name"] = (ind_map.get(code) or {}).get("name", "")
    print(f"[daily] {target_date} 触发票 {len(triggers)} 只 "
          f"({', '.join(f'{k}={v.get('n', 0)}' for k, v in src_meta.items())})", flush=True)
    if not triggers:
        print("[daily] 当日无触发，落空 JSON")

    # 2) 加载特征矩阵（内存纪律：只取 grid 四轴列 + 收益 + didx，峰值 ~150MB）
    z = np.load(FEAT_NPZ)
    calendar = z["calendar"].tolist()
    didx = z["didx"]
    ti_date = calendar.index(target_date) if target_date in calendar else None
    if ti_date is None:
        print(f"[daily] {target_date} 不在交易日历，退出")
        sys.exit(1)
    li = np.where(didx < ti_date)[0]           # PIT：学习集=信号日之前的全部股票日
    Fsub = z["F"][:, [0, 2, 6, 8]].copy()      # depth60/ret60/volr5/log_cap
    R = z["R"].copy()
    print(f"[daily] learn={len(li)} rows load={time.time()-t0:.0f}s", flush=True)

    # 口径自校验（抽样对比 similarity_engine._grid_predict）
    sys.path.insert(0, str(ROOT / "engine"))
    import similarity_engine as se
    Ffull = z["F"]  # 自校验需要完整 15 维（仅此次访问）
    _selfcheck(se, Ffull, R, li, None)
    del Ffull

    # 3) 学习集全量打分 → 历史分位参照分布
    pred_l, _, _ = _grid_score(Fsub[li], R[li], Fsub[li])
    hist5 = np.sort(pred_l[:, 1])
    hist1 = np.sort(pred_l[:, 0])

    # 4) 触发票打分
    codes = sorted(triggers)
    Ft, valid = [], []
    for c in codes:
        fv = _features_at(c, target_date)
        if fv is None:
            triggers[c]["error"] = "no_bar_or_insufficient_history"
            continue
        Ft.append(fv)
        valid.append(c)
    if Ft:
        pred, level, cell_n = _grid_score(Fsub[li], R[li], np.vstack(Ft))
        for k, c in enumerate(valid):
            e = triggers[c]
            e.update({
                "knn_t1_pct": round(float(pred[k, 0]) * 100, 3),
                "knn_t5_pct": round(float(pred[k, 1]) * 100, 3),
                "knn_t20_pct": round(float(pred[k, 2]) * 100, 3),
                "pct_rank_hist": round(float(np.searchsorted(hist5, pred[k, 1]) / len(hist5)), 3),
                "pct_rank_hist_t1": round(float(np.searchsorted(hist1, pred[k, 0]) / len(hist1)), 3),
                "top_decile": bool(pred[k, 1] >= hist5[int(len(hist5) * 0.9)]),
                "n_neighbors": int(cell_n[k]),
                "grid_level": int(level[k]),
            })

    out = {
        "_meta": {"built": time.strftime("%Y-%m-%d %H:%M"), "engine": "GridCF-D(无regime轴)",
                  "min_cell_n": GRID_MIN_N, "fee": FEE, "learn_rows": int(len(li)),
                  "口径": "次日开盘入,一字开剔,净0.15%,分箱边界=学习期(信号日前全部股票日)分位数",
                  "refs": "AGENTS.md #276/#277；RES-07 排序层定位，不作独立触发"},
        "date": target_date,
        "sources": src_meta,
        "hist_score_t5_quantiles": {str(q): round(float(np.quantile(hist5, q)) * 100, 3)
                                    for q in (0.1, 0.5, 0.9)},
        "scores": [triggers[c] for c in codes],
    }
    op = ROOT / "data" / f"similarity_daily_{target_date.replace('-', '')}.json"
    with open(op, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[daily] DONE -> {op} elapsed={time.time()-t0:.0f}s")
    for c in codes:
        e = triggers[c]
        if "knn_t5_pct" in e:
            print(f"  {c} {e['name']:<8} src={'+'.join(e['sources']):<28} "
                  f"T+5={e['knn_t5_pct']:+.3f}% 分位={e['pct_rank_hist']:.2f} "
                  f"邻居={e['n_neighbors']} lv={e['grid_level']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    a = ap.parse_args()
    d = a.date
    if not d:  # 默认=最新日度产物日期
        for rel in ("docs/ops-state.json", "data/reversal_confirmed.json"):
            p = ROOT / rel
            if p.exists():
                j = _load_json(p)
                d = j.get("sig_date") or j.get("date")
                if d:
                    break
    run(d)
