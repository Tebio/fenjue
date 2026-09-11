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


def run_pipeline(name, detect, stocks, regime, stock_cap, qs, horizon=HORIZON, fee=0.0015):
    full, ctrl = [], []
    seg_t, seg_r, seg_c = {"2019-2022": [], "2023-2026": []}, {}, {i: [] for i in range(5)}
    random.seed(42)
    for code, d in stocks.items():
        c, o, n = d["c"], d["o"], d["n"]
        hi = n - horizon - 1
        sc = stock_cap.get(code, {})
        for i in range(START, hi):
            if o[i + 1] <= 0 or not detect(d, i):
                continue
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
            i = random.randint(START + 1, n - horizon - 2)
            ctrl.append(c[i + horizon] / o[i + 1] - 1 - fee)

    cost = {f"{f*100:.2f}%": S([r + fee - f for r in full]) for f in FEES}
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
            "时间分段": seg_t_stats, "regime分段": seg_r_stats, "市值五分位": seg_c_stats,
            "成本压力": cost, "每票每年触发": round(trig_yr, 2),
            "超额pp/笔": round(edge_pp, 2), "判决": verdict}


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
    stocks = load_universe()
    print("stocks:", len(stocks), flush=True)
    regime = load_regime()
    stock_cap, qs = load_cap_quintiles()
    out = {}
    for name, fn in REGISTRY.items():
        if only and name not in only:
            continue
        out[name] = run_pipeline(name, fn, stocks, regime, stock_cap, qs)
        print(f"{name}: 全样本{out[name]['全样本']} 判决{out[name]['判决']}", flush=True)
    dst = ROOT / "data/law_pipeline_candle_20260911.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved", dst)


if __name__ == "__main__":
    main()
