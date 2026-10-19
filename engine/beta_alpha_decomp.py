#!/usr/bin/env python3
"""engine/beta_alpha_decomp.py — beta vs alpha 分解审判（kanban 卡 t_6e6606e7）

动机：#290 walk-forward 判决「事件级正均值主要来自恐慌后大盘反弹的 beta 时点」
（四线日历时间日度超额 NW-t 多 ≤0、DSR≈0）。本卡把这句判决做成四重可证伪分解，
逐线给出**可加恒等式**：总edge = 全体宇宙均 + 时点beta + 位置beta + 净alpha（残差恒 0）。

对象（事件集全部复用既有产物，禁止重新探测）：
  DEEP_LO_V2   深档低位v2 生产口径（簇门 cnt25≥5 × depth≤−35% × 每日取最深 top5）
               ★主口径：含退市宇宙 / 全命运结算 / 一字跌停开也计（与 deep_batches_full_20260927 台账同源）
  DEEP_LO_V2_npz  同口径的 npz 版（辅助：npz builder 剔 ST/退名 = 幸存者样本，用于对照偏差）
  LD_LOW       跌停接（npz：day≤−9.5% 且 收盘≤MA60）
  PEAD_LOW     预增低位池（npz bit1）
  REV_KNN_KEEP / REV_KNN_DROP  反转族 × knn_vote dec>1（留存）/ dec≤1（别碰），OOS 2023+

四把刀（各自独立成节）：
  ① 市场超额口径：事件收益 − 同日等权全宇宙收益 → 超额剩几 pp、NW-t 多少
  ② 时点置换安慰剂：同一只票上把事件日平移 ±5/10/20 交易日 ×1000 → 真值落什么分位
  ③ 同日同深度对照：同日、同 depth 十分位桶、非本线信号的行 → 净 alpha = 信号 − 对照
  ④ 日内截面分散度：同日内部 depth/dhigh/knn 对相对收益的 RankIC + 日簇规模效应

产出 data/beta_alpha_decomp_20261016.json。用法：.venv/bin/python engine/beta_alpha_decomp.py
"""
import json, math, sys, time
from pathlib import Path
from collections import defaultdict

import numpy as np

ROOT = Path("/opt/data/fenjue")
FEAT = ROOT / "data/similarity_features.npz"
BASE = ROOT / "data/factor_census_base.npz"
TIMELINE = ROOT / "data/regime_timeline_hcap.json"
LEDGER = ROOT / "data/deep_batches_full_20260927.json"
OUT = ROOT / "data/beta_alpha_decomp_20261016.json"
N_SHIFT = 1000
SEED = 20261016
sys.path.insert(0, str(ROOT / "engine"))
from law_pipeline import nw_t   # 共享统计件（#262-C 纪律：禁一次性脚本各写一份）


def stats(rs, lag=5):
    rs = np.asarray(rs, float); rs = rs[np.isfinite(rs)]
    n = len(rs)
    if n < 10:
        return {"n": int(n)}
    m, sd = float(rs.mean()), float(rs.std(ddof=1))
    win, los = rs[rs > 0], rs[rs < 0]
    o = {"n": int(n), "win%": round(100 * float((rs > 0).mean()), 1),
         "mean%": round(100 * m, 3), "med%": round(100 * float(np.median(rs)), 3),
         "t": round(m / (sd / math.sqrt(n)), 2) if sd > 0 else None,
         "odds": round(float(win.mean() / abs(los.mean())), 2) if len(win) and len(los) else None}
    if n >= lag + 30:
        o["t_NW"] = nw_t(rs.tolist(), lag)
    return o


def fin(x):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    return float(x.mean()) if len(x) else None


def f100(v):
    return None if v is None else round(100 * float(v), 3)


def pct_of(dist, v):
    d = np.asarray(dist, float); d = d[np.isfinite(d)]
    if not len(d) or v is None:
        return None
    return round(float((d < v).mean()), 3)


def spearman(a, b):
    a = np.asarray(a, float); b = np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if len(a) < 3:
        return None
    ra = np.argsort(np.argsort(a)).astype(float); rb = np.argsort(np.argsort(b)).astype(float)
    ra -= ra.mean(); rb -= rb.mean()
    den = math.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    return float((ra * rb).sum() / den) if den > 0 else None


def cal_series(rets, eday, uni_map):
    """日历时间日度超额序列：事件日聚均值 − 当日宇宙均（#290 主判据口径）"""
    by = defaultdict(list)
    for e, x in zip(eday, rets):
        if np.isfinite(x):
            by[int(e)].append(float(x))
    s = np.array([np.mean(v) - uni_map[d] for d, v in sorted(by.items()) if d in uni_map])
    if len(s) < 30:
        return {"天数": int(len(s)), "note": "样本不足（<30 交易日）"}
    m, sd = float(s.mean()), float(s.std(ddof=1))
    return {"天数": int(len(s)), "日均超额pp": round(100 * m, 3), "t_NW": nw_t(s.tolist(), 5),
            "年化Sharpe": round((m / sd if sd > 0 else 0) * math.sqrt(244), 2)}


def decile(x, n=10):
    x = np.asarray(x, float)
    return np.clip(np.digitize(x, np.percentile(x, np.arange(100 / n, 100, 100 / n))), 0, n - 1)


class Line:
    """统一事件表：一行一个事件。R 列与 horizons 对齐。"""

    def __init__(self, name, note, code, sig_day, entry_day, R, horizons, depth,
                 dhigh=None, knn=None, universe=None, uni_all=None, pool=None, batches=None):
        self.name, self.note = name, note
        self.code = np.asarray(code, np.int64)
        self.sig_day = np.asarray(sig_day, np.int64)
        self.entry_day = np.asarray(entry_day, np.int64)
        self.R = np.asarray(R, float)
        self.horizons = tuple(horizons)
        self.depth = np.asarray(depth, float)
        self.dhigh = np.zeros(len(self.depth)) if dhigh is None else np.asarray(dhigh, float)
        self.knn = None if knn is None else np.asarray(knn, float)
        self.universe = universe or {}
        self.uni_all = uni_all or {}
        self.pool = pool or {}      # {(day, bucket): local rows}
        self.idx_map = None         # external row -> local row (-1 if absent)
        self.batches = batches or {}
        # 生产口径线（事件 bar 不在 npz 全表内）时置为 npz dict：平移后的 bar 回 npz 取价，
        # 真值也改在 npz 口径上取，两侧同宇宙可比。默认 None = 用本线自带 R。
        self.placebo_npz = None
        self.n = len(self.sig_day)
        self.bucket = decile(self.depth, 10)

    def to_local(self, ext):
        """外部行号（npz 全局行 / deep 事件序号）-> 本线局部行号（缺失 -1）"""
        ext = np.asarray(ext, np.int64)
        m = self.idx_map
        if m is None:
            return ext
        m = np.asarray(m)
        ok = (ext >= 0) & (ext < len(m))
        out = np.full(len(ext), -1, np.int64)
        out[ok] = m[ext[ok]]
        return out

    def build_pool(self, ext_pool):
        """把外部行号池映射到局部空间并按桶归一"""
        p = {}
        for key, arr in ext_pool.items():
            loc = self.to_local(arr)
            loc = loc[loc >= 0]
            if len(loc):
                p[key] = loc
        return p

    def hcol(self, h):
        return self.horizons.index(h)

    def day_uni(self, h):
        u = self.universe[h]
        return np.array([u.get(int(d), np.nan) for d in self.entry_day])

    def excess(self, h):
        return self.R[:, self.hcol(h)] - self.day_uni(h)


def load_npz():
    z = np.load(FEAT, mmap_mode="r")
    d = dict(cal=z["calendar"].tolist(), didx=np.asarray(z["didx"]),
             eidx=np.asarray(z["eidx"]), code=np.asarray(z["code"]),
             flags=np.asarray(z["flags"]), day_pct=np.asarray(z["day_pct"], float),
             R=np.asarray(z["R"], float), F=z["F"])
    d["depth"] = np.asarray(d["F"][:, 0], float)
    d["dhigh"] = np.asarray(d["F"][:, 1], float)
    zb = np.load(BASE, mmap_mode="r")
    assert zb["calendar"].tolist() == d["cal"], "base 日历不一致"
    c2j = {int(c): j for j, c in enumerate(zb["codes"].tolist())}
    js = np.array([c2j.get(int(c), -1) for c in d["code"]])
    knn = np.full(len(d["code"]), 255, np.uint8)
    ok = js >= 0
    knn[ok] = np.asarray(zb["dec_knn_vote"])[d["didx"][ok], js[ok]]
    d["knn"] = knn
    del zb
    return d


def npz_universe(z, hs=(1, 5, 20)):
    uni = {}
    for h in hs:
        i = (1, 5, 20).index(h)
        r = z["R"][:, i]; ok = np.isfinite(r)
        ue, inv = np.unique(z["eidx"][ok], return_inverse=True)
        cnt = np.bincount(inv)
        uni[h] = dict(zip(ue.tolist(), (np.bincount(inv, weights=r[ok]) / np.maximum(cnt, 1)).tolist()))
    return uni


def rows_at(keys_sorted, korder, code, day):
    """按 (code, day) 在 npz 行索引里定位；返回行号，未命中 -1"""
    k = np.asarray(code, np.int64) * 4096 + np.asarray(day, np.int64)
    j = np.clip(np.searchsorted(keys_sorted, k), 0, len(keys_sorted) - 1)
    out = np.full(len(k), -1, np.int64)
    hit = keys_sorted[j] == k
    out[hit] = korder[j[hit]]
    return out


def build_pool(z, sig_rows_by_line):
    """{(day,bucket): 行数组} —— 当日全部行按 depth 十分位分桶（不受线路筛选影响）"""
    b = decile(z["depth"], 10)
    pool = defaultdict(list)
    for r in range(len(b)):
        pool[(int(z["didx"][r]), int(b[r]))].append(r)
    return {k: np.asarray(v, np.int64) for k, v in pool.items()}, b


def run_line(L, panic, z, keys_sorted, korder, rng, hs_main=5):
    nd = len(z["cal"])          # 交易日总数（原实现漏定义 → NameError，2026-10-16 终审修复）
    out = {"note": L.note, "n": int(L.n), "口径": "次日开盘入 / 净费 0.15% 已含（npz 一字开已剔）"}
    out["基础"] = {f"T+{h}": stats(L.R[:, L.hcol(h)], lag=h) for h in L.horizons}
    i5 = L.hcol(hs_main)

    # ---------- ① 市场超额口径 ----------
    sec1 = {"时点beta": {}}
    for h in L.horizons:
        i = L.hcol(h); ex = L.excess(h)
        sec1[f"T+{h}"] = {"事件均值pp": f100(fin(L.R[:, i])),
                          "事件日宇宙均pp": f100(fin(L.day_uni(h))),
                          "同日超额pp": f100(fin(ex)),
                          "超额NW-t(事件级)": stats(ex, lag=h).get("t_NW"),
                          "日度超额": cal_series(L.R[:, i], L.entry_day, L.universe[h])}
        sec1["时点beta"][f"T+{h}"] = {
            "事件日宇宙均−全体宇宙均pp": f100(fin(L.day_uni(h)) - L.uni_all[h]),
            "全体宇宙均pp": f100(L.uni_all[h])}
    out["①市场超额口径"] = sec1

    # ---------- ② 时点置换安慰剂（同票平移 ±5/10/20 ×1000） ----------
    real5 = fin(L.R[:, i5]); real_ex5 = fin(L.excess(hs_main))
    cand = np.array([-20, -10, -5, 5, 10, 20])
    uni5 = L.universe[hs_main]
    if L.placebo_npz:
        # 生产口径线（big_kcache 全命运结算）：npz 里没有该事件的 bar 全表，
        # 平移后的 bar 必须回到 npz 取收益 → 真值也在 npz 口径上取，两侧同宇宙可比
        z = L.placebo_npz
        R5 = z["R"][:, 1]
        t0_rows = rows_at(keys_sorted, korder, L.code, L.entry_day)
        t0_rows = t0_rows[t0_rows >= 0]
        real5 = fin(R5[t0_rows])
        real_ex5 = fin(R5[t0_rows] - np.array([uni5.get(int(z["eidx"][r]), np.nan) for r in t0_rows]))
    sim_raw = np.full(N_SHIFT, np.nan); sim_ex = np.full(N_SHIFT, np.nan)
    for t in range(N_SHIFT):
        want = L.entry_day + cand[rng.integers(0, 6, L.n)]
        ext = rows_at(keys_sorted, korder, L.code, want)
        okm = (ext >= 0) & (want >= 0) & (want < nd)
        ext = ext[okm]
        if not len(ext):
            continue
        if L.placebo_npz:
            z = L.placebo_npz
            R5 = z["R"][:, 1]
            sim_raw[t] = fin(R5[ext])
            sim_ex[t] = fin(R5[ext] - np.array([uni5.get(int(z["eidx"][r]), np.nan) for r in ext]))
            continue
        loc = L.to_local(ext)
        loc = loc[loc >= 0]
        if not len(loc):
            continue
        sim_raw[t] = fin(L.R[loc, i5])
        sim_ex[t] = fin(L.R[loc, i5] - np.array([uni5.get(int(L.entry_day[j]), np.nan) for j in loc]))
    out["②时点置换安慰剂"] = {
        "B": N_SHIFT, "口径": "同一只票的 bar 上把事件日平移 ±5/10/20 交易日；控住个股、未控住当时位置/形态",
        "真T+5均值pp": f100(real5),
        "安慰剂T+5 P5/P50/P95pp": [f100(float(np.nanpercentile(sim_raw, q))) for q in (5, 50, 95)],
        "真值分位(原始均值)": pct_of(sim_raw, real5),
        "真T+5超额pp": f100(real_ex5),
        "安慰剂超额P5/P50/P95pp": [f100(float(np.nanpercentile(sim_ex, q))) for q in (5, 50, 95)],
        "真值超额分位": pct_of(sim_ex, real_ex5),
        "note": "分位 = P(安慰剂 < 真值)；≥0.95 才算真值显著高于随机时点"}

    # ---------- ③ 同日同深度对照 ----------
    ctrl = np.full(L.n, -1, np.int64)
    for j in range(L.n):
        p = L.pool.get((int(L.sig_day[j]), int(L.bucket[j])))
        if p is not None and len(p):
            ctrl[j] = p[rng.integers(0, len(p))]
    v = ctrl >= 0
    ctrl_raw = L.R[ctrl[v], i5] if v.any() else np.array([])
    dayu = L.day_uni(hs_main)
    net_alpha = fin(L.R[v, i5] - L.R[ctrl[v], i5]) if v.any() else None
    pos_beta = fin(L.R[ctrl[v], i5] - dayu[v]) if v.any() else None
    sec3 = {"定义": "同日、同 depth 十分位桶、非本线信号的行（对照池=当日全行分桶，本线信号行已从池中剔除）",
            "匹配率": round(float(v.mean()), 3) if L.n else None,
            "信号T+5原始均值pp": f100(real5), "对照T+5原始均值pp": f100(fin(ctrl_raw)),
            "信号T+5超额pp": f100(real_ex5),
            "对照T+5超额pp": f100(fin(L.R[ctrl[v], i5] - dayu[v])) if v.any() else None,
            "位置beta(对照原始−当日宇宙均)pp": f100(pos_beta),
            "净alpha(信号−对照原始)pp": f100(net_alpha),
            "对照分位(信号 vs 对照分布)": pct_of(ctrl_raw, real5),
            "note": "净alpha 已扣掉时点与位置两层；对照池按 (day, depth十分位) 精确匹配"}
    pev = panic[L.sig_day]
    if pev.sum() >= 10:
        sub = np.nonzero(pev & v)[0]
        sec3["同regime专项(信号落在恐慌/暴跌日)"] = {
            "恐慌信号事件数": int(pev.sum()),
            "恐慌信号T+5超额pp": f100(fin(L.R[pev, i5] - dayu[pev])),
            "恐慌信号净alpha pp": f100(fin(L.R[sub, i5] - L.R[ctrl[sub], i5])) if len(sub) else None,
            "note": "排除「信号日多是非恐慌日」的 regime 混淆：只在恐慌/暴跌日内部比"}
    out["③同日同深度对照(T+5)"] = sec3

    # ---------- ④ 日内截面分散度 ----------
    by_day = defaultdict(list)
    for j in range(L.n):
        by_day[int(L.sig_day[j])].append(j)
    feats = {"深度(−depth)": -L.depth, "位置(dhigh60)": L.dhigh}
    if L.knn is not None:
        feats["knn_dec档"] = L.knn
    ics = {k: [] for k in feats}
    spread, dayn, dayex = [], [], []
    for d, ks in by_day.items():
        u = uni5.get(int(d), np.nan)
        if not np.isfinite(u):
            continue
        rel = L.R[ks, i5] - u
        for nm, sc in feats.items():
            val = spearman(sc[ks], rel)
            if val is not None:
                ics[nm].append(val)
        if len(ks) >= 6 and fin(rel) is not None:
            o = np.argsort(rel); kk = max(1, len(ks) // 3)
            spread.append(float(np.nanmean(rel[o[-kk:]]) - np.nanmean(rel[o[:kk]])))
        if fin(rel) is not None:
            dayn.append(len(ks)); dayex.append(fin(rel))
    sec4 = {}
    for nm, vs in ics.items():
        if len(vs) < 20:
            sec4[nm] = {"截面日数": len(vs), "note": "不足 20 天"}
            continue
        vv = np.array(vs)
        sec4[nm] = {"截面日数": int(len(vv)), "日均RankIC": round(float(vv.mean()), 4),
                    "IC_t_NW": nw_t(vv.tolist(), 5), "IC>0占比": round(float((vv > 0).mean()), 3)}
    if len(spread) >= 20:
        s = np.array(spread)
        sec4["当日内部顶1/3−底1/3价差"] = {
            "截面日数": len(s), "均值pp": round(100 * float(s.mean()), 3),
            "t": round(float(s.mean() / (s.std(ddof=1) / math.sqrt(len(s)))), 2)}
    if len(dayn) >= 20:
        dn = np.array(dayn, float); de = np.array(dayex, float)
        big, small = de[dn >= 10], de[dn < 10]
        sec4["日簇规模×日超额"] = {"信号日数": int(len(dn)), "spearman": round(spearman(dn, de) or 0, 4),
                                   "大簇≥10日数": int((dn >= 10).sum()), "小簇<10日数": int((dn < 10).sum()),
                                   "大簇日均超额pp": f100(fin(big)), "小簇日均超额pp": f100(fin(small))}
    sec4["_note"] = "簇强是日级常量，日内无法算 IC；knn_dec 仅 OOS 2023+"
    out["④日内截面(T+5)"] = sec4

    # ---------- 可加恒等式分解 ----------
    tot = f100(fin(L.R[:, i5]))
    u_all = f100(L.uni_all[hs_main])
    timing = sec1["时点beta"][f"T+{hs_main}"]["事件日宇宙均−全体宇宙均pp"]
    pos = f100(pos_beta); na = f100(net_alpha)
    resid = round(tot - u_all - timing - pos - na, 3) if None not in (tot, u_all, timing, pos, na) else None
    out["分解表(T+5)"] = {
        "口径": "总edge = 全体宇宙均(无条件) + 时点beta + 位置beta + 净alpha，残差应 ≈0（恒等式校验）",
        "全体宇宙均pp": u_all, "时点beta pp": timing, "位置beta pp": pos, "净alpha pp": na, "残差 pp": resid}
    out["判决表(T+5)"] = {
        "总edge pp": tot, "时点beta pp": timing,
        "同日超额(含时点beta)pp": sec1[f"T+{hs_main}"]["同日超额pp"],
        "位置beta pp": pos, "净alpha(去时点去位置)pp": na,
        "净alpha占总edge比": round(na / tot, 3) if (na is not None and tot) else None,
        "②置换超额分位": out["②时点置换安慰剂"]["真值超额分位"],
        "④日内深度RankIC": sec4.get("深度(−depth)", {}).get("日均RankIC")}
    return out


def main():
    t0 = time.time()
    rng = np.random.default_rng(SEED)
    z = load_npz()
    cal = z["cal"]; nd = len(cal)
    print(f"[load] rows={len(z['didx'])} days={nd} {time.time()-t0:.0f}s", flush=True)

    tl = json.loads(TIMELINE.read_text())
    reg = {r["date"]: r["regime"] for r in tl}
    idx = {r["date"]: r.get("idx") for r in tl}
    reg_day = np.array([reg.get(d, "") for d in cal])
    idx_day = np.array([idx.get(d, np.nan) for d in cal], float)
    panic = (reg_day == "恐慌期") | (np.isfinite(idx_day) & (idx_day <= -1.5))
    print(f"[regime] 恐慌/暴跌日并集={int(panic.sum())}", flush=True)

    uni_npz = npz_universe(z)
    uni_all = {h: float(np.mean(list(uni_npz[h].values()))) for h in uni_npz}

    keys = z["code"].astype(np.int64) * 4096 + z["didx"]
    korder = np.argsort(keys, kind="stable")
    ksort = keys[korder]

    deep = z["depth"]; dpct = z["day_pct"]; flags = z["flags"]; knn = z["knn"]
    cnt25 = np.bincount(z["didx"][(dpct <= -0.098) & (deep <= -0.25)], minlength=nd)
    specs = {
        "DEEP_LO_V2_npz": ((cnt25[z["didx"]] >= 5) & (dpct <= -0.098) & (deep <= -0.35),
                           "npz 口径：簇门 cnt25≥5 × day≤−9.8% × depth≤−35%"
                           "（⚠️ npz builder 剔 ST/退名=幸存者样本，仅作生产口径的对照）"),
        "LD_LOW": ((dpct <= -0.095) & (deep <= 0.0), "跌停接（day≤−9.5% 且 收盘≤MA60）"),
        "PEAD_LOW": ((flags & 2) != 0, "预增低位池（bit1：60日内预增 × 距60日高≤−20% × 流通<50亿）"),
        "REV_KNN_KEEP": (((flags & 4) != 0) & (knn > 1) & (knn < 255), "反转族 × knn_vote 留存档(dec>1)"),
        "REV_KNN_DROP": (((flags & 4) != 0) & (knn <= 1) & (knn < 255), "反转族 × knn_vote 别碰档(dec≤1)"),
    }
    # 各线信号行集合（构建对照池时剔除）
    sig_rows = {}
    for nm, (m, _) in specs.items():
        sig_rows[nm] = set(np.nonzero(m)[0].tolist())
    print("[lines] " + " ".join(f"{k}={len(v)}" for k, v in sig_rows.items()), flush=True)

    # 对照池：当日全行按 depth 十分位分桶，逐线剔除自身信号行
    base_bucket = decile(deep, 10)
    day_bucket_rows = defaultdict(list)
    for r in range(len(base_bucket)):
        day_bucket_rows[(int(z["didx"][r]), int(base_bucket[r]))].append(r)
    day_bucket_rows = {k: np.asarray(v, np.int64) for k, v in day_bucket_rows.items()}
    print(f"[pool] buckets={len(day_bucket_rows)} {time.time()-t0:.0f}s", flush=True)

    out = {"_meta": {"built": time.strftime("%Y-%m-%d %H:%M"), "card": "t_6e6606e7",
                     "repo": str(ROOT), "seed": SEED, "n_shift": N_SHIFT,
                     "口径声明": "入场=信号日次日开盘；npz 一致（一字开剔/净费0.15%）；T+5 主口径",
                     "宇宙": "同日等权全宇宙均（npz=当日有行且可成交的全体；深档线=当日全深渊件同源口径）",
                     "数据来源": "similarity_features.npz + factor_census_base.npz + "
                                "regime_timeline_hcap.json + deep_batches_full_20260927.json",
                     "npz_幸存者警告": "npz builder 剔除名称含 ST/退 的票，退市票不进样本 → 深档类结论偏乐观；"
                                     "生产口径 DEEP_LO_V2 走 big_kcache 全命运结算（含退市）",
                     "DSR": "#290 已报 DSR≈0；本卡只做 β/α 归因，不重算 DSR"}}

    for nm, (m, note) in specs.items():
        i5 = 1  # (1,5,20) 的 5 在列 1
        k = np.nonzero(m)[0]
        if len(k) < 20:
            out[nm] = {"n": int(len(k)), "note": "样本不足"}
            continue
        pool = {key: arr[np.isin(arr, list(sig_rows[nm]), invert=True)] for key, arr in day_bucket_rows.items()}
        L = Line(nm, note, z["code"][k], z["didx"][k], z["eidx"][k], z["R"][k][:, [0, 1, 2]],
                 (1, 5, 20), deep[k], z["dhigh"][k],
                 knn=(knn[k].astype(float) if nm.startswith("REV") else None),
                 universe=uni_npz, uni_all=uni_all, pool=None)
        g2l = np.full(len(z["didx"]), -1, np.int64)
        g2l[k] = np.arange(len(k), dtype=np.int64)
        L.idx_map = g2l
        L.pool = L.build_pool(pool)
        out[nm] = run_line(L, panic, z, ksort, korder, rng)
        print(f"[{nm}] n={len(k)} 完成 {time.time()-t0:.0f}s", flush=True)

    # ---------- 生产口径 DEEP_LO_V2（含退市宇宙，H=(1,5,10,20)）----------
    try:
        import walkforward as wf
        dep = wf.deep_events()
        uL = dep["uni"]
        evs = dep["events"]; cnt = dep["cnt25"]
        sel, batches = wf.deep_select(dep, 5, -0.35, topn=5, require_buyable=False)
        sel = np.asarray(sel, bool)
        kk = np.nonzero(sel)[0]
        R4 = np.column_stack([np.array([e[4 + i] for e in evs])[kk] for i in range(4)])
        # 全深渊件（depth≤−35%）构成对照池的母集：当日深跌件按 depth 十分位分桶
        all_depth = np.array([e[3] for e in evs], float)
        all_sig = np.array([e[0] for e in evs]); all_entry = np.array([e[1] for e in evs])
        all_R = np.column_stack([np.array([e[4 + i] for e in evs]) for i in range(4)])
        all_code = np.array([int(e[2]) for e in evs])
        ab = decile(all_depth, 10)
        sel_set = set(kk.tolist())
        dr = defaultdict(list)
        for r in range(len(ab)):
            if r in sel_set:
                continue                       # 剔除本线信号行
            dr[(int(all_sig[r]), int(ab[r]))].append(r)
        pool = {t: np.asarray(v, np.int64) for t, v in dr.items()}
        u_all4 = {h: float(np.mean(list(uL[h].values()))) for h in (1, 5, 10, 20)}
        L = Line("DEEP_LO_V2", "深档低位v2 生产口径：簇门 cnt25≥5 × depth≤−35% × 每日最深 top5；"
                "big_kcache 全命运结算（含退市/一字跌停开），与 deep_batches_full_20260927 台账同源",
                all_code[kk], all_sig[kk], all_entry[kk], R4, (1, 5, 10, 20), all_depth[kk],
                universe=uL, uni_all=u_all4, pool=None, batches=batches)
        g2l = np.full(len(evs), -1, np.int64)
        g2l[kk] = np.arange(len(kk), dtype=np.int64)
        L.idx_map = g2l
        L.pool = L.build_pool(pool)
        rec = run_line(L, panic, z, ksort, korder, rng)
        rec["n_batches"] = len(batches)
        ds = np.array([cal[int(d)] for d in all_sig[kk]])
        yrs = np.array([d[:4] for d in ds]); r10 = R4[:, 2]
        rec["分年(T+10)"] = {y: {"n": int((yrs == y).sum()), "事件均pp": f100(fin(r10[yrs == y]))}
                             for y in sorted(set(yrs))}
        w24 = yrs == "2024"
        rec["2024集中度(T+10)"] = {"事件占比": round(float(w24.mean()), 3),
                                  "收益贡献占比": round(float(np.nansum(r10[w24]) / np.nansum(r10)), 3)}
        # 台账互证（批级，65 批）
        bl = json.loads(LEDGER.read_text())
        rows = [(b["date"], b["r10"]) for b in bl if b["date"] in cal]
        if rows:
            rr = np.array([x[1] for x in rows])
            dd = np.array([cal.index(x[0]) for x in rows])
            uu = np.array([uL[10].get(int(d), np.nan) for d in dd])
            ex = rr - uu
            rec["台账互证(批级65批/T+10)"] = {
                "n": len(rows), "批均总edge pp": f100(fin(rr)),
                "批均同日宇宙均pp": f100(fin(uu)), "批均同日超额pp": f100(fin(ex)),
                "超额NW-t(批级)": stats(ex, lag=10).get("t_NW"),
                "日度超额": cal_series(rr, dd, uL[10]),
                "note": "台账批级（批内等权）vs 上面事件级（逐事件等权）——两口径同源宇宙，数值应量级一致"}
        out["DEEP_LO_V2"] = rec
        print(f"[DEEP_LO_V2] n={int(sel.sum())} batches={len(batches)} 完成 {time.time()-t0:.0f}s", flush=True)
    except Exception as e:
        import traceback; traceback.print_exc()
        out["DEEP_LO_V2"] = {"error": f"{type(e).__name__}: {e}"}

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"[DONE] -> {OUT} elapsed={time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
