#!/usr/bin/env python3
"""allregime_allx_study.py — 全周期×全信号×右尾选股（2026-09-19/20 用户三连令）。

A. 全 regime × 全 REGISTRY × T+1/T+5/T+20：平淡期也出，一个不落
B. 右尾选股（反马云平均）：旗舰组合命中内的收益分布（分位数/最大亏损）+
   右尾预测器：哪些特征能把「涨最多的那批」挑出来（捕获率=特征 top10% 命中收益 top10% 的倍率）
C. 2026 当年同样口径
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent
FEE = 0.0015


def fwd(d, i, h):
    ei = i + 1
    if ei + h >= d["n"] or d["o"][ei] <= 0 or d["o"][ei] <= d["c"][i] * 0.905:
        return None
    return d["c"][ei + h] / d["o"][ei] - 1 - FEE


def stat_full(rs):
    rs = sorted(r for r in rs if r is not None)
    if len(rs) < 30:
        return None
    n = len(rs)
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    odds = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else None
    q = lambda p: round(100 * rs[min(int(n * p), n - 1)], 2)
    return {"n": n, "win%": round(100 * len(wins) / n, 1), "mean%": round(100 * sum(rs) / n, 2),
            "med%": q(0.5), "p5%": q(0.05), "p95%": q(0.95), "最差%": round(100 * rs[0], 1),
            "赔率": round(odds, 2) if odds else None}


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    regime = lp.load_regime()
    REGIMES = ("主线期", "妖股期", "恐慌期", "平淡期")

    # ---- A 全 regime × 全信号 ----
    print("== A. 全 regime × 全信号（T+5，n≥100）==", flush=True)
    table = {}
    for name, det in lp.REGISTRY.items():
        cells = defaultdict(list)
        for code, d in stocks.items():
            for i in range(61, d["n"] - 6):
                rg = regime.get(d["date"][i])
                if rg is None:
                    continue
                try:
                    if det(d, i):
                        r = fwd(d, i, 5)
                        if r is not None:
                            cells[rg].append(r)
                except Exception:
                    pass
        row = {rg: stat_full(cells.get(rg, [])) for rg in REGIMES}
        if any(row.values()):
            table[name] = row
    # 每 regime 的可玩格（均值>0 且胜率>52%）
    for rg in REGIMES:
        playable = [(nm, row[rg]) for nm, row in table.items()
                    if row.get(rg) and row[rg]["mean%"] > 0 and row[rg]["win%"] > 52]
        playable.sort(key=lambda x: -x[1]["mean%"])
        print(f"\n◆ {rg} 可玩格（均值>0 胜率>52%）: {len(playable)} 个", flush=True)
        for nm, s in playable[:8]:
            print(f"  {nm}: 胜{s['win%']}% 均{s['mean%']}% n={s['n']} 赔{s['赔率']} 最差{s['最差%']}%", flush=True)

    # ---- B 右尾选股（旗舰组合：深跌+跌停潮）----
    print("\n== B. 右尾选股（组合_跌停低_深跌_跌停潮 命中内分布）==", flush=True)
    fund, capm = lp._XFUND, lp._XCAP
    det = lp.REGISTRY["组合_跌停低_深跌_跌停潮"]
    rows = []
    for code, d in stocks.items():
        for i in range(61, d["n"] - 7):
            try:
                if not det(d, i):
                    continue
            except Exception:
                continue
            r5 = fwd(d, i, 5)
            if r5 is None:
                continue
            c, v, ma = d["c"], d["v"], d["ma60"]
            rows.append({
                "r5": r5,
                "深度": -(c[i] / ma[i] - 1),
                "超跌60": -(c[i] / max(c[max(0, i - 60):i + 1]) - 1),
                "量比": lp._volratio(d, i),
                "连跌": sum(1 for k in range(9) if c[i - k] < c[i - k - 1]),
                "市值": lp.cap_at_date(capm, code, d["date"][i]),
            })
    rs = sorted(r["r5"] for r in rows)
    n = len(rs)
    print(f"命中 {n}：分布 p5={100*rs[int(n*.05)]:.1f}% p25={100*rs[int(n*.25)]:.1f}% 中位={100*rs[n//2]:.1f}% "
          f"p75={100*rs[int(n*.75)]:.1f}% p95={100*rs[int(n*.95)]:.1f}% 最差={100*rs[0]:.1f}% 最好={100*rs[-1]:.1f}%", flush=True)
    # 右尾捕获：特征 top10% 里有多少比例落在收益 top10%
    top_r = set(sorted(range(n), key=lambda k: -rows[k]["r5"])[:n // 10])
    for f in ("深度", "超跌60", "量比", "连跌", "市值"):
        vals = [r[f] for r in rows if r[f] is not None]
        if not vals:
            continue
        order = sorted(range(len(rows)), key=lambda k: -(rows[k][f] if rows[k][f] is not None else -1e18))[:n // 10]
        capture = len(set(order) & top_r) / max(1, len(top_r))
        print(f"  右尾捕获率（{f} top10% ∩ 收益 top10%）: {100*capture:.0f}%（随机=10%）", flush=True)

    # ---- C 2026 当年（旗舰组合）----
    print("\n== C. 2026 旗舰组合当年 ==", flush=True)
    rs26 = [r["r5"] for r in rows]  # rows 没带年份，重算
    rows26 = []
    for code, d in stocks.items():
        for i in range(61, d["n"] - 7):
            if d["date"][i] < "2026-01-01":
                continue
            try:
                if det(d, i):
                    r5 = fwd(d, i, 5)
                    if r5 is not None:
                        rows26.append(r5)
            except Exception:
                pass
    s26 = stat_full(rows26)
    print(f"  2026 旗舰: {s26}", flush=True)

    (ROOT / "data/allregime_allx_20260919.json").write_text(json.dumps(
        {"regime_table": table, "旗舰分布n": n, "2026旗舰": s26}, ensure_ascii=False, indent=1))
    print("saved", flush=True)


if __name__ == "__main__":
    main()
