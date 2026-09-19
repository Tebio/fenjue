#!/usr/bin/env python3
"""qpack3.py — 欠账清剿批 1（2026-09-19 深夜）。

A. 主线腿日内强度选票容量验证（qpack2 Q6 发现的 +1.97pp/日 接进 capacity_sim pick="strength"）
B. 流动性约束实测：旗舰组合加「入场日成交额≥2亿」过滤前后的容量曲线（E6 欠账）
C. PEAD 业绩漂移（S4 老欠账）：预增50+/强利好 的 T+5/T+20 + 位置对照
D. 触板底座交叉由 cross_matrix --base touch 另行跑（本脚本不含）
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent
FEE = 0.0015


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    regime = lp.load_regime()
    out = {}

    # ---- A 主线腿：日内强度选票 vs 随机（主线期-only，K1/K3）----
    det_ml = lp.REGISTRY["组合_缺口低开_低位阳线"]
    sigs_all = lp._collect_sigs(det_ml, stocks)
    sigs_ml = {dt: evs for dt, evs in sigs_all.items() if regime.get(dt) == "主线期"}
    for K in (1, 3):
        r0 = lp.capacity_sim(sigs_ml, stocks, slots=10, hold=5, cluster_k=K, seeds=3, pick="random")
        r1 = lp.capacity_sim(sigs_ml, stocks, slots=10, hold=5, cluster_k=K, seeds=3, pick="strength")
        out[f"A_主线腿_K{K}"] = {"随机": r0, "日内强度": r1}
        print(f"A K{K}: 随机 {r0['年化%']}%/笔{r0['均笔%']}%  vs  强度 {r1['年化%']}%/笔{r1['均笔%']}%", flush=True)

    # ---- B 流动性约束：旗舰组合入场日成交额<2亿剔除 ----
    det = lp.REGISTRY["组合_跌停低_深跌_跌停潮"]
    sigs = lp._collect_sigs(det, stocks)
    sigs_liq = {dt: [s for s in evs if stocks[s[0]]["amt"][s[1]] >= 2e8] for dt, evs in sigs.items()}
    sigs_liq = {dt: evs for dt, evs in sigs_liq.items() if evs}
    dropped = sum(len(v) for v in sigs.values()) - sum(len(v) for v in sigs_liq.values())
    for tag, sg in (("原版", sigs), ("剔低流动性", sigs_liq)):
        r = lp.capacity_sim(sg, stocks, slots=10, hold=5, cluster_k=3, seeds=2, pick="deep")
        out[f"B_{tag}"] = r
        print(f"B {tag}: 年化{r['年化%']}% 均笔{r['均笔%']}% 回撤{r['回撤%']}%", flush=True)
    print(f"B 剔除低流动性事件 {dropped} 笔", flush=True)

    # ---- C PEAD 业绩预告漂移（S4 欠账首跑）----
    pead = json.loads((ROOT / "data/pead_events.json").read_text())
    by_date = defaultdict(list)   # notice_date -> [(code, type)]
    for e in pead:
        nd = (e.get("NOTICE_DATE") or "")[:10]
        t = e.get("FORECASTTYPE") or ""
        if nd:
            by_date[nd].append((e["SECURITY_CODE"], t))
    # 事件日=首个≥公告日的交易日（盘后公告次日）
    all_dates = sorted({x for s in stocks.values() for x in s["date"]})
    import bisect as _b

    def ev_day(nd):
        j = _b.bisect_left(all_dates, nd)
        return all_dates[j] if j < len(all_dates) else None

    def stat(rs):
        rs = [r for r in rs if r is not None]
        if not rs:
            return None
        w = [r for r in rs if r > 0]
        l = [r for r in rs if r <= 0]
        odds = (sum(w) / len(w)) / abs(sum(l) / len(l)) if w and l else None
        return {"n": len(rs), "win%": round(100 * len(w) / len(rs), 1),
                "mean%": round(100 * sum(rs) / len(rs), 2), "赔率": round(odds, 2) if odds else None}

    for types, tag in (({"预增"}, "预增"), ({"预增", "扭亏"}, "强利好"), ({"预减", "首亏"}, "强利空")):
        r5, r20 = [], []
        for nd, evs in by_date.items():
            dt = ev_day(nd)
            if dt is None:
                continue
            for code, t in evs:
                if t not in types:
                    continue
                d = stocks.get(code)
                if not d:
                    continue
                idx = {x: j for j, x in enumerate(d["date"])}
                i = idx.get(dt)
                if i is None or i < 1:
                    continue
                ei = i if False else i  # 事件日当根已是可交易日
                # 公告盘后发 → 次日开盘买
                if i + 1 >= d["n"]:
                    continue
                e0 = d["o"][i + 1]
                if e0 <= 0:
                    continue
                if i + 5 < d["n"]:
                    r5.append(d["c"][i + 5] / e0 - 1 - FEE)
                if i + 20 < d["n"]:
                    r20.append(d["c"][i + 20] / e0 - 1 - FEE)
        out[f"C_PEAD_{tag}"] = {"T+5": stat(r5), "T+20": stat(r20)}
        print(f"C PEAD_{tag}: T+5 {stat(r5)} | T+20 {stat(r20)}", flush=True)

    (ROOT / "data/qpack3_20260919.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved", flush=True)


if __name__ == "__main__":
    main()
