#!/usr/bin/env python3
"""engine/claims_shadow.py — 存活主张的影子前向记录（L5 毕业条件的数据源）

每日收盘后（kcache 刷新后）跑：
1. 扫描今日信号：REVERSAL（跌≥3%）/ LIMITDOWN（跌≤-9.5%，剔一字）/ PANIC_DEPTH 四档
2. 登记 shadow 单：{signal_date, claim, code, tier}
3. 回填历史单：次日开盘价（entry）、T+1/T+5/T+20 收盘收益
4. 汇总各主张的滚动影子表现 → data/claims_shadow_summary.json 供 claims_audit 读 L5

设计约束：只用 big_kcache（前复权日K），无新增数据依赖；净口径 -0.15%。
"""
import json
from datetime import date
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data/big_kcache"
SHADOW = ROOT / "data/claims_shadow.jsonl"
SUMMARY = ROOT / "data/claims_shadow_summary.json"
FEE = 0.0015
# FRONTRUN_V2（2026-09-12 注册）：首板+板块梯队≥3+市值20-400亿。
# 入场口径=信号日收盘（打板成交假设，fill 率由影子前向中的封板时间另行定量），
# 与框架默认的次日开盘不同——次日追是该主张内部已证伪的变体（-0.52%）。
CLOSE_ENTRY_CLAIMS = {"FRONTRUN_FIRSTBOARD_V2", "WATCHPOOL_GRAD"}
_industry = None
_stock_cap = None
_regime_tl = None


def _regime_of(d):
    """当日周期标签（regime_timeline_hcap），懒加载。"""
    global _regime_tl
    if _regime_tl is None:
        try:
            _regime_tl = {r["date"]: r["regime"] for r in json.load(open(ROOT / "data/regime_timeline_hcap.json"))}
        except Exception:
            _regime_tl = {}
    return _regime_tl.get(d, "?")


def industry_map():
    global _industry
    if _industry is None:
        _industry = json.loads((ROOT / "data/industry_map.json").read_text())
    return _industry


def stock_caps():
    global _stock_cap
    if _stock_cap is None:
        import glob
        cap = {}
        for fp in glob.glob(str(ROOT / "data/cap_hist/*.json")):
            d = {}
            for dt, _px, c in json.loads(open(fp).read()):
                d[dt[:7]] = c
            cap[Path(fp).stem] = d
        _stock_cap = cap
    return _stock_cap


def load_stocks():
    out = {}
    for fp in sorted(KC.glob("*.json")):
        ks = json.loads(fp.read_text())
        if len(ks) >= 65:
            out[fp.stem] = ks
    return out


def detect(code, ks, i, ladder=None):
    """返回第 i 根（信号日）触发的 (claim, tier) 列表。
    自查修正（2026-09-12）：①不再假设信号日=最后一根（SHADOW_DATE 回填历史时错位）；
    ②LIMITDOWN 不在信号日剔一字——可成交性只能在入场日（i+1）判，注册时全量登记。
    ③FRONTRUN_FIRSTBOARD_V2：首板（≥9.8% 且前60日无板）+可买（开盘<+9.5%）
      +梯队（ladder 同行业当日≥3）+市值带20-400亿（cap_hist 月度，缺数据=不触发）。"""
    if i < 65:
        return []
    c, pc = ks[i]["close"], ks[i - 1]["close"]
    if pc <= 0:
        return []
    chg = c / pc - 1
    hits = []
    if chg <= -0.03:
        hits.append(("REVERSAL_OPEN_T1", None))
        tier = ("-3~-5%" if chg > -0.05 else "-5~-7%" if chg > -0.07
                else "-7~-9.5%" if chg > -0.095 else "≤-9.5%")
        hits.append(("PANIC_DEPTH_DOSE", tier))
    if chg <= -0.095:
        hits.append(("LIMITDOWN_NEXT_DAY", None))
    if ladder is not None and chg >= 0.098:
        o = ks[i]["open"]
        if o > 0 and (o / pc - 1) < 0.095:  # 一字板买不进
            first = all(
                ks[j]["close"] <= 0 or ks[j - 1]["close"] <= 0
                or (ks[j]["close"] / ks[j - 1]["close"] - 1) < 0.098
                for j in range(max(1, i - 60), i))
            if first:
                industry = industry_map().get(code, {}).get("industry") or "?"
                if ladder.get(industry, 0) >= 3:
                    cap = stock_caps().get(code, {}).get(ks[i]["date"][:7])
                    if cap is not None and 20 <= cap <= 400:
                        # tier=当日regime（2026-09-12：反人群打板假设的前向测量——恐慌/平淡期fill是漏，主线/妖股期是坑）
                        reg = _regime_of(ks[i]["date"])
                        hits.append(("FRONTRUN_FIRSTBOARD_V2", reg))
    # WATCHPOOL_GRAD（G8，2026-09-12）：观察池毕业=今日首板 + 前15日内曾触发 B 变体池信号
    # （量比≥3、涨幅1~7.5%、未板、复牌守卫、额≥2亿）。入场=信号日收盘（打板口径同 FRONTRUN）。
    if chg >= 0.098 and i >= 6:
        import datetime as _dt
        for j in range(max(6, i - 15), i):
            if ks[j - 1]["close"] <= 0:
                continue
            try:
                d0 = _dt.date.fromisoformat(ks[j - 5]["date"]); d1 = _dt.date.fromisoformat(ks[j]["date"])
            except Exception:
                continue
            if (d1 - d0).days > 12 or any(ks[k]["volume"] <= 0 for k in range(j - 5, j)):
                continue
            pj = (ks[j]["close"] / ks[j - 1]["close"] - 1) * 100
            if not (1.0 <= pj <= 7.5):
                continue
            base = [ks[k]["volume"] for k in range(j - 5, j)]
            mb = sum(base) / len(base)
            if mb <= 0 or ks[j]["volume"] / mb < 3.0:
                continue
            if ks[j]["volume"] * ks[j]["close"] < 2e8:
                continue
            hits.append(("WATCHPOOL_GRAD", None))
            break
    return hits


def main():
    stocks = load_stocks()
    import os
    today = os.environ.get("SHADOW_DATE") or date.today().isoformat()  # SHADOW_DATE 供测试回填历史日
    last_max = max(ks[-1]["date"] for ks in stocks.values())
    if os.environ.get("SHADOW_DATE"):
        # 显式回填历史日：只要求该日在数据里真实存在（多数票有当日 bar），
        # 不能用「等于最新交易日」当守卫——那会让所有补登记日一律 [SILENT]（2026-09-18 修）
        n_has = sum(1 for ks in stocks.values() if any(k["date"] == today for k in ks[-6:]))
        if n_has < 0.5 * len(stocks):
            print(f"[SILENT] SHADOW_DATE={today} 在 kcache 中不存在（{n_has}/{len(stocks)} 票有当日 bar）")
            return
    elif today not in {ks[-1]["date"] for ks in stocks.values()}:
        print(f"[SILENT] kcache 最新 {last_max}，今日 {today} 无数据（非交易日或未刷新）")
        return

    # 1. 登记今日信号（先算今日行业梯队，供 FRONTRUN 检测）
    ladder = {}
    for code, ks in stocks.items():
        j = len(ks) - 1
        if ks[j]["date"] != today or j < 1 or ks[j - 1]["close"] <= 0:
            continue
        if ks[j]["close"] / ks[j - 1]["close"] - 1 >= 0.098:
            ind = industry_map().get(code, {}).get("industry") or "?"
            ladder[ind] = ladder.get(ind, 0) + 1
    existing = set()
    if SHADOW.exists():
        for line in SHADOW.read_text().splitlines():
            r = json.loads(line)
            existing.add((r["signal_date"], r["claim"], r["code"]))
    new = 0
    with SHADOW.open("a") as f:
        for code, ks in stocks.items():
            idx = next((j for j in range(len(ks) - 1, -1, -1) if ks[j]["date"] == today), None)
            if idx is None:
                continue
            for claim, tier in detect(code, ks, idx, ladder):
                key = (today, claim, code)
                if key not in existing:
                    f.write(json.dumps({"signal_date": today, "claim": claim, "code": code,
                                        "tier": tier, "entry": None, "r1": None, "r5": None, "r20": None},
                                       ensure_ascii=False) + "\n")
                    new += 1

    # 2. 回填（重写整个 jsonl——单文件量级可控：每日几百条×数月）
    lines = [json.loads(x) for x in SHADOW.read_text().splitlines()]
    filled = 0
    for r in lines:
        ks = stocks.get(r["code"])
        if not ks:
            continue
        idx = {k["date"]: j for j, k in enumerate(ks)}
        si = idx.get(r["signal_date"])
        if si is None or si + 1 >= len(ks):
            continue
        if r["entry"] is None:
            if r["claim"] in CLOSE_ENTRY_CLAIMS:
                # 信号日收盘入场（打板成交假设）；信号日一字全天（high==low）判不可成交
                if ks[si]["high"] <= ks[si]["low"]:
                    r["untradeable"] = "信号日一字板买不进"
                    continue
                e = ks[si]["close"]
                if e <= 0:
                    continue
                r["entry"] = e
                filled += 1
            else:
                e = ks[si + 1]["open"]
                if e <= 0:
                    continue
                # 入场日可成交性（自查修正：一字剔除在入场日判，与 s10_retest 口径一致）
                pc0 = ks[si]["close"]
                gap = e / pc0 - 1 if pc0 > 0 else 0
                amp = (ks[si + 1]["high"] - ks[si + 1]["low"]) / pc0 if pc0 > 0 else 1
                if gap >= 0.095:
                    r["untradeable"] = "一字涨停买不进"
                    continue
                if gap <= -0.095 and amp < 0.01:
                    r["untradeable"] = "一字跌停锁死"
                    continue
                r["entry"] = e
                filled += 1
        if r["entry"]:
            e = r["entry"]
            # T+1 时序硬断言（2026-09-18 修）：出场日必须严格晚于入场日。
            # 旧实现用 off 从信号日 si 起算，open-entry 族（反转/跌停接）变成
            # 「当日开盘买 → 当日收盘卖」= T+0，物理不可能成交（A股 T+1）。
            # 现改为从入场日 ei 起算：ei=si（收盘入场）/ei=si+1（次日开盘入场）。
            ei = si if r["claim"] in CLOSE_ENTRY_CLAIMS else si + 1
            for tag, off in [("r1", 1), ("r5", 5), ("r20", 20)]:
                if r[tag] is None and ei + off < len(ks):
                    assert ei + off > ei, "出场日必须晚于入场日"
                    r[tag] = round(ks[ei + off]["close"] / e - 1 - FEE, 5)
                    filled += 1
    SHADOW.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in lines) + "\n")

    # 3. 汇总（只统计 entry 已填的单）
    import statistics as st
    summ = {}
    for r in lines:
        if r["entry"] is None:
            continue
        for tag in ("r1", "r5", "r20"):
            v = r[tag]
            if v is None:
                continue
            key = (r["claim"], r["tier"] or "-", tag)
            summ.setdefault(key, []).append(v)
    out = {}
    for (claim, tier, tag), vs in sorted(summ.items()):
        out.setdefault(claim, {}).setdefault(tier, {})[tag] = {
            "n": len(vs), "win%": round(100 * sum(x > 0 for x in vs) / len(vs), 1),
            "mean%": round(100 * st.mean(vs), 2)}
    SUMMARY.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"shadow: 新登记 {new}，回填 {filled}，累计 {len(lines)} 单")


if __name__ == "__main__":
    main()
