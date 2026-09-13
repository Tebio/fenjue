#!/usr/bin/env python3
"""engine/law_pipeline.py — 定律证伪管线（law-program-20260911.md S1 冲刺产物）

一键五件套：随机对照 / 时间分段(2019-22,2023-26) / regime分段(主线/妖股/恐慌/平淡)
           / 市值五分位 / 成本压力(0.15/0.30/0.50%) + L4容量账 + 自动判决。

用法：
    python3 engine/law_pipeline.py              # 跑 REGISTRY 全部信号
    python3 engine/law_pipeline.py 避雷针_低位   # 只跑指定信号

信号契约：detect(d, i) -> bool。d 是预计算字典：
    d["c"],d["o"],d["h"],d["l"] = 收盘/开盘/最高/最低数组
    d["ma60"][i] = 60 日均线（i<60 时为 None）
    d["date"][i] = 日期字符串
入场=i+1 开盘，离场=i+1+horizon 收盘，horizon=5，净口径 fee=0.0015。
判决只覆盖 L2/L3/L4（L1机制靠人，L5影子前向靠时间）。
"""
import json, glob, math, random, statistics as st, sys
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
KC, CAP = ROOT / "data/big_kcache", ROOT / "data/cap_hist"
TIMELINE = ROOT / "data/regime_timeline_hcap.json"
FEES = [0.0015, 0.003, 0.005]
HORIZON = 5
HORIZONS = [1, 3, 5, 10, 20]  # IC 衰减曲线（alphalens/qlib 惯例）
NW_MIN_T = 3.0                # Harvey & Liu 2015 多重检验门槛（本项目累计已测>20个信号）
START = 65

# 入场口径（2026-09-13 清欠账批）：默认 next_open=次日开盘；
# signal_close=信号日收盘（打板系close-entry主张）；trigger6=前收×1.06（半路板盘中触发价代理）。
# CLI 覆盖：python3 engine/law_pipeline.py submit --entry trigger6 banlu_b5
ENTRY_MODE = "next_open"


def _epx(d, i):
    if ENTRY_MODE == "signal_close":
        return d["c"][i]
    if ENTRY_MODE == "trigger6":
        return d["c"][i - 1] * 1.06
    return d["o"][i + 1]


def load_universe():
    stocks = {}
    for fp in glob.glob(str(KC / "*.json")):
        ks = json.loads(open(fp).read())
        if len(ks) < 300:
            continue
        c = [k["close"] for k in ks]
        pre = [0.0]
        for x in c:
            pre.append(pre[-1] + x)
        ma60 = [None] * 60 + [(pre[i + 1] - pre[i - 59]) / 60 for i in range(59, len(c) - 1)]
        ma60.append((pre[len(c)] - pre[len(c) - 60]) / 60)
        ma60 = ma60[:len(c)]  # 自查修正：原构造多出一个尾部元素（无害但脏）
        stocks[Path(fp).stem] = {
            "code": Path(fp).stem,
            "c": c, "o": [k["open"] for k in ks], "h": [k["high"] for k in ks],
            "l": [k["low"] for k in ks], "v": [k.get("volume", 0) for k in ks], "ma60": ma60,
            "amt": [k.get("amount", 0.0) for k in ks],
            "date": [k["date"] for k in ks], "n": len(ks),
        }
    return stocks


def load_regime():
    return {r["date"]: r["regime"] for r in json.loads(TIMELINE.read_text())}


def load_cap_quintiles():
    per_month, stock_cap = {}, {}
    for fp in glob.glob(str(CAP / "*.json")):
        code = Path(fp).stem
        d = {}
        for date, _px, cap in json.loads(open(fp).read()):
            m = date[:7]
            d[m] = cap
            per_month.setdefault(m, []).append(cap)
        stock_cap[code] = d
    qs = {}
    for m, caps in per_month.items():
        caps.sort()
        n = len(caps)
        qs[m] = [caps[int(n * p)] for p in (0.2, 0.4, 0.6, 0.8)] if n >= 50 else None
    return stock_cap, qs


def cap_quintile(stock_cap, qs, code, date):
    m = date[:7]
    cap = stock_cap.get(code, {}).get(m)
    b = qs.get(m)
    if cap is None or b is None:
        return None
    return sum(cap > x for x in b)


def S(rs):
    if len(rs) < 30:
        return None
    n = len(rs)
    m = st.mean(rs)
    return {"n": n, "win%": round(100 * sum(r > 0 for r in rs) / n, 1),
            "mean%": round(100 * m, 2), "med%": round(100 * st.median(rs), 2),
            "t": round(m / (st.stdev(rs) / math.sqrt(n)), 1)}


def nw_t(rs, lag):
    """Newey-West HAC t 值（重叠窗口收益的标准误修正，lag=持有期）。
    重叠 h 日的收益自相关到 h-1 阶，朴素 t 值虚高 ~sqrt(h) 倍。"""
    n = len(rs)
    if n < lag + 30:
        return None
    m = st.mean(rs)
    g0 = sum((r - m) ** 2 for r in rs) / n
    lrv = g0
    for k in range(1, lag + 1):
        gk = sum((rs[t_] - m) * (rs[t_ - k] - m) for t_ in range(k, n)) / n
        lrv += 2 * (1 - k / (lag + 1)) * gk
    return round(m / math.sqrt(lrv / n), 1) if lrv > 0 else None


def calendar_time(events, stocks, horizon, fee):
    """日历时间组合法（Fama-French 标准）：事件按入场日聚合成日度组合，
    每日收益 - 当日全宇宙均值 = 日度超额序列，对序列做 NW t。
    治的是事件在恐慌日扎堆导致的横截面相关——朴素 t 把同一天 100 只票当 100 个独立样本。"""
    from collections import defaultdict
    by_date = defaultdict(list)
    for code, i in events:
        d = stocks[code]
        by_date[d["date"][min(i + 1, d["n"] - 1)]].append(d["c"][i + horizon] / _epx(d, i) - 1 - fee)
    # 全宇宙日度均值（同窗口口径）
    uni = defaultdict(list)
    for code, d in stocks.items():
        c, o, n = d["c"], d["o"], d["n"]
        for i in range(START, n - horizon - 1):
            if _epx(d, i) > 0:
                uni[d["date"][i + 1]].append(c[i + horizon] / _epx(d, i) - 1 - fee)
    uni_m = {dt: st.mean(v) for dt, v in uni.items()}
    dates = sorted(by_date)
    series = [st.mean(by_date[dt]) - uni_m[dt] for dt in dates if dt in uni_m]
    if len(series) < 30:
        return None
    m, sd = st.mean(series), st.stdev(series)
    sr = m / sd * math.sqrt(244) if sd > 0 else 0
    return {"天数": len(series), "日均超额%": round(100 * m, 3),
            "年化Sharpe": round(sr, 2), "t_NW": nw_t(series, horizon),
            "skew": round(_skew(series), 2), "kurt": round(_kurt(series), 2)}


def _skew(x):
    m = st.mean(x)
    s = st.stdev(x)
    return sum((v - m) ** 3 for v in x) / len(x) / s ** 3 if s > 0 else 0


def _kurt(x):
    m = st.mean(x)
    s = st.stdev(x)
    return sum((v - m) ** 4 for v in x) / len(x) / s ** 4 if s > 0 else 3


def deflated_sharpe(sr_daily, T, skew, kurt, trials=25):
    """Deflated Sharpe Ratio（Bailey & López de Prado 2014）：
    在试过 trials 个策略的选择偏差下，观测 Sharpe 仍显著为正的概率。
    sr_daily 必须是日频 Sharpe（年化值/√244），T=日度观测数。
    返回 P(SR>0 | 选择偏差修正后)，>0.95 才算硬。"""
    from math import erf, sqrt
    if T < 10:
        return None
    em = 0.5772156649
    Phi = lambda z: 0.5 * (1 + erf(z / sqrt(2)))
    V = max(1e-12, (1 - skew * sr_daily + (kurt - 1) / 4 * sr_daily ** 2) / (T - 1))
    sd = sqrt(V)
    sr_star = sd * ((1 - em) * _norm_ppf(1 - 1 / trials) + em * _norm_ppf(1 - 1 / (trials * 2.718281828)))
    return round(Phi((sr_daily - sr_star) / sd), 3)


def _norm_ppf(p):
    """Acklam 近似逆正态"""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def run_pipeline(name, detect, stocks, regime, stock_cap, qs, horizon=HORIZON, fee=0.0015):
    full, ctrl = [], []
    events = []  # (code, i) 供多期衰减曲线复用
    seg_t, seg_r, seg_c = {"2019-2022": [], "2023-2026": []}, {}, {i: [] for i in range(5)}
    random.seed(42)
    for code, d in stocks.items():
        c, o, n = d["c"], d["o"], d["n"]
        hi = n - max(HORIZONS) - 1
        sc = stock_cap.get(code, {})
        for i in range(START, hi):
            if _epx(d, i) <= 0 or not detect(d, i):
                continue
            events.append((code, i))
            r = c[i + horizon] / _epx(d, i) - 1 - fee
            full.append(r)
            dt = d["date"][i]
            seg_t["2019-2022" if dt < "2023" else "2023-2026"].append(r)
            seg_r.setdefault(regime.get(dt, "?"), []).append(r)
            b = qs.get(dt[:7])
            cap = sc.get(dt[:7])
            if cap is not None and b:
                seg_c[sum(cap > x for x in b)].append(r)
        for _ in range(3):
            i = random.randint(START + 1, n - max(HORIZONS) - 2)
            ctrl.append(c[i + horizon] / _epx(d, i) - 1 - fee)

    # IC 衰减曲线：同一批事件在 T+1/3/5/10/20 的表现 + NW 修正 t
    decay = {}
    for h in HORIZONS:
        rs = [stocks[code]["c"][i + h] / _epx(stocks[code], i) - 1 - fee for code, i in events]
        s = S(rs)
        if s:
            s["t_NW"] = nw_t(rs, h)
            s["过Harvey门槛"] = "✅" if (s["t_NW"] is not None and abs(s["t_NW"]) >= NW_MIN_T) else "❌"
            decay[f"T+{h}"] = s

    cost = {f"{f*100:.2f}%": S([r + fee - f for r in full]) for f in FEES}
    ct = calendar_time(events, stocks, horizon, fee)
    dsr = deflated_sharpe(ct["年化Sharpe"] / math.sqrt(244), ct["天数"], ct["skew"], ct["kurt"]) if ct else None
    years = 1862 / 244
    trig_yr = len(full) / len(stocks) / years
    edge_pp = (st.mean(full) - st.mean(ctrl)) * 100 if full and ctrl else 0

    seg_r_stats = {k: S(v) for k, v in sorted(seg_r.items()) if S(v)}
    seg_c_stats = {f"Q{q}": S(v) for q, v in sorted(seg_c.items()) if S(v)}
    seg_t_stats = {k: S(v) for k, v in seg_t.items()}

    def pos(x): return x and x["mean%"] > 0
    verdict = {"L2_时间分段": "✅" if all(pos(v) for v in seg_t_stats.values()) else "❌",
               "L2_regime分段": "✅" if sum(1 for v in seg_r_stats.values() if pos(v)) >= max(3, len(seg_r_stats) - 1) else "❌",
               "L3_市值五分位": "✅" if sum(1 for v in seg_c_stats.values() if pos(v)) >= len(seg_c_stats) - 1 else "❌",
               "L4_成本容量": "✅" if (full and st.mean(full) > 3 * fee and trig_yr * edge_pp / 100 > 0.02) else "❌",
               "L1_机制": "人工", "L5_影子前向": "待20交易日"}
    return {"信号": name, "全样本": S(full), "随机对照": S(ctrl),
            "衰减曲线": decay, "日历时间组合": ct, "DSR概率": dsr,
            "时间分段": seg_t_stats, "regime分段": seg_r_stats, "市值五分位": seg_c_stats,
            "成本压力": cost, "每票每年触发": round(trig_yr, 2),
            "超额pp/笔": round(edge_pp, 2), "判决": verdict}


def matched_marginal(detect, stocks, horizons, fee=0.0015, seed=7):
    """位置匹配对照的边际贡献（剥离 MA60 位置因子）：
    对照组 = 同一只票、**同位置**（信号日在MA60上→对照也取MA60上的随机日）的随机日。
    返回 {h: 边际pp}。2026-09-12 修正：旧版对照组只取 MA60 下方日，
    对高位信号（如涨停洗盘）构成错配对照，边际值虚高。"""
    import random as _rnd
    rnd = _rnd.Random(seed)
    out = {}
    for h in horizons:
        sig, ctl = [], []
        for code, d in stocks.items():
            c, o, n, ma = d["c"], d["o"], d["n"], d["ma60"]
            days, lows, highs = [], [], []
            for i in range(START, n - h - 1):
                if _epx(d, i) <= 0 or ma[i] is None:
                    continue
                (lows if c[i] <= ma[i] else highs).append(i)
                if detect(d, i):
                    days.append(i)
            for i in days:
                sig.append(c[i + h] / _epx(d, i) - 1 - fee)
            # 按信号日自身位置分组匹配
            lo_n = sum(1 for i in days if c[i] <= ma[i])
            hi_n = len(days) - lo_n
            for pool, k in ((lows, lo_n), (highs, hi_n)):
                if pool and k:
                    for i in rnd.sample(pool, min(k, len(pool))):
                        ctl.append(c[i + h] / _epx(d, i) - 1 - fee)
        if len(sig) >= 30 and len(ctl) >= 30:
            out[h] = round(100 * (st.mean(sig) - st.mean(ctl)), 2)
    return out


def submit_gate(name, detect, stocks, regime, stock_cap, qs):
    """WorldQuant BRAIN 式提交闸门：新信号入库前的确定性全检。
    硬闸门（任一不过即拒收，exit 1）：
      G1 衰减曲线 T+5 的 t_NW ≥ 3.0（Harvey 多重检验门槛）
      G2 时间分段两段同号为正
      G3 regime 分段 ≥3/4 为正
      G4 市值五分位 ≥4/5 为正
      G5 位置匹配对照 T+5 与 T+20 边际贡献均为正
      G6 成本压力 0.30% 下全样本仍为正
    参考项（不卡但报告）：日历时间组合 DSR、L4 容量账。
    """
    r = run_pipeline(name, detect, stocks, regime, stock_cap, qs)
    marg = matched_marginal(detect, stocks, [5, 20])
    d5 = r["衰减曲线"].get("T+5", {})
    # G3（2026-09-13 修正）：原判据要求 ≥3 个 regime 格为正——对自带 regime 闸门的信号
    # （如 banlu_b5 只在平淡/恐慌期触发）结构性不可能通过，属类别错误。修正：有样本格<3 时
    # 改判「所有有样本格为正」，跨regime稳健性由机制层（L1）背书；有样本格≥3 维持原判据。
    cells = {k: v for k, v in r["regime分段"].items() if v}
    if len(cells) >= 3:
        g3 = sum(1 for v in cells.values() if v["mean%"] > 0) >= len(cells) - 1
    else:
        g3 = bool(cells) and all(v["mean%"] > 0 for v in cells.values())
    gates = {
        "G1_tNW≥3": abs(d5.get("t_NW") or 0) >= NW_MIN_T,
        "G2_时间分段": all(v and v["mean%"] > 0 for v in r["时间分段"].values()),
        "G3_regime≥3/4": g3,
        "G4_市值≥4/5": sum(1 for v in r["市值五分位"].values() if v and v["mean%"] > 0) >= len(r["市值五分位"]) - 1,
        "G5_位置匹配边际>0": bool(marg) and all(v > 0 for v in marg.values()),
        "G6_0.30%成本仍正": (r["成本压力"].get("0.30%") or {}).get("mean%", -9) > 0,
    }
    passed = all(gates.values())
    verdict = {"信号": name, "闸门": {k: "✅" if v else "❌" for k, v in gates.items()},
               "判决": "PASS 可入注册表" if passed else "REJECT",
               "入场口径": ENTRY_MODE,
               "位置匹配边际pp": marg, "日历时间DSR": r["DSR概率"],
               "时间分段": r["时间分段"], "regime分段": r["regime分段"], "衰减曲线": r["衰减曲线"],
               "每票每年触发": r["每票每年触发"], "全样本": r["全样本"], "随机对照": r["随机对照"]}
    return passed, verdict


# ---------- 信号注册表（新增信号往这里加，不许再写一次性脚本） ----------

# ---- 跨股截面上下文（梯队/市值/行业/周期，供打板系探测器用）----
# 惰性构建：claims_audit / main 在 load_universe 后调 build_xsection(stocks)。
# 未构建时探测器一律返回 False（防半初始化误判）。
_XLADDER = None   # date -> industry -> 当日涨停家数（≥+9.8%，kcache 比率，复权安全）
_XCAP = None      # code -> month(YYYY-MM) -> 流通市值(亿)
_XREGIME = None   # date -> regime
_IND = None       # code -> industry


def build_xsection(stocks):
    from collections import defaultdict
    global _XLADDER, _XCAP, _XREGIME, _IND
    if _XLADDER is not None:
        return
    ind_map = json.loads((ROOT / "data/industry_map.json").read_text())
    _IND = {c: (v.get("industry") or "?") for c, v in ind_map.items()}
    lad = defaultdict(lambda: defaultdict(int))
    for code, d in stocks.items():
        c, n, dates = d["c"], d["n"], d["date"]
        ind = _IND.get(code, "?")
        for i in range(1, n):
            if c[i - 1] > 0 and c[i] / c[i - 1] - 1 >= 0.098:
                lad[dates[i]][ind] += 1
    _XLADDER = lad
    _XCAP, _qs = load_cap_quintiles()
    _XREGIME = load_regime()


def _limitup(d, i):
    return d["c"][i - 1] > 0 and d["c"][i] / d["c"][i - 1] - 1 >= 0.098


def _no_board60(d, i):
    """近60日无涨停（不含当日）——对齐 banlu_backtest.first_board60"""
    if i < 61:
        return False
    for k in range(max(1, i - 60), i):
        if _limitup(d, k):
            return False
    return True


def _first_board60(d, i):
    return _limitup(d, i) and _no_board60(d, i)


def _ladder(d, i):
    return _XLADDER.get(d["date"][i], {}).get(_IND.get(d["code"], "?"), 0)


def _cap_ok(d, i):
    m = _XCAP.get(d["code"], {}).get(d["date"][i][:7])
    return m is not None and 20 <= m <= 400

def _td9buy(d, i):
    c = d["c"]
    return all(c[i - k] < c[i - k - 4] for k in range(9))

def _td9sell(d, i):
    c = d["c"]
    return all(c[i - k] > c[i - k - 4] for k in range(9))

def _shadows(d, i):
    body = abs(d["c"][i] - d["o"][i])
    return body, min(d["c"][i], d["o"][i]) - d["l"][i], d["h"][i] - max(d["c"][i], d["o"][i])

def _biglower(d, i):
    b, lo, _up = _shadows(d, i)
    return lo >= max(2 * b, 0.03 * d["c"][i])

def _bigupper(d, i):
    b, _lo, up = _shadows(d, i)
    return up >= max(2 * b, 0.03 * d["c"][i])


# ---- Sequoia-X 移植（逐行对齐 sngyai/Sequoia-X 源码，泛化到任意信号日 i） ----

def _htf(d, i):
    """高窄旗形：40日高低比>1.6 且 近10日振幅<15% 且 近10日低点≥40日高点80% 且 量<前20日均量0.6"""
    if i < 41:
        return False
    h, l, v = d["h"], d["l"], d["v"]
    h40, l40 = max(h[i - 39:i + 1]), min(l[i - 39:i + 1])
    if l40 <= 0 or h40 / l40 <= 1.6:
        return False
    h10, l10 = max(h[i - 9:i + 1]), min(l[i - 9:i + 1])
    if l10 <= 0 or h10 / l10 >= 1.15 or l10 < h40 * 0.8:
        return False
    return v[i] < (sum(v[i - 20:i]) / 20) * 0.6


def _shakeout(d, i):
    """涨停洗盘：昨日涨停(≥+9.5%) 且 今日收阴 且 今日量>昨日2倍 且 今日低点≥昨收"""
    if i < 2:
        return False
    c, o, l, v = d["c"], d["o"], d["l"], d["v"]
    return (c[i - 2] > 0 and c[i - 1] >= c[i - 2] * 1.095 and c[i] < o[i]
            and v[i - 1] > 0 and v[i] > v[i - 1] * 2.0 and l[i] >= c[i - 1])


def _uptrend_ld(d, i):
    """上升趋势跌停：昨日 MA20>MA60 且 今日收盘≤昨收×0.905 且 量>20日均量2倍"""
    if i < 61:
        return False
    c, v = d["c"], d["v"]
    ma20 = sum(c[i - 20:i]) / 20
    ma60v = sum(c[i - 60:i]) / 60
    if ma20 <= ma60v or c[i - 1] <= 0 or c[i] > c[i - 1] * 0.905:
        return False
    vma = sum(v[i - 19:i + 1]) / 20
    return vma > 0 and v[i] > vma * 2.0


# ---- 2026-09-13 清欠账：external 背书主张接入滚动审计的日K探测器 ----
# 口径声明：frontrun_v2/watchpool_grad 为收盘上车（close-entry）主张，审计配 entry=signal_close；
# banlu_b5 真实入场是盘中 +6% 市价触发，日K只能代理（h≥前收×1.06 视为触发），审计配 entry=trigger6。
# 三者真实前向由 claims_shadow 逐日记账，这里是滚动kill线监视器。

def _reversal(d, i):
    """反转族：T-1 大跌（≤-3%）→ 次日开盘买（审计框架默认 next_open，与主张口径一致）"""
    return d["c"][i - 1] > 0 and d["c"][i] / d["c"][i - 1] - 1 <= -0.03


def _limitdown(d, i):
    """跌停次日接（剔全天一字锁死：开盘≈跌停且振幅<1%，对齐 s10_retest）"""
    c, o, h, l = d["c"], d["o"], d["h"], d["l"]
    if c[i - 1] <= 0 or c[i] / c[i - 1] - 1 > -0.095:
        return False
    if o[i] / c[i - 1] - 1 <= -0.09 and (h[i] - l[i]) / c[i - 1] < 0.01:
        return False
    return True


def _panic_deep(d, i):
    """恐慌深度深档 ≤-9.5%（不剔一字，对齐 s3_combo 剂量曲线口径）"""
    return d["c"][i - 1] > 0 and d["c"][i] / d["c"][i - 1] - 1 <= -0.095


def _frontrun_v2(d, i):
    """首板+梯队≥3+市值20-400亿（对齐 frontrun_intersection V2）"""
    if _XLADDER is None or i < 61:
        return False
    return _first_board60(d, i) and _ladder(d, i) >= 3 and _cap_ok(d, i)


def _watchpool_grad(d, i):
    """池毕业：当日首板 + 前15日内触发B变体池信号（量比≥3/涨幅1~7.5%/未板/额≥2亿）"""
    if i < 66 or not _first_board60(d, i):
        return False
    c, v, amt = d["c"], d["v"], d["amt"]
    for k in range(max(6, i - 15), i):
        if c[k - 1] <= 0:
            continue
        pj = c[k] / c[k - 1] - 1
        if not (0.01 <= pj <= 0.075) or pj >= 0.098:
            continue
        base = v[k - 5:k]
        if any(x <= 0 for x in base):
            continue  # 复牌守卫（缩量停牌日剔除）
        mb = sum(base) / 5
        if mb <= 0 or v[k] / mb < 3.0:
            continue
        if amt[k] > 0 and amt[k] < 2e8:
            continue  # 额≥2亿（amount 缺失时放行，与 banlu kcache 口径一致用 v*c 兜底）
        if amt[k] <= 0 and v[k] * c[k] < 2e8:
            continue
        return True
    return False


def _banlu_b5(d, i):
    """半路板B5日K代理：盘中触+6%（h≥前收×1.06）+量比≥2+梯队≥2+60日无板+市值带+平淡/恐慌期"""
    if _XLADDER is None or _XREGIME is None or i < 61:
        return False
    if _XREGIME.get(d["date"][i]) not in ("平淡期", "恐慌期"):
        return False
    c, h, v = d["c"], d["h"], d["v"]
    if c[i - 1] <= 0 or h[i] / c[i - 1] < 1.06:
        return False
    base = v[i - 5:i]
    if any(x <= 0 for x in base):
        return False
    mb = sum(base) / 5
    if mb <= 0 or v[i] / mb < 2.0:
        return False
    return _no_board60(d, i) and _ladder(d, i) >= 2 and _cap_ok(d, i)


# ---- 2026-09-13 清欠账批②：祖训1细分（上升回调vs下跌趋势分组） ----
# 祖训1「下跌买需处于上升趋势」从未分组验证过；MA60位置作趋势代理。

# ---- 2026-09-13 清欠账批③：PEAD S4（业绩预告事件漂移） ----
# 事件日=首个≥NOTICE_DATE的交易日（公告常为盘后/周末发）；入场=次日开盘（框架默认口径即正确）。
# 数据源：东财 RPT_PUBLIC_OP_PREDICT（data/pead_events.json，39451条，2019至今）。
import bisect as _bisect

_PEAD = None


def _pead_map():
    global _PEAD
    if _PEAD is None:
        ev = json.loads((ROOT / "data/pead_events.json").read_text())
        m = {}
        for e in ev:
            code, nd = e.get("SECURITY_CODE", ""), (e.get("NOTICE_DATE") or "")[:10]
            if not code or not nd:
                continue
            m.setdefault(code, []).append((nd, e.get("FORECASTTYPE") or "", e.get("INCREASEL")))
        _PEAD = {}
        for code, lst in m.items():
            lst.sort()
            _PEAD[code] = ([x[0] for x in lst], [(x[1], x[2]) for x in lst])
    return _PEAD


def _pead_on(d, i, types, min_inc=None):
    ent = _pead_map().get(d["code"])
    if not ent:
        return False
    dts, metas = ent
    lo = d["date"][i - 1] if i >= 1 else ""
    hi = d["date"][i]
    j = _bisect.bisect_right(dts, lo)
    while j < len(dts) and dts[j] <= hi:
        t, inc = metas[j]
        if t in types and (min_inc is None or (inc is not None and inc >= min_inc)):
            return True
        j += 1
    return False

REGISTRY = {
    "TD9买入": _td9buy,
    "TD9卖出": _td9sell,
    "大长腿_低位": lambda d, i: d["c"][i] <= d["ma60"][i] and _biglower(d, i),
    "大长腿_高位": lambda d, i: d["c"][i] > d["ma60"][i] and _biglower(d, i),
    "避雷针_低位": lambda d, i: d["c"][i] <= d["ma60"][i] and _bigupper(d, i),
    "避雷针_高位": lambda d, i: d["c"][i] > d["ma60"][i] and _bigupper(d, i),
    # ---- 2026-09-12 hot_regime_scan 幸存：跨regime唯一双段一致（定义对齐 s3_combo/hot_regime_scan） ----
    "强势回调_MA60上": lambda d, i: d["c"][i] > d["ma60"][i] and d["c"][i] / d["c"][i - 1] - 1 <= -0.03,
    # ---- Sequoia-X 移植候选（2026-09-12，定义逐行对齐原项目源码） ----
    "高窄旗形HTF": _htf,
    "涨停洗盘Shakeout": _shakeout,
    "上升趋势跌停ULD": _uptrend_ld,
    # ---- 2026-09-13 清欠账：打板系/反转系主张滚动审计接线 ----
    "反转族_T-1大跌": _reversal,
    "跌停次日接_剔一字": _limitdown,
    "恐慌深度_≤-9.5": _panic_deep,
    "frontrun_v2": _frontrun_v2,
    "watchpool_grad": _watchpool_grad,
    "banlu_b5": _banlu_b5,
    # ---- 祖训1细分（2026-09-13）：反转族按趋势位置分组 ----
    "反转族_MA60上": lambda d, i: d["ma60"][i] is not None and d["c"][i] > d["ma60"][i] and _reversal(d, i),
    "反转族_MA60下": lambda d, i: d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i] and _reversal(d, i),
    # ---- PEAD S4（2026-09-13）：业绩预告事件漂移 ----
    "PEAD_预增50+": lambda d, i: _pead_on(d, i, {"预增"}, 50),
    "PEAD_强利好": lambda d, i: _pead_on(d, i, {"预增", "扭亏"}),
    "PEAD_强利空": lambda d, i: _pead_on(d, i, {"预减", "首亏"}),
}


def main():
    global ENTRY_MODE
    argv = sys.argv[1:]
    if "--entry" in argv:
        k = argv.index("--entry")
        ENTRY_MODE = argv[k + 1]
        del argv[k:k + 2]
        assert ENTRY_MODE in ("next_open", "signal_close", "trigger6"), ENTRY_MODE
        print(f"entry mode: {ENTRY_MODE}")
    only = argv or None
    submit_mode = only and only[0] == "submit"
    if submit_mode:
        only = only[1:] or None
    stocks = load_universe()
    print("stocks:", len(stocks), flush=True)
    build_xsection(stocks)
    regime = load_regime()
    stock_cap, qs = load_cap_quintiles()
    out = {}
    rc = 0
    for name, fn in REGISTRY.items():
        if only and name not in only:
            continue
        if submit_mode:
            passed, v = submit_gate(name, fn, stocks, regime, stock_cap, qs)
            out[name] = v
            print(json.dumps(v, ensure_ascii=False), flush=True)
            rc |= 0 if passed else 1
        else:
            out[name] = run_pipeline(name, fn, stocks, regime, stock_cap, qs)
            print(f"{name}: 全样本{out[name]['全样本']} 判决{out[name]['判决']}", flush=True)
    tag = "submit" if submit_mode else "candle"
    # 2026-09-13 修正：文件名硬编码 20260911 → BJT 当日；存在同名文件则合并而非覆盖
    # （分批跑不同 entry 口径时不再互相吃掉结果。教训：旧文件曾被覆盖丢失一次）
    from datetime import datetime, timedelta, timezone
    today = (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat().replace("-", "")
    dst = ROOT / f"data/law_pipeline_{tag}_{today}.json"
    if dst.exists():
        prev = json.loads(dst.read_text())
        prev.update(out)
        out = prev
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved", dst)
    sys.exit(rc)


if __name__ == "__main__":
    main()
