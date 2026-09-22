"""炸板尾部损失·自家 8 年日K自建（2026-09-22，回应炸板池数据源受限）。

判定（主板 10%，涨停价=round(昨收×1.10,2)，剔 ST 按现行名）：
  触板 = high >= 涨停价；回封 = 收盘 >= 涨停价；尾部 = 触板未回封。
排板成交模型：涨停价挂单，触板即成交（一字锁死 low==high==涨停 不可成交，剔）。
入场价=涨停价。收益=次日开盘/收盘 vs 涨停价，费 0.15%。
分组：全触板 vs 回封（在涨停池=上次研究的池）vs 尾部（未回封=上次缺失的坑）；
      regime/逐年分层。
判决问题：排板策略的完整期望 = 回封组收益 × 回封占比 + 尾部组收益 × 尾部占比
（相对「只在回封板里选」的上限估计的折扣）。
"""
import collections
import json
import math
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015

stocks = lp.load_universe()
regime = lp.load_regime()
names = {str(s["code"]).zfill(6): s.get("name", "")
         for s in json.loads(open(f"{ROOT}/data/main_board_codes.json").read())["stocks"]}
print("universe", len(stocks), flush=True)


def limit_px(pc):
    return round(pc * 1.10 + 1e-9, 2)


groups = {"触板全部": [], "回封": [], "尾部": []}
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    nm = names.get(code, "")
    if "ST" in nm or "退" in nm:
        continue
    n = d["n"]
    for i in range(60, n - 2):
        pc = d["c"][i - 1]
        if pc <= 0 or d["h"][i] <= 0:
            continue
        lp_px = limit_px(pc)
        if d["h"][i] < lp_px - 1e-9:
            continue
        # 一字锁死（开=低=高≈涨停）不可成交
        if d["l"][i] >= lp_px - 1e-9 and d["o"][i] >= lp_px - 1e-9:
            continue
        dt = d["date"][i]
        resealed = d["c"][i] >= lp_px - 1e-9
        e = lp_px  # 排板入场=涨停价
        rec = {"date": dt, "year": dt[:4], "regime": regime.get(dt, "?"), "code": code,
               "seg": "2019-2022" if dt < "2023" else "2023-2026",
               "open1": d["o"][i + 1] / e - 1 - FEE if d["o"][i + 1] > 0 else None,
               "close1": d["c"][i + 1] / e - 1 - FEE,
               "close0": d["c"][i] / e - 1}  # 当日收盘浮盈（入场=涨停价）
        groups["触板全部"].append(rec)
        groups["回封" if resealed else "尾部"].append(rec)
print({k: len(v) for k, v in groups.items()}, flush=True)


def blk(rs):
    rs = [r for r in rs if r["close1"] is not None]
    n = len(rs)
    if n < 30:
        return {"n": n}
    o = [r["open1"] for r in rs if r["open1"] is not None]
    c = [r["close1"] for r in rs]
    m = st.mean(c)
    sd = st.stdev(c) if n > 1 else 0
    return {"n": n, "开盘均%": round(st.mean(o) * 100, 2), "收盘均%": round(m * 100, 2),
            "胜率": round(sum(1 for x in c if x > 0) / n, 3),
            "t": round(m / (sd / math.sqrt(n)), 1) if sd else None,
            "当日浮盈均%": round(st.mean(r["close0"] for r in rs) * 100, 2)}


out = {}
print("\n═══ 排板模型三分组（入场=涨停价，费 0.15%）═══")
for k, v in groups.items():
    b = blk(v)
    out[k] = b
    print(f"  {k:<6} n={b['n']:>6} 当日浮盈{b['当日浮盈均%']:+6.2f}% 次日开盘{b['开盘均%']:+6.2f}% 次日收盘{b['收盘均%']:+6.2f}%(t{b['t']}) 胜率{b['胜率']*100:.0f}%")

print("\n═══ 尾部组×regime ═══")
for rg in ("妖股期", "恐慌期", "平淡期", "主线期"):
    b = blk([r for r in groups["尾部"] if r["regime"] == rg])
    out[f"尾部_{rg}"] = b
    if b.get("n", 0) >= 30:
        print(f"  {rg}: n={b['n']:>5} 次日收盘{b['收盘均%']:+6.2f}% 胜率{b['胜率']*100:.0f}%")

print("\n═══ 尾部组×逐年 ═══")
yb = collections.defaultdict(list)
for r in groups["尾部"]:
    yb[r["year"]].append(r)
for y, v in sorted(yb.items()):
    b = blk(v)
    out[f"尾部_{y}"] = b
    if b.get("n", 0) >= 30:
        print(f"  {y}: n={b['n']:>5} 次日收盘{b['收盘均%']:+6.2f}% 胜率{b['胜率']*100:.0f}%")

# 完整期望
allr = groups["触板全部"]
reseal_rate = len(groups["回封"]) / len(allr)
tail_ret = blk(groups["尾部"])
reseal_ret = blk(groups["回封"])
full_exp = reseal_rate * reseal_ret["收盘均%"] + (1 - reseal_rate) * tail_ret["收盘均%"]
print(f"\n═══ 排板完整期望（等权全部触板，不择股）═══")
print(f"回封占比 {reseal_rate*100:.0f}% | 回封组 {reseal_ret['收盘均%']}% | 尾部组 {tail_ret['收盘均%']}%")
print(f"完整期望（次日收盘）: {full_exp:+.2f}%  ← 对比「只在回封板里选」的上限 {reseal_ret['收盘均%']:+.2f}%")
out["完整期望"] = {"回封占比": round(reseal_rate, 4), "回封组": reseal_ret, "尾部组": tail_ret,
                  "完整期望%": round(full_exp, 2)}

json.dump(out, open(f"{ROOT}/data/zhaban_tail_8y_20260922.json", "w"), ensure_ascii=False, indent=1)
print("saved data/zhaban_tail_8y_20260922.json")
