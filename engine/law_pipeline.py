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
        stocks[Path(fp).stem] = {
            "c": c, "o": [k["open"] for k in ks], "h": [k["high"] for k in ks],
            "l": [k["low"] for k in ks], "ma60": ma60,
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
        by_date[d["date"][min(i + 1, d["n"] - 1)]].append(d["c"][i + horizon] / d["o"][i + 1] - 1 - fee)
    # 全宇宙日度均值（同窗口口径）
    uni = defaultdict(list)
    for code, d in stocks.items():
        c, o, n = d["c"], d["o"], d["n"]
        for i in range(START, n - horizon - 1):
            if o[i + 1] > 0:
                uni[d["date"][i + 1]].append(c[i + horizon] / o[i + 1] - 1 - fee)
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
            if o[i + 1] <= 0 or not detect(d, i):
                continue
            events.append((code, i))
            r = c[i + horizon] / o[i + 1] - 1 - fee
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
            ctrl.append(c[i + horizon] / o[i + 1] - 1 - fee)

    # IC 衰减曲线：同一批事件在 T+1/3/5/10/20 的表现 + NW 修正 t
    decay = {}
    for h in HORIZONS:
        rs = [stocks[code]["c"][i + h] / stocks[code]["o"][i + 1] - 1 - fee for code, i in events]
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
    对照组 = 同一只票、同在 MA60 下方的随机日（数量与信号相同）。
    返回 {h: 边际pp}。这是形态的终审口径——日历时间过不了没关系，
    过不了位置匹配对照就说明形态只是位置的代理变量。"""
    import random as _rnd
    rnd = _rnd.Random(seed)
    out = {}
    for h in horizons:
        sig, ctl = [], []
        for code, d in stocks.items():
            c, o, n, ma = d["c"], d["o"], d["n"], d["ma60"]
            days, lows = [], []
            for i in range(START, n - h - 1):
                if o[i + 1] <= 0 or ma[i] is None:
                    continue
                if c[i] <= ma[i]:
                    lows.append(i)
                    if detect(d, i):
                        days.append(i)
            for i in days:
                sig.append(c[i + h] / o[i + 1] - 1 - fee)
            for i in rnd.sample(lows, min(len(days), len(lows))):
                ctl.append(c[i + h] / o[i + 1] - 1 - fee)
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
    gates = {
        "G1_tNW≥3": abs(d5.get("t_NW") or 0) >= NW_MIN_T,
        "G2_时间分段": all(v and v["mean%"] > 0 for v in r["时间分段"].values()),
        "G3_regime≥3/4": sum(1 for v in r["regime分段"].values() if v and v["mean%"] > 0) >= max(3, len(r["regime分段"]) - 1),
        "G4_市值≥4/5": sum(1 for v in r["市值五分位"].values() if v and v["mean%"] > 0) >= len(r["市值五分位"]) - 1,
        "G5_位置匹配边际>0": bool(marg) and all(v > 0 for v in marg.values()),
        "G6_0.30%成本仍正": (r["成本压力"].get("0.30%") or {}).get("mean%", -9) > 0,
    }
    passed = all(gates.values())
    verdict = {"信号": name, "闸门": {k: "✅" if v else "❌" for k, v in gates.items()},
               "判决": "PASS 可入注册表" if passed else "REJECT",
               "位置匹配边际pp": marg, "日历时间DSR": r["DSR概率"],
               "每票每年触发": r["每票每年触发"], "全样本": r["全样本"], "随机对照": r["随机对照"]}
    return passed, verdict


# ---------- 信号注册表（新增信号往这里加，不许再写一次性脚本） ----------

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

REGISTRY = {
    "TD9买入": _td9buy,
    "TD9卖出": _td9sell,
    "大长腿_低位": lambda d, i: d["c"][i] <= d["ma60"][i] and _biglower(d, i),
    "大长腿_高位": lambda d, i: d["c"][i] > d["ma60"][i] and _biglower(d, i),
    "避雷针_低位": lambda d, i: d["c"][i] <= d["ma60"][i] and _bigupper(d, i),
    "避雷针_高位": lambda d, i: d["c"][i] > d["ma60"][i] and _bigupper(d, i),
}


def main():
    only = sys.argv[1:] or None
    submit_mode = only and only[0] == "submit"
    if submit_mode:
        only = only[1:] or None
    stocks = load_universe()
    print("stocks:", len(stocks), flush=True)
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
    dst = ROOT / f"data/law_pipeline_{tag}_20260911.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved", dst)
    sys.exit(rc)


if __name__ == "__main__":
    main()
