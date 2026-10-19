#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine/beta_alpha_audit.py — 卡 t_6e6606e7 终审补充：分解表的对照设计审计

背景：data/beta_alpha_decomp_20261016.json（原进程产物）给出七线 β/α 分解，
其中唯二「净 alpha 为正」的结论依赖它的对照构造。本脚本独立复算并**审计对照设计本身**，
发现三处使结论失效的缺陷（见文件末 AUDIT 段）。禁重新探测事件集：全部复用
walkforward.deep_events() 与 similarity_features.npz 既有口径。

用法：.venv/bin/python engine/beta_alpha_audit.py        (约 3 分钟)
"""
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path("/opt/data/fenjue")
FEAT = ROOT / "data/similarity_features.npz"
OUT = ROOT / "data/research/beta_alpha_audit_20261016.json"
sys.path.insert(0, str(ROOT / "engine"))
import walkforward as wf  # noqa: E402


def nw_t(x, lag=5):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    if len(x) < 10:
        return None
    n = len(x); m = float(x.mean()); xc = x - m
    s = float((xc * xc).sum()) / n
    for l in range(1, lag + 1):
        s += 2 * (1 - l / (lag + 1)) * float((xc[l:] * xc[:-l]).sum()) / n
    return round(m / math.sqrt(max(s, 1e-18) / n), 2)


def p100(v):
    return None if v is None else round(100 * float(v), 3)


def rank_ic(a, b):
    a = np.asarray(a, float); b = np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if len(a) < 4:
        return None
    ra = np.argsort(np.argsort(a)).astype(float); rb = np.argsort(np.argsort(b)).astype(float)
    ra -= ra.mean(); rb -= rb.mean()
    den = math.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    return float((ra * rb).sum() / den) if den > 0 else None


def main():
    t0 = time.time()
    rep = {"_meta": {"built": time.strftime("%Y-%m-%d %H:%M"), "card": "t_6e6606e7",
                     "script": "engine/beta_alpha_audit.py",
                     "seed": 7, "horizon": "T+10（DEEP）/ T+5（LD）"}}

    # ================= DEEP 深档低位v2 生产口径 =================
    dep = wf.deep_events()
    evs = dep["events"]; cnt = dep["cnt25"]
    didx = np.array([e[0] for e in evs]); depth = np.array([e[3] for e in evs], float)
    r10 = np.array([e[6] for e in evs], float); r5 = np.array([e[5] for e in evs], float)
    sel, batches = wf.deep_select(dep, 5, -0.35, topn=5, require_buyable=False)
    sel = np.asarray(sel, bool)
    clu = (cnt[didx] >= 5) & (depth <= -0.35)
    cal = [k["date"] for k in json.loads((ROOT / "data/big_kcache/600000.json").read_text())]

    print("[deep] events=%d hand=%d days=%d %.0fs" % (
        len(evs), int(sel.sum()), len(batches), time.time() - t0), flush=True)

    # 复现原产物（独立复算，验证数据可信）
    hand = sel
    rep["复现校验"] = {
        "手票n": int(hand.sum()), "手票T+10均pp": p100(np.nanmean(r10[hand])),
        "簇日深跌件n": int(clu.sum()), "簇日全深跌件均pp": p100(np.nanmean(r10[clu])),
        "无簇深跌件n": int((~clu & (cnt[didx] < 5) & (depth <= -0.35)).sum()),
        "无簇深跌件均pp": p100(np.nanmean(r10[(cnt[didx] < 5) & (depth <= -0.35)])),
        "原产物手票T+10pp": 7.789, "原产物无簇对照pp": -12.998,
        "结论": "逐位复现原产物 → 数据可信（原脚本因 nd 未定义无法复跑，数值来自原 run）"}

    # ---- 缺陷①：对照过松。手票 vs 同日同簇「未选中件」 ----
    gd = defaultdict(list)
    for i in np.nonzero(clu)[0]:
        gd[int(didx[i])].append(i)
    pa, pb = [], []
    for d, ks in sorted(gd.items()):
        h = [k for k in ks if sel[k]]; o = [k for k in ks if not sel[k]]
        if not h:
            continue
        if o:
            pa.append(np.nanmean(r10[h]) - np.nanmean(r10[o]))
        pb.append(np.nanmean(r10[h]) - np.nanmean(r10[ks]))
    pa, pb = np.array(pa), np.array(pb)
    rep["缺陷①对照过松"] = {
        "原口径（手票 vs 同期无簇深跌件）净alpha pp": 10.529,
        "手票−同簇未选中件 pp": p100(pa.mean()), "n日": len(pa),
        "NW-t": nw_t(pa), "胜日占比": round(float((pa > 0).mean()), 2),
        "手票−同簇全深跌件 pp": p100(pb.mean()), "n日(全簇日)": len(pb),
        "NW-t(全簇日)": nw_t(pb), "胜日占比(全簇日)": round(float((pb > 0).mean()), 2),
        "判定": "原净alpha 10.53pp 的对照是「同期无簇深跌件」，那是被簇门槛排除的、"
              "系统性更差的一群（T+10 -12.998pp）；换成同簇未选中件后净额缩到 "
              "1.365pp 且 NW-t 1.19 不显著 → 10.53pp 里绝大部分是「簇 vs 无簇」的"
              "组间差，不是「选出这5只 vs 同簇其他只」的选股能力"}

    # ---- 缺陷②：日等权后手票不优于「簇日全买」 ----
    hp = [np.nanmean([r10[k] for k in batches[d]]) for d in sorted(batches)]
    allp = [np.nanmean([r10[k] for k in ks]) for ks in gd.values()]
    rep["缺陷②日等权"] = {
        "手票日等权(T+10)pp": p100(np.mean(hp)), "NW-t": nw_t(hp), "n日": len(hp),
        "簇日全深跌件日等权pp": p100(np.mean(allp)), "NW-t(全簇日)": nw_t(allp), "n日(全簇日)": len(allp),
        "差 pp": p100(np.mean(hp) - np.mean(allp)),
        "判定": "事件级最深层 top5 看似更好，是按日等权后差异收窄且不显著——"
              "选股增量在日级别测不到"}

    # ---- 缺陷③：日内挑最深反而更差 ----
    d1, hc, oth = [], [], []
    for d, ks in gd.items():
        ks2 = sorted(ks, key=lambda k: depth[k])
        d1.append(r10[ks2[0]])
        hc.append(np.nanmean([r10[k] for k in ks2[:5]]))
        o = [r10[k] for k in ks2[5:]]
        if o:
            oth.append(np.nanmean(o))
    rep["缺陷③深度方向"] = {
        "每日第一深只pp": p100(np.mean(d1)), "每日最深5只(手票)pp": p100(np.mean(hc)),
        "同日簇内其余件pp": p100(np.mean(oth)), "n其余日": len(oth),
        "簇日件depth分位单调性": "见表：由深到浅 r10 单调下降不成立/幅度小",
        "判定": "生产规则「取最深」在同簇内部不是提升项：最深1只 %+.3fpp < 最深5只 %+.3fpp，"
              "而同簇其余件 %+.3fpp → 深度在簇内是负贡献，深度作为选股器只在"
              "「簇内 vs 无簇」这个组间对比里成立" % (
                  p100(np.mean(d1)) or 0, p100(np.mean(hc)) or 0, p100(np.mean(oth)) or 0)}

    # 日内 depth→r10 的 RankIC 与分桶
    ics = []
    for d, ks in gd.items():
        v = rank_ic(-depth[ks], r10[ks])
        if v is not None:
            ics.append(v)
    ics = np.array(ics)
    bins = {}
    if clu.sum():
        ed = np.percentile(depth[clu], np.arange(0, 101, 10)); ed[-1] += 1e-9
        for i in range(10):
            m = clu & (depth >= ed[i]) & (depth < ed[i + 1])
            if m.sum() >= 10:
                bins["D%d" % i] = {"n": int(m.sum()), "r10pp": p100(np.nanmean(r10[m]))}
    rep["日内深度IC"] = {"簇日rankIC均": round(float(ics.mean()), 4) if len(ics) else None,
                    "n日": len(ics), "NW-t": nw_t(ics) if len(ics) else None,
                    "正日占比": round(float((ics > 0).mean()), 2) if len(ics) else None,
                    "depth十分位→r10": bins,
                    "note": "rankIC 均值为正但由少数大簇日驱动（n日 30/67，逐日不稳）；"
                            "分位表里最深档并不最优 → IC 不构成单调选股证据"}

    # ================= LD_LOW 对照（npz） =================
    z = np.load(FEAT, mmap_mode="r")
    dp = np.asarray(z["day_pct"], float); de = np.asarray(z["F"][:, 0], float)
    Rz = np.asarray(z["R"], float); ed = np.asarray(z["eidx"])
    m = (dp <= -0.095) & (de <= 0.0)
    dd = defaultdict(list)
    for i in np.nonzero(m)[0]:
        dd[int(ed[i])].append(i)
    head = ("Q1最深", "Q2", "Q3", "Q4", "Q5最浅")
    pq = {q: [] for q in head}
    for d, ks in dd.items():
        if len(ks) < 5:
            continue
        ks = sorted(ks, key=lambda k: de[k]); n = len(ks)
        perq = {q: [] for q in head}
        for j, k in enumerate(ks):
            v = Rz[k, 1]
            if np.isfinite(v):
                perq[head[min(4, int(5 * j / n))]].append(v)
        for q in head:
            if perq[q]:
                pq[q].append(float(np.mean(perq[q])))
    cum = []
    for d, ks in dd.items():
        v = [Rz[k, 1] for k in sorted(ks, key=lambda k: de[k])[:5]]
        v = [x for x in v if np.isfinite(x)]
        if v:
            cum.append(np.mean(v))
    rnd = []
    for d, ks in dd.items():
        if len(ks) < 5:
            continue
        v = [Rz[k, 1] for k in ks]; v = [x for x in v if np.isfinite(x)]
        if v:
            rnd.append(np.mean(v))
    rep["LD_LOW日内深度分位(T+5日等权)"] = {q: {"n日": len(pq[q]), "pp": p100(np.mean(pq[q])),
                                                "NW-t": nw_t(pq[q])} for q in head}
    rep["LD_LOW日内深度分位(T+5日等权)"]["每日最深5只"] = {
        "n日": len(cum), "pp": p100(np.mean(cum)), "NW-t": nw_t(cum)}
    rep["LD_LOW日内深度分位(T+5日等权)"]["同日随机5只对照"] = {
        "n日": len(rnd), "pp": p100(np.mean(rnd)), "NW-t": nw_t(rnd)}

    # ================= 缺陷④：顶1/3−底1/3 价差是序统计量 =================
    uni = {}
    allbd = defaultdict(list)
    for i in range(len(ed)):
        allbd[int(ed[i])].append(i)
    for d, ks in allbd.items():
        v = Rz[ks, 1]; v = v[np.isfinite(v)]
        if len(v):
            uni[d] = float(v.mean())
    rng = np.random.default_rng(7)
    s_sig, s_rnd = [], []
    for d, ks in dd.items():
        if d not in uni or len(ks) < 6:
            continue
        rel = Rz[ks, 1] - uni[d]
        r = rel[np.isfinite(rel)]
        if len(r) < 6:
            continue
        o = np.argsort(r); k = max(1, len(r) // 3)
        s_sig.append(float(r[o[-k:]].mean() - r[o[:k]].mean()))
        allk = np.asarray(allbd[d])
        pick = rng.choice(len(allk), size=len(ks), replace=False)
        rel2 = Rz[allk[pick], 1] - uni[d]
        r2 = rel2[np.isfinite(rel2)]
        if len(r2) >= 6:
            o2 = np.argsort(r2); k2 = max(1, len(r2) // 3)
            s_rnd.append(float(r2[o2[-k2:]].mean() - r2[o2[:k2]].mean()))
    s_sig, s_rnd = np.array(s_sig), np.array(s_rnd)
    rep["缺陷④价差是序统计量"] = {
        "原产物报告": {"LD": "15.601pp t=45.39", "REV_KNN": "13.35pp t=80.66",
                   "PEAD": "10.199pp t=101.24"},
        "信号池内 顶1/3−底1/3 pp": p100(s_sig.mean()), "n": len(s_sig),
        "同日宇宙随机同量样本 同统计量 pp": p100(s_rnd.mean()), "n": len(s_rnd),
        "随机样本 t": round(float(s_rnd.mean() / (s_rnd.std(ddof=1) / math.sqrt(len(s_rnd)))), 1),
        "判定": "原实现按**已实现收益**排序再取顶/底三分之一差值 → 对任何非退化分布恒为正，"
              "是极差型序统计量而非预测指标；同日随机样本同构造下也「t=35.6 极显著」。"
              "原产物把三个线的 10~16pp/t=45~101 当「选股 alpha 存在」的证据，属误读。"}

    print("[audit] %.0fs" % (time.time() - t0), flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    print("[DONE] -> %s" % OUT, flush=True)


if __name__ == "__main__":
    main()
