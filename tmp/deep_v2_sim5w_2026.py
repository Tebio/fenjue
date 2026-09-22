"""2026 深档 v2 回放表格 + 5万槽位模拟（2026-09-22 深夜）。

生产口径：成簇日（深档件≥5）出手票=深跌件(≤-35%)深度最深前5，次日开盘买（一字跌停作废），
T+5 收盘卖，费 0.15%，5万本金、最多 5 槽、每槽=当时权益/5、同股重复信号不加仓。
输出：①按信号日分组的完整表格 ②资金曲线（期末/回撤/逐笔）。
"""
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
CAP0 = 50_000.0
SLOTS = 5

stocks = lp.load_universe()
names = {str(s["code"]).zfill(6): s.get("name", "")
         for s in json.loads(open(f"{ROOT}/data/main_board_codes.json").read())["stocks"]}
print("universe", len(stocks), flush=True)

# 成簇日（2026）
cluster = {}
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    nm = names.get(code, "")
    if "ST" in nm or "退" in nm:
        continue
    n = d["n"]
    for i in range(60, n):
        if d["c"][i - 1] <= 0 or d["date"][i] < "2026-01-01":
            continue
        ma = d["ma60"][i]
        if not ma:
            continue
        if d["c"][i] / d["c"][i - 1] - 1 <= -0.095 and d["c"][i] <= ma * 0.75:
            cluster[d["date"][i]] = cluster.get(d["date"][i], 0) + 1

# 逐成簇日生成出手名单
days = sorted(d for d, k in cluster.items() if k >= 5)
signals = []  # (sig_date, entry_date, code, name, depth, entry_px, exit_idx)
for dt in days:
    picks = []
    for code, d in stocks.items():
        if code[:2] not in ("60", "00"):
            continue
        nm = names.get(code, "")
        if "ST" in nm or "退" in nm:
            continue
        i = d["date"].index(dt) if dt in d["date"] else None
        if i is None or i < 60 or i + 6 >= d["n"]:
            continue
        ma = d["ma60"][i]
        if not ma or d["c"][i - 1] <= 0:
            continue
        pct = d["c"][i] / d["c"][i - 1] - 1
        depth = d["c"][i] / ma - 1
        if pct <= -0.095 and depth <= -0.35:
            picks.append((depth, code, nm, pct, i))
    picks.sort()
    for depth, code, nm, pct, i in picks[:5]:
        d = stocks[code]
        # 一字跌停开盘作废（开≈跌停且振幅≈0）
        if d["o"][i + 1] <= d["c"][i] * 1.001 and d["h"][i + 1] <= d["o"][i + 1] * 1.005:
            continue
        signals.append({"sig": dt, "entry_d": d["date"][i + 1], "code": code, "name": nm,
                        "depth": depth, "pct": pct, "i": i,
                        "entry": d["o"][i + 1], "exit_i": i + 6})  # T+5 收盘（入场日+5）

# 打印完整表格
print(f"\n{'信号日':<11}{'名称':<7}{'代码':<8}{'当日':>7}{'深度':>6}  {'T+1':>7}{'T+3':>7}{'T+5':>7}{'T+10':>7}")
for s in signals:
    d = stocks[s["code"]]
    i = s["i"]
    e = s["entry"]
    fmt = lambda x: f"{x * 100:+6.1f}%" if x is not None else "   —  "
    r = {h: (d["c"][i + h] / e - 1 - FEE) if i + h < d["n"] else None for h in (1, 3, 5, 10)}
    print(f"{s['sig']:<11}{s['name']:<7}{s['code']:<8}{s['pct'] * 100:+6.1f}%{s['depth'] * 100:+5.0f}%  {fmt(r[1])}{fmt(r[3])}{fmt(r[5])}{fmt(r[10])}")

# ── 5 万槽位模拟 ──
events = sorted(signals, key=lambda s: s["entry_d"])
cash = CAP0
pos = []   # {code, entry_i, exit_i, val, name, entry_d}
trades = []
equity_curve = []
for s in events:
    d = stocks[s["code"]]
    # 先结算到期的
    for p in pos[:]:
        dd = stocks[p["code"]]
        j = dd["date"].index(s["entry_d"]) if s["entry_d"] in dd["date"] else None
        exit_now = j is not None and j >= p["exit_i"]
        if exit_now:
            px = dd["c"][p["exit_i"]]
            ret = px / p["entry"] - 1 - FEE
            cash += p["val"] * (1 + ret)
            trades.append({**p, "ret": ret, "exit_d": dd["date"][p["exit_i"]]})
            pos.remove(p)
    # 同股已在持 → 跳过
    if any(p["code"] == s["code"] for p in pos):
        continue
    if len(pos) >= SLOTS:
        continue
    val = min(CAP0 / SLOTS, cash)
    if val < 100:
        continue
    cash -= val
    pos.append({"code": s["code"], "name": s["name"], "entry": s["entry"], "val": val,
                "exit_i": s["exit_i"], "entry_d": s["entry_d"], "sig": s["sig"]})
    equity_curve.append((s["entry_d"], cash + sum(p["val"] for p in pos)))
# 收尾：全部按最后可得价格结算
for p in pos:
    dd = stocks[p["code"]]
    j = min(p["exit_i"], dd["n"] - 1)
    ret = dd["c"][j] / p["entry"] - 1 - FEE
    cash += p["val"] * (1 + ret)
    trades.append({**p, "ret": ret, "exit_d": dd["date"][j]})

final = cash
wins = [t for t in trades if t["ret"] > 0]
peak, mdd = CAP0, 0.0
for _, eq in equity_curve:
    peak = max(peak, eq)
    mdd = min(mdd, eq / peak - 1)
print(f"\n═══ 5万槽位模拟（生产口径）═══")
print(f"笔数 {len(trades)} | 胜率 {len(wins)}/{len(trades)} = {len(wins) / len(trades) * 100:.0f}% | 均笔 {st.mean(t['ret'] for t in trades) * 100:+.2f}%")
print(f"期末 {final:,.0f} 元（{(final / CAP0 - 1) * 100:+.1f}%）| 曲线回撤 {mdd * 100:.1f}%")
print("\n逐笔：")
for t in sorted(trades, key=lambda x: x["entry_d"]):
    print(f"  {t['entry_d']} 买 {t['name']}({t['code']}) → {t['exit_d']} 卖 {t['ret'] * 100:+.1f}%")
json.dump({"trades": [{k: v for k, v in t.items()} for t in trades], "final": final},
          open(f"{ROOT}/data/deep_v2_sim5w_2026_20260922.json", "w"), ensure_ascii=False, indent=1)
print("\nsaved data/deep_v2_sim5w_2026_20260922.json")
