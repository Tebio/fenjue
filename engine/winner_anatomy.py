#!/usr/bin/env python3
"""engine/winner_anatomy.py — 大赢票解剖（2026-09-19 用户立项：抓+19%不误杀、排负收益票）。

问题：反转族宽清单（9/18 起红线停推）里，金健米业 9/16（T+1 +19.2%）与声迅股份 9/14（T+1 -7.4%）
同在清单里。大赢/大输有没有**信号日收盘前可算**的共性？五族假设一次全测：
  H1 龙头效应：前 10/20 日有涨停（板链史）、距最近板天数
  H2 板块共振：当日行业涨停数（_XLADDER 梯队）
  H3 技术面：距MA60深度、量比、TD9、三连阴、距60日高
  H4 基本面：亏损/ST（fund_cache）、市值带
  H5 情绪：regime、当日全市场跌停数（_XLDC 恐慌强度）
设计纪律（防自欺）：
  ① 特征全部 PIT（信号日收盘可知）；② 看全量不看精选——过滤器必须同时
     提升大赢率(T+1≥+5%)、**降低大输率(T+1≤-3%)**、且不毁掉均值才算数；
  ③ 幸存组合走 submit 七闸门，禁一次性结论；④ 全 horizon 曲线（钦定汇报纪律）。
用法：.venv/bin/python engine/winner_anatomy.py
输出：data/winner_anatomy_YYYYMMDD.json
"""
import json
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fjcore import Universe, forward, REGISTRY, START, td9buy, three_down  # 2026-09-20 绞杀者收编（fwd 与 fjcore.forward 逐行一致，直接换）

ROOT = Path("/opt/data/fenjue")
FEE = 0.0015
HORIZONS = [1, 2, 3, 5, 10, 20]


def feats(d, i):
    c, o, h_, v, ma = d["c"], d["o"], d["h"], d["v"], d["ma60"]
    # 板链史（H1）
    pb10 = pb20 = 0
    last_b = None
    for j in range(max(1, i - 20), i):
        if c[j - 1] > 0 and c[j] / c[j - 1] - 1 >= 0.098:
            pb20 += 1
            if j >= i - 10:
                pb10 += 1
            last_b = i - j
    # 量比
    base = [v[k] for k in range(i - 5, i) if v[k] > 0]
    vr = v[i] / (sum(base) / len(base)) if base and v[i] > 0 else 0
    hi60 = max(h_[max(0, i - 60):i + 1])
    return {"前10日板数": pb10, "前20日板数": pb20, "距最近板": last_b if last_b is not None else 99,
            "量比": vr, "距MA60": (c[i] / ma[i] - 1) if ma[i] else None,
            "距60高": c[i] / hi60 - 1 if hi60 > 0 else None,
            "TD9": td9buy(d, i), "三连阴": three_down(d, i)}


# fwd 已收编：fjcore.forward（逐行一致：次日开盘/0.905剔一字跌停/净0.15%）


def main():
    u = Universe().load()
    stocks = u.stocks
    print("stocks:", len(stocks), flush=True)
    ladder, ldc = u.ladder, u.ldc
    ind = u.ind           # code -> industry（str）
    regime = u.regime
    det = REGISTRY["反转族_T-1大跌"]

    events = []  # (code, i, feats)
    for code, d in stocks.items():
        n = d["n"]
        for i in range(START, n - 22):
            if d["o"][i + 1] <= 0:
                continue
            try:
                if det(d, i):
                    events.append((code, i, feats(d, i)))
            except Exception:
                pass
    print(f"反转族事件 {len(events)}", flush=True)

    # 每个事件的 T+1 / T+5
    recs = []
    for code, i, f in events:
        d = stocks[code]
        r1, r5 = forward(d, i, 1), forward(d, i, 5)
        if r1 is None:
            continue
        fu = u.fund_at(code, d["date"][i])
        recs.append({"code": code, "date": d["date"][i], "f": f, "r1": r1, "r5": r5,
                     "梯队": (ladder.get(d["date"][i], {}).get(ind.get(code)) if ladder else None),
                     "恐慌": ldc.get(d["date"][i], 0) if ldc else 0,
                     "regime": regime.get(d["date"][i], "?"),
                     "pe": fu[0] if fu else None, "st": fu[1] if fu else None,
                     "cap": u.cap_at(code, d["date"][i])})

    def anat(rs, label):
        if len(rs) < 50:
            return None
        r1 = [x["r1"] for x in rs]
        r5 = [x["r5"] for x in rs if x["r5"] is not None]
        big = sum(1 for x in r1 if x >= 0.05)
        bad = sum(1 for x in r1 if x <= -0.03)
        wins = [x for x in r1 if x > 0]
        return {"n": len(rs), "T1均值%": round(100 * st.mean(r1), 2),
                "大赢率%": round(100 * big / len(r1), 1), "大输率%": round(100 * bad / len(r1), 1),
                "胜率%": round(100 * len(wins) / len(r1), 1),
                "T5均值%": round(100 * st.mean(r5), 2) if r5 else None}

    out = {"基线_全部": anat(recs, "全部")}
    # H1 龙头/板链
    for name, sel in [("前10日有板", lambda x: x["f"]["前10日板数"] >= 1),
                      ("前20日有板", lambda x: x["f"]["前20日板数"] >= 1),
                      ("前10日≥2板(链)", lambda x: x["f"]["前10日板数"] >= 2),
                      ("距板≤3日", lambda x: x["f"]["距最近板"] <= 3),
                      ("距板4-10日", lambda x: 4 <= x["f"]["距最近板"] <= 10),
                      ("无板链史", lambda x: x["f"]["前20日板数"] == 0)]:
        out[f"H1_{name}"] = anat([x for x in recs if sel(x)], name)
    # H2 板块梯队
    for name, lo, hi in [("梯队0-1", 0, 1), ("梯队2", 2, 2), ("梯队≥3", 3, 99)]:
        out[f"H2_梯队{lo}-{hi if hi < 99 else '∞'}"] = anat(
            [x for x in recs if x["梯队"] is not None and lo <= x["梯队"] <= hi], name)
    # H3 技术面
    for name, sel in [("缩量<0.8", lambda x: x["f"]["量比"] < 0.8),
                      ("放量≥1.5", lambda x: x["f"]["量比"] >= 1.5),
                      ("TD9", lambda x: x["f"]["TD9"]),
                      ("三连阴", lambda x: x["f"]["三连阴"]),
                      ("距60高≤-30%", lambda x: (x["f"]["距60高"] or 0) <= -0.30),
                      ("距60高>-15%(贴高)", lambda x: (x["f"]["距60高"] or -1) > -0.15)]:
        out[f"H3_{name}"] = anat([x for x in recs if sel(x)], name)
    # H4 基本面
    for name, sel in [("亏损或ST", lambda x: (x["pe"] is not None and x["pe"] <= 0) or x["st"]),
                      ("非亏非ST", lambda x: not ((x["pe"] is not None and x["pe"] <= 0) or x["st"])),
                      ("市值<50亿", lambda x: x["cap"] is not None and x["cap"] < 50),
                      ("市值≥200亿", lambda x: x["cap"] is not None and x["cap"] >= 200)]:
        out[f"H4_{name}"] = anat([x for x in recs if sel(x)], name)
    # H5 情绪
    for name, sel in [("跌停潮≥50", lambda x: x["恐慌"] >= 50),
                      ("跌停潮<20", lambda x: x["恐慌"] < 20),
                      ("恐慌期", lambda x: x["regime"] == "恐慌期"),
                      ("妖股期", lambda x: x["regime"] == "妖股期")]:
        out[f"H5_{name}"] = anat([x for x in recs if sel(x)], name)

    print(json.dumps(out, ensure_ascii=False, indent=1), flush=True)

    # 合成筛选：大赢率显著升 + 大输率不升 + 均值不毁 的组合
    base = out["基线_全部"]
    print("\n== 合成筛选（大赢率↑且大输率↓且均值≥基线）==")
    combos = {
        "前10日有板+梯队≥3": lambda x: x["f"]["前10日板数"] >= 1 and (x["梯队"] or 0) >= 3,
        "前10日有板+缩量": lambda x: x["f"]["前10日板数"] >= 1 and x["f"]["量比"] < 0.8,
        "前10日有板+非亏ST": lambda x: x["f"]["前10日板数"] >= 1 and not ((x["pe"] is not None and x["pe"] <= 0) or x["st"]),
        "距板≤3+梯队≥3": lambda x: x["f"]["距最近板"] <= 3 and (x["梯队"] or 0) >= 3,
        "前10日有板+梯队≥3+非亏ST": lambda x: x["f"]["前10日板数"] >= 1 and (x["梯队"] or 0) >= 3 and not ((x["pe"] is not None and x["pe"] <= 0) or x["st"]),
    }
    res = {}
    for nm, sel in combos.items():
        a = anat([x for x in recs if sel(x)], nm)
        res[nm] = a
        if a:
            print(f"  {nm}: {a}")
    out["合成"] = res

    today = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y%m%d")
    fp = ROOT / f"data/winner_anatomy_{today}.json"
    json.dump({"meta": {"date": today, "事件": len(recs), "口径": "反转族next_open/剔一字/净0.15%"},
               "解剖": out}, open(fp, "w"), ensure_ascii=False, indent=1)
    print("saved", fp, flush=True)


if __name__ == "__main__":
    main()
