#!/usr/bin/env python3
"""pick_ranker.py — 恐慌成簇日选票排名器（2026-09-19 用户令：研究要能用来选票）。

问题：成簇日一堆票命中，买哪只次日涨得更多？
方法：
  1. 每日命中集合内按单特征排序，头名 vs 当日等权均值（选股超额）+ 秩相关 IC
  2. 合成评分（深度+超跌+连跌+小市值+缩量 z 分和）排名
  3. 容量模拟实证：槽位按排名从上往下吃 vs 随机吃（capacity_sim 的选票规则替换）
PIT 纪律：排名特征全部信号日收盘可知（次日缺口不进特征）。
"""
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent
FEE = 0.0015
BASE = "跌停接_MA60下"


def feats(d, i, code, fund, capm):
    c, o, v, ma = d["c"], d["o"], d["v"], d["ma60"]
    hi60 = max(c[max(0, i - 60):i + 1])
    n_down = 0
    j = i
    while j > 0 and c[j] < c[j - 1]:
        n_down += 1
        j -= 1
    fu = fund.get(code, {}).get(d["date"][i])
    return {
        "深度": -(c[i] / ma[i] - 1),          # 越深越好（取负后越大越好）
        "超跌60": -(c[i] / hi60 - 1) if hi60 > 0 else 0,
        "连跌": n_down,
        "小市值": -(lp.cap_at_date(capm, code, d["date"][i]) or 1e9),  # 越小越好（PIT 日频）
        "缩量": -lp._volratio(d, i),           # 越缩越好
        "低PE": -(fu[0]) if fu and fu[0] is not None else 0,
    }


def fwd(d, i, h):
    ei = i + 1
    if ei + h >= d["n"] or d["o"][ei] <= 0 or d["o"][ei] <= d["c"][i] * 0.905:
        return None
    return d["c"][ei + h] / d["o"][ei] - 1 - FEE


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    fund, capm = lp._XFUND, lp._XCAP

    det = lp.REGISTRY[BASE]
    days = defaultdict(list)   # date -> [(code, i, feats)]
    for code, d in stocks.items():
        for i in range(61, d["n"] - 22):
            try:
                if det(d, i):
                    days[d["date"][i]].append((code, i, feats(d, i, code, fund, capm)))
            except Exception:
                pass
    cluster = {dt: evs for dt, evs in days.items() if len(evs) >= 3}
    print(f"成簇日 {len(cluster)}，事件总数 {sum(len(v) for v in cluster.values())}", flush=True)

    FEATS = ["深度", "超跌60", "连跌", "小市值", "缩量", "低PE"]
    # 1) 单特征头名超额 + IC
    for h, hname in ((1, "T+1"), (5, "T+5")):
        print(f"\n== {hname} 单特征排名效果（头名超额 vs 当日等权；IC=秩相关）==")
        for f in FEATS:
            top_excess, ics = [], []
            for dt, evs in cluster.items():
                scored = []
                for code, i, ft in evs:
                    r = fwd(stocks[code], i, h)
                    if r is not None:
                        scored.append((ft[f], r))
                if len(scored) < 3:
                    continue
                scored.sort(key=lambda x: -x[0])
                day_mean = sum(r for _, r in scored) / len(scored)
                top_excess.append(scored[0][1] - day_mean)
                # 秩相关（简化 Pearson on ranks）
                n = len(scored)
                rk_f = {k: rnk for rnk, (k, _) in enumerate(sorted(scored))}
                rk_r = {k: rnk for rnk, k in enumerate(sorted(r for _, r in scored))}
                mf = sum(rk_f.values()) / n
                mr = sum(rk_r.values()) / n
                cov = sum((rk_f[a] - mf) * (rk_r[b] - mr) for a, b in [(x[0], x[1]) for x in scored])
                vf = sum((rk_f[x[0]] - mf) ** 2 for x in scored)
                vr = sum((rk_r[x[1]] - mr) ** 2 for x in scored)
                if vf > 0 and vr > 0:
                    ics.append(cov / (vf * vr) ** 0.5)
            if top_excess:
                te = 100 * sum(top_excess) / len(top_excess)
                ic = sum(ics) / len(ics) if ics else 0
                print(f"  {f}: 头名超额 {te:+.2f}pp/日  IC {ic:+.3f}  (n日={len(top_excess)})", flush=True)

    # 2) 合成评分（z 分和：深度+超跌+连跌+小市值+缩量）
    print("\n== 合成评分（z 分和：深度/超跌/连跌/小市值/缩量）==")
    for h, hname in ((1, "T+1"), (5, "T+5")):
        top_excess = []
        for dt, evs in cluster.items():
            scored = []
            for f in FEATS[:5]:
                vs = [e[2][f] for e in evs]
                m = sum(vs) / len(vs)
                sd = (sum((x - m) ** 2 for x in vs) / len(vs)) ** 0.5 or 1
                for e in evs:
                    e[2][f"_z_{f}"] = (e[2][f] - m) / sd
            for code, i, ft in evs:
                r = fwd(stocks[code], i, h)
                if r is not None:
                    z = sum(ft[f"_z_{f}"] for f in FEATS[:5])
                    scored.append((z, r))
            if len(scored) < 3:
                continue
            scored.sort(key=lambda x: -x[0])
            day_mean = sum(r for _, r in scored) / len(scored)
            top_excess.append(scored[0][1] - day_mean)
        if top_excess:
            print(f"  {hname}: 合成头名超额 {100*sum(top_excess)/len(top_excess):+.2f}pp/日 (n日={len(top_excess)})", flush=True)


if __name__ == "__main__":
    main()
