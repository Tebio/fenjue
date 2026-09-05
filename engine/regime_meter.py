#!/usr/bin/env python3
"""engine/regime_meter.py — 市场情绪周期仪 (2026-09-06)

回答用户的问题：「科技利好没人理、妖股乱飞」到底是什么状态？能不能研究？
答案：个股妖股不可预测（彩票负期望），但【市场状态】是可测量可分类的。

四类状态（盘后全市场扫描判定）：
  主线期：涨停多 + 涨停集中在少数主线板块 + 主线板块强度灯亮 → 用焚诀/板块操作台
  妖股期：涨停不少但高度分散在小市值无关联票（无主线承接）→ 不打主线牌，要么不做要么纯接力纪律
  恐慌期：涨停稀少 + 跌停多 + 指数弱 → 空仓/只做高股息防御
  平淡期：介于之间 → 观望为主

数据：腾讯全主板批量行情（~5400 票，90 个分批请求）。无未来函数（当日收盘数据）。
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
sys.path.insert(0, str(ROOT))
from engine.console import tencent_quotes, clear_proxy, kline_sina  # noqa: E402

POOL_CODES_CACHE = ROOT / "data" / "main_board_codes.json"


def main_board_pool() -> list[dict]:
    """全主板实时池：优先 a-stock MCP（3194 票，含价/涨幅/成交额）；挂了回退历史池并集。"""
    import time
    import urllib.request
    if POOL_CODES_CACHE.exists():
        d = json.loads(POOL_CODES_CACHE.read_text())
        if time.time() - d.get("ts", 0) < 86400 and d.get("stocks"):
            return d["stocks"]
    stocks = []
    try:
        def rpc(method, params, rid):
            req = urllib.request.Request(
                "http://localhost:8767/mcp",
                data=json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}).encode(),
                headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
            raw = urllib.request.urlopen(req, timeout=60).read().decode()
            for line in raw.splitlines():
                if line.startswith("data:"):
                    return json.loads(line[5:])
            return json.loads(raw)
        rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "fenjue", "version": "1"}}, 1)
        r = rpc("tools/call", {"name": "get_main_board_pool", "arguments": {}}, 2)
        d = json.loads(r["result"]["content"][0]["text"])
        stocks = d.get("stocks", [])
    except Exception:
        stocks = []
    if stocks:
        POOL_CODES_CACHE.write_text(json.dumps({"ts": time.time(), "stocks": stocks}))
        return stocks
    # 回退：历史池并集（无实时价，meter 走腾讯报价）
    codes = set()
    for f in sorted(ROOT.glob("pool_2026*.json")):
        for r in json.loads(f.read_text()).get("results", []):
            c = str(r["code"]).zfill(6)
            if c.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
                codes.add(c)
    return [{"code": c, "name": "", "change_percent": None} for c in sorted(codes)]


def classify(stats: dict) -> tuple[str, str]:
    n_board = stats["limit_ups"]
    small_ratio = stats["small_cap_board_ratio"]
    top_sector_conc = stats["top_sector_concentration"]
    idx_pct = stats["index_pct"]
    if n_board >= 50 and top_sector_conc >= 0.35 and idx_pct > -0.5:
        return "主线期", "涨停集中在主线板块且指数不弱——用板块操作台/焚诀主线打法"
    if n_board >= 40 and small_ratio >= 0.6 and top_sector_conc < 0.25:
        return "妖股期", "涨停高度分散在无关联小票=无主线接力情绪票——个股不可预测，只认纪律不认研究"
    if n_board < 25 and idx_pct < -0.5:
        return "恐慌期", "涨停稀少+指数弱——空仓或高股息防御"
    return "平淡期", "无量能无主线——观望，等信号"


def scan() -> dict:
    clear_proxy()
    stocks = main_board_pool()
    live = [s for s in stocks if s.get("change_percent") is not None]
    if live:
        # MCP 全市场实时：直接统计涨停；市值只对涨停票补拉腾讯（几十只，快）
        boards = [{"code": str(s["code"]).zfill(6), "name": s.get("name", ""),
                   "pct": s["change_percent"]} for s in live if s["change_percent"] >= 9.8]
        caps = tencent_quotes([b["code"] for b in boards]) if boards else {}
        for b in boards:
            b["cap"] = (caps.get(b["code"]) or {}).get("mktcap_yi") or 0
        idx_pct = 0.0
        try:
            idx = kline_sina("sh000001", 2)
            idx_pct = round((float(idx[-1]["close"]) / float(idx[-2]["close"]) - 1) * 100, 2)
        except Exception:
            pass
    else:
        # 回退路径：腾讯批量
        codes = [str(s["code"]).zfill(6) for s in stocks]
        quotes = tencent_quotes(codes)
        boards = [{"code": c, "name": q["name"], "cap": q.get("mktcap_yi") or 0}
                  for c, q in quotes.items() if q["pct"] >= 9.8]
        idx_pct = 0.0
    small = sum(1 for b in boards if b["cap"] < 100)
    # 板块集中度需要行业标签——池内票有 sector，池外归为「其他」
    sector_of = {}
    for f in sorted(ROOT.glob("pool_2026*.json")):
        for r in json.loads(f.read_text()).get("results", []):
            sector_of[str(r["code"]).zfill(6)] = r.get("sector", "")
    sec_counter = Counter(sector_of.get(b["code"], "其他") for b in boards)
    # 「其他」= 池外无行业标签的散票，不参与集中度——妖股期的特征恰恰是涨停全在「其他」
    known = {k: v for k, v in sec_counter.items() if k != "其他"}
    top_conc = (max(known.values()) / len(boards)) if known and boards else 0
    idx_pct = 0.0
    try:
        idx = kline_sina("sh000001", 2)
        idx_pct = round((float(idx[-1]["close"]) / float(idx[-2]["close"]) - 1) * 100, 2)
    except Exception:
        pass
    stats = {"limit_ups": len(boards), "small_cap_board_ratio": round(small / len(boards), 2) if boards else 0,
             "top_sector_concentration": round(top_conc, 2), "index_pct": idx_pct,
             "top_sectors": sec_counter.most_common(5)}
    regime, advice = classify(stats)
    return {"date": date.today().isoformat(), "regime": regime, "advice": advice,
            "stats": stats, "boards": boards[:40]}


if __name__ == "__main__":
    r = scan()
    log = ROOT / "data" / "regime_log.jsonl"
    with log.open("a") as f:
        f.write(json.dumps({k: r[k] for k in ("date", "regime", "stats")}, ensure_ascii=False) + "\n")
    s = r["stats"]
    print(f"情绪周期仪 {r['date']}: 【{r['regime']}】")
    print(f"  涨停 {s['limit_ups']} 家 | 小市值(<100亿)占比 {s['small_cap_board_ratio']:.0%} | "
          f"最大板块集中度 {s['top_sector_concentration']:.0%} | 上证 {s['index_pct']:+.2f}%")
    print(f"  涨停板块分布: {s['top_sectors']}")
    print(f"  → {r['advice']}")
