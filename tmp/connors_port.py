"""Connors RSI(2) A股移植验证（2026-09-25，用户要求：用现成论文思路给最优解并全部干完）。

正典规则（Connors 2008《Short Term Trading Strategies That Work》）：
  入=收盘：价>MA200（A股用MA250≈年线）且 RSI(2)<10
  出=收盘>MA5（反弹兑现）；时间止损=10 个交易日
  无固定止损（正典结论：固定止损降低盈利）
变体网格：RSI 阈 5/10/15 × 趋势门 MA60/MA250 × regime 全/主线期 × 时段 全史/2026。
对照：咱们的主线期回踩-3%（固定 T+1 出）。
口径：收盘信号→次日开盘入（生产口径，正典的收盘入过于乐观），费 0.15%，含退市股。
另测市值分层（正典警告：小票上 edge 消失）+ Lee-Swaminathan 换手交互。
"""
import collections
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
stocks = lp.load_universe()
regime = lp.load_regime()


def rsi2(c, i):
    if i < 2:
        return None
    g1, l1 = max(c[i] - c[i - 1], 0), max(c[i - 1] - c[i], 0)
    g2, l2 = max(c[i - 1] - c[i - 2], 0), max(c[i - 2] - c[i - 1], 0)
    ag, al = (g1 + g2) / 2, (l1 + l2) / 2
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


results = collections.defaultdict(list)
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(255, n - 11):
        if d["c"][i - 1] <= 0 or d["o"][i + 1] <= 0:
            continue
        r2 = rsi2(d["c"], i)
        if r2 is None or r2 >= 15:
            continue
        ma250 = st.mean(d["c"][i - 249:i + 1])
        ma60 = d["ma60"][i]
        ma5 = st.mean(d["c"][i - 4:i + 1])
        dt = d["date"][i]
        rg = regime.get(dt, "?")
        entry = d["o"][i + 1]
        # 正典出场：收盘>MA5 或第 10 日强制
        exit_px, exit_i = None, None
        for j in range(i + 1, min(i + 11, n)):
            ma5j = st.mean(d["c"][j - 4:j + 1])
            if d["c"][j] > ma5j or j == min(i + 10, n - 1):
                exit_px, exit_i = d["c"][j], j
                break
        if exit_px is None:
            continue
        ret = exit_px / entry - 1 - FEE
        hold = exit_i - i
        ev = {"ret": ret, "hold": hold, "win": ret > 0, "date": dt, "rg": rg,
              "r2": r2, "ma250_ok": d["c"][i] > ma250, "ma60_ok": ma60 and d["c"][i] > ma60,
              "t1": d["c"][i + 1] / entry - 1 - FEE}
        for rth in (5, 10, 15):
            if r2 < rth:
                for gate, gname in ((ev["ma250_ok"], "MA250"), (ev["ma60_ok"], "MA60")):
                    if gate:
                        results[f"RSI<{rth}+{gname}"].append(ev)
                        if rg == "主线期":
                            results[f"RSI<{rth}+{gname}+主线期"].append(ev)
                        if dt >= "2026-01-01":
                            results[f"RSI<{rth}+{gname}+2026"].append(ev)
                        if rg == "主线期" and dt >= "2026-01-01":
                            results[f"RSI<{rth}+{gname}+主线期+2026"].append(ev)


def rep(lb, rows):
    if len(rows) < 30:
        return
    wr = sum(1 for r in rows if r["win"]) / len(rows)
    m = st.mean(r["ret"] for r in rows)
    hold = st.mean(r["hold"] for r in rows)
    t1w = sum(1 for r in rows if r["t1"] > 0) / len(rows)
    t1m = st.mean(r["t1"] for r in rows)
    print(f"  {lb:<28} n={len(rows):>6} 正典出 {wr * 100:5.1f}%/{m * 100:+5.2f}%(持{hold:.1f}日) | 固定T+1 {t1w * 100:5.1f}%/{t1m * 100:+5.2f}%")


print("═══ Connors 正典出场（收>MA5，10日时间止损）vs 固定 T+1 ═══")
for k in sorted(results):
    if "2026" in k and "主线期" not in k:
        continue
    rep(k, results[k])
