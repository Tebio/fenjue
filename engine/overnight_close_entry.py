#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine/overnight_close_entry.py — 存活线入场时点叠加：T尾盘买 vs T+1开盘买（卡 t_9e69cd05）

任务③：文献方向「隔夜负→次日盘中强」已在全宇宙证实（engine/overnight_effect.py ③）；
本脚本把它落到既有存活线的入场时点决策上——深档(DEEP)/跌停接(LD)/反转族(REV)的
T+1 开盘买入是否该改为 T 日尾盘买（信号日收盘已知，T+1 物理可行）。

口径（逐字复刻生产定义，见 engine/auction_confirm_backtest.py / law_pipeline.py）
- ma60 = law_pipeline 滞后一根口径（ma60[i]=mean(c[i-60..i-1])，#290 注记）。
- REV：T 收收≤-3% 且 T 开/昨收>-9.5% 且 v*c≥8e7；生产 confirm：剔 T+1 gap≤-9.5% 个股
  + 当日（剔一字后）gap≥+1% 占比>1/3 整日作废。后两步用了 T+1 开盘信息，
  改 T 尾盘买则**物理不可用**——双口径并出。
- LD：_limitdown（≤-9.5% 剔全天一字锁死）∩ 收≤ma60；生产剔 T+1 一字跌停开。
- DEEP：跌停 ∩ 收≤ma60 ∩ 深度≤-25% 计簇（簇门≥5），出手票=深度≤-35% 最深前5；
  台账口径不剔一字跌停开（#290②）。

双臂：OPEN 臂入场 o[i+1]、CLOSE 臂入场 c[i]；出场 c[i+h]，h∈{1,5,10}，净费 FLAT_RT（双臂同费）。
判定：配对差 + 符号置换检验（B=5000）+ 日历时间日度均值差 NW-t。
叠加候选：9:25 竞价 gap 已知后的条件过滤网格（在 OPEN 臂上，合法时点）。

内存纪律（15GB 机；本脚本第一版 load_universe 全宇宙驻内存 → exit 137 实测）：
两遍流式——① 只留事件 ID（code,i）+簇计数，逐文件即弃；② 按事件所在票二次加载取价。
复跑：.venv/bin/python engine/overnight_close_entry.py（纯离线，~2 分钟）
产物：data/overnight_close_entry_20261016.json
"""
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import law_pipeline as lp  # noqa: E402
from costs import FLAT_RT  # noqa: E402

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data" / "big_kcache"
OUT = ROOT / "data/overnight_close_entry_20261016.json"
FEE = FLAT_RT
HS = (1, 5, 10)          # 出场 = c[i+h]
GAP_EDGES = [(-99, -0.095), (-0.095, -0.05), (-0.05, -0.03), (-0.03, -0.01),
             (-0.01, 0.0), (0.0, 0.01), (0.01, 0.02), (0.02, 0.04), (0.04, 99)]


def _limitdown(c, o, h, l, i, pc):
    """逐条对齐 law_pipeline._limitdown（剔全天一字锁死）。"""
    if pc <= 0 or c[i] / pc - 1 > -0.095:
        return False
    if o[i] / pc - 1 <= -0.09 and (h[i] - l[i]) / pc < 0.01:
        return False
    return True


def scan_events():
    """流式一遍：返回 (events, 深档批数[lagged 口径], 深档批数[含当日口径审计])。"""
    ev = {"REV": [], "LD": [], "DEEP": []}
    d25, d25_td = defaultdict(int), defaultdict(int)
    dcand = []                                    # (code, day, i, depth)
    for fp in sorted(glob.glob(str(KC / "*.json"))):
        code = Path(fp).stem
        if code[:2] not in ("60", "00"):
            continue
        ks = json.loads(open(fp).read())
        n = len(ks)
        if n < 300:
            continue
        c = np.array([k["close"] for k in ks])
        o = np.array([k["open"] for k in ks])
        h = np.array([k["high"] for k in ks])
        l = np.array([k["low"] for k in ks])
        v = np.array([k.get("volume", 0.0) for k in ks])
        dates = [k["date"] for k in ks]
        S = np.concatenate([[0.0], np.cumsum(c)])
        ma = np.full(n, np.nan)
        ma[60:] = (S[60:n] - S[:n - 60]) / 60           # lagged：ma[i]=mean(c[i-60..i-1])
        ma_td = np.full(n, np.nan)
        ma_td[59:] = (S[60:] - S[:-60]) / 60            # 含当日（仅审计簇数）
        for i in range(lp.START, n - 11):
            pc = c[i - 1]
            if pc <= 0:
                continue
            chg = c[i] / pc - 1
            if chg <= -0.03 and o[i] / pc - 1 > -0.095 and v[i] * c[i] >= 8e7:
                ev["REV"].append((code, i))
            if chg <= -0.095:
                if np.isfinite(ma[i]) and ma[i] > 0 and c[i] <= ma[i]:
                    dep = c[i] / ma[i] - 1
                    if dep <= -0.25:
                        d25[dates[i]] += 1
                        dcand.append((code, dates[i], i, dep))
                if np.isfinite(ma_td[i]) and c[i] <= ma_td[i] * 0.75:
                    d25_td[dates[i]] += 1
            if np.isfinite(ma[i]) and c[i] <= ma[i] and _limitdown(c, o, h, l, i, pc):
                ev["LD"].append((code, i))
        del c, o, h, l, v, S, ma, ma_td, ks, dates
    picks = defaultdict(list)
    for code, day, i, dep in dcand:
        if dep <= -0.35 and d25[day] >= 5:
            picks[day].append((code, i, dep))
    deep = []
    for day, lst in picks.items():
        lst.sort(key=lambda x: x[2])
        deep.extend((c0, i0) for c0, i0, _ in lst[:5])
    ev["DEEP"] = deep
    return ev, sum(1 for k in d25 if d25[k] >= 5), sum(1 for k in d25_td if d25_td[k] >= 5)


def enrich(ev):
    """第二遍：按事件所在票二次加载，取入场双价与三档出场价（每票只加载一次）。"""
    bycode = defaultdict(list)
    for line, items in ev.items():
        for code, i in items:
            bycode[code].append((line, i))
    rows = {k: [] for k in ev}
    for code, items in bycode.items():
        ks = json.loads(open(KC / f"{code}.json").read())
        n = len(ks)
        c = np.array([k["close"] for k in ks])
        o = np.array([k["open"] for k in ks])
        dates = [k["date"] for k in ks]
        for line, i in items:
            if i + 1 >= n or o[i + 1] <= 0 or c[i] <= 0:
                continue
            rows[line].append({
                "code": code, "i": i, "date": dates[i], "entry_date": dates[i + 1],
                "gap": float(o[i + 1] / c[i] - 1), "po": float(o[i + 1]), "pc": float(c[i]),
                "ex": {hh: (float(c[i + hh]) if i + hh < n else np.nan) for hh in HS}})
        del c, o, ks, dates
    return rows


def S1(x):
    x = np.asarray(x, dtype=float); x = x[np.isfinite(x)]
    if len(x) < 10:
        return {"n": int(len(x))}
    return {"n": int(len(x)), "win%": round(100 * float(np.mean(x > 0)), 1),
            "mean%": round(100 * float(np.mean(x)), 3),
            "med%": round(100 * float(np.median(x)), 3),
            "t_NW": lp.nw_t([float(v) for v in x], 5)}


def perm_test(diff, B=5000, seed=7):
    """符号置换检验（配对差的零分布）。分块计算（REV 类 30 万级样本 × B=5000 的全矩阵
    = 1.7e9 float ≈ 13.8GB，15GB 机上必 OOM——实测 exit 137）。"""
    d = np.asarray(diff, dtype=float); d = d[np.isfinite(d)]
    if len(d) < 30:
        return None
    rng = np.random.default_rng(seed)
    obs = float(np.mean(d))
    n = len(d)
    cnt_ge = 0
    step = max(1, int(4e7 // max(n, 1)))          # 每块 ≤ ~40M float
    done = 0
    while done < B:
        b = min(step, B - done)
        null = (rng.choice((-1.0, 1.0), size=(b, n)) * d).mean(axis=1)
        cnt_ge += int(np.sum(np.abs(null) >= abs(obs)))
        done += b
    return {"mean_diff_pp": round(100 * obs, 3), "p": round(cnt_ge / B, 4),
            "win配对%": round(100 * float(np.mean(d > 0)), 1), "n": int(n)}


def cal_t_diff(rows, diff):
    """日历时间：配对差按入场日聚日度均值 → NW-t（治成簇横截面相关）。"""
    by = defaultdict(list)
    for r, dd in zip(rows, diff):
        if np.isfinite(dd):
            by[r["entry_date"]].append(float(dd))
    series = [float(np.mean(v)) for _, v in sorted(by.items())]
    if len(series) < 30:
        return None
    return {"days": len(series), "diff_bp/day": round(1e4 * float(np.mean(series)), 1),
            "t_NW": lp.nw_t(series, 5)}


def gap_grid(rows, rO):
    """9:25 竞价 gap 已知后的条件叠加网格（在 OPEN 臂上，时点合法）。"""
    gaps = np.array([r["gap"] for r in rows])
    out = {"分桶": {}}
    for hh in HS:
        buckets = []
        for lo, hi in GAP_EDGES:
            m = (gaps > lo) & (gaps <= hi)
            if m.sum() >= 30:
                buckets.append({"bin": f"({lo},{hi}]", **S1(rO[hh][m])})
        out["分桶"][f"T+{hh}"] = buckets
    rules = {}
    for name, m in (("gap≤-2%才买", gaps <= -0.02), ("gap≤-3%才买", gaps <= -0.03),
                    ("剔gap≥+1%", gaps < 0.01), ("剔gap≥+2%", gaps < 0.02),
                    ("gap≤0才买", gaps <= 0.0)):
        rules[name] = {f"T+{hh}": S1(rO[hh][m]) for hh in HS}
        rules[name]["覆盖率%"] = round(100 * float(np.mean(m)), 1)
    out["候选规则"] = rules
    return out


def main():
    ev, n_lag, n_td = scan_events()
    print(f"clusters: lagged={n_lag} batches vs 含当日={n_td}（台账锚=65）", flush=True)
    rows_all = enrich(ev)
    res = {"_meta": {"owner": "engine.overnight_close_entry", "task": "t_9e69cd05",
                     "fee": FEE, "horizons": list(HS),
                     "deep_batches_lagged": n_lag, "deep_batches_today": n_td,
                     "口径": "ma60=law_pipeline滞后一根；双臂同费；置换 B=5000",
                     "note": "CLOSE 臂对 REV/LD 的 T+1 信息过滤（一字开/日级作废）不可用→全集照吃"},
           "lines": {}}
    for line, rows in rows_all.items():
        rO = {hh: np.array([r["ex"][hh] / r["po"] - 1 - FEE for r in rows]) for hh in HS}
        rC = {hh: np.array([r["ex"][hh] / r["pc"] - 1 - FEE for r in rows]) for hh in HS}
        gaps = np.array([r["gap"] for r in rows])
        void = set()
        if line == "REV":
            by_day = defaultdict(list)
            for k, r in enumerate(rows):
                if r["gap"] > -0.095:
                    by_day[r["entry_date"]].append(k)
            void = {d for d, ks_ in by_day.items()
                    if sum(1 for k in ks_ if rows[k]["gap"] >= 0.01) / len(ks_) > 1 / 3}
            prod = np.array([r["gap"] > -0.095 and r["entry_date"] not in void for r in rows])
        elif line == "LD":
            prod = gaps > -0.095
        else:
            prod = np.ones(len(rows), bool)
        lr = {"n_full": len(rows), "n_open_prod": int(prod.sum()), "整日作废日数": len(void)}
        for hh in HS:
            lr[f"T+{hh}"] = {
                "OPEN生产": S1(rO[hh][prod]), "CLOSE全集": S1(rC[hh]),
                "配对差(CLOSE-OPEN,生产子集)": perm_test((rC[hh] - rO[hh])[prod]),
                "配对差日历时间": cal_t_diff([r for r, m in zip(rows, prod) if m],
                                          (rC[hh] - rO[hh])[prod]),
                "被剔一字开_OPEN口径": S1(rO[hh][~prod]) if line != "DEEP" else None,
                "被剔一字开_CLOSE口径": S1(rC[hh][~prod]) if line != "DEEP" else None}
        sub = [r for r, m in zip(rows, prod) if m]
        lr["gap叠加网格"] = gap_grid(sub, {hh: rO[hh][prod] for hh in HS})
        for arm, rr, mask in (("OPEN", rO, prod), ("CLOSE", rC, np.ones(len(rows), bool))):
            by_y = defaultdict(list)
            for r, m, ret in zip(rows, mask, rr[5]):
                if m and np.isfinite(ret):
                    by_y[r["date"][:4]].append(float(ret))
            lr[f"分年{arm}_T+5"] = {y: {"n": len(v),
                                     "win%": round(100 * float(np.mean(np.array(v) > 0)), 1),
                                     "mean%": round(100 * float(np.mean(v)), 2)}
                                  for y, v in sorted(by_y.items()) if len(v) >= 10}
        res["lines"][line] = lr
        print(line, "n=", len(rows), "open_prod=", int(prod.sum()), flush=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print("->", OUT)


if __name__ == "__main__":
    main()
