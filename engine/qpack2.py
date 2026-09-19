#!/usr/bin/env python3
"""qpack2.py — 用户思路六问 + 2026 验证（2026-09-19 深夜，「继续全跑」）。

Q1 双腿撞车日：恐慌腿与主线腿同日同时出票的重合度
Q2 主线期确认迟滞成本：今日收盘确认主线→明日买 vs 昨日已主线→今日买（1日提前量值多少）
Q3 缺口低开真假分辨：前5交易日有无业绩预告利空（PEAD 预减/首亏/续亏）→ T+5 分组
Q4 妖股期/主线期确认规则：「连续2日同regime才确认」vs 单日标签对主线腿的影响
Q5 双腿合并资金曲线（共账户、去重、共槽）
Q6 主线腿选票规则：排名特征 IC/头名超额（主线期事件）
Q7 2026 样本：主线腿+恐慌腿当年胜率全 horizon
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
OUT = {}


def fwd(d, i, h):
    ei = i + 1
    if ei + h >= d["n"] or d["o"][ei] <= 0 or d["o"][ei] <= d["c"][i] * 0.905:
        return None
    return d["c"][ei + h] / d["o"][ei] - 1 - FEE


def stat(rs):
    rs = [r for r in rs if r is not None]
    if not rs:
        return None
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    odds = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else None
    return {"n": len(rs), "win%": round(100 * len(wins) / len(rs), 1),
            "mean%": round(100 * sum(rs) / len(rs), 2), "赔率": round(odds, 2) if odds else None}


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    regime = lp.load_regime()
    days_sorted = sorted(regime)

    det_panic = lp.REGISTRY["组合_跌停低_三连阴"]
    det_ml = lp.REGISTRY["组合_缺口低开_低位阳线"]

    sigs_panic = lp._collect_sigs(det_panic, stocks)
    sigs_ml_all = lp._collect_sigs(det_ml, stocks)
    sigs_ml = {dt: evs for dt, evs in sigs_ml_all.items() if regime.get(dt) == "主线期"}

    # ---- Q1 撞车日 ----
    both = set(sigs_panic) & set(sigs_ml)
    overlap_pair = sum(1 for dt in both for e1 in sigs_panic[dt] if e1 in set(sigs_ml[dt]))
    OUT["Q1_撞车"] = {"双腿同日开火天数": len(both), "同票同日双腿命中": overlap_pair}
    print(f"Q1: 双腿同日开火 {len(both)} 天；同票双腿命中 {overlap_pair} 次", flush=True)

    # ---- Q2 主线确认迟滞成本 ----
    # A: 今日收盘确认主线期 → 明日开盘买（现行）; B: 昨日已是主线期 → 今日开盘买（提前一天）
    mainline_set = {d for d in days_sorted if regime[d] == "主线期"}
    rA, rB = [], []
    for dt, evs in sigs_ml_all.items():
        if dt in mainline_set:
            for code, i in evs:
                r = fwd(stocks[code], i, 5)
                if r is not None:
                    rA.append(r)
    # B：信号日在主线期，但入场提前一天 = 信号日当天开盘买（昨日已主线，今日盘前可知昨日regime）
    for dt, evs in sigs_ml_all.items():
        # 昨日（前一交易日）是主线期 且 今日仍主线期 → 今日开盘就买（利用昨日已知信息）
        k = days_sorted.index(dt) if dt in mainline_set else None
        if k and k > 0 and regime.get(days_sorted[k - 1]) == "主线期":
            for code, i in evs:
                d = stocks[code]
                if d["o"][i] > 0 and i + 5 < d["n"]:
                    rB.append(d["c"][i + 5] / d["o"][i] - 1 - FEE)   # 信号日当天开盘买
    OUT["Q2_确认迟滞"] = {"确认后次日买": stat(rA), "连续主线提前一天买": stat(rB)}
    print(f"Q2: 次日买 {stat(rA)} vs 提前一天买 {stat(rB)}", flush=True)

    # ---- Q3 缺口真假（PEAD 利空分辨）----
    pead = json.loads((ROOT / "data/pead_events.json").read_text())
    bad = defaultdict(list)   # code -> [NOTICE_DATE...]
    for e in pead:
        if e.get("FORECASTTYPE") in ("预减", "首亏", "续亏", "增亏", "略减"):
            bad[e["SECURITY_CODE"]].append((e["NOTICE_DATE"] or "")[:10])
    for v in bad.values():
        v.sort()
    import bisect as _bs
    r_bad, r_clean = [], []
    for dt, evs in sigs_ml_all.items():
        if dt not in mainline_set:
            continue
        for code, i in evs:
            r = fwd(stocks[code], i, 5)
            if r is None:
                continue
            bl = bad.get(code, [])
            j = _bs.bisect_right(bl, dt) - 1
            has_bad = j >= 0 and (dt > bl[j] >= days_sorted[max(0, days_sorted.index(dt) - 7)] if dt in days_sorted else False)
            (r_bad if has_bad else r_clean).append(r)
    OUT["Q3_缺口真假"] = {"前一周有利空预告": stat(r_bad), "无利空预告": stat(r_clean)}
    print(f"Q3: 有利空 {stat(r_bad)} vs 无利空 {stat(r_clean)}", flush=True)

    # ---- Q4 迟滞确认规则 ----
    # 主线腿只在「昨日+前日都是主线期」的确认日出票
    confirm_set = set()
    for k in range(2, len(days_sorted)):
        if regime[days_sorted[k]] == regime[days_sorted[k-1]] == "主线期":
            confirm_set.add(days_sorted[k])
    sigs_ml_conf = {dt: evs for dt, evs in sigs_ml_all.items() if dt in confirm_set}
    r_conf = []
    for dt, evs in sigs_ml_conf.items():
        for code, i in evs:
            r = fwd(stocks[code], i, 5)
            if r is not None:
                r_conf.append(r)
    OUT["Q4_迟滞确认"] = {"单日主线标签": stat(rA), "连续2日确认": stat(r_conf),
                       "确认日数": len(confirm_set), "主线期总日数": len(mainline_set)}
    print(f"Q4: 单日 {stat(rA)} vs 连续2日确认 {stat(r_conf)}（{len(confirm_set)}/{len(mainline_set)} 天）", flush=True)

    # ---- Q5 双腿合并资金曲线 ----
    merged = defaultdict(list)
    for src in (sigs_panic, sigs_ml):
        for dt, evs in src.items():
            merged[dt].extend(evs)
    merged = {dt: list(set(evs)) for dt, evs in merged.items()}
    for tag, sg, K in (("恐慌腿单跑", sigs_panic, 5), ("主线腿单跑", sigs_ml, 1), ("双腿合并", dict(merged), 3)):
        r = lp.capacity_sim(sg, stocks, slots=10, hold=5, cluster_k=K, seeds=2, pick="deep")
        OUT[f"Q5_{tag}"] = r
        print(f"Q5 {tag}: 年化{r['年化%']}% 均笔{r['均笔%']}% 回撤{r['回撤%']}% 笔数{r['笔数']}", flush=True)

    # ----Q6 主线腿选票（排名特征）----
    FEATS = {
        "缺口深度": lambda d, i: -(d["o"][i] / d["c"][i - 1] - 1),       # 低开越深越好？
        "日内强度": lambda d, i: d["c"][i] / d["o"][i] - 1,             # 收阳越强越好？
        "缩量": lambda d, i: -lp._volratio(d, i),
        "小市值": lambda d, i: -(lp.cap_at_date(lp._XCAP, d["code"], d["date"][i]) or 1e9),
        "距MA20深": lambda d, i: -(d["c"][i] / (sum(d["c"][i - 19:i + 1]) / 20) - 1) if i >= 20 else 0,
    }
    q6 = {}
    for fn, f in FEATS.items():
        top_excess = []
        for dt, evs in sigs_ml.items():
            scored = []
            for code, i in evs:
                r = fwd(stocks[code], i, 5)
                if r is not None:
                    scored.append((f(stocks[code], i), r))
            if len(scored) < 3:
                continue
            scored.sort(key=lambda x: -x[0])
            day_mean = sum(r for _, r in scored) / len(scored)
            top_excess.append(scored[0][1] - day_mean)
        if top_excess:
            q6[fn] = round(100 * sum(top_excess) / len(top_excess), 2)
            print(f"Q6 主线腿选票 {fn}: 头名超额 {q6[fn]:+.2f}pp/日 (n日={len(top_excess)})", flush=True)
    OUT["Q6_主线腿选票"] = q6

    # ---- Q7 2026 样本（主线腿 + 恐慌腿当年全 horizon）----
    for tag, sigs in (("主线腿", sigs_ml), ("恐慌腿", sigs_panic)):
        for h in (1, 5, 20):
            rs = []
            for dt, evs in sigs.items():
                if dt < "2026-01-01":
                    continue
                for code, i in evs:
                    r = fwd(stocks[code], i, h)
                    if r is not None:
                        rs.append(r)
            print(f"Q7 2026 {tag} T+{h}: {stat(rs)}", flush=True)
            OUT[f"Q7_2026_{tag}_T{h}"] = stat(rs)

    (ROOT / "data/qpack2_20260919.json").write_text(json.dumps(OUT, ensure_ascii=False, indent=1))
    print("saved data/qpack2_20260919.json")


if __name__ == "__main__":
    main()
