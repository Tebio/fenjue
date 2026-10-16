#!/usr/bin/env python3
"""engine/factor_census.py — 公开因子矿普查 × regime 交叉（2026-10-15 过夜卡 t_9857628c）

使命：从 GTJA191 / WorldQuant101 / qlib Alpha158 三个公开因子库精选 24 个日频因子
+ 父卡协同过滤引擎的 GridCF OOS 打分（F25），统一实验台一次宇宙加载全向量化普查，
幸存者过 law_pipeline 六闸门终审，家族级 BH-FDR 控制（#263⑧ 认证的缺口首次实战）。

预登记（写死在代码里，先于任何数据观察，防钓鱼式挑格）：
  ① 每个因子的做多尾部方向在下表 FACTORS 里固定（A股均值回复先验：量价背离/恐慌出清/
     低波低换手/深跌位置为多头侧；追高/放量冲高/彩票波动为空头侧，只测多头侧的可执行性）。
  ② 初筛三条件全过才进六闸门：T+5 多头尾-空头尾 ≥ +0.5pp（池级）；
     多头尾日历时间 t_NW(T+5) ≥ 2.0；十分档单调步数 ≥ 6/9（沿预登记方向）。
  ③ 条件变体（因子×regime / 因子×簇≥K）：格内事件 n≥300 且格内日历 t_NW ≥ 2.0
     且（因子本体未过初筛 或 格均值 ≥ 本体均值+1pp）才送审，每因子至多 2 个变体。
  ④ trials 分母如实报：stage1 家族 = 25；DSR trials = 25 + 送审的条件变体数。
  ⑤ 终审口径：事件研究 / 日历时间 / DSR 三口径取最严 + 位置匹配对照（六闸门自带）。

跳过清单（已在自家坟墓，不重测）：MA交叉族（#231/#241）、MACD/KDJ-K/RSI6/量比/ATR%
（指标普查终审全平）、RSV（KDJ同源）、打板/封单（#257/#258）、分时类（无L2数据）。

口径：信号日收盘可知 → 次日（日历下一交易日）开盘入，一字开（跳空≥9.5%）剔，净费 0.0015；
矩阵口径的「次日」=日历下一行（停牌票当日 NaN 自然剔除）——与 law_pipeline 股票内下一根
bar 的口径略有差异，初筛用矩阵口径，六闸门终审一律走 law_pipeline 原生扫描（权威口径）。

用法：
  .venv/bin/python engine/factor_census.py knnscore   # F25 GridCF OOS 打分矩阵
  .venv/bin/python engine/factor_census.py screen     # 建矩阵+初筛+交叉诊断+落盘
  .venv/bin/python engine/factor_census.py submit     # 幸存者/条件变体过六闸门
"""
import json, math, glob, sys, time, bisect, warnings
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT = Path("/opt/data/fenjue")
KC, CAP = ROOT / "data/big_kcache", ROOT / "data/cap_hist"
BASE_NPZ = ROOT / "data/factor_census_base.npz"       # 十分档id+收益矩阵（续跑锚）
MASK_NPZ = ROOT / "data/factor_census_masks.npz"      # 送审尾部 mask（submit 用）
KNN_NPZ = ROOT / "data/similarity_gridscore.npz"      # F25 打分矩阵（knnscore 产）
OUT_JSON = ROOT / "data/factor_census_20261015.json"
from costs import FLAT_RT  # TAX-01 唯一真源 engine/costs.py（AGENTS #287）
FEE = FLAT_RT
HORIZONS = (1, 5, 20)
NW_MIN_T = 3.0
# 初筛阈值（预登记）
SCR_SPREAD_PP, SCR_TNW, SCR_MONO = 0.5, 2.0, 6
# 条件变体阈值（预登记）
COND_MIN_N, COND_TNW, COND_LIFT_PP, COND_MAX_PER_FACTOR = 300, 2.0, 1.0, 2
OOS_START = "2023-01-01"   # F25 样本外起点（学习期 2019-2022 内不打分）

# ---------------- 因子定义（预登记方向：tail=做多尾） ----------------
# 每项: (来源, 方向, 一句话机制假设)
FACTOR_META = {
    # --- 量价相关性族（GTJA006/WQ6 同源扩展）---
    "pv_corr_ov10": ("GTJA006/WQ6", "low", "开盘价与成交量10日相关：负相关=分歧出清后修复"),
    "pv_corr_hv5": ("WQ26近似", "low", "最高价与成交量5日相关：冲高放量=派发"),
    "wq12_vol_price": ("WQ101#12", "high", "sign(Δ量)×(-Δ价)：放量下跌日的反转修复"),
    "pv_corr_cv20": ("GTJA003族", "low", "收盘价与成交量20日相关：量价背离长尾"),
    # --- K线结构族（Alpha158 KBAR）---
    "clv20": ("Alpha158-KBAR", "low", "20日收盘位置均值(2c-h-l)/(h-l)：持续收弱=出清"),
    "ushadow20": ("Alpha158-KBAR", "low", "20日上影线均值：冲高回落少=稳步爬升"),
    "lshadow20": ("Alpha158-KBAR", "high", "20日下影线均值：下方承接盘存在"),
    "entity20": ("GTJA101/Alpha158", "low", "20日实体(c-o)/o均值：连阴出清修复"),
    "range20": ("Alpha158-KBAR", "low", "20日振幅(h-l)/o均值：低波动溢价"),
    # --- 波动不对称/彩票族 ---
    "std20": ("Alpha158-STD", "low", "20日收益波动率：低波（对照：八年大样本低波≈随机，事件口径未测）"),
    "dvol_ratio20": ("自建(波动不对称)", "high", "下跌日波动占比：恐慌型波动结构=出清"),
    "maxret20": ("MAX彩票/Alpha158-MAX", "low", "20日最大单日涨幅：彩票需求压价（月频已测/日频事件口径未测）"),
    "ivol20": ("特质波动", "low", "剔除市场均值后的特质波动20日：高特质波动=彩票"),
    # --- 量能/流动性/拥挤度族 ---
    "volcv20": ("自建(拥挤度)", "low", "成交量20日变异系数：爆量脉冲=拥挤"),
    "amihud20": ("Amihud非流动", "high", "|r|/成交额20日均值：非流动性溢价"),
    "turn20": ("换手率(已知梯度对照)", "low", "20日平均换手：低换手梯度（指标普查唯一活口，作已知活对照）"),
    "voltrend": ("自建(量能趋势)", "low", "5日均量/20日均量：缩量=出清"),
    # --- 路径结构族 ---
    "er20": ("Kaufman效率比", "low", "|ret20|/Σ|r|：路径混乱=震荡出清（弱先验）"),
    "cntup20": ("Alpha158-CNT", "low", "20日上涨天数占比：连跌修复"),
    "sump20": ("Alpha158-SUMP", "low", "正收益和/|收益|和：收益结构偏负=出清"),
    "gapfreq20": ("自建(跳空频率)", "low", "20日跳空>2%频率：高跳空=彩票/不稳定"),
    # --- 位置/动量对照族（已知家族，校验实验台用）---
    "dhigh60": ("Alpha158-MAX同源", "low", "距60日高：深档家族标尺（已知活，对照）"),
    "ret5": ("Alpha158-ROC5", "low", "5日反转（已知反转族，对照）"),
    "ret60": ("Alpha158-ROC60", "low", "60日反转/输家（已知，对照）"),
    # --- 引擎因子（父卡产物）---
    "knn_vote": ("相似样本引擎GridCF", "high", "历史最像样本的T+5作业均值（OOS窗口2023+）"),
}
ORDER = list(FACTOR_META)  # 固定顺序=固定编号


# ---------------- 矩阵构建 ----------------

def _roll(s, w, fn="mean"):
    r = pd.Series(s, dtype="float64").rolling(w)
    out = getattr(r, fn)()
    return out.to_numpy()


def _roll_corr(a, b, w):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.Series(a).rolling(w).corr(pd.Series(b)).to_numpy()


def _stock_factors(c, o, h, l, v, amt, cap, mkt_r_didx):
    """单票 24 个因子（KNN 另算）。全部 PIT：窗口 [i-w+1, i]。"""
    n = len(c)
    with np.errstate(all="ignore"):
        prev_c = np.concatenate([[np.nan], c[:-1]])
        r = c / prev_c - 1
        dv = np.concatenate([[np.nan], np.diff(v)])
        dc = np.concatenate([[np.nan], np.diff(c)])
        eps = 1e-12
        f = {}
        f["pv_corr_ov10"] = _roll_corr(o, v, 10)
        f["pv_corr_hv5"] = _roll_corr(h, v, 5)
        f["wq12_vol_price"] = np.sign(dv) * (-dc)
        f["pv_corr_cv20"] = _roll_corr(c, v, 20)
        f["clv20"] = _roll((2 * c - h - l) / (h - l + eps), 20)
        f["ushadow20"] = _roll((h - np.maximum(o, c)) / o, 20)
        f["lshadow20"] = _roll((np.minimum(o, c) - l) / o, 20)
        f["entity20"] = _roll((c - o) / o, 20)
        f["range20"] = _roll((h - l) / o, 20)
        f["std20"] = _roll(r, 20, "std")
        neg = np.where(r < 0, r, np.nan)
        dn = pd.Series(r < 0).rolling(20).sum().to_numpy()
        dstd = pd.Series(np.where(np.isfinite(neg), neg, 0.0)).rolling(20).std().to_numpy()
        with np.errstate(all="ignore"):
            f["dvol_ratio20"] = np.where(dn >= 5, dstd / f["std20"], np.nan)
        f["maxret20"] = _roll(r, 20, "max")
        mkt = mkt_r_didx  # 与该票对齐的市场日收益序列
        f["ivol20"] = _roll(r - mkt, 20, "std")
        vm = _roll(v, 20)
        f["volcv20"] = _roll(v, 20, "std") / (vm + eps)
        f["amihud20"] = _roll(np.abs(r) / (amt + 1.0) * 1e8, 20)  # 每亿元成交的|r|
        with np.errstate(all="ignore"):
            turn = np.where(cap > 0, v * c / (cap * 1e8), np.nan)
        f["turn20"] = _roll(turn, 20)
        f["voltrend"] = _roll(v, 5) / (vm + eps)
        sumabs = pd.Series(np.abs(r)).rolling(20).sum().to_numpy()
        ret20 = c / pd.Series(c).shift(20).to_numpy() - 1
        f["er20"] = np.abs(ret20) / (sumabs + eps)
        f["cntup20"] = _roll((r > 0).astype(float), 20)
        f["sump20"] = pd.Series(np.where(r > 0, r, 0.0)).rolling(20).sum().to_numpy() / (sumabs + eps)
        f["gapfreq20"] = _roll((np.abs(o / prev_c - 1) > 0.02).astype(float), 20)
        f["dhigh60"] = c / pd.Series(h).rolling(60).max().to_numpy() - 1
        f["ret5"] = c / pd.Series(c).shift(5).to_numpy() - 1
        f["ret60"] = ret60 = c / pd.Series(c).shift(60).to_numpy() - 1
    return f


def build_matrices():
    """单次宇宙加载 → 基础矩阵 + 因子十分档 + 前向收益，落盘 BASE_NPZ。"""
    t0 = time.time()
    calendar = [k["date"] for k in json.loads(open(KC / "600000.json").read())]
    d2i = {d: i for i, d in enumerate(calendar)}
    D = len(calendar)
    files = sorted(glob.glob(str(KC / "*.json")))
    # 预扫：定股票列数
    codes, series = [], {}
    for fp in files:
        ks = json.loads(open(fp).read())
        if len(ks) < 300:
            continue
        code = Path(fp).stem
        codes.append(code)
        series[code] = ks
    S = len(codes)
    print(f"[build] stocks={S} days={D}", flush=True)
    O = np.full((D, S), np.nan, dtype=np.float32)
    C = np.full((D, S), np.nan, dtype=np.float32)
    V = np.full((D, S), np.nan, dtype=np.float32)
    A = np.full((D, S), np.nan, dtype=np.float32)
    CAPM = np.full((D, S), np.nan, dtype=np.float32)
    FACT = {name: np.full((D, S), np.nan, dtype=np.float32) for name in ORDER if name != "knn_vote"}
    c2j = {c: j for j, c in enumerate(codes)}
    # 先填 C 算市场日收益（ivol 用）
    for j, code in enumerate(codes):
        ks = series[code]
        didx = np.array([d2i.get(k["date"], -1) for k in ks])
        ok = didx >= 0
        C[didx[ok], j] = np.array([k["close"] for k in ks], dtype=np.float32)[ok]
    with np.errstate(all="ignore"):
        prevC = np.roll(C, 1, axis=0)
        prevC[0] = np.nan
        R1D = np.where((C > 0) & (prevC > 0), C / prevC - 1, np.nan)
    mkt_r = np.nanmean(R1D, axis=1)  # 全宇宙等权日收益
    mkt_r[~np.isfinite(mkt_r)] = 0.0

    for j, code in enumerate(codes):
        ks = series[code]
        n = len(ks)
        didx = np.array([d2i.get(k["date"], -1) for k in ks])
        ok = didx >= 0
        if not ok.any():
            continue
        c = np.array([k["close"] for k in ks], dtype=np.float64)
        o = np.array([k["open"] for k in ks], dtype=np.float64)
        h = np.array([k["high"] for k in ks], dtype=np.float64)
        l = np.array([k["low"] for k in ks], dtype=np.float64)
        v = np.array([k.get("volume", 0.0) for k in ks], dtype=np.float64)
        # big_kcache 无 amount 字段（实测 2026-10-15 600000 无此键）——成交额用 v×c 代理
        amt = v * c
        cap = np.full(n, np.nan)
        capf = CAP / f"{code}.json"
        if capf.exists():
            rows = sorted(json.loads(open(capf).read()), key=lambda r: r[0])
            jj = np.searchsorted([r[0] for r in rows], [k["date"] for k in ks], side="right") - 1
            okc = jj >= 0
            cap[okc] = np.array([r[2] for r in rows])[jj[okc]]
        mkt_aligned = mkt_r[np.clip(didx, 0, D - 1)]
        fs = _stock_factors(c, o, h, l, v, amt, cap, mkt_aligned)
        di = didx[ok]
        O[di, j] = o[ok]; C[di, j] = c[ok]; V[di, j] = v[ok]; A[di, j] = amt[ok]
        CAPM[di, j] = cap[ok]
        for name, arr in fs.items():
            FACT[name][di, j] = arr[ok].astype(np.float32)
        if (j + 1) % 400 == 0:
            print(f"[build] {j+1}/{S} {time.time()-t0:.0f}s", flush=True)
        del series[code]

    # F25：GridCF OOS 打分（decmerge 步骤负责并入十分档）—— build 阶段只留空占位

    # 前向收益（矩阵口径：次日=日历下一行）
    ent = np.roll(O, -1, axis=0)
    ent[-1] = np.nan
    with np.errstate(all="ignore"):
        gap = ent / C
        valid = np.isfinite(ent) & (ent > 0) & np.isfinite(C) & (C > 0) & (gap < 1.095) & (gap > 0.905)
    RET = {}
    for hh in HORIZONS:
        ex = np.roll(C, -(1 + hh), axis=0)
        ex[-(1 + hh):] = np.nan
        with np.errstate(all="ignore"):
            rr = np.where(valid, ex / ent - 1 - FEE, np.nan).astype(np.float32)
        RET[hh] = rr

    # 十分档（每日横截面，PIT：当日收盘可知）
    DEC = {}
    for name in ORDER:
        Fm = FACT.get(name)
        if Fm is None:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            usable = np.where(valid & np.isfinite(Fm), Fm, np.nan)
            edges = np.nanpercentile(usable, np.linspace(10, 90, 9), axis=1)  # (9, D)
        with np.errstate(all="ignore"):
            dec = (usable[:, :, None] >= edges.T[:, None, :]).sum(axis=2).astype(np.uint8)
        dec[~np.isfinite(usable)] = 255
        DEC[name] = dec
        print(f"[deciles] {name} done {time.time()-t0:.0f}s", flush=True)

    np.savez(BASE_NPZ, codes=np.array(codes), calendar=np.array(calendar),
             dec_names=np.array(list(DEC)),
             **{f"dec_{k}": v for k, v in DEC.items()},
             **{f"ret_{k}": v for k, v in RET.items()})
    print(f"[build] DONE elapsed={time.time()-t0:.0f}s -> {BASE_NPZ}", flush=True)


# ---------------- F25：GridCF OOS 打分 ----------------

def knnscore():
    """用父卡 similarity_engine 的 GridCF（无regime轴=D方向，实测更强）在 2019-22 学习、
    对全部行打 T+5 预测分；矩阵口径落盘，2019-22 段置 NaN（样本内不许用）。"""
    sys.path.insert(0, str(ROOT / "engine"))
    import similarity_engine as se
    t0 = time.time()
    F, R, didx, eidx, flags, ind, day_pct, calendar = se._load_all()
    se._prep(F, didx, ind, day_pct, eidx, R)  # 板块温度二次过（F[:,9]）
    sp = bisect.bisect_left(calendar, OOS_START)
    li = np.where(didx < sp)[0]
    ti = np.arange(len(F))
    print(f"[knnscore] learn={len(li)} rows={len(ti)}", flush=True)
    pred = se._grid_predict(F, R, li, ti, use_regime=False)
    score5 = pred[:, 1].copy()
    score5[didx < sp] = np.nan  # 样本内置空
    # 映射到普查矩阵（行列锚定 BASE_NPZ 的 calendar/codes，必须先跑 build）
    if not BASE_NPZ.exists():
        print("[knnscore] BASE_NPZ 不存在，先跑 build", flush=True)
        sys.exit(1)
    zb = np.load(BASE_NPZ)
    codes, calendar_m = zb["codes"].tolist(), zb["calendar"].tolist()
    assert calendar_m == list(calendar), "日历不一致：先重跑 build"
    D, S = len(calendar_m), len(codes)
    c2j = {int(c): j for j, c in enumerate(codes)}
    M = np.full((D, S), np.nan, dtype=np.float32)
    zf = np.load(se.FEAT_NPZ)
    code_arr = zf["code"]
    js = np.array([c2j.get(int(c), -1) for c in code_arr])
    ok = (js >= 0) & np.isfinite(score5)
    M[didx[ok], js[ok]] = score5[ok].astype(np.float32)
    np.savez(KNN_NPZ, score=M)
    print(f"[knnscore] DONE coverage={ok.mean():.2%} elapsed={time.time()-t0:.0f}s", flush=True)


def decmerge():
    """把 F25 打分矩阵并入 BASE_NPZ 的十分档（build 之后跑）。"""
    z = np.load(BASE_NPZ)
    M = np.load(KNN_NPZ)["score"]
    ent_valid = np.isfinite(z["ret_1"])  # 收益有效=入场有效
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        usable = np.where(ent_valid & np.isfinite(M), M, np.nan)
        edges = np.nanpercentile(usable, np.linspace(10, 90, 9), axis=1)
    with np.errstate(all="ignore"):
        dec = (usable[:, :, None] >= edges.T[:, None, :]).sum(axis=2).astype(np.uint8)
    dec[~np.isfinite(usable)] = 255
    pack = {k: z[k] for k in z.files}
    pack["dec_knn_vote"] = dec
    names = list(z["dec_names"]) + ["knn_vote"]
    pack["dec_names"] = np.array(names)
    np.savez(BASE_NPZ, **pack)
    print(f"[decmerge] knn_vote 并入，names={len(names)}", flush=True)


# ---------------- 统计小件 ----------------

def _nw_t(x, lag):
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


def _phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _stats(rs):
    rs = np.asarray(rs, dtype=float)
    rs = rs[np.isfinite(rs)]
    if len(rs) < 30:
        return None
    return {"n": int(len(rs)), "win%": round(100 * float((rs > 0).mean()), 1),
            "mean%": round(100 * float(rs.mean()), 3)}


# ---------------- 初筛 ----------------

def screen():
    t0 = time.time()
    z = np.load(BASE_NPZ)
    codes, calendar = z["codes"].tolist(), z["calendar"].tolist()
    D, S = len(calendar), len(codes)
    R5 = z["ret_5"]
    R1 = z["ret_1"]
    R20 = z["ret_20"]
    # 宇宙日度均值（按入场日 e=d+1 聚合）
    uni = {}
    for hh, Rh in ((1, R1), (5, R5), (20, R20)):
        m = np.full(D + 1, np.nan)
        for d in range(D - 1):
            row = Rh[d]
            if np.isfinite(row).any():
                m[d + 1] = np.nanmean(row)
        uni[hh] = m
    regime_tl = {r["date"]: r["regime"] for r in json.loads((ROOT / "data/regime_timeline_hcap.json").read_text())}
    reg_of_day = np.array([regime_tl.get(d, "?") for d in calendar])

    out = {"factors": {}, "screen_rule": {
        "spread_pp>=": SCR_SPREAD_PP, "tNW_T5>=": SCR_TNW, "mono_steps>=": SCR_MONO,
        "cond": {"min_n": COND_MIN_N, "tNW>=": COND_TNW, "lift_pp>=": COND_LIFT_PP,
                 "max_per_factor": COND_MAX_PER_FACTOR},
        "trials_stage1": len(ORDER)}}
    masks = {}
    cond_candidates = []

    for name in ORDER:
        key = f"dec_{name}"
        if key not in z:
            print(f"[screen] {name}: 缺矩阵跳过", flush=True)
            continue
        dec = z[key]
        src, tail, hypo = FACTOR_META[name]
        tail_dec = 0 if tail == "low" else 9
        opp_dec = 9 if tail == "low" else 0
        tmask = dec == tail_dec
        # 十分档表（T+5 池级）
        rows, means = [], []
        for q in range(10):
            s = _stats(R5[dec == q])
            rows.append({"d": q + 1, **(s or {"n": 0})})
            means.append(s["mean%"] if s else np.nan)
        if tail == "low":
            mono = sum(1 for a, b in zip(means, means[1:]) if np.isfinite(a) and np.isfinite(b) and b < a)
            spread = means[0] - means[9]
        else:
            mono = sum(1 for a, b in zip(means, means[1:]) if np.isfinite(a) and np.isfinite(b) and b > a)
            spread = means[9] - means[0]
        # 日历时间（按入场日聚合，减宇宙均值）
        cal = {}
        for hh, Rh in ((1, R1), (5, R5), (20, R20)):
            by = defaultdict(list)
            for d in range(D - 1):
                tm = tmask[d]
                if not tm.any():
                    continue
                vals = Rh[d][tm]
                vals = vals[np.isfinite(vals)]
                if len(vals) and np.isfinite(uni[hh][d + 1]):
                    by[d + 1].append(float(vals.mean() - uni[hh][d + 1]))
            series = np.array([v[0] for k, v in sorted(by.items())])
            cal[f"T+{hh}"] = {"天数": int(len(series)),
                              "日均超额pp": round(100 * float(series.mean()), 3) if len(series) else None,
                              "t_NW": _nw_t(series, hh)}
        t5 = cal["T+5"]
        p_two = 2 * (1 - _phi(abs(t5["t_NW"]))) if t5["t_NW"] is not None else None
        passed = (np.isfinite(spread) and spread >= SCR_SPREAD_PP
                  and (t5["t_NW"] or 0) >= SCR_TNW and mono >= SCR_MONO)
        rec = {"src": src, "tail": tail, "假设": hypo,
               "deciles_T5": rows, "单调步数": mono, "尾-尾_pp": round(float(spread), 3) if np.isfinite(spread) else None,
               "日历时间": cal, "p_双侧": p_two, "初筛": "PASS" if passed else "FAIL"}
        # 交叉诊断（所有因子都跑，便宜）
        xreg, xclu = {}, {}
        ev_days = np.where(tmask.any(axis=1))[0]
        cnt_day = tmask.sum(axis=1)
        for d in ev_days:
            if d + 1 >= D:
                continue
            vals = R5[d][tmask[d]]
            vals = vals[np.isfinite(vals)]
            if len(vals) == 0 or not np.isfinite(uni[5][d + 1]):
                continue
            ex = float(vals.mean() - uni[5][d + 1])
            xreg.setdefault(reg_of_day[d], []).append(ex)
            k = cnt_day[d]
            b = "1-2" if k <= 2 else "3-9" if k <= 9 else "10-29" if k <= 29 else ">=30"
            xclu.setdefault(b, []).append(ex)
        rec["x_regime_T5"] = {k2: {"日数": len(v), "日均超额pp": round(100 * float(np.mean(v)), 3),
                                   "t_NW": _nw_t(np.array(v), 5)} for k2, v in sorted(xreg.items())}
        rec["x_cluster_T5"] = {k2: {"日数": len(v), "日均超额pp": round(100 * float(np.mean(v)), 3),
                                    "t_NW": _nw_t(np.array(v), 5)} for k2, v in sorted(xclu.items())}
        out["factors"][name] = rec
        print(f"[screen] {name}: spread={rec['尾-尾_pp']} mono={mono} tNW={t5['t_NW']} -> {rec['初筛']}", flush=True)

        if passed:
            masks[name] = tmask
        # 条件变体候选（预登记规则）
        cands = []
        base_mean = t5["日均超额pp"]
        for rg, cell in rec["x_regime_T5"].items():
            n_events_est = cell["日数"]
            if (cell["t_NW"] is not None and cell["t_NW"] >= COND_TNW
                    and (not passed or (base_mean is not None and cell["日均超额pp"] >= base_mean + COND_LIFT_PP))):
                cands.append((f"{name}@regime={rg}", cell["t_NW"], ("regime", rg)))
        for b, cell in rec["x_cluster_T5"].items():
            if b in ("10-29", ">=30") and cell["t_NW"] is not None and cell["t_NW"] >= COND_TNW \
                    and (not passed or (base_mean is not None and cell["日均超额pp"] >= base_mean + COND_LIFT_PP)):
                cands.append((f"{name}@簇{b}", cell["t_NW"], ("cluster", b)))
        cands.sort(key=lambda x: -x[1])
        for cname, tnw, spec in cands[:COND_MAX_PER_FACTOR]:
            if spec[0] == "regime":
                m = tmask & (reg_of_day[:, None] == spec[1])
            else:
                lo = {"10-29": 10, ">=30": 30}[spec[1]]
                hi = {"10-29": 29, ">=30": 10 ** 9}[spec[1]]
                m = tmask & (cnt_day[:, None] >= lo) & (cnt_day[:, None] <= hi)
            n_ev = int(m.sum())
            if n_ev >= COND_MIN_N:
                masks[cname] = m
                cond_candidates.append({"name": cname, "parent": name, "spec": spec,
                                        "t_NW_日级": tnw, "事件数": n_ev})

    # 家族 FDR（BH，stage1 家族 25 个）
    fam = [(n, r["p_双侧"]) for n, r in out["factors"].items() if r["p_双侧"] is not None]
    fam.sort(key=lambda x: x[1])
    m = len(fam)
    bh = {}
    for rank, (n, p) in enumerate(fam, 1):
        bh[n] = {"p": p, "bh_threshold": round(0.05 * rank / m, 6),
                 "bh_pass": p <= 0.05 * rank / m}
    # BH 步进：找最大 k 使 p_(k) <= 0.05k/m
    kmax = 0
    for rank, (n, p) in enumerate(fam, 1):
        if p <= 0.05 * rank / m:
            kmax = rank
    for rank, (n, p) in enumerate(fam, 1):
        bh[n]["bh_pass"] = rank <= kmax
    out["family_fdr"] = {"family_size": m, "bh_kmax": kmax, "per_factor": bh}

    out["_meta"] = {"built": time.strftime("%Y-%m-%d %H:%M"), "universe": f"{S}票×{D}日",
                    "口径": "次日开盘入/一字开剔/净0.15%/矩阵口径(日历下一行)",
                    "factors": len(ORDER), "fee": FEE}
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    np.savez(MASK_NPZ, codes=np.array(codes), calendar=np.array(calendar),
             mask_names=np.array(list(masks)), **{f"m_{k}": v for k, v in masks.items()})
    (ROOT / "data/factor_census_cond_candidates.json").write_text(
        json.dumps(cond_candidates, ensure_ascii=False, indent=1))
    print(f"[screen] DONE survivors={sum(1 for r in out['factors'].values() if r['初筛']=='PASS')} "
          f"cond={len(cond_candidates)} masks={len(masks)} elapsed={time.time()-t0:.0f}s", flush=True)


# ---------------- 六闸门终审（law_pipeline 原生） ----------------

def submit():
    sys.path.insert(0, str(ROOT / "engine"))
    import law_pipeline as lp
    z = np.load(MASK_NPZ)
    codes, calendar = z["codes"].tolist(), z["calendar"].tolist()
    names = z["mask_names"].tolist()
    only = sys.argv[2:] or names
    print(f"[submit] candidates={len(only)}", flush=True)
    stocks = lp.load_universe()
    print(f"[submit] stocks={len(stocks)}", flush=True)
    regime = lp.load_regime()
    stock_cap, qs = lp.load_cap_quintiles()
    d2i = {d: i for i, d in enumerate(calendar)}
    c2j = {c: j for j, c in enumerate(codes)}
    res = {}
    rc = 0
    for name in only:
        key = f"m_{name}"
        if key not in z:
            continue
        mask = z[key]
        def detect(d, i, mask=mask):
            j = c2j.get(d["code"])
            k = d2i.get(d["date"][i])
            return j is not None and k is not None and bool(mask[k, j])
        t0 = time.time()
        passed, v = lp.submit_gate(name, detect, stocks, regime, stock_cap, qs)
        v["耗时s"] = int(time.time() - t0)
        res[name] = v
        print(json.dumps({"name": name, "passed": passed}, ensure_ascii=False), flush=True)
        rc |= 0 if passed else 1
        # 增量落盘防丢
        dst = ROOT / "data/factor_census_gates_20261015.json"
        prev = json.loads(dst.read_text()) if dst.exists() else {}
        prev.update(res)
        dst.write_text(json.dumps(prev, ensure_ascii=False, indent=1))
    print(f"[submit] DONE rc={rc}", flush=True)
    sys.exit(rc)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "screen"
    if cmd == "knnscore":
        knnscore()
    elif cmd == "decmerge":
        decmerge()
    elif cmd == "build":
        build_matrices()
    elif cmd == "screen":
        if not BASE_NPZ.exists():
            build_matrices()
        screen()
    elif cmd == "submit":
        submit()
    elif cmd == "all":
        if not BASE_NPZ.exists():
            build_matrices()
        if not KNN_NPZ.exists():
            knnscore()
        decmerge()
        screen()
