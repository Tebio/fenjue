#!/usr/bin/env python3
"""engine/console.py — 板块操作台 (2026-09-06)

灵感来源：炒股群银行股大佬的「操作台」（股息率锚定价格带 + 明日委托单）。
本模块把它工程化、通用化：
  1. 价值锚价格带：银行=股息率阈值反推（实测反推验证：买入4.5%/卖出4.0%/清仓3.0%）；
     其他板块=PB 分位锚（低分位买/高分位卖）
  2. 板块强度灯：决定「什么时候跑去银行/离开银行」——成分股上涨家数比、均涨幅、
     均换手、银行ETF(512800) 20日相对上证强度
  3. 明日委托单：买入线/加仓-4%/-8%阶梯/卖出触发/卖出线/清仓线，直接可抄挂单
  4. 基本面质量表：config/bank_fundamentals.json（不良率/拨备/增速，财报季人工或AI更新）

冻结纪律合规：全新独立模块，不触碰 ScoringEngine/权重/公式。
数据：腾讯 qt.gtimg.cn（价/PE/PB/市值/换手）+ akshare 分红 + 新浪K线（ETF）。
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
FUND_FILE = ROOT / "config" / "bank_fundamentals.json"
DIV_CACHE = ROOT / "data" / "dividend_cache.json"

# 大佬实测反推的锚（齐鲁/青岛双样本验证）：买入4.5% / 卖出4.0% / 清仓3.0%
YIELD_ANCHORS = {"buy": 4.5, "sell": 4.0, "clear": 3.0}
LADDER = (-0.04, -0.08)  # 加仓阶梯

BANKS = [  # 大佬清单 15 行 + 代码
    ("601665", "齐鲁银行", "核心"), ("002948", "青岛银行", "核心"), ("002142", "宁波银行", "次核心"),
    ("601838", "成都银行", "次核心"), ("601963", "重庆银行", "次核心"), ("601939", "建设银行", "次核心"),
    ("600926", "杭州银行", "次核心"), ("601229", "上海银行", "再次核心"), ("601398", "工商银行", "再次核心"),
    ("601288", "农业银行", "再次核心"), ("601988", "中国银行", "再次核心"), ("601328", "交通银行", "再次核心"),
    ("601077", "渝农商行", "观察"), ("600919", "江苏银行", "观察"), ("601009", "南京银行", "观察"),
]

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def _get(url: str, gbk: bool = False, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                               "Referer": "https://finance.sina.com.cn"})
    raw = urllib.request.urlopen(req, context=_ctx, timeout=timeout).read()
    return raw.decode("gb18030" if gbk else "utf-8", errors="ignore")


def clear_proxy() -> None:
    for k in list(os.environ):
        if "proxy" in k.lower():
            os.environ.pop(k, None)


# ── 数据层 ──────────────────────────────────────────────
def tencent_quotes(codes: list[str]) -> dict[str, dict]:
    """腾讯批量行情。字段(1基): 3价 33涨幅% 47 PE(动) 46 PB 45 总市值亿 47? — 实测校准如下。"""
    out = {}
    for i in range(0, len(codes), 60):
        batch = [("sh" if c.startswith("6") else "sz") + c for c in codes[i:i + 60]]
        text = _get("https://qt.gtimg.cn/q=" + ",".join(batch), gbk=True)
        for line in text.splitlines():
            if '="' not in line:
                continue
            left, rawv = line.split('="', 1)
            code = left.rsplit("_", 1)[-1][-6:]
            f = rawv.rstrip('";').split("~")
            if len(f) < 50 or not f[1]:
                continue
            try:
                out[code] = {
                    "name": f[1], "price": float(f[3]), "pct": float(f[32]),
                    "pe": float(f[39]) if f[39] else None,      # 实测 line48=7.84=PE
                    "pb": float(f[45]) if f[45] else None,      # 实测 line47=0.85=PB
                    "mktcap_yi": float(f[44]) if f[44] else None,
                    "turnover": float(f[38]) if f[38] else None,
                }
            except (ValueError, IndexError):
                continue
    return out


def dividend_ttm(code: str) -> float | None:
    """每股分红 TTM（akshare 东财分红明细，每10股派息→每股；磁盘缓存 7 天）。"""
    cache = json.loads(DIV_CACHE.read_text()) if DIV_CACHE.exists() else {}
    ent = cache.get(code)
    import time
    if ent and time.time() - ent.get("ts", 0) < 7 * 86400:
        return ent["dps"]
    sys.path.insert(0, "/opt/data/python-libs")
    try:
        import akshare as ak
        df = ak.stock_history_dividend_detail(symbol=code, indicator="分红")
        df = df[df["进度"] == "实施"].copy()
        df["除权除息日"] = __import__("pandas").to_datetime(df["除权除息日"])
        cutoff = __import__("pandas").Timestamp.now() - __import__("pandas").Timedelta(days=365)
        recent = df[df["除权除息日"] >= cutoff]
        dps = round(float(recent["派息"].sum()) / 10, 4) if len(recent) else None
        cache[code] = {"dps": dps, "ts": time.time()}
        DIV_CACHE.write_text(json.dumps(cache))
        return dps
    except Exception:
        return ent["dps"] if ent else None


def kline_sina(symbol: str, n: int = 90) -> list[dict]:
    url = ("http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={n}")
    return json.loads(_get(url))


# ── 锚定数学 ──────────────────────────────────────────────
def bands_from_dividend(dps: float) -> dict:
    return {"buy": round(dps / (YIELD_ANCHORS["buy"] / 100), 2),
            "sell": round(dps / (YIELD_ANCHORS["sell"] / 100), 2),
            "clear": round(dps / (YIELD_ANCHORS["clear"] / 100), 2)}


def zone_of(price: float, bands: dict) -> tuple[str, str]:
    if price <= bands["buy"]:
        return "买入区", "可建仓/加仓"
    if price <= bands["sell"]:
        return "持有区", "持有不动"
    if price < bands["clear"]:
        return "卖出区", "减仓不清仓"
    return "清仓区", "清仓离场"


def ladder(bands: dict) -> dict:
    return {"买入线": bands["buy"],
            "加仓-4%": round(bands["buy"] * (1 + LADDER[0]), 2),
            "加仓-8%": round(bands["buy"] * (1 + LADDER[1]), 2),
            "卖出线": bands["sell"], "清仓线": bands["clear"]}


# ── 板块强度灯 ──────────────────────────────────────────────
def sector_strength(codes: list[str], quotes: dict[str, dict], etf: str | None = None) -> dict:
    """成分股横截面：上涨家数比/均涨幅/均换手 + 板块ETF 20日相对上证强度（有配置才算）。"""
    qs = [quotes[c] for c in codes if c in quotes]
    up_ratio = sum(1 for q in qs if q["pct"] > 0) / len(qs) * 100 if qs else 0
    avg_pct = sum(q["pct"] for q in qs) / len(qs) if qs else 0
    avg_turn = sum(q["turnover"] or 0 for q in qs) / len(qs) if qs else 0
    rs20 = None
    if etf:
        try:
            etfk = kline_sina(etf)
            idx = kline_sina("sh000001")
            if len(etfk) >= 21 and len(idx) >= 21:
                e20 = float(etfk[-1]["close"]) / float(etfk[-21]["close"]) - 1
                i20 = float(idx[-1]["close"]) / float(idx[-21]["close"]) - 1
                rs20 = round((e20 - i20) * 100, 2)
        except Exception:
            pass
    # 强度灯：涨家比>70% 且 均涨幅>1% 且 RS20>0 → 强势（跑去银行）
    strong = up_ratio >= 70 and avg_pct >= 1.0 and (rs20 is None or rs20 > 0)
    return {"up_ratio": round(up_ratio, 1), "avg_pct": round(avg_pct, 2),
            "avg_turnover": round(avg_turn, 2), "rs20_vs_index": rs20,
            "lamp": "🟢强势可入" if strong else ("🟡中性观察" if avg_pct > 0 else "🔴弱势回避")}


# ── 报告 ──────────────────────────────────────────────
def build_console() -> dict:
    clear_proxy()
    codes = [c for c, _, _ in BANKS]
    quotes = tencent_quotes(codes)
    funds = json.loads(FUND_FILE.read_text()) if FUND_FILE.exists() else {}
    rows = []
    for code, name, tier in BANKS:
        q = quotes.get(code)
        if not q:
            continue
        dps = dividend_ttm(code)
        bands = bands_from_dividend(dps) if dps else None
        yld = round(dps / q["price"] * 100, 2) if dps else None
        zone, action = zone_of(q["price"], bands) if bands else ("无分红数据", "—")
        row = {"code": code, "name": name, "tier": tier, "price": q["price"], "pct": q["pct"],
               "pe": q["pe"], "pb": q["pb"], "yield": yld, "mktcap": q["mktcap_yi"],
               "zone": zone, "action": action}
        if bands:
            row["bands"] = bands
            row["ladder"] = ladder(bands)
            row["dist_to_clear%"] = round((bands["clear"] / q["price"] - 1) * 100, 1)
            row["dist_to_buy%"] = round((bands["buy"] / q["price"] - 1) * 100, 1)
        f = funds.get(code)
        if f:
            row["fundamentals"] = f
        rows.append(row)
    strength = sector_strength(codes, quotes)
    return {"strength": strength, "rows": rows}


def render_text(console: dict) -> str:
    s = console["strength"]
    lines = [f"🏦 银行板块操作台 | 强度灯 {s['lamp']}（上涨家数 {s['up_ratio']}% 均涨幅 {s['avg_pct']:+.2f}% RS20 {s['rs20_vs_index']}）",
             ""]
    cur_tier = None
    for r in console["rows"]:
        if r["tier"] != cur_tier:
            cur_tier = r["tier"]
            lines.append(f"── {cur_tier} ──")
        if "bands" not in r:
            lines.append(f"{r['name']}({r['code']}) {r['price']} 无分红数据")
            continue
        b, l = r["bands"], r["ladder"]
        lines.append(
            f"{r['name']}({r['code']}) {r['price']} ({r['pct']:+.1f}%) 息率{r['yield']}% | "
            f"{r['zone']}·{r['action']} | 买≤{b['buy']} 卖{b['sell']} 清≥{b['clear']} | "
            f"距清仓{r['dist_to_clear%']:+.1f}% 距买入{r['dist_to_buy%']:+.1f}%")
    lines.append("")
    lines.append("── 明日委托单（价格线不随日内波动，分红/财报更新后调整）──")
    for r in console["rows"]:
        if "ladder" not in r or r["zone"] in ("清仓区",):
            continue
        l = r["ladder"]
        op = {"买入区": "加仓", "持有区": "持有", "卖出区": "减仓"}[r["zone"]]
        lines.append(f"{r['name']} [{op}] 买{l['买入线']}/加{l['加仓-4%']}/{l['加仓-8%']} 卖{l['卖出线']} 清{l['清仓线']}")
    return "\n".join(lines)


if __name__ == "__main__":
    console = build_console()
    out = ROOT / "data" / "console_banks.json"
    out.write_text(json.dumps(console, ensure_ascii=False, indent=2))
    print(render_text(console))
    print(f"\n写入 {out}")


# ── 通用板块扩展（v1：价格分位锚，影子假设待验证） ──────────────
def bands_from_price_pct(code: str, band_cfg: dict, years: int = 5) -> dict | None:
    """价格分位锚（BVPS 缓变的 v1 近似）：5 年日K价格分位 → 买/卖/清线。"""
    try:
        ks = kline_sina(("sh" if code.startswith("6") else "sz") + code, n=years * 250)
    except Exception:
        return None
    if len(ks) < 250:
        return None
    prices = sorted(float(k["close"]) for k in ks)
    n = len(prices)
    def at(pct):
        return round(prices[min(n - 1, int(n * pct / 100))], 2)
    return {"buy": at(band_cfg["buy_pct"]), "sell": at(band_cfg["sell_pct"]),
            "clear": at(band_cfg["clear_pct"])}


def build_generic_sector(sector: str, cfg: dict) -> dict:
    clear_proxy()
    quotes = tencent_quotes(cfg["codes"])
    rows = []
    for code in cfg["codes"]:
        q = quotes.get(code)
        if not q:
            continue
        if cfg["anchor"] == "yield":
            dps = dividend_ttm(code)
            bands = bands_from_dividend(dps) if dps else None
            yld = round(dps / q["price"] * 100, 2) if dps else None
        else:
            bands = bands_from_price_pct(code, cfg["bands"])
            yld = None
        zone, action = zone_of(q["price"], bands) if bands else ("无数据", "—")
        row = {"code": code, "name": q["name"], "price": q["price"], "pct": q["pct"],
               "pe": q["pe"], "pb": q["pb"], "yield": yld, "zone": zone, "action": action}
        if cfg["anchor"] != "yield":
            # 热点/成长板块的正确锚不是估值带，是回测验证过的反转买点（8年 50.2%/+0.31%）
            row["reversal_watch"] = ("⚡今日跌≥3%·明日开盘反转买点候选" if q["pct"] <= -3
                                     else "反转买点触发条件：单日收跌≥3%")
        if bands:
            row["bands"] = bands
            row["ladder"] = ladder(bands)
        rows.append(row)
    strength = sector_strength(cfg["codes"], quotes, etf=cfg.get("etf"))
    return {"sector": sector, "strength": strength, "rows": rows}


def render_sector_text(console: dict) -> str:
    s = console["strength"]
    lines = [f"📊 {console['sector']}操作台 | 强度灯 {s['lamp']}（上涨家数 {s['up_ratio']}% 均涨幅 {s['avg_pct']:+.2f}% RS20 {s['rs20_vs_index']}）"]
    for r in console["rows"]:
        if "bands" not in r:
            lines.append(f"{r['name']}({r['code']}) {r['price']} 无锚数据")
            continue
        b = r["bands"]
        extra = f" | {r['reversal_watch']}" if r.get("reversal_watch") and "⚡" in r["reversal_watch"] else ""
        lines.append(f"{r['name']}({r['code']}) {r['price']} ({r['pct']:+.1f}%) | {r['zone']}·{r['action']} | 买≤{b['buy']} 卖{b['sell']} 清≥{b['clear']}{extra}")
    return "\n".join(lines)
