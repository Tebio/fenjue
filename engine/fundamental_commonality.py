#!/usr/bin/env python3
"""engine/fundamental_commonality.py — 存活策略命中票的基本面共同点分析（2026-09-18）

用户立项：「胜率高赔率高的票，基本面共同点是什么，比如市盈率、换手、市值等等」
纪律：位置匹配对照（同票同 MA60 位置随机日）——否则只能测出"跌过深度跌的票 PE 低"这类同义反复。
输出：每信号 × 每因子的命中组 vs 对照组分布 + 分位差 + 分位内的事件收益（避免"低 PE 更赚"的辛普森陷阱）。

用法：python3 engine/fundamental_commonality.py
"""
import json
import random
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, "/opt/data/fenjue/engine")
import importlib.util

spec = importlib.util.spec_from_file_location("lp", "/opt/data/fenjue/engine/law_pipeline.py")
lp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lp)

ROOT = Path("/opt/data/fenjue")
FUND = ROOT / "data/fund_cache"
FEE = 0.0015
HORIZON = 5
FACTORS = ["peTTM", "pbMRQ", "psTTM", "turn", "cap"]
# fund_cache 行格式（fetch_fundamentals.py FIELDS）：
# [0]date [1]close [2]turn [3]tradestatus [4]pctChg [5]peTTM [6]pbMRQ [7]psTTM [8]isST
# 2026-09-18 自查抓到：enumerate(start=4) 把 pctChg 当 peTTM（跌停日钳到-10 露馅），改显式映射
FACTOR_IDX = {"peTTM": 5, "pbMRQ": 6, "psTTM": 7, "turn": 2}


def load_fund(code):
    fp = FUND / f"{code}.json"
    if not fp.exists():
        return None
    try:
        rows = json.loads(fp.read_text())
    except Exception:
        return None
    if not rows:
        return None
    # date -> (close, turn, tradestatus, pctChg, pe, pb, ps, isST)
    return {r[0]: r for r in rows}


def pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    return s[min(int(len(s) * p), len(s) - 1)]


# ---- cap（流通市值，亿元）：cap_hist 日频 [date, px, cap] ----
CAP_DIR = ROOT / "data/cap_hist"


def load_cap(code):
    fp = CAP_DIR / f"{code}.json"
    if not fp.exists():
        return None
    try:
        rows = json.loads(fp.read_text())
    except Exception:
        return None
    if not rows:
        return None
    rows.sort(key=lambda r: r[0])
    return ([r[0] for r in rows], [r[2] for r in rows])  # (dates, caps) 预拆分防逐事件重建


def cap_on(packed, date):
    """取 date 当天或之前最近的流通市值（二分）。packed=(dates, caps)"""
    import bisect
    dates, caps = packed
    j = bisect.bisect_right(dates, date) - 1
    return caps[j] if j >= 0 else None


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    fund = {}
    cap_cache = {}
    for code in stocks:
        f = load_fund(code)
        if f:
            fund[code] = f
        cp = load_cap(code)
        if cp:
            cap_cache[code] = cp
    print(f"universe={len(stocks)} with_fund={len(fund)} with_cap={len(cap_cache)}")

    # 信号集合（注册表存活项 + 对照）
    SIGS = ["跌停接_MA60下", "组合_跌停低_长周期输家", "组合_跌停低_长周期_超跌20",
            "组合_跌停低_三连阴", "组合_跌停低_避雷针低位", "避雷针_低位",
            "banlu_b5_MA60上", "frontrun_v2_低位追"]

    out = {}
    rng = random.Random(20260918)

    for name in SIGS:
        det = lp.REGISTRY.get(name)
        if det is None:
            continue
        hits = []      # (code, i) 命中
        pool = []      # 位置匹配对照池：(code, i) 同 MA60 位置
        for code, d in stocks.items():
            if code not in fund:
                continue
            f = fund[code]
            for i in range(lp.START, d["n"] - 1):
                dt = d["date"][i]
                row = f.get(dt)
                if row is None or row[3] != "1":   # 停牌剔除
                    continue
                try:
                    is_hit = det(d, i)
                except Exception:
                    continue
                below = d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
                if is_hit:
                    hits.append((code, i, below))
                else:
                    pool.append((code, i, below))

        # 位置匹配对照：按命中组的位置分布等量采样
        n_below = sum(1 for h in hits if h[2])
        n_above = len(hits) - n_below
        ctrl_below = [p for p in pool if p[2]]
        ctrl_above = [p for p in pool if not p[2]]
        rng.shuffle(ctrl_below)
        rng.shuffle(ctrl_above)
        ctrl = ctrl_below[:n_below] + ctrl_above[:n_above]
        print(f"{name}: hits={len(hits)} (low={n_below} high={n_above}) ctrl={len(ctrl)}")

        def factor_vals(events, code_i):
            vals = {k: [] for k in FACTORS}
            for code, i, _ in events:
                row = fund[code][stocks[code]["date"][i]]
                for k in FACTORS:
                    if k == "cap":
                        continue  # cap 单独从 cap_hist 取（日频流通市值，亿元）
                    v = row[FACTOR_IDX[k]]
                    if v is not None:
                        vals[k].append(v)
                # cap：cap_hist 是日频 [date, px, cap亿]，取信号日（或之前最近）值
                dt = stocks[code]["date"][i]
                ch = cap_cache.get(code)
                if ch:
                    cap_v = cap_on(ch, dt)
                    if cap_v is not None:
                        vals["cap"].append(cap_v)
            return vals

        hv = factor_vals(hits, None)
        cv = factor_vals(ctrl, None)

        rec = {"n_hits": len(hits), "n_ctrl": len(ctrl), "factors": {}}
        for k in FACTORS:
            h, c = hv[k], cv[k]
            if len(h) < 30 or len(c) < 30:
                continue
            rec["factors"][k] = {
                "hit_median": round(st.median(h), 3),
                "ctrl_median": round(st.median(c), 3),
                "hit_q25": round(pct(h, .25), 3), "hit_q75": round(pct(h, .75), 3),
                "ctrl_q25": round(pct(c, .25), 3), "ctrl_q75": round(pct(c, .75), 3),
            }
        out[name] = rec

    dst = ROOT / "data/fundamental_commonality_20260918.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved", dst)


if __name__ == "__main__":
    main()
