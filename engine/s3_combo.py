#!/usr/bin/env python3
"""engine/s3_combo.py — S3 组合层首测（law-program S3 冲刺）

原始设想"反转族×形态×位置"因形态族 DEAD（self-audit-20260912）重构为：
存活主张的组合维度实测——
  A. 反转族 × 四态 regime（主线/妖股/恐慌/平淡）
  B. 反转族 × 星期几（挂周一效应）
  C. 跌幅分层剂量曲线（-3~-5 / -5~-7 / -7~-9.5 / ≤-9.5%≈S10）
  D. 组合闸门候选：反转 ∩ 恐慌期、反转 ∩ MA60下、反转 ∩ 周四五信号
口径：信号日 i 收盘确认 → i+1 开盘买 → i+1 尾盘卖（T+1）和 i+5 尾盘卖（T+5），净-0.15%。
每格附：同日全宇宙均值超额（日历时间口径，防"全市场都在弹"假edge）。
"""
import json, glob, math, statistics as st
from pathlib import Path

KC = Path("/opt/data/fenjue/data/big_kcache")
TL = Path("/opt/data/fenjue/data/regime_timeline_hcap.json")
FEE = 0.0015
OUT = Path("/opt/data/fenjue/data/s3_combo_20260912.json")

stocks = {}
for fp in glob.glob(str(KC / "*.json")):
    ks = json.loads(open(fp).read())
    if len(ks) >= 300:
        stocks[Path(fp).stem] = ks
print("universe:", len(stocks), flush=True)

regime = {r["date"]: r["regime"] for r in json.loads(TL.read_text())}
WD = ["周一", "周二", "周三", "周四", "周五"]

import datetime as dt
def weekday(ds):
    return dt.date.fromisoformat(ds).weekday()

# 预计算全宇宙日度 T+1 均值（同日超额基准）
uni = {}
for ks in stocks.values():
    c = [k["close"] for k in ks]; o = [k["open"] for k in ks]
    for i in range(65, len(ks) - 2):
        if o[i + 1] > 0:
            uni.setdefault(ks[i + 1]["date"], []).append(c[i + 1] / o[i + 1] - 1 - FEE)
uni_m = {d: st.mean(v) for d, v in uni.items()}
print("universe daily means ready", flush=True)


def grp(name, pred, hold):
    """pred(ks,c,o,i)->bool；hold=持有天数。返回 统计+同日超额"""
    rs, xs = [], []
    for ks in stocks.values():
        c = [k["close"] for k in ks]; o = [k["open"] for k in ks]
        for i in range(65, len(ks) - hold - 1):
            if o[i + 1] > 0 and pred(ks, c, o, i):
                r = c[i + hold] / o[i + 1] - 1 - FEE
                rs.append(r)
                ex = uni_m.get(ks[i + 1]["date"])
                if ex is not None:
                    xs.append(r - ex if hold == 1 else 0)
    if len(rs) < 30:
        return None
    base = {"n": len(rs), "win%": round(100 * sum(r > 0 for r in rs) / len(rs), 1),
            "net%": round(100 * st.mean(rs), 2)}
    if hold == 1 and xs:
        base["同日超额%"] = round(100 * st.mean(xs), 3)
    return base


def chg(c, i):
    return c[i] / c[i - 1] - 1 if c[i - 1] > 0 else 0


R = {}
# A. regime 四态
for rg in ["主线期", "妖股期", "恐慌期", "平淡期"]:
    R[f"A 反转×{rg}"] = grp(rg, lambda ks, c, o, i, _r=rg: chg(c, i) <= -0.03 and regime.get(ks[i]["date"]) == _r, 1)
    print("A", rg, "done", flush=True)
# B. 星期
for w in range(5):
    R[f"B 反转×{WD[w]}"] = grp(WD[w], lambda ks, c, o, i, _w=w: chg(c, i) <= -0.03 and weekday(ks[i]["date"]) == _w, 1)
# C. 跌幅分层
for lo, hi, tag in [(-0.05, -0.03, "-3~-5%"), (-0.07, -0.05, "-5~-7%"), (-0.095, -0.07, "-7~-9.5%"), (-9, -0.095, "≤-9.5%")]:
    R[f"C 跌幅{tag}"] = grp(tag, lambda ks, c, o, i, _l=lo, _h=hi: _l <= chg(c, i) < _h if lo != -9 else chg(c, i) < _h, 1)
    R[f"C 跌幅{tag} T+5"] = grp(tag, lambda ks, c, o, i, _l=lo, _h=hi: _l <= chg(c, i) < _h if lo != -9 else chg(c, i) < _h, 5)
    print("C", tag, "done", flush=True)
# D. 组合闸门
ma60 = lambda c, i: sum(c[i - 60:i]) / 60
R["D 反转∩恐慌期"] = grp("恐慌", lambda ks, c, o, i: chg(c, i) <= -0.03 and regime.get(ks[i]["date"]) == "恐慌期", 1)
R["D 反转∩非恐慌"] = grp("非恐慌", lambda ks, c, o, i: chg(c, i) <= -0.03 and regime.get(ks[i]["date"]) not in (None, "恐慌期"), 1)
R["D 反转∩MA60下"] = grp("MA60下", lambda ks, c, o, i: chg(c, i) <= -0.03 and c[i] <= ma60(c, i), 1)
R["D 反转∩MA60上"] = grp("MA60上", lambda ks, c, o, i: chg(c, i) <= -0.03 and c[i] > ma60(c, i), 1)
R["D 反转∩周四五信号"] = grp("周四五", lambda ks, c, o, i: chg(c, i) <= -0.03 and weekday(ks[i]["date"]) in (3, 4), 1)
R["D 基准 反转全量"] = grp("基准", lambda ks, c, o, i: chg(c, i) <= -0.03, 1)
R["D 基准 反转全量 T+5"] = grp("基准T5", lambda ks, c, o, i: chg(c, i) <= -0.03, 5)

OUT.write_text(json.dumps(R, ensure_ascii=False, indent=1))
print(json.dumps(R, ensure_ascii=False, indent=1))
print("saved", OUT)
