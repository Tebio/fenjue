#!/usr/bin/env python3
"""金股怎么才能赚钱：换事件定义重扫（用户「再想想要怎么才能赚钱」）。

前面几轮都在「组合月第 6 个交易日」这个人为入场日上找。这次换事件本身：
**券商公告日（研报发布日）才是真实事件**，而不是月历。

扫描方向：
  ① 公告日事件效应：t0=公告日当天收盘买 / t1=次日收盘买，持 1/2/3/5/10/20 日，vs 全市场同日同持有期
  ② 新鲜度：本月「首次入选」vs「上个月已被推过」
  ③ 拥挤度：本月被 1 / 2 / ≥3 家券商推
  ④ 公告日当天已冲高则回避：按 t0 当日涨幅三分位
  ⑤ 券商质量：各家首次推荐的 t1 持 5 日，谁推的票靠谱
费率双边 0.30%。

用法：.venv/bin/python engine/gold_announcement_study.py
"""
import collections
import glob
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
sys.path.insert(0, "/opt/data/python-libs")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0030
HORIZ = (1, 2, 3, 5, 10, 20)


def load_events():
    rows = []
    for fp in glob.glob(f"{ROOT}/data/gold_raw/*.json"):
        rows += json.load(open(fp))
    ev = collections.defaultdict(lambda: {"ann": set(), "brokers": [], "name": ""})
    seen = set()
    for r in rows:
        c = str(r["股票代码"]).split(".")[0].zfill(6)
        if c[:2] not in ("60", "00"):
            continue
        ct = str(r["组合时间"])[:6]
        ann = str(r["公告日期"])
        br = str(r["研究机构"])
        k = (c, ct, br, ann)
        if k in seen:
            continue
        seen.add(k)
        e = ev[(c, f"{ct[:4]}-{ct[4:]}")]
        e["ann"].add(ann)
        e["brokers"].append((br, ann))
        e["name"] = str(r.get("股票简称", c))
    return ev


def main():
    U = lp.load_universe()
    ev = load_events()
    months = sorted({m for (_, m) in ev})
    prev = {months[i]: months[i - 1] for i in range(1, len(months))}
    in_month = collections.defaultdict(set)
    for (c, m) in ev:
        in_month[m].add(c)

    recs = []
    for (c, mo), e in ev.items():
        d = U.get(c)
        if not d:
            continue
        first = min(e["ann"])
        first_iso = f"{first[:4]}-{first[4:6]}-{first[6:]}"
        idx = None
        for k, day in enumerate(d["date"]):
            if day >= first_iso:
                idx = k
                break
        if idx is None or idx < 25 or idx + 21 >= d["n"]:
            continue
        fwd = {}
        ok = True
        for h in HORIZ:
            if idx + h < d["n"]:
                fwd[f"t0_{h}"] = d["c"][idx + h] / d["c"][idx] - 1 - FEE
                fwd[f"t1_{h}"] = d["c"][idx + h] / d["c"][idx + 1] - 1 - FEE
            else:
                ok = False
        if not ok:
            continue
        recs.append(dict(code=c, name=e["name"], mo=mo, t0=d["date"][idx],
                         t0_ret=d["c"][idx] / d["c"][idx - 1] - 1,
                         n_broker=len({b for b, _ in e["brokers"]}),
                         brokers=sorted({b for b, _ in e["brokers"]}),
                         first_time=(c not in in_month.get(prev.get(mo), set())), **fwd))

    print(f"公告日事件 n={len(recs)}（{months[0]}~{months[-1]}）\n")

    # 全市场基准：抽样 600 只，预建 date→index
    step = max(1, len(U) // 600)
    sample = [(c, d) for c, d in list(U.items())[::step] if c[:2] in ("60", "00")]
    pos = [(d, {day: i for i, day in enumerate(d["date"])}, d["c"], d["n"]) for _, d in sample]
    mk = {}

    def mkt(day, h):
        key = (day, h)
        if key in mk:
            return mk[key]
        xs = []
        for d, p, c, n in pos:
            i = p.get(day)
            if i is not None and i + h < n and c[i] > 0:
                xs.append(c[i + h] / c[i] - 1 - FEE)
        mk[key] = st.mean(xs) if len(xs) > 150 else None
        return mk[key]

    print("① 公告日事件效应（t0=公告日收盘买，t1=次日收盘买），超额=减去全市场同日同持有期")
    print(f"{'持有':<5}{'t0均值':>9}{'胜率':>6}{'超额':>9}   {'t1均值':>9}{'胜率':>6}{'超额':>9}{'n':>6}")
    for h in HORIZ:
        line = f"{h:<5}"
        for tag in ("t0", "t1"):
            g = [r[f"{tag}_{h}"] for r in recs]
            ex = []
            for r in recs:
                mb = mkt(r["t0"], h)
                if mb is not None:
                    ex.append(r[f"{tag}_{h}"] - mb)
            line += f"{st.mean(g)*100:>8.2f}%{sum(1 for x in g if x>0)/len(g)*100:>5.0f}%"
            line += f"{(st.mean(ex)*100 if ex else float('nan')):>+8.2f}pp" + ("   " if tag == "t0" else "")
        print(line + f"{len(recs):>6}")

    print("\n② 首次入选 vs 重复推荐（t1 买入）")
    for h in (3, 5, 10, 20):
        a = [r[f"t1_{h}"] for r in recs if r["first_time"]]
        b = [r[f"t1_{h}"] for r in recs if not r["first_time"]]
        if a and b:
            print(f"  持{h:>2}日: 首次 n={len(a):>3} {st.mean(a)*100:+6.2f}%/胜{sum(1 for x in a if x>0)/len(a)*100:3.0f}%"
                  f"  | 重复 n={len(b):>3} {st.mean(b)*100:+6.2f}%/胜{sum(1 for x in b if x>0)/len(b)*100:3.0f}%"
                  f"  差 {(st.mean(a)-st.mean(b))*100:+.2f}pp")

    print("\n③ 拥挤度：本月被几家券商推（t1 买入）")
    for h in (5, 20):
        line = f"  持{h:>2}日: "
        for lab, f in (("1家", lambda r: r["n_broker"] == 1), ("2家", lambda r: r["n_broker"] == 2), ("≥3家", lambda r: r["n_broker"] >= 3)):
            g = [r[f"t1_{h}"] for r in recs if f(r)]
            if g:
                line += f"{lab} n={len(g):>3} {st.mean(g)*100:+6.2f}%/胜{sum(1 for x in g if x>0)/len(g)*100:3.0f}%   "
        print(line)

    print("\n④ 公告日当天涨幅分组（t1 买入）")
    vals = sorted(r["t0_ret"] for r in recs)
    q1, q2 = st.quantiles(vals, n=3)
    for h in (5, 20):
        line = f"  持{h:>2}日: "
        for lab, f in (("当日跌/最弱1/3", lambda r: r["t0_ret"] < q1), ("中间", lambda r: q1 <= r["t0_ret"] < q2), ("当日最强1/3", lambda r: r["t0_ret"] >= q2)):
            g = [r[f"t1_{h}"] for r in recs if f(r)]
            line += f"{lab} {st.mean(g)*100:+6.2f}%/胜{sum(1 for x in g if x>0)/len(g)*100:3.0f}%   "
        print(line)

    print("\n⑤ 券商质量：各家首次推荐的 t1 持 5 日（样本≥15）")
    per = collections.defaultdict(list)
    for r in recs:
        if r["first_time"]:
            for b in r["brokers"]:
                per[b].append(r["t1_5"])
    rank = [(b, len(v), st.mean(v), sum(1 for x in v if x > 0) / len(v)) for b, v in per.items() if len(v) >= 15]
    rank.sort(key=lambda z: -z[2])
    print(f"  {len(rank)} 家达标。前 6：")
    for b, n, m, w in rank[:6]:
        print(f"    {b:<12} n={n:>3} {m*100:+6.2f}%/胜{w*100:3.0f}%")
    print("  后 6：")
    for b, n, m, w in rank[-6:]:
        print(f"    {b:<12} n={n:>3} {m*100:+6.2f}%/胜{w*100:3.0f}%")
    if rank:
        print(f"  券商间极差 {(rank[0][2]-rank[-1][2])*100:.2f}pp，全体均值 {st.mean([m for _,_,m,_ in rank])*100:+.2f}%")


if __name__ == "__main__":
    main()
