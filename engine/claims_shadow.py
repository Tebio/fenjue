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


def load_stocks():
    out = {}
    for fp in sorted(KC.glob("*.json")):
        ks = json.loads(fp.read_text())
        if len(ks) >= 65:
            out[fp.stem] = ks
    return out


def detect(code, ks, i):
    """返回第 i 根（信号日）触发的 (claim, tier) 列表。
    自查修正（2026-09-12）：①不再假设信号日=最后一根（SHADOW_DATE 回填历史时错位）；
    ②LIMITDOWN 不在信号日剔一字——可成交性只能在入场日（i+1）判，注册时全量登记。"""
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
    return hits


def main():
    stocks = load_stocks()
    import os
    today = os.environ.get("SHADOW_DATE") or date.today().isoformat()  # SHADOW_DATE 供测试回填历史日
    last_dates = {ks[-1]["date"] for ks in stocks.values()}
    if today not in last_dates:
        print(f"[SILENT] kcache 最新 {max(last_dates)}，今日 {today} 无数据（非交易日或未刷新）")
        return

    # 1. 登记今日信号
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
            for claim, tier in detect(code, ks, idx):
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
            for tag, off in [("r1", 1), ("r5", 5), ("r20", 20)]:
                if r[tag] is None and si + off < len(ks):
                    r[tag] = round(ks[si + off]["close"] / e - 1 - FEE, 5)
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
