#!/usr/bin/env python3
"""engine/sim_tournament.py — 七玩法模拟盘锦标赛（2026-09-12，用户立项）

每个玩法 10 万起，同一窗口（m60 覆盖期 2024-08-26 起 ≈2 年），净口径 -0.15%/笔：
1. dividend_hold   股息躺平：窗口首日等权买 5 只高股息，拿死到底
2. dividend_t      股息做T：同篮子 + m60 bar 路径机械做T（-1.5%买/+1.5%卖，同bar双触不成交）
3. long_trend      长线趋势：MA20 金叉 MA60 且 MA60 上行 → 次日开盘买；收盘破 MA60 → 次日开盘卖
4. short_t1        短线打板：FRONTRUN_V2 + m60 尾盘开缝才算成交 → T+1 尾盘卖
5. swing_t5        波段：同信号 → T+5 尾盘卖（槽位占 5 天）
6. scalp_overnight 短差：同信号 → T+1 开盘卖（吃隔夜缺口）
7. reversal        反转族：昨跌≥3% → 次日开盘买 → T+1 尾盘卖（一字跌停剔）
诚实边界：前复权价格口径（分红近似再投资）；fill=尾盘开缝保守口径；历史重放≠未来。
"""
import json, sys, datetime
from collections import defaultdict

ROOT = "/opt/data/fenjue"
D = ROOT + "/data"
START = "2024-08-26"
FEE = 0.0015
CAPITAL = 100000.0

sys.path.insert(0, ROOT + "/engine")
import claims_shadow as cs


def m60_fillable(code, d, close):
    try:
        bars = [r for r in json.load(open(f"{D}/m60_cache/{code}.json")) if r["day"].startswith(d)]
    except Exception:
        return False
    return bool(bars) and float(bars[-1]["low"]) < close * 0.995


def ma(ks, n, i):
    if i + 1 < n:
        return None
    return sum(ks[j]["close"] for j in range(i - n + 1, i + 1)) / n


class Book:
    """等槽位复利账本"""
    def __init__(self, slots):
        self.eq = CAPITAL
        self.slots = slots
        self.open = []   # (exit_date, exit_fn_placeholder) — 简化为 (退出日index, code, entry_eq份额, claim)
        self.trades = []
        self.curve = []

    def size(self):
        return self.eq / self.slots


def main():
    stocks = cs.load_stocks()
    ind = cs.industry_map()
    cal = [k["date"] for k in stocks["000001"]]
    dates = [d for d in cal if d >= START]
    idx = {c: {k["date"]: j for j, k in enumerate(ks)} for c, ks in stocks.items()}
    dpos = {d: n for n, d in enumerate(dates)}

    # ── 梯子（frontrun 用）──
    ladder_by_date = {}
    for d in dates:
        lad = defaultdict(int)
        for c, ks in stocks.items():
            j = idx[c].get(d)
            if j and j >= 1 and ks[j - 1]["close"] > 0 and ks[j]["close"] / ks[j - 1]["close"] - 1 >= 0.098:
                lad[ind.get(c, {}).get("industry") or "?"] += 1
        ladder_by_date[d] = lad

    # ── 1/2. 股息组篮子：息率宇宙取前5（近似：分红缓存 TTM 息率）──
    div_cache = json.load(open(f"{D}/dividend_cache.json"))
    basket = []
    for code, rec in div_cache.items():
        ks = stocks.get(code)
        if not ks:
            continue
        j = idx[code].get(dates[0])
        if j is None:
            continue
        dps = rec.get("dps")
        if dps and ks[j]["close"] > 0:
            basket.append((dps / ks[j]["close"], code))  # 息率近似=每股分红/窗口首日收盘（前复权口径）
    basket = [c for _, c in sorted(basket, reverse=True)[:5]]
    if not basket:  # 兜底：锚定两只
        basket = ["601398", "601088"]
    print("股息篮子:", basket, file=sys.stderr)

    books = {k: Book(s) for k, s in {
        "dividend_hold": 5, "dividend_t": 5, "long_trend": 5,
        "short_t1": 3, "swing_t5": 3, "scalp_overnight": 3, "reversal": 3}.items()}

    # 股息组：窗口首日开盘买入拿死（做T组另加T收益流）
    t_pnl = defaultdict(float)  # dividend_t 每日 T 净收益（占权益比例累加到日收益）
    for c in basket:
        j = idx[c].get(dates[0])
        if j is None:
            continue
        entry = stocks[c][j]["open"]
        if entry <= 0:
            continue
        for name in ("dividend_hold", "dividend_t"):
            bk = books[name]
            cash = bk.eq / 5
            bk.eq -= cash
            bk.open.append({"code": c, "entry": entry, "cash": cash, "entry_date": dates[0]})

    # 做T 预计算：每日 bar 路径（-1.5%/+1.5%，同bar双触不成交，买进卖不出尾盘了结）
    for c in basket:
        try:
            rows = json.load(open(f"{D}/m60_cache/{c}.json"))
        except Exception:
            continue
        byday = defaultdict(list)
        for r in rows:
            byday[r["day"][:10]].append(r)
        for d in dates:
            j = idx[c].get(d)
            if not j or j < 1 or d not in byday:
                continue
            pc = stocks[c][j - 1]["close"]
            buy_px, sell_px = pc * 0.985, pc * 1.015
            hit_b = any(float(r["low"]) <= buy_px for r in byday[d])
            hit_s = any(float(r["high"]) >= sell_px for r in byday[d])
            if hit_b and hit_s:  # 同bar双触顺序不明→保守不成交
                continue
            if hit_b:
                close = stocks[c][j]["close"]
                # 低吸腿：-1.5% 买进，当日尾盘了结（费 0.1%）
                t_pnl[d] += (close / buy_px - 1) - 0.001
    # 注：做T组=底仓拿死 + 低吸T腿收益（正T先买后卖）；卖出腿（先卖后买反T）口径边界不测。

    # ── 主循环 ──
    for di, d in enumerate(dates):
        # 3. 长线趋势：先处理后卖/买（开盘执行）
        bk = books["long_trend"]
        for pos in list(bk.open):
            ks = stocks[pos["code"]]
            j = idx[pos["code"]].get(d)
            if j is None or j < 61:
                continue
            m60v = ma(ks, 60, j)
            if m60v and ks[j - 1]["close"] < ma(ks, 60, j - 1) and ks[j]["open"] > 0:
                # 昨收破MA60 → 今开卖（连本带利回笼）
                ret = ks[j]["open"] / pos["entry"] - 1 - FEE
                bk.eq += pos["cash"] * (1 + ret)
                bk.trades.append((pos["entry_date"], d, pos["code"], ret))
                bk.open.remove(pos)
        if len(bk.open) < 5:
            best = None
            for c, ks in stocks.items():
                j = idx[c].get(d)
                if j is None or j < 62 or any(p["code"] == c for p in bk.open):
                    continue
                m20p, m60p = ma(ks, 20, j - 1), ma(ks, 60, j - 1)
                m20c, m60c = ma(ks, 20, j), ma(ks, 60, j)
                m60_5 = ma(ks, 60, j - 5)
                if not all([m20p, m60p, m20c, m60c, m60_5]):
                    continue
                golden = m20p <= m60p and m20c > m60c and m60c > m60_5
                if golden and ks[j]["close"] > ks[j - 1]["close"]:
                    # 次日开盘买 → 需要下一交易日
                    if di + 1 < len(dates):
                        nj = idx[c].get(dates[di + 1])
                        if nj and ks[nj]["open"] > 0:
                            vr = ks[j]["volume"] / max(1, sum(ks[k]["volume"] for k in range(j - 5, j)) / 5)
                            if best is None or vr > best[0]:
                                best = (vr, c, dates[di + 1], ks[nj]["open"])
            if best:
                cash = bk.eq / 5
                bk.eq -= cash
                bk.open.append({"code": best[1], "entry": best[3], "cash": cash, "entry_date": best[2]})

        # 4-6. 打板系信号（frontrun V2 + fill）
        lad = ladder_by_date[d]
        sigs = []
        for c, ks in stocks.items():
            j = idx[c].get(d)
            if j is None or j < 65 or j + 1 >= len(ks) or ks[j - 1]["close"] <= 0:
                continue
            chg = ks[j]["close"] / ks[j - 1]["close"] - 1
            if chg >= 0.098:  # 仅涨停日才进 frontrun 检测（剪枝）
                hits = cs.detect(c, ks, j, lad)
                if any(h[0] == "FRONTRUN_FIRSTBOARD_V2" for h in hits):
                    if m60_fillable(c, d, ks[j]["close"]):
                        sigs.append((c, j))
        sigs = sigs[:3]

        for name, exit_mode in (("short_t1", "t1_close"), ("swing_t5", "t5_close"), ("scalp_overnight", "t1_open")):
            bk = books[name]
            # 到期平仓（尾盘/开盘按模式）
            for pos in list(bk.open):
                ks = stocks[pos["code"]]
                hold_days = di - pos["entry_di"]
                due = (exit_mode == "t1_close" and hold_days >= 1) or \
                      (exit_mode == "t1_open" and hold_days >= 1) or \
                      (exit_mode == "t5_close" and hold_days >= 5)
                if not due:
                    continue
                j = idx[pos["code"]].get(d)
                if j is None or ks[j]["close"] <= 0:
                    continue
                px = ks[j]["open"] if (exit_mode == "t1_open") else ks[j]["close"]
                if px <= 0:
                    continue
                ret = px / pos["entry"] - 1 - FEE
                bk.eq += pos["cash"] * (1 + ret)
                bk.trades.append((pos["entry_date"], d, pos["code"], ret))
                bk.open.remove(pos)
            # 开仓
            for c, j in sigs:
                if len(bk.open) >= 3:
                    break
                entry = stocks[c][j]["close"]
                cash = bk.eq / 3
                bk.eq -= cash
                bk.open.append({"code": c, "entry": entry, "cash": cash, "entry_date": d, "entry_di": di})

        # 7. 反转族（入场日尾盘卖=当日开→收，与 +0.139% 实测口径一致）
        bk = books["reversal"]
        for pos in list(bk.open):
            ks = stocks[pos["code"]]
            if di >= pos["entry_di"]:
                j = idx[pos["code"]].get(d)
                if j and ks[j]["close"] > 0:
                    ret = ks[j]["close"] / pos["entry"] - 1 - FEE
                    bk.eq += pos["cash"] * (1 + ret)
                    bk.trades.append((pos["entry_date"], d, pos["code"], ret))
                    bk.open.remove(pos)
        if di + 1 < len(dates):
            rev_sigs = []
            for c, ks in stocks.items():
                j = idx[c].get(d)
                if j is None or j < 1 or ks[j - 1]["close"] <= 0:
                    continue
                if ks[j]["close"] / ks[j - 1]["close"] - 1 <= -0.03:
                    nj = idx[c].get(dates[di + 1])
                    if nj is None:
                        continue
                    e = ks[nj]
                    if e["open"] <= 0:
                        continue
                    if (e["open"] / ks[j]["close"] - 1) <= -0.095 and (e["high"] - e["low"]) / e["close"] < 0.01:
                        continue  # 一字跌停买不进
                    rev_sigs.append((c, e["open"], abs(ks[j]["close"] / ks[j - 1]["close"] - 1)))
            rev_sigs.sort(key=lambda s: -s[2])
            for c, opx, _ in rev_sigs[:3 - len(bk.open)]:
                cash = bk.eq / 3
                bk.eq -= cash
                bk.open.append({"code": c, "entry": opx, "cash": cash, "entry_date": d, "entry_di": di + 1})

        # 日记账（权益=现金+持仓市值）
        for name, bk in books.items():
            mv = 0.0
            for pos in bk.open:
                ks = stocks[pos["code"]]
                j = idx[pos["code"]].get(d)
                if j:
                    mv += pos["cash"] * ks[j]["close"] / pos["entry"]
                else:
                    mv += pos["cash"]
            t_bonus = t_pnl.get(d, 0) / 5 if name == "dividend_t" else 0
            bk.curve.append((d, (bk.eq + mv) * (1 + t_bonus)))

    # ── 汇总 ──
    ks0 = stocks["000001"]
    bench = ks0[idx["000001"][dates[-1]]]["close"] / ks0[idx["000001"][dates[0]]]["close"] - 1
    out = {"window": [dates[0], dates[-1]], "days": len(dates), "capital": CAPITAL,
           "bench%": round(bench * 100, 1), "basket": basket, "strategies": {}}
    for name, bk in books.items():
        final = bk.curve[-1][1] if bk.curve else CAPITAL
        peak, mdd = CAPITAL, 0.0
        for _, v in bk.curve:
            peak = max(peak, v); mdd = min(mdd, v / peak - 1)
        wins = [t for t in bk.trades if t[3] > 0]
        out["strategies"][name] = {
            "final": round(final), "return%": round((final / CAPITAL - 1) * 100, 1),
            "maxDD%": round(mdd * 100, 1), "trades": len(bk.trades),
            "win%": round(len(wins) / len(bk.trades) * 100, 1) if bk.trades else 0,
            "avg%": round(sum(t[3] for t in bk.trades) / len(bk.trades) * 100, 2) if bk.trades else 0,
        }
    json.dump(out, open(f"{D}/sim_tournament_20260912.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
