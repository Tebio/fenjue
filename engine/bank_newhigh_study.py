#!/usr/bin/env python3
"""银行「创历史新高」信号实测（2026-10-08，用户发来大佬的东财条件选股后立项）。

大佬筛选式：东财 → 银行板块(42) → 最高价(前复权)创历史新高 → 实时命中 3 只
（杭州银行/工商银行/中国银行）。问题：这个信号能不能跟？

口径（全仓库统一）：
- 事件：某日 high == 该日之前（含当日）区间最高（前复权 kcache，2019-01 起，
  所以「历史新高」= 本区间新高，非真全史——2019 前的高点看不到，已在结论里标注）
- 入场：事件次日(T+1)开盘；出场：T+5/T+20/T+60 收盘；净口径双边 0.15%
- 对照三档：①同票非新高日（同 horizon 全样本均值）②同日全银行均值（剔银行 beta）
  ③上证指数同 horizon（剔大盘）
- 分层：分年 + 双段(2019-22/2023-26) + 首创新高(前 60 日无新高) vs 连续新高
- 息率交叉：事件日 trailing 12 月每股分红/价格 → 息率档（<3 / 3-4 / 4-4.5 / >4.5）
  即大佬操作台的 清仓/卖出/持有/买入 线，看「什么息率档上创新高才值得跟」
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
sys.path.insert(0, "/opt/data/python-libs")
KC = ROOT / "data/big_kcache"
from costs import FLAT_RT  # TAX-01 唯一真源 engine/costs.py（AGENTS #287）
FEE = FLAT_RT
HORIZONS = (5, 20, 60)
CACHE_UNIV = ROOT / "data/bank_universe.json"


def bank_universe() -> list[str]:
    """银行股全名单（42 只，与大佬筛选器的「银行(42)」对齐）。

    数据源：本地 data/industry_map.json 的证监会行业 J66货币金融服务（38 只）
    —— 东财 push2 板块接口被容器代理拦（AGENTS.md 已记），所以不走 akshare 板块接口；
    38 只漏掉的 4 只按名单补齐（渝农商行/沪农商行/张家港行/青农商行），合计 42 = 东财口径。
    """
    if CACHE_UNIV.exists():
        return json.loads(CACHE_UNIV.read_text())["codes"]
    im = json.loads((ROOT / "data/industry_map.json").read_text())
    codes = {c for c, v in im.items() if "货币金融" in str(v.get("industry", ""))}
    # J66 里混着非银行金融机构（中油资本/新力金融/江苏金租），东财银行板块不含 → 剔掉
    codes -= {"000617", "600318", "600901"}
    codes |= {"601077", "601825", "002839", "002958"}   # J66 未收录的 4 家银行
    codes = sorted(codes)
    CACHE_UNIV.write_text(json.dumps(
        {"codes": codes, "src": "industry_map J66 + 补齐4只（东财银行板块口径 42）",
         "ts": datetime.now().isoformat()}, ensure_ascii=False))
    return codes


def series(code: str):
    fp = KC / f"{code}.json"
    if not fp.exists():
        return []
    return json.loads(fp.read_text())


def div_events(code: str) -> list[tuple[str, float]]:
    """实施派息明细（复用 watchlist_refresh 的缓存实现）。"""
    sys.path.insert(0, str(ROOT / "engine"))
    import watchlist_refresh as W
    return W.div_events(code)


def trailing_dps(ev: list[tuple[str, float]], day: str) -> float:
    """day 之前的近 365 天实施派息合计（元/股）。"""
    d0 = datetime.fromisoformat(day).date()
    tot = sum(v for d, v in ev
              if 0 <= (d0 - datetime.fromisoformat(d).date()).days <= 365)
    return tot / 10


def main():
    idx = json.loads((ROOT / "data/index_sh000001.json").read_text())
    idx_close = {r["date"]: r["close"] for r in idx}

    codes = bank_universe()
    ks = {c: series(c) for c in codes}
    ks = {c: v for c, v in ks.items() if len(v) > 200}
    print(f"银行宇宙 {len(codes)} 只，有 kcache {len(ks)} 只")

    rows = []           # 事件行
    all_days = {}       # (code, date) -> 各行收益，供对照（后面剔除事件日本身）
    for c, k in ks.items():
        dates = [r["date"] for r in k]
        hi_run = 0.0
        last_high_i = -999
        for i, r in enumerate(k):
            if r["high"] > hi_run:
                hi_run = r["high"]
                if i >= 120:
                    ev = {"code": c, "date": r["date"], "i": i,
                          "first": (i - last_high_i) > 60}
                    last_high_i = i
                    rows.append(ev)
        # 全样本基线（该票所有日）
        for i, r in enumerate(k):
            if i < 120:
                continue
            all_days[(c, r["date"])] = {h: ret(k, i, h) for h in HORIZONS}
    # 对照必须剔除事件日本身（否则「非新高对照」= 事件自己，2026-10-08 自查抓的 bug）
    event_keys = {(e["code"], e["date"]) for e in rows}
    for key in list(all_days):
        if key in event_keys:
            del all_days[key]

    print(f"事件数 {len(rows)}")
    dps_cache = {}
    out = []
    for ev in rows:
        k, i = ks[ev["code"]], ev["i"]
        rec = {"code": ev["code"], "date": ev["date"], "i": ev["i"], "first": ev["first"]}
        for h in HORIZONS:
            rec[h] = ret(k, i, h)
        # 息率档
        if ev["code"] not in dps_cache:
            try:
                dps_cache[ev["code"]] = div_events(ev["code"])
            except Exception:
                dps_cache[ev["code"]] = []
        dps = trailing_dps(dps_cache[ev["code"]], ev["date"])
        px = k[i]["high"]
        rec["yield"] = dps / px * 100 if px else None
        out.append(rec)

    # 对照：同日全银行均值 / 指数 / 同票近邻非新高
    by_date = {}
    for ev in out:
        by_date.setdefault(ev["date"], []).append(ev)
    per_code: dict[str, list] = {}
    for c, k in ks.items():
        for i, r in enumerate(k):
            if i >= 120 and (c, r["date"]) in all_days:
                per_code.setdefault(c, []).append((i, r["date"], all_days[(c, r["date"])]))
    bank_day_avg = {}
    for c, k in ks.items():
        for i, r in enumerate(k):
            if i >= 120:
                bank_day_avg.setdefault(r["date"], {h: [] for h in HORIZONS})
                for h in HORIZONS:
                    v = ret(k, i, h)
                    if v is not None:
                        bank_day_avg[r["date"]][h].append(v)

    def stats(vals):
        vals = [v for v in vals if v is not None]
        if not vals:
            return None
        return {"n": len(vals), "win": sum(1 for v in vals if v > 0) / len(vals) * 100,
                "mean": sum(vals) / len(vals),
                "med": sorted(vals)[len(vals) // 2]}

    def fmt(s):
        return "—" if not s else f"n={s['n']:<5} {s['win']:5.1f}% {s['mean']:+7.2f}% 中位{s['med']:+6.2f}%"

    print("\n═══ ① 全体事件 vs 三档对照（净 0.15%）═══")
    for h in HORIZONS:
        ev = stats([r[h] for r in out])
        # 同票近邻对照：同一只票 ±60 交易日内的非新高日（局部基线，剔趋势）
        near = []
        for r in out:
            for i, d, rd in per_code.get(r["code"], []):
                if abs(i - r["i"]) <= 60:
                    near.append(rd.get(h))
        ctrl_same = stats(near)
        # 同日全银行均值（按事件日期聚合，再对事件取平均）
        vals = []
        for r in out:
            arr = bank_day_avg.get(r["date"], {}).get(h) or []
            if arr:
                vals.append(sum(arr) / len(arr))
        ctrl_bank = stats(vals)
        idxs = []
        for r in out:
            a = idx_close.get(r["date"])
            j = next((x for x, rr in enumerate(idx) if rr["date"] == r["date"]), None)
            b = idx_close.get(idx[j + h]["date"]) if j is not None and j + h < len(idx) else None
            if a and b:
                idxs.append((b / a - 1) * 100 - FEE * 100)
        ctrl_idx = stats(idxs)
        print(f"T+{h:<3} 事件 {fmt(ev)}")
        print(f"      同票非新高 {fmt(ctrl_same)}")
        print(f"      同日全银行 {fmt(ctrl_bank)}")
        print(f"      上证指数   {fmt(ctrl_idx)}")
        if ev and ctrl_bank and ctrl_idx:
            print(f"      → 超额(对银行) {(ev['mean'] - ctrl_bank['mean']):+.2f}pp  "
                  f"(对指数) {(ev['mean'] - ctrl_idx['mean']):+.2f}pp")

    print("\n═══ ② 首创新高 vs 连续新高 ═══")
    for label, sub in (("首创新高(前60日无新高)", [r for r in out if r["first"]]),
                       ("连续新高", [r for r in out if not r["first"]])):
        print(f"{label:<22} " + " | ".join(f"T+{h} {fmt(stats([r[h] for r in sub]))}" for h in HORIZONS))

    print("\n═══ ③ 分年（T+20）═══")
    years = sorted({r["date"][:4] for r in out})
    for y in years:
        s = stats([r[20] for r in out if r["date"].startswith(y)])
        print(f"  {y}: {fmt(s)}")

    print("\n═══ ④ 双段（T+20 / T+60）═══")
    for lo, hi, name in (("2019", "2022", "2019-2022"), ("2023", "2026", "2023-2026")):
        sub = [r for r in out if lo <= r["date"][:4] <= hi]
        print(f"  {name}: T+20 {fmt(stats([r[20] for r in sub]))} | T+60 {fmt(stats([r[60] for r in sub]))}")

    print("\n═══ ⑤ 息率档交叉（T+20；即大佬操作台的 4.5/4.0/3.0 线）═══")
    buckets = [(0, 3, "清仓区 <3%"), (3, 4, "卖出区 3-4%"), (4, 4.5, "持有区 4-4.5%"), (4.5, 99, "买入区 >4.5%")]
    for lo, hi, name in buckets:
        sub = [r for r in out if r["yield"] is not None and lo <= r["yield"] < hi]
        print(f"  {name:<14} {fmt(stats([r[20] for r in sub]))}")
    ny = sum(1 for r in out if r["yield"] is None)
    print(f"  （无息率数据 {ny} 条）")

    (ROOT / "data/bank_newhigh_events.json").write_text(json.dumps(out, ensure_ascii=False))
    print(f"\n事件明细已落盘 data/bank_newhigh_events.json（{len(out)} 条）")


def ret(k: list[dict], i: int, h: int) -> float | None:
    """事件日 i → 次日开盘买、T+h 收盘卖的净收益(%)。"""
    if i + h >= len(k) - 1:
        return None
    entry = k[i + 1]["open"]
    exitp = k[i + h]["close"]
    if entry <= 0:
        return None
    return (exitp / entry - 1) * 100 - FEE * 100


if __name__ == "__main__":
    main()
