#!/usr/bin/env python3
"""engine/doubler.py — 翻倍股早期信号扫描 + 首板基率统计 (2026-09-06)

科学诚实声明：学术界 MAX/彩票因子研究（Bali et al.）证明彩票股整体负期望——
没有任何方法能「预测」哪只票翻倍。本模块不预测，只做两件事：
  1. 基率测量：用 300 只分层样本 2019-2026 全历史，测「首板」（60日内首次涨停）的
     T+1/T+5 真实表现——用数据说话，不讲技术面玄学
  2. 早期信号扫描：翻倍股复盘（利通电子/百合花）的共性是【板块主线强 + 小中市值 +
     首板启动 + 后续资金接力确认】。扫描器只负责把「今天谁首板了、在哪个板块、市值多大」
     摆出来，后续必须过人工验证清单（业务真实/订单/业绩/证伪风险）才升级观察。
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
KCACHE = ROOT / "data" / "big_kcache"


def first_board_events(ks: list[dict], lookback: int = 60) -> list[int]:
    """首板事件：当日收盘涨幅≥9.8%（≈涨停）且前 lookback 日内无涨停。返回 K 线下标。"""
    out = []
    closes = [float(k["close"]) for k in ks]
    n = len(ks)
    last_board = -10**9
    for j in range(1, n - 5):
        if closes[j - 1] <= 0:
            continue
        pct = (closes[j] - closes[j - 1]) / closes[j - 1] * 100
        if pct >= 9.8 and j - last_board > lookback:
            out.append(j)
            last_board = j
        elif pct >= 9.8:
            last_board = j
    return out


def base_rate() -> dict:
    """300 只分层样本 2019-2026：首板后的 T+1（开→收）、T+1（收→收）、T+5 收益。"""
    stats = defaultdict(list)
    files = sorted(KCACHE.glob("*.json"))
    for f in files:
        if f.stem == "000001":
            continue
        ks = json.loads(f.read_text())
        if len(ks) < 120:
            continue
        for j in first_board_events(ks):
            buy_open = float(ks[j + 1]["open"])
            if buy_open <= 0:
                continue
            # 一字板买不进：开盘即涨停(开盘涨幅≥9.5%)剔除
            prev_close = float(ks[j]["close"])
            if (buy_open - prev_close) / prev_close * 100 >= 9.5:
                continue
            stats["T1_open_to_close"].append((float(ks[j + 1]["close"]) - buy_open) / buy_open * 100)
            stats["T1_close_to_close"].append((float(ks[j + 1]["close"]) - prev_close) / prev_close * 100)
            stats["T5_close"].append((float(ks[j + 5]["close"]) - prev_close) / prev_close * 100)
    return {k: {"n": len(v), "win%": round(sum(1 for x in v if x > 0) / len(v) * 100, 1),
                "avg%": round(sum(v) / len(v), 2)} for k, v in stats.items()}


def scan_today(universe: dict[str, dict], quotes: dict[str, dict], sector_lamps: dict[str, dict]) -> list[dict]:
    """当日早期信号：首板/大阳 + 中小市值 + 板块灯。universe: {code: {name, sector}}"""
    out = []
    for code, meta in universe.items():
        q = quotes.get(code)
        if not q:
            continue
        cap = q.get("mktcap_yi") or 0
        if q["pct"] >= 9.8:
            sig = "首板/涨停"
        elif q["pct"] >= 6 and (q.get("turnover") or 0) >= 5:
            sig = "放量大阳"
        else:
            continue
        if not (20 <= cap <= 400):  # 翻倍股几乎都是中小市值起步（利通~60亿、百合花227亿）
            continue
        lamp = (sector_lamps.get(meta.get("sector", "")) or {}).get("lamp", "")
        out.append({"code": code, "name": q["name"], "sector": meta.get("sector", ""),
                    "pct": q["pct"], "cap_yi": cap, "signal": sig, "sector_lamp": lamp})
    out.sort(key=lambda x: x["pct"], reverse=True)
    return out


CHECKLIST = """人工验证清单（缺一不可，否则只是情绪票）：
  ① 业务真实：公司公告/财报里有没有这项业务？收入占比多少？
  ② 订单/业绩可验证：合同负债、中标公告、业绩预告——拿原文，不听二手
  ③ 板块是真主线：板块≥3只联动涨停、有产业新闻催化（财联社原文）
  ④ 证伪风险：概念被公司否认过没有？（百合花的光刻胶概念曾被证伪后照涨——知道自己在炒什么）
  ⑤ 接力结构：首板后 2-3 日是否开板有承接（利通 4-29/30 量比 2.3/3.1 = 放量换手接力）
"""

if __name__ == "__main__":
    print("== 首板基率（300 只分层样本 2019-2026，剔除一字板买不进）==")
    r = base_rate()
    print(json.dumps(r, ensure_ascii=False, indent=2))
