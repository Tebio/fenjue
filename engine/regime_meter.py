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
            # K3修（2026-09-13 夜）：缓存只信 code 名单，价格字段全部作废——
            # 实锤事故：9/11 周期仪吃到 9/10 缓存快照，boards 整天复制前日
            # （水发燃气 9/11 实际 -4.2% 被记成涨停 9.989），regime_log 污染。
            return [{**s, "change_percent": None, "price": None} for s in d["stocks"]]
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
        r = rpc("tools/call", {"name": "get_main_board_pool", "arguments": {"refresh": True, "limit": 5000}}, 2)
        d = json.loads(r["result"]["content"][0]["text"])
        stocks = d.get("stocks", [])
    except Exception:
        stocks = []
    if stocks:
        POOL_CODES_CACHE.write_text(json.dumps({"ts": time.time(), "stocks": stocks}))
        return stocks
    # 回退：历史池并集（无实时价，meter 走腾讯报价）
    codes = set()
    for f in sorted(ROOT.glob("pool_20*.json")):
        for r in json.loads(f.read_text()).get("results", []):
            c = str(r["code"]).zfill(6)
            if c.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
                codes.add(c)
    return [{"code": c, "name": "", "change_percent": None} for c in sorted(codes)]


def classify(stats: dict) -> tuple[str, str]:
    n_board = stats["limit_ups"]
    small_ratio = stats["small_cap_board_ratio"]
    chain_conc = stats["top_sector_concentration"]
    idx_pct = stats["index_pct"]
    # 2026-09-05 标定（回验数据）：6月主线=链集中27-30%+涨停86-129；8底妖股=小市值61-88%+链分散<22%
    if n_board >= 60 and chain_conc >= 0.22:
        return "主线期", "涨停集中在主线产业链——用板块操作台/焚诀主线打法（反转开盘买、追高只允许尾盘买）"
    if n_board >= 40 and small_ratio >= 0.65 and chain_conc < 0.22:
        return "妖股期", "涨停全是小市值散票无主线——默认不参与；个股不可预测"
    if stats.get("limit_downs", 0) >= 20 or (n_board < 30 and idx_pct < -1.0):
        return "恐慌期", "跌停潮或涨停枯竭+指数大跌——空仓或高股息防御"
    return "平淡期", "无量能无主线——观望，红利宇宙建仓窗口"


def scan() -> dict:
    clear_proxy()
    stocks = main_board_pool()
    live = [s for s in stocks if s.get("change_percent") is not None]
    # 2026-09-20 完整性闸门：MCP 池退化实锤（limit=5000 只回 233 行，9/16-18 涨停数 43/17/28
    # vs 真实 82/47/75，徽标误报平淡期一周）。池行数不足 2500 = 明显不完整，直接转腾讯全量。
    # 新鲜度抽查只管「过期」，不管「缺页」——两个都要查。
    if live and len(live) < 2500:
        print(f"[FALLBACK] MCP池完整性不足（{len(live)}行<2500），转腾讯全量路径")
        live = []
    if live:
        # K3修（2026-09-13 夜）：live 路径新鲜度抽查——MCP 池可能服务端滞后返回昨日快照。
        # 抽最多3只边缘票（|pct|∈[3,9]）与腾讯实时对照，偏差>1pp 即判定整池过期，转腾讯路径。
        import random as _rnd
        edge = [s for s in live if 3 <= abs(s["change_percent"]) <= 9][:3]
        if edge:
            probe = tencent_quotes([str(s["code"]).zfill(6) for s in edge])
            stale = 0
            for s in edge:
                c = str(s["code"]).zfill(6)
                q = probe.get(c)
                if q and abs(q["pct"] - s["change_percent"]) > 1.0:
                    stale += 1
            if stale >= 2:
                print(f"[SILENT] MCP池新鲜度抽查失败（{stale}/{len(edge)} 偏差>1pp），转腾讯全量路径")
                live = []
    if live:
        # MCP 全市场实时：直接统计涨停；市值只对涨停票补拉腾讯（几十只，快）
        boards = [{"code": str(s["code"]).zfill(6), "name": s.get("name", ""),
                   "pct": s["change_percent"]} for s in live if s["change_percent"] >= 9.8]
        limit_downs = sum(1 for s in live if s["change_percent"] <= -9.8)
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
        boards = [{"code": c, "name": q["name"], "cap": q.get("mktcap_yi") or 0, "pct": q.get("pct")}
                  for c, q in quotes.items() if q["pct"] >= 9.8]
        limit_downs = sum(1 for q in quotes.values() if q["pct"] <= -9.8)
        idx_pct = 0.0
    small = sum(1 for b in boards if b["cap"] < 100)
    # 行业标签：baostock 全市场映射（5546 只，去代码前缀）+ 池内 sector 补充；链级归并（AI电子链）
    import re as _re
    sector_of = {}
    imap = ROOT / "data" / "industry_map.json"
    if imap.exists():
        for c, v in json.loads(imap.read_text()).items():
            sector_of[c] = _re.sub(r"^[A-Z]\d+", "", v.get("industry", ""))
    for f in sorted(ROOT.glob("pool_20*.json")):
        for r in json.loads(f.read_text()).get("results", []):
            c = str(r["code"]).zfill(6)
            if r.get("sector"):
                sector_of[c] = r["sector"]
    def _chain(sec):
        if any(k in sec for k in ("计算机", "通信", "电子", "光学", "元件", "半导体", "消费电子", "软件")):
            return "AI电子链"
        return sec
    sec_counter = Counter(_chain(sector_of.get(b["code"], "其他")) for b in boards)
    known = {k: v for k, v in sec_counter.items() if k != "其他"}
    top_conc = (max(known.values()) / len(boards)) if known and boards else 0
    idx_pct = 0.0
    try:
        idx = kline_sina("sh000001", 2)
        idx_pct = round((float(idx[-1]["close"]) / float(idx[-2]["close"]) - 1) * 100, 2)
    except Exception:
        pass
    stats = {"limit_ups": len(boards), "limit_downs": limit_downs,
             "small_cap_board_ratio": round(small / len(boards), 2) if boards else 0,
             "top_sector_concentration": round(top_conc, 2), "index_pct": idx_pct,
             "top_sectors": sec_counter.most_common(5)}
    regime, advice = classify(stats)
    return {"date": date.today().isoformat(), "regime": regime, "advice": advice,
            "stats": stats, "boards": boards}  # 2026-09-07: 不再截断40只——截断导致连板梯队漏票（中国出版2板被切掉）


if __name__ == "__main__":
    r = scan()
    log = ROOT / "data" / "regime_log.jsonl"
    entry = json.dumps({"date": r["date"], "regime": r["regime"], "stats": r["stats"],
                        "boards": r["boards"]}, ensure_ascii=False)
    lines = [l for l in log.read_text().splitlines() if l.strip()] if log.exists() else []
    if lines and json.loads(lines[-1])["date"] == r["date"]:
        lines[-1] = entry  # 同日重跑=覆盖，不堆重复行（打板接力按行序读，重复行会算出假昨日）
    else:
        lines.append(entry)
    log.write_text("\n".join(lines) + "\n")
    s = r["stats"]
    print(f"情绪周期仪 {r['date']}: 【{r['regime']}】")
    print(f"  涨停 {s['limit_ups']} 家 | 小市值(<100亿)占比 {s['small_cap_board_ratio']:.0%} | "
          f"最大板块集中度 {s['top_sector_concentration']:.0%} | 上证 {s['index_pct']:+.2f}%")
    print(f"  涨停板块分布: {s['top_sectors']}")
    print(f"  → {r['advice']}")
