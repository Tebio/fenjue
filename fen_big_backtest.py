#!/usr/bin/env python3
"""fen_big_backtest.py — 多年大样本策略对照回测 (2026-09-06)

样本：焚诀池历史覆盖的 903 票里按板块分层抽 300 票，2019-01-01 → 2026-09-04 全历史日K（baostock 前复权）。
每个股票日 D 判定（全部用 T-1 及更早数据，零未来函数；一字板不可成交剔除）：
  A 追高门：开盘涨幅∈[2,8.5]%，开盘>MA5或MA20(T-1)，MA20乖离≤35%
  B 甜区：  开盘涨幅∈[4,6.5]%（A 的子集）
  C 反转：  T-1 日收跌≤-3%，买 D 开盘
  D 低波：  20日日收益波动率横截面最低20% + 开盘>MA20(T-1)
  R 随机：  同策略同日随机等数股票日（10种子）
  I 指数：  上证指数同日
口径：D 开盘买 → D+1 收盘卖（T1）/ D+2 收盘（T2）。输出按策略×年份× horizons。
"""
from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "/opt/data/python-libs")
import baostock as bs  # noqa: E402

ROOT = Path("/opt/data/fenjue")
CACHE = ROOT / "data" / "big_kcache"
CACHE.mkdir(parents=True, exist_ok=True)
START, END = "2019-01-01", "2026-09-04"


def load_universe() -> list[dict]:
    codes: dict[str, dict] = {}
    for f in sorted(ROOT.glob("pool_20*.json")):
        for r in json.loads(f.read_text()).get("results", []):
            c = str(r["code"]).zfill(6)
            if c.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
                codes.setdefault(c, {"code": c, "name": r["name"], "sector": r.get("sector", "")})
    # 分层抽样：每板块最多 6 只，凑满 300
    by_sec = defaultdict(list)
    for v in codes.values():
        by_sec[v["sector"]].append(v)
    rng = random.Random(7)
    sample = []
    for sec, rows in sorted(by_sec.items()):
        rng.shuffle(rows)
        sample.extend(rows[:6])
    rng.shuffle(sample)
    return sample[:300]


def fetch(code: str) -> list[dict]:
    f = CACHE / f"{code}.json"
    if f.exists():
        return json.loads(f.read_text())
    bs_code = ("sh." if code.startswith("6") else "sz.") + code
    rs = bs.query_history_k_data_plus(
        bs_code, "date,open,high,low,close,volume",
        start_date=START, end_date=END, frequency="d", adjustflag="2")
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    out = [{"date": r[0], "open": float(r[1] or 0), "high": float(r[2] or 0),
            "low": float(r[3] or 0), "close": float(r[4] or 0), "volume": float(r[5] or 0)}
           for r in rows if r[4]]
    f.write_text(json.dumps(out))
    return out


def events_for(code: str, ks: list[dict]) -> dict[str, list[tuple]]:
    """返回 {策略: [(j, open_pct, buy)]}，j = D 在 ks 的下标"""
    ev = {"A": [], "B": [], "C": [], "D": []}
    n = len(ks)
    closes = [k["close"] for k in ks]
    rets = [0.0] + [(closes[i] - closes[i - 1]) / closes[i - 1] * 100 for i in range(1, n)]
    for j in range(21, n - 2):
        today, prev = ks[j], ks[j - 1]
        if prev["close"] <= 0 or today["open"] <= 0:
            continue
        open_pct = (today["open"] - prev["close"]) / prev["close"] * 100
        if abs(open_pct) >= 9.8:  # 一字板不可成交
            continue
        ma5 = sum(closes[j - 5:j]) / 5
        ma20 = sum(closes[j - 20:j]) / 20
        ma20_gap = (today["open"] - ma20) / ma20 * 100
        if 2.0 <= open_pct <= 8.5 and (today["open"] > ma5 or today["open"] > ma20) and ma20_gap <= 35:
            ev["A"].append(j)
            if 4.0 <= open_pct <= 6.5:
                ev["B"].append(j)
        if rets[j - 1] <= -3.0:  # T-1 大跌 → 反转买开盘
            ev["C"].append(j)
        vol20 = (sum((r - sum(rets[j - 20:j]) / 20) ** 2 for r in rets[j - 20:j]) / 20) ** 0.5
        if today["open"] > ma20:
            ev["D"].append((j, vol20))  # 先全收，横截面低波筛选在聚合层做
    return ev


def ret(ks, j, hz):
    buy = ks[j]["open"]
    sell = ks[j + hz]["close"]
    return (sell - buy) / buy * 100 if buy > 0 else None


def main() -> int:
    universe = load_universe()
    print(f"样本 {len(universe)} 票", file=sys.stderr)
    lg = bs.login()
    if lg.error_code != "0":
        print("baostock login fail", lg.error_msg, file=sys.stderr)
        return 1
    all_events = {}
    kstore = {}
    for i, s in enumerate(universe):
        try:
            ks = fetch(s["code"])
        except Exception as e:
            print(f"{s['code']} fetch fail {e}", file=sys.stderr)
            continue
        if len(ks) < 60:
            continue
        kstore[s["code"]] = ks
        all_events[s["code"]] = events_for(s["code"], ks)
        if i % 50 == 0:
            print(f"  {i}/{len(universe)}", file=sys.stderr)
    bs.logout()
    print(f"就绪 {len(kstore)} 票", file=sys.stderr)

    # D 策略横截面低波：按日聚合波动率，取最低 20%
    day_vol = defaultdict(list)  # date -> [(vol, code, j)]
    for code, ev in all_events.items():
        for j, v in ev["D"]:
            day_vol[kstore[code][j]["date"]].append((v, code, j))
    d_events = defaultdict(list)  # code -> [j]
    for dt, rows in day_vol.items():
        rows.sort()
        cutoff = max(1, int(len(rows) * 0.2))
        for v, code, j in rows[:cutoff]:
            d_events[code].append(j)

    rng = random.Random(42)
    out = {}
    for strat in ("A", "B", "C", "D", "R"):
        by_year = defaultdict(list)
        for code, ks in kstore.items():
            if strat == "D":
                idxs = d_events.get(code, [])
            elif strat == "R":
                n_ev = len(all_events[code]["A"])
                pool = list(range(21, len(ks) - 2))
                idxs = rng.sample(pool, min(n_ev, len(pool))) if pool else []
            else:
                idxs = all_events[code][strat]
            for j in idxs:
                r1 = ret(ks, j, 1)
                if r1 is None:
                    continue
                by_year[ks[j]["date"][:4]].append(r1)
        out[strat] = {y: {"n": len(v), "win%": round(sum(1 for x in v if x > 0) / len(v) * 100, 1),
                          "avg%": round(sum(v) / len(v), 3)} for y, v in sorted(by_year.items())}
        allv = [x for v in by_year.values() for x in v]
        out[strat]["ALL"] = {"n": len(allv), "win%": round(sum(1 for x in allv if x > 0) / len(allv) * 100, 1),
                             "avg%": round(sum(allv) / len(allv), 3)} if allv else {}

    # 指数同口径
    idx_ks = fetch("000001") if (CACHE / "000001.json").exists() else None
    rs2 = bs.login()
    idx_rows = fetch("000001") if not idx_ks else idx_ks
    bs.logout()
    # 指数用未复权 sh.000001——baostock 指数代码
    (ROOT / "data" / "big_backtest.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
