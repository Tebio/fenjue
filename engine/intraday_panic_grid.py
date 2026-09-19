#!/usr/bin/env python3
"""intraday_panic_grid.py — 恐慌组合的盘中择时网格（2026-09-19 用户问 10:30后/尾盘买卖）。

复用 exec_timing_m60 的 m60 装载。事件=lp REGISTRY 恐慌系信号（日线判定），
盘中价格=m60 四根 bar（10:30/11:30/14:00/15:00 收盘 + 9:30 开盘）。
A. 入场时点网格：T+1 日 9:30开/10:30/11:30/14:00/15:00（尾盘）买 → T+5 收盘卖
B. 离场时点网格：T+1 开盘买 → 离场日 9:30/10:30/11:30/14:00/15:00 卖
窗口：2024-08-26→（m60 仅 2 年深，近期偏重，结论标注口径）
"""
import glob
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import law_pipeline as lp
from exec_timing_m60 import load_m60, nw_t

ROOT = Path(__file__).resolve().parent.parent
M60 = ROOT / "data/m60_cache"
FEE = 0.0015
WIN0 = "2024-08-26"
SIGS = ["跌停接_MA60下", "组合_跌停低_三连阴", "组合_跌停低_长周期_超跌20"]
SLOTS = [("9:30开", None), ("10:30", 0), ("11:30", 1), ("14:00", 2), ("15:00尾盘", 3)]



def _paired_t(a, b):
    """配对 t（红队S7，无 scipy 依赖）：mean(diff)/(sd/sqrt(n))"""
    ds = [x - y for x, y in zip(a, b)]
    n = len(ds)
    if n < 3:
        return 0.0
    m = sum(ds) / n
    sd = (sum((x - m) ** 2 for x in ds) / (n - 1)) ** 0.5
    return round(m / (sd / n ** 0.5), 1) if sd > 0 else 0.0

def slot_price(bars, slot):
    return bars[0]["open"] if slot is None else bars[slot]["close"]


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    m60_files = {Path(f).stem: f for f in glob.glob(str(M60 / "*.json"))}
    rng = random.Random(7)

    for name in SIGS:
        det = lp.REGISTRY[name]
        entry_grid = {s[0]: [] for s in SLOTS}
        exit_grid = {s[0]: [] for s in SLOTS}
        skipped = 0
        for code, d in stocks.items():
            if code not in m60_files:
                continue
            m6 = None
            # ex-div 哨兵（对齐 exec_timing_m60：m60 不复权 vs kcache 前复权，比值漂移>1.5% 的日期标记）
            ks_dates = d["date"]
            kc_close = d["c"]
            ratio, flagged, prev = {}, set(), None
            _m6_tmp = None
            for i2, dt2 in enumerate(ks_dates):
                if _m6_tmp is None and code in m60_files:
                    _m6_tmp = load_m60(m60_files[code])
                if _m6_tmp and dt2 in _m6_tmp and _m6_tmp[dt2] and kc_close[i2] > 0:
                    ratio[dt2] = _m6_tmp[dt2][-1]["close"] / kc_close[i2]
            prev_i = None
            for _i2, dt2 in enumerate(ks_dates):
                if dt2 in ratio:
                    if prev_i is not None and _i2 - prev_i == 1 and abs(ratio[dt2] / ratio[ks_dates[prev_i]] - 1) > 0.015:
                        flagged.add(dt2)   # 红队S8：只在相邻交易日判定，跨缺口不比
                    prev_i = _i2
            m6 = _m6_tmp
            for i in range(61, d["n"] - 7):
                try:
                    if not det(d, i):
                        continue
                except Exception:
                    continue
                ei = i + 1
                xi = ei + 5
                if xi >= d["n"]:
                    continue
                ed, xd = d["date"][ei], d["date"][xi]
                if ed < WIN0:
                    continue
                if any(dd in flagged for dd in ks_dates[i:xi + 1]):   # 除权跨度剔除
                    skipped += 1
                    continue
                if m6 is None:
                    continue
                be, bx = m6.get(ed), m6.get(xd)
                if not be or not bx or len(be) < 4 or len(bx) < 4:
                    skipped += 1
                    continue
                # 一字跌停买不进（开盘≈跌停：bar0 open 贴信号日收盘×0.905）
                if be[0]["open"] <= d["c"][i] * 0.905:
                    skipped += 1
                    continue
                # A 入场网格：各时点买 → T+5 尾盘卖
                for sname, slot in SLOTS:
                    r = bx[3]["close"] / slot_price(be, slot) - 1 - FEE
                    entry_grid[sname].append(r)
                # B 离场网格：9:30 买 → 离场日各时点卖
                for sname, slot in SLOTS:
                    r = slot_price(bx, slot) / be[0]["open"] - 1 - FEE
                    exit_grid[sname].append(r)

        print(f"\n=== {name}（窗口 {WIN0}→今，2年）")
        base_e = entry_grid["9:30开"]
        for sname, _ in SLOTS:
            rs = entry_grid[sname]
            wins = sum(x > 0 for x in rs)
            mean = 100 * sum(rs) / len(rs)
            winsl = [x for x in rs if x > 0]
            lossl = [x for x in rs if x <= 0]
            odds = (sum(winsl) / len(winsl)) / abs(sum(lossl) / len(lossl)) if winsl and lossl else 0
            t = _paired_t(rs, base_e) if sname != "9:30开" else 0   # 红队S7：同事件配对t
            print(f"  入场{sname:<8} n={len(rs)} 胜{100*wins/len(rs):.1f}% 均{mean:+.2f}% 赔{odds:.2f} 对开盘差t={t:.1f}")
        base_x = exit_grid["15:00尾盘"]
        for sname, _ in SLOTS:
            rs = exit_grid[sname]
            wins = sum(x > 0 for x in rs)
            mean = 100 * sum(rs) / len(rs)
            t = _paired_t(rs, base_x) if sname != "15:00尾盘" else 0
            print(f"  离场{sname:<8} n={len(rs)} 胜{100*wins/len(rs):.1f}% 均{mean:+.2f}% 对尾盘差t={t:.1f}")
        print(f"  (剔除不可成交/缺bar {skipped})")


if __name__ == "__main__":
    main()
