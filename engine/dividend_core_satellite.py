#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine/dividend_core_satellite.py — 红利「核心/卫星」分层模拟器（2026-09-13）

口径
----
- 宇宙：dividend_history.json 中「≥3 个不同年度有分红」且 名称不含 ST/退 的 A 股;
        实盘中再叠加「当日收盘价 > 2」的入场过滤。宇宙集合为静态集合, 与原
        engine/dividend_sim.py 完全一致。
- 息率：时点 TTM 息率 = 过去 365 日累计每股派现 (按分红日期轴 bisect_right)
        / 当日收盘价。前复权价只用于比率, 绝对价位跨除权日不可比。
- 交易时点：T 日收盘出信号 → T+1 日开盘成交。任何决策只用 ≤T 的数据,
              T+1 开盘之后的信息一律不可见（无未来函数）。
- 费用：双边各 0.0015。单笔净收益 = P_out/P_in - 1 - 2*0.0015。
- 资金：初始 100000, 每只固定名义仓 = 当前总权益 / 5。

分层规则
--------
- 核心仓：最多 3 只, 每只 1/5 仓。买入线 息率 ≥ 4.5%（次日开盘）;
          唯一息率卖点 息率 < 3.0%; 连续 500 交易日无分红强制清。
- 卫星仓：最多 2 只, 每只 1/5 仓。买入线 息率 ≥ 4.5%（次日开盘）;
          卖出线 息率 < 3.5%。
- 同票不可同时占两层。核心仓有空位时, 卫星仓中息率仍 ≥ 4.5% 的票
  优先转为核心（记录转移次数, 不产生买卖点、不计费用）。
- 每日顺序：开盘先卖 → 后买; 买入选股 = 当日宇宙内息率最高且未持仓者。

数据源
------
/opt/data/fenjue/data/big_kcache/*.json      日线 {date, open, close, ...}
/opt/data/fenjue/data/dividend_history.json  {code: [[分红日, 每股派现], ...]}
/opt/data/fenjue/data/industry_map.json      {code: {name: ...}}

输出
----
/opt/data/fenjue/data/dividend_core_satellite_20260913.json
/opt/data/fenjue/data/dividend_curve_cs_20260913.json
/opt/data/fenjue/data/红利分层_8年交易明细.csv   (utf-8-sig)

已知限制
--------
- 分红按除权日记账, 真实到账时滞与红利税未建模。
- 停牌日按成本估值; 开盘价缺失时卖单顺延至下一交易日重试。
- 「五大行躺平 +116.7%」为外部给定基准, 本文件不重算。
- 原版对照曲线读取 data/dividend_curve_20260912.json, 缺失时该列显示 n/a。
"""
import json
import glob
import sys
import csv
import bisect
from collections import defaultdict

ROOT = "/opt/data/fenjue"
D = ROOT + "/data"

START = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--start=")), "2019-01-03")
OUTSUF = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--out=")), "20260913")

FEE = 0.0015                 # 单边手续费
CAPITAL = 100000.0

BUY_Y = 0.045                # 建仓线（核心 / 卫星一致）
CORE_SELL_Y = 0.030          # 核心仓唯一息率卖点
SAT_SELL_Y = 0.035           # 卫星仓息率卖点
CORE_MAX, SAT_MAX = 3, 2
POS_FRAC = 0.2               # 每只名义仓 = 当前总权益的 1/5
NODIV_DAYS = 500             # 连续无分红交易日上限

# ============================== 数据加载 ==============================
stocks = {}
for f in sorted(glob.glob(f"{D}/big_kcache/*.json")):
    stocks[f.split("/")[-1][:6]] = json.load(open(f))

names = {c: v.get("name", "") for c, v in json.load(open(f"{D}/industry_map.json")).items()}
divh = json.load(open(f"{D}/dividend_history.json"))

cal = [k["date"] for k in stocks["000001"]]
dates = [d for d in cal if d >= START]
idx = {c: {k["date"]: j for j, k in enumerate(ks)} for c, ks in stocks.items()}

# ============================== 宇宙 ==============================
universe = []
for c, recs in divh.items():
    if c not in stocks:
        continue
    nm = names.get(c, "")
    if "ST" in nm or "退" in nm:
        continue
    if len({dt[:4] for dt, _ in recs}) >= 3:
        universe.append(c)
universe.sort()
print(f"宇宙: {len(universe)} 只（≥3年度分红 / 非ST退）", file=sys.stderr)

# ============================== 时点 TTM 分红 ==============================
div_dts = {c: sorted(d for d, _ in divh[c]) for c in universe}

ttm = {}
for c in universe:
    recs = sorted(divh[c])
    dts = [d for d, _ in recs]
    amts = [a for _, a in recs]
    arr = []
    for k in stocks[c]:
        d = k["date"]
        y = d[:4]
        prev_same = (str(int(y) - 1) + d[4:]) if y.isdigit() else d
        lo = bisect.bisect_right(dts, d)
        hi = bisect.bisect_right(dts, prev_same)
        arr.append(sum(amts[hi:lo]) if lo > hi else 0.0)
    ttm[c] = arr

# ============================== 工具 ==============================
def _j(c, d):
    return idx.get(c, {}).get(d)


def _open(c, d):
    j = _j(c, d)
    if j is None:
        return None
    px = stocks[c][j].get("open", 0) or 0
    return px if px > 0 else None


def _close(c, d):
    j = _j(c, d)
    if j is None:
        return None
    px = stocks[c][j].get("close", 0) or 0
    return px if px > 0 else None


def _yld(c, d):
    j = _j(c, d)
    if j is None:
        return None
    px = stocks[c][j].get("close", 0) or 0
    if px <= 0:
        return None
    return ttm[c][j] / px


# ============================== 主循环 ==============================
equity_cash = CAPITAL
core, sat = [], []            # 两层持仓 [{code, layer, entry, cash, entry_date, exit_day, exit_reason}]
trades = []
transfers = 0
curve = []
pending_buy = None            # {code, layer, day, cash}


def _mtm(d):
    v = 0.0
    for p in core + sat:
        px = _close(p["code"], d)
        v += p["cash"] * (px / p["entry"]) if px else p["cash"]
    return v


def _equity(d):
    return equity_cash + _mtm(d)


def _held(c):
    return any(p["code"] == c for p in core) or any(p["code"] == c for p in sat)


def _no_div_gap(c, di):
    """当前交易日往前, 距最近一次分红的交易日数; 无记录返回极大值。
    K3审查修（2026-09-13）：必须用完整日历 cal 定位分红日——用窗口日历 dates 时，
    若最近分红早于 START，bisect 得 -1 → 误判"500日无分红"→ 买入次日即强清
    （考试窗 2026-03 起实测连环误杀：思维列控/东方雨虹 买入次日被清）。"""
    dts = div_dts.get(c) or []
    if not dts:
        return 10 ** 9
    p = bisect.bisect_right(dts, dates[di]) - 1
    if p < 0:
        return 10 ** 9
    ld_i = bisect.bisect_right(cal, dts[p]) - 1   # 完整日历定位
    di_full = bisect.bisect_right(cal, dates[di]) - 1
    if ld_i < 0:
        return 10 ** 9
    return di_full - ld_i


for di, d in enumerate(dates):
    nd = dates[di + 1] if di + 1 < len(dates) else None

    # ---------- 1. 开盘执行（先卖后买） ----------
    # 1a) 卖出（exit_day=首个可成交日：停牌顺延——K3审查修复：原版停牌后 exit_day 留在过去日，永远不再触发）
    for lst in (core, sat):
        for p in list(lst):
            ed = p.get("exit_day")
            if ed is None or ed > d:
                continue
            px = _open(p["code"], d)
            if px is None:
                continue                      # 停牌 → 留到下个交易日再试（exit_day 保持 ≤ 当日即可顺延）
            ret = px / p["entry"] - 1 - 2 * FEE
            equity_cash += p["cash"] * (1 + ret)
            trades.append({
                "code": p["code"],
                "name": names.get(p["code"], p["code"]),
                "layer": p["layer"],
                "in": p["entry_date"],
                "out": d,
                "ret": ret,
                "reason": p.get("exit_reason", ""),
            })
            lst.remove(p)

    # 1b) 买入
    if pending_buy and pending_buy["day"] == d:
        b = pending_buy
        pending_buy = None
        px = _open(b["code"], d)
        if px is not None:
            cash = min(b["cash"], equity_cash)
            if cash > 1.0:
                equity_cash -= cash
                tgt = core if b["layer"] == "核心" else sat
                tgt.append({
                    "code": b["code"],
                    "layer": b["layer"],
                    "entry": px,
                    "cash": cash,
                    "entry_date": d,
                    "exit_day": None,
                    "exit_reason": None,
                })

    # ---------- 硬断言：仓位上限 ----------
    assert len(core) <= CORE_MAX, f"核心仓超限 {len(core)} @{d}"
    assert len(sat) <= SAT_MAX, f"卫星仓超限 {len(sat)} @{d}"
    assert len(core) + len(sat) <= CORE_MAX + SAT_MAX, f"总仓位超限 @{d}"
    codes_now = [p["code"] for p in core + sat]
    assert len(codes_now) == len(set(codes_now)), f"同票占两层 @{d}"

    # ---------- 2. 收盘记账 ----------
    ev = _equity(d)
    assert ev >= 0, f"权益为负 @{d}"
    curve.append((d, ev))

    if nd is None:
        continue

    # ---------- 3. 收盘出信号（T+1 开盘执行） ----------
    # 3a) 卖出信号
    for lst, line, tag in ((core, CORE_SELL_Y, "3.0%"), (sat, SAT_SELL_Y, "3.5%")):
        for p in lst:
            if p.get("exit_day") is not None:
                continue
            c = p["code"]
            if _no_div_gap(c, di) > NODIV_DAYS:
                p["exit_day"] = nd
                p["exit_reason"] = "连续500交易日无分红"
                continue
            y = _yld(c, d)
            if y is not None and y < line:
                p["exit_day"] = nd
                p["exit_reason"] = f"息率跌破{tag}"

    # 3b) 卫星 → 核心 转移（核心有空位且卫星票息率仍 ≥ 4.5%）
    for p in list(sat):
        if len(core) >= CORE_MAX:
            break
        if p.get("exit_day") is not None:
            continue
        y = _yld(p["code"], d)
        if y is not None and y >= BUY_Y:
            sat.remove(p)
            p["layer"] = "核心"
            core.append(p)
            transfers += 1

    # 3c) 买入信号（当日息率最高且未持仓者）
    if pending_buy is None and (len(core) < CORE_MAX or len(sat) < SAT_MAX):
        best = None
        for c in universe:
            if _held(c):
                continue
            j = _j(c, d)
            if j is None or j < 1:
                continue
            kk = stocks[c][j]
            close = kk.get("close", 0) or 0
            if close <= 2:
                continue
            y = ttm[c][j] / close
            if y >= BUY_Y and (best is None or y > best[0]):
                best = (y, c)
        if best is not None and _open(best[1], nd) is not None:
            layer = "核心" if len(core) < CORE_MAX else "卫星"
            cash = min(equity_cash, _equity(d) * POS_FRAC)
            if cash > 1.0:
                pending_buy = {"code": best[1], "layer": layer, "day": nd, "cash": cash}

# ============================== T+1 硬断言 ==============================
for t in trades:
    assert t["out"] > t["in"], f"T+1 违约: {t}"

# ============================== 统计 ==============================
final = curve[-1][1]
peak, mdd = CAPITAL, 0.0
for _, v in curve:
    peak = max(peak, v)
    mdd = min(mdd, v / peak - 1)

by_year = defaultdict(float)
for d, v in curve:
    by_year[d[:4]] = v
years = {}
prev = CAPITAL
for y in sorted(by_year):
    years[y] = round((by_year[y] / prev - 1) * 100, 1)
    prev = by_year[y]

wins = [t for t in trades if t["ret"] > 0]
win_pct = round(len(wins) / len(trades) * 100, 1) if trades else 0.0
core_sells = sum(1 for t in trades if t["layer"] == "核心")
sat_sells = sum(1 for t in trades if t["layer"] == "卫星")

out = {
    "window": [dates[0], dates[-1]],
    "equity": round(final),
    "return%": round((final / CAPITAL - 1) * 100, 1),
    "maxDD%": round(mdd * 100, 1),
    "trades": len(trades),
    "win%": win_pct,
    "by_year": years,
    "universe": len(universe),
    "核心仓卖出笔数": core_sells,
    "卫星仓卖出笔数": sat_sells,
    "转移次数": transfers,
}

json.dump(out, open(f"{D}/dividend_core_satellite_{OUTSUF}.json", "w"),
          ensure_ascii=False, indent=1)
json.dump([[d, round(v, 2)] for d, v in curve],
          open(f"{D}/dividend_curve_cs_{OUTSUF}.json", "w"))

with open(f"{D}/红利分层_8年交易明细.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["代码", "名称", "层", "买入日", "卖出日", "收益%", "卖出原因"])
    for t in trades:
        w.writerow([t["code"], t["name"], t["layer"], t["in"], t["out"],
                    round(t["ret"] * 100, 2), t["reason"]])

# ============================== 对照输出 ==============================
print(json.dumps(out, ensure_ascii=False, indent=1))


def seg_ret(curve_, lo, hi="9999-99-99"):
    base = None
    last = None
    for d, v in curve_:
        if d < lo:
            base = v
        elif d <= hi:
            if base is None:
                base = v
            last = v
    if base is None or last is None or base <= 0:
        return None
    return (last / base - 1) * 100


orig_curve = None
try:
    raw = json.load(open(f"{D}/dividend_curve_20260912.json"))
    orig_curve = [(r[0], r[1]) for r in raw]
except Exception:
    orig_curve = None

cs24 = seg_ret(curve, "2024-01-01")
or24 = seg_ret(orig_curve, "2024-01-01") if orig_curve else None

print()
print("=" * 68)
print("红利「核心/卫星」分层 vs 原版 dividend_sim vs 五大行躺平")
print("-" * 68)
print(f"{'':22s}{'总收益':>12s}{'最大回撤':>12s}{'交易笔数':>10s}{'胜率':>10s}")
print(f"{'分层版(核心3+卫星2)':22s}"
      f"{out['return%']:>11.1f}%{out['maxDD%']:>11.1f}%{out['trades']:>10d}{out['win%']:>9.1f}%")
print(f"{'原版 dividend_sim':22s}{103.9:>11.1f}%{-24.0:>11.1f}%{30:>10d}{56.7:>9.1f}%")
print(f"{'五大行躺平':22s}{116.7:>11.1f}%{'n/a':>12s}{'n/a':>10s}{'n/a':>10s}")
print("-" * 68)
print("2024-2026 主升段收益对比：")
print(f"  分层版 : {cs24:+.1f}%" if cs24 is not None else "  分层版 : n/a")
if or24 is not None:
    print(f"  原版   : {or24:+.1f}%   (读自 dividend_curve_20260912.json)")
else:
    print("  原版   : n/a      (未找到 dividend_curve_20260912.json)")
print("-" * 68)

if cs24 is not None and or24 is not None:
    if cs24 > or24:
        print(f"结论：分层【解决】了主升段洗出问题 —— 2024-2026 段分层版 {cs24:+.1f}% "
              f"跑赢原版 {cs24 - or24:+.1f}pct；")
        print(f"      核心仓仅以 3.0% 为卖点（本段共 {core_sells} 笔核心卖出），"
              f"不再被 3.5% 波段线在银行主升途中扫出。")
    else:
        print(f"结论：分层【未解决】主升段洗出问题 —— 2024-2026 段分层版 {cs24:+.1f}% "
              f"落后原版 {cs24 - or24:+.1f}pct，需检查核心仓建仓时点与 3.0% 卖点触发。")
elif cs24 is not None:
    print(f"结论：分层版 2024-2026 段 {cs24:+.1f}%；原版曲线缺失，无法同段对比。"
          f"本段核心仓卖出 {core_sells} 笔 / 卫星仓卖出 {sat_sells} 笔 / 转移 {transfers} 次。")
else:
    print("结论：窗口内无 2024-2026 段数据，无法判定。")
print("=" * 68)
