#!/usr/bin/env python3
"""金股「买后低点 → 卖前高点」反弹研究（2026-10-19 用户：什么票才容易涨）。

不看 T+20 终值，只看**区间内真正可交易的那一段**：
  低点 L = 入场后 1~20 日收盘最低那天；高点 H = L 之后到 T+20 的最高收盘；
  **rebound = H / L − 1**  ← 这才是「跌几天买、涨几天卖」的天花板。
再扫 25 个候选特征，找**跨月符号稳定**的「什么票容易反弹」。

特征分两层（严格区分是否当时可得）：
  A 事前可知（入场前一交易日及之前）：位置/波动/股性/流动性/券商覆盖/文本关键词
  B 低点当日可知（模拟「看到这根 K 线再买」）：跌深、跌速、量能、影线、是否跌停、大盘环境

基准：同月全市场主板同一算法的 rebound 分布（判断「金股是否更容易反弹」）。

用法：.venv/bin/python engine/gold_rebound_study.py
"""
import collections
import glob
import json
import math
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, "/opt/data/fenjue/engine")
sys.path.insert(0, "/opt/data/python-libs")
import law_pipeline as lp
import trade_calendar as tc

ROOT = "/opt/data/fenjue"
FEE = 0.0015
KW = {
    "涨价提价": ("涨价", "提价", "价格上涨", "价格中枢上移", "涨价函"),
    "产能扩产": ("产能", "扩产", "投产", "新建", "技改"),
    "新品新单": ("新品", "新产品", "新订单", "中标", "订单"),
    "国企改革": ("国企改革", "央企", "资产注入", "重组", "股权激励"),
    "高股息": ("高股息", "分红", "股息率"),
    "出海": ("出海", "海外", "出口", "全球"),
    "景气theme": ("机器人", "AI", "算力", "新能源", "半导体", "军工", "固态电池", "创新药"),
}


def load_raw():
    rows = []
    for fp in glob.glob(f"{ROOT}/data/gold_raw/*.json"):
        rows += json.load(open(fp))
    return rows


def build_cohorts(raw):
    """组合月 → 股票 → {公告日集合, 机构集合, 理由文本}；PIT 过滤在外层做。"""
    co = collections.defaultdict(lambda: collections.defaultdict(
        lambda: {"ann": set(), "broker": set(), "reason": "", "title": ""}))
    seen = set()
    for r in raw:
        c = str(r["股票代码"]).split(".")[0].zfill(6)
        if c[:2] not in ("60", "00"):
            continue
        ct = str(r["组合时间"])[:6]
        ann = str(r["公告日期"])
        k = (c, r["研究机构"], ann, ct)
        if k in seen:
            continue
        seen.add(k)
        e = co[f"{ct[:4]}-{ct[4:]}"][c]
        e["ann"].add(ann)
        e["broker"].add(r["研究机构"])
        if len(str(r.get("推荐理由", ""))) > len(e["reason"]):
            e["reason"] = str(r.get("推荐理由", ""))
        e["title"] = e["title"] or str(r.get("股票简称", c))
    return co


def rebound_path(c, j, hi_h=20):
    """j=入场日索引；L/H 在 1..20 内找。返回 dict 或 None。"""
    n = len(c)
    if j + hi_h >= n:
        return None
    seg = c[j + 1:j + 1 + hi_h]
    lo = min(seg)
    L = seg.index(lo) + 1                     # 相对入场日的第几天
    after = c[j + L:j + 1 + hi_h]             # L 当天起
    H = max(after)
    hd = after.index(H) + L
    return {"L": L, "H_day": hd, "low": lo, "high": H,
            "rebound": H / lo - 1,
            "rebound5": max(after[:6]) / lo - 1,
            "drop_to_low": lo / c[j] - 1}


def path_feats(d, j, p, e):
    c, h, l, o, v = d["c"], d["h"], d["l"], d["o"], d["v"]
    L = p["L"]
    kl = j + L
    rng = max(1e-9, h[kl] - l[kl])
    f = {
        "drop_to_low": p["drop_to_low"],
        "days_to_low": L,
        "low_day_ret": c[kl] / c[kl - 1] - 1,
        "low_day_volr": v[kl] / max(1.0, st.mean(v[kl - 5:kl])),
        "low_day_shadow": (c[kl] - l[kl]) / rng,
        "low_day_limit": 1.0 if c[kl] / c[kl - 1] - 1 <= -0.095 else 0.0,
        "mkt_at_low": e.get(d["date"][kl], 0.0),
    }
    cd = 0
    k = kl
    while k > j and c[k] < c[k - 1]:
        cd += 1
        k -= 1
    f["consec_down"] = float(cd)
    return f


def pre_feats(d, j, meta):
    if j < 260:
        return None
    c, h, l, v, o = d["c"], d["h"], d["l"], d["v"], d["o"]
    ma60 = st.mean(c[j - 60:j])
    r1 = [c[k] / c[k - 1] - 1 for k in range(j - 60, j)]
    xs = [c[k] / c[k - 1] - 1 for k in range(j - 120, j)]
    mx = st.mean(xs)
    den = sum((x - mx) ** 2 for x in xs)
    f = {
        "dist60": c[j - 1] / max(h[j - 60:j]) - 1,
        "dist250": c[j - 1] / max(h[j - 250:j]) - 1,
        "depth60": c[j - 1] / ma60 - 1,
        "vol60": st.pstdev(r1),
        "amp60": st.mean([(h[k] - l[k]) / c[k - 1] for k in range(j - 60, j)]),
        "fade": sum(1 for k in range(j - 120, j) if h[k] / c[k - 1] - 1 >= 0.03 and c[k] / h[k] - 1 <= -0.02) / 120,
        "vrec": sum(1 for k in range(j - 120, j) if l[k] / c[k - 1] - 1 <= -0.03 and c[k] / l[k] - 1 >= 0.02) / 120,
        "autocorr": (sum((xs[k] - mx) * (xs[k - 1] - mx) for k in range(1, len(xs))) / den) if den else 0.0,
        "r20pre": c[j - 1] / c[j - 21] - 1,
        "r60pre": c[j - 1] / c[j - 61] - 1,
        "amt20": st.mean([v[k] * c[k] / 1e8 for k in range(j - 20, j)]),
        "limit250": float(sum(1 for k in range(j - 250, j) if c[k] / c[k - 1] - 1 >= 0.095)),
        "price": o[j],
        "n_broker": float(len(meta["broker"])),
        "reason_len": float(len(meta["reason"])),
    }
    txt = meta["reason"]
    for name, kws in KW.items():
        f[f"kw_{name}"] = 1.0 if any(w in txt for w in kws) else 0.0
    return f


def main():
    U = lp.load_universe()
    idx = json.loads(Path(f"{ROOT}/data/index_sh000001.json").read_text())
    idates = [r["date"] for r in idx]
    ic = {r["date"]: float(r["close"]) for r in idx}
    iret = {idates[k]: ic[idates[k]] / ic[idates[k - 1]] - 1 for k in range(1, len(idates))}
    raw = load_raw()
    co = build_cohorts(raw)
    months = sorted(co)

    pool, base = [], []
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
            pf = pre_feats(d, j, meta)
            if not pf:
                continue
            p = rebound_path(d["c"], j)
            if not p:
                continue
            rec = dict(pf); rec.update(path_feats(d, j, p, iret))
            rec.update({kk: vv for kk, vv in p.items() if kk != "drop_to_low"})
            rec.update(mo=mo, code=c, name=meta["title"])
            pool.append(rec)
        step = max(1, len(U) // 700)
        for c, d in list(U.items())[::step]:
            if entry not in d["date"]:
                continue
            j = d["date"].index(entry)
            p = rebound_path(d["c"], j)
            if p:
                base.append(p)

    print(f"金股池 n={len(pool)}（2026-05~10 PIT）｜全市场基准 n={len(base)}\n")
    r = [x["rebound"] for x in pool]
    rb = [x["rebound"] for x in base]
    print("① 「买后低点 → 卖前高点」这一段有多大")
    for lab, arr in (("金股池", r), ("全市场", rb)):
        a = sorted(arr)
        print(f"  {lab}: 中位 {st.median(a)*100:+.2f}%  均值 {st.mean(a)*100:+.2f}%  "
              f"P25 {a[len(a)//4]*100:+.2f}%  P75 {a[len(a)*3//4]*100:+.2f}%  "
              f"≥5% 占 {sum(1 for x in a if x>=0.05)/len(a)*100:.0f}%  ≥10% 占 {sum(1 for x in a if x>=0.10)/len(a)*100:.0f}%")
    print(f"  金股低点出现在入场后第 {st.median([x['L'] for x in pool]):.0f} 日（中位），"
          f"低点距卖点 {st.median([x['H_day']-x['L'] for x in pool]):.0f} 个交易日（中位）")
    print(f"  跌幅中位 {st.median([x['drop_to_low'] for x in pool])*100:+.2f}%（入场→低点）")

    FEATS = [k for k in pool[0] if k not in
             ("L", "H_day", "low", "high", "rebound", "rebound5", "mo", "code", "name")]
    zname = {
        "dist60": "距60日高", "dist250": "距250日高", "depth60": "距MA60", "vol60": "日波动率",
        "amp60": "日均振幅", "fade": "冲高回落率", "vrec": "V形修复率", "autocorr": "日收益自相关",
        "r20pre": "入场前20日涨幅", "r60pre": "入场前60日涨幅", "amt20": "日均成交额",
        "limit250": "年涨停次数", "price": "股价", "n_broker": "券商覆盖数", "reason_len": "推荐理由字数",
        "drop_to_low": "入场→低点跌幅", "days_to_low": "低点出现日", "low_day_ret": "低点当日涨跌",
        "low_day_volr": "低点日量比", "low_day_shadow": "低点日下影占比", "low_day_limit": "低点日是否跌停",
        "mkt_at_low": "低点日大盘涨跌", "consec_down": "低点前连阴数",
    }
    for k in list(zname):
        if k.startswith("kw_"):
            zname[k] = "关键词:" + k[3:]

    print("\n② 25 个候选特征 × 反弹幅度（三分位：高组 − 低组），跨月同号才算稳")
    print(f"{'特征':<16}{'低组中位':>10}{'高组中位':>10}{'差(pp)':>9}{'同号月':>7}  判定")
    surv = []
    for k in FEATS:
        vals = [x[k] for x in pool if x.get(k) is not None]
        if len(set(vals)) < 3:
            continue
        try:
            q1, q2 = st.quantiles(vals, n=3)
        except Exception:
            continue
        lo = [x["rebound"] for x in pool if x[k] < q1]
        hi = [x["rebound"] for x in pool if x[k] >= q2]
        if len(lo) < 15 or len(hi) < 15:
            continue
        diffs = []
        for mo in months:
            a = [x["rebound"] for x in pool if x["mo"] == mo and x[k] < q1]
            b = [x["rebound"] for x in pool if x["mo"] == mo and x[k] >= q2]
            if len(a) >= 6 and len(b) >= 6:
                diffs.append(st.median(b) - st.median(a))
        same = sum(1 for d in diffs if d > 0) if st.median(diffs) > 0 else sum(1 for d in diffs if d < 0)
        judge = "跨月稳定" if same == len(diffs) and len(diffs) >= 4 else ("方向一致" if same >= 3 else "不稳定")
        print(f"{zname.get(k,k):<16}{st.median(lo)*100:>9.2f}%{st.median(hi)*100:>9.2f}%"
              f"{(st.median(hi)-st.median(lo))*100:>+9.2f}{same}/{len(diffs):>6}  {judge}")
        if judge == "跨月稳定":
            surv.append((k, st.median(hi) - st.median(lo), same, len(diffs)))

    print("\n③ 跨月稳定的特征（可直接用于选票）")
    if not surv:
        print("  无")
    for k, d, s, n in sorted(surv, key=lambda z: -abs(z[1])):
        print(f"  {zname.get(k,k)}: 高组比低组反弹多 {d*100:+.2f}pp，{s}/{n} 月同号")


if __name__ == "__main__":
    main()
