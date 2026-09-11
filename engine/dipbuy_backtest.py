#!/usr/bin/env python3
"""engine/dipbuy_backtest.py — 盘中低吸 vs 开盘买 对照 (2026-09-06)

回应：「为什么不以盘中买点/卖点为标准？妖股盘中低吸第二天说不定涨停」
用 300 只分层样本 2019-2026 日K（OHLC）实测可成交的限价低吸单：

  R-open  反转开盘买：T-1跌≥3% → T日开盘买（对照组，已有 +0.308%/50.2%）
  R-dip1  反转低吸：T-1跌≥3% → T日挂限价 T-1收盘×0.99（盘中再跌1%才接）→ T+1收盘出
  R-dip2  同上但挂 ×0.98（跌2%才接）
  B-open  首板次日开盘追：T-1涨停 → T日开盘买（已有：44.8%/-0.2%）
  B-dip2  首板次日低吸：T-1涨停 → T日挂 T-1收盘×0.98 → T+1收盘出
  B-dip5  首板次日深低吸：挂 ×0.95 → T+1收盘出

成交判定：T日最低价 ≤ 限价 才成交（保守：成交价=限价）。
一字板/涨跌停不可成交日剔除。零未来函数。
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

KCACHE = Path("/opt/data/fenjue/data/big_kcache")


def pct(a: float, b: float) -> float:
    return (a - b) / b * 100 if b else 0.0


def run() -> dict:
    stats = defaultdict(list)
    for f in sorted(KCACHE.glob("*.json")):
        if f.stem == "000001":
            continue
        ks = json.loads(f.read_text())
        n = len(ks)
        if n < 120:
            continue
        for j in range(1, n - 1):
            prev, today, nxt = ks[j - 1], ks[j], ks[j + 1]
            pc = float(prev["close"])
            tc = float(today["close"])
            if pc <= 0 or tc <= 0:
                continue
            prev_chg = pct(pc, float(prev["open"]))  # T-1 日收相对其开盘——改用收收口径
            prev_cc = pct(pc, float(ks[j - 2]["close"])) if j >= 2 else 0.0
            today_open = float(today["open"])
            today_low = float(today["low"])
            nxt_close = float(nxt["close"])
            # 一字跌停当日限价单必"触及"但实盘排不到（2026-09-06 R2 审查修复，
            # 与 B-open 的一字开剔除对齐）：开盘≈跌停且全天振幅<1% → 低吸腿全部跳过
            sealed_down = pct(today_open, pc) <= -9.5 and (float(today["high"]) - today_low) / pc * 100 < 1.0
            # ── 反转族（T-1 收跌≥3%，收收口径）──
            if prev_cc <= -3.0:
                stats["R-open"].append(pct(nxt_close, today_open))
                for tag, mul in (("R-dip1", 0.99), ("R-dip2", 0.98)):
                    limit = pc * mul
                    if today_low <= limit and not sealed_down:
                        stats[tag].append(pct(nxt_close, limit))
                    # 未成交=放弃（不计）
            # ── 首板族（T-1 涨停）──
            if prev_cc >= 9.8:
                if pct(today_open, pc) < 9.5:  # 一字开买不进剔除
                    stats["B-open"].append(pct(nxt_close, today_open))
                for tag, mul in (("B-dip2", 0.98), ("B-dip5", 0.95)):
                    limit = pc * mul
                    if today_low <= limit and not sealed_down:
                        stats[tag].append(pct(nxt_close, limit))
    return {k: {"n": len(v), "win%": round(sum(1 for x in v if x > 0) / len(v) * 100, 1),
                "avg%": round(sum(v) / len(v), 3)} for k, v in sorted(stats.items())}


if __name__ == "__main__":
    r = run()
    out = Path("/opt/data/fenjue/data/dipbuy_backtest.json")
    out.write_text(json.dumps(r, ensure_ascii=False, indent=2))
    print(json.dumps(r, ensure_ascii=False, indent=2))
