"""回封确认买入测试（2026-09-22）：涨停池数据独有的新入场腿。

逻辑：炸板→回封确认的瞬间买（最后封板时间=入场点），入场价=涨停价。
与排板的区别：排板是事前赌它封住（吃 34% 尾部），回封确认是事后确认它封住了再买
（尾部为零——没回封的票你根本不会买）。代价：入场价=涨停价（比排板成本高），
且要假设回封瞬间能成交（回封时卖单涌出，可成交性合理）。
测试：炸板次数≥1 的票按「最后封板时间」分桶 → 次日三价。
对照：未炸板（早盘板=排板能成交的上限组）与全池。
"""
import csv
import json
import math
import statistics as st

ROOT = "/opt/data/fenjue"
rows = list(csv.DictReader(open(f"{ROOT}/data/limit_up_mainboard_20250908_20260922.csv", encoding="utf-8-sig")))


def f(r, k):
    try:
        return float(r[k])
    except (TypeError, ValueError):
        return None


def zi(r):
    try:
        return int(r["炸板次数"])
    except (TypeError, ValueError):
        return 0


def tmin(r, k):
    t = (r.get(k) or "").strip()
    if len(t) < 5:
        return None
    try:
        return int(t[:2]) * 60 + int(t[3:5])
    except ValueError:
        return None


def blk(rs, label):
    rs = [r for r in rs if f(r, "次日收盘涨幅(%)") is not None and f(r, "次日开盘涨幅(%)") is not None]
    n = len(rs)
    if n < 15:
        return None
    o = [f(r, "次日开盘涨幅(%)") for r in rs]
    c = [f(r, "次日收盘涨幅(%)") for r in rs]
    m = st.mean(c)
    sd = st.stdev(c) if n > 1 else 0
    return {"label": label, "n": n, "开盘均%": round(st.mean(o), 2), "收盘均%": round(m, 2),
            "胜率": round(sum(1 for x in c if x > 0) / n, 3),
            "t": round(m / (sd / math.sqrt(n)), 1) if sd else None}


broken = [r for r in rows if zi(r) >= 1 and tmin(r, "最后封板时间") is not None]
out = {}

print(f"炸板≥1 且最后封板时间有效: {len(broken)}")
print("\n═══ 回封确认买入（炸板≥1，按最后封板时间分桶）═══")
for lo, hi, lb in ((570, 690, "上午回封(≤11:30)"), (690, 840, "午后早段(11:30-14:00)"), (840, 905, "尾盘回封(≥14:00)")):
    b = blk([r for r in broken if lo <= tmin(r, "最后封板时间") < hi], lb)
    out[f"回封_{lb}"] = b
    if b:
        print(f"  {lb:<16} n={b['n']:>5} 开盘{b['开盘均%']:+6.2f}% 收盘{b['收盘均%']:+6.2f}%(t{b['t']}) 胜率{b['胜率']*100:.0f}%")

# 封单强度在回封确认组内是否还有区分度
print("\n═══ 回封确认组 × 封单强度 ═══")
vals = sorted(f(r, "封单额/流通市值(%)") for r in broken if f(r, "封单额/流通市值(%)") is not None)
qs = [vals[int(len(vals) * p)] for p in (0.33, 0.67)]
for lo, hi, lb in ((0, qs[0], "弱封单"), (qs[0], qs[1], "中"), (qs[1], 999, "强封单")):
    b = blk([r for r in broken if f(r, "封单额/流通市值(%)") is not None and lo <= f(r, "封单额/流通市值(%)") < hi], lb)
    out[f"回封封单_{lb}"] = b
    if b:
        print(f"  {lb:<5} n={b['n']:>5} 收盘{b['收盘均%']:+6.2f}%(t{b['t']}) 胜率{b['胜率']*100:.0f}%")

# 对照组
for label, sub in (("对照:未炸板全组", [r for r in rows if zi(r) == 0]),
                   ("对照:早盘板未炸板(排板上限)", [r for r in rows if zi(r) == 0 and r["封板时段"] == "早盘板(<10:30)"])):
    b = blk(sub, label)
    out[label] = b
    if b:
        print(f"\n  {label}: n={b['n']} 收盘{b['收盘均%']:+.2f}%(t{b['t']}) 胜率{b['胜率']*100:.0f}%")

json.dump(out, open(f"{ROOT}/data/zhaban_reseal_entry_20260922.json", "w"), ensure_ascii=False, indent=1)
print("\nsaved data/zhaban_reseal_entry_20260922.json")
