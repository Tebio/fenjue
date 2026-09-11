#!/usr/bin/env python3
"""engine/strategy_zoo.py — A股策略族全量对照联赛（2026-09-11 用户批评后立项）

同一口径跑所有流传策略族，回答「哪个胜率最大最稳」：
  信号日 t 收盘确认 → t+1 开盘买入（无未来函数）→ 次日尾盘 / T+5 尾盘卖出
  净口径 -0.15% 双边；随机对照 2 万组；退市股缺失为全仓已知限制。
数据：big_kcache 前复权（3154 只 × 2019-05~2026-09）。
"""
import json, glob, random, statistics as st
from pathlib import Path

KC = Path("/opt/data/fenjue/data/big_kcache")
FEE = 0.0015
OUT = Path("/opt/data/fenjue/data/strategy_zoo_20260911.json")
random.seed(42)

stocks = {}
for fp in glob.glob(str(KC / "*.json")):
    ks = json.loads(open(fp).read())
    if len(ks) >= 300:
        stocks[Path(fp).stem] = ks
print("universe:", len(stocks))


def S(rets):
    if len(rets) < 30:
        return None
    n = len(rets)
    return {"n": n, "win%": round(sum(1 for r in rets if r > 0) / n * 100, 1),
            "mean%": round(st.mean(rets) * 100, 2), "med%": round(st.median(rets) * 100, 2)}


def collect(cond, min_i=65, tail=6):
    """cond(ks,c,h,v,i)->True 时，open[t+1] 买入；返回 (T+1尾盘收益, T+5尾盘收益)"""
    r1, r5 = [], []
    for ks in stocks.values():
        c = [k["close"] for k in ks]
        h = [k["high"] for k in ks]
        v = [k["volume"] for k in ks]
        o = [k["open"] for k in ks]
        for i in range(min_i, len(ks) - tail - 1):
            if cond(ks, c, h, v, o, i):
                entry = o[i + 1]
                if entry <= 0:
                    continue
                r1.append(c[i + 1] / entry - 1 - FEE)
                r5.append(c[i + 5] / entry - 1 - FEE)
    return r1, r5


def chg(c, i):
    return c[i] / c[i - 1] - 1


STRATS = {
    # 已验证基准
    "S1 反转族(昨跌≥3%)": lambda ks, c, h, v, o, i: chg(c, i) <= -0.03,
    # 打板族
    "S2 涨停收盘打板(尾盘挤进)": lambda ks, c, h, v, o, i: chg(c, i) >= 0.095,
    "S3 首板次日开盘追": lambda ks, c, h, v, o, i: chg(c, i - 1) >= 0.095 and chg(c, i - 2) < 0.095 if i >= 2 else False,
    "S4 二连板次日追": lambda ks, c, h, v, o, i: (chg(c, i - 1) >= 0.095 and chg(c, i - 2) >= 0.095) if i >= 2 else False,
    # 趋势族
    "S5 20日新高突破(海龟短)": lambda ks, c, h, v, o, i: c[i] > max(c[i - 20:i]) and chg(c, i) > 0.01,
    "S6 55日新高突破(海龟长)": lambda ks, c, h, v, o, i: c[i] > max(c[i - 55:i]) and chg(c, i) > 0.01,
    "S7 MA20上穿": lambda ks, c, h, v, o, i: c[i - 1] < sum(c[i - 21:i - 1]) / 20 and c[i] > sum(c[i - 20:i]) / 20 if i >= 21 else False,
    # 反转/超跌族
    "S8 超跌20%(60日内)": lambda ks, c, h, v, o, i: c[i] / max(c[i - 60:i]) - 1 <= -0.20 and chg(c, i) > 0,
    "S9 三连阴买": lambda ks, c, h, v, o, i: chg(c, i) < 0 and chg(c, i - 1) < 0 and chg(c, i - 2) < 0 if i >= 2 else False,
    "S10 跌停次日接": lambda ks, c, h, v, o, i: chg(c, i) <= -0.095,
    # 题材形态族
    "S11 缩量横盘放量突破(再升型)": lambda ks, c, h, v, o, i: (
        (max(h[i - 20:i]) - min(c[i - 20:i])) / min(c[i - 20:i]) < 0.12
        and v[i] > sum(v[i - 20:i]) / 20 * 2.5 and chg(c, i) > 0.03) if i >= 20 else False,
    "S12 触板未封(炸板)次日": lambda ks, c, h, v, o, i: h[i] / c[i - 1] - 1 >= 0.095 and chg(c, i) < 0.09,
}

R = {}
for name, cond in STRATS.items():
    for y0, y1, seg in [("2019-01-01", "2026-09-04", "全段"), ("2019-01-01", "2022-12-31", "前半"), ("2023-01-01", "2026-09-04", "后半")]:
        def c2(ks, c, h, v, o, i, _c=cond, _y0=y0, _y1=y1):
            return _y0 <= ks[i]["date"] <= _y1 and _c(ks, c, h, v, o, i)
        r1, r5 = collect(c2)
        R.setdefault(name, {})[seg] = {"T+1尾盘": S(r1), "T+5尾盘": S(r5)}
    print(name, "done")

# 随机对照
keys = list(stocks.keys())
pool = []
while len(pool) < 20000:
    ks = stocks[random.choice(keys)]
    i = random.randint(66, len(ks) - 8)
    pool.append((ks, i))
R["随机对照"] = {"全段": {
    "T+1尾盘": S([ks[i + 1]["close"] / ks[i + 1]["open"] - 1 - FEE for ks, i in pool]),
    "T+5尾盘": S([ks[i + 5]["close"] / ks[i + 1]["open"] - 1 - FEE for ks, i in pool])}}

OUT.write_text(json.dumps(R, ensure_ascii=False, indent=1))
print("saved", OUT)
