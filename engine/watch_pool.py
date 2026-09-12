#!/usr/bin/env python3
"""engine/watch_pool.py — 放量异动观察池（G1，2026-09-12）

来源：#38 实测「异动放量未板」= 次日大涨 2.4x 基率（一鸣食品/银河电子启动前形态）。
用户案例：002519 银河电子 9/02 放量 4.6 倍试盘（收 +1.76%）→ 横盘 7 天 → 9/11 首板。
注意：原版 3~7% 收盘涨幅会漏掉这种「上影试盘」，参数变体须由回测决定（禁过拟合单票）。

模式：
  python3 engine/watch_pool.py            # 每日更新：扫描新候选+维护池状态 → data/watch_pool.json
  python3 engine/watch_pool.py --backtest # 8年全宇宙：参数变体×5日首板转化率×转化后期望（G6 量化）
信号：量比≥V（当日量/前5日均量）且收盘涨幅∈[LO,HI] 且未涨停
池维护：毕业=其后出现 ≥9.8% 首板；出局=收盘破入池日最低；超时=15 交易日未毕业
"""
import json, sys, statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data/big_kcache"
POOL_F = ROOT / "data/watch_pool.json"
EXPIRE = 15

# 参数变体（回测定输赢）：(量比, 涨幅下限%, 涨幅上限%)
VARIANTS = {"A_原版": (2.0, 3.0, 7.0), "B_试盘宽容": (3.0, 1.0, 7.5), "C_折中": (2.5, 2.0, 8.0)}
ACTIVE = "B_试盘宽容"  # 2026-09-12 回测选定：转化率 13.49%/倍数 2.16x 双优（data/watch_pool_backtest_20260912.json）


def load_stocks():
    return {fp.stem: json.loads(fp.read_text()) for fp in sorted(KC.glob("*.json"))}


def volratio(ks, i):
    base = [ks[j]["volume"] for j in range(max(0, i - 5), i)]
    return ks[i]["volume"] / (sum(base) / len(base)) if base and sum(base) > 0 else 0


def is_signal(ks, i, v):
    V, LO, HI = v
    if i < 6 or ks[i - 1]["close"] <= 0:
        return False
    # 防复牌/停牌缝隙污染（2026-09-12 自抓：前5根bar跨≤12自然日且量全>0，否则量比虚高）
    import datetime as _dt
    try:
        d0 = _dt.date.fromisoformat(ks[i - 5]["date"])
        d1 = _dt.date.fromisoformat(ks[i]["date"])
    except Exception:
        return False
    if (d1 - d0).days > 12 or any(ks[j]["volume"] <= 0 for j in range(i - 5, i)):
        return False
    pct = (ks[i]["close"] / ks[i - 1]["close"] - 1) * 100
    if not (LO <= pct <= HI):
        return False
    if volratio(ks, i) < V:
        return False
    return ks[i]["volume"] * ks[i]["close"] >= 2e8  # 近似成交额≥2亿


def backtest(stocks):
    """每变体：信号量、5日内首板转化率、转化日T+1期望、基率对照。"""
    out = {}
    base_conv, all_conv = [], []
    for vname, v in VARIANTS.items():
        conv, fail, t1 = 0, 0, []
        for code, ks in stocks.items():
            n = len(ks)
            for i in range(61, n - 6):
                if not is_signal(ks, i, v):
                    continue
                hit = None
                for k in range(i + 1, min(i + 6, n)):
                    if ks[k - 1]["close"] > 0 and (ks[k]["close"] / ks[k - 1]["close"] - 1) * 100 >= 9.8:
                        hit = k
                        break
                if hit and hit + 1 < n:
                    conv += 1
                    t1.append((ks[hit + 1]["close"] / ks[hit]["close"] - 1) * 100 - 0.15)
                else:
                    fail += 1
        # 基率：随机日5日内有板概率（抽样）
        import random
        rnd = random.Random(7)
        b_hit = b_tot = 0
        codes = [c for c in stocks if len(stocks[c]) >= 70]
        for _ in range(20000):
            ks = stocks[rnd.choice(codes)]
            i = rnd.randint(61, len(ks) - 7)
            b_tot += 1
            for k in range(i + 1, i + 6):
                if ks[k - 1]["close"] > 0 and (ks[k]["close"] / ks[k - 1]["close"] - 1) * 100 >= 9.8:
                    b_hit += 1
                    break
        out[vname] = {"信号n": conv + fail, "5日首板转化%": round(100 * conv / (conv + fail), 2) if conv + fail else 0,
                       "基率%": round(100 * b_hit / b_tot, 2),
                       "倍数": round((100 * conv / (conv + fail)) / (100 * b_hit / b_tot), 2) if conv + fail and b_hit else 0,
                       "转化后T+1": {"n": len(t1), "win%": round(100 * sum(x > 0 for x in t1) / len(t1), 1),
                                      "avg%": round(st.mean(t1), 2)} if t1 else None}
    return out


def daily_update(stocks):
    names = json.loads((ROOT / "data/industry_map.json").read_text())
    latest = max(ks[-1]["date"] for ks in stocks.values())
    pool = json.loads(POOL_F.read_text()) if POOL_F.exists() else {"pool": [], "graduated": [], "ejected": []}
    v = VARIANTS[ACTIVE]
    # 首次播种：扫最近 10 个交易日补建池（防首日空池）
    # 日历锚定 000001（退市股尾部在旧年份，union 会污染种子——2026-09-12 自抓）
    if not pool.get("seeded"):
        ref = stocks.get("000001") or next(iter(stocks.values()))
        dates = [k["date"] for k in ref[-12:]]
        seen = {e["code"] for e in pool["pool"]}
        for dt in dates[:-1]:
            for code, ks in stocks.items():
                if code in seen:
                    continue
                i = next((j for j, k in enumerate(ks) if k["date"] == dt), None)
                if i and is_signal(ks, i, v):
                    pool["pool"].append({"code": code, "name": names.get(code, {}).get("name", code),
                                         "entry_date": dt, "entry_close": ks[i]["close"],
                                         "entry_low": ks[i]["low"], "entry_vol": ks[i]["volume"],
                                         "volratio": round(volratio(ks, i), 1),
                                         "pct": round((ks[i]["close"] / ks[i-1]["close"] - 1) * 100, 2),
                                         "days": 0, "status": "观察中"})
                    seen.add(code)
        pool["seeded"] = True
    # 1. 维护存量
    idx = {c: {k["date"]: j for j, k in enumerate(ks)} for c, ks in stocks.items()}
    for e in pool["pool"]:
        ks = stocks.get(e["code"])
        if not ks:
            continue
        j0 = idx[e["code"]].get(e["entry_date"])
        j1 = idx[e["code"]].get(latest)
        if j1 is None and ks[-1]["date"] < latest:
            j1 = len(ks) - 1  # 已退市/停牌：用其自身尾部维护（走向超时出局）
        if j0 is None or j1 is None:
            continue
        e["days"] = j1 - j0
        hit = None
        for k in range(j0 + 1, j1 + 1):
            if ks[k - 1]["close"] > 0 and (ks[k]["close"] / ks[k - 1]["close"] - 1) * 100 >= 9.8:
                hit = k
                break
        if hit:
            e["status"] = "毕业"
            e["graduate_date"] = ks[hit]["date"]
            pool["graduated"].append(e)
            e["_rm"] = True
        elif ks[j1]["close"] < e["entry_low"]:
            e["status"] = "出局·破前低"
            pool["ejected"].append(e)
            e["_rm"] = True
        elif e["days"] >= EXPIRE:
            e["status"] = "出局·超时"
            pool["ejected"].append(e)
            e["_rm"] = True
        else:
            e["shrink"] = ks[j1]["volume"] < e["entry_vol"]
    pool["pool"] = [e for e in pool["pool"] if not e.pop("_rm", False)]
    # 2. 扫描新候选
    have = {e["code"] for e in pool["pool"]}
    new = 0
    for code, ks in stocks.items():
        if code in have or ks[-1]["date"] != latest:
            continue
        i = len(ks) - 1
        if is_signal(ks, i, v):
            pool["pool"].append({"code": code, "name": names.get(code, {}).get("name", code),
                                 "entry_date": latest, "entry_close": ks[i]["close"],
                                 "entry_low": ks[i]["low"], "entry_vol": ks[i]["volume"],
                                 "volratio": round(volratio(ks, i), 1),
                                 "pct": round((ks[i]["close"] / ks[i - 1]["close"] - 1) * 100, 2),
                                 "days": 0, "status": "观察中"})
            new += 1
    pool["updated"] = latest
    pool["variant"] = ACTIVE
    POOL_F.write_text(json.dumps(pool, ensure_ascii=False, indent=1))
    print(f"watch_pool: {latest} 新增 {new}，池中 {len(pool['pool'])}，毕业累计 {len(pool['graduated'])}")


def main():
    stocks = load_stocks()
    if "--backtest" in sys.argv:
        res = backtest(stocks)
        (ROOT / "data/watch_pool_backtest_20260912.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        daily_update(stocks)


if __name__ == "__main__":
    main()
