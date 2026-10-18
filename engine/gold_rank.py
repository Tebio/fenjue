#!/usr/bin/env python3
"""金股出票排行（2026-10-18，卡 t_60428c85 口径落地 / 用户「用之前的策略测出来的排行」）。

三步：
① 金股主线同口径画像：把 gold_stock_cache 全历史名单按「生产口径」重建事件
   （信号日=月第5交易日收盘 → 入场=月第6交易日开盘，离场 T+1/5/20 收盘收盘，扣费 0.0015），
   逐事件记 depth60/dhigh60/volr5/log_amt20/regime/year，落 data/gold_portrait_20261018.json。
   同时用旧口径（月首交易日次日开盘，gold_stock_backtest.py 原式）重算一遍做对拍。
② 分桶：dhigh60 / depth60 / volr5 / year / regime 的 T20 胜率与均值（对照用）。
③ 排行：对当日 14 只独家+年内首入票，用「桶内实证期望 + KNN 近邻实证」两法交叉打分排序。

可复跑：cd /opt/data/fenjue && .venv/bin/python engine/gold_rank.py
"""
import json
import math
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = Path("/opt/data/fenjue")
CACHE = ROOT / "data" / "gold_stock_cache"
FEE = 0.0015
OUT = ROOT / "data" / "gold_portrait_20261018.json"
RANK_OUT = ROOT / "data" / "gold_rank_20261018.json"

idx = json.loads((ROOT / "data/index_sh000001.json").read_text())
idays = [r["date"] for r in idx]
iclose = {r["date"]: float(r["close"]) for r in idx}
i2d = {d: i for i, d in enumerate(idays)}
regime_tl = {r["date"]: r["regime"] for r in json.loads((ROOT / "data/regime_timeline_hcap.json").read_text())}

U = lp.load_universe()
picks_all = {}
for f in sorted(CACHE.glob("20[0-9][0-9]-[0-9][0-9].json")):
    rows = json.loads(f.read_text())
    if rows:
        picks_all[f.stem] = rows


def feats(d, i):
    ma = d["ma60"][i]
    dep = d["c"][i] / ma - 1 if ma and ma > 0 else None
    hi = max(d["h"][max(0, i - 59):i + 1])
    dh = d["c"][i] / hi - 1 if hi > 0 else None
    base = d["v"][i - 5:i]
    vr = d["v"][i] / (sum(base) / 5) if len(base) == 5 and all(x > 0 for x in base) else None
    # 规模代理：20 日均量（big_kcache 的 amt 字段全 0，不可用）
    v20 = sum(d["v"][max(0, i - 19):i + 1]) / len(d["v"][max(0, i - 19):i + 1])
    return dep, dh, vr, (math.log(v20) if v20 and v20 > 0 else None)


def build_entry_shift(shift):
    """shift=5 → 生产口径（第6交易日开盘入）；shift=0 → 旧口径（月首交易日次日开盘入）。"""
    ev = []
    for mo, rows in picks_all.items():
        mdays = [x for x in idays if x.startswith(mo)]
        if len(mdays) < shift + 2:
            continue
        sig = mdays[shift - 1] if shift else mdays[0]
        tgt = mdays[shift] if shift else (idays[i2d[mdays[0]] + 1] if i2d[mdays[0]] + 1 < len(idays) else None)
        if not tgt:
            continue
        for r in rows:
            d = U.get(r["code"])
            if not d or sig not in d["date"]:
                continue
            i = d["date"].index(sig)
            if tgt not in d["date"]:
                continue
            j = d["date"].index(tgt)
            if j >= d["n"] or d["o"][j] <= 0:
                continue
            entry = d["o"][j]
            r1 = d["c"][j] / entry - 1 - FEE
            r5 = d["c"][j + 5] / entry - 1 - FEE if j + 5 < d["n"] else None
            r20 = d["c"][j + 20] / entry - 1 - FEE if j + 20 < d["n"] else None
            dep, dh, vr, la = feats(d, i)
            mk = None
            if tgt in i2d and i2d[tgt] + 20 < len(idays):
                mk = iclose[idays[i2d[tgt] + 20]] / iclose[tgt] - 1
            ev.append({"month": mo, "code": r["code"], "name": r.get("name", ""),
                       "sig": sig, "entry_day": tgt, "entry": entry,
                       "r1": r1, "r5": r5, "r20": r20, "mkt20": mk,
                       "depth60": dep, "dhigh60": dh, "volr5": vr, "log_v20": la,
                       "regime": regime_tl.get(sig), "year": tgt[:4]})
    return ev


def blk(rows, lb, minn=30):
    rows = [r for r in rows if r["r20"] is not None]
    if len(rows) < minn:
        return f"{lb:<22} n={len(rows):>5}  (太少)"
    out = f"{lb:<22} n={len(rows):>5}"
    for h in ("r1", "r5", "r20"):
        xs = [r[h] for r in rows if r[h] is not None]
        if not xs:
            continue
        out += f" | {h.upper()} {sum(1 for x in xs if x > 0) / len(xs) * 100:5.1f}%/{st.mean(xs) * 100:+6.2f}%"
    ex = [r["r20"] - r["mkt20"] for r in rows if r["mkt20"] is not None]
    if ex:
        out += f" | 超额 {st.mean(ex) * 100:+5.2f}%"
    return out


def band(x, edges, labels):
    if x is None:
        return "NA"
    for (lo, hi), lb in zip(edges, labels):
        if lo <= x < hi:
            return lb
    return labels[-1]


DH_E = [(-9, -0.5), (-0.5, -0.3), (-0.3, -0.2), (-0.2, 0.0), (0.0, 9)]
DH_L = ["深≤-50%", "-50~-30%", "-30~-20%", "-20~0%", "≥0%(新高区)"]
DP_E = [(-9, -0.3), (-0.3, -0.15), (-0.15, 0.0), (0.0, 9)]
DP_L = ["深≤-30%", "-30~-15%", "-15~0%", "≥0%(MA60上)"]
VR_E = [(0, 0.7), (0.7, 1.0), (1.0, 1.5), (1.5, 99)]
VR_L = ["缩<0.7", "0.7~1.0", "1.0~1.5", "放>1.5"]


def main():
    ev = build_entry_shift(5)
    ev_old = build_entry_shift(0)
    print(f"生产口径事件 {len(ev)}（旧口径 {len(ev_old)}）")
    print("\n── 口径对拍（全样本 T20）──")
    print(blk(ev, "生产口径(第6交易日入)"))
    print(blk(ev_old, "旧口径(月首次日次开入)"))

    print("\n── 分年 ──")
    for y in sorted({r["year"] for r in ev}):
        print(blk([r for r in ev if r["year"] == y], f"{y}年"))

    print("\n── 位置 dhigh60（距60日高）──")
    for lb in DH_L:
        print(blk([r for r in ev if band(r["dhigh60"], DH_E, DH_L) == lb], lb))
    print("\n── 位置 depth60（距MA60）──")
    for lb in DP_L:
        print(blk([r for r in ev if band(r["depth60"], DP_E, DP_L) == lb], lb))
    print("\n── 量能 volr5 ──")
    for lb in VR_L:
        print(blk([r for r in ev if band(r["volr5"], VR_E, VR_L) == lb], lb))
    print("\n── regime（信号日）──")
    for g in sorted({r["regime"] for r in ev if r["regime"]}):
        print(blk([r for r in ev if r["regime"] == g], g))
    print("\n── 2026 段 × dhigh60（近段是否同向）──")
    for lb in DH_L:
        print(blk([r for r in ev if r["year"] == "2026" and band(r["dhigh60"], DH_E, DH_L) == lb], f"2026 {lb}", minn=10))
    print("\n── 2025-2026 × dhigh60 ──")
    for lb in DH_L:
        print(blk([r for r in ev if r["year"] in ("2025", "2026") and band(r["dhigh60"], DH_E, DH_L) == lb], f"25-26 {lb}", minn=10))

    json.dump(ev, open(OUT, "w"), ensure_ascii=False)

    # ── ③ 当日 14 只排行 ──
    cur = json.loads((ROOT / "data/gold_current.json").read_text())
    picks = cur["solo_fresh"]
    entry_day = cur["entry_day"]
    i_entry = i2d[entry_day]
    sig_day = idays[i_entry - 1]

    hist = [r for r in ev if r["r20"] is not None and r["dhigh60"] is not None]
    m2026 = st.mean([r["r20"] for r in hist if r["year"] == "2026"]) if any(r["year"] == "2026" for r in hist) else 0.0
    mall = st.mean([r["r20"] for r in hist])

    def bucket_expect(edges, labels, full=True):
        """桶内实证期望：全历史 40% + 2025-26 近段 60%（2026 段位置效应与全历史不同向，必须混入近段）。"""
        out = {}
        for lb in labels:
            a = [r["r20"] for r in hist if band(r["dhigh60"] if full else r["depth60"], edges, labels) == lb]
            b = [r["r20"] for r in hist if r["year"] in ("2025", "2026")
                 and band(r["dhigh60"] if full else r["depth60"], edges, labels) == lb]
            if len(a) < 30:
                out[lb] = (mall, len(a), None)
            elif len(b) < 30:
                out[lb] = (st.mean(a), len(a), None)
            else:
                out[lb] = (0.4 * st.mean(a) + 0.6 * st.mean(b), len(a), len(b))
        return out

    e_dh = bucket_expect(DH_E, DH_L, full=True)
    e_dp = bucket_expect(DP_E, DP_L, full=False)

    # KNN：标准化 (dhigh60, depth60, volr5, log_v20)
    dims = ["dhigh60", "depth60", "volr5", "log_v20"]
    H = [r for r in hist if all(r[k] is not None for k in dims)]
    mu = {k: st.mean([r[k] for r in H]) for k in dims}
    sd = {k: (st.pstdev([r[k] for r in H]) or 1) for k in dims}
    HZ = [[(r[k] - mu[k]) / sd[k] for k in dims] for r in H]

    def knn(q, k=60):
        qz = [(q[d] - mu[d]) / sd[d] if q[d] is not None else 0.0 for d in dims]
        ds = sorted(((sum((a - b) ** 2 for a, b in zip(qz, z)), i) for i, z in enumerate(HZ)))[:k]
        xs = [H[i]["r20"] for _, i in ds]
        return st.mean(xs), sum(1 for x in xs if x > 0) / len(xs), len(xs)

    rows = []
    for p in picks:
        d = U[p["code"]]
        if sig_day not in d["date"]:
            continue
        i = d["date"].index(sig_day)
        dep, dh, vr, lv = feats(d, i)
        lbh, lbd = band(dh, DH_E, DH_L), band(dep, DP_E, DP_L)
        edh, ndh, ndh26 = e_dh[lbh]
        edp, ndp, ndp26 = e_dp[lbd]
        kn, kw, kn_n = knn({"dhigh60": dh, "depth60": dep, "volr5": vr, "log_v20": lv})
        j = d["date"].index(entry_day) if entry_day in d["date"] else None
        entry = d["o"][j] if j is not None else None
        r1 = (d["c"][j + 1] / entry - 1) if j is not None and j + 1 < d["n"] else None
        last = d["c"][d["n"] - 1]
        mtm = (last / entry - 1) if entry else None
        expect = 0.4 * edh + 0.3 * edp + 0.3 * kn
        warn = []
        if dh is not None and dh <= -0.3:
            warn.append("2026该深桶翻负(-5.6%)")
        if dh is not None and dh >= 0:
            warn.append("新高区历史T20负")
        if vr is not None and vr < 0.7:
            warn.append("缩量")
        rows.append({"code": p["code"], "name": p["name"], "close": last, "entry": entry,
                     "depth60": dep, "dhigh60": dh, "volr5": vr, "log_v20": lv,
                     "bucket_dh": lbh, "bucket_dh_n": ndh, "e_dh": edh, "e_dh_n26": ndh26,
                     "bucket_dp": lbd, "e_dp": edp, "e_dp_n26": ndp26,
                     "knn_r20": kn, "knn_win": kw, "knn_n": kn_n,
                     "expect": expect, "r1": r1, "mtm": mtm, "warn": warn,
                     "region": "深跌区" if (dh is not None and dh <= -0.2) else ("中位区" if (dh is not None and dh <= 0) else "高位区")})
    rows.sort(key=lambda r: -r["expect"])

    print(f"\n═══ 2026-10 独家+年内首入 {len(rows)} 只排行（入场日 {entry_day}，信号日 {sig_day}）═══")
    print(f"全历史 T20 均值 {mall*100:+.2f}%；2026 段 {m2026*100:+.2f}%；信号日 regime={regime_tl.get(sig_day)}；入场日 regime={regime_tl.get(entry_day)}")
    print(f"期望=0.4×dhigh60桶(全史40%+25-26算60%) + 0.3×depth60桶 + 0.3×KNN60")
    hdr = f"{'#':>2} {'代码':>6} {'名称':<9} {'期望T20':>7} {'dhigh60':>8} {'depth60':>8} {'volr5':>6} {'E_dh':>7} {'E_dp':>7} {'KNN':>7} {'K胜率':>6} {'已实现r1':>8} {'浮动':>7}"
    print(hdr)
    for k, r in enumerate(rows, 1):
        f = lambda x, p=1: ("   n/a" if x is None else f"{x*100:+.{p}f}%")
        vr = "n/a" if r["volr5"] is None else f"{r['volr5']:.2f}"
        print(f"{k:>2} {r['code']:>6} {r['name']:<9} {f(r['expect']):>7} {f(r['dhigh60']):>8} {f(r['depth60']):>8} "
              f"{vr:>6} {f(r['e_dh']):>7} {f(r['e_dp']):>7} {f(r['knn_r20']):>7} {r['knn_win']*100:>5.1f}% {f(r['r1']):>8} {f(r['mtm']):>7}")
    print()
    for k, r in enumerate(rows, 1):
        if r["warn"]:
            print(f"  {k:>2}. {r['name']}：{'+'.join(r['warn'])}")
    json.dump({"entry_day": entry_day, "sig_day": sig_day,
               "market_note": {"baseline_r20": mall, "y2026": m2026,
                               "regime_sig": regime_tl.get(sig_day), "regime_entry": regime_tl.get(entry_day)},
               "rows": rows, "model": "0.4*dhigh60桶 + 0.3*depth60桶 + 0.3*KNN60；桶期望=全史40%+25-26段60%"},
              open(RANK_OUT, "w"), ensure_ascii=False, indent=1)
    print(f"\n落盘 {OUT} / {RANK_OUT}")


if __name__ == "__main__":
    main()
