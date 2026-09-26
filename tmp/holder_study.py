"""增减持/回购事件分析（2026-09-26 深夜）。

①个股事件研究：公告日次日开盘入，T+1/5/20/60，费 0.15%，含退市股；分类型×分年×regime；
  对照=同股同位置随机日（快版：同股其他月份首个交易日）。
②市场级：月度回购公告数序列 vs 指数前瞻 60 日收益（回购潮=底部先行指标验证）；
  当月回购数处于历史高位（>80 分位）时次月指数表现。
"""
import bisect
import collections
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
events = json.loads(open(f"{ROOT}/data/holder_events_raw_20260926.json").read())
stocks = lp.load_universe()
regime = lp.load_regime()
idx_data = json.loads(open(f"{ROOT}/data/index_sh000001.json").read())
cal = [k["date"] for k in idx_data]
idx_map = {k["date"]: float(k["close"]) for k in idx_data}
print(f"事件 {len(events)}", flush=True)

recs = []
for e in events:
    d = stocks.get(e["code"])
    if not d:
        continue
    j = bisect.bisect_left(cal, e["date"])
    if j >= len(cal):
        continue
    day = cal[j]  # 公告日对齐到交易日（盘后公告→次日）
    if day not in d["date"]:
        continue
    i = d["date"].index(day)
    if i < 60 or i + 61 >= d["n"] or d["o"][i + 1] <= 0:
        continue
    entry = d["o"][i + 1]
    # 指数同期收益（超额对照：区分公告效应 vs 趋势延续）
    j0 = cal.index(day)
    def _mkt(h):
        return idx_map[cal[j0 + 1 + h]] / idx_map[cal[j0 + 1]] - 1 if j0 + 1 + h < len(cal) else 0
    recs.append({"code": e["code"], "date": day, "kind": e["kind"], "year": day[:4],
                 "rg": regime.get(day, "?"),
                 "t1": d["c"][i + 1] / entry - 1 - FEE,
                 "t5": d["c"][i + 5] / entry - 1 - FEE,
                 "t20": d["c"][i + 20] / entry - 1 - FEE,
                 "t60": d["c"][i + 60] / entry - 1 - FEE,
                 "x5": d["c"][i + 5] / entry - 1 - FEE - _mkt(4),
                 "x20": d["c"][i + 20] / entry - 1 - FEE - _mkt(19),
                 "x60": d["c"][i + 60] / entry - 1 - FEE - _mkt(59)})
print(f"可计算 {len(recs)}")


def blk(rows, lb):
    if len(rows) < 25:
        print(f"  {lb}: n={len(rows)} 不足")
        return
    line = f"  {lb:<18} n={len(rows):>5}"
    for h in ("t1", "t5", "t20", "t60"):
        xs = [r[h] for r in rows]
        wr = sum(1 for x in xs if x > 0) / len(xs)
        line += f" | {h.upper()} {wr * 100:4.0f}%/{st.mean(xs) * 100:+5.2f}%"
    xs = [r["x20"] for r in rows]
    line += f" | X20超额 {st.mean(xs) * 100:+5.2f}%"
    print(line)


print("\n═══ 按类型 ═══")
for k in ("增持", "回购", "减持"):
    blk([r for r in recs if r["kind"] == k], k)
print("\n═══ 分年 ═══")
for y in ("2024", "2025", "2026"):
    for k in ("增持", "回购", "减持"):
        blk([r for r in recs if r["kind"] == k and r["year"] == y], f"{y}{k}")
print("\n═══ regime ═══")
for g in ("恐慌期", "平淡期", "妖股期", "主线期"):
    for k in ("回购", "减持"):
        blk([r for r in recs if r["kind"] == k and r["rg"] == g], f"{g}{k}")

# ② 市场级：月度回购公告数 vs 指数前瞻
monthly = collections.Counter(r["date"][:7] for r in recs if r["kind"] == "回购")
months = sorted(monthly)
vals = sorted(monthly.values())
p80 = vals[int(len(vals) * 0.8)] if vals else 999
print(f"\n═══ 回购潮指标（月度回购公告数，P80={p80}） ═══")
for hi in (True, False):
    fw = []
    for mo in months:
        if (monthly[mo] >= p80) != hi:
            continue
        j = bisect.bisect_left(cal, mo + "-01")
        if j + 42 >= len(cal):
            continue
        fw.append(idx_map[cal[j + 42]] / idx_map[cal[j]] - 1)
    if len(fw) >= 3:
        print(f"  回购数{'≥' if hi else '<'}P80 的月份 n={len(fw)}：随后60日指数 {st.mean(fw) * 100:+.2f}% "
              f"（胜率 {sum(1 for x in fw if x > 0) / len(fw) * 100:.0f}%）")
json.dump(recs, open(f"{ROOT}/data/holder_events_study_20260926.json", "w"), ensure_ascii=False)
print("\nsaved")
