#!/usr/bin/env python3
"""engine/downtrend_raid.py — 下跌中继突袭涨停/大涨 事件研究（2026-10-15 立项，kanban t_f32e9abf）

用户原话：「测一下下跌中继来个涨停或者大涨的」

问题：下跌趋势中段（不是底部出清）的票突然涨停/大涨（≥7%），
     ①之后 T+1/2/3/5/10/20 全 horizon 胜率/均值/赔率
     ②与「底部出清后大涨」的判别边界
     ③有没有事前可识别的分层（板块联动/梯队/量能/深度）

口径（默认，与 law_pipeline 对齐）：
  入场 = 次 bar 开盘（next_open），净扣 0.15% 单边往返口径（fee=0.0015）；
  一字买不进剔除：次日开盘 ≥ 信号日收盘×1.098×0.995 视为封死买不到。
  另报 signal_close 口径（信号日涨停价成交=打板纸面，仅作上界参考）。

内存纪律（2026-10-15 实锤）：容器 cgroup 上限 4GB，law_pipeline.load_universe()
+ build_xsection() 在 5 个并行 worker 同驻时会 OOM（实测 exit=137）。
本模块用 array('f') 压缩存价量 + 全局交易日历索引，全宇宙驻留 <500MB。
"""
import glob
import json
import math
import random
import statistics as st
import sys
from array import array
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data/big_kcache"
CAPD = ROOT / "data/cap_hist"
FEE = 0.0015
START = 65
HORIZONS = [1, 2, 3, 5, 10, 20]

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp  # noqa: E402  （复用 S/nw_t/calendar_time/deflated_sharpe/capacity_sim）


# ---------------------------------------------------------------- 紧凑宇宙

def load_compact(limit=None):
    """返回 (stocks, cal)。stocks 的 dict 结构与 law_pipeline.load_universe() 兼容
    （c/o/h/l/v/date/n/ma60/code），但价量用 array('f') 压缩、日期走全局日历索引。"""
    import resource
    cal = [x["date"] for x in json.loads((ROOT / "data/index_sh000001.json").read_text())]
    cidx = {d: i for i, d in enumerate(cal)}
    stocks = {}
    files = sorted(KC.glob("*.json"))
    if limit:
        files = files[:limit]
    for fp in files:
        try:
            ks = json.loads(fp.read_text())
        except Exception:
            continue
        if len(ks) < 300:
            continue
        n = len(ks)
        c = array('f'); o = array('f'); h = array('f'); l = array('f'); v = array('f'); di = array('i')
        for k in ks:
            j = cidx.get(k["date"])
            if j is None:
                continue
            c.append(k["close"]); o.append(k["open"]); h.append(k["high"])
            l.append(k["low"]); v.append(k.get("volume", 0) or 0); di.append(j)
        del ks
        n = len(c)
        if n < 300:
            continue
        # MA60（与 law_pipeline 同式：ma60[i] = mean(c[i-59:i+1])），前 59 位 None
        ma = [0.0] * 60  # 前 59 位占位 0（不参与判定，i>=65 才用）
        s = sum(c[:60])
        ma.append(s / 60)
        for i in range(60, n):
            s += c[i] - c[i - 60]
            ma.append(s / 60)
        stocks[fp.stem] = {"code": fp.stem, "c": c, "o": o, "h": h, "l": l, "v": v,
                           "ma60": ma[:n], "amt": [0.0] * n,
                           "di": di, "date": [cal[j] for j in di], "n": n}
    return stocks, cal


def build_xs(stocks, cal):
    """自制横截面（避开 law_pipeline.build_xsection 的 _XFUND 内存黑洞，实测 >1GB）：
    date -> 涨停家数 / 跌停家数 / industry -> 涨停家数（梯队）/ regime / 段龄。"""
    ind = json.loads((ROOT / "data/industry_map.json").read_text())
    code2ind = {str(k).zfill(6): (v.get("industry") or "?") for k, v in ind.items()}
    del ind
    lud = defaultdict(int); ldd = defaultdict(int)
    lad = defaultdict(lambda: defaultdict(int))
    for code, d in stocks.items():
        c, di = d["c"], d["di"]
        i_ = code2ind.get(code, "?")
        n = len(c)
        for j in range(1, n):
            if c[j - 1] <= 0:
                continue
            r = c[j] / c[j - 1] - 1
            if r >= 0.098:
                lud[cal[di[j]]] += 1
                lad[cal[di[j]]][i_] += 1
            elif r <= -0.095:
                ldd[cal[di[j]]] += 1
    tl = json.loads((ROOT / "data/regime_timeline_hcap.json").read_text())
    reg = {}; age = {}
    cur, a = None, 0
    for x in tl:
        if x["regime"] != cur:
            cur, a = x["regime"], 1
        else:
            a += 1
        reg[x["date"]] = cur
        age[x["date"]] = a
    return {"code2ind": code2ind, "lud": lud, "ldd": ldd, "lad": lad, "regime": reg, "age": age}


def load_cap_month(stocks):
    """月度 PIT 市值：每月键 'YYYY-MM-01' 存「上月末流通市值」，完全在过去。
    返回 (packed, qs)：packed=code->(keys, vals)；qs=月->四分位边界（上月全市场横截面）。"""
    packed = {}
    per_month = defaultdict(list)
    for code in stocks:
        fp = CAPD / f"{code}.json"
        if not fp.exists():
            continue
        try:
            rows = sorted(json.loads(fp.read_text()), key=lambda r: r[0])
        except Exception:
            continue
        keys, vals = [], []
        cur_m = None; last_cap = None
        for dt, _px, cap in rows:
            m = dt[:7]
            if cur_m is None:
                cur_m = m
            if m != cur_m:
                # 上月最后一个交易日的市值 → 记在「本月月初」键上（PIT 安全）
                keys.append(cur_m + "-01"); vals.append(last_cap)
                cur_m = m
            last_cap = cap
        if cur_m:
            keys.append(cur_m + "-01"); vals.append(last_cap)
        if keys:
            packed[code] = (keys, vals)
            for k, val in zip(keys, vals):
                per_month[k].append(val)
    qs = {}
    for k, v in per_month.items():
        if len(v) >= 50:
            v = sorted(v)
            n = len(v)
            qs[k] = [v[int(n * p)] for p in (0.2, 0.4, 0.6, 0.8)]
    return packed, qs


def cap_at(packed, code, date):
    p = packed.get(code)
    if not p:
        return None
    keys, vals = p
    j = bisect_right(keys, date) - 1
    return vals[j] if j >= 0 else None


# ---------------------------------------------------------------- 探测器（与 law_pipeline REGISTRY 同定义）

def downtrend_ctx(d, i, drop20=0.10, look=20):
    """下跌中继语境（信号日 i 收盘可判，无未来函数）：
    ① 前 20 交易日累计跌幅 ≤ -drop20（用 c[i]/c[i-20]-1，含当日大涨也照样算）
    ② MA60 下行（ma60[i] < ma60[i-5]）
    ③ 收盘仍在 MA60 下方（中段，不是已反转站上）"""
    if i < 65:
        return False
    c, ma = d["c"], d["ma60"]
    if c[i - look] <= 0 or ma[i] is None or ma[i - 5] is None:
        return False
    if c[i] / c[i - look] - 1 > -drop20:
        return False
    if not (ma[i] < ma[i - 5]):
        return False
    return c[i] <= ma[i]


def raid_limitup(d, i):      # 下跌中继 × 当日涨停
    return downtrend_ctx(d, i) and d["c"][i - 1] > 0 and d["c"][i] / d["c"][i - 1] - 1 >= 0.098


def raid_big7(d, i):         # 下跌中继 × 当日 ≥7% 大阳
    return downtrend_ctx(d, i) and d["c"][i - 1] > 0 and d["c"][i] / d["c"][i - 1] - 1 >= 0.07


def raid_big5(d, i):
    return downtrend_ctx(d, i) and d["c"][i - 1] > 0 and d["c"][i] / d["c"][i - 1] - 1 >= 0.05


def bottom_flush_big7(d, i):
    """边界对照：底部出清后大涨 —— 深跌到位（收≤MA60×0.65）且 MA60 下行 × 当日 ≥7%。
    与中继的区别=「已经砸出深度」而不是「刚跌了一段」。"""
    if i < 65:
        return False
    c, ma = d["c"], d["ma60"]
    if ma[i] is None or ma[i] <= 0 or c[i - 1] <= 0:
        return False
    if not (ma[i] < ma[i - 5]):
        return False
    if c[i - 1] > ma[i] * 0.65:      # 用信号日前一日判定深度（当日已大涨会抬高）
        return False
    return c[i] / c[i - 1] - 1 >= 0.07


# ---------------------------------------------------------------- 事件抽取

def collect(stocks, xs, det, exclude_sealed=True):
    """返回事件列表 [{code, i, date, ...}]，入场=次 bar 开盘。
    exclude_sealed：次日开盘 ≥ 信号日收盘×1.098×0.995（一字涨停封死买不到）剔除。"""
    ev = []
    for code, d in stocks.items():
        c, o, n, di = d["c"], d["o"], d["n"], d["di"]
        for i in range(START, n - max(HORIZONS) - 1):
            if c[i - 1] <= 0 or o[i + 1] <= 0:
                continue
            if not det(d, i):
                continue
            if exclude_sealed and o[i + 1] >= c[i] * 1.098 * 0.995:
                continue
            dt = d["date"][i]
            ev.append({"code": code, "i": i, "date": dt, "ep": o[i + 1],
                       "cp": c[i], "di": di[i]})
    return ev


def fwd(d, i, h, entry="next_open"):
    """前向净收益（含费）。口径**逐字对齐 law_pipeline.run_pipeline**：
    entry=next_open → o[i+1]；离场 = c[i+h]（h=1 即入场日收盘，符合本仓库 T+N 惯例）。
    entry=signal_close → 信号日收盘买（打板纸面口径，仅作上界参考）。"""
    c = d["c"]
    ep = d["o"][i + 1] if entry == "next_open" else c[i]
    if ep <= 0 or i + h >= d["n"]:
        return None
    return c[i + h] / ep - 1 - FEE


def stats(rs):
    if not rs:
        return None
    if len(rs) < 30:
        return {"n": len(rs), "win%": round(100 * sum(r > 0 for r in rs) / len(rs), 1),
                "mean%": round(100 * st.mean(rs), 2), "t": None, "样本不足": True}
    return lp.S(rs)


def odds(rs):
    w = [r for r in rs if r > 0]; l = [r for r in rs if r <= 0]
    if not w or not l:
        return None
    return round(st.mean(w) / abs(st.mean(l)), 2)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "probe"
    print("loading compact universe…", flush=True)
    stocks, cal = load_compact()
    print("stocks:", len(stocks), "cal:", len(cal), flush=True)
    xs = build_xs(stocks, cal)
    print("xs done: 涨停日数=%d 跌停日数=%d" % (len(xs["lud"]), len(xs["ldd"])), flush=True)

    DETS = {"下跌中继_涨停": raid_limitup, "下跌中继_大涨7": raid_big7,
            "下跌中继_大涨5": raid_big5, "底部出清后大涨7": bottom_flush_big7}
    out = {}
    for name, det in DETS.items():
        ev = collect(stocks, xs, det)
        o = {"n_events": len(ev), "years": round(len(cal) / 244.0, 2),
             "每票每年": round(len(ev) / len(stocks) / (len(cal) / 244.0), 3)}
        for h in HORIZONS:
            rs = [r for r in (fwd(stocks[e["code"]], e["i"], h) for e in ev) if r is not None]
            s = stats(rs)
            if s:
                s["odds"] = odds(rs)
                o[f"T+{h}"] = s
        out[name] = o
        print("=" * 70)
        print(name, "n=%d" % len(ev), flush=True)
        for h in HORIZONS:
            s = o.get(f"T+{h}")
            if s:
                print("   T+%-3d n=%-6d win=%5.1f%%  mean=%+6.2f%%  t=%s  odds=%s" % (
                    h, s["n"], s["win%"], s["mean%"], s.get("t"), s.get("odds")), flush=True)
    dst = ROOT / "data/downtrend_raid_probe.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved", dst)


if __name__ == "__main__":
    main()
