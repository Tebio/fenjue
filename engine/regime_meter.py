#!/usr/bin/env python3
"""engine/regime_meter.py — 市场情绪周期仪 (2026-09-06)

回答用户的问题：「科技利好没人理、妖股乱飞」到底是什么状态？能不能研究？
答案：个股妖股不可预测（彩票负期望），但【市场状态】是可测量可分类的。

四类状态（盘后全市场扫描判定）：
  主线期：涨停多 + 涨停集中在少数主线板块 + 主线板块强度灯亮 → 用焚诀/板块操作台
  妖股期：涨停不少但高度分散在小市值无关联票（无主线承接）→ 不打主线牌，要么不做要么纯接力纪律
  恐慌期：腿一=跌停潮(合计口径滚动分位≥q95) → 反弹窗口，分批建指数仓不要空仓躲；
          腿二=涨停枯竭+指数跌 → 趋势弱势，降进攻频率。**两腿建议相反，禁止共用一句**
          （2026-10-20 实测：腿一前瞻5日 +1.356% t=4.09、回撤更浅；腿二 -0.067% t=-0.84）
  平淡期：介于之间 → 观望为主

数据：腾讯全主板批量行情（~5400 票，90 个分批请求）。无未来函数（当日收盘数据）。

2026-10-20 改版（旧版见 regime_meter.py.bak）：
  1. 「恐慌期」腿一从绝对家数（跌停≥20）改为滚动 250 日分位（pct_limit_down≥PANIC_PCT_Q）。
     原因：旧 20 家建立在前复权 pct<=-9.8 的被低估序列上（低估 14.6%、漏判 143 天，
     见 research/K3_market_sense.md），且绝对家数跨年不可比。
     阈值 PANIC_PCT_Q 由 engine/reg_calibrate.py 数据标定（分位切档×前瞻5日指数收益/波动）。
     classify() 向后兼容：stats 无 pct_limit_down 字段时回退旧绝对规则（golden 测试不受影响）。
  2. 历史回溯路径（--hist）改用 data/emotion_series.jsonl 日序列（不复权精确限价）。
     ⚠️ 限制声明：实时路径依赖盘中 MCP/腾讯实时快照（盘中价、涨停池、市值补拉），
     无法历史复现；历史判定是「同日收盘」日频代理意义下的。
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
from engine.regime_core import (  # noqa: E402
    classify as _core_classify,
    classify_ex as _core_classify_ex,
    PANIC_PCT_Q,
    LEG2_LU_MAX,
    LEG2_IDX_PCT,
)

POOL_CODES_CACHE = ROOT / "data" / "main_board_codes.json"

# 恐慌腿一：滚动 250 日分位阈值（reg_calibrate.py 标定，见 research/K3_market_sense.md §阈值标定）
PANIC_PCT_Q = 0.95
SERIES_JSONL = ROOT / "data" / "emotion_series.jsonl"


def _is_st_name(name: str) -> bool:
    """ST/*ST/SST 名称判定（实时路径只有名称可用，无 ST 名单字段）。"""
    n = (name or "").upper().replace(" ", "")
    return ("ST" in n) or ("*ST" in n)


def count_limit_downs(rows, code_key=None) -> tuple[int, int]:
    """**合计口径**跌停计数 = 纯 10% 档 + 真 ST 5% 档。

    ⚠️ 必须与 emotion_series.jsonl 的 limit_down 列同口径（该列已改为不复权精确限价 +
    含真 ST 5% 档）。若分子只数纯 10% 而对合计窗口算分位，腿一会系统性偏钝——
    实测这种错配让分位近 250 日平均低估 21.8 个百分点。

    rows: 每项含 name 与 pct（或 change_percent）字段的 dict 可迭代。
    返回 (n_ld10, n_ld05)。
    """
    n10 = n05 = 0
    for r in rows:
        pct = r.get("pct")
        if pct is None:
            pct = r.get("change_percent")
        if pct is None:
            continue
        if pct <= -9.8:
            n10 += 1
        elif pct <= -4.75 and _is_st_name(r.get("name", "")):
            n05 += 1
    return n10, n05


def limit_down_percentile(today_ld: int, today: str) -> float | None:
    """今日跌停家数在日序列尾窗 250 日（含今日，虚拟 append）中的经验分位。

    序列文件滞后于今日属正常（cron 盘后补），此时分位基于截至序列末日的窗口，
    报告口径为「近似分位」；窗口非 None 值不足 120 时返回 None。"""
    if not SERIES_JSONL.exists():
        return None
    vals = []
    for line in SERIES_JSONL.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r["date"] != today:  # 同日行已由 cron 建过则剔除，避免双计
            vals.append(r["limit_down"])
    win = vals[-249:] + [today_ld]
    if len(win) < 120:
        return None
    return round(sum(1 for v in win if v <= today_ld) / len(win), 4)


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
    """四态判定——**委托 engine/regime_core.py**（2026-10-20 起唯一出处）。

    本函数只做 stats dict 到 regime_core.classify 的适配，不再自带阈值逻辑。
    见 regime_core 模块 docstring 的裁决记录（腿一分位 q95、腿二保 30、两腿建议相反）。
    """
    return _core_classify(
        limit_ups=stats["limit_ups"],
        index_pct=stats["index_pct"],
        small_cap_ratio=stats["small_cap_board_ratio"],
        top_sector_conc=stats["top_sector_concentration"],
        limit_downs_abs=stats.get("limit_downs"),
        pct_limit_down=stats.get("pct_limit_down"),
    )


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
        _ld10, _ld05 = count_limit_downs(live)
        limit_downs = _ld10 + _ld05  # 合计口径：纯10%档 + 真ST5%档（与分位窗口同口径）
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
        _ld10, _ld05 = count_limit_downs(quotes.values())
        limit_downs = _ld10 + _ld05  # 合计口径：纯10%档 + 真ST5%档（与分位窗口同口径）
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
             "pct_limit_down": limit_down_percentile(limit_downs, date.today().isoformat()),
             "top_sectors": sec_counter.most_common(5)}
    regime, advice = classify(stats)
    # 2026-10-20：腿标志与缺口标志一并上浮，写进 regime_log 供面板显示（stderr 告警
    # 在 cron 里没人看，见 AGENTS #329 遗留②/#330-B）。
    _v = _core_classify_ex(
        limit_ups=stats["limit_ups"], index_pct=stats["index_pct"],
        small_cap_ratio=stats["small_cap_board_ratio"],
        top_sector_conc=stats["top_sector_concentration"],
        limit_downs_abs=stats.get("limit_downs"),
        pct_limit_down=stats.get("pct_limit_down"),
    )
    return {"date": date.today().isoformat(), "regime": regime, "advice": advice,
            "gap": _v["gap"], "basis": _v["basis"], "leg1": _v["leg1"], "leg2": _v["leg2"],
            "stats": stats, "boards": boards}  # 2026-09-07: 不再截断40只——截断导致连板梯队漏票（中国出版2板被切掉）


def hist_scan(start: str = "2019-01-01", end: str = "9999-12-31") -> list[dict]:
    """历史回溯：读 emotion_series.jsonl 日序列，逐日判恐慌/非恐慌（新旧规则都给）。

    ⚠️ 实时路径不可历史复现——此处为「同日收盘」日频代理。
    主线/妖股腿需小市值占比与板块集中度，日序列没有这两个维度，
    历史路径只判「恐慌 vs 非恐慌」（这正是 2026-10-20 改版涉及的判定）。"""
    idx = {r["date"]: float(r["close"]) for r in json.loads((ROOT / "data" / "index_sh000001.json").read_text())}
    out = []
    prev_idx = None
    for line in SERIES_JSONL.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        d = r["date"]
        if d < start:
            continue
        if d > end:
            break
        idx_pct = None
        if d in idx:
            idx_pct = round((idx[d] / prev_idx - 1) * 100, 2) if prev_idx is not None else None
            prev_idx = idx[d]
        leg2 = (r["limit_up"] < 30) and (idx_pct is not None and idx_pct < -1.0)
        pct_ld = r.get("pct_limit_down")
        new_panic = (pct_ld is not None and pct_ld >= PANIC_PCT_Q) or leg2
        old_panic = (r["limit_down"] >= 20) or leg2
        out.append({"date": d, "limit_up": r["limit_up"], "limit_down": r["limit_down"],
                    "pct_limit_down": pct_ld, "index_pct": idx_pct,
                    "panic_new": new_panic, "panic_old": old_panic})
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--hist", action="store_true", help="历史回溯模式（日序列，不碰实时接口）")
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="9999-12-31")
    ap.add_argument("--tail", type=int, default=15)
    args = ap.parse_args()
    if args.hist:
        rows = hist_scan(args.start, args.end)
        diff = [r for r in rows if r["panic_new"] != r["panic_old"]]
        only_new = sum(1 for r in diff if r["panic_new"])
        only_old = sum(1 for r in diff if r["panic_old"])
        print(f"历史恐慌判定 {rows[0]['date']}..{rows[-1]['date']} 共 {len(rows)} 天 | "
              f"新规则(分位≥{PANIC_PCT_Q}) {sum(r['panic_new'] for r in rows)} 天 / "
              f"旧规则(≥20家) {sum(r['panic_old'] for r in rows)} 天 | "
              f"改判 {len(diff)} 天（仅新 {only_new} / 仅旧 {only_old}）")
        print("⚠️ 实时路径不可历史复现；主线/妖股腿日序列无小市值/集中度维度，此处只判恐慌。")
        hlog = ROOT / "data" / "regime_hist.jsonl"
        with open(hlog, "w") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        for r in rows[-args.tail:]:
            pn = "恐慌" if r["panic_new"] else ("恐慌*" if r["panic_old"] else "  -  ")
            print(f"{r['date']} {pn} 涨停 {r['limit_up']:3d} 跌停 {r['limit_down']:3d} "
                  f"分位 {r['pct_limit_down'] if r['pct_limit_down'] is not None else '-':>5} 指数 {r['index_pct']}")
        raise SystemExit(0)
    r = scan()
    # DATA-07 熔断（R1-②展示型降级）：周期仪照跑照写（用户要看），
    # 但命中阻断依赖时 regime_log 条目带 data_stale:true + 依赖项清单。
    _brk = {"data_stale": False, "stale_datasets": [], "reason": ""}
    try:
        from engine import breaker
        _brk = breaker.stale_mark("周期仪")
    except Exception:
        pass
    log = ROOT / "data" / "regime_log.jsonl"
    entry_d = {"date": r["date"], "regime": r["regime"], "advice": r.get("advice"),
               "gap": r.get("gap"), "basis": r.get("basis"),
               "leg1": r.get("leg1"), "leg2": r.get("leg2"),
               "stats": r["stats"], "boards": r["boards"]}
    if _brk.get("data_stale"):
        entry_d["data_stale"] = True
        entry_d["stale_datasets"] = _brk["stale_datasets"]
    entry = json.dumps(entry_d, ensure_ascii=False)
    lines = [l for l in log.read_text().splitlines() if l.strip()] if log.exists() else []
    if lines and json.loads(lines[-1])["date"] == r["date"]:
        lines[-1] = entry  # 同日重跑=覆盖，不堆重复行（打板接力按行序读，重复行会算出假昨日）
    else:
        lines.append(entry)
    log.write_text("\n".join(lines) + "\n")
    if _brk.get("data_stale"):
        print(f"🚨 数据断供降级（DATA-07）：{'、'.join(_brk['stale_datasets'])} —— 本次判定按陈旧依赖产出，见 regime_log 条目标记")
    s = r["stats"]
    print(f"情绪周期仪 {r['date']}: 【{r['regime']}】")
    print(f"  涨停 {s['limit_ups']} 家 | 小市值(<100亿)占比 {s['small_cap_board_ratio']:.0%} | "
          f"最大板块集中度 {s['top_sector_concentration']:.0%} | 上证 {s['index_pct']:+.2f}%")
    print(f"  涨停板块分布: {s['top_sectors']}")
    print(f"  → {r['advice']}")
