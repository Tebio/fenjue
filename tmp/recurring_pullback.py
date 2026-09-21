"""反复票白名单×回调 A/B 研究（2026-09-21 用户立项：要全历史时期适用）。

核心检验：同一回调形态，白名单（近20日大涨≥3）vs 非白名单，边际是不是白名单给的。
口径：信号日 T → T+1 开盘买（next_open，与全管线一致），费 0.15%，H=T+1/3/5/10。
分组：回调日(-3~-9.5%) / 回撤企稳(5日高回撤≥8%且非跌停) × 白名单是/否。
输出：逐年表（2019-2026，用户点名"任何时期适用"）+ regime 分段 + A/B 边际。
"""
import collections
import json
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

FEE = 0.0015
HS = [1, 3, 5, 10]
ROOT = "/opt/data/fenjue"

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
print("universe", len(stocks), flush=True)

det_wl = lp.REGISTRY["反复票_回调日"]
det_wl2 = lp.REGISTRY["反复票_回撤企稳"]


def trig_huili(d, i):
    return d["c"][i - 1] > 0 and -0.095 < d["c"][i] / d["c"][i - 1] - 1 <= -0.03


def trig_huiche(d, i):
    return (i >= 5 and d["c"][i - 1] > 0
            and d["c"][i] <= max(d["c"][i - 4:i + 1]) * 0.92
            and d["c"][i] / d["c"][i - 1] - 1 > -0.095)


groups = collections.defaultdict(list)  # name -> list of (date, [r per H])
years = {str(y): collections.defaultdict(list) for y in range(2019, 2027)}
regs = collections.defaultdict(lambda: collections.defaultdict(list))
recent = []

for code, d in stocks.items():
    c, o, n = d["c"], d["o"], d["n"]
    hi = n - max(HS) - 1
    lp._cbig(d)  # 预建缓存
    for i in range(lp.START, hi):
        if o[i + 1] <= 0:
            continue
        hl = trig_huili(d, i)
        hc = trig_huiche(d, i)
        if not hl and not hc:
            continue
        wl = lp._wl(d, i)
        dt = d["date"][i]
        rs = [c[i + h] / o[i + 1] - 1 - FEE for h in HS]
        for tag, on in (("回调日", hl), ("回撤企稳", hc)):
            if not on:
                continue
            g = f"{tag}×{'白名单' if wl else '非白名单'}"
            groups[g].append((dt, rs))
            years[dt[:4]][g].append(rs[2])  # T+5
            regs[tag + ("×白" if wl else "×非")][regime.get(dt, "?")].append(rs[2])
            if dt >= "2026-08-01" and wl:
                recent.append((dt, code, tag, round(rs[2] * 100, 2)))


def agg(rs):
    if not rs:
        return "n=0"
    wr = sum(1 for r in rs if r > 0) / len(rs)
    return f"n={len(rs)} 胜率{wr * 100:.0f}% 均值{sum(rs) / len(rs) * 100:+.2f}%"


print("\n═══ A/B 总表（净费0.15%，次日开盘买）═══")
for g in ("回调日×白名单", "回调日×非白名单", "回撤企稳×白名单", "回撤企稳×非白名单"):
    rows = groups.get(g, [])
    print(f"\n【{g}】 n={len(rows)}")
    for k, h in enumerate(HS):
        rs = [r[k] for _, r in rows]
        print(f"  T+{h}: {agg(rs)}")

print("\n═══ 逐年表（T+5）═══")
hdr = ["回调日×白名单", "回调日×非白名单", "回撤企稳×白名单", "回撤企稳×非白名单"]
print(f"{'年份':<6}" + "".join(f"{g:>22}" for g in ["回调×白", "回调×非", "回撤×白", "回撤×非"]))
for y in sorted(years):
    cells = []
    for g in hdr:
        rs = years[y].get(g, [])
        cells.append(f"{sum(rs) / len(rs) * 100:+.2f}%/{sum(1 for r in rs if r > 0) / len(rs) * 100:.0f}%(n{len(rs)})" if rs else "—")
    print(f"{y:<6}" + "".join(f"{c:>22}" for c in cells))

print("\n═══ regime 分段（T+5）═══")
for g, dd in regs.items():
    line = " ".join(f"{k}:{sum(v) / len(v) * 100:+.2f}%(n{len(v)})" for k, v in sorted(dd.items()) if v)
    print(f"{g:<10} {line}")

print("\n═══ 2026-08 以来白名单触发记录（T+5实际值）═══")
names = {str(s["code"]).zfill(6): s.get("name", "")
         for s in json.load(open(f"{ROOT}/data/main_board_codes.json")).get("stocks", [])}
for dt, code, tag, r5 in sorted(recent)[-25:]:
    print(f"  {dt} {names.get(code, code)}({code}) {tag} T+5={r5:+.1f}%")

out = {"groups": {g: {"n": len(rows),
                      **{f"T+{HS[k]}": {"mean": sum(r[k] for _, r in rows) / len(rows),
                                        "wr": sum(1 for _, r in rows if r[k] > 0) / len(rows)}
                         for k in range(len(HS))}}
                   for g, rows in groups.items()},
       "yearly_T5": {y: {g: {"n": len(rs), "mean": sum(rs) / len(rs) if rs else None,
                             "wr": sum(1 for r in rs if r > 0) / len(rs) if rs else None}
                         for g, rs in dd.items()}
                     for y, dd in years.items()},
       "regime_T5": {g: {k: {"n": len(v), "mean": sum(v) / len(v)} for k, v in dd.items() if v}
                     for g, dd in regs.items()}}
json.dump(out, open(f"{ROOT}/data/recurring_pullback_20260921.json", "w"), ensure_ascii=False, indent=1)
print("\n落盘 data/recurring_pullback_20260921.json")
