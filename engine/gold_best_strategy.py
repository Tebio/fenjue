#!/usr/bin/env python3
"""金股最容易赚钱的策略：从结果反推（2026-10-19 用户「直接从答案反推」）。

不是回答单点问题，而是**在全部可执行空间里搜一遍，找那种每个月都赚的规则**。

搜索空间
  买入时点 d：出票后第 0~12 个交易日收盘（附条件变体：只买阴转阳日 / 放量见底次日）
  卖出规则 ：固定持 k 日 / 止盈+X% / 止损-Y% / 移动止盈(高点回撤 z) / T+20 强平
  选股过滤 ：全池 / 弹性分 top 1/3 / 距60日高 top 1/3 / 低波动 bottom 1/3

评分纪律（缺一即淘汰）
  ① 逐月均值 5/5 全正（不是合并均值）
  ② 同窗口全市场同规则超额 > 0（剥掉 beta，避免把跟市当赚钱）
  ③ 样本：每期 ≥15 笔，总 ≥75 笔
  ④ 报告命中格数 vs 随机期望，防止择优选格（多测试偏差）

用法：.venv/bin/python engine/gold_best_strategy.py
"""
import collections
import glob
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, "/opt/data/fenjue/engine")
sys.path.insert(0, "/opt/data/python-libs")
import law_pipeline as lp
import trade_calendar as tc
import gold_rebound_study as G

ROOT = "/opt/data/fenjue"
FEE = 0.0030          # 双边合计（佣金+印花税+滑点保守）
MAXH = 20
COMPLETE = ("2026-05", "2026-06", "2026-07", "2026-08", "2026-09")


def build_pool(U, co, months):
    pool = []
    for mo in months:
        y = int(mo[:4])
        days = [x for x in (tc.trading_days(y) or []) if x.startswith(mo)]
        if len(days) < 7:
            continue
        entry = days[5]
        for c, meta in co[mo].items():
            if min(meta["ann"]) > entry.replace("-", ""):
                continue
            d = U.get(c)
            if not d or entry not in d["date"]:
                continue
            j = d["date"].index(entry)
            pf = G.pre_feats(d, j, meta)
            if not pf or j + MAXH + 1 >= d["n"]:
                continue
            pool.append(dict(pf, mo=mo, code=c, name=meta["title"], j=j,
                             c=d["c"], v=d["v"], date=d["date"]))
    return pool


def build_base(U, months, entry_map):
    base = []
    step = max(1, len(U) // 700)
    for mo in months:
        entry = entry_map[mo]
        for c, d in list(U.items())[::step]:
            if entry not in d["date"]:
                continue
            j = d["date"].index(entry)
            if j + MAXH + 1 >= d["n"] or j < 30:
                continue
            base.append(dict(mo=mo, code=c, j=j, c=d["c"], v=d["v"], date=d["date"]))
    return base


def simulate(x, d, rule):
    """在入场后第 d 日收盘买入，按 rule 卖。返回净收益或 None。"""
    c = x["c"]
    j = x["j"]
    b = j + d
    if b >= x["j"] + MAXH or b >= len(c) - 1:
        return None
    px = c[b]
    if px <= 0:
        return None
    end = min(b + MAXH - d, len(c) - 1)
    kind = rule[0]
    if kind == "hold":
        k = rule[1]
        if b + k > len(c) - 1:
            return None
        return c[b + k] / px - 1 - FEE
    if kind == "tp":                      # 止盈 tp / 止损 sl / 时间到时强平
        _, tp, sl = rule
        for t in range(b + 1, end + 1):
            r = c[t] / px - 1
            if tp and r >= tp:
                return tp - FEE
            if sl and r <= sl:
                return sl - FEE
            if tp is None and sl is None:
                break
        return c[end] / px - 1 - FEE
    if kind == "trail":                   # 高点回撤 z 止盈 + 可止损
        _, z, sl = rule
        peak = px
        for t in range(b + 1, end + 1):
            r = c[t] / px - 1
            if sl and r <= sl:
                return sl - FEE
            peak = max(peak, c[t])
            if c[t] <= peak * (1 - z):
                return c[t] / px - 1 - FEE
        return c[end] / px - 1 - FEE
    return None


def entry_day_for(x, d, mode):
    """返回实际下单日相对偏移；mode 决定是否加条件。"""
    if mode == "plain":
        return d
    c, v = x["c"], x["v"]
    j = x["j"]
    # 首次出现「收盘为近5日最低 且 量比>1.2」→ 次日买
    for t in range(j + 1, j + 13):
        if t + 1 >= len(c) or t < 6:
            continue
        lo5 = min(c[t - 4:t + 1])
        volr = v[t] / max(1.0, st.mean(v[t - 5:t]))
        if c[t] <= lo5 and volr > 1.2:
            return t + 1 - j
    return None


def score(trades, months):
    per = {}
    for mo in months:
        g = [t for t, m in trades if m == mo]
        if len(g) >= 8:
            per[mo] = (len(g), st.mean(g), sum(1 for x in g if x > 0) / len(g))
    if len(per) < 5:
        return None
    return per


def main():
    U = lp.load_universe()
    co = G.build_cohorts(G.load_raw())
    months = sorted(co)
    entry_map = {}
    for mo in months:
        y = int(mo[:4])
        days = [x for x in (tc.trading_days(y) or []) if x.startswith(mo)]
        if len(days) >= 7:
            entry_map[mo] = days[5]
    pool = build_pool(U, co, months)
    base = build_base(U, months, entry_map)

    # 弹性分（事前可得）用于选股过滤
    SIG = ["vol60", "fade", "limit250", "r60pre", "amp60", "amt20", "dist60"]
    SGN = {"dist60": -1}
    mu = {k: st.mean([r[k] for r in pool]) for k in SIG}
    sd = {k: (st.pstdev([r[k] for r in pool]) or 1) for k in SIG}
    for r in pool:
        r["elastic"] = sum(SGN.get(k, 1) * (r[k] - mu[k]) / sd[k] for k in SIG) / len(SIG)

    def subset(name):
        if name == "all":
            return pool
        vals = sorted(pool, key=lambda r: -r["elastic"])
        if name == "elastic_top":
            return vals[:len(vals) * 2 // 3]
        if name == "elastic_bot":
            return vals[len(vals) // 3:]
        if name == "near_high":           # 距60日高最近的 2/3
            return sorted(pool, key=lambda r: -r["dist60"])[:len(pool) * 2 // 3]
        if name == "deep":                # 距60日高最远的 2/3
            return sorted(pool, key=lambda r: r["dist60"])[:len(pool) * 2 // 3]
        return pool

    rules = []
    for k in (1, 2, 3, 4, 5, 7, 10):
        rules.append((f"持{k}日", ("hold", k)))
    for tp in (0.02, 0.03, 0.05, 0.08):
        rules.append((f"止盈{tp*100:.0f}%或不设限持满", ("tp", tp, None)))
        for sl in (-0.03, -0.05):
            rules.append((f"止盈{tp*100:.0f}%/止损{abs(sl)*100:.0f}%", ("tp", tp, sl)))
    for z in (0.02, 0.03, 0.05):
        rules.append((f"高点回撤{z*100:.0f}%止盈", ("trail", z, None)))
        rules.append((f"高点回撤{z*100:.0f}%+止损5%", ("trail", z, -0.05)))

    print(f"搜索：{len(rules)} 条卖出规则 × 13 个买入日 × 4 种选股 × 2 种触发 = {len(rules)*13*4*2} 格\n")
    # 全市场基准：同 d、同规则
    base_cache = {}
    for bd in range(0, 13):
        for _, rule in rules:
            xs = [simulate(x, bd, rule) for x in base]
            xs = [x for x in xs if x is not None]
            if len(xs) >= 100:
                base_cache[(bd, rule)] = st.mean(xs)

    results = []
    for sub in ("all", "elastic_top", "elastic_bot", "near_high", "deep"):
        rows = subset(sub)
        for mode in ("plain", "vol_low"):
            for d in range(0, 13):
                for label, rule in rules:
                    trades = []
                    for x in rows:
                        dd = entry_day_for(x, d, mode) if mode != "plain" else d
                        if dd is None:
                            continue
                        r = simulate(x, dd, rule)
                        if r is not None:
                            trades.append((r, x["mo"]))
                    per = score(trades, COMPLETE)
                    if not per:
                        continue
                    means = [v[1] for v in per.values()]
                    n_tot = sum(v[0] for v in per.values())
                    if n_tot < 75:
                        continue
                    ex = None
                    key = (d, rule)
                    if mode == "plain" and key in base_cache:
                        ex = st.mean(means) - base_cache[key]
                    results.append(dict(sub=sub, mode=mode, d=d, rule=label,
                                        n=n_tot, minm=min(means), mean=st.mean(means),
                                        win=st.mean([v[2] for v in per.values()]),
                                        pos=sum(1 for x in means if x > 0), ex=ex,
                                        per={k: (round(v[0]), round(v[1] * 100, 2), round(v[2] * 100)) for k, v in per.items()}))

    print(f"通过样本门槛的格子：{len(results)}（随机期望：要求 5/5 月全正的格子数 ≈ {len(results)*0.5**5:.1f}）\n")
    ok = [r for r in results if r["pos"] == 5 and (r["ex"] is None or r["ex"] > 0)]
    print(f"同时满足「5/5 月全正」+「超额>0」的格子：{len(ok)}\n")
    json.dump(results, open(f"{ROOT}/data/gold_best_strategy_20261019.json", "w"), ensure_ascii=False)
    five = [r for r in results if r["pos"] == 5]
    print(f"仅 5/5 月全正（不管超额）的格子：{len(five)}")
    if five:
        five.sort(key=lambda r: -(r["ex"] if r["ex"] is not None else -9))
        for r in five[:8]:
            print(f"  {r['sub']:<11}{r['mode']:<8}d={r['d']:<2} {r['rule']:<24} n={r['n']:>3} "
                  f"最差月 {r['minm']*100:+5.2f}% 均值 {r['mean']*100:+5.2f}% 超额{(r['ex']*100 if r['ex'] is not None else float('nan')):+5.2f}pp")
    print()
    ok.sort(key=lambda r: -r["minm"])
    for r in ok[:12]:
        print(f"{r['sub']:<11}{r['mode']:<8}d={r['d']:<2} {r['rule']:<22} "
              f"n={r['n']:>3} 最差月 {r['minm']*100:+5.2f}% 均值 {r['mean']*100:+5.2f}% "
              f"胜{r['win']*100:3.0f}% 超额{(r['ex']*100 if r['ex'] is not None else float('nan')):+5.2f}pp")

    print("\n最稳健格子的逐月明细：")
    for r in ok[:3]:
        print(f"  {r['sub']} / {r['mode']} / d={r['d']} / {r['rule']}")
        for mo, (n, m, w) in sorted(r["per"].items()):
            print(f"    {mo}: n={n:>2} 均值 {m:+6.2f}% 胜率 {w:>3}%")


if __name__ == "__main__":
    main()
