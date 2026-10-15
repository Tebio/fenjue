#!/usr/bin/env python3
"""engine/downtrend_raid3.py — 下跌中继突袭：分层轴 + 条件内对照（stage 3）

回答三个问题：
  ⓑ 与「底部出清后大涨」的判别边界：同一批信号按「已砸深度」分档看单调性
  ⓒ 事前可识别分层：量能（个股量比/全市场额比）、板块联动（行业涨停家数/是否行业首板）、
     深度（距 MA60 / 前 20 日跌幅 / 距 120 日高）、市值五档、regime

每一格都同时给：
  · raw（事件样本 T+N 均值/胜率）
  · **条件内对照**（同股、同位置「MA60 下方且 MA60 下行」的非事件日 T+N 均值）——
    位置匹配对照的对照组必须卡在同类条件内，只剔位置会漏掉条件本身的 beta（AGENTS 三级终审②）
"""
import json
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, "/opt/data/fenjue/engine")
from downtrend_raid import (ROOT, HORIZONS, load_compact, build_xs, collect, fwd,
                            stats, odds, raid_big7, load_cap_month, cap_at)

HS = [1, 5, 20]
DET = raid_big7


def main():
    stocks, cal = load_compact()
    print("stocks:", len(stocks), flush=True)
    xs = build_xs(stocks, cal)
    packed, qs = load_cap_month(stocks)
    print("cap loaded:", len(packed), flush=True)
    idx_amt = {x["date"]: x["volume"] for x in json.loads((ROOT / "data/index_sh000001.json").read_text())}
    cal_list = sorted(idx_amt)
    amt_ma20 = {}
    for k, dt in enumerate(cal_list):
        if k >= 20:
            amt_ma20[dt] = sum(idx_amt[cal_list[j]] for j in range(k - 20, k)) / 20

    def feats(code, d, i):
        c, v, ma = d["c"], d["v"], d["ma60"]
        dt = d["date"][i]
        vr = None
        if i >= 25:
            b = v[i - 20:i]
            if all(x > 0 for x in b):
                mb = sum(b) / 20
                vr = v[i] / mb if mb > 0 else None
        amt_ratio = (idx_amt[dt] / amt_ma20[dt]) if (dt in amt_ma20 and amt_ma20[dt] > 0) else None
        ind = xs["code2ind"].get(code, "?")
        lad = xs["lad"].get(dt, {}).get(ind, 0)
        # 是否行业内今日首个涨停（行业涨停数==1）
        first_ind = (lad == 1)
        depth60 = (c[i] / ma[i] - 1) if (ma[i] and ma[i] > 0) else None
        drop20 = (c[i] / c[i - 20] - 1) if (i >= 20 and c[i - 20] > 0) else None
        ret120 = (c[i] / c[i - 120] - 1) if (i >= 120 and c[i - 120] > 0) else None
        cap = cap_at(packed, code, dt)
        q = None
        b = qs.get(dt[:7] + "-01")
        if cap is not None and b:
            q = sum(cap > x for x in b)
        ret = (c[i] / c[i - 1] - 1) if c[i - 1] > 0 else None
        return {"vr": vr, "amt_ratio": amt_ratio, "ladder": lad, "first_ind": first_ind,
                "depth60": depth60, "drop20": drop20, "ret120": ret120, "capq": q,
                "regime": xs["regime"].get(dt), "ret": ret}

    print("collecting events…", flush=True)
    ev = collect(stocks, xs, DET)
    for e in ev:
        e.update(feats(e["code"], stocks[e["code"]], e["i"]))
    print("events:", len(ev), flush=True)

    # 条件内对照池：同股「MA60 下方 + MA60 下行」的非事件日（位置+语境双匹配），
    # 同时收集与事件同日的全市场额比/regime 分档，便于同条件内公平比较。
    print("building condition-matched control pool…", flush=True)
    ctl = defaultdict(list)   # axis -> [T+N 收益]
    ctl_by = defaultdict(lambda: defaultdict(list))   # (axis, bucket) -> [ret]
    for code, d in stocks.items():
        c, ma, n = d["c"], d["ma60"], d["n"]
        for i in range(65, n - max(HS) - 1):
            if d["o"][i + 1] <= 0:
                continue
            if ma[i] is None or ma[i - 5] is None or c[i - 20] <= 0:
                continue
            if not (ma[i] < ma[i - 5] and c[i] <= ma[i]):      # 与事件同语境
                continue
            if DET(d, i):                                      # 事件日不入对照
                continue
            f = feats(code, d, i)
            if f["ret"] is not None and f["ret"] >= 0.07:       # 大涨日也不入对照（对照=无事件）
                continue
            for h in HS:
                r = fwd(d, i, h)
                if r is None:
                    continue
                ctl[h].append(r)
                for axis, key in _buckets(f):
                    ctl_by[(axis, key)][h].append(r)
    print("control pool:", {h: len(ctl[h]) for h in HS}, flush=True)

    AXES = {
        "量比(个股5日)": lambda f: _band(f["vr"], [(0, 1, "<1"), (1, 2, "1-2"), (2, 4, "2-4"), (4, 1e9, ">4")]),
        "全市场额比(20日)": lambda f: _band(f["amt_ratio"], [(0, 0.8, "<0.8缩"), (0.8, 1.2, "0.8-1.2常"), (1.2, 1.6, "1.2-1.6放"), (1.6, 1e9, ">1.6巨")]),
        "行业涨停梯队": lambda f: _band(f["ladder"], [(0, 1, "0"), (1, 2, "1"), (2, 3, "2"), (3, 1e9, ">=3")]),
        "行业内首板": lambda f: "行业首板(该行业今日仅此1板)" if f["first_ind"] else ("行业多板(>=2)" if f["ladder"] >= 2 else "?"),
        "距MA60深度": lambda f: _band(f["depth60"], [(-1e9, -0.35, "<=-35%"), (-0.35, -0.25, "-25~-35%"), (-0.25, -0.15, "-15~-25%"), (-0.15, 0, "-0~15%")]),
        "前20日跌幅": lambda f: _band(f["drop20"], [(-1e9, -0.30, "<=-30%"), (-0.30, -0.20, "-20~-30%"), (-0.20, -0.10, "-10~-20%")]),
        "距120日高": lambda f: _band(f["ret120"], [(-1e9, -0.45, "<=-45%"), (-0.45, -0.30, "-30~-45%"), (-0.30, -0.15, "-15~-30%"), (-0.15, 1e9, ">-15%")]),
        "市值五分位": lambda f: "Q%d" % (f["capq"] + 1) if f["capq"] is not None else None,
        "regime": lambda f: f["regime"],
    }
    out = {"n_events": len(ev), "n_control": {h: len(ctl[h]) for h in HS}, "axes": {}}
    for axis, fn in AXES.items():
        buckets = defaultdict(lambda: defaultdict(list))
        for e in ev:
            k = fn(e)
            if k is None:
                continue
            for h in HS:
                r = fwd(stocks[e["code"]], e["i"], h)
                if r is not None:
                    buckets[k][h].append(r)
        rows = {}
        print("\n=== %s ===" % axis, flush=True)
        for k in sorted(buckets, key=lambda x: str(x)):
            row = {}
            txt = "  %-28s" % k
            for h in HS:
                s = stats(buckets[k][h])
                cs = stats(ctl_by.get((axis, k), {}).get(h, []))
                row[f"T+{h}"] = {"sig": s, "ctl": cs,
                                 "margin_pp": (round(s["mean%"] - cs["mean%"], 2)
                                               if s and cs else None)}
                if s:
                    mm = row[f"T+{h}"]["margin_pp"]
                    txt += "  T+%-2d %5.1f%%/%+5.2f%% (n=%4d, ctl%+5.2f%%, 边际%+5.2f%%%s)" % (
                        h, s["win%"], s["mean%"], s["n"],
                        cs["mean%"] if cs else 0, mm if mm is not None else 0,
                        "" if (mm is not None and mm > 1.5) else " ")
            print(txt, flush=True)
            rows[k] = row
        out["axes"][axis] = rows
    dst = ROOT / "data/downtrend_raid_stage3.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved", dst)


def _band(x, bands):
    if x is None:
        return None
    for lo, hi, name in bands:
        if lo is None or x >= lo:
            if hi is None or x < hi:
                return name
    return None


def _buckets(f):
    out = []
    out.append(("量比(个股5日)", _band(f["vr"], [(0, 1, "<1"), (1, 2, "1-2"), (2, 4, "2-4"), (4, 1e9, ">4")])))
    out.append(("全市场额比(20日)", _band(f["amt_ratio"], [(0, 0.8, "<0.8缩"), (0.8, 1.2, "0.8-1.2常"), (1.2, 1.6, "1.2-1.6放"), (1.6, 1e9, ">1.6巨")])))
    out.append(("行业涨停梯队", _band(f["ladder"], [(0, 1, "0"), (1, 2, "1"), (2, 3, "2"), (3, 1e9, ">=3")])))
    out.append(("行业内首板", "行业首板(该行业今日仅此1板)" if f["first_ind"] else ("行业多板(>=2)" if f["ladder"] >= 2 else "?")))
    out.append(("距MA60深度", _band(f["depth60"], [(-1e9, -0.35, "<=-35%"), (-0.35, -0.25, "-25~-35%"), (-0.25, -0.15, "-15~-25%"), (-0.15, 0, "-0~15%")])))
    out.append(("前20日跌幅", _band(f["drop20"], [(-1e9, -0.30, "<=-30%"), (-0.30, -0.20, "-20~-30%"), (-0.20, -0.10, "-10~-20%")])))
    out.append(("距120日高", _band(f["ret120"], [(-1e9, -0.45, "<=-45%"), (-0.45, -0.30, "-30~-45%"), (-0.30, -0.15, "-15~-30%"), (-0.15, 1e9, ">-15%")])))
    out.append(("市值五分位", "Q%d" % (f["capq"] + 1) if f["capq"] is not None else None))
    out.append(("regime", f["regime"]))
    return [(a, k) for a, k in out if k is not None]


if __name__ == "__main__":
    main()
