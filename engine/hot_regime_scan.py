#!/usr/bin/env python3
"""engine/hot_regime_scan.py — 非恐慌期赚钱信号扫描（2026-09-12 用户质问立项）

问题：恐慌期只占15.9%的日子，体系的存活edge全是恐慌反转族——剩下84%的日子喝西北风？
本脚本把热钱期候选信号 × 四态regime 过统一证伪口径：
  首板次日追 / 二连板晋级追 / 强势回调(MA60上跌≥3%) / 20日新高突破 / 反转族对照
口径：信号日i收盘确认 → i+1开盘买 → T+1/T+5尾盘卖，净-0.15%。
每格附同日全宇宙超额（日历时间口径，防"妖股期全市场都涨"假edge）。
筛选：n≥200 且 双时段(2019-22/2023-26)同号 才进候选名单。
"""
import json, glob, math, statistics as st
from pathlib import Path

KC = Path("/opt/data/fenjue/data/big_kcache")
TL = Path("/opt/data/fenjue/data/regime_timeline_hcap.json")
FEE = 0.0015
OUT = Path("/opt/data/fenjue/data/hot_regime_scan_20260912.json")

stocks = {}
for fp in glob.glob(str(KC / "*.json")):
    ks = json.loads(open(fp).read())
    if len(ks) >= 300:
        stocks[Path(fp).stem] = ks
print("universe:", len(stocks), flush=True)
regime = {r["date"]: r["regime"] for r in json.loads(TL.read_text())}
REGIMES = ["主线期", "妖股期", "恐慌期", "平淡期"]


def limit_th(code):
    return 0.195 if code.startswith(("30", "68")) else 0.097


def ma60(c, i):
    return sum(c[i - 60:i]) / 60


# 预计算日K特征
feat = {}
for code, ks in stocks.items():
    c = [k["close"] for k in ks]
    o = [k["open"] for k in ks]
    h = [k["high"] for k in ks]
    d = [k["date"] for k in ks]
    th = limit_th(code)
    lu = [c[i] / c[i - 1] - 1 >= th if c[i - 1] > 0 else False for i in range(len(c))]
    hi20 = [max(h[max(0, i - 20):i]) if i >= 1 else None for i in range(len(c))]
    feat[code] = {"c": c, "o": o, "d": d, "lu": lu, "hi20": hi20, "th": th}
print("features ready", flush=True)

# 同日全宇宙均值（T+1/T+5 日历时间基准）
uni1, uni5 = {}, {}
for code, f in feat.items():
    c, o, d = f["c"], f["o"], f["d"]
    for i in range(65, len(c) - 6):
        if o[i + 1] > 0:
            uni1.setdefault(d[i + 1], []).append(c[i + 1] / o[i + 1] - 1 - FEE)
            uni5.setdefault(d[i + 1], []).append(c[i + 5] / o[i + 1] - 1 - FEE)
uni1m = {k: st.mean(v) for k, v in uni1.items()}
uni5m = {k: st.mean(v) for k, v in uni5.items()}
print("universe baselines ready", flush=True)

SIGS = {
    "首板次日": lambda f, i: f["lu"][i] and not f["lu"][i - 1] and not f["lu"][i - 2],
    "二连板晋级": lambda f, i: f["lu"][i] and f["lu"][i - 1] and not f["lu"][i - 2],
    "强势回调(MA60上-3%)": lambda f, i: f["c"][i] > ma60(f["c"], i) and f["c"][i] / f["c"][i - 1] - 1 <= -0.03,
    "新高突破(20日+5%)": lambda f, i: f["hi20"][i] is not None and f["c"][i] > f["hi20"][i]
        and f["c"][i] / f["c"][i - 1] - 1 >= 0.05,
    "反转族对照(任意-3%)": lambda f, i: f["c"][i] / f["c"][i - 1] - 1 <= -0.03,
}

R = {}
for sname, pred in SIGS.items():
    for rg in REGIMES + ["全regime"]:
        for hz, unim in ((1, uni1m), (5, uni5m)):
            rs, xs = [], []
            early, late = [], []  # ≤2022-12-31 / ≥2023-01-01（信号日切）
            for code, f in feat.items():
                c, o, d = f["c"], f["o"], f["d"]
                for i in range(66, len(c) - 6):
                    if o[i + 1] <= 0:
                        continue
                    if rg != "全regime" and regime.get(d[i]) != rg:
                        continue
                    if not pred(f, i):
                        continue
                    r = c[i + hz] / o[i + 1] - 1 - FEE
                    rs.append(r)
                    ex = unim.get(d[i + 1])
                    if ex is not None:
                        xs.append(r - ex)
                    (early if d[i] <= "2022-12-31" else late).append(r)
            if len(rs) < 200:
                continue
            cell = {"n": len(rs), "win%": round(100 * sum(r > 0 for r in rs) / len(rs), 1),
                    "net%": round(100 * st.mean(rs), 2),
                    "同日超额%": round(100 * st.mean(xs), 3) if xs else None,
                    "早段net%": round(100 * st.mean(early), 2) if len(early) >= 100 else None,
                    "晚段net%": round(100 * st.mean(late), 2) if len(late) >= 100 else None}
            R.setdefault(sname, {})[f"{rg} T+{hz}"] = cell
    print(sname, "done", flush=True)

OUT.write_text(json.dumps(R, ensure_ascii=False, indent=1))
print("saved", OUT)
