#!/usr/bin/env python3
"""engine/monday_combo.py — BACKLOG#9 周一效应 × 组合交互（2026-09-19 深夜）。

已有证据：周一效应单因子 +0.169%/60.8%（factor_research，L2+ 黑名单外的存活因子）；
各组合（跌停低系/缺口低系/触板低系/B5/frontrun低位）全部按「次日开盘买」口径注册。
问题：入场日是周一 vs 其他 weekday，组合表现是否显著不同？若周一显著强，
组合可加「周一加档」调制；若弱，则周一信号降档——两条都是可执行结论。
口径：事件研究，净 0.15%，剔次日一字跌停开盘；入场日=信号日次日（与注册口径一致）；
对照=同组合非周一入场；披露全部 5 个 weekday × 全 horizon（T+1/2/3/5/10/20，钦定汇报纪律）。
用法：.venv/bin/python engine/monday_combo.py [信号名 …]（默认=注册表里的候选组合全集）
输出：data/monday_combo_YYYYMMDD.json
"""
import json
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path("/opt/data/fenjue")
FEE = 0.0015
HORIZONS = [1, 2, 3, 5, 10, 20]
# 默认受试=注册表里已过的组合类主张（单底座/死信号不重复测——底座裸跑的周一交互已含在组合里）
DEFAULT = ["组合_跌停低_长周期_超跌20", "组合_跌停低_三连阴", "组合_跌停低_缩量_剔亏ST",
           "组合_跌停低_输家_超跌20_剔亏ST", "组合_缺口低开_低位_剔亏ST", "组合_缺口低开_低位阳线",
           "组合_触板未封_低位", "banlu_b5_MA60上", "frontrun_v2_低位追", "跌停接_MA60下",
           "跌停接_MA60上_2月", "组合_跌停低_TD9买入滤"]
WEEK = ["一", "二", "三", "四", "五"]


def main():
    names = sys.argv[1:] or DEFAULT
    stocks = lp.load_universe()
    print("stocks:", len(stocks), flush=True)
    lp.build_xsection(stocks)
    hi = max(HORIZONS) + 1

    out = {}
    for nm in names:
        det = lp.REGISTRY.get(nm)
        if det is None:
            print(f"!! {nm} 不在 REGISTRY，跳过", flush=True)
            continue
        # 入场日(信号日次日) weekday -> horizon -> returns
        cells = defaultdict(lambda: defaultdict(list))
        for code, d in stocks.items():
            n = d["n"]
            o, c = d["o"], d["c"]
            for i in range(lp.START, n - hi - 1):
                if o[i + 1] <= 0:
                    continue
                try:
                    if not det(d, i):
                        continue
                except Exception:
                    continue
                ei = i + 1
                if o[ei] <= c[i] * 0.905:   # 一字跌停开盘买不到
                    continue
                wd = datetime.strptime(d["date"][ei], "%Y-%m-%d").weekday()
                if wd > 4:
                    continue
                for h in HORIZONS:
                    if ei + h < n:
                        cells[wd][h].append(c[ei + h] / o[ei] - 1 - FEE)
        res = {}
        for wd in range(5):
            day = {}
            for h in HORIZONS:
                rs = cells[wd][h]
                if len(rs) >= 30:
                    wins = [r for r in rs if r > 0]
                    losses = [r for r in rs if r <= 0]
                    odds = st.mean(wins) / abs(st.mean(losses)) if wins and losses else None
                    day[f"T+{h}"] = {"胜率%": round(100 * len(wins) / len(rs), 1),
                                     "均值%": round(100 * st.mean(rs), 2),
                                     "赔率": round(odds, 2) if odds else None, "n": len(rs)}
            res[f"周{WEEK[wd]}"] = day
        # 周一 vs 其余 合并对照（T+5 主口径）
        mon = cells[0][5]
        oth = [r for wd in range(1, 5) for r in cells[wd][5]]
        res["周一_vs_其余_T+5"] = {
            "周一": {"n": len(mon), "均值%": round(100 * st.mean(mon), 2)} if len(mon) >= 10 else None,
            "其余": {"n": len(oth), "均值%": round(100 * st.mean(oth), 2)} if len(oth) >= 30 else None,
            "差pp": round(100 * (st.mean(mon) - st.mean(oth)), 2) if len(mon) >= 10 and len(oth) >= 30 else None}
        out[nm] = res
        print(f"{nm}: 周一vs其余 T+5 差 {res['周一_vs_其余_T+5']['差pp']}pp", flush=True)

    today = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y%m%d")
    fp = ROOT / f"data/monday_combo_{today}.json"
    json.dump({"meta": {"date": today, "口径": "次日开盘买/剔一字/净0.15%/入场日weekday"}, "signals": out},
              open(fp, "w"), ensure_ascii=False, indent=1)
    print("saved", fp, flush=True)


if __name__ == "__main__":
    main()
