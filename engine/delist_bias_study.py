#!/usr/bin/env python3
"""engine/delist_bias_study.py — 退市股幸存者偏差量化（#270 A1，卡 t_f680fa88）

背景：big_kcache 曾缺退市股（#265⑤）。2026-09-12 delisted_codes.json 双锚点补齐 194 只
（186 只有效入宇宙），baostock query_stock_basic(status=0) 权威清单复核：主板 outDate>=2019
共 195 只，生产宇宙仍缺 7 只（双锚法漏的长期停牌股）+2 只 2026-10-19 待退市（窗口内仍存活）。
本脚本把 7 只隔离缓存（data/delist_kcache_iso/，不进生产 kcache）并入，重跑两条基线。

三宇宙对比：
  U_surv = 纯存活者（剔除全部退市/迁板 201 只）—— 修复前口径
  U_cur  = 生产现状 big_kcache 3377 只（已含 186 只退市）
  U_full = U_cur + 隔离缓存 7 只 —— 全量口径
两口径：
  P1 = law_pipeline._collect_sigs 原口径（i in [61, n-22)，退市股末 22 根 bar 信号被截断）
  P2 = 全命运口径（i 到 n-2，持有窗越界按最后收盘结算，对齐转债线「退市按最后收盘结算」）
探测器逐字抄生产定义：
  跌停接 = law_pipeline._limitdown（剔全天一字锁死）；入场次日开盘，一字跌停（开≤前收×0.905）剔；
  深档低位v2 = dashboard_build.deep_low_scan（簇门=深档件[≤-9.5% 且收<MA60 且收≤MA60×0.75]≥5，
               出手票=收≤MA60×0.65 按深度升序前5）。
费用 0.15% 单程扣（与 law_pipeline 事件研究一致）。历史口径无 ST 过滤（与已发布基线一致）。
"""
import json
import math
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
KC, ISO = ROOT / "data/big_kcache", ROOT / "data/delist_kcache_iso"
OUT = ROOT / "data/delist_bias_study_20261015.json"
from costs import FLAT_RT  # TAX-01 唯一真源 engine/costs.py（AGENTS #287）
FEE = FLAT_RT
MIN_BARS = 300          # law_pipeline.load_universe 的 ≥300 过滤（主口径）
START = 65              # law_pipeline START
P1_TAIL = 22            # _collect_sigs 的 n-22 截断

DEAD194 = set(json.loads((ROOT / "data/delisted_codes.json").read_text())["codes"])
ISO_CODES = {p.stem for p in ISO.glob("*.json")}
DEAD = DEAD194 | ISO_CODES   # 201 只


def ma60_of(c):
    """逐字复刻 law_pipeline.load_universe 的 ma60 构造（前 60 根为 None）。"""
    pre = [0.0]
    for x in c:
        pre.append(pre[-1] + x)
    ma = [None] * 60 + [(pre[i + 1] - pre[i - 59]) / 60 for i in range(59, len(c) - 1)]
    ma.append((pre[len(c)] - pre[len(c) - 60]) / 60)
    return ma[:len(c)]


def S(rs):
    if not rs:
        return None
    n = len(rs)
    m = st.mean(rs)
    return {"n": n, "win%": round(100 * sum(r > 0 for r in rs) / n, 2),
            "mean%": round(100 * m, 3),
            "med%": round(100 * st.median(rs), 3),
            "t": round(m / (st.stdev(rs) / math.sqrt(n)), 2) if n > 1 and st.stdev(rs) > 0 else None}


def main():
    # ---- 事件容器 ----
    # 跌停接：每条 (tag, date, low60, {h: ret})
    ev_ld = []
    # 深档件（簇门计数+出手候选）：每日 [(depth, tag, low35, {h: ret})]
    deep_by_day = defaultdict(list)
    # 全市场基线：tag -> h -> [sum, n, wins]
    base = defaultdict(lambda: defaultdict(lambda: [0.0, 0, 0]))
    n_files = {"surv": 0, "dead_cur": 0, "dead_new": 0}

    sources = [(KC, None), (ISO, "dead_new")]
    for kcdir, forced_tag in sources:
        for fp in sorted(kcdir.glob("*.json")):
            code = fp.stem
            tag = forced_tag or ("dead_cur" if code in DEAD194 else "surv")
            ks = json.loads(fp.read_text())
            if len(ks) < MIN_BARS:
                continue
            n_files[tag] += 1
            c = [k["close"] for k in ks]
            o = [k["open"] for k in ks]
            h_ = [k["high"] for k in ks]
            l_ = [k["low"] for k in ks]
            dts = [k["date"] for k in ks]
            n = len(c)
            ma = ma60_of(c)

            def ret(i, hh):
                """次日开盘入场；P2 结算：出场越界按最后收盘。一字跌停剔在调用处。"""
                e = o[i + 1]
                j = i + 1 + hh
                return (c[j] if j < n else c[n - 1]) / e - 1 - FEE

            for i in range(START, n - 1):
                if c[i - 1] <= 0 or c[i] <= 0:
                    continue
                p1_ok = i < n - P1_TAIL
                buyable = o[i + 1] > 0 and o[i + 1] > c[i] * 0.905  # 次日开盘一字跌停＝买不到
                # ---- 全市场基线（T+1/T+5，需次日开盘存在）----
                if o[i + 1] > 0:
                    for hh in (1, 5):
                        r = ret(i, hh)
                        b = base[(tag, "P1" if p1_ok else "P2only")][hh]
                        b[0] += r; b[1] += 1; b[2] += r > 0
                # ---- 跌停接（生产 _limitdown 逐字；信号收集即套入场过滤，对齐 _collect_sigs）----
                if c[i] / c[i - 1] - 1 <= -0.095:
                    one_word = (o[i] / c[i - 1] - 1 <= -0.09
                                and (h_[i] - l_[i]) / c[i - 1] < 0.01)
                    if not one_word and buyable:
                        ev_ld.append((tag, dts[i],
                                      ma[i] is not None and c[i] <= ma[i],
                                      p1_ok, {1: ret(i, 1), 5: ret(i, 5)}))
                    # ---- 深档件（簇门计数=信号日裸条件，deep_low_scan 逐字，不套入场过滤）----
                    if ma[i] is not None and c[i] < ma[i] and c[i] <= ma[i] * 0.75:
                        depth = c[i] / ma[i] - 1
                        deep_by_day[dts[i]].append(
                            (depth, tag, depth <= -0.35, p1_ok, buyable,
                             {5: ret(i, 5), 10: ret(i, 10)} if buyable else None))

    print(f"宇宙文件数(≥{MIN_BARS} bars): {n_files}", flush=True)

    TAGSETS = {"U_surv": {"surv"}, "U_cur": {"surv", "dead_cur"},
               "U_full": {"surv", "dead_cur", "dead_new"}}
    out = {"meta": {"min_bars": MIN_BARS, "fee": FEE, "files": n_files,
                    "dead194": len(DEAD194), "iso_new": sorted(ISO_CODES)},
           "limitdown": {}, "limitdown_ma60low": {}, "deep_low_v2": {}, "baseline": {}}

    for uname, tags in TAGSETS.items():
        # 跌停接（全体 + MA60下子线），P1/P2
        for key, lowonly in (("limitdown", False), ("limitdown_ma60low", True)):
            for p in ("P1", "P2"):
                for hh in (1, 5):
                    rs = [e[4][hh] for e in ev_ld
                          if e[0] in tags and (p == "P2" or e[3])
                          and (not lowonly or e[2])]
                    out[key].setdefault(uname, {})[f"{p}_T{hh}"] = S(rs)
        # 深档低位v2：簇门=宇宙内当日深档件裸计数≥5；出手票=≤-35% 且可买，深度升序前5（另报不截断变体）
        for p in ("P1", "P2"):
            picks, picks_all, ndays = [], [], 0
            for dt, evs in deep_by_day.items():
                evs_u = [e for e in evs if e[1] in tags and (p == "P2" or e[3])]
                if len(evs_u) < 5:
                    continue                      # 簇门
                ndays += 1
                hand = sorted((e for e in evs_u if e[2] and e[4]), key=lambda e: e[0])
                picks.extend(hand[:5])
                picks_all.extend(hand)
            for hh in (5, 10):
                out["deep_low_v2"].setdefault(uname, {})[f"{p}_T{hh}"] = S([e[5][hh] for e in picks])
                out["deep_low_v2"][uname][f"{p}_T{hh}_notop5"] = S([e[5][hh] for e in picks_all])
            out["deep_low_v2"][uname][f"{p}_cluster_days"] = ndays
            if uname == "U_full":
                for p2 in ("surv", "dead_cur", "dead_new"):
                    sub = [e for e in picks if e[1] == p2]
                    out["deep_low_v2"].setdefault("picks_by_tag", {})[f"{p}_{p2}"] = {
                        "n": len(sub),
                        "T5": S([e[5][5] for e in sub]), "T10": S([e[5][10] for e in sub])}
        # 全市场基线
        for p in ("P1", "P2"):
            for hh in (1, 5):
                s = n_ = w = 0
                for t in tags:
                    for pp in (("P1",) if p == "P1" else ("P1", "P2only")):
                        b = base[(t, pp)][hh]
                        s += b[0]; n_ += b[1]; w += b[2]
                out["baseline"].setdefault(uname, {})[f"{p}_T{hh}"] = (
                    {"n": n_, "win%": round(100 * w / n_, 2), "mean%": round(100 * s / n_, 4)}
                    if n_ else None)

    # 退市股事件单独解剖（偏差来源）
    dead_ev = [e for e in ev_ld if e[0] != "surv"]
    out["dead_stock_anatomy"] = {
        "limitdown_events_dead": len(dead_ev),
        "dead_P2_T5": S([e[4][5] for e in dead_ev]),
        "dead_P1_T5": S([e[4][5] for e in dead_ev if e[3]]),
        "surv_P2_T5": S([e[4][5] for e in ev_ld if e[0] == "surv"]),
    }

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
