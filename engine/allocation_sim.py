#!/usr/bin/env python3
"""engine/allocation_sim.py — BACKLOG#13 高股息锚 × 双腿的资金分配（2026-09-19 深夜）。

问题：红利压舱石 / 恐慌腿 / 主线腿 的钱怎么分？底仓 60-70/进攻 0-30 是拍的没优化过。
腿的定义（blindspot §十七 + qpack2/qpack3 已验证）：
  红利锚  = dividend_core_satellite 资金曲线（data/dividend_curve_cs_20260913.json，8年 +196.8%）
  恐慌腿  = 组合_跌停低_三连阴，槽10/成簇K5/超跌最深选票（qpack2 恐慌腿单跑 10.4%/年 回撤-8.9%）
  主线腿  = 组合_缺口低开_低位阳线 ∩ 信号日regime=主线期，槽10/K1/日内强度选票
           （§十七 主线期-only +5.47%/年；qpack3 A：强度选票 K1 5.47→7.3%）
方法：三条资金曲线各自归一 → 按权重加权合成 → 扫 w_div×w_panic 全网格，报 年化/回撤/期末。
口径注记：双腿曲线=cost-MTM（capacity_sim 口径，权益在持有期走平），红利=真实MTM，
          混合口径会低估合并波动，回撤读数偏浅——分配结论看相对排序不看绝对值。
用法：.venv/bin/python engine/allocation_sim.py
输出：data/allocation_sim_YYYYMMDD.json
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path("/opt/data/fenjue")
FEE = 0.0015
CAP0 = 1_000_000.0


def curve_sim(sigs, stocks, slots=10, hold=5, cluster_k=1, pick="random", seed=0):
    """capacity_sim 的曲线版（seed 固定，返回 [[date, equity]]）。规则与 lp.capacity_sim 逐行一致。"""
    import random as _random
    dates = sorted({x for s in stocks.values() for x in s["date"]})
    didx = {c: {x: j for j, x in enumerate(s["date"])} for c, s in stocks.items()}
    rnd = _random.Random(seed)
    cash, pos, eqs = CAP0, [], []
    for k, day in enumerate(dates):
        keep = []
        for code, ei, xi, val in pos:
            j = didx[code].get(day, -1)
            if j < 0 or j < xi:
                keep.append((code, ei, xi, val))
                continue
            d = stocks[code]
            c2, o2, nn = d["c"], d["o"], d["n"]
            jj = xi
            if jj >= nn or c2[jj] <= 0 or o2[ei] <= 0:
                keep.append((code, ei, xi, val))
                continue
            r = c2[jj] / o2[ei] - 1 - FEE
            cash += val * (1 + r)   # 本金+盈亏（漏 1+ 曾致本金归零，手抄对照实验抓出）
        pos = keep
        if k > 0:
            lst = sigs.get(dates[k - 1], [])
            cands = [s for s in lst if didx[s[0]].get(day) == s[1] + 1]
            if len(lst) < cluster_k:
                cands = []
            if pick == "strength":
                cands.sort(key=lambda s: -(stocks[s[0]]["c"][s[1]] / stocks[s[0]]["o"][s[1]] - 1)
                           if stocks[s[0]]["o"][s[1]] > 0 else 1e9)
            elif pick == "deep":
                def _deep_key(s):
                    dd = stocks[s[0]]
                    ma, cc = dd["ma60"][s[1]], dd["c"][s[1]]
                    if not ma or ma <= 0 or cc <= 0:
                        return 1e9
                    return cc / ma - 1
                cands.sort(key=_deep_key)
            else:
                rnd.shuffle(cands)
            for code, i in cands[:max(0, slots - len(pos))]:
                if cash < CAP0 / slots:
                    break
                cash -= CAP0 / slots
                pos.append((code, i + 1, i + 1 + hold, CAP0 / slots))
        eqs.append([day, cash + sum(v for *_x, v in pos)])
    return eqs


def metrics(curve):
    t0, t1 = curve[0][0], curve[-1][0]
    yrs = len(curve) / 244.0
    final = curve[-1][1] / curve[0][1]
    peak, mdd = -1e18, 0
    for _, e in curve:
        peak = max(peak, e)
        mdd = min(mdd, e / peak - 1)
    return {"年化%": round(((final) ** (1 / yrs) - 1) * 100, 1),
            "期末x": round(final, 2), "回撤%": round(mdd * 100, 1)}


def main():
    stocks = lp.load_universe()
    print("stocks:", len(stocks), flush=True)
    lp.build_xsection(stocks)
    regime = lp.load_regime()

    div_curve = json.load(open(ROOT / "data/dividend_curve_cs_20260913.json"))
    sigs_panic = lp._collect_sigs(lp.REGISTRY["组合_跌停低_三连阴"], stocks)
    sigs_ml_all = lp._collect_sigs(lp.REGISTRY["组合_缺口低开_低位阳线"], stocks)
    sigs_ml = {dt: evs for dt, evs in sigs_ml_all.items() if regime.get(dt) == "主线期"}
    print("收集完毕，跑三条曲线…", flush=True)

    legs = {
        "红利锚": div_curve,
        "恐慌腿": curve_sim(sigs_panic, stocks, slots=10, hold=5, cluster_k=5, pick="deep"),
        "主线腿": curve_sim(sigs_ml, stocks, slots=10, hold=5, cluster_k=1, pick="strength"),
    }
    single = {k: metrics(v) for k, v in legs.items()}
    print(json.dumps(single, ensure_ascii=False), flush=True)

    # 对齐到公共交易日
    common = set(d for d, _ in legs["红利锚"])
    for k in ("恐慌腿", "主线腿"):
        common &= set(d for d, _ in legs[k])
    dates = sorted(common)
    norm = {}
    for k, curve in legs.items():
        m = dict(curve)
        base = m[dates[0]]
        norm[k] = {d: m[d] / base for d in dates}

    grid = {}
    for w_div in (0, 0.3, 0.5, 0.6, 0.7, 0.8, 1.0):
        for p in (0, 0.25, 0.5, 0.75, 1.0):
            w_p, w_m = (1 - w_div) * p, (1 - w_div) * (1 - p)
            curve = [[d, norm["红利锚"][d] * w_div + norm["恐慌腿"][d] * w_p + norm["主线腿"][d] * w_m]
                     for d in dates]
            key = f"红利{w_div:.0%}/恐慌{w_p:.0%}/主线{w_m:.0%}"
            grid[key] = metrics(curve)
    for k, v in grid.items():
        print(f"{k}: {v}", flush=True)

    # 基准：上证同窗
    idx = json.load(open(ROOT / "data/index_sh000001.json"))
    im = {r["date"]: r["close"] for r in idx if isinstance(r, dict) and r.get("date") in set(dates)} \
        if idx and isinstance(idx[0], dict) else {}
    bench = None
    if im:
        bcurve = [[d, im[d]] for d in dates if d in im]
        if len(bcurve) > 100:
            bench = metrics(bcurve)

    today = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y%m%d")
    fp = ROOT / f"data/allocation_sim_{today}.json"
    json.dump({"meta": {"date": today, "窗口": [dates[0], dates[-1]],
                        "口径": "三曲线归一加权；双腿cost-MTM/红利真实MTM，回撤偏浅，看相对排序"},
               "单腿": single, "上证基准": bench, "权重网格": grid},
              open(fp, "w"), ensure_ascii=False, indent=1)
    print("saved", fp, flush=True)


if __name__ == "__main__":
    main()
