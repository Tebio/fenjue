"""反复票「低位打进吃波动」变体检验（2026-09-21 用户提案）。

用户方案：反复的时候（白名单内）在低位打进去，吃波动就跑。
与已证伪变体的区别：不等下跌日，等价格落到短期低位（埋伏），短持快跑。

变体（白名单=近20交易日大涨≥9.5%≥3次，无前视；入场=次日开盘；费0.15%）：
  A 低位触及：白名单 × 收盘=5日最低收 × 非跌停 → T+1/T+2/T+3 收盘卖
  B 低位企稳：白名单 × 收盘距10日最低收≤2% × 当日收阳(c≥o) → T+1/T+2/T+3
  C B+止盈：持有期内收盘≥入场价+5% 当日尾盘走，否则 T+3 尾盘走（吃波动就跑的直译）
对照：同形态非白名单组（白名单边际检验）；逐年表+regime分段。
"""
import collections
import json
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

FEE = 0.0015
ROOT = "/opt/data/fenjue"
stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
print("universe", len(stocks), flush=True)


def lowA(d, i):   # 收盘=5日最低收 且非跌停
    if i < 5 or d["c"][i - 1] <= 0:
        return False
    chg = d["c"][i] / d["c"][i - 1] - 1
    return chg > -0.095 and d["c"][i] == min(d["c"][i - 4:i + 1])


def lowB(d, i):   # 距10日最低收≤2% 且当日收阳
    if i < 10 or d["c"][i - 1] <= 0:
        return False
    lo = min(d["c"][i - 9:i + 1])
    return d["c"][i] <= lo * 1.02 and d["c"][i] >= d["o"][i] > 0


groups = collections.defaultdict(list)          # g -> list of (date, [T+1,T+2,T+3])
groupsC = collections.defaultdict(list)         # 止盈变体: (date, ret, held_days)
years = {str(y): collections.defaultdict(list) for y in range(2019, 2027)}
regs = collections.defaultdict(lambda: collections.defaultdict(list))
recent = []

for code, d in stocks.items():
    c, o, n = d["c"], d["o"], d["n"]
    hi = n - 4
    cb = lp._cbig(d)
    for i in range(lp.START, hi):
        a, b = lowA(d, i), lowB(d, i)
        if not a and not b:
            continue
        if o[i + 1] <= 0:
            continue
        wl = cb[i - 1] - cb[max(0, i - 21)] >= 3
        dt = d["date"][i]
        rs = [c[i + h] / o[i + 1] - 1 - FEE for h in (1, 2, 3)]
        for tag, on in (("A低位触及", a), ("B低位企稳", b)):
            if not on:
                continue
            g = f"{tag}×{'白' if wl else '非'}"
            groups[g].append((dt, rs))
            years[dt[:4]][g].append(rs[2])
            regs[g][regime.get(dt, "?")].append(rs[2])
            if wl and dt >= "2026-08-01":
                recent.append((dt, code, tag, round(rs[0] * 100, 2), round(rs[2] * 100, 2)))
        # C 变体：B+止盈（只吃波动）
        if b and o[i + 1] > 0:
            ep = o[i + 1]
            held, ret = 3, None
            for h in (1, 2, 3):
                if c[i + h] >= ep * 1.05:
                    held, ret = h, c[i + h] / ep - 1 - FEE
                    break
            if ret is None:
                ret = c[i + 3] / ep - 1 - FEE
            g = f"C止盈×{'白' if wl else '非'}"
            groupsC[g].append((dt, ret, held))
            years[dt[:4]][g].append(ret)
            regs[g][regime.get(dt, "?")].append(ret)
            if wl and dt >= "2026-08-01":
                recent.append((dt, code, "C止盈", round(ret * 100, 2), held))


def agg(rs):
    if not rs:
        return "n=0"
    wr = sum(1 for r in rs if r > 0) / len(rs)
    return f"n={len(rs)} 胜率{wr * 100:.0f}% 均值{sum(rs) / len(rs) * 100:+.2f}%"


print("\n═══ 低位打进变体 A/B 总表 ═══")
for g in ("A低位触及×白", "A低位触及×非", "B低位企稳×白", "B低位企稳×非"):
    rows = groups.get(g, [])
    print(f"【{g}】n={len(rows)}")
    for k, h in enumerate((1, 2, 3)):
        print(f"  T+{h}: {agg([r[k] for _, r in rows])}")
for g in ("C止盈×白", "C止盈×非"):
    rows = groupsC.get(g, [])
    rets = [r for _, r, _ in rows]
    holds = [h for _, _, h in rows]
    print(f"【{g}】{agg(rets)} 平均持有{sum(holds) / len(holds):.1f}天" if rows else f"【{g}】n=0")

print("\n═══ 逐年表（T+3 / C为止盈口径）═══")
hdr = ["A低位触及×白", "A低位触及×非", "B低位企稳×白", "B低位企稳×非", "C止盈×白", "C止盈×非"]
print(f"{'年份':<5}" + "".join(f"{g[:2] + g[-1]:>18}" for g in hdr))
for y in sorted(years):
    cells = []
    for g in hdr:
        rs = years[y].get(g, [])
        cells.append(f"{sum(rs) / len(rs) * 100:+.2f}/{sum(1 for r in rs if r > 0) / len(rs) * 100:.0f}%n{len(rs)}" if rs else "—")
    print(f"{y:<5}" + "".join(f"{c:>18}" for c in cells))

print("\n═══ regime 分段（T+3 / C止盈口径）═══")
for g in hdr:
    dd = regs.get(g, {})
    print(f"{g:<12} " + " ".join(f"{k}:{sum(v) / len(v) * 100:+.2f}%" for k, v in sorted(dd.items()) if v))

names = {str(s["code"]).zfill(6): s.get("name", "")
         for s in json.load(open(f"{ROOT}/data/main_board_codes.json")).get("stocks", [])}
print("\n═══ 2026-08 以来白名单触发（T+1/T+3 或止盈实际值）═══")
for row in sorted(recent)[-20:]:
    print("  ", row[0], names.get(row[1], row[1]), row[2], "→", row[3], row[4] if len(row) > 4 else "")

out = {
    "groups": {g: {"n": len(rows),
                   **{f"T+{h}": {"mean": sum(r[k] for _, r in rows) / len(rows),
                                 "wr": sum(1 for _, r in rows if r[k] > 0) / len(rows)}
                      for k, h in enumerate((1, 2, 3))}}
               for g, rows in groups.items()},
    "groupsC": {g: {"n": len(rows),
                    "mean": sum(r for _, r, _ in rows) / len(rows),
                    "wr": sum(1 for _, r, _ in rows if r > 0) / len(rows),
                    "avg_hold": sum(h for _, _, h in rows) / len(rows)}
                for g, rows in groupsC.items()},
    "yearly": {y: {g: {"n": len(rs), "mean": sum(rs) / len(rs), "wr": sum(1 for r in rs if r > 0) / len(rs)}
                   for g, rs in dd.items()}
               for y, dd in years.items()},
    "regime": {g: {k: {"n": len(v), "mean": sum(v) / len(v)} for k, v in dd.items() if v}
               for g, dd in regs.items()},
}
json.dump(out, open(f"{ROOT}/data/recurring_lowentry_20260921.json", "w"), ensure_ascii=False, indent=1)
print("\n落盘 data/recurring_lowentry_20260921.json")
