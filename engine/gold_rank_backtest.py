#!/usr/bin/env python3
"""金股排序法回测：股性口径 vs KNN口径 vs 合成（2026-10-19 用户「你可以用9月，8月的测一下先」）。

背景：`gold_rank.py` 用「位置桶期望 + KNN近邻」给金股池排序，但 #297 已证它依赖的
历史画像有月份错位；#300 又发现池内唯一跨月稳定的因子是「距60日高」。到底该信哪个？
本脚本在**已完成 T+20 的月份**上做前推对拍（train 只用更早的组合月，无前视）：

方法：
  A 股性口径   ：按 距60日高 降序（越靠 60 日高越好，#300）
  B KNN 口径    ：沿用 gold_rank 的四维（dhigh60 / depth60 / volr5 / log_v20）取 60 近邻
                  的 T+20 均值，训练集=更早组合月的 PIT 事件（只含已走完 20 日的）
  C 合成        ：A、B 名次平均
  D 对照组      ：距250日高 / 日波动率 / 冲高回落率 单因子排序

评分：池内三分位 top vs bottom 的 T+20 差（spread），以及 top5/bottom5 的实测。
用法：.venv/bin/python engine/gold_rank_backtest.py
"""
import collections
import glob
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
sys.path.insert(0, "/opt/data/python-libs")
import law_pipeline as lp
import trade_calendar as tc

ROOT = "/opt/data/fenjue"
FEE = 0.0015
DIMS = ["dhigh60", "depth60", "volr5", "log_v20"]


def cohorts():
    rows = []
    for fp in glob.glob(f"{ROOT}/data/gold_raw/*.json"):
        rows += json.load(open(fp))
    out = collections.defaultdict(lambda: collections.defaultdict(set))
    seen = set()
    for r in rows:
        c = str(r["股票代码"]).split(".")[0].zfill(6)
        if c[:2] not in ("60", "00"):
            continue
        ct = str(r["组合时间"])[:6]
        ann = str(r["公告日期"])
        k = (c, r["研究机构"], ann, ct)
        if k in seen:
            continue
        seen.add(k)
        out[f"{ct[:4]}-{ct[4:]}"][c].add(ann)
    return out


def feats(d, j):
    """入场日 j；特征用 j-1 及之前（KNN 维度按 gold_rank 口径：dhigh60/depth60/volr5/log_v20）。"""
    if j < 260:
        return None
    c, h, l, v = d["c"], d["h"], d["l"], d["v"]
    ma60 = st.mean(c[j - 60:j])
    f = {
        "dhigh60": c[j - 1] / max(h[j - 60:j]) - 1,
        "depth60": c[j - 1] / ma60 - 1,
        "volr5": v[j - 1] / st.mean(v[j - 6:j - 1]),
        "log_v20": __import__("math").log(max(1.0, st.mean([v[k] * c[k] for k in range(j - 20, j)]))),
        "dist250": c[j - 1] / max(h[j - 250:j]) - 1,
        "vol60": st.pstdev([c[k] / c[k - 1] - 1 for k in range(j - 60, j)]),
        "fade": sum(1 for k in range(j - 120, j)
                    if h[k] / c[k - 1] - 1 >= 0.03 and c[k] / h[k] - 1 <= -0.02) / 120,
        "amp60": st.mean([(h[k] - l[k]) / c[k - 1] for k in range(j - 60, j)]),
        "r60pre": c[j - 1] / c[j - 61] - 1,
    }
    return f


def main():
    U = lp.load_universe()
    combos = cohorts()
    months = sorted(combos)
    pool = collections.defaultdict(list)
    for mo in months:
        y = int(mo[:4])
        days = [x for x in (tc.trading_days(y) or []) if x.startswith(mo)]
        if len(days) < 7:
            continue
        entry = days[5]
        for c, anns in combos[mo].items():
            if min(anns) > entry.replace("-", ""):
                continue
            d = U.get(c)
            if not d or entry not in d["date"]:
                continue
            j = d["date"].index(entry)
            f = feats(d, j)
            if not f:
                continue
            r20 = (d["c"][j + 20] / d["o"][j] - 1 - FEE) if j + 20 < d["n"] else None
            pool[mo].append(dict(f, code=c, name=d.get("name", c), mo=mo, r20=r20))

    # 标准化用历史训练集的均值/方差
    def knn_train(train_rows):
        if not train_rows:
            return None
        mu = {k: st.mean([r[k] for r in train_rows]) for k in DIMS}
        sd = {k: (st.pstdev([r[k] for r in train_rows]) or 1) for k in DIMS}
        Z = [[(r[k] - mu[k]) / sd[k] for k in DIMS] for r in train_rows]
        return mu, sd, Z, train_rows

    print("排序法前推对拍（spread = 池内 top 三分之一 − bottom 三分之一 的 T+20）\n")
    hdr = f"{'月':<9}{'n':>4}   {'A股性(距60高)':>20}{'B KNN(四维)':>20}{'C合成':>20}{'D距250高':>20}{'D波动率':>20}"
    print(hdr)
    agg = collections.defaultdict(list)
    for mo in months:
        rows = [r for r in pool[mo] if r["r20"] is not None]
        if len(rows) < 30:
            continue
        train = [r for m2 in months if m2 < mo for r in pool[m2] if r["r20"] is not None and r["r20"] is not None]
        kt = knn_train(train)
        if kt:
            mu, sd, Z, tr = kt
            for r in rows:
                q = [(r[k] - mu[k]) / sd[k] for k in DIMS]
                ds = sorted((sum((a - b) ** 2 for a, b in zip(q, z)), i) for i, z in enumerate(Z))[:60]
                r["knn"] = st.mean(tr[i]["r20"] for _, i in ds)
        else:
            for r in rows:
                r["knn"] = 0.0
        # 名次（越大越好）
        def rank_of(key, reverse=True):
            s = sorted(rows, key=lambda r: -r[key] if reverse else r[key])
            return {r["code"]: i + 1 for i, r in enumerate(s)}
        rA = rank_of("dhigh60")          # 距60日高越大（越近）越好
        rB = rank_of("knn")
        rC = {c: (rA[c] + rB[c]) / 2 for c in rA}
        rD1 = rank_of("dist250")
        rD2 = rank_of("vol60", reverse=False)   # 波动越小越好
        third = max(3, len(rows) // 3)
        line = f"{mo:<9}{len(rows):>4}   "
        for lab, rk in (("A", rA), ("B", rB), ("C", rC), ("D1", rD1), ("D2", rD2)):
            top = [r["r20"] for r in rows if rk[r["code"]] <= third]
            bot = [r["r20"] for r in rows if rk[r["code"]] > len(rows) - third]
            sp = st.mean(top) - st.mean(bot)
            agg[lab].append(sp)
            line += f"{sp*100:+7.2f}pp({st.mean(top)*100:+5.2f})"[:20].rjust(21)
        print(line)
        # top5/bottom5 实测
        s5 = sorted(rows, key=lambda r: rA[r["code"]])
        print(f"          A口径 top5 {[r['name'] for r in s5[:5]]} → 均值 {st.mean([r['r20'] for r in s5[:5]])*100:+.2f}%"
              f" | bottom5 均值 {st.mean([r['r20'] for r in s5[-5:]])*100:+.2f}%")
        s5b = sorted(rows, key=lambda r: rB[r["code"]])
        print(f"          B口径 top5 {[r['name'] for r in s5b[:5]]} → 均值 {st.mean([r['r20'] for r in s5b[:5]])*100:+.2f}%"
              f" | bottom5 均值 {st.mean([r['r20'] for r in s5b[-5:]])*100:+.2f}%")
    print("\n汇总：各方法 spread 均值 / 正号月数")
    for lab in ("A", "B", "C", "D1", "D2"):
        xs = agg.get(lab) or []
        if xs:
            print(f"  {lab}: 均 {st.mean(xs)*100:+.2f}pp  中位 {st.median(xs)*100:+.2f}pp  正号 {sum(1 for x in xs if x>0)}/{len(xs)}")


if __name__ == "__main__":
    main()
