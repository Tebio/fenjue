"""转债三策略+整合测试（2026-09-25，用户：转债线搞完看能不能整合）。

①低价防守线：CB 收盘≤105 买入（次日开盘），T+20/60/120 收益+最大回撤（债底保护验证）
②双低轮动（近似）：双低值=价格+溢价率×100，溢价率=价格/(100/转股价×正股价)-1，
  每周五换仓持前 10，2023-01~2026-09 净值 vs 沪深300（下修未调整=偏差已注记）
③强赎事件：有强赎公告(NOTICE_DATE_HS)的 CB，公告后 T+1/5/20
④整合：恐慌日 CB 低价篮子 T+5 vs 正股深档同日表现（互补还是重叠）
"""
import collections
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
cb_list = json.load(open(f"{ROOT}/data/cb_list.json"))
cb_k = json.load(open(f"{ROOT}/data/cb_klines.json"))
stocks = lp.load_universe()
regime = lp.load_regime()

meta = {r["SECURITY_CODE"]: r for r in cb_list}
print(f"转债宇宙 {len(cb_k)}", flush=True)

# ① 低价防守线
low_events = []
for code, rows in cb_k.items():
    m = meta.get(code)
    if not m:
        continue
    for i in range(1, len(rows) - 121):
        if rows[i]["close"] <= 105 and rows[i]["close"] > 80 and rows[i + 1]["open"] > 0:
            entry = rows[i + 1]["open"]
            path = [r["close"] / entry - 1 for r in rows[i:i + 121]]
            low_events.append({"code": code, "date": rows[i]["date"], "px": rows[i]["close"],
                               "t20": rows[i + 20]["close"] / entry - 1 - FEE,
                               "t60": rows[i + 60]["close"] / entry - 1 - FEE,
                               "t120": rows[i + 120]["close"] / entry - 1 - FEE,
                               "mdd120": min(path)})
print(f"\n① 低价(≤105)事件 {len(low_events)}")
for h in ("t20", "t60", "t120"):
    xs = [e[h] for e in low_events]
    wr = sum(1 for x in xs if x > 0) / len(xs)
    print(f"   {h}: {wr * 100:.1f}%/{st.mean(xs) * 100:+.2f}% 中位最大回撤 {sorted(e['mdd120'] for e in low_events)[len(low_events)//2] * 100:.1f}%")
# 分年
for y in ("2023", "2024", "2025", "2026"):
    xs = [e["t120"] for e in low_events if e["date"][:4] == y]
    if len(xs) > 20:
        print(f"   {y}: n={len(xs)} {sum(1 for x in xs if x > 0)/len(xs) * 100:.0f}%/{st.mean(xs) * 100:+.2f}%")

# ② 双低轮动（周五换仓）
print("\n② 双低轮动（前10，周五换仓）")
dates_all = sorted({r["date"] for rows in cb_k.values() for r in rows if r["date"] >= "2023-01-01"})
fridays = [d for d in dates_all if d[8:] and (dates_all.index(d) == len(dates_all) - 1 or dates_all[dates_all.index(d) + 1][:7] != d[:7] or True)]
# 简化：每周最后一个交易日
week_ends = []
prev_wk = None
for d in dates_all:
    wk = d[:4] + d[5:7] + str((int(d[8:10]) - 1) // 7)
    if prev_wk and wk != prev_wk:
        week_ends.append(prev_d)
    prev_wk, prev_d = wk, d
week_ends.append(dates_all[-1])

def double_low(code, dt):
    m = meta.get(code)
    rows = cb_k[code]
    idx = {r["date"]: k for k, r in enumerate(rows)}
    k = idx.get(dt)
    if k is None or not m or not m.get("INITIAL_TRANSFER_PRICE"):
        return None
    stock = stocks.get(str(m.get("CONVERT_STOCK_CODE", "")).zfill(6))
    if not stock or dt not in stock["date"]:
        return None
    si = stock["date"].index(dt)
    conv_val = 100 / m["INITIAL_TRANSFER_PRICE"] * stock["c"][si]
    if conv_val <= 0:
        return None
    px = rows[k]["close"]
    premium = px / conv_val - 1
    return px + premium * 100

nav, nav_idx = 1.0, 1.0
idx_data = json.loads(open(f"{ROOT}/data/index_sh000001.json").read())
idx_map = {k["date"]: float(k["close"]) for k in idx_data}
navs, navs_idx = [], []
prev, prev_d0 = None, None
for wk in week_ends:
    scores = []
    for code in cb_k:
        dl = double_low(code, wk)
        if dl is not None:
            scores.append((dl, code))
    scores.sort()
    picks = [c for _, c in scores[:10]]
    if prev and picks:
        # 本周收益：上周 picks 从 prev→wk
        rets = []
        for code in prev:
            rows = cb_k[code]
            idx = {r["date"]: k for k, r in enumerate(rows)}
            k0, k1 = idx.get(prev_d0), idx.get(wk)
            if k0 is not None and k1 is not None and k1 > k0:
                rets.append(rows[k1]["close"] / rows[k0]["close"] - 1 - 2 * FEE)
        if rets:
            nav *= 1 + st.mean(rets)
        if prev_d0 in idx_map and wk in idx_map:
            nav_idx *= idx_map[wk] / idx_map[prev_d0]
    prev = picks
    prev_d0 = wk
    navs.append((wk, nav))
    navs_idx.append((wk, nav_idx))
peak, mdd = 1.0, 0.0
for _, v in navs:
    peak = max(peak, v)
    mdd = min(mdd, v / peak - 1)
peak_i, mdd_i = 1.0, 0.0
for _, v in navs_idx:
    peak_i = max(peak_i, v)
    mdd_i = min(mdd_i, v / peak_i - 1)
print(f"   双低轮动 净值 {nav:.3f}（{(nav - 1) * 100:+.1f}%）最大回撤 {mdd * 100:.1f}% | 沪深300 {navs_idx[-1][1]:.3f}（{(navs_idx[-1][1] - 1) * 100:+.1f}%）回撤 {mdd_i * 100:.1f}%")
# 分年净值
for y in ("2023", "2024", "2025", "2026"):
    seg = [v for d, v in navs if d[:4] == y]
    seg_i = [v for d, v in navs_idx if d[:4] == y]
    if seg:
        base = [v for d, v in navs if d[:4] < y or (d[:4] == y)][0]
        print(f"   {y}: 双低 {seg[-1] / base - 1:+.1%} vs 300 {seg_i[-1] / ([v for d, v in navs_idx if d[:4] <= y][0]) - 1:+.1%}" if seg_i else "")

# ③ 强赎事件
print("\n③ 强赎公告后表现")
redeem_events = []
for code, rows in cb_k.items():
    m = meta.get(code)
    nd = (m or {}).get("NOTICE_DATE_HS")
    if not nd:
        continue
    nd = str(nd)[:10]
    idx = {r["date"]: k for k, r in enumerate(rows)}
    k = idx.get(nd)
    if k is None or k + 21 >= len(rows) or rows[k + 1]["open"] <= 0:
        continue
    entry = rows[k + 1]["open"]
    redeem_events.append({"t1": rows[k + 1]["close"] / entry - 1 - FEE,
                          "t5": rows[k + 5]["close"] / entry - 1 - FEE,
                          "t20": rows[k + 20]["close"] / entry - 1 - FEE})
print(f"   事件 {len(redeem_events)}")
for h in ("t1", "t5", "t20"):
    xs = [e[h] for e in redeem_events]
    if xs:
        print(f"   {h}: {sum(1 for x in xs if x > 0)/len(xs) * 100:.0f}%/{st.mean(xs) * 100:+.2f}%")

# ④ 整合：恐慌日 CB 低价篮子 vs 深档
print("\n④ 恐慌日 CB 低价篮子 T+5（vs 深档同日）")
panic_days = sorted(d for d, r in regime.items() if r == "恐慌期")
cb_panic, deep_same = [], []
for dt in panic_days:
    for code, rows in cb_k.items():
        idx = {r["date"]: k for k, r in enumerate(rows)}
        k = idx.get(dt)
        if k is None or k + 6 >= len(rows) or rows[k]["close"] > 130 or rows[k + 1]["open"] <= 0:
            continue
        cb_panic.append(rows[k + 5]["close"] / rows[k + 1]["open"] - 1 - FEE)
if cb_panic:
    print(f"   恐慌日 CB 篮子(价<130) T+5: n={len(cb_panic)} {sum(1 for x in cb_panic if x > 0)/len(cb_panic) * 100:.0f}%/{st.mean(cb_panic) * 100:+.2f}%")
