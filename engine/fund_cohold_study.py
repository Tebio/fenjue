#!/usr/bin/env python3
"""月频「同类动量」事件研究（基金共同持股网络）——冯冠豪 Active Mutual Fund Co-Holdings 的 A 股主板移植。

设计
  网络 : 季度 Q 主动偏股基金 top10 重仓 → 股票对共同被 ≥2 个组合重仓即一条边，边权=共同组合数；
         每股取边权 top10 邻居（并列按代码升序，确定性）。
  PIT  : 网络可用日 = 季报披露保守死线 Q1→05-01 / Q2→09-01 / Q3→11-01 / Q4→次年04-01。
         信号只用 t-1 月末及以前的价；结果 = t 月末收益。无任何未来信息。
  信号 : A 的 top10 邻居在月 t-1 的等权收益（有效邻居 ≥3 才计）。
  结果 : A 在月 t 的收益 − 当期全宇宙等权收益（剔 β 超额）。
统计 : 每月按信号五分组 → Q5−Q1 超额价差；NW(3) t；命中率；分年；变体（边权加权 / 边≥3 / 邻居数）。
对照 : ①自身动量三分组内价差（剔自身动量代理）②MA60 位置带内价差（位置匹配）。
产物 : data/fund_cohold/peer_momentum_study.json
用法 : .venv/bin/python engine/fund_cohold_study.py [起始月 YYYY-MM] [结束月 YYYY-MM]
"""
import json, math, os, sys
from collections import defaultdict
import numpy as np

ROOT = "/opt/data/fenjue"
DC = f"{ROOT}/data/fund_cohold"
MAT, NPZ = f"{DC}/matrix", f"{DC}/kc_scalars.npz"
OUT = f"{DC}/peer_momentum_study.json"
QV = {"03-31": lambda y: f"{y}-05-01", "06-30": lambda y: f"{y}-09-01",
      "09-30": lambda y: f"{y}-11-01", "12-31": lambda y: f"{y+1}-04-01"}


def nw_t(x, lag=3):
    x = np.asarray(x, float); x = x[np.isfinite(x)]; n = len(x)
    if n < 6: return float("nan")
    d = x - x.mean(); s = (d * d).mean()
    for L in range(1, min(lag, n - 1) + 1):
        s += 2 * (1 - L / (lag + 1)) * (d[L:] * d[:-L]).mean()
    return float(x.mean() / math.sqrt(s / n)) if s > 0 else float("nan")


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else "2021-06"
    end = sys.argv[2] if len(sys.argv) > 2 else "2026-09"
    z = np.load(NPZ, allow_pickle=True)
    codes = [str(c) for c in z["codes"]]
    months = [str(m) for m in z["months"]]
    me, pos = z["month_end"], z["ma60_pos"]
    ci = {c: i for i, c in enumerate(codes)}
    mi = {m: i for i, m in enumerate(months)}
    mats = {f[:-5]: json.load(open(f"{MAT}/{f}"))
            for f in os.listdir(MAT) if f.endswith(".json") and f != "ledger.json"}
    q_avail = sorted((QV[q[5:]](int(q[:4])), q) for q in mats)
    print(f"季度矩阵 {len(mats)} 季: {q_avail[0][1]} .. {q_avail[-1][1]}", flush=True)

    def net_at(date):
        c = [q for av, q in q_avail if av <= date]
        return c[-1] if c else None

    def mret(i, m):
        j = mi.get(m)
        if j is None or j == 0: return None
        a, b = me[i, j - 1], me[i, j]
        if not np.isfinite(a) or not np.isfinite(b) or a <= 0 or b <= 0: return None
        return float(b / a - 1)

    month_last_date = {}
    for k in json.load(open(f"{ROOT}/data/big_kcache/000001.json")):
        month_last_date[k["date"][:7]] = k["date"]

    study_months = [m for m in months if start <= m <= end]
    rets, umean = {}, {}
    prevs = {months[mi[m] - 1] for m in study_months if mi[m] > 0}
    for m in sorted(set(study_months) | prevs):
        rs = []
        for c in codes:
            r = mret(ci[c], m)
            if r is not None:
                rets[(c, m)] = r; rs.append(r)
        umean[m] = float(np.mean(rs)) if rs else None

    net_cache, events = {}, []
    for mt in study_months:
        j = mi[mt]
        if j == 0: continue
        mp = months[j - 1]
        ref = month_last_date.get(mp)
        q = net_at(ref) if ref else None
        if q is None: continue
        if q not in net_cache:
            pair = defaultdict(int)
            for hold in mats[q].values():
                ss = [s for s in hold if s[:2] in ("60", "00") and s in ci
                      and mret(ci[s], mp) is not None]
                for a in range(len(ss)):
                    for b in range(a + 1, len(ss)):
                        pair[(ss[a], ss[b])] += 1
            n2, n3 = defaultdict(list), defaultdict(list)
            for (a, b), w in pair.items():
                if w >= 2:
                    n2[a].append((b, w)); n2[b].append((a, w))
                if w >= 3:
                    n3[a].append((b, w)); n3[b].append((a, w))
            for d in (n2, n3):
                for a in d:
                    d[a].sort(key=lambda x: (-x[1], x[0])); d[a] = d[a][:10]
            net_cache[q] = (n2, n3, sum(1 for v in pair.values() if v >= 2))
            print(f"网络 {q}: 边≥2={net_cache[q][2]} 覆盖股票={len(n2)}", flush=True)
        n2, n3 = net_cache[q][0], net_cache[q][1]
        for A, nbrs in n2.items():
            rA, own = rets.get((A, mt)), rets.get((A, mp))
            if rA is None: continue
            rn, rw = [], []
            for s, w in nbrs:
                r = rets.get((s, mp))
                if r is not None: rn.append(r); rw.append((r, w))
            if len(rn) < 3: continue
            r3 = [x for x in (rets.get((s, mp)) for s, w in n3.get(A, [])) if x is not None]
            events.append({"m": mt, "A": A, "ref": ref, "q": q,
                           "sig": float(np.mean(rn)),
                           "sigw": float(np.average([x for x, w in rw], weights=[w for x, w in rw])),
                           "sig3": float(np.mean(r3)) if len(r3) >= 3 else None,
                           "nbr": len(rn), "r": rA, "ex": rA - umean[mt], "own": own,
                           "pos": float(pos[ci[A], j - 1]) if np.isfinite(pos[ci[A], j - 1]) else None})
    print(f"事件 {len(events)} 覆盖月份 {len(set(e['m'] for e in events))}", flush=True)

    def quintile(evts, key, col="ex", min_n=50):
        g = defaultdict(list)
        for e in evts:
            if e.get(key) is not None: g[e["m"]].append(e)
        sp, exq = [], defaultdict(list)
        for m, lst in sorted(g.items()):
            lst.sort(key=lambda e: e[key]); n = len(lst)
            if n < min_n: continue
            qs = [lst[n * k // 5: n * (k + 1) // 5] for k in range(5)]
            means = [float(np.mean([e[col] for e in q])) for q in qs if q]
            if len(means) < 5: continue
            for k in range(5): exq[k + 1].append(means[k])
            sp.append(means[4] - means[0])
        return sp, exq, len(g)

    def summ(sp, exq, nm, label):
        return {"label": label, "months": nm,
                "spread_pp": round(float(np.mean(sp)) * 100, 3) if sp else None,
                "hit": round(float(np.mean([x > 0 for x in sp])), 3) if sp else None,
                "nw_t": round(nw_t(np.array(sp) * 100), 2) if len(sp) > 5 else None,
                "q_excess_pp": {str(k): round(float(np.mean(v)) * 100, 3) for k, v in sorted(exq.items())},
                "monthly_spread_pp": [round(x * 100, 3) for x in sp]}

    results = {}
    for key, label in [("sig", "等权信号"), ("sigw", "边权加权"), ("sig3", "边≥3变体")]:
        ev = [e for e in events if e.get(key) is not None]
        sp, exq, nm = quintile(ev, key)
        results[key] = summ(sp, exq, nm, label)

    def band(p):
        if p is None: return None
        if p >= 0: return "above_ma60"
        if p >= -0.10: return "0_to_-10"
        if p >= -0.25: return "-10_to_-25"
        return "below_-25"

    # 对照 1: 自身动量三分组内价差
    ctrl_own, mg = defaultdict(list), defaultdict(list)
    for e in events:
        if e["own"] is not None: mg[e["m"]].append(e)
    for m, lst in mg.items():
        lst.sort(key=lambda e: e["own"]); n = len(lst)
        if n < 60: continue
        for t in range(3):
            sub = sorted(lst[n * t // 3: n * (t + 1) // 3], key=lambda e: e["sig"])
            nn = len(sub)
            if nn < 20: continue
            ctrl_own[t].append(float(np.mean([e["ex"] for e in sub[-nn // 5:]]))
                               - float(np.mean([e["ex"] for e in sub[:nn // 5]])))
    results["ctrl_own_momentum"] = {f"own_tercile_{k+1}": {
        "spread_pp": round(float(np.mean(v)) * 100, 3), "months": len(v),
        "nw_t": round(nw_t(np.array(v) * 100), 2),
        "hit": round(float(np.mean([x > 0 for x in v])), 3)} for k, v in sorted(ctrl_own.items())}

    # 对照 2: MA60 位置带内价差（位置匹配）
    ctrl_pos = defaultdict(list)
    for m, lst in mg.items():
        b = defaultdict(list)
        for e in lst:
            k = band(e["pos"])
            if k: b[k].append(e)
        for k, sub in b.items():
            sub.sort(key=lambda e: e["sig"]); nn = len(sub)
            if nn < 25: continue
            ctrl_pos[k].append(float(np.mean([e["ex"] for e in sub[-nn // 5:]]))
                               - float(np.mean([e["ex"] for e in sub[:nn // 5]])))
    results["ctrl_position"] = {k: {"spread_pp": round(float(np.mean(v)) * 100, 3),
        "months": len(v), "nw_t": round(nw_t(np.array(v) * 100), 2),
        "hit": round(float(np.mean([x > 0 for x in v])), 3)} for k, v in sorted(ctrl_pos.items())}

    yearly = defaultdict(list)
    for m, lst in mg.items():
        lst.sort(key=lambda e: e["sig"]); n = len(lst)
        if n < 50: continue
        yearly[m[:4]].append(float(np.mean([e["ex"] for e in lst[-n // 5:]]))
                             - float(np.mean([e["ex"] for e in lst[:n // 5]])))
    results["by_year"] = {y: {"spread_pp": round(float(np.mean(v)) * 100, 3),
        "months": len(v), "hit": round(float(np.mean([x > 0 for x in v])), 3)}
        for y, v in sorted(yearly.items())}

    meta = {"study": "fund_cohold_peer_momentum", "role": "月频中线先导（不进短线推送）",
            "universe": "主板 60/00 且当期有价", "months": study_months, "n_events": len(events),
            "avail_rule": "Q1->05-01 Q2->09-01 Q3->11-01 Q4->次年04-01（保守披露死线）",
            "network": "主动偏股基金 top10 重仓；边=共同持有 ≥2 组合；每股 top10 边权邻居",
            "signal": "邻居月 t-1 等权收益，≥3 邻居", "outcome": "月 t 收益 − 当期宇宙均值",
            "fee": "未扣（月频先导口径）"}
    json.dump({"_meta": meta, "results": results,
               "events": [{"m": e["m"], "A": e["A"], "ref": e["ref"], "q": e["q"],
                           "sig": round(e["sig"], 6), "sigw": round(e["sigw"], 6),
                           "sig3": round(e["sig3"], 6) if e["sig3"] is not None else None,
                           "r": round(e["r"], 6), "ex": round(e["ex"], 6), "nbr": e["nbr"],
                           "own": round(e["own"], 6) if e["own"] is not None else None,
                           "pos": round(e["pos"], 6) if e["pos"] is not None else None}
                          for e in events]},
              open(OUT, "w"), ensure_ascii=False)
    print(json.dumps({k: v for k, v in results.items()}, ensure_ascii=False, indent=1)[:3000])
    print("STUDY_DONE", OUT)


if __name__ == "__main__":
    main()
