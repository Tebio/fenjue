"""妖股启动期首板线·生产级验证（2026-09-25，用户要求：好不好用/赚不赚钱/准不准确）。

信号：妖股期段龄1-2 + 首板（前10日无板）+ 梯队≥3 + 量比≥1.5，当日打板进（close-entry），T+1 收盘出。
验证四件套：
  A 一字板剔除：首板日 open==high==low==close=涨停（全天锁死买不进）→ 剔除重算
  B 分年/分月胜率收益（准不准确）
  C 5万槽位模拟：最多5槽、每槽=权益/5、T+1收盘出、费0.15%、重叠信号跳过（赚不赚钱）
  D 出场变体：T+1开盘卖 / T+1收盘卖 / T+2收盘卖（执行敏感性）
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
age_map = {}
cur_r, age = None, 0
for x in tl:
    if x["regime"] != cur_r:
        cur_r, age = x["regime"], 1
    else:
        age += 1
    age_map[x["date"]] = (x["regime"], age)
mmap = json.load(open(f"{ROOT}/data/industry_map.json"))
code2ind = {str(k).zfill(6): v["industry"] for k, v in mmap.items() if isinstance(v, dict) and v.get("industry")}


def is_lu(c, cp):
    return cp > 0 and c / cp - 1 >= 0.098


ind_boards = collections.defaultdict(lambda: collections.Counter())
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    ind = code2ind.get(code, "")
    for i in range(61, d["n"]):
        if is_lu(d["c"][i], d["c"][i - 1]):
            ind_boards[d["date"][i]][ind] += 1

events = []
yizi = 0
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(61, n - 6):
        dt = d["date"][i]
        rg, age = age_map.get(dt, ("?", 0))
        if rg != "妖股期" or age > 2 or d["c"][i - 1] <= 0:
            continue
        if not is_lu(d["c"][i], d["c"][i - 1]):
            continue
        if any(is_lu(d["c"][j], d["c"][j - 1]) for j in range(i - 10, i)):
            continue
        vr = d["v"][i] / (st.mean(d["v"][i - 20:i]) or 1)
        if vr < 1.5:
            continue
        ind = code2ind.get(code, "")
        if ind_boards[dt].get(ind, 0) < 3:
            continue
        limit = round(d["c"][i - 1] * 1.1, 2)
        if d["o"][i] >= limit * 0.999 and d["l"][i] >= limit * 0.999:
            yizi += 1
            continue  # 一字锁死买不进
        events.append({"code": code, "date": dt, "age": age,
                       "t1c": d["c"][i + 1] / d["c"][i] - 1 - FEE,
                       "t1o": d["o"][i + 1] / d["c"][i] - 1 - FEE if d["o"][i + 1] > 0 else None,
                       "t2c": d["c"][i + 2] / d["c"][i] - 1 - FEE,
                       "t5c": d["c"][i + 5] / d["c"][i] - 1 - FEE})
print(f"一字板剔除 {yizi} 只，可买事件 {len(events)}")


def blk(rows, lb, h="t1c"):
    if len(rows) < 20:
        return
    xs = [r[h] for r in rows if r[h] is not None]
    wr = sum(1 for x in xs if x > 0) / len(xs)
    print(f"  {lb:<16} n={len(xs):>5} {wr * 100:5.1f}%/{st.mean(xs) * 100:+5.2f}%")


print("\n═══ A 可买口径总览 ═══")
for h, t in (("t1c", "T+1收盘出"), ("t1o", "T+1开盘出"), ("t2c", "T+2收盘出"), ("t5c", "T+5收盘出")):
    blk(events, t, h)

print("\n═══ B 分年（T+1收盘出） ═══")
years = sorted(set(r["date"][:4] for r in events))
for y in years:
    blk([r for r in events if r["date"][:4] == y], y)

print("\n═══ B2 分月（近2年） ═══")
months = sorted(set(r["date"][:7] for r in events if r["date"] >= "2025-01"))
for m in months:
    blk([r for r in events if r["date"][:7] == m], m)

print("\n═══ C 5万槽位模拟（T+1收盘出，5槽均分） ═══")
by_day = collections.defaultdict(list)
for r in events:
    by_day[r["date"]].append(r)
equity, curve = 50000.0, []
peak = equity
maxdd = 0.0
trades = 0
wins = 0
open_slots = []  # (exit_date, ret)
for dt in sorted(by_day):
    # 结算到期
    for ex, ret in list(open_slots):
        if ex <= dt:
            equity *= 1 + ret / 5 * 5 / 5  # 每槽=权益/5，收益按槽比例
            open_slots.remove((ex, ret))
    # 当日信号入场（最多补到5槽）
    room = 5 - len(open_slots)
    sigs = by_day[dt][:room]
    for r in sigs:
        # 找退出日（该股下一交易日）
        d = stocks[r["code"]]
        i = d["date"].index(dt)
        exit_dt = d["date"][i + 1]
        open_slots.append((exit_dt, r["t1c"]))
        trades += 1
        wins += 1 if r["t1c"] > 0 else 0
    peak = max(peak, equity)
    maxdd = min(maxdd, equity / peak - 1)
    curve.append((dt, equity))
print(f"  交易 {trades} 笔 胜率 {wins / trades * 100:.1f}% 期末 {equity:,.0f}（{(equity / 50000 - 1) * 100:+.1f}%）最大回撤 {maxdd * 100:.1f}%")
years_span = len(set(r["date"][:4] for r in events))
print(f"  覆盖 {years_span} 个年份，粗年化 {(equity / 50000) ** (1 / 7.75) - 1:+.1%}" if equity > 0 else "")
print("  近3年曲线:")
for dt, eq in curve[-60::20]:
    print(f"    {dt} {eq:,.0f}")
