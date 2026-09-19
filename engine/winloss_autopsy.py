#!/usr/bin/env python3
"""winloss_autopsy.py — 命中票的胜负解剖（2026-09-19 用户立项：不是差不多就完事）。

对组合命中事件逐笔算 T+5，按收益分档（大赢>+10% / 大胜>+3% / 平 / 大亏<-5%），
对比各档在信号日的特征分布，找「涨的和跌的」之间真正分开的变量。
特征（全部信号日时点可知）：量比、距MA60深度、连跌天数、60日超跌深度、跌停日是否开板
（h>c 承接痕迹）、一字跌停（h==l）、次日缺口、流通市值、peTTM/亏损、regime、年份。
另输出 top10/bottom10 具名案例供人工复盘。
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent
FEE = 0.0015
SIG = sys.argv[1] if len(sys.argv) > 1 else "组合_跌停低_三连阴"


def feats(d, i, code, fund, capm):
    c, o, h, l, v, ma = d["c"], d["o"], d["h"], d["l"], d["v"], d["ma60"]
    f = {}
    f["量比"] = lp._volratio(d, i)
    f["距MA60%"] = round((c[i] / ma[i] - 1) * 100, 1) if ma[i] else None
    f["连跌天数"] = 0
    j = i
    while j > 0 and c[j] < c[j - 1]:
        f["连跌天数"] += 1
        j -= 1
    hi60 = max(c[max(0, i - 60):i + 1])
    f["超跌深度%"] = round((c[i] / hi60 - 1) * 100, 1) if hi60 > 0 else None
    f["跌停开板"] = h[i] > c[i] * 1.001      # 盘中高于收盘=开板过（有承接/撬板）
    f["一字跌停"] = h[i] == l[i]
    f["次日缺口%"] = round((o[i + 1] / c[i] - 1) * 100, 1) if i + 1 < d["n"] else None
    cap = lp.cap_at_date(capm, code, d["date"][i])  # PIT 日频
    f["市值亿"] = cap
    fu = fund.get(code, {}).get(d["date"][i])
    f["peTTM"] = fu[0] if fu else None           # _XFUND 值=(peTTM, isST) 二元组
    f["亏损"] = (fu[0] is not None and fu[0] <= 0) if fu else None
    return f


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    regime = lp.load_regime()
    fund = lp._XFUND
    capm = lp._XCAP

    det = lp.REGISTRY[SIG]
    rows = []
    for code, d in stocks.items():
        for i in range(61, d["n"] - 7):
            try:
                if not det(d, i):
                    continue
            except Exception:
                continue
            ei = i + 1
            if d["o"][ei] <= d["c"][i] * 0.905:
                continue
            r5 = d["c"][ei + 5] / d["o"][ei] - 1 - FEE
            f = feats(d, i, code, fund, capm)
            f.update({"code": code, "date": d["date"][i], "r5": round(r5 * 100, 2),
                      "regime": regime.get(d["date"][i], "?"), "year": d["date"][i][:4]})
            rows.append(f)
    print(f"{SIG}: 事件 {len(rows)}")

    # 分档
    big_win = [r for r in rows if r["r5"] >= 10]
    win = [r for r in rows if 3 <= r["r5"] < 10]
    flat = [r for r in rows if -3 < r["r5"] < 3]
    big_loss = [r for r in rows if r["r5"] <= -5]
    print(f"大赢(≥+10%) {len(big_win)} | 中赢(+3~10) {len(win)} | 平 {len(flat)} | 大亏(≤-5%) {len(big_loss)}")

    KEYS = ["量比", "距MA60%", "连跌天数", "超跌深度%", "次日缺口%", "市值亿", "peTTM"]

    def med(rs, k):
        vs = sorted(r[k] for r in rs if r.get(k) is not None)
        return round(vs[len(vs) // 2], 2) if vs else None

    def rate(rs, k):
        vs = [r[k] for r in rs if r.get(k) is not None]
        return round(100 * sum(vs) / len(vs), 1) if vs else None

    print(f"\n{'特征':<10}{'大赢':>8}{'中赢':>8}{'平':>8}{'大亏':>8}")
    for k in KEYS:
        print(f"{k:<10}{med(big_win, k)!s:>8}{med(win, k)!s:>8}{med(flat, k)!s:>8}{med(big_loss, k)!s:>8}")
    for k in ("跌停开板", "一字跌停", "亏损"):
        print(f"{k + '率%':<10}{rate(big_win, k)!s:>8}{rate(win, k)!s:>8}{rate(flat, k)!s:>8}{rate(big_loss, k)!s:>8}")

    # regime/年份分布
    for dim in ("regime", "year"):
        print(f"\n按{dim}（大赢占比% / 大亏占比%）:")
        groups = defaultdict(lambda: [0, 0, 0])
        for r in rows:
            g = groups[r[dim]]
            g[0] += 1
            if r["r5"] >= 10:
                g[1] += 1
            if r["r5"] <= -5:
                g[2] += 1
        for k in sorted(groups):
            n, w, l = groups[k]
            print(f"  {k}: n={n} 大赢{100*w/n:.0f}% 大亏{100*l/n:.0f}%")

    # 具名案例
    rows.sort(key=lambda r: -r["r5"])
    print("\n=== 大赢案例 TOP10")
    for r in rows[:10]:
        print(f"  {r['date']} {r['code']} r5={r['r5']}% 量比{r['量比']:.1f} 距MA60 {r['距MA60%']}% 连跌{r['连跌天数']} 超跌{r['超跌深度%']}% 开板{r['跌停开板']} 市值{r['市值亿']} pe{r['peTTM']} {r['regime']}")
    print("=== 大亏案例 TOP10")
    for r in rows[-10:]:
        print(f"  {r['date']} {r['code']} r5={r['r5']}% 量比{r['量比']:.1f} 距MA60 {r['距MA60%']}% 连跌{r['连跌天数']} 超跌{r['超跌深度%']}% 开板{r['跌停开板']} 市值{r['市值亿']} pe{r['peTTM']} {r['regime']}")

    (ROOT / f"data/winloss_autopsy_{SIG}_20260919.json").write_text(
        json.dumps(rows, ensure_ascii=False))


if __name__ == "__main__":
    main()
