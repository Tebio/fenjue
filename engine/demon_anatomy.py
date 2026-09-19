#!/usr/bin/env python3
"""engine/demon_anatomy.py — 妖股解剖（2026-09-19 深夜，用户过夜立项）。

任务：找出历史大涨票（百合花式妖股），解剖「启动前形态 + 启动后惯性 + 市场环境」，
反推策略/叠加/细化。

样本与防未来函数设计（PIT 纪律，先声明后跑数）：
  事件 = 首板日 j（复用 doubler.first_board_events：60 日无板后首个 ≥+9.8% 涨停）。
  标签（这是目标不是特征，允许用未来）：妖 = max(c[j+1..j+25]) / c[j] ≥ 1.8（25 日内曾翻倍-20%）。
  特征（全部 ≤ 首板日收盘可知，禁用 j 之后任何数据）：
    启动前形态：距60日高、距MA60、PIT市值、平台振幅20、板日量比(对前5日)、连跌天数、TD9、PE/ST
    市场环境：regime、当日全市场跌停数(_XLDC)、同行业当日涨停数(_XLADDER 梯队)、上证20日涨幅
    板日结构：一字板(开=低=收=高)、板日换手率(量/前20日均量)
  启动后惯性（解剖用，不作特征）：连板数、断板日表现、二波率。
口径边界（诚实声明）：
  ① 只覆盖「涨停启动」的妖股（百合花 5/19 即首板启动）；非板启动的妖股在宇宙外。
  ② 与 #38 的关系：启动日**前夜**无特征已被证——本研究不问「明天谁启动」，
     只问「今天首板了，它是妖的概率多大、什么条件放大这概率」（晋级段问题）。
  ③ 退市股在库（big_kcache 含 186 只），幸存者偏差已控。
  ④ 百合花 603823 作校准案例单独打印。
用法：.venv/bin/python engine/demon_anatomy.py
输出：data/demon_anatomy_YYYYMMDD.json
"""
import json
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp
from doubler import first_board_events

ROOT = Path("/opt/data/fenjue")
DEMON_RUN = 1.8       # 妖标签：25日内曾涨至1.8倍
FWD = 25


def pre_feats(d, j):
    """首板日 j 收盘可知的全部特征（禁越界）。"""
    c, o, h, l, v, ma = d["c"], d["o"], d["h"], d["l"], d["v"], d["ma60"]
    hi60 = max(h[max(0, j - 60):j])
    lo20, hi20 = min(l[max(0, j - 20):j]), max(h[max(0, j - 20):j])
    base5 = [v[k] for k in range(max(0, j - 5), j) if v[k] > 0]
    base20 = [v[k] for k in range(max(0, j - 20), j) if v[k] > 0]
    nd = 0
    k = j - 1
    while k > 0 and c[k] < c[k - 1]:
        nd += 1
        k -= 1
    return {
        "距60高%": round((c[j - 1] / hi60 - 1) * 100, 1) if hi60 > 0 and j >= 1 else None,  # 前收盘口径
        "距MA60%": round((c[j] / ma[j] - 1) * 100, 1) if ma[j] else None,
        "平台振幅20%": round((hi20 / lo20 - 1) * 100, 1) if lo20 > 0 else None,
        "板日量比": round(v[j] / (sum(base5) / len(base5)), 2) if base5 and v[j] > 0 else None,
        "板日量比20": round(v[j] / (sum(base20) / len(base20)), 2) if base20 and v[j] > 0 else None,
        "连跌天数": nd,
        "TD9": lp._td9buy(d, j - 1) if j >= 13 else False,   # 前夜口径
        "一字板": bool(o[j] == l[j] == c[j] == h[j]),
    }


def main():
    stocks = lp.load_universe()
    print("stocks:", len(stocks), flush=True)
    lp.build_xsection(stocks)
    fund, capm, ladder, ldc, ind = lp._XFUND, lp._XCAP, lp._XLADDER, lp._XLDC, (lp._IND or {})
    regime = lp.load_regime()
    idx = json.load(open(ROOT / "data/index_sh000001.json"))
    idxc = {k["date"]: k["close"] for k in idx}
    idxd = [k["date"] for k in idx]

    def idx_ret20(dt):
        try:
            k = idxd.index(dt)
            if k >= 20 and idxc.get(idx[k - 20]):
                return idxc[dt] / idxc[idxd[k - 20]] - 1
        except Exception:
            pass
        return None

    events = []
    for code, d in stocks.items():
        ks = [{"close": c, "open": o} for c, o in zip(d["c"], d["o"])]
        for j in first_board_events(ks):
            if j + 1 >= d["n"]:
                continue
            dt = d["date"][j]
            c = d["c"]
            fwd_max = max(c[j + 1:min(j + 1 + FWD, d["n"])], default=0)
            demon = fwd_max / c[j] >= DEMON_RUN if c[j] > 0 else False
            # 连板数（启动后惯性解剖）
            chain = 1
            while j + chain < d["n"] and c[j + chain - 1] > 0 \
                    and c[j + chain] / c[j + chain - 1] - 1 >= 0.098:
                chain += 1
            fu = lp.fund_at(code, dt)
            events.append({
                "code": code, "date": dt, "妖": demon,
                "fwd_max%": round((fwd_max / c[j] - 1) * 100, 1) if c[j] > 0 else None,
                "连板": chain,
                "T1开收%": round((c[j + 1] / d["o"][j + 1] - 1) * 100, 1) if d["o"][j + 1] > 0 else None,
                "f": pre_feats(d, j),
                "市值": lp.cap_at_date(capm, code, dt),
                "pe": fu[0] if fu else None, "st": fu[1] if fu else None,
                "板块梯队": (ladder.get(dt, {}).get(ind.get(code)) if ladder else None),
                "市场跌停": ldc.get(dt, 0) if ldc else 0,
                "regime": regime.get(dt, "?"),
                "上证20日%": round(idx_ret20(dt) * 100, 1) if idx_ret20(dt) is not None else None,
            })
    n_dem = sum(1 for e in events if e["妖"])
    print(f"首板事件 {len(events)}，妖股 {n_dem}（基率 {100*n_dem/len(events):.2f}%）", flush=True)

    def lift(sel, label):
        sub = [e for e in events if sel(e)]
        if len(sub) < 100:
            return None
        nd = sum(1 for e in sub if e["妖"])
        base = n_dem / len(events)
        p = nd / len(sub)
        chains = [e["连板"] for e in sub]
        return {"n": len(sub), "妖率%": round(100 * p, 2), "lift": round(p / base, 2),
                "均连板": round(st.mean(chains), 2)}

    out = {"基率": {"n": len(events), "妖率%": round(100 * n_dem / len(events), 2)}}
    # —— 启动前形态 ——
    for label, sel in [
        ("距60高≤-30%", lambda e: (e["f"]["距60高%"] or 0) <= -30),
        ("距60高 -30~-15%", lambda e: -30 < (e["f"]["距60高%"] or 0) <= -15),
        ("距60高 -15~0%", lambda e: -15 < (e["f"]["距60高%"] or 0) <= 0),
        ("距60高>0%(新高区)", lambda e: (e["f"]["距60高%"] or -1) > 0),
        ("MA60下", lambda e: (e["f"]["距MA60%"] or 1) <= 0),
        ("平台振幅<25%(缩量平台)", lambda e: (e["f"]["平台振幅20%"] or 99) < 25),
        ("平台振幅≥50%", lambda e: (e["f"]["平台振幅20%"] or 0) >= 50),
        ("板日量比≥3(放量板)", lambda e: (e["f"]["板日量比"] or 0) >= 3),
        ("板日量比<1.5(缩量板)", lambda e: 0 < (e["f"]["板日量比"] or 9) < 1.5),
        ("连跌≥3日启动", lambda e: e["f"]["连跌天数"] >= 3),
        ("一字板", lambda e: e["f"]["一字板"]),
        ("市值<50亿", lambda e: e["市值"] is not None and e["市值"] < 50),
        ("市值50-150亿", lambda e: e["市值"] is not None and 50 <= e["市值"] < 150),
        ("市值≥400亿", lambda e: e["市值"] is not None and e["市值"] >= 400),
        ("亏损或ST", lambda e: (e["pe"] is not None and e["pe"] <= 0) or e["st"]),
    ]:
        r = lift(sel, label)
        if r:
            out[f"形态_{label}"] = r
    # —— 市场环境 ——
    for label, sel in [
        ("梯队≥3(板块共振)", lambda e: (e["板块梯队"] or 0) >= 3),
        ("梯队≥5", lambda e: (e["板块梯队"] or 0) >= 5),
        ("梯队0-1(孤板)", lambda e: (e["板块梯队"] or 0) <= 1),
        ("市场跌停≥20", lambda e: e["市场跌停"] >= 20),
        ("市场跌停<5", lambda e: e["市场跌停"] < 5),
        ("上证20日>+5%(强市)", lambda e: (e["上证20日%"] or -99) > 5),
        ("上证20日<-5%(弱市)", lambda e: (e["上证20日%"] or 99) < -5),
        ("主线期", lambda e: e["regime"] == "主线期"),
        ("妖股期", lambda e: e["regime"] == "妖股期"),
        ("恐慌期", lambda e: e["regime"] == "恐慌期"),
        ("平淡期", lambda e: e["regime"] == "平淡期"),
    ]:
        r = lift(sel, label)
        if r:
            out[f"环境_{label}"] = r
    # —— 合成（高 lift 叠加，事后必须过闸门）——
    for label, sel in [
        ("梯队≥3+市值50-150", lambda e: (e["板块梯队"] or 0) >= 3 and e["市值"] is not None and 50 <= e["市值"] < 150),
        ("梯队≥3+放量板", lambda e: (e["板块梯队"] or 0) >= 3 and (e["f"]["板日量比"] or 0) >= 3),
        ("梯队≥3+非一字+市值20-400", lambda e: (e["板块梯队"] or 0) >= 3 and not e["f"]["一字板"] and e["市值"] is not None and 20 <= e["市值"] <= 400),
        ("主线期+梯队≥3", lambda e: e["regime"] == "主线期" and (e["板块梯队"] or 0) >= 3),
        ("妖股期+梯队≥3", lambda e: e["regime"] == "妖股期" and (e["板块梯队"] or 0) >= 3),
    ]:
        r = lift(sel, label)
        if r:
            out[f"合成_{label}"] = r

    # —— 妖股惯性解剖（启动后）——
    demons = [e for e in events if e["妖"]]
    if demons:
        out["妖股解剖"] = {
            "连板分布": {str(k): sum(1 for e in demons if e["连板"] == k) for k in range(1, 8)},
            "均连板": round(st.mean([e["连板"] for e in demons]), 2),
            "一字板占比%": round(100 * sum(1 for e in demons if e["f"]["一字板"]) / len(demons), 1),
            "梯队≥3占比%": round(100 * sum(1 for e in demons if (e["板块梯队"] or 0) >= 3) / len(demons), 1),
            "regime分布": {r: sum(1 for e in demons if e["regime"] == r) for r in ("主线期", "妖股期", "恐慌期", "平淡期")},
            "市值中位亿": round(st.median([e["市值"] for e in demons if e["市值"]]), 1),
            "距60高中位%": round(st.median([e["f"]["距60高%"] for e in demons if e["f"]["距60高%"] is not None]), 1),
        }
    # —— 百合花校准 ——
    bh = [e for e in events if e["code"] == "603823" and e["date"] >= "2026-01-01"]
    out["百合花校准"] = bh

    today = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y%m%d")
    fp = ROOT / f"data/demon_anatomy_{today}.json"
    json.dump({"meta": {"date": today, "妖定义": f"25日内曾涨至{DEMON_RUN}x", "首板口径": "60日无板后首个≥+9.8%",
                        "事件数": len(events), "妖股数": n_dem},
               "结果": out}, open(fp, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1), flush=True)
    print("saved", fp, flush=True)


if __name__ == "__main__":
    main()
