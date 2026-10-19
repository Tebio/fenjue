#!/usr/bin/env python3
"""涨停前一日能不能选出来（用户：欢瑞/沃特/亨通/冰雪反推，要在涨停前一天选出共性）。

口径：
  · 特征日 t = 交易日收盘，只用 t 及以前的数据（PIT）
  · label = 下一交易日涨幅 > 9.7%（主板涨停）
  · 样本 = 主板全库 2025-09-08 ~ 2026-09-22
  · 「吃到」= t+1 开盘买 → t+1 收盘卖（追首板日） / t+2 收盘卖（持两天），扣费 0.30%
用法：.venv/bin/python engine/limitup_prevday_study.py
"""
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
sys.path.insert(0, "/opt/data/python-libs")
import law_pipeline as lp

BEG, END = "2025-09-08", "2026-09-22"
LIMIT = 0.097
KEYS = ["r1", "r5", "r20", "dist60", "pos60", "distma20", "vr", "vol60", "amp", "down", "lim20", "amt"]


def feats(d, i):
    c, o, h, l, v = d["c"], d["o"], d["h"], d["l"], d["v"]
    if i < 65 or c[i - 1] <= 0:
        return None
    hi60 = max(h[i - 59:i + 1])
    lo60 = min(l[i - 59:i + 1])
    ma20 = sum(c[i - 19:i + 1]) / 20
    v5 = sum(v[i - 5:i]) / 5 or 1
    r = [c[k] / c[k - 1] - 1 for k in range(i - 59, i + 1) if c[k - 1] > 0]
    dn, k = 0, i
    while k > i - 10 and c[k] < c[k - 1]:
        dn += 1
        k -= 1
    lim20 = sum(1 for k in range(i - 19, i + 1) if c[k] / c[k - 1] - 1 > LIMIT)
    return dict(r1=c[i] / c[i - 1] - 1,
                r5=c[i] / c[i - 5] - 1 if c[i - 5] > 0 else 0,
                r20=c[i] / c[i - 20] - 1 if c[i - 20] > 0 else 0,
                dist60=c[i] / hi60 - 1,
                pos60=(c[i] - lo60) / (hi60 - lo60) if hi60 > lo60 else 0.5,
                distma20=c[i] / ma20 - 1,
                vr=v[i] / v5,
                vol60=st.pstdev(r) if len(r) > 30 else 0,
                amp=(h[i] - l[i]) / c[i - 1],
                down=dn, lim20=lim20, amt=v[i] * c[i] / 1e8)


def collect(U):
    cand = []
    nd = set()
    for c, d in U.items():
        if c[:2] not in ("60", "00"):
            continue
        n, dates = d["n"], d["date"]
        for i in range(65, n - 2):
            day = dates[i]
            if day < BEG or day > END:
                continue
            f = feats(d, i)
            if not f:
                continue
            nxt = d["c"][i + 1] / d["c"][i] - 1
            o1 = d["o"][i + 1]
            cand.append({"code": c, "day": day, "f": f, "lab": 1 if nxt > LIMIT else 0,
                         "r_d1": (d["c"][i + 1] / o1 - 1 - 0.003) if o1 > 0 else None,
                         "r_d2": (d["c"][i + 2] / o1 - 1 - 0.003) if o1 > 0 else None,
                         "r_c2": (d["c"][i + 2] / d["c"][i + 1] - 1 - 0.003) if d["c"][i + 1] > 0 else None})
            nd.add(day)
    return cand, len(nd)


def main():
    U = lp.load_universe()
    cand, nd = collect(U)
    base = sum(x["lab"] for x in cand) / len(cand)
    print(f"样本 {len(cand)} 股票日 / {nd} 个交易日，次日涨停 {sum(x['lab'] for x in cand)} 个，"
          f"基础率 {base*100:.2f}%（日均 {sum(x['lab'] for x in cand)/nd:.1f} 只）\n")

    print("① 单特征五分位（命中率(lift)  |  次日开盘买当日卖  |  次日开盘买持2日）")
    for k in KEYS:
        vals = sorted(x["f"][k] for x in cand)
        qs = [vals[int(len(vals) * p)] for p in (0.2, 0.4, 0.6, 0.8)]
        groups = [[] for _ in range(5)]
        for x in cand:
            idx = 0
            while idx < 4 and x["f"][k] >= qs[idx]:
                idx += 1
            groups[idx].append(x)
        line = f"  {k:<9}"
        for g in groups:
            if not g:
                line += "|     -         "
                continue
            hit = sum(1 for y in g if y["lab"]) / len(g)
            d1 = [y["r_d1"] for y in g if y["r_d1"] is not None]
            d2 = [y["r_d2"] for y in g if y["r_d2"] is not None]
            line += f"| {hit*100:4.1f}%({hit/base:3.1f}x) {st.mean(d1)*100:+5.2f}/{st.mean(d2)*100:+5.2f} "
        print(line)

    print("\n② 可执行规则（条件全部在特征日收盘可知）")
    print(f"{'规则':<40}{'每日候选':>8}{'命中率':>8}{'lift':>6}{'开→收':>8}{'开→T+2':>9}{'正收益占比':>9}")
    RULES = [
        ("全部（基础率）", lambda f: True),
        ("深跌 dist60<-30%", lambda f: f["dist60"] < -0.30),
        ("深跌+缩量 vr<0.8", lambda f: f["dist60"] < -0.30 and f["vr"] < 0.8),
        ("深跌+缩量+当日跌", lambda f: f["dist60"] < -0.30 and f["vr"] < 0.8 and f["r1"] < 0),
        ("深跌+缩量+连跌≥2", lambda f: f["dist60"] < -0.30 and f["vr"] < 0.8 and f["down"] >= 2),
        ("深跌+缩量+20日无板", lambda f: f["dist60"] < -0.30 and f["vr"] < 0.8 and f["lim20"] == 0),
        ("深跌+缩量+振幅<3%", lambda f: f["dist60"] < -0.30 and f["vr"] < 0.8 and f["amp"] < 0.03),
        ("低位横盘 pos60<0.25", lambda f: f["pos60"] < 0.25),
        ("低位横盘+缩量", lambda f: f["pos60"] < 0.25 and f["vr"] < 0.8),
        ("低位+缩量+小振幅", lambda f: f["pos60"] < 0.25 and f["vr"] < 0.8 and f["amp"] < 0.03),
        ("低位+缩量+无板+小振幅", lambda f: f["pos60"] < 0.25 and f["vr"] < 0.8 and f["lim20"] == 0 and f["amp"] < 0.03),
        ("曾涨停 lim20≥1 + 缩量", lambda f: f["lim20"] >= 1 and f["vr"] < 0.8),
        ("曾涨停 + 深跌", lambda f: f["lim20"] >= 1 and f["dist60"] < -0.25),
        ("放量上涨 vr>1.5 & r1>3%", lambda f: f["vr"] > 1.5 and f["r1"] > 0.03),
    ]
    for lab, fn in RULES:
        g = [x for x in cand if fn(x["f"])]
        if not g:
            print(f"  {lab:<38}{0:>8}")
            continue
        hit = sum(1 for x in g if x["lab"]) / len(g)
        d1 = [x["r_d1"] for x in g if x["r_d1"] is not None]
        d2 = [x["r_d2"] for x in g if x["r_d2"] is not None]
        c2 = [x["r_c2"] for x in g if x["r_c2"] is not None]
        print(f"  {lab:<38}{len(g)/nd:>8.1f}{hit*100:>7.2f}%{hit/base:>5.1f}x"
              f"{st.mean(d1)*100:>7.2f}%{st.mean(d2)*100:>8.2f}%"
              f"{sum(1 for y in c2 if y>0)/len(c2)*100:>8.0f}%")
        # 命中子样本（次日真涨停的那些）
        hitg = [x for x in g if x["lab"]]
        if hitg:
            h2 = [x["r_c2"] for x in hitg if x["r_c2"] is not None]
            print(f"      └ 其中真涨停 {len(hitg)} 笔：T+1收盘买→T+2卖 {st.mean(h2)*100:+6.2f}%"
                  f"（正收益 {sum(1 for y in h2 if y>0)/len(h2)*100:.0f}%）")

    print("\n③ 今天（特征日 2026-10-16 收盘）这几只票长什么样")
    watch = {"000892": "欢瑞世纪(10-09/12涨停)", "002886": "沃特股份(今日涨停)",
             "600487": "亨通光电(今日炸板)", "603099": "长白山(冰雪10-13)",
             "600593": "大连圣亚(冰雪10-13)", "002639": "雪人股份(冰雪10-13)",
             "000530": "冰山冷热(冰雪四连板)"}
    for c, nm in watch.items():
        d = U.get(c)
        if not d:
            continue
        f = feats(d, d["n"] - 1)
        if not f:
            continue
        print(f"  {c} {nm:<22} 当日{f['r1']*100:+6.2f}% 5日{f['r5']*100:+6.1f}% 距60高{f['dist60']*100:+6.1f}% "
              f"pos{f['pos60']:.2f} 量比{f['vr']:.2f} 振幅{f['amp']*100:.1f}% 连跌{f['down']} 20日板{f['lim20']} 额{f['amt']:.1f}亿")


if __name__ == "__main__":
    main()
