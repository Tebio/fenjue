#!/usr/bin/env python3
"""engine/zhaban_backtest.py — 炸板回踩买点回测（金风模式，2026-09-12 用户立项「都搞」#3）

原型（用户实盘）：主线行情末期，龙头涨停开盘，炸板回踩到 +8% 时买入，其后 +40%。
与已证伪的「连板分歧日水下低吸」（n=10498，次日 -1.57% 全灭）的关键区别：
  水下低吸 = 炸到负值（弱势）；金风模式 = 高开炸板但**回踩不翻绿**（强势洗盘）。
信号（日K 8 年全宇宙）：
  T-1 涨停（涨幅≥9.8%）；T 日开盘涨幅 ≥+5%；T 日最低涨幅 ∈ [+3%, +8.5%]（炸板未深砸）
  子类：R=回封（收盘≥+9.8%）/ U=未回封
入场假设（两种，诚实标注乐观度）：
  opt = 买在当日最低（理想成交，乐观上界）
  mid = 买在 (最低+收盘)/2（保守代理）
出场：T+1 开盘卖 / T+1 收盘卖 / T+5 收盘卖。费 0.15%。
检验：双段、regime、位置匹配对照（同票同MA60侧随机日，mid 入场口径）、NW-t。
"""
import json, sys, random, statistics as st
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = Path("/opt/data/fenjue")
FEE = 0.0015


def S(rs):
    if len(rs) < 30:
        return None
    m = st.mean(rs)
    return {"n": len(rs), "win%": round(100*sum(r > 0 for r in rs)/len(rs), 1),
            "mean%": round(100*m, 2), "med%": round(100*st.median(rs), 2)}


def main():
    stocks = lp.load_universe()
    regime = lp.load_regime()
    events = {"R": [], "U": []}  # (code, i, entry_opt, entry_mid)
    for code, d in stocks.items():
        c, o, h, l, n = d["c"], d["o"], d["h"], d["l"], d["n"]
        for i in range(61, n - 6):
            pc = c[i-1]
            if pc <= 0:
                continue
            g_prev = (c[i-1]/c[i-2]-1)*100 if i >= 2 and c[i-2] > 0 else 0
            if g_prev < 9.8:
                continue
            g_open = (o[i]/pc-1)*100 if o[i] > 0 else -99
            g_low = (l[i]/pc-1)*100 if l[i] > 0 else -99
            g_close = (c[i]/pc-1)*100
            if g_open < 5 or not (3 <= g_low <= 8.5):
                continue
            grp = "R" if g_close >= 9.8 else "U"
            e_opt = l[i]
            e_mid = (l[i] + c[i]) / 2
            events[grp].append((code, i, e_opt, e_mid))

    out = {"meta": {"fee": FEE, "def": "T-1涨停+T开>=5%+T最低涨幅3~8.5%",
                    "entry": "opt=买在最低(乐观上界) mid=(最低+收)/2(保守)"}}
    for grp, evs in events.items():
        res = {}
        for ekey, ei in (("opt", 2), ("mid", 3)):
            for label, fn in {
                "T+1开盘卖": lambda c, o, i, e: (o[i+1]/e-1-FEE) if o[i+1] > 0 else None,
                "T+1收盘卖": lambda c, o, i, e: (c[i+1]/e-1-FEE),
                "T+5收盘卖": lambda c, o, i, e: (c[i+5]/e-1-FEE),
            }.items():
                rs = []
                for code, i, e2, e3 in evs:
                    d = stocks[code]
                    v = fn(d["c"], d["o"], i, (e2, e3)[ei-2])
                    if v is not None:
                        rs.append(v)
                s = S(rs)
                if s and label == "T+5收盘卖":
                    s["t_NW"] = lp.nw_t(rs, 5)
                res[f"{ekey}_{label}"] = s
        # 分段（mid, T+1收盘卖）
        seg_t, seg_r = defaultdict(list), defaultdict(list)
        for code, i, e2, e3 in evs:
            d = stocks[code]
            r = d["c"][i+1]/e3-1-FEE
            dt = d["date"][i]
            seg_t["2019-2022" if dt < "2023" else "2023-2026"].append(r)
            seg_r[regime.get(dt, "?")].append(r)
        res["seg_time_mid_T1c"] = {k: S(v) for k, v in seg_t.items()}
        res["seg_regime_mid_T1c"] = {k: S(v) for k, v in sorted(seg_r.items()) if S(v)}
        out[grp] = res
        print(f"=== {grp} ===", json.dumps(res, ensure_ascii=False), flush=True)

    # 位置匹配对照（合并 R+U，mid 入场，T+1收盘卖）
    rnd = random.Random(7)
    sig, ctl = [], []
    ev_by_code = defaultdict(list)
    for grp in ("R", "U"):
        for code, i, e2, e3 in events[grp]:
            ev_by_code[code].append((i, e3))
    for code, items in ev_by_code.items():
        d = stocks[code]
        c, ma, n = d["c"], d["ma60"], d["n"]
        lows, highs = [], []
        for i in range(61, n - 6):
            if ma[i] is not None:
                (lows if c[i] <= ma[i] else highs).append(i)
        lo_n = sum(1 for i, _ in items if ma[i] is not None and c[i] <= ma[i])
        for i, e in items:
            sig.append(c[i+1]/e-1-FEE)
        for pool, k in ((lows, lo_n), (highs, len(items)-lo_n)):
            if pool and k:
                for i in rnd.sample(pool, min(k, len(pool))):
                    ctl.append(c[i+1]/c[i]-1-FEE)
    if len(sig) >= 30 and len(ctl) >= 30:
        out["matched_mid_T1c"] = {"sig%": round(100*st.mean(sig), 2), "ctl%": round(100*st.mean(ctl), 2),
                                   "marginal_pp": round(100*(st.mean(sig)-st.mean(ctl)), 2), "n": len(sig)}
    print("matched:", json.dumps(out.get("matched_mid_T1c"), ensure_ascii=False))
    (ROOT/"data/zhaban_backtest_20260912.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    print("SAVED data/zhaban_backtest_20260912.json")


if __name__ == "__main__":
    main()
