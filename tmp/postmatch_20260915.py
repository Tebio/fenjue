#!/usr/bin/env python3
"""postmatch_20260915.py — 盲测赛后对账 + 问题清单清剿（2026-09-19）。

Q1 赛后对账：4 只盲测票 9/16 开盘买 → 9/16/17/18 走势 + T1 强度判定 + 黑名单形态检查
Q2 本周成簇日：9/14-9/18 每日底座信号数
Q3 美能能源(001299) 黑名单形态扫描（剧震/高位避雷针/连板链）
Q6 组合抢钱：历史上多组合同日同票重合率
Q8 金健预警器：当前（9/18）处于「低位首板后回踩期」的票（观察源非买点）
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent
FEE = 0.0015
PICKS = ["603983", "605188", "002059", "000430"]


def q1(stocks):
    print("== Q1 赛后对账（9/16 开盘买）==")
    for code in PICKS:
        d = stocks.get(code)
        if not d:
            print(f"{code} 无数据"); continue
        idx = {x: j for j, x in enumerate(d["date"])}
        e = idx.get("2026-09-16")
        if e is None:
            print(f"{code} 9/16 无 bar"); continue
        ent = d["o"][e]
        rows = []
        for dt in ("2026-09-16", "2026-09-17", "2026-09-18"):
            j = idx.get(dt)
            if j is not None:
                rows.append(f"{dt[5:]} 收{d['c'][j]:.2f}({(d['c'][j]/ent-1)*100:+.1f}%)")
        t1 = (d["c"][e] / ent - 1) * 100
        strength = "强(≥+3%)" if t1 >= 3 else ("弱(≤-3%)" if t1 <= -3 else "平")
        # 黑名单形态检查 9/17-18：剧震（量比≥2+上影4%或大阴-4%）
        warn = []
        for dt in ("2026-09-17", "2026-09-18"):
            j = idx.get(dt)
            if j is None:
                continue
            v, c, h, o = d["v"], d["c"], d["h"], d["o"]
            base = v[j-5:j]
            mb = sum(base)/len(base) if base else 0
            vr = v[j]/mb if mb > 0 else 0
            chg = c[j]/c[j-1]-1 if c[j-1] > 0 else 0
            upper = (h[j]-c[j])/c[j] if c[j] > 0 else 0
            if vr >= 2 and (upper >= 0.04 or chg <= -0.04):
                warn.append(f"{dt[5:]}剧震(量比{vr:.1f})")
        print(f"{code}: 买{ent:.2f} | {' '.join(rows)} | T1强度={strength} | {'⚠️'+' '.join(warn) if warn else '无黑名单形态'}")


def q2(stocks):
    print("\n== Q2 本周成簇日（底座信号数/日）==")
    det = lp.REGISTRY["跌停接_MA60下"]
    cnt = defaultdict(int)
    for code, d in stocks.items():
        for i in range(61, d["n"] - 1):
            dt = d["date"][i]
            if "2026-09-14" <= dt <= "2026-09-18":
                try:
                    if det(d, i):
                        cnt[dt] += 1
                except Exception:
                    pass
    for dt in sorted(cnt, reverse=True)[:7]:
        print(f"  {dt}: {cnt[dt]} 只 {'✅成簇(K≥3)' if cnt[dt] >= 3 else '零星'}")
    if not cnt:
        print("  本周无底座信号")


def q3(stocks):
    print("\n== Q3 美能能源 001299 形态扫描 ==")
    d = stocks.get("001299")
    if not d:
        print("  无数据"); return
    idx = {x: j for j, x in enumerate(d["date"])}
    j = idx.get("2026-09-18")
    c, o, h, l, v, ma = d["c"], d["o"], d["h"], d["l"], d["v"], d["ma60"]
    print(f"  9/18 收 {c[j]:.2f}（成本 9.675 → 浮{(c[j]/9.675-1)*100:+.1f}%）")
    print(f"  位置: {'MA60上' if ma[j] and c[j] > ma[j] else 'MA60下'}（MA60={ma[j]:.2f}）" if ma[j] else "  MA60 无")
    # 近10日涨停数、今日形态
    boards = sum(1 for k in range(max(1, j-10), j+1) if c[k-1] > 0 and c[k]/c[k-1]-1 >= 0.098)
    base = v[j-5:j]
    mb = sum(base)/len(base)
    vr = v[j]/mb if mb > 0 else 0
    upper = (h[j]-c[j])/c[j]
    chg = c[j]/c[j-1]-1
    print(f"  近10日涨停 {boards} 次 | 周五量比 {vr:.2f} 涨幅 {chg*100:+.1f}% 上影 {upper*100:.1f}%")
    quake = boards >= 2 and vr >= 2 and (upper >= 0.04 or chg <= -0.04)
    print(f"  剧震黑名单触发: {'是⚠️' if quake else '否'}")
    # TD9/连跌状态
    td = sum(1 for k in range(9) if j-4-k >= 0 and c[j-k] < c[j-k-4])
    print(f"  TD9 买入计数: {td}/9")


def q6(stocks):
    print("\n== Q6 组合抢钱统计（同日同票多组合重合）==")
    combos = ["组合_跌停低_长周期_超跌20", "组合_跌停低_三连阴", "组合_跌停低_避雷针_缩量",
              "组合_跌停低_输家_超跌20_剔亏ST", "组合_跌停低_TD9买入滤"]
    fire = defaultdict(list)
    for name in combos:
        det = lp.REGISTRY[name]
        for code, d in stocks.items():
            for i in range(61, d["n"] - 1):
                try:
                    if det(d, i):
                        fire[(d["date"][i], code)].append(name)
                except Exception:
                    pass
    overlap = sum(1 for v in fire.values() if len(v) > 1)
    print(f"  组合信号总触发 {sum(len(v) for v in fire.values())}，去重日票 {len(fire)}，重合 {overlap}（{100*overlap/max(1,len(fire)):.1f}%）")
    print(f"  含义：{overlap} 个日票会被多个组合重复计数——组合间高度同源，分仓要去重")


def q8(stocks):
    print("\n== Q8 金健预警器（当前处于首板后回踩期的票，观察源非买点）==")
    watch = []
    for code, d in stocks.items():
        n = d["n"]
        if d["date"][n-1] != "2026-09-18":
            continue
        c, o, v = d["c"], d["o"], d["v"]
        # 近 3~12 日有低位放量首板，此后不破启动位，当前缩量
        for B in range(n - 3, max(60, n - 13), -1):
            if c[B] <= 0 or c[B-1] <= 0:
                continue
            if c[B]/c[B-1]-1 < 0.098:
                continue
            base = v[max(0, B-5):B]
            mb = sum(base)/len(base) if base else 0
            if mb <= 0 or v[B]/mb < 2.5:
                continue
            if any(c[k] > 0 and c[k-1] > 0 and c[k]/c[k-1]-1 >= 0.098 for k in range(max(1, B-60), B)):
                continue
            if min(c[B+1:n]) < o[B] * 0.97:
                continue
            watch.append((code, d["date"][B], round(c[n-1]/c[B]-1, 3)))
            break
    for code, bd, ret in sorted(watch, key=lambda x: -x[2])[:10]:
        print(f"  {code} 首板日{bd} 首板以来{ret*100:+.1f}%")
    print(f"  共 {len(watch)} 只（N字买点已证伪，此名单仅作二波启动预警观察源）")


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    q1(stocks); q2(stocks); q3(stocks); q6(stocks); q8(stocks)


if __name__ == "__main__":
    main()
