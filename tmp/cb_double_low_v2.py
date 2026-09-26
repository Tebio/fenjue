"""双低轮动正统重测（2026-09-26 晚，BACKLOG#25——v1 实现存疑（-23.9%/年均匀负=疑似 bug），重写）。

修正点：①周界=ISO 周最后一个交易日（v1 的周界计算是错的）②每周组合收益=持仓从本周末到下周末的
等权均值（v1 的 prev/prev_d0 引用混乱）③双低值=价格+溢价率×100；溢价率用初始转股价（下修未调
=高估溢价=偏向排除被下修债，误差方向已注记）④对照=沪深300。
变体：A 纯低价前10（价格最低，绕开转股价问题）B 双低前10 C 双低前10+剔除强赎公告债。
"""
import collections
import datetime
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
meta = {r["SECURITY_CODE"]: r for r in cb_list}
cb_idx = {c: {r["date"]: k for k, r in enumerate(rows)} for c, rows in cb_k.items()}

idx_data = json.load(open(f"{ROOT}/data/index_sh000001.json"))
idx_map = {k["date"]: float(k["close"]) for k in idx_data}

# ISO 周末（每周最后一个交易日）
cal = sorted({r["date"] for rows in cb_k.values() for r in rows})
week_last = {}
for d in cal:
    iso = datetime.date.fromisoformat(d).isocalendar()[:2]
    week_last[iso] = d
weeks = sorted(week_last.values())
weeks = [w for w in weeks if "2023-01-01" <= w <= "2026-09-24"]
print(f"周数 {len(weeks)}", flush=True)


def premium(code, dt):
    m = meta.get(code)
    if not m or not m.get("INITIAL_TRANSFER_PRICE"):
        return None
    stock = stocks.get(str(m.get("CONVERT_STOCK_CODE", "")).zfill(6))
    if not stock or dt not in stock["date"]:
        return None
    si = stock["date"].index(dt)
    if stock["c"][si] <= 0:
        return None
    conv = 100 / m["INITIAL_TRANSFER_PRICE"] * stock["c"][si]
    rows = cb_k[code]
    k = cb_idx[code].get(dt)
    if k is None:
        return None
    return rows[k]["close"] / conv - 1


def picks_for(wk, mode):
    scored = []
    for code, rows in cb_k.items():
        k = cb_idx[code].get(wk)
        if k is None or rows[k]["close"] <= 0:
            continue
        px = rows[k]["close"]
        if px > 160:
            continue  # 高价债排除
        if mode == "A":
            scored.append((px, code))
        else:
            pm = premium(code, wk)
            if pm is None:
                continue
            if mode == "C":
                nd = str(meta.get(code, {}).get("NOTICE_DATE_HS") or "")[:10]
                if nd and nd <= wk:
                    continue  # 已发强赎公告的剔除
            scored.append((px + pm * 100, code))
    scored.sort()
    return [c for _, c in scored[:10]]


def run(mode):
    nav = 1.0
    curve = []
    for a, b in zip(weeks, weeks[1:]):
        picks = picks_for(a, mode)
        if not picks:
            continue
        rets = []
        for code in picks:
            rows = cb_k[code]
            k0, k1 = cb_idx[code].get(a), cb_idx[code].get(b)
            if k0 is None or k1 is None or k1 <= k0 or rows[k0]["close"] <= 0:
                continue
            rets.append(rows[k1]["close"] / rows[k0]["close"] - 1 - 2 * FEE)
        if rets:
            nav *= 1 + st.mean(rets)
        curve.append((b, nav))
    peak, mdd = 1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    by_year = collections.defaultdict(list)
    prev_nav = {y: 1.0 for y in ("2023", "2024", "2025", "2026")}
    yearly = {}
    base = 1.0
    yr_start = {}
    for d, v in curve:
        y = d[:4]
        if y not in yr_start:
            yr_start[y] = curve[[c[0] for c in curve].index(next(c[0] for c in curve if c[0][:4] == y))][1] if False else None
    # 简化分年：记录每年首个净值
    yr_first, yr_last = {}, {}
    for d, v in curve:
        yr_first.setdefault(d[:4], v)
        yr_last[d[:4]] = v
    yr_ret = {y: (yr_last[y] / (yr_first.get(str(int(y) - 1), yr_first[y]) if y != "2023" else 1.0) - 1) for y in yr_last}
    return nav, mdd, yr_ret, curve


print("═══ 双低正统重测（2023-01~2026-09，周五换仓，前10） ═══")
results = {}
for mode, lb in (("A", "纯低价前10"), ("B", "双低前10"), ("C", "双低+剔强赎")):
    nav, mdd, yr_ret, curve = run(mode)
    results[mode] = curve
    yrs = " ".join(f"{y}:{r:+.1%}" for y, r in sorted(yr_ret.items()))
    print(f"  {lb}: 净值 {nav:.3f}（{(nav - 1) * 100:+.1f}%）回撤 {mdd * 100:.1f}% | {yrs}")

# 沪深300 同期
i0 = idx_map.get(weeks[0])
i1 = idx_map.get(weeks[-1])
if i0 and i1:
    print(f"  沪深300同期: {i1 / i0 - 1:+.1%}")
json.dump({m: c for m, c in results.items()}, open(f"{ROOT}/data/cb_double_low_v2_20260926.json", "w"))
print("saved data/cb_double_low_v2_20260926.json")
