#!/usr/bin/env python3
"""engine/sim_play.py — 焦点区规则历史模拟盘（2026-09-12，用户：拿数据模拟试着玩）

模拟「按面板焦点区规则玩」过去一年：
- 反转族 REVERSAL_OPEN_T1：昨跌≥3% → 次日开盘买 → T+1 尾盘卖
- 首板抢跑 FRONTRUN_FIRSTBOARD_V2：首板+梯队+市值带 → 当日收盘（打板纸面口径）→ T+1 尾盘卖
- 池毕业 WATCHPOOL_GRAD：池信号后首板 → 同上
仓位规则：每天最多 3 笔等仓（1/3 单位），优先级 池毕业>抢跑>反转，同策略按当日涨跌幅绝对值排。
费用：净 -0.15%/笔。一字跌停/涨停买不进剔除。
诚实边界：close-entry 是纸面口径（fill 率 0.3~0.6 折算见 G5）；这是规则重放不是未来保证。
"""
import json, glob, sys, datetime
from collections import defaultdict

ROOT = "/opt/data/fenjue"
D = ROOT + "/data"
WINDOW_START = "2025-09-12"
FEE = 0.0015
FILL_M60 = "--fill-m60" in sys.argv  # 实战保守版：close-entry 仅当尾盘 bar 有开缝（可排队成交）才计入

sys.path.insert(0, ROOT + "/engine")
import claims_shadow as cs  # 复用 detect/load_stocks/industry_map/stock_caps


def main():
    stocks = cs.load_stocks()
    ind = cs.industry_map()
    caps = cs.stock_caps()
    cal = [k["date"] for k in stocks["000001"]]
    dates = [d for d in cal if d >= WINDOW_START]
    dset = set(dates)

    # 预建索引
    idx = {c: {k["date"]: j for j, k in enumerate(ks)} for c, ks in stocks.items()}

    # 预计算每个交易日的行业梯队（当日涨停数 by 行业）
    ladder_by_date = {}
    for d in dates:
        lad = defaultdict(int)
        for c, ks in stocks.items():
            j = idx[c].get(d)
            if not j or j < 1 or ks[j - 1]["close"] <= 0:
                continue
            if ks[j]["close"] / ks[j - 1]["close"] - 1 >= 0.098:
                lad[ind.get(c, {}).get("industry") or "?"] += 1
        ladder_by_date[d] = lad

    trades = []  # (date, code, claim, ret)
    for d in dates:
        lad = ladder_by_date[d]
        day_sigs = []
        for c, ks in stocks.items():
            j = idx[c].get(d)
            if j is None or j + 1 >= len(ks):
                continue
            for claim, tier in cs.detect(c, ks, j, lad):
                day_sigs.append((c, j, claim, abs(ks[j]["close"] / ks[j - 1]["close"] - 1) if ks[j-1]["close"] > 0 else 0))
        pri = {"FRONTRUN_FIRSTBOARD_V2": 0, "WATCHPOOL_GRAD": 1, "REVERSAL_OPEN_T1": 2}  # 按实测 edge 排序
        day_sigs.sort(key=lambda s: (pri.get(s[2], 9), -s[3]))
        for c, j, claim, _ in day_sigs[:3]:
            ks = stocks[c]
            e = ks[j + 1]  # 入场日
            if e["close"] <= 0:
                continue
            if claim in cs.CLOSE_ENTRY_CLAIMS:
                entry = ks[j]["close"]
                if FILL_M60:
                    mf = f"{D}/m60_cache/{c}.json"
                    try:
                        bars = [r for r in json.load(open(mf)) if r["day"].startswith(d)]
                    except Exception:
                        bars = []
                    if not bars or float(bars[-1]["low"]) >= entry * 0.995:
                        continue  # 尾盘一封到底=排队买不进，保守剔除
                if e["open"] / ks[j]["close"] - 1 >= 0.095:
                    continue  # 次日一字高开无法评估，保留（打板口径已在车上）
            else:
                # 反转族：次日开盘买；一字跌停剔除（开盘≈跌停且振幅<1%）
                if ks[j]["close"] > 0 and (e["open"] / ks[j]["close"] - 1) <= -0.095 \
                        and (e["high"] - e["low"]) / e["close"] < 0.01:
                    continue
                entry = e["open"]
                if entry <= 0:
                    continue
            ret = e["close"] / entry - 1 - FEE
            trades.append((d, c, claim, ret))

    # 日组合收益（当天开仓的 1/3 等仓，其余现金 0）
    by_day = defaultdict(list)
    for t in trades:
        by_day[t[0]].append(t[3])
    eq, curve = 1.0, []
    for d in dates:
        rets = by_day.get(d, [])
        eq *= 1 + sum(rets) / 3
        curve.append((d, eq))
    peak, mdd = 1.0, 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1)

    ks0 = stocks["000001"]
    i0 = next(j for j, k in enumerate(ks0) if k["date"] == dates[0])
    i1 = next(j for j, k in enumerate(ks0) if k["date"] == dates[-1])
    bench = ks0[i1]["close"] / ks0[i0]["close"] - 1

    by_claim = defaultdict(list)
    for t in trades:
        by_claim[t[2]].append(t[3])

    out = {
        "window": [dates[0], dates[-1]], "trading_days": len(dates),
        "trades": len(trades), "trade_win%": round(sum(1 for t in trades if t[3] > 0) / len(trades) * 100, 1) if trades else 0,
        "trade_avg%": round(sum(t[3] for t in trades) / len(trades) * 100, 2) if trades else 0,
        "sim_equity": round(eq, 3), "sim_return%": round((eq - 1) * 100, 1),
        "max_drawdown%": round(mdd * 100, 1),
        "bench_index%": round(bench * 100, 1),
        "by_claim": {k: {"n": len(v), "win%": round(sum(1 for x in v if x > 0) / len(v) * 100, 1),
                          "avg%": round(sum(v) / len(v) * 100, 2)} for k, v in by_claim.items()},
        "curve_tail": curve[-5:],
    }
    json.dump(out, open(D + "/sim_play_20260912.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
