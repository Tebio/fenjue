#!/usr/bin/env python3
"""engine/downtrend_raid7.py — 下跌中继突袭：深度子集 ± 聚类日剥离（stage 7，终审）

stage3/4/5/6 已定：
  · 中继全样本正超额只是「抱团日」现象，且 5 天吃掉 96.5% 贡献（2024-02-08 一天 46.7%）
  · 日历时间法（真 t_NW）给 负
  · 唯一单调分层是「距 MA60 深度」

本版回答最后一问：把深度子集（≈底部出清条件）单独拿出来，它是否也只是聚类日现象？
  A 深度子集（<=-35% / -25~-35%）的日历时间 t_NW
  B 剔除 2024-02-08/02-19 等超大聚类日后，各深度档的日级配对边际
  C 中继深档 vs 底部出清（≤MA60×0.65）事件集的重合度
"""
import json
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp
from downtrend_raid import (ROOT, load_compact, collect, fwd, stats, raid_big7,
                            bottom_flush_big7, START, FEE)

HS = [1, 5, 20]


def main():
    stocks, cal = load_compact()
    print("stocks:", len(stocks), flush=True)

    all_sum = {h: defaultdict(float) for h in HS}; all_cnt = {h: defaultdict(int) for h in HS}
    ctx_sum = {h: defaultdict(float) for h in HS}; ctx_cnt = {h: defaultdict(int) for h in HS}
    for code, d in stocks.items():
        c, o, ma, n = d["c"], d["o"], d["ma60"], d["n"]
        for i in range(START, n - max(HS) - 1):
            ep = o[i + 1]
            if ep <= 0:
                continue
            dt = d["date"][i]
            r0 = c[i - 1] > 0 and (c[i] / c[i - 1] - 1 >= 0.07)
            ctx = (ma[i] is not None and ma[i - 5] is not None and ma[i] < ma[i - 5]
                   and c[i] <= ma[i])
            for h in HS:
                r = c[i + h] / ep - 1 - FEE
                all_sum[h][dt] += r; all_cnt[h][dt] += 1
                if ctx and not r0:
                    ctx_sum[h][dt] += r; ctx_cnt[h][dt] += 1
    allm = {h: {dt: all_sum[h][dt] / all_cnt[h][dt] for dt in all_sum[h]} for h in HS}
    ctxm = {h: {dt: ctx_sum[h][dt] / ctx_cnt[h][dt] for dt in ctx_sum[h]} for h in HS}
    print("daily means done", flush=True)

    ev = collect(stocks, xs=None, det=raid_big7)
    print("中继大涨7 events:", len(ev), flush=True)
    for e in ev:
        d = stocks[e["code"]]
        ma = d["ma60"][e["i"]]
        e["depth"] = (d["c"][e["i"]] / ma - 1) if ma else None
    evb = collect(stocks, xs=None, det=bottom_flush_big7)
    print("底部出清大涨7 events:", len(evb), flush=True)
    key_b = {(e["code"], e["i"]) for e in evb}
    key_a = {(e["code"], e["i"]) for e in ev}
    print("重合 |A∩B| =", len(key_a & key_b), " A-B =", len(key_a - key_b), " B-A =", len(key_b - key_a), flush=True)

    def caltime(events, hs=HS):
        byd = defaultdict(list)
        for e in events:
            byd[e["date"]].append(e)
        out = {}
        for h in hs:
            ser = []
            for dt in sorted(byd):
                if dt not in allm[h]:
                    continue
                rs = [fwd(stocks[e["code"]], e["i"], h) for e in byd[dt]]
                rs = [r for r in rs if r is not None]
                if rs:
                    ser.append(st.mean(rs) - allm[h][dt])
            if len(ser) < 30:
                out["T+%d" % h] = {"天数": len(ser), "不足": True}
                continue
            s = stats(ser)
            out["T+%d" % h] = {"天数": len(ser), "日均超额%": s["mean%"], "日胜率%": s["win%"],
                               "t_朴素": s["t"], "t_NW": lp.nw_t(ser, h)}
        return out

    def paired_daily(events, drop_days=(), hs=HS):
        """日级配对边际 = 逐日(事件股均值 - 同语境非事件股均值) 的日序列 NW t"""
        byd = defaultdict(list)
        for e in events:
            if e["date"] in drop_days:
                continue
            byd[e["date"]].append(e)
        out = {}
        for h in hs:
            ser = []
            for dt in sorted(byd):
                if dt not in ctxm[h]:
                    continue
                rs = [fwd(stocks[e["code"]], e["i"], h) for e in byd[dt]]
                rs = [r for r in rs if r is not None]
                if rs:
                    ser.append(st.mean(rs) - ctxm[h][dt])
            if len(ser) < 30:
                out["T+%d" % h] = {"天数": len(ser), "不足": True}
                continue
            s = stats(ser)
            out["T+%d" % h] = {"天数": len(ser), "日均边际%": s["mean%"], "日胜率%": s["win%"],
                               "t_朴素": s["t"], "t_NW": lp.nw_t(ser, h)}
        return out

    print("\n=== A 各档的日历时间（对全宇宙） ===")
    A = {}
    for lo, hi, name in [(-9, -0.25, "深档<=-25%"), (-9, -0.35, "极深<=-35%"),
                         (-0.25, -0.15, "中-15~-25%"), (-0.15, 9, "浅>-15%")]:
        sub = [e for e in ev if e["depth"] is not None and lo <= e["depth"] < hi]
        A[name] = {"n": len(sub), **caltime(sub)}
        print("  %-14s n=%5d  %s" % (name, len(sub), json.dumps({k: v for k, v in A[name].items() if k != "n"}, ensure_ascii=False)), flush=True)
    A["底部出清大涨7"] = {"n": len(evb), **caltime(evb)}
    print("  %-14s n=%5d  %s" % ("底部出清大涨7", len(evb), json.dumps({k: v for k, v in A["底部出清大涨7"].items() if k != "n"}, ensure_ascii=False)), flush=True)

    print("\n=== B 剔除超大聚类日后的日级配对边际 ===")
    kday = defaultdict(int)
    for e in ev:
        kday[e["date"]] += 1
    top = sorted(kday, key=lambda d: -kday[d])[:5]
    print("  剔除日:", [(d, kday[d]) for d in top], flush=True)
    B = {}
    for tag, sub, drop in (
            ("全样本", ev, ()),
            ("全样本_剔前5聚类日", ev, tuple(top)),
            ("极深<=-35%", [e for e in ev if e["depth"] is not None and e["depth"] < -0.35], ()),
            ("极深<=-35%_剔前5聚类日", [e for e in ev if e["depth"] is not None and e["depth"] < -0.35], tuple(top)),
            ("中段-15~-35%", [e for e in ev if e["depth"] is not None and -0.35 <= e["depth"] < -0.15], ()),
            ("中段-15~-35%_剔前5聚类日", [e for e in ev if e["depth"] is not None and -0.35 <= e["depth"] < -0.15], tuple(top)),
            ("浅>-15%", [e for e in ev if e["depth"] is not None and e["depth"] >= -0.15], ()),
            ("底部出清大涨7", evb, ()),
            ("底部出清大涨7_剔前5聚类日", evb, tuple(top)),
    ):
        if len(sub) < 60:
            print("  %-26s n=%d 样本不足" % (tag, len(sub))); continue
        B[tag] = {"n": len(sub), **paired_daily(sub, drop)}
        r = B[tag].get("T+5", {})
        print("  %-26s n=%5d  T+5 天数=%s 日均边际=%s%% 日胜率=%s%% t_NW=%s" % (
            tag, len(sub), r.get("天数"), r.get("日均边际%"), r.get("日胜率%"), r.get("t_NW")), flush=True)

    out = {"重合": {"A∩B": len(key_a & key_b), "A-B": len(key_a - key_b), "B-A": len(key_b - key_a)},
           "A_分档日历时间": A, "B_日级配对边际": B, "剔除日": [(d, kday[d]) for d in top]}
    (ROOT / "data/downtrend_raid_stage7.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved stage7")


if __name__ == "__main__":
    main()
