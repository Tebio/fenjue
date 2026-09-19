#!/usr/bin/env python3
"""shadow_rebuild.py — 影子账本全量重建清洗（2026-09-19 用户立项：旧账有脏数据/bug）。

背景：claims_shadow.jsonl 早期条目的 entry/r1/r5/r20 是在有 bug 的实现下填的——
  · C2（9/12 前）：可成交性在信号日判（应在入场日判）
  · T+0 幻觉（9/18 前）：open-entry 族的收益从信号日开盘价算到当日收盘，物理不可能
  · C3（9/12 前）：退市股末日幽灵信号
本脚本不删历史、全部用现行正确口径重算，逐条覆写；改动量写报告。
口径源 = claims_shadow.py 第 230-268 行的现行回填逻辑（逐行对齐，禁自由发挥）。
"""
import json
import shutil
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHADOW = ROOT / "data/claims_shadow.jsonl"
SUMMARY = ROOT / "data/claims_shadow_summary.json"
FEE = 0.0015
CLOSE_ENTRY_CLAIMS = {"FRONTRUN_FIRSTBOARD_V2", "WATCHPOOL_GRAD"}


def load_stocks():
    out = {}
    for fp in sorted((ROOT / "data/big_kcache").glob("*.json")):
        ks = json.loads(fp.read_text())
        if len(ks) >= 2:
            out[fp.stem] = ks
    return out


def refill(r, ks):
    """重置并用现行口径重算一条单。返回是否有改动。"""
    old = dict(r)
    for k in ("entry", "r1", "r5", "r20", "untradeable"):
        r.pop(k, None)
    idx = {k["date"]: j for j, k in enumerate(ks)}
    si = idx.get(r["signal_date"])
    if si is None:
        r["stale"] = "信号日不在该票k线（幽灵/已退市缺数据）"
        return old != r
    if r["claim"] in CLOSE_ENTRY_CLAIMS:
        if ks[si]["high"] <= ks[si]["low"]:
            r["untradeable"] = "信号日一字板买不进"
        else:
            e = ks[si]["close"]
            if e > 0:
                r["entry"] = e
        ei = si
    else:
        if si + 1 >= len(ks):
            r["stale"] = "信号日为最后一根bar，无入场日"
            return old != r
        e = ks[si + 1]["open"]
        pc0 = ks[si]["close"]
        gap = e / pc0 - 1 if pc0 > 0 else 0
        amp = (ks[si + 1]["high"] - ks[si + 1]["low"]) / pc0 if pc0 > 0 else 1
        if gap >= 0.095:
            r["untradeable"] = "一字涨停买不进"
        elif gap <= -0.095 and amp < 0.01:
            r["untradeable"] = "一字跌停锁死"
        elif e > 0:
            r["entry"] = e
        ei = si + 1
    if r.get("entry"):
        e = r["entry"]
        for tag, off in (("r1", 1), ("r5", 5), ("r20", 20)):
            if ei + off < len(ks):
                r[tag] = round(ks[ei + off]["close"] / e - 1 - FEE, 5)
    return old != r


def main():
    bak = SHADOW.with_suffix(".jsonl.bak_20260919")
    if not bak.exists():
        shutil.copy2(SHADOW, bak)
    stocks = load_stocks()
    lines, seen, dedup = [], set(), 0
    changed = 0
    missing_stock = 0
    for raw in SHADOW.read_text().splitlines():
        r = json.loads(raw)
        key = (r["signal_date"], r["claim"], r["code"], r.get("tier"))
        if key in seen:
            dedup += 1
            continue
        seen.add(key)
        ks = stocks.get(r["code"])
        if ks is None:
            missing_stock += 1
            r["stale"] = "kcache 无此票"
        else:
            if refill(r, ks):
                changed += 1
        lines.append(r)
    SHADOW.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in lines) + "\n")

    # 汇总（只统可成交单；口径同 claims_shadow.py 第3段）
    import statistics as st
    summ = defaultdict(list)
    for r in lines:
        if not r.get("entry"):
            continue
        for tag in ("r1", "r5", "r20"):
            v = r.get(tag)
            if v is not None:
                summ[(r["claim"], r.get("tier") or "-", tag)].append(v)
    out = {}
    for (claim, tier, tag), vs in sorted(summ.items()):
        out.setdefault(claim, {}).setdefault(tier, {})[tag] = {
            "n": len(vs), "win%": round(100 * sum(x > 0 for x in vs) / len(vs), 1),
            "mean%": round(100 * st.mean(vs), 2)}
    SUMMARY.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"重建完成：{len(lines)} 单（去重-{dedup}，无票-{missing_stock}），重算改动 {changed} 单")
    print(f"备份：{bak.name}")


if __name__ == "__main__":
    main()
