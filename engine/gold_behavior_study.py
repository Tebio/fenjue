#!/usr/bin/env python3
"""金股股性研究（2026-10-19 用户「金股股性也研究一下」）。

沿用 skill `a-stock-signal-lab` 的股性口径（`fenjue/timing.py::StockBehaviorProfile`：
FADE 冲高回落 / V_RECOVERY / MIXED），但把观察尺度从**分时**换到**日线 + T+20 持有期**，
并补齐 A 股常用的股性维度。

三段产出：
① **选股画像**：金股池（2026-05~10、PIT、主板）的股性分布 vs 同期全市场主板基准。
② **股性 × 前瞻收益**：按各股性分位分组看 T+5/T+20，**要求跨月符号稳定**才算数。
③ **股性分类 × 前瞻收益**：FADE / V_RECOVERY / MIXED 三类在金股池里的持有期表现。

特征全部只用「入场日前一日收盘及之前」的数据（无前视）。

用法：.venv/bin/python engine/gold_behavior_study.py
"""
import collections
import glob
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, "/opt/data/fenjue/engine")
sys.path.insert(0, "/opt/data/python-libs")
import law_pipeline as lp
import trade_calendar as tc

ROOT = "/opt/data/fenjue"
FEE = 0.0015
MOS = ("2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10")


def cohorts():
    rows = []
    for fp in glob.glob(f"{ROOT}/data/gold_raw/*.json"):
        rows += json.load(open(fp))
    out = collections.defaultdict(lambda: collections.defaultdict(set))
    seen = set()
    for r in rows:
        c = str(r["股票代码"]).split(".")[0].zfill(6)
        if c[:2] not in ("60", "00"):
            continue
        ct = str(r["组合时间"])[:6]
        ann = str(r["公告日期"])
        k = (c, r["研究机构"], ann, ct)
        if k in seen:
            continue
        seen.add(k)
        out[f"{ct[:4]}-{ct[4:]}"][c].add(ann)
    return out


def features(d, j, idx=None):
    """j = 入场日索引；只用 j-1 及之前的数据。"""
    if j < 260:
        return None
    c, h, l, o, v = d["c"], d["h"], d["l"], d["o"], d["v"]
    import statistics as _st
    feat = {}
    r1 = [(c[k] / c[k - 1] - 1) for k in range(j - 60, j)]
    feat["vol60"] = _st.pstdev(r1)
    amp = [((h[k] - l[k]) / c[k - 1]) for k in range(j - 60, j)]
    feat["amp60"] = _st.mean(amp)
    feat["turn_amt60"] = _st.mean([v[k] * c[k] / 1e8 for k in range(j - 60, j)])   # 亿
    lim = 0
    low_lim = 0
    for k in range(j - 250, j):
        ch = c[k] / c[k - 1] - 1
        if ch >= 0.095:
            lim += 1
        elif ch <= -0.095:
            low_lim += 1
    feat["limit250"] = lim
    feat["limitdown250"] = low_lim
    feat["limit_ratio"] = lim / max(1, lim + low_lim) if (lim + low_lim) else 0.5
    feat["dist250"] = c[j - 1] / max(h[j - 250:j]) - 1
    feat["dist60"] = c[j - 1] / max(h[j - 60:j]) - 1
    feat["r60_pre"] = c[j - 1] / c[j - 61] - 1
    feat["r20_pre"] = c[j - 1] / c[j - 21] - 1
    # 日线股性：冲高回落 / V形修复（对齐 StockBehaviorProfile 口径）
    fade = vrec = n = 0
    for k in range(j - 120, j):
        if c[k - 1] <= 0:
            continue
        n += 1
        if h[k] / c[k - 1] - 1 >= 0.03 and c[k] / h[k] - 1 <= -0.02:
            fade += 1
        if l[k] / c[k - 1] - 1 <= -0.03 and c[k] / l[k] - 1 >= 0.02:
            vrec += 1
    feat["fade"] = fade / n if n else 0
    feat["vrec"] = vrec / n if n else 0
    # 波动方向偏好：连涨/连跌后的次日表现（一阶自相关）
    xs = [(c[k] / c[k - 1] - 1) for k in range(j - 120, j)]
    if len(xs) > 5:
        mx = _st.mean(xs)
        num = sum((xs[k] - mx) * (xs[k - 1] - mx) for k in range(1, len(xs)))
        den = sum((x - mx) ** 2 for x in xs)
        feat["autocorr"] = num / den if den else 0
    else:
        feat["autocorr"] = 0
    # beta to 上证（60日）
    if idx:
        pairs = [(r1[n], idx.get(d["date"][k])) for n, k in enumerate(range(j - 60, j))]
        pairs = [(a, b) for a, b in pairs if b is not None]
        if len(pairs) >= 30:
            mi = _st.mean([b for _, b in pairs])
            mr = _st.mean([a for a, _ in pairs])
            cov = sum((a - mr) * (b - mi) for a, b in pairs)
            var = sum((b - mi) ** 2 for _, b in pairs)
            feat["beta60"] = cov / var if var else 1.0
        else:
            feat["beta60"] = 1.0
    else:
        feat["beta60"] = 1.0
    return feat


def fwd(d, j, h):
    return (d["c"][j + h] / d["o"][j] - 1 - FEE) if j + h < d["n"] and d["o"][j] > 0 else None


def main():
    U = lp.load_universe()
    idx_raw = json.loads(Path(ROOT + "/data/index_sh000001.json").read_text())
    ic = {r["date"]: float(r["close"]) for r in idx_raw}
    combos = cohorts()

    pool, base = [], []
    for mo in MOS:
        y = int(mo[:4])
        days = [x for x in (tc.trading_days(y) or []) if x.startswith(mo)]
        if len(days) < 7:
            continue
        entry = days[5]
        if entry not in ic:
            continue
        idays = [r["date"] for r in idx_raw]
        ei = idays.index(entry)
        iret = {idays[k]: ic[idays[k]] / ic[idays[k - 1]] - 1 for k in range(max(1, ei - 400), ei)}
        for c, anns in combos[mo].items():
            if min(anns) > entry.replace("-", ""):
                continue
            d = U.get(c)
            if not d or entry not in d["date"]:
                continue
            j = d["date"].index(entry)
            f = features(d, j, iret)
            if not f:
                continue
            pool.append(dict(f, mo=mo, code=c, name=d.get("name", c),
                             r5=fwd(d, j, 5), r20=fwd(d, j, 20)))
        # 基准：同日全市场主板（抽样 800）
        step = max(1, len(U) // 800)
        for c, d in list(U.items())[::step]:
            if entry not in d["date"]:
                continue
            j = d["date"].index(entry)
            f = features(d, j, iret)
            if not f:
                continue
            base.append(dict(f, mo=mo, r20=fwd(d, j, 20)))

    KEYS = ["vol60", "amp60", "turn_amt60", "limit250", "limit_ratio", "dist250",
            "dist60", "r20_pre", "r60_pre", "beta60", "fade", "vrec", "autocorr"]
    print(f"金股池 n={len(pool)}（2026-05~10 PIT 主板）｜基准 n={len(base)}（同期全市场主板抽样）\n")
    print("① 选股画像：金股池 vs 全市场（中位）")
    print(f"{'特征':<12}{'金股池':>10}{'全市场':>10}{'差':>9}   解读")
    desc = {
        "vol60": ("日波动率(60日)", 100, "%"), "amp60": ("日均振幅", 100, "%"),
        "turn_amt60": ("日均成交额(亿)", 1, ""), "limit250": ("年涨停次数", 1, "次"),
        "limit_ratio": ("涨停占涨跌停比", 1, ""), "dist250": ("距250日高", 100, "%"),
        "dist60": ("距60日高", 100, "%"), "r20_pre": ("入场前20日涨幅", 100, "%"),
        "r60_pre": ("入场前60日涨幅", 100, "%"), "beta60": ("60日beta", 1, ""),
        "fade": ("冲高回落率", 100, "%"), "vrec": ("V形修复率", 100, "%"),
        "autocorr": ("日收益自相关", 1, ""),
    }
    for k in KEYS:
        a = st.median([p[k] for p in pool])
        b = st.median([p[k] for p in base])
        mult, unit = desc[k][1], desc[k][2]
        print(f"{desc[k][0]:<12}{a*mult:>10.2f}{b*mult:>10.2f}{(a-b)*mult:>+9.2f}")

    print("\n② 股性 × T+20：按池内三分位分组，看是否跨月稳定（要求 5/5 月同号）")
    for k in KEYS:
        vals = [p[k] for p in pool if p["r20"] is not None]
        if len(vals) < 60:
            continue
        qs = st.quantiles(vals, n=3)
        rows = []
        for lo, hi, lab in [(-1e9, qs[0], "低"), (qs[0], qs[1], "中"), (qs[1], 1e9, "高")]:
            g = [p["r20"] for p in pool if lo <= p[k] < hi and p["r20"] is not None]
            per = []
            for mo in MOS:
                gm = [p["r20"] for p in pool if lo <= p[k] < hi and p["r20"] is not None and p["mo"] == mo]
                if len(gm) >= 8:
                    per.append(st.mean(gm))
            rows.append((lab, len(g), st.mean(g) if g else 0,
                         sum(1 for x in g if x > 0) / len(g) if g else 0, per))
        hi_lab, hi_n, hi_m, hi_w, hi_per = rows[2]
        lo_lab, lo_n, lo_m, lo_w, lo_per = rows[0]
        # 跨月稳定：高组-低组 每月同号
        diffs = []
        for mo in MOS:
            gh = [p["r20"] for p in pool if p[k] >= qs[1] and p["r20"] is not None and p["mo"] == mo]
            gl = [p["r20"] for p in pool if p[k] < qs[0] and p["r20"] is not None and p["mo"] == mo]
            if len(gh) >= 6 and len(gl) >= 6:
                diffs.append(st.mean(gh) - st.mean(gl))
        stable = len(diffs) >= 4 and (all(d > 0 for d in diffs) or all(d < 0 for d in diffs))
        print(f"  {desc[k][0]:<14} 低 {lo_m*100:+6.2f}%/胜{lo_w*100:3.0f}% (n={lo_n:>3})"
              f" | 高 {hi_m*100:+6.2f}%/胜{hi_w*100:3.0f}% (n={hi_n:>3})"
              f" | 高-低 {st.mean(diffs)*100:+5.2f}pp 同号月 {sum(1 for d in diffs if d>0)}/{len(diffs)}"
              f"{'  ← 跨月稳定' if stable else ''}")

    print("\n③ 股性分类（FADE / V_RECOVERY / MIXED）× 前瞻收益，逐月")
    def classify(p):
        if p["fade"] >= 0.55 and p["fade"] - p["vrec"] >= 0.15:
            return "FADE"
        if p["vrec"] >= 0.55 and p["vrec"] - p["fade"] >= 0.15:
            return "V_RECOVERY"
        return "MIXED"
    for p in pool:
        p["cls"] = classify(p)
    print(f"{'月':<9}" + "".join(f"{c:>22}" for c in ("FADE", "MIXED", "V_RECOVERY")))
    for mo in MOS:
        line = f"{mo:<9}"
        for cl in ("FADE", "MIXED", "V_RECOVERY"):
            g = [p["r20"] for p in pool if p["mo"] == mo and p["cls"] == cl and p["r20"] is not None]
            line += f"{(f'{st.mean(g)*100:+.2f}%/胜{sum(1 for x in g if x>0)/len(g)*100:.0f}%(n={len(g)})' if g else '-'):>22}"
        print(line)
    for cl in ("FADE", "MIXED", "V_RECOVERY"):
        g = [p["r20"] for p in pool if p["cls"] == cl and p["r20"] is not None]
        if g:
            print(f"  合并 {cl:<11} n={len(g):>3}  T+20 {st.mean(g)*100:+.2f}%/胜{sum(1 for x in g if x>0)/len(g)*100:.0f}%")


if __name__ == "__main__":
    main()
