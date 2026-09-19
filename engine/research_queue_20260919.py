#!/usr/bin/env python3
"""research_queue_20260919.py — 用户五问研究队列（2026-09-19 立项，全排进去跑）。

R1 裸底座衰退机制：跌停接_MA60下 分年份 T+1/T+5 胜率/均值/位置匹配边际——edge 什么时候消失的
R2 成簇过滤 K×槽位二维网格：K∈{1,3,5,10,20} × slots∈{5,10,30}，3 个主信号，找容量最优区
R3 T1 强度加仓开关：T1 收盘≥+3% 次日开盘加一槽 vs 不加（组合_跌停低_长周期_超跌20，K5 口径）
R4 高位剧震回避黑名单：近10日≥2涨停 + 天量剧震 → 前向 T+1/5/20（预期显著为负→黑名单）
R5 席位×恐慌接跌：跌停低事件 ∩ 当日龙虎榜（格局席位净买/机构净买）分组对比（1年深度，诚实限量）
输出：data/research_queue_20260919.json（全部结果）+ 逐题打印
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent
FEE = 0.0015
OUT = {}


def fwd(d, i, h):
    """次日开盘买，入场日+h 收盘卖，净口径。"""
    ei = i + 1
    if ei >= d["n"] or ei + h >= d["n"] or d["o"][ei] <= 0:
        return None
    if d["o"][ei] <= d["c"][i] * 0.905:   # 一字跌停买不进
        return None
    return d["c"][ei + h] / d["o"][ei] - 1 - FEE


def stat(rs):
    if not rs:
        return None
    wins = [r for r in rs if r > 0]
    return {"n": len(rs), "win%": round(100 * len(wins) / len(rs), 1),
            "mean%": round(100 * sum(rs) / len(rs), 2)}


# ---------------- R1 ----------------
def r1(stocks):
    det = lp.REGISTRY["跌停接_MA60下"]
    by_year = defaultdict(list)      # year -> [(code,i)]
    for code, d in stocks.items():
        c, ma, n = d["c"], d["ma60"], d["n"]
        for i in range(61, n - 22):
            if ma[i] is not None and c[i] <= ma[i] and c[i-1] > 0 and c[i]/c[i-1]-1 <= -0.095:
                by_year[d["date"][i][:4]].append((code, i))
    res = {}
    for y in sorted(by_year):
        evs = by_year[y]
        r1s = [fwd(stocks[c], i, 1) for c, i in evs]
        r5s = [fwd(stocks[c], i, 5) for c, i in evs]
        res[y] = {"n": len(evs), "T+1": stat([x for x in r1s if x is not None]),
                  "T+5": stat([x for x in r5s if x is not None])}
    OUT["R1_裸底座分年"] = res
    for y, v in res.items():
        print(f"R1 {y}: n={v['n']} T+1 {v['T+1']['win%']}%/{v['T+1']['mean%']}%  T+5 {v['T+5']['win%']}%/{v['T+5']['mean%']}%", flush=True)


# ---------------- R2 ----------------
def r2(stocks):
    grid = {}
    for name in ["跌停接_MA60下", "组合_跌停低_长周期_超跌20", "组合_跌停低_TD9买入滤"]:
        sigs = lp._collect_sigs(lp.REGISTRY[name], stocks)
        rec = {}
        for K in (1, 3, 5, 10, 20):
            for slots in (5, 10, 30):
                r = lp.capacity_sim(sigs, stocks, slots=slots, hold=5, cluster_k=K, seeds=2)
                rec[f"K{K}_槽{slots}"] = r
                print(f"R2 {name} K{K}槽{slots}: 年化{r['年化%']}% 均笔{r['均笔%']}% 回撤{r['回撤%']}%", flush=True)
        grid[name] = rec
    OUT["R2_Kx槽位"] = grid


# ---------------- R3 ----------------
def r3(stocks):
    """T1 强度加仓：买入后首日(T1)收盘 ≥+3% → T2 开盘加一槽。对照=不加。K5 成簇过滤。"""
    import random as _random
    name = "组合_跌停低_长周期_超跌20"
    sigs = lp._collect_sigs(lp.REGISTRY[name], stocks)
    dates = sorted({x for s in stocks.values() for x in s["date"]})
    didx = {c: {x: j for j, x in enumerate(s["date"])} for c, s in stocks.items()}

    def run(add_on_strength):
        rnd = _random.Random(7)
        cap0, slots, hold = 1_000_000.0, 10, 5
        cash, pos, trades, eqs = cap0, [], [], []
        for k, day in enumerate(dates):
            keep = []
            for code, ei, xi, val, added in pos:
                j = didx[code].get(day, -1)
                d = stocks[code]
                # T1 收盘判定加仓（T1=入场日 ei；次日 ei+1 开盘加一槽）
                if add_on_strength and not added and j == ei + 1:
                    pc = d["o"][ei]
                    if pc > 0 and d["c"][ei] / pc - 1 >= 0.03 and cash >= cap0 / slots:
                        cash -= cap0 / slots
                        keep.append((code, ei, xi, val, True))
                        keep.append((code, ei + 1, xi, cap0 / slots, True))  # 加仓腿：ei+1 开盘买
                        continue
                if j < 0 or j < xi:
                    keep.append((code, ei, xi, val, added)); continue
                if xi >= d["n"] or d["c"][xi] <= 0 or d["o"][ei] <= 0:
                    keep.append((code, ei, xi, val, added)); continue
                r = d["c"][xi] / d["o"][ei] - 1 - FEE
                cash += val * (1 + r)
                trades.append(r * 100)
            pos = keep
            if k > 0:
                lst = sigs.get(dates[k - 1], [])
                cands = [s for s in lst if didx[s[0]].get(day) == s[1] + 1]
                if len(lst) < 5:
                    cands = []
                rnd.shuffle(cands)
                for code, i in cands[:max(0, slots - len(pos))]:
                    if cash < cap0 / slots:
                        break
                    cash -= cap0 / slots
                    pos.append((code, i + 1, i + 1 + hold, cap0 / slots, False))
            eqs.append(cash + sum(v for *_x, v, _a in pos))
        yrs = len(dates) / 244.0
        final = eqs[-1]
        peak, mdd = -1e18, 0
        for e in eqs:
            peak = max(peak, e)
            mdd = min(mdd, e / peak - 1)
        return {"年化%": round(((final / cap0) ** (1 / yrs) - 1) * 100, 1),
                "回撤%": round(mdd * 100, 1), "笔数": len(trades),
                "均笔%": round(sum(trades) / len(trades), 2) if trades else 0}

    base, add = run(False), run(True)
    OUT["R3_T1加仓"] = {"不加仓": base, "T1≥3%加仓": add}
    print(f"R3: 不加 {base}  vs  加仓 {add}", flush=True)


# ---------------- R4 ----------------
def r4(stocks):
    """高位剧震回避：近10日≥2涨停 + 今日天量剧震（量比≥2 且 上影≥4%或大阴≤-4%）。"""
    def is_quake(d, i):
        c, o, h, l, v = d["c"], d["o"], d["h"], d["l"], d["v"]
        if i < 12 or c[i] <= 0 or c[i - 1] <= 0:
            return False
        boards = sum(1 for j in range(i - 10, i) if c[j] > 0 and c[j - 1] > 0 and c[j] / c[j - 1] - 1 >= 0.098)
        if boards < 2:
            return False
        base = v[i - 5:i]
        if len(base) < 5 or any(x <= 0 for x in base):
            return False
        mb = sum(base) / 5
        if mb <= 0 or v[i] / mb < 2.0:
            return False
        chg = c[i] / c[i - 1] - 1
        upper = (h[i] - c[i]) / c[i]
        return upper >= 0.04 or chg <= -0.04

    rs = {1: [], 5: [], 20: []}
    ctrl = {1: [], 5: [], 20: []}
    import random
    rng = random.Random(19)
    for code, d in stocks.items():
        c, ma, n = d["c"], d["ma60"], d["n"]
        hits_i = []
        for i in range(61, n - 22):
            if ma[i] is not None and c[i] > ma[i] and is_quake(d, i):   # 高位=MA60上
                hits_i.append(i)
        for i in hits_i:
            for h in (1, 5, 20):
                r = fwd(d, i, h)
                if r is not None:
                    rs[h].append(r)
        # 同票高位非剧震对照（等量）
        pool = [i for i in range(61, n - 22) if ma[i] is not None and c[i] > ma[i] and not is_quake(d, i)]
        for i in rng.sample(pool, min(len(hits_i) * 2, len(pool))):
            for h in (1, 5, 20):
                r = fwd(d, i, h)
                if r is not None:
                    ctrl[h].append(r)
    OUT["R4_高位剧震"] = {f"T+{h}": {"剧震": stat(rs[h]), "高位对照": stat(ctrl[h]),
                                "边际pp": round((sum(rs[h]) / len(rs[h]) - sum(ctrl[h]) / len(ctrl[h])) * 100, 2)
                                if rs[h] and ctrl[h] else None}
                          for h in (1, 5, 20)}
    for h in (1, 5, 20):
        print(f"R4 T+{h}: 剧震 {stat(rs[h])} vs 高位对照 {stat(ctrl[h])}", flush=True)


# ---------------- R5 ----------------
def r5(stocks):
    HT = ROOT / "data/hithink"
    det = lp.REGISTRY["跌停接_MA60下"]
    # 格局型席位（seat_gene v1 实证：T5 衰减慢 = 题材含金量）
    GEJU = ("成都", "中山东路", "章盟主", "炒股养家")
    groups = {"格局席位净买": [], "机构净买": [], "上榜但无": [], "未上榜": []}
    for ddir in sorted(HT.iterdir()):
        if not ddir.is_dir():
            continue
        day = ddir.name
        hot = org = None
        fh, fo = ddir / "lhb_hot.json", ddir / "lhb_org.json"
        geju_codes, org_codes, board_codes = set(), set(), set()
        if fh.exists():
            hot = json.loads(fh.read_text())["data"]
            for seat in hot.get("hot_money_items") or []:
                sname = seat.get("name", "")
                if any(g in sname for g in GEJU):
                    for r in seat.get("rows") or []:
                        if (r.get("hot_money_item_net_value") or 0) > 0:
                            geju_codes.add(r["ticker"])
                        board_codes.add(r["ticker"])
        if fo.exists():
            org = json.loads(fo.read_text())["data"]
            for r in org.get("stock_items") or []:
                board_codes.add(r["ticker"])
                if (r.get("org_net_value") or 0) > 0:
                    org_codes.add(r["ticker"])
        for code, d in stocks.items():
            idx = {x: j for j, x in enumerate(d["date"])}
            i = idx.get(day)
            if i is None or i < 61:
                continue
            c, ma = d["c"], d["ma60"]
            if not (ma[i] is not None and c[i] <= ma[i] and c[i-1] > 0 and c[i]/c[i-1]-1 <= -0.095):
                continue
            r = fwd(d, i, 5)
            if r is None:
                continue
            tick = code + (".SH" if code.startswith("6") else ".SZ")
            if code in geju_codes or tick in geju_codes:
                groups["格局席位净买"].append(r)
            elif code in org_codes or tick in org_codes:
                groups["机构净买"].append(r)
            elif code in board_codes or tick in board_codes:
                groups["上榜但无"].append(r)
            else:
                groups["未上榜"].append(r)
    OUT["R5_席位x恐慌"] = {k: stat(v) for k, v in groups.items()}
    for k, v in groups.items():
        print(f"R5 {k}: {stat(v)}", flush=True)


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    for fn in (r1, r2, r3, r4, r5):
        try:
            fn(stocks)
        except Exception as e:
            print(f"[ERR] {fn.__name__}: {e}", flush=True)
            OUT[fn.__name__ + "_error"] = str(e)
        (ROOT / "data/research_queue_20260919.json").write_text(
            json.dumps(OUT, ensure_ascii=False, indent=1))
    print("saved", ROOT / "data/research_queue_20260919.json")


if __name__ == "__main__":
    main()
