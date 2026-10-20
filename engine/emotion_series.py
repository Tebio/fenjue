#!/usr/bin/env python3
"""engine/emotion_series.py — 情绪周期六指标全市场日度序列 + 滚动250日分位 (2026-10-20 改版)

改版要点（旧版见 emotion_series.py.bak）：
  1. 涨跌停判定：前复权 + pct≥9.8  →  不复权精确限价（Decimal HALF_UP，0.10/0.05 双档含 ST）
  2. 六个指标各加滚动 250 日经验分位列 pct_*（绝对值跨年不可比——
     同为 25 家跌停，2019 年约 93 分位、2026 年只有约 81 分位）
  3. 起止日期可配置（--start/--end），不再硬编码 2026-01-01
  4. 落盘 data/emotion_series.jsonl（每行一日，含全部指标与分位）

指标：ADR(涨跌家数比)、涨停数、跌停数、最高板、晋级率(昨板→今板)、两市成交额
ST 口径：涨/跌停家数含 ST（恐慌广度）；连板/晋级率同样含 ST（与家数自洽——
  旧口径下 ST 5% 板根本不算板，晋级率分子分母会打架）。
分位定义：当日值在尾窗 250 个交易日（含当日）中 ≤ 当日值的比例；暖机期(窗口<120)为 null。
分位在全序列（2019 起）上算完再按 --start 切片输出。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
sys.path.insert(0, str(ROOT))
from engine.emo_build_series import build, load_cached, rolling_pct, st_anchor_check  # noqa: E402

OUT = ROOT / "data" / "emotion_series.jsonl"

METRICS = ["adr", "limit_up", "limit_down", "max_streak", "promote_rate", "amount"]


def daily_records(daily: dict) -> list[dict]:
    """由逐日聚合算六指标基础序列。"""
    out = []
    prev_boards: set[str] = set()
    for d in sorted(daily):
        rec = daily[d]
        boards = rec["boards"]
        streaks = rec["streaks"]
        max_streak = max(streaks.values()) if streaks else 0
        promoted = len(boards & prev_boards)
        rate = round(promoted / len(prev_boards) * 100, 1) if prev_boards else None
        out.append({
            "date": d,
            "up": rec["up"], "down": rec["down"],
            "adr": round(rec["up"] / max(1, rec["down"]), 2),
            "limit_up": len(boards), "limit_down": rec["limit_down"],
            "limit_up_st": rec["limit_up_st"], "limit_down_st": rec["limit_down_st"],
            "max_streak": max_streak,
            "promote_rate": rate,
            "amount": round(rec["amount"] / 1e8, 1),  # 亿元
        })
        prev_boards = boards
    return out


def attach_percentiles(rows: list[dict]) -> None:
    for m in METRICS:
        pct = rolling_pct([r[m] for r in rows])
        for r, p in zip(rows, pct):
            r[f"pct_{m}"] = p


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2019-01-01", help="输出起始日(含)，默认 2019-01-01")
    ap.add_argument("--end", default="9999-12-31", help="输出截止日(含)")
    ap.add_argument("--rebuild", action="store_true", help="不用缓存，重扫不复权库")
    ap.add_argument("--tail", type=int, default=15, help="末尾打印行数")
    args = ap.parse_args()

    daily = build() if args.rebuild else (load_cached() or build())
    rows = daily_records(daily)
    attach_percentiles(rows)

    # 落盘：全历史（分位必须在全序列上算完再切，故文件也写全历史）
    with open(OUT, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    anchor = st_anchor_check(daily)
    if anchor["pool_st"]:
        print(f"[emo] ST 对账: hithink {anchor['hithink_date']} 池内 is_st {len(anchor['pool_st'])} 只（子集口径）")

    sel = [r for r in rows if args.start <= r["date"] <= args.end]
    print(f"[emo] 序列 {rows[0]['date']}..{rows[-1]['date']} 共 {len(rows)} 天 -> {OUT}")
    print(f"[emo] 输出区间 {sel[0]['date'] if sel else '-'}..{sel[-1]['date'] if sel else '-'} 共 {len(sel)} 天")
    for r in sel[-args.tail:]:
        pr = "-" if r["promote_rate"] is None else f"{r['promote_rate']:5.1f}"
        pcts = " ".join(f"{m}:{('-' if r[f'pct_{m}'] is None else f'{r[f'pct_{m}']:.2f}')}" for m in METRICS)
        print(f"{r['date']} ADR {r['adr']:5.2f} 涨/跌 {r['up']:4d}/{r['down']:4d} | "
              f"涨停 {r['limit_up']:3d}(ST{r['limit_up_st']}) 跌停 {r['limit_down']:3d}(ST{r['limit_down_st']}) | "
              f"最高板 {r['max_streak']:2d} 晋级 {pr}% | 额 {r['amount']:7.0f}亿 | {pcts}")


if __name__ == "__main__":
    main()
