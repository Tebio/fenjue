"""妖股期段龄门测试（2026-09-25，用户「基于现状改进」——把相位单调变成生产闸门）。

假设：妖股期策略（B5 半路板/抢跑首板）的 edge 集中在妖段启动期（段龄 1-3 天），退潮期衰减。
代理信号（生产口径近似）：妖股期日、首板（前10日无板）、量比≥1.5、梯队≥3（板块同日≥3板）。
入场=次日开盘，T+1/T+5 收盘出，费 0.15%，含退市股。
分桶：段龄 1-2 / 3-5 / 6+ 天（段龄=该妖股段内第 N 个交易日，从 regime 时间轴算）。
"""
import collections
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
stocks = lp.load_universe()
tl = json.load(open(f"{ROOT}/data/regime_timeline_hcap.json"))

# 段龄表：日期 → (regime, 段内第几天)
age_map = {}
cur_r, age = None, 0
for x in tl:
    if x["regime"] != cur_r:
        cur_r, age = x["regime"], 1
    else:
        age += 1
    age_map[x["date"]] = (cur_r, age)

# 板块同日涨停数（梯队）
ind_boards = collections.defaultdict(lambda: collections.Counter())
mmap = json.load(open(f"{ROOT}/data/industry_map.json"))
code2ind = {str(k).zfill(6): v["industry"] for k, v in mmap.items() if isinstance(v, dict) and v.get("industry")}


def is_lu(c, cp):
    return cp > 0 and c / cp - 1 >= 0.098


for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    ind = code2ind.get(code, "")
    n = d["n"]
    for i in range(61, n):
        if is_lu(d["c"][i], d["c"][i - 1]):
            ind_boards[d["date"][i]][ind] += 1

events = []
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(61, n - 6):
        dt = d["date"][i]
        rg, age = age_map.get(dt, ("?", 0))
        if rg != "妖股期" or d["c"][i - 1] <= 0 or d["o"][i + 1] <= 0:
            continue
        if not is_lu(d["c"][i], d["c"][i - 1]):
            continue
        if any(is_lu(d["c"][j], d["c"][j - 1]) for j in range(i - 10, i)):
            continue  # 首板（前10日无板）
        vr = d["v"][i] / (st.mean(d["v"][i - 20:i]) or 1)
        if vr < 1.5:
            continue
        ind = code2ind.get(code, "")
        if ind_boards[dt].get(ind, 0) < 3:
            continue  # 梯队≥3
        entry = d["o"][i + 1]
        events.append({"code": code, "date": dt, "age": age, "vr": vr,
                       "t1": d["c"][i + 1] / entry - 1 - FEE,
                       "t5": d["c"][i + 5] / entry - 1 - FEE})
print(f"妖股期首板+梯队≥3+量比≥1.5 事件 {len(events)}")

def blk(rows, lb):
    if len(rows) < 20:
        print(f"  {lb:<18} n={len(rows)} 样本不足")
        return
    line = f"  {lb:<18} n={len(rows):>5}"
    for h in ("t1", "t5"):
        xs = [r[h] for r in rows]
        wr = sum(1 for x in xs if x > 0) / len(xs)
        line += f" | {h.upper()} {wr * 100:5.1f}%/{st.mean(xs) * 100:+5.2f}%"
    print(line)

print("\n═══ 按妖段段龄 ═══")
for lo, hi, lb in ((1, 3, "启动期(段龄1-2)"), (3, 6, "发酵期(3-5)"), (6, 999, "退潮期(6+)")):
    blk([r for r in events if lo <= r["age"] < hi], lb)
print("\n═══ 分时段稳健性 ═══")
for seg in ("2019-2021", "2022-2024", "2025-2026"):
    y0, y1 = seg.split("-")
    blk([r for r in events if y0 <= r["date"][:4] <= y1 and r["age"] <= 2], f"启动期 {seg}")
    blk([r for r in events if y0 <= r["date"][:4] <= y1 and r["age"] >= 6], f"退潮期 {seg}")
print("\n═══ 对照：非妖股期同信号 ═══")
# 同信号但在其他 regime（从 events 重建太贵，直接标注 regime 重扫）
json.dump(events, open(f"{ROOT}/data/age_gate_test_20260925.json", "w"), ensure_ascii=False)
print("saved data/age_gate_test_20260925.json")
