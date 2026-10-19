#!/usr/bin/env python3
"""金股 d7 买入时点：开盘 vs 盘中（用户「买入时间点是开盘还是盘中10:30之后」）。

数据源：baostock 30 分钟 K 线（前复权，单进程），缓存到 data/min30bs/{code}.json。
每个事件：买入取 T+7 当日的 开盘 / 10:00 / 10:30 / 11:00 / 11:30 / 13:30 / 14:00 / 收盘，
卖出默认 T+9 收盘，另附买卖时点矩阵。费率双边 0.30%。

用法：
  PYTHONPATH=/opt/data/python-libs:. .venv/bin/python engine/gold_entry_timing.py --fetch
  PYTHONPATH=/opt/data/python-libs:. .venv/bin/python engine/gold_entry_timing.py
"""
import json
import statistics as st
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/data/fenjue/engine")
sys.path.insert(0, "/opt/data/python-libs")
import law_pipeline as lp
import gold_rebound_study as G
import gold_best_strategy as B

ROOT = Path("/opt/data/fenjue")
CACHE = ROOT / "data/min30bs"
FEE = 0.0030
SLOTS = ["10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00"]


def bs_code(c):
    return ("sh." if c[:2] in ("60", "68", "51", "58", "11", "13") else "sz.") + c


def fetch_all(codes, beg="2026-05-01", end="2026-10-23"):
    import baostock as bs
    CACHE.mkdir(parents=True, exist_ok=True)
    todo = [c for c in codes if not (CACHE / f"{c}.json").exists()]
    print(f"待拉 {len(todo)} / 共 {len(codes)}", flush=True)
    if not todo:
        return
    lg = bs.login()
    if lg.error_code != "0":
        print("baostock 登录失败", lg.error_msg)
        return
    t0 = time.time()
    for i, c in enumerate(todo, 1):
        try:
            rs = bs.query_history_k_data_plus(bs_code(c), "date,time,open,close",
                                             start_date=beg, end_date=end, frequency="30", adjustflag="2")
            bars = {}
            while rs.error_code == "0" and rs.next():
                d, t, o, cl = rs.get_row_data()
                hhmm = f"{t[8:10]}:{t[10:12]}"
                day = bars.setdefault(d, {})
                if "open" not in day:
                    day["open"] = float(o)
                day[hhmm] = float(cl)
            (CACHE / f"{c}.json").write_text(json.dumps(bars))
        except Exception as e:
            print(f"  {c} 失败 {e}", flush=True)
        if i % 25 == 0:
            print(f"  {i}/{len(todo)}  {time.time()-t0:.0f}s", flush=True)
    bs.logout()
    print(f"拉取完成 {len(todo)} 只，用时 {time.time()-t0:.0f}s", flush=True)


def analyze():
    U = lp.load_universe()
    co = G.build_cohorts(G.load_raw())
    months = sorted(co)
    pool = B.build_pool(U, co, months)
    SIG = ["vol60", "fade", "limit250", "r60pre", "amp60", "amt20", "dist60"]
    SGN = {"dist60": -1}
    mu = {k: st.mean([r[k] for r in pool]) for k in SIG}
    sd = {k: (st.pstdev([r[k] for r in pool]) or 1) for k in SIG}
    for r in pool:
        r["elastic"] = sum(SGN.get(k, 1) * (r[k] - mu[k]) / sd[k] for k in SIG) / len(SIG)
    rank = sorted(pool, key=lambda r: -r["elastic"])
    top13 = set(id(x) for x in rank[:len(rank) // 3])

    rows, miss = [], 0
    for r in pool:
        if r["mo"] not in B.COMPLETE:
            continue
        j, d = r["j"], r["date"]
        if j + 9 >= len(d):
            continue
        d7, d9 = d[j + 7], d[j + 9]
        fp = CACHE / f"{r['code']}.json"
        if not fp.exists():
            miss += 1
            continue
        bars = json.loads(fp.read_text())
        b7, b9 = bars.get(d7), bars.get(d9)
        if not b7 or not b9 or "15:00" not in b9 or "open" not in b7:
            miss += 1
            continue
        rows.append({"mo": r["mo"], "code": r["code"], "name": r["name"], "d7": d7, "d9": d9,
                     "top13": id(r) in top13, "b7": b7, "b9": b9})
    print(f"可分析事件 n={len(rows)}（缺数据 {miss}）\n")
    if not rows:
        return

    def ret(rec, buy, sell):
        p0 = rec["b7"].get(buy)
        p1 = rec["b9"].get(sell)
        if not p0 or not p1:
            return None
        return p1 / p0 - 1 - FEE

    print("① 买入时点对比（卖出固定 T+9 收盘 15:00）")
    print(f"{'买入':<9}{'n':>5}{'均值':>9}{'胜率':>6}{'中位':>9}   {'top1/3均值':>11}{'胜率':>6}")
    for t in ["open"] + SLOTS:
        g, gt = [], []
        for rec in rows:
            x = ret(rec, t, "15:00")
            if x is not None:
                g.append(x)
                if rec["top13"]:
                    gt.append(x)
        if not g:
            continue
        print(f"{t:<9}{len(g):>5}{st.mean(g)*100:>8.2f}%{sum(1 for x in g if x>0)/len(g)*100:>5.0f}%"
              f"{st.median(g)*100:>8.2f}%   {st.mean(gt)*100:>10.2f}%{sum(1 for x in gt if x>0)/len(gt)*100:>5.0f}%")

    print("\n② 逐月（全池）：不同买入时点，均卖 T+9 收盘")
    print(f"{'月':<9}{'n':>5}{'开盘':>9}{'10:00':>9}{'10:30':>9}{'11:00':>9}{'收盘':>9}")
    for mo in B.COMPLETE:
        sub = [r for r in rows if r["mo"] == mo]
        line = f"{mo:<9}{len(sub):>5}"
        for t in ["open", "10:00", "10:30", "11:00", "15:00"]:
            g = [x for x in (ret(r, t, "15:00") for r in sub) if x is not None]
            line += f"{st.mean(g)*100:>8.2f}%" if g else "        -"
        print(line)

    print("\n③ 矩阵：弹性top1/3，买入时点 × 卖出时点（均值%）")
    sb = ["open", "10:00", "10:30", "11:00", "15:00"]
    ss = ["10:00", "10:30", "11:00", "14:00", "15:00"]
    print("        " + "".join(f"卖{s:>8}" for s in ss))
    for b in sb:
        line = f"买{b:<6}"
        for s in ss:
            g = [x for x in (ret(r, b, s) for r in rows if r["top13"]) if x is not None]
            line += f"{st.mean(g)*100:>9.2f}" if g else "        -"
        print(line)

    print("\n④ 配对比较：10:30 买 vs 开盘买（同一笔比）")
    for label, sub in (("全池", rows), ("弹性top1/3", [r for r in rows if r["top13"]])):
        diffs = []
        for rec in sub:
            a, b = ret(rec, "open", "15:00"), ret(rec, "10:30", "15:00")
            if a is not None and b is not None:
                diffs.append(b - a)
        if diffs:
            se = st.stdev(diffs) / len(diffs) ** 0.5
            print(f"  {label}: 10:30 比开盘 平均{'高' if st.mean(diffs)>0 else '低'} {abs(st.mean(diffs))*100:.3f}pp"
                  f"（中位 {st.median(diffs)*100:+.3f}pp, t={st.mean(diffs)/se:.2f}, n={len(diffs)}）")


def main():
    if "--fetch" in sys.argv:
        U = lp.load_universe()
        co = G.build_cohorts(G.load_raw())
        pool = B.build_pool(U, co, sorted(co))
        fetch_all(sorted({r["code"] for r in pool}))
        return
    analyze()


if __name__ == "__main__":
    main()
