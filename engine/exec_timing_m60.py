#!/usr/bin/env python3
"""engine/exec_timing_m60.py — m60 执行时点研究（law-program 分钟线DB落地首跑）

问题：存活主张（反转族/PANIC_DEPTH剂量）的既有口径是「i+1开盘买→离场日15:00卖」。
m60 两年数据（2024-08-26→2026-09-11，不复权）回答两件事：
  A. 入场时点：开盘/10:30/11:30/14:00/15:00/回踩限价-1%/-2%，哪个更优？
  B. 离场时点：离场日 开盘/10:30/11:30/14:00/15:00，「开盘砍最差」在 bar 级是否成立？

纪律实现：
  - 信号定义逐行对齐 s3_combo.py（chg<=-3% 反转基准 + 四档剂量）
  - 事件集跨变体强制一致（4根bar齐全、无ex-div跨度、非一字涨停开）→ 配对NW-HAC t
  - 随机对照：同票±60交易日无信号日，E0/X0同口径，报边际贡献
  - 双时段切分：≤2025-06-30 / >2025-06-30（m60 仅2年，无法再按19-22/23-26切）
  - ex-div 哨兵：m60日收盘 vs big_kcache前复权收盘比值日环比漂移>1.5% → 边界标记，
    跨度内含标记边界的交易整条剔除（B6 口径限制的工程化解）
  - 净口径 fee=0.0015
"""
import json, glob, math, random, statistics as st, time
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data/big_kcache"
M60 = ROOT / "data/m60_cache"
FEE = 0.0015
OUT = ROOT / "data/exec_timing_m60_20260912.json"
SPLIT = "2025-06-30"
SEED = 20260912

BUCKETS = [("反转全量(≤-3%)", None), ("-3~-5%", (-0.05, -0.03)), ("-5~-7%", (-0.07, -0.05)),
           ("-7~-9.5%", (-0.095, -0.07)), ("≤-9.5%", (-9.0, -0.095))]

# bar 下标 0..3 = 10:30/11:30/14:00/15:00
def e_open(b):  return b[0]["open"]
def e_b1(b):    return b[0]["close"]
def e_b2(b):    return b[1]["close"]
def e_b3(b):    return b[2]["close"]
def e_b4(b):    return b[3]["close"]
def e_dip1(b):
    lim = b[0]["open"] * 0.99
    return lim if min(x["low"] for x in b) <= lim else None
def e_dip2(b):
    lim = b[0]["open"] * 0.98
    return lim if min(x["low"] for x in b) <= lim else None

ENTRIES = {"E0开盘": e_open, "E1_1030": e_b1, "E2_1130": e_b2, "E3_1400": e_b3,
           "E4尾盘": e_b4, "E5回踩-1%": e_dip1, "E6回踩-2%": e_dip2}

EXITS = {"X0尾盘": lambda b: b[3]["close"], "X3_1400": lambda b: b[2]["close"],
         "X2_1130": lambda b: b[1]["close"], "X1_1030": lambda b: b[0]["close"],
         "X4开盘": lambda b: b[0]["open"]}


def nw_t(rs, lag=1):
    n = len(rs)
    if n < lag + 30:
        return None
    m = st.mean(rs)
    s = sum((r - m) ** 2 for r in rs) / n
    for L in range(1, lag + 1):
        cov = sum((rs[t] - m) * (rs[t - L] - m) for t in range(L, n)) / n
        s += 2 * (1 - L / (lag + 1)) * cov
    return round(m / math.sqrt(s / n), 1) if s > 0 else None


def S(rs, lag=1):
    rs = [r for r in (rs or []) if r is not None]
    if len(rs) < 30:
        return None
    m = st.mean(rs)
    return {"n": len(rs), "win%": round(100 * sum(r > 0 for r in rs) / len(rs), 1),
            "net%": round(100 * m, 2), "med%": round(100 * st.median(rs), 2), "nw_t": nw_t(rs, lag)}


def paired_diff(base, cur):
    """共同非 None 下标上的差值序列（配对）"""
    d = [c - b for b, c in zip(base, cur) if b is not None and c is not None]
    return d


def load_m60(fp):
    out = {}
    for b in json.loads(open(fp).read()):
        d = b["day"][:10]
        out.setdefault(d, []).append({"t": b["day"][11:], "open": float(b["open"]),
                                      "high": float(b["high"]), "low": float(b["low"]),
                                      "close": float(b["close"])})
    for d in out:
        out[d].sort(key=lambda x: x["t"])
    return out


def main():
    t0 = time.time()
    rng = random.Random(SEED)
    kc_files = {Path(f).stem: f for f in glob.glob(str(KC / "*.json"))}
    m60_files = {Path(f).stem: f for f in glob.glob(str(M60 / "*.json"))}
    both = sorted(set(kc_files) & set(m60_files))
    print(f"universe kc={len(kc_files)} m60={len(m60_files)} ∩={len(both)}", flush=True)

    events = {b[0]: [] for b in BUCKETS}          # (code, ed, d1, d5)
    controls = {b[0]: [] for b in BUCKETS}        # (code, ed_c, d1_c, d5_c)
    n_exdiv = n_bars = n_yizi = 0

    for code in both:
        ks = json.loads(open(kc_files[code]).read())
        if len(ks) < 300:
            continue
        m6path = m60_files[code]
        m6 = load_m60(m6path)
        if not m6:
            continue
        dates = [k["date"] for k in ks]
        c = [k["close"] for k in ks]
        o = [k["open"] for k in ks]
        # ex-div 哨兵
        ratio, flagged, prev = {}, set(), None
        for i, d in enumerate(dates):
            if d in m6 and m6[d] and c[i] > 0:
                ratio[d] = m6[d][-1]["close"] / c[i]
        for d in dates:
            if d in ratio:
                if prev is not None and abs(ratio[d] / ratio[prev] - 1) > 0.015:
                    flagged.add(d)
                prev = d
        m60_dates = sorted(m6)
        first_m60, last_m60 = m60_dates[0], m60_dates[-1]

        def ok_span(i0, i1):
            return not any(d in flagged for d in dates[i0:i1 + 1])

        def full_bars(d):
            b = m6.get(d)
            return b is not None and len(b) >= 4

        for i in range(65, len(ks) - 6):
            chg = c[i] / c[i - 1] - 1 if c[i - 1] > 0 else 0
            if chg > -0.03:
                continue
            ed, d1, d5 = dates[i + 1], dates[i + 1], dates[i + 5]
            if ed < "2024-08-26":  # 统一窗口：长停牌股1970根bar会拉伸到更早，剔除以保全宇宙口径一致
                continue
            if ed < first_m60 or d5 > last_m60:
                continue
            if not (full_bars(ed) and full_bars(d1) and full_bars(d5)):
                n_bars += 1
                continue
            be = m6[ed]
            if be[0]["open"] == be[0]["high"] == be[0]["low"] == be[0]["close"] and o[i + 1] / c[i] - 1 > 0.098:
                n_yizi += 1
                continue
            if not ok_span(i, i + 5):
                n_exdiv += 1
                continue
            for name, rng_ in BUCKETS:
                hit = chg <= -0.03 if rng_ is None else (rng_[0] <= chg < rng_[1])
                if hit:
                    events[name].append((code, ed, d1, d5))
                    # 对照：同票±60日内无信号日
                    cands = [j for j in range(max(66, i - 60), min(len(ks) - 6, i + 60))
                             if c[j - 1] > 0 and c[j] / c[j - 1] - 1 > -0.03
                             and dates[j + 1] >= "2024-08-26"
                             and full_bars(dates[j + 1]) and full_bars(dates[j + 5])
                             and ok_span(j, j + 5)]
                    if cands:
                        j = rng.choice(cands)
                        controls[name].append((code, dates[j + 1], dates[j + 1], dates[j + 5]))
                    else:
                        controls[name].append(None)
        # stock done
    for bn in events:
        print(f"bucket {bn}: n={len(events[bn])} ctl={sum(1 for x in controls[bn] if x)}", flush=True)
    print(f"dropped: exdiv={n_exdiv} bars={n_bars} yizi={n_yizi}  {time.time()-t0:.0f}s", flush=True)

    need = {c for ev in events.values() for c, *_ in ev}
    print(f"preload m60 ×{len(need)}", flush=True)
    MEM = {code: load_m60(m60_files[code]) for code in need}
    print(f"preload done {time.time()-t0:.0f}s", flush=True)

    def run(evts, ctls, horizon):
        idx = 1 if horizon == 1 else 2  # d1 / d5 在元组里的位置
        res = {e: {x: {"all": [], "early": [], "late": []} for x in EXITS} for e in ENTRIES}
        ctl_rs = []
        for k, (code, ed, d1, d5) in enumerate(evts):
            dx = (d1, d1, d5)[idx]
            m6 = MEM[code]
            be, bx = m6[ed], m6[dx]
            for en, ef in ENTRIES.items():
                pe = ef(be)
                for xn, xf in EXITS.items():
                    # None 占位保持事件对齐（E5/E6 未成交 / 价格非法）
                    r = None
                    if pe is not None and pe > 0:
                        r = xf(bx) / pe - 1 - FEE
                    res[en][xn]["all"].append(r)
                    if r is not None:
                        res[en][xn]["early" if ed <= SPLIT else "late"].append(r)
            ct = ctls[k]
            if ct:
                cc, ce, c1, c5 = ct
                m6c = MEM.get(cc) or load_m60(m60_files[cc])
                dx_c = c1 if horizon == 1 else c5
                if ce in m6c and dx_c in m6c and len(m6c[ce]) >= 4 and len(m6c[dx_c]) >= 4:
                    ctl_rs.append(EXITS["X0尾盘"](m6c[dx_c]) / e_open(m6c[ce]) - 1 - FEE)
        return res, ctl_rs

    R = {"_meta": {"window": "2024-08-26→2026-09-11", "fee": FEE, "split": SPLIT, "seed": SEED,
                   "dropped": {"exdiv": n_exdiv, "bars": n_bars, "yizi": n_yizi}}}
    for bn, _ in BUCKETS:
        evts, ctls = events[bn], controls[bn]
        if len(evts) < 100:
            continue
        R[bn] = {}
        for hz in (1, 5):
            res, ctl_rs = run(evts, ctls, hz)
            base_e = res["E0开盘"]["X0尾盘"]["all"]
            # T+1 退化格剔除：E4尾盘买=同日15:00买卖（纯费）、X4开盘卖=E0同bar（纯费）
            skip_ent = {"E4尾盘"} if hz == 1 else set()
            skip_ext = {"X4开盘"} if hz == 1 else set()
            ent = {}
            for en in ENTRIES:
                if en in skip_ent:
                    ent[en] = "degenerate(T+1同日15:00买卖)"
                    continue
                cur = res[en]["X0尾盘"]
                s = S(cur["all"], hz)
                if not s:
                    continue
                se, sl = S(cur["early"], hz), S(cur["late"], hz)
                s["early_net%"] = se["net%"] if se else None
                s["late_net%"] = sl["net%"] if sl else None
                if en != "E0开盘":
                    if en.startswith("E5") or en.startswith("E6"):
                        # 限价单口径：未成交=持币0收益。全事件配对差（诚实口径），
                        # 只在成交子集上比是恒等式（便宜1%/2%机械加成），无信息量。
                        filled = [c for c in cur["all"] if c is not None]
                        s["fill%"] = round(100 * len(filled) / len(cur["all"]), 1)
                        exp_all = [(c if c is not None else 0.0) for c in cur["all"]]
                        s["全事件期望%"] = round(100 * st.mean(exp_all), 3)
                        diff = [(c if c is not None else 0.0) - b
                                for b, c in zip(base_e, cur["all"]) if b is not None]
                        s["vsE0全事件_pp"] = round(100 * st.mean(diff), 3) if len(diff) >= 30 else None
                        s["vsE0_nw_t"] = nw_t(diff, hz)
                        s["paired_n"] = len(diff)
                    else:
                        diff = paired_diff(base_e, cur["all"])
                        s["vsE0_diff_pp"] = round(100 * st.mean(diff), 3) if len(diff) >= 30 else None
                        s["vsE0_nw_t"] = nw_t(diff, hz)
                        s["paired_n"] = len(diff)
                ent[en] = s
            ext = {}
            for xn in EXITS:
                if xn in skip_ext:
                    ext[xn] = "degenerate(T+1同bar买卖)"
                    continue
                cur = res["E0开盘"][xn]["all"]
                s = S(cur, hz)
                if not s:
                    continue
                if xn != "X0尾盘":
                    diff = paired_diff(base_e, cur)
                    s["vsX0_diff_pp"] = round(100 * st.mean(diff), 3) if len(diff) >= 30 else None
                    s["vsX0_nw_t"] = nw_t(diff, hz)
                ext[xn] = s
            base_clean = [r for r in base_e if r is not None]
            R[bn][f"T+{hz}"] = {"入场研究": ent, "离场研究": ext,
                                "随机对照_E0X0": S(ctl_rs, hz),
                                "信号边际_pp": round(100 * (st.mean(base_clean) - st.mean(ctl_rs)), 3)
                                if len(ctl_rs) >= 30 else None}
        print(f"bucket {bn} done {time.time()-t0:.0f}s", flush=True)

    OUT.write_text(json.dumps(R, ensure_ascii=False, indent=1))
    print("saved", OUT, f"{time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
