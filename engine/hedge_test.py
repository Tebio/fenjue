#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine/hedge_test.py — beta 对冲 / 市场中性化实测（卡 t_4a55cc92，直接回应 AGENTS #290）

背景：engine/beta_alpha_decomp.py（卡 t_6e6606e7）已把存活线拆成
  总 edge = 时点 beta + 位置 beta + 净 alpha（同日同位置对照），结论是事件级正均值
  主要来自「恐慌后大盘反弹」的 beta 时点。本卡问**可交易版本**：既然收益主要是 beta，
  就把它对冲掉、只留 alpha。

两路对冲 × 五档比例 × 各 horizon：
  ① 期货路  信号日次日开盘买入信号票 + 同日开盘做空 β 倍名义市值 IF/IC/IM 主力连续
  ② ETF 路  同结构做空 510300/510500/512100（A 股散户唯一做空方式 = 融券卖出，含借券费）
  ③ λ ∈ {0, 0.3, 0.5, 0.7, 1.0} 对冲比例敏感度（λ=0 即不对冲 = 原始 edge 对照）
  ④ 成本现实检验：期货佣金/滑点/保证金资金占用、ETF 借券费+保证金、真实基差
     （由期货与指数实际成交价隐含）、准入与合约粒度门槛
  ⑤ 位置匹配对照：同日同 depth 十分位、非信号票，用**同一对冲结构**算净收益，与信号票比

事件集（零重新探测，全部复用既有产物原口径）：
  DEEP_LEDGER  深档低位v2 生产台账口径 —— walkforward.deep_events()+deep_select(5,-0.35,top5)
  DEEP_NPZ / LD / PEAD / REV  —— npz 行口径（day_pct / depth60 / flags 原定义）

数据（只读）：similarity_features.npz / big_kcache / data/research/hedge_prices_20261016.json
产出 data/research/hedge_test_20261016.json
用法 .venv/bin/python engine/hedge_test.py       # 全量
     HEDGE_ONLY=LD,REV .venv/bin/python engine/hedge_test.py   # 子集（调试）
"""
import json
import math
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data/big_kcache"
FEAT = ROOT / "data/similarity_features.npz"
PRICES = ROOT / "data/research/hedge_prices_20261016.json"
OUT = ROOT / "data/research/hedge_test_20261016.json"
CAL_ANCHOR = KC / "600000.json"
sys.path.insert(0, str(ROOT / "engine"))
from law_pipeline import nw_t, deflated_sharpe, _skew, _kurt   # noqa: E402  共享统计件

H = (1, 5, 20)          # npz 线 horizon
HL = (1, 5, 10, 20)     # 台账线 horizon
N_CTRL = 40             # 位置匹配对照重抽次数
SEED = 20261016
BETA_WIN = 120          # β 回归窗（交易日，PIT：窗=[i-120, i-1]，剔信号日）
DAYS_YEAR = 244
TRIALS_BASE = 7491      # dsr_recount 实测口径（#262-C）
N_COMBOS = 360          # 本卡新增组合数（4线×2路×3工具×3horizon×5λ）→ DSR 分母增量

# ── 对冲成本参数（真实费目，全部落 _meta 备查）───────────────────────────
FUT_COMM = 0.000023       # 中金所股指期货 开/平昨 万分之 0.23（按成交额计）
FUT_COMM_TODAY = 0.00023  # 平今 万分之 2.3（本卡全走平昨，单列备查）
FUT_SLIP_PT = 0.2         # 滑点 1 个最小变动价位（0.2 点）/边
FUT_MARGIN = 0.15         # 交易所保证金 15%（投机）
ETF_BORROW = 0.085        # 融券借券费率 8.5%/年（券商散户主流档）
ETF_BORROW_ALT = [0.0, 0.085, 0.12]
ETF_COMM_RT = 0.0004      # ETF 佣金往返
ETF_MARGIN = 0.50         # 融券保证金比例
RF = 0.015                # 保证金占用资金成本（货币基金机会成本 1.5%/年）

CONTRACT = {"IF": (300, "沪深300", "sh000300", "sh510300"),
            "IH": (300, "上证50", "sh000016", "sh510050"),
            "IC": (200, "中证500", "sh000905", "sh510500"),
            "IM": (200, "中证1000", "sh000852", "sh512100")}
FUT_ACCESS = ["个人开股指期货：申请前连续 5 个交易日保证金账户可用资金 ≥50 万元",
              "＋知识测试 ≥80 分 ＋10 个交易日/20 笔以上仿真成交记录",
              "1 手最小粒度：IF≈300×点数（≈123 万元）、IC/IM≈200×点数（≈130 万元）名义市值",
              "日内开仓上限 500 手；持仓限额 IF 5000 手 / IH·IC·IM 各 1200 手"]
MARGIN_ACCESS = ["融资融券（含融券卖出 ETF）个人门槛同为 20 日均资产 ≥50 万元",
                 "融券券源受券商库存约束，宽基 ETF 相对充裕但费率/可得性随行情变化",
                 "无券可借时该腿物理不可执行——本卡只报成本，不报可得性概率"]


def stats(rs, lag=5):
    rs = np.asarray(rs, dtype=float)
    rs = rs[np.isfinite(rs)]
    n = len(rs)
    if n < 10:
        return {"n": int(n)}
    m, sd = float(rs.mean()), float(rs.std(ddof=1))
    out = {"n": int(n), "win%": round(100 * float((rs > 0).mean()), 1),
           "mean_pp": round(100 * m, 3), "med_pp": round(100 * float(np.median(rs)), 3),
           "t": round(m / (sd / math.sqrt(n)), 2) if sd > 0 else None}
    if n >= lag + 30:
        out["t_NW"] = nw_t(rs.tolist(), lag)
    return out


def daily_series(vals, days):
    """事件级 → 日度组合序列（按入场日等权聚合）。"""
    by = defaultdict(list)
    for d, x in zip(days, vals):
        if np.isfinite(x):
            by[int(d)].append(float(x))
    ds = sorted(by)
    return np.array([float(np.mean(by[k])) for k in ds]), np.array(ds)


def cal_stats(ser, uni=None, days=None):
    """日度序列 → t_NW + 年化 Sharpe + DSR（含本卡 trials 增量）。"""
    if uni is not None and days is not None:
        ser = np.array([v - uni.get(int(d), 0.0) for v, d in zip(ser, days)])
    ser = np.asarray(ser, float)
    ser = ser[np.isfinite(ser)]
    if len(ser) < 30:
        return {"天数": int(len(ser)), "note": "样本不足(<30 日)"}
    m, sd = float(ser.mean()), float(ser.std(ddof=1))
    sr = m / sd if sd > 0 else 0.0
    out = {"天数": int(len(ser)), "日均_pp": round(100 * m, 3), "日波动_pp": round(100 * sd, 3),
           "年化Sharpe": round(sr * math.sqrt(DAYS_YEAR), 2), "t_NW": nw_t(ser.tolist(), 5)}
    if len(ser) >= 40 and sd > 0:
        sk, ku = _skew(ser.tolist()), _kurt(ser.tolist())
        out["DSR_base"] = deflated_sharpe(sr, len(ser), sk, ku, trials=TRIALS_BASE)
        out["DSR_+本卡组合数"] = deflated_sharpe(sr, len(ser), sk, ku, trials=TRIALS_BASE + N_COMBOS)
    return out


# ── 价格装载 ──────────────────────────────────────────────────────────────
def load_prices(cal):
    raw = json.loads(PRICES.read_text())
    d2i = {d: i for i, d in enumerate(cal)}
    nd = len(cal)
    out, meta = {}, {}
    for key, blk in raw.items():
        if key == "_meta":
            continue
        o = np.full(nd, np.nan)
        c = np.full(nd, np.nan)
        for r in blk["rows"]:
            j = d2i.get(r["date"])
            if j is not None:
                o[j], c[j] = r["open"], r["close"]
        out[key] = {"open": o, "close": c}
        rows = blk["rows"]
        meta[key] = {"n": len(rows), "first": rows[0]["date"], "last": rows[-1]["date"]}
    return out, meta


def short_ret(P, key, h, nd):
    """做空收益序列：第 e 日开盘做空、第 e+h 日收盘平仓 → (o[e] − c[e+h]) / o[e]。
    用真实期货/ETF 成交价 → 基差（贴水/升水）自动隐含，不需另加修正项。"""
    o, c = P[key]["open"], P[key]["close"]
    arr = np.full(nd, np.nan)
    with np.errstate(all="ignore"):
        arr[:nd - h] = (o[:nd - h] - c[h:]) / o[:nd - h]
    return arr


# ── 逐股 β（PIT 滚动 OLS）→ {idxkey: (codes_sorted, cpos, matrix float32[n_code, nd])} ──
def build_betas(cal, codes_needed):
    nd = len(cal)
    d2i = {d: i for i, d in enumerate(cal)}
    raw = json.loads(PRICES.read_text())
    mret = {}
    for k in ("sh000300", "sh000905", "sh000852"):
        s = np.full(nd, np.nan)
        for r in raw[k]["rows"]:
            j = d2i.get(r["date"])
            if j is not None:
                s[j] = r["close"]
        with np.errstate(all="ignore"):
            mret[k] = np.concatenate([[np.nan], s[1:] / s[:-1] - 1])
    codes = np.array(sorted(codes_needed), dtype=np.int64)
    cpos = {int(c): i for i, c in enumerate(codes)}
    mats = {k: np.full((len(codes), nd), np.nan, dtype=np.float32) for k in mret}
    t0 = time.time()
    for ki, code in enumerate(codes):
        fp = KC / f"{int(code):06d}.json"
        if not fp.exists():
            continue
        ks = json.loads(fp.read_text())
        if len(ks) < 300:
            continue
        s = np.full(nd, np.nan)
        for r0 in ks:
            j = d2i.get(r0["date"])
            if j is not None:
                s[j] = r0["close"]
        with np.errstate(all="ignore"):
            rr = np.concatenate([[np.nan], s[1:] / s[:-1] - 1])
        for idxk, m in mret.items():
            ok = np.isfinite(rr) & np.isfinite(m)
            x = np.where(ok, m, 0.0)
            y = np.where(ok, rr, 0.0)
            cs = lambda a: np.concatenate([[0.0], np.cumsum(a, dtype=np.float64)])   # noqa: E731
            cs_yx, cs_x, cs_y = cs(y * x), cs(x), cs(y)
            cs_x2, cs_n = cs(x * x), cs(ok.astype(float))
            ii = np.arange(nd)
            lo = np.maximum(0, ii - BETA_WIN)      # 窗 = [i-120, i-1]：严格 PIT，剔信号日
            hi = np.maximum(0, ii - 1)
            cnt = cs_n[hi + 1] - cs_n[lo]
            sx, sy = cs_x[hi + 1] - cs_x[lo], cs_y[hi + 1] - cs_y[lo]
            sxy, sx2 = cs_yx[hi + 1] - cs_yx[lo], cs_x2[hi + 1] - cs_x2[lo]
            with np.errstate(all="ignore"):
                cov = sxy / cnt - (sx / cnt) * (sy / cnt)
                var = sx2 / cnt - (sx / cnt) ** 2
                mats[idxk][ki] = np.where((cnt >= 60) & (var > 0), cov / var, np.nan)
        if (ki + 1) % 800 == 0:
            print(f"[beta] {ki+1}/{len(codes)} {time.time()-t0:.0f}s", flush=True)
    print(f"[beta] done {len(codes)} codes {time.time()-t0:.0f}s", flush=True)
    return {k: (codes, cpos, v) for k, v in mats.items()}


def beta_lookup(B, idxkey, codes, days):
    """向量化 β 取数（codes int 数组，days 交易日索引）。"""
    _cs, cpos, mat = B[idxkey]
    out = np.full(len(codes), np.nan)
    pos = np.array([cpos.get(int(c), -1) for c in codes])
    ok = (pos >= 0) & (days >= 0) & (days < mat.shape[1])
    out[ok] = mat[pos[ok], days[ok]]
    return out


# ── 事件集 ────────────────────────────────────────────────────────────────
def load_events():
    z = np.load(FEAT, mmap_mode="r")
    cal = z["calendar"].tolist()
    assert [k["date"] for k in json.loads(CAL_ANCHOR.read_text())] == cal, "日历不一致"
    didx = np.asarray(z["didx"]).astype(np.int64)
    eidx = np.asarray(z["eidx"]).astype(np.int64)
    code = np.asarray(z["code"]).astype(np.int64)
    flags = np.asarray(z["flags"])
    R = np.array(z["R"], dtype=np.float64)
    day_pct = np.asarray(z["day_pct"], dtype=np.float64)
    depth = np.asarray(z["F"][:, 0], dtype=np.float64)
    c25 = np.bincount(didx[(day_pct <= -0.098) & (depth <= -0.25)], minlength=len(cal))
    LINES = {
        "DEEP_NPZ": (np.where((day_pct <= -0.098) & (depth <= -0.35) & (c25[didx] >= 5))[0],
                     "深档低位v2 npz 口径（day≤−9.8%×depth60≤−35%×成簇≥5）；"
                     "npz 剔 ST/退名=幸存者样本，非台账口径", "npz"),
        "LD": (np.where((day_pct <= -0.095) & (depth <= 0.0))[0],
               "跌停接_MA60下（day≤−9.5% 且 收盘≤MA60）", "npz"),
        "PEAD": (np.where((flags & 2) != 0)[0], "预增低位池（bit1）", "npz"),
        "REV": (np.where((flags & 4) != 0)[0],
                "反转族（bit2：日≤−3% × 距60日高≤−20%）", "npz"),
    }
    return dict(cal=cal, didx=didx, eidx=eidx, code=code, R=R, depth=depth,
                day_pct=day_pct, LINES=LINES, c25=c25)


def deep_ledger():
    """深档低位v2 生产台账口径（含退市宇宙 / 全命运结算 / 逐票扫 big_kcache）。"""
    import walkforward as wf
    dep = wf.deep_events()
    sel, _batches = wf.deep_select(dep, 5, -0.35, topn=5, require_buyable=False)
    ev = dep["events"]
    k = np.where(sel)[0]
    return dict(idx=k, didx=np.array([ev[i][0] for i in k], dtype=np.int64),
                eidx=np.array([ev[i][1] for i in k], dtype=np.int64),
                code=np.array([int(ev[i][2]) for i in k], dtype=np.int64),
                R=np.array([[ev[i][4], ev[i][5], ev[i][6], ev[i][7]] for i in k]),
                depth=np.array([ev[i][3] for i in k]), n_batches=len(_batches))


# ── 主流程 ────────────────────────────────────────────────────────────────
def main():
    t0 = time.time()
    rng = np.random.default_rng(SEED)
    only = set((os.environ.get("HEDGE_ONLY") or "").split(",")) - {""}
    EV = load_events()
    cal, didx, eidx, code = EV["cal"], EV["didx"], EV["eidx"], EV["code"]
    R, depth = EV["R"], EV["depth"]
    nd = len(cal)
    P, pmeta = load_prices(cal)

    DEEP = deep_ledger()
    print(f"[deep] n={len(DEEP['idx'])} batches={DEEP['n_batches']} {time.time()-t0:.0f}s", flush=True)

    keep = np.zeros(len(code), bool)
    for _n, (_r, _no, _k) in EV["LINES"].items():
        if not only or _n in only:
            keep[_r] = True
    base_codes = code[keep] if only else code
    all_codes = set(int(c) for c in np.unique(np.concatenate([base_codes, DEEP["code"]])))
    B = build_betas(cal, all_codes)

    # 宇宙基线（当日等权，npz 行口径）
    uni = {}
    for i, h in enumerate(H):
        r = R[:, i]
        ok = np.isfinite(r)
        ue, ui = np.unique(eidx[ok], return_inverse=True)
        um = np.bincount(ui, weights=r[ok]) / np.maximum(np.bincount(ui), 1)
        uni[h] = dict(zip(ue.tolist(), um.tolist()))

    def fut_cost(h, lvl):
        return FUT_COMM * 2 + 2 * (FUT_SLIP_PT / np.maximum(lvl, 1e-9)) + FUT_MARGIN * RF * h / DAYS_YEAR

    def etf_cost(h, borrow=ETF_BORROW):
        return borrow * h / DAYS_YEAR + ETF_COMM_RT + ETF_MARGIN * RF * h / DAYS_YEAR

    TRACKS = [("IF", "sh000300"), ("IC", "sh000905"), ("IM", "sh000852")]
    ETFKEYS = {"IF": "sh510300", "IC": "sh510500", "IM": "sh512100"}
    LAMBDAS = (0.0, 0.3, 0.5, 0.7, 1.0)

    def run_block(Rb, didxb, eidxb, codeb, hmap):
        """两路对冲 × λ 矩阵。hmap: {h: 取 Rb 的列号}"""
        res = {"期货": {}, "ETF": {}, "对冲工具做空收益上下文": {}}
        for io, idxkey in TRACKS:
            fkey, dkey = io + "0", ETFKEYS[io]
            b = beta_lookup(B, idxkey, codeb, didxb)
            lvl = P[idxkey]["open"][np.clip(eidxb, 0, nd - 1)]   # 入场日指数开盘水平
            for h, col in hmap.items():
                sr = Rb[:, col]
                hrf = short_ret(P, fkey, h, nd)[eidxb]
                hre = short_ret(P, dkey, h, nd)[eidxb]
                mk = np.isfinite(hrf)
                if mk.sum():
                    res["对冲工具做空收益上下文"].setdefault(f"{io}_T+{h}", {})["做空收益均值_pp"] = round(
                        100 * float(np.nanmean(hrf[mk])), 3)
                okf = np.isfinite(sr) & np.isfinite(hrf) & np.isfinite(b)
                oke = np.isfinite(sr) & np.isfinite(hre) & np.isfinite(b)
                cf, ce = fut_cost(h, lvl), etf_cost(h)
                d = {}
                for lam in LAMBDAS:
                    d[f"λ={lam}"] = stats((sr + lam * b * hrf - lam * b * cf)[okf])
                res["期货"][f"{io}_T+{h}"] = d
                d2 = {}
                for lam in LAMBDAS:
                    d2[f"λ={lam}"] = stats((sr + lam * b * hre - lam * b * ce)[oke])
                res["ETF"][f"{dkey}_T+{h}"] = d2
        return res

    out = {"_meta": {
        "built": time.strftime("%Y-%m-%d %H:%M"), "card": "t_4a55cc92", "repo": str(ROOT),
        "horizons_npz": list(H), "horizons_ledger": list(HL),
        "股票收益口径": "npz/deep_events 内置：入场=信号日次日开盘（一字开剔），出场=T+1+h 收盘，净 0.15%",
        "对冲口径": "入场日（=T+1）开盘做空 β 倍名义市值，第 T+1+h 日收盘平仓；"
                  "用真实期货主力连续/ETF 成交价 → 基差（贴水/升水）自动隐含",
        "净收益式": "net = 股票净收益 + λ·β·(对冲工具做空收益) − λ·β·(对冲成本率)；"
                  "做空收益=(开仓价−平仓价)/开仓价；成本含佣金/滑点/保证金资金占用",
        "β估计": f"事件前 {BETA_WIN} 交易日滚动 OLS（PIT，窗=[i−120, i−1] 剔信号日），逐股 vs 300/500/1000",
        "成本_期货": {"开仓+平昨佣金(按成交额)": FUT_COMM, "平今佣金(单列备查)": FUT_COMM_TODAY,
                    "滑点": "0.2 点/边（1 个最小变动价位）", "保证金": FUT_MARGIN, "保证金资金成本": RF},
        "成本_ETF融券": {"借券年费": ETF_BORROW, "借券费敏感度": ETF_BORROW_ALT,
                      "佣金往返": ETF_COMM_RT, "保证金比例": ETF_MARGIN, "保证金资金成本": RF},
        "合约乘数": {k: v[0] for k, v in CONTRACT.items()},
        "准入": {"期货": FUT_ACCESS, "融券": MARGIN_ACCESS},
        "工具数据窗": pmeta, "n_ctrl": N_CTRL, "seed": SEED,
        "trials_base": TRIALS_BASE, "n_combos_本卡": N_COMBOS,
        "已知边界": ["期货主力连续换月接缝制造假基差跳变（长 horizon 跨月时更明显）",
                   "IM 期货仅 2022-07+；512100 ETF 2016-11+；510300/510500 ETF 2016-01+",
                   "融券可得性/券源不建模，只建模成本——真实执行可能无券",
                   "β 用历史 120 日估计（PIT），非事后真实 beta——这正是实盘能拿到的信息"]}}

    # ── 四条 npz 线 ──
    for name, (idxrows, note, kind) in EV["LINES"].items():
        if only and name not in only:
            continue
        Rb = R[idxrows]
        hmap = {h: list(H).index(h) for h in H}
        rec = {"note": note, "n": int(len(idxrows)), "kind": kind,
               "基础(不对冲)": {f"T+{h}": stats(Rb[:, hmap[h]]) for h in H}}
        rec["对冲矩阵"] = run_block(Rb, didx[idxrows], eidx[idxrows], code[idxrows], hmap)
        h = 5
        b = beta_lookup(B, "sh000905", code[idxrows], didx[idxrows])
        sr = Rb[:, hmap[h]]
        hr = short_ret(P, "IC0", h, nd)[eidx[idxrows]]
        lvl = P["sh000905"]["open"][np.clip(eidx[idxrows], 0, nd - 1)]
        ok = np.isfinite(sr) & np.isfinite(hr) & np.isfinite(b)
        s0, d0 = daily_series(sr[ok], eidx[idxrows][ok])
        s1, d1 = daily_series((sr + b * hr - b * fut_cost(h, lvl))[ok], eidx[idxrows][ok])
        rec["日度序列_IC期货λ=1_T+5"] = {"不对冲_vs宇宙": cal_stats(s0, uni[h], d0),
                                        "对冲后_vs宇宙": cal_stats(s1, uni[h], d1),
                                        "对冲后_vs零": cal_stats(s1, None, d1)}
        out[name] = rec
        print(f"[line] {name} n={rec['n']} {time.time()-t0:.0f}s", flush=True)

    # ── 深档台账口径 ──
    if not only or "DEEP" in only:
        Rec = {"note": "深档低位v2 生产台账口径（含退市宇宙 / 全命运结算），#290 同源",
               "n": int(len(DEEP["idx"])), "n_batches": DEEP["n_batches"], "kind": "ledger"}
        hL = {h: i for i, h in enumerate(HL)}
        Rec["基础(不对冲)"] = {f"T+{h}": stats(DEEP["R"][:, hL[h]]) for h in HL}
        Rec["对冲矩阵"] = run_block(DEEP["R"], DEEP["didx"], DEEP["eidx"], DEEP["code"], hL)
        h = 5
        b = beta_lookup(B, "sh000905", DEEP["code"], DEEP["didx"])
        sr = DEEP["R"][:, hL[h]]
        hr = short_ret(P, "IC0", h, nd)[DEEP["eidx"]]
        lvl = P["sh000905"]["open"][np.clip(DEEP["eidx"], 0, nd - 1)]
        ok = np.isfinite(sr) & np.isfinite(hr) & np.isfinite(b)
        s0, d0 = daily_series(sr[ok], DEEP["eidx"][ok])
        s1, d1 = daily_series((sr + b * hr - b * fut_cost(h, lvl))[ok], DEEP["eidx"][ok])
        Rec["日度序列_IC期货λ=1_T+5"] = {"不对冲_vs宇宙": cal_stats(s0, uni[h], d0),
                                        "对冲后_vs宇宙": cal_stats(s1, uni[h], d1),
                                        "对冲后_vs零": cal_stats(s1, None, d1)}
        out["DEEP_LEDGER"] = Rec
        print(f"[deep] hedged {time.time()-t0:.0f}s", flush=True)

    # ── ⑤ 位置匹配对照（全向量化重抽）──
    bucket = np.full(len(didx), -1, dtype=np.int8)
    ordd = np.lexsort((depth, didx))
    ue, ustart = np.unique(didx[ordd], return_index=True)
    uend = np.append(ustart[1:], len(didx))
    for k in range(len(ue)):
        sl = ordd[ustart[k]:uend[k]]
        m = len(sl)
        bucket[sl] = (np.arange(m) * 10 // max(m, 1)).clip(0, 9).astype(np.int8)

    ctrl = {}
    for name, (idxrows, note, kind) in EV["LINES"].items():
        if only and name not in only:
            continue
        inl = np.zeros(len(didx), bool)
        inl[idxrows] = True
        gid = didx.astype(np.int64) * 10 + np.maximum(bucket, 0).astype(np.int64)
        gid[bucket < 0] = -1
        pool_by_g = {int(g): np.where((gid == g) & (~inl))[0] for g in np.unique(gid[idxrows])}
        sg = gid[idxrows]
        order = np.argsort(sg, kind="stable")
        sg_sorted = sg[order]
        gs, gstart = np.unique(sg_sorted, return_index=True)
        gend = np.append(gstart[1:], len(sg_sorted))
        picks_all = np.full((N_CTRL, len(idxrows)), -1, dtype=np.int64)
        for gi, g in enumerate(gs):
            pool = pool_by_g.get(int(g))
            if pool is None or not len(pool):
                continue
            sl = np.arange(gstart[gi], gend[gi])
            picks_all[:, sl] = pool[rng.integers(0, len(pool), size=(N_CTRL, len(sl)))]
        hmap = {h: list(H).index(h) for h in H}
        srec = {}
        for h in H:
            hb = beta_lookup(B, "sh000905", code[idxrows], didx[idxrows])
            hsr = R[idxrows, hmap[h]]
            hhr = short_ret(P, "IC0", h, nd)[eidx[idxrows]]
            hlvl = P["sh000905"]["open"][np.clip(eidx[idxrows], 0, nd - 1)]
            hok = np.isfinite(hsr) & np.isfinite(hhr) & np.isfinite(hb)
            hnet = (hsr + hb * hhr - hb * fut_cost(h, hlvl))[hok]
            valid = picks_all >= 0
            pc = np.where(valid, picks_all, 0)
            cb = beta_lookup(B, "sh000905", code[pc].ravel(),
                             didx[pc].ravel()).reshape(pc.shape)
            csr = R[pc, hmap[h]]
            chr_ = short_ret(P, "IC0", h, nd)[eidx[pc]]
            clvl = P["sh000905"]["open"][np.clip(eidx[pc], 0, nd - 1)]
            cok = valid & np.isfinite(csr) & np.isfinite(chr_) & np.isfinite(cb)
            cnet = np.where(cok, csr + cb * chr_ - cb * fut_cost(h, clvl), np.nan)
            with np.errstate(all="ignore"):
                per_draw = np.nanmean(cnet, axis=1)
            srec[f"T+{h}"] = {
                "信号票_IC对冲净_pp": round(100 * float(np.nanmean(hnet)), 3) if hok.sum() else None,
                "对照_同位置非信号_IC对冲净_pp": round(100 * float(np.nanmean(per_draw)), 3),
                "对照_P5/P50/P95_pp": [round(100 * float(np.nanpercentile(per_draw, p)), 3)
                                    for p in (5, 50, 95)],
                "净alpha(信号−对照)_pp": round(
                    100 * (float(np.nanmean(hnet)) - float(np.nanmean(per_draw))), 3)
                if hok.sum() else None,
                "信号端有效事件": int(hok.sum()),
                "对照端有效事件中位": int(np.median(cok.sum(axis=1)))}
        ctrl[name] = srec
    out["⑤位置匹配对照_IC期货λ=1"] = ctrl
    print(f"[ctrl] {time.time()-t0:.0f}s", flush=True)

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved", OUT, OUT.stat().st_size, f"{time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
