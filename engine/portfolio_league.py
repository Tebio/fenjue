#!/usr/bin/env python3
"""engine/portfolio_league.py — 组合配置反事实联赛（2026-10-16 卡 t_091c012a，#289 组合层深挖）

回答的问题：「每一格配置（替换/剔除/槽位/资金/regime门）分别值多少钱」——给待裁决配置项配数字。

复用 engine/portfolio.py 的信号生成与账本（零新探测、口径唯一真源），只做配置枚举。
每格 = 一次完整组合模拟（合并净值/回撤/逐年/资金占用/2025 归因）。

格子清单（cells）：
  A  baseline        现状并存：atk=[DEEP_V2,LD,REV_KNN,REV_RES08,REV]
  B  replace_revknn  REV_KNN 替代 REV：atk=[DEEP_V2,LD,REV_KNN]
  C  solo_rev        单 REV
  D  solo_revknn     单 REV_KNN
  E  no_ld           剔除 LD：atk=[DEEP_V2,REV_KNN,REV_RES08,REV]
  F..  ablation_<线>  基线逐线剔除（各线 2025 边际贡献）
  G  slot{c}cap{k}   槽位 3/5/8 × 资金 5/10/20 万（九宫格，atk 槽数变化，div5/cb3 不变）
  R  panic_half      regime 门增强版：恐慌期进攻账户仓位上限减半（基线配置）
  R2 panic_half_rep  panic 门 × REV_KNN 替代配置

纪律：DSR 分母如实报 trials=格子数；最优格必须在优化窗（2019-2022）选出、在留出段
（2023-2026 与 2024+）验证，防配置过拟合。单一配置不做样本外声明。

用法： .venv/bin/python engine/portfolio_league.py            # 全量（~15-25 分钟）
       .venv/bin/python engine/portfolio_league.py report      # 读最新 JSON 打印摘要
产出： data/portfolio_league_YYYYMMDD.json（逐格指标 + 九宫格矩阵 + 归因 + 最优格）
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
sys.path.insert(0, str(ROOT / "engine"))
import portfolio as P  # noqa: E402
from line_health import load_universe_lean  # noqa: E402  低内存 loader（同值）

TIERS = P.TIERS
SPLIT_OOS = "2023-01-01"
SPLIT_2024 = "2024-01-01"
ATK_ALL = ["DEEP_V2", "LD", "REV_KNN", "REV_RES08", "REV"]


def merge_entries(entries_by_line, lines):
    """把逐线 entries 合并成一份当日待买清单（保留原 prio，模拟器内部再按 (prio, -rank) 排序）。"""
    out = {}
    for ln in lines:
        for day, evs in entries_by_line[ln].items():
            out.setdefault(day, []).extend(evs)
    return out


def seg_metrics(curve, lo=None, hi=None):
    """区段指标：curve=[(date, equity)]。返回 final_x/ann%/mdd%/yearly%。"""
    sub = [(d, e) for d, e in curve if (lo is None or d >= lo) and (hi is None or d < hi)]
    if len(sub) < 5:
        return None
    base = sub[0][1]
    yrs = len(sub) / 244.0
    final = sub[-1][1] / base
    peak, mdd = -1e18, 0.0
    for _, e in sub:
        peak = max(peak, e)
        mdd = min(mdd, e / peak - 1)
    yearly = {}
    for d, e in sub:
        yearly.setdefault(d[:4], []).append(e)
    return {"x": round(final, 3),
            "ann%": round((final ** (1 / yrs) - 1) * 100, 2),
            "mdd%": round(mdd * 100, 1),
            "yearly%": {y: round((v[-1] / v[0] - 1) * 100, 1) for y, v in yearly.items()}}


def daily_series(curve):
    """逐日权益序列（用于 DSR / 相关性）。"""
    return [curve[k][1] - (curve[k - 1][1] if k else curve[0][1]) for k in range(len(curve))]


def dsr_from_curve(curve, trials):
    import statistics as st
    r = [curve[k][1] / curve[k - 1][1] - 1 for k in range(1, len(curve)) if curve[k - 1][1] > 0]
    if len(r) < 30:
        return None
    m, s = st.mean(r), st.pstdev(r)
    if s <= 0:
        return None
    sr_d = m / s
    sk = P.lp._skew(r)
    ku = P.lp._kurt(r)
    return P.lp.deflated_sharpe(sr_d, len(r), sk, ku, trials=trials)


def _n_by_line(trades):
    out = {}
    for t in trades:
        out[t["line"]] = out.get(t["line"], 0) + 1
    return out


def run_cell(name, capital, lines, entries, ctx, slots=None, split=None, panic_half=False,
             solo=False):
    t0 = time.time()
    curve, trades, inv, books = P.simulate(entries, capital, ctx["calendar"], ctx["stocks"],
                                          ctx["didx"], ctx["cb_didx"], ctx["cb_bars"],
                                          ctx["ttm_map"], lines,
                                          slots=slots, split=split, panic_half=panic_half,
                                          solo=solo)
    m = P.metrics(curve, trades, inv)
    drag = sum(max(0.0, 10.0 - 0.0005 * t["notional"]) for t in trades)
    contrib = {}
    for t in trades:
        y = t["exit_d"][:4]
        contrib.setdefault(y, {})
        contrib[y][t["line"]] = round(contrib[y].get(t["line"], 0.0) + t["pnl"], 0)
    cell = {"name": name, "capital": capital, "lines": lines, "panic_half": panic_half,
            "slots": slots or P.SLOTS, "split": split or P.SPLIT,
            "full": m, "contrib": contrib, "n_by_line": _n_by_line(trades),
            "min_comm_drag元": round(drag, 0),
            "seg_1922": seg_metrics(curve, None, SPLIT_OOS),
            "seg_2326": seg_metrics(curve, SPLIT_OOS, None),
            "seg_24p": seg_metrics(curve, SPLIT_2024, None),
            "secs": round(time.time() - t0, 1)}
    return cell, curve


def main():
    t0 = time.time()
    P.load_regime()
    print("[league] 加载宇宙（lean）…", flush=True)
    stocks = load_universe_lean()
    names = {str(s["code"]).zfill(6): s.get("name", "")
             for s in json.loads((ROOT / "data/main_board_codes.json").read_text())["stocks"]}
    calendar = [k["date"] for k in json.loads((ROOT / "data/index_sh000001.json").read_text())]
    didx = {c: {x: j for j, x in enumerate(s["date"])} for c, s in stocks.items()}
    print(f"[league] 宇宙 {len(stocks)} 只 / 日历 {len(calendar)} 天 ({time.time()-t0:.0f}s)", flush=True)

    rev, ld, deep = P.gen_stock_signals(stocks, names)
    deep5 = P.deep_picks(deep)
    knn, res08 = P.knn_variants(rev)
    divh = json.loads((ROOT / "data/dividend_history.json").read_text())
    div_sigs, ttm_map, _uni = P.gen_div_signals(stocks, names, divh)
    cb_sigs, cb_bars = P.gen_cb_signals()
    cb_didx = {c: {r["date"]: j for j, r in enumerate(rows)} for c, rows in cb_bars.items()}
    print(f"[league] 信号就绪 ({time.time()-t0:.0f}s)", flush=True)

    sigs_all = {"DEEP_V2": deep5, "LD": ld, "REV": rev, "REV_KNN": knn, "REV_RES08": res08,
                "DIV": div_sigs, "CB": cb_sigs}
    entries_by_line = {ln: P.build_entries({ln: sigs_all[ln]}, didx, stocks, cb_bars)
                       for ln in sigs_all}
    ctx = {"calendar": calendar, "stocks": stocks, "didx": didx,
           "cb_didx": cb_didx, "cb_bars": cb_bars, "ttm_map": ttm_map}

    # 锚点自检（与 #289 对齐：LD≈68%/+5.09%、DEEP 出手票≈60.7%/+6.29%）
    anchors = {
        "LD_T+5": P.event_anchor(ld, stocks, P.HOLD_T),
        "DEEP_V2_top5_T+5": P.event_anchor(deep5, stocks, P.HOLD_T),
        "CB_T+120": P.cb_event_anchor(cb_sigs, cb_bars),
        "deep_batches": len(deep5),
        "event_counts": {k: sum(len(v) for v in sigs_all[k].values()) for k in sigs_all},
    }
    print("[league] 锚点:", json.dumps(anchors, ensure_ascii=False), flush=True)

    cells, curves = [], {}
    cal_range = [calendar[0], calendar[-1]]

    def add(name, capital, lines, **kw):
        cell, curve = run_cell(name, capital, lines, merge_entries(entries_by_line, lines),
                              ctx, **kw)
        cells.append(cell)
        curves[name] = curve
        _flush(cells, anchors, curves)
        f = cell["full"]
        print(f"[league] {name:22s} cap={capital:6d} x={f.get('final_x')} ann={f.get('ann%')}% "
              f"mdd={f.get('mdd%')}% y2025={f.get('yearly%', {}).get('2025')} ({cell['secs']}s)",
              flush=True)
        return cell

    # ---- ① REV_KNN 替代 vs 并存 vs 单线（全七线口径，与 #289 锚 1.339x 可比）----
    ALL7 = ATK_ALL + ["DIV", "CB"]

    def add7(name, lines_atk, **kw):
        return add(name, 100000, lines_atk + ["DIV", "CB"], **kw)

    add7("A_baseline", ATK_ALL)
    add7("B_replace_revknn", ["DEEP_V2", "LD", "REV_KNN"])
    add("C_solo_rev", 100000, ["REV"], solo=True)
    add("D_solo_revknn", 100000, ["REV_KNN"], solo=True)
    # ---- ② 剔除 LD ----
    add7("E_no_ld", ["DEEP_V2", "REV_KNN", "REV_RES08", "REV"])
    # ---- ④ 逐线剔除（2025 归因）----
    for ln in ATK_ALL:
        add7(f"F_ablate_{ln}", [x for x in ATK_ALL if x != ln])
    # ---- ③ 九宫格：槽位 3/5/8 × 资金 5/10/20 万 ----
    for cap in TIERS:
        for sl in (3, 5, 8):
            slots = dict(P.SLOTS)
            slots["atk"] = sl
            add(f"G_slot{sl}_cap{cap//10000}w", cap, ALL7, slots=slots)
    # ---- ⑤ regime 门增强版 ----
    add7("R_panic_half", ATK_ALL, panic_half=True)
    add7("R2_panic_half_rep", ["DEEP_V2", "LD", "REV_KNN"], panic_half=True)

    _finalize(cells, curves, anchors, t0, cal_range)


def _flush(cells, anchors, curves):
    """逐格落盘（进程被杀/超时也保住进度）。"""
    out = {"_meta": {"produced_by": "engine/portfolio_league.py", "partial": True,
                     "produced_at": time.strftime("%Y-%m-%d %H:%M:%S")},
           "anchors": anchors, "cells": cells,
           "cells_done": [c["name"] for c in cells]}
    (ROOT / "data/portfolio_league_partial.json").write_text(json.dumps(out, ensure_ascii=False))


def _finalize(cells, curves, anchors, t0, cal_range):
    n_trials = len(cells)
    # DSR（trials = 格子数，如实报；另报 7491+格子数 的严口径）
    for c in cells:
        cv = curves[c["name"]]
        c["dsr_trialsN"] = dsr_from_curve(cv, n_trials)
        c["dsr_trials7491"] = dsr_from_curve(cv, 7491 + n_trials)
    # 槽位×资金矩阵（只看 G_ 前缀）
    grid = {f"{c['slots']['atk']}槽|{c['capital']//10000}万": {
        "final_x": c["full"]["final_x"], "ann%": c["full"]["ann%"],
        "mdd%": c["full"]["mdd%"], "util%": c["full"]["util%"],
        "trades": c["full"]["trades"], "win%": c["full"]["win%"],
        "y2025%": c["full"].get("yearly%", {}).get("2025")}
        for c in cells if c["name"].startswith("G_")}
    # 最优格：在优化窗 2019-2022 按 (x, -|mdd|) 选，再看留出段
    cand = [c for c in cells if c.get("seg_1922")]
    best = max(cand, key=lambda c: (c["seg_1922"]["x"], -abs(c["seg_1922"]["mdd%"])))
    base = next(c for c in cells if c["name"] == "A_baseline")
    # 2025 归因：基线 2025 逐线盈亏 + 各剔除格 2025 变化
    attrib_2025 = {
        "baseline_lines": base["contrib"].get("2025", {}),
        "baseline_2025_yearly%": base["full"]["yearly%"].get("2025"),
        "ablation_2025": {c["name"]: {"y2025%": c["full"]["yearly%"].get("2025"),
                                      "contrib_2025": c["contrib"].get("2025", {})}
                          for c in cells if c["name"].startswith("F_ablate_") or
                          c["name"] in ("B_replace_revknn", "E_no_ld")},
    }
    out = {"_meta": {"produced_by": "engine/portfolio_league.py", "partial": False,
                     "produced_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "calendar": cal_range,
                     "fee_roundtrip": P.FEE, "trials": n_trials,
                     "note": "DSR 分母 trials=格子数（配置过拟合防线）；最优格在 2019-2022 选出，"
                             "2023-2026 与 2024+ 为留出段验证"},
           "anchors": anchors, "trials": n_trials, "cells": cells,
           "grid_slots_x_capital": grid,
           "attrib_2025": attrib_2025,
           "best_by_1922": {"name": best["name"], "seg_1922": best["seg_1922"],
                            "seg_2326": best["seg_2326"], "seg_24p": best["seg_24p"],
                            "full": best["full"]},
           "baseline": {"name": base["name"], "full": base["full"],
                        "seg_1922": base["seg_1922"], "seg_2326": base["seg_2326"]},
           "secs_total": round(time.time() - t0, 0)}
    day = time.strftime("%Y%m%d")
    (ROOT / f"data/portfolio_league_{day}.json").write_text(json.dumps(out, ensure_ascii=False))
    print(f"\n[league] 落盘 data/portfolio_league_{day}.json  trials={n_trials} "
          f"({time.time()-t0:.0f}s)", flush=True)
    print_report(out)


def print_report(out):
    print("\n===== 组合配置反事实联赛 =====")
    for c in out["cells"]:
        f = c["full"]
        print(f"  {c['name']:22s} x={f['final_x']:5} ann={f['ann%']:6}% mdd={f['mdd%']:6}% "
              f"util={f['util%']:5}% n={f['trades']:5} win={f['win%']}% "
              f"|19-22 {c['seg_1922']['x']}x |23-26 {c['seg_2326']['x']}x "
              f"|24+ {c['seg_24p']['x']}x |DSR(N)={c['dsr_trialsN']} DSR(7491)={c['dsr_trials7491']}")
    print("\n九宫格（槽位×资金）：")
    for k, v in sorted(out["grid_slots_x_capital"].items()):
        print(f"  {k:12s} x={v['final_x']} ann={v['ann%']}% mdd={v['mdd%']}% util={v['util%']}%")
    print(f"\n最优格(2019-2022 选出)={out['best_by_1922']['name']} "
          f"19-22={out['best_by_1922']['seg_1922']['x']}x → "
          f"23-26={out['best_by_1922']['seg_2326']['x']}x → "
          f"24+={out['best_by_1922']['seg_24p']['x']}x")


def report():
    import glob
    fs = sorted(glob.glob(str(ROOT / "data/portfolio_league_2*.json")))
    fs = [f for f in fs if "partial" not in f]
    if not fs:
        print("无产物，先跑主模式")
        return
    print_report(json.loads(open(fs[-1]).read()))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        report()
    else:
        main()
