"""数据破壁 fetcher（2026-10-15 卡 t_fd5a5b97）——四类历史数据公开端点落地。

端点与实测结论见 docs/data-endpoints-20261015.md。要点：
- 东财系必须直连（代理节点 IP 被东财风控，会话 trust_env=False；push2his 本网络全封不可用）。
- 问财（iwencai）有日配额（实测 ~100-150 次/日，滚动 24h），耗尽返回纯文本——
  按失败处理抛 QuotaExhausted，绝不把空结果写进缓存（毒缓存防线，同 gold_monthly 纪律）。
- PIT 安全缓存：data/research/<kind>/<YYYY-MM-DD>.json，按 BJT 交易日不可变落盘；
  当日文件只在 15:05 BJT 后允许写（盘中值未定型）；历史日默认不重拉（--force 除外）。
- 写盘=原子写；字段英文 snake_case；比率小数；必带 _meta（INTERFACES.md I0/I8）。
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path("/opt/data/fenjue")
DATA = ROOT / "data" / "research"
BJT = timezone(timedelta(hours=8))
UT = "7eea3edcaed734bea9cbfc24409ed989"
WENCAI_CLI = "/opt/data/.iwencai-skillhub/skills/hithink-insresearch-query/scripts/cli.py"


class QuotaExhausted(Exception):
    """问财日配额耗尽（返回纯文本而非 JSON）。"""


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    s.trust_env = False  # 东财风控代理节点 IP，直连最稳（2026-10-15 实测）
    return s


def _meta(owner: str, inputs: list, snapshot: str) -> dict:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        sha = "unknown"
    return {"generated_at": datetime.now(BJT).isoformat(timespec="seconds"),
            "data_snapshot": snapshot, "code_version": sha, "inputs": inputs, "owner": owner}


def atomic_write(path: Path, obj: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return path


def _pit_write_allowed(day: str) -> bool:
    """历史日随便写；当日仅在收盘定型（15:05 BJT）后写。"""
    now = datetime.now(BJT)
    today = now.strftime("%Y-%m-%d")
    if day < today:
        return True
    if day == today:
        return now.hour > 15 or (now.hour == 15 and now.minute >= 5)
    return False  # 未来日


def cached_path(kind: str, day: str) -> Path:
    return DATA / kind / f"{day}.json"


def get_or_fetch(kind: str, day: str, fetcher, force: bool = False):
    """PIT 安全读取：有缓存用缓存（历史不可变），无缓存且过定型时刻才拉。"""
    p = cached_path(kind, day)
    if p.exists() and not force:
        return json.loads(p.read_text(encoding="utf-8")), "cache"
    if not _pit_write_allowed(day):
        return None, "pit_blocked"
    obj = fetcher(day)
    obj["_meta"] = _meta(f"engine.datawall_fetcher.{kind}", [], day)
    atomic_write(p, obj)
    return obj, "fetched"


# ---------------------------------------------------------------- ① 竞价（问财）

def _wencai_query(query: str, limit: int = 100, page: int = 1) -> dict:
    env = dict(os.environ)
    envf = Path("/opt/data/.env")
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    p = subprocess.run([sys.executable, WENCAI_CLI, "--query", query,
                        "--limit", str(limit), "--page", str(page)],
                       capture_output=True, text=True, timeout=60, env=env)
    if "次数已用完" in p.stdout or "次数已用完" in p.stderr:
        raise QuotaExhausted("iwencai daily quota exhausted")
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"wencai non-JSON response: {p.stdout[:200]!r}") from e


def _pick(row: dict, prefix: str, day8: str):
    v = row.get(f"{prefix}[{day8}]")
    return v


def _pct(v):
    """问财百分数字段 → 小数（INTERFACES 比率小数）。"""
    return (v / 100.0) if isinstance(v, (int, float)) else None


def fetch_auction_zt(day: str) -> dict:
    """问财「<日>涨停股的集合竞价」——一发拿全涨停宇宙竞价+封单全字段（实测 39/39 对齐 HiThink）。"""
    y, m, d = int(day[:4]), int(day[5:7]), int(day[8:10])
    day8 = day.replace("-", "")
    j = _wencai_query(f"{y}年{m}月{d}日涨停股的集合竞价", limit=100)
    if not j.get("success"):
        raise RuntimeError(f"wencai query failed: {str(j)[:200]}")
    items = []
    for r in j.get("datas") or []:
        pct = _pick(r, "竞价涨幅", day8)
        items.append({
            "code": (r.get("股票代码") or "").split(".")[0],
            "name": r.get("股票简称"),
            "auction_price": _pick(r, "竞价匹配价", day8),
            "auction_volume": _pick(r, "竞价量", day8),            # 股
            "auction_amount": _pick(r, "竞价金额", day8),            # 元
            "auction_pct": (pct / 100.0) if isinstance(pct, (int, float)) else None,
            "unmatched_volume": _pick(r, "竞价未匹配量", day8),
            "unmatched_amount": _pick(r, "竞价未匹配金额", day8),
            "seal_amount": _pick(r, "涨停封单额", day8),            # 元（收盘封单）
            "seal_ratio": _pct(_pick(r, "封成比", day8)),          # 封单额/成交额（问财原始为百分数）
            "seal_float_ratio": _pct(_pick(r, "封流比", day8)),    # 封单额/流通市值（同上百分数）
            "open_count": _pick(r, "涨停开板次数", day8),
            "first_limit_time": _pick(r, "首次涨停时间", day8),
            "last_limit_time": _pick(r, "最终涨停时间", day8),
            "limit_days_text": _pick(r, "几天几板", day8),
            "limit_reason": _pick(r, "涨停原因", day8),
        })
    return {"date": day, "source": "iwencai_zt_auction", "n": len(items), "items": items}


def fetch_auction_top(day: str, limit: int = 100) -> dict:
    """问财「<日>集合竞价成交金额排名前N」——不限涨停的全市场头部竞价。"""
    y, m, d = int(day[:4]), int(day[5:7]), int(day[8:10])
    day8 = day.replace("-", "")
    j = _wencai_query(f"{y}年{m}月{d}日集合竞价成交金额排名前{limit}", limit=limit)
    if not j.get("success"):
        raise RuntimeError(f"wencai query failed: {str(j)[:200]}")
    items = []
    for r in j.get("datas") or []:
        pct = _pick(r, "竞价涨幅", day8)
        items.append({
            "code": (r.get("股票代码") or "").split(".")[0],
            "name": r.get("股票简称"),
            "auction_price": _pick(r, "竞价匹配价", day8),
            "auction_volume": _pick(r, "竞价量", day8),
            "auction_amount": _pick(r, "竞价匹配金额", day8) or _pick(r, "竞价金额", day8),
            "auction_pct": (pct / 100.0) if isinstance(pct, (int, float)) else None,
            "unmatched_volume": _pick(r, "竞价未匹配量", day8),
            "unmatched_amount": _pick(r, "竞价未匹配金额", day8),
            "abnormal_type": _pick(r, "竞价异动类型", day8),
        })
    return {"date": day, "source": "iwencai_top_auction", "n": len(items), "items": items}


# ---------------------------------------------------------------- ③ 东财涨停池

def fetch_zt_pool_em(day: str) -> dict:
    """东财 push2ex 涨停池（直连）。有效窗口≈近 3-4 周，更早日返回空池（非错误）。"""
    r = _session().get("https://push2ex.eastmoney.com/getTopicZTPool",
                       params={"ut": UT, "dpt": "wz.ztzt", "Pageindex": "0",
                               "pagesize": "10000", "sort": "fbt:asc",
                               "date": day.replace("-", "")}, timeout=15)
    pool = ((r.json().get("data") or {}).get("pool")) or []
    items = [{
        "code": x.get("c"), "name": x.get("n"),
        "price": (x.get("p") or 0) / 1000.0,
        "pct": (x.get("zdp") or 0) / 100.0,
        "amount": x.get("amount"), "float_mcap": x.get("ltsz"), "total_mcap": x.get("tshare"),
        "turnover": (x.get("hs") or 0) / 100.0,
        "limit_days": x.get("lbc"),
        "first_seal_time": str(x.get("fbt") or "").zfill(6),
        "last_seal_time": str(x.get("lbt") or "").zfill(6),
        "seal_fund": x.get("fund"),
        "break_count": x.get("zbc") or 0,   # 空值=0 已实证（2026-09 台账）
        "industry": x.get("hybk"),
        "limit_stat_days": (x.get("zttj") or {}).get("days"),
        "limit_stat_count": (x.get("zttj") or {}).get("ct"),
        "seal_ratio": round(x["fund"] / x["amount"], 4) if x.get("fund") and x.get("amount") else None,
    } for x in pool]
    return {"date": day, "source": "eastmoney_ztpool", "n": len(items), "items": items}


# ---------------------------------------------------------------- ④ 龙虎榜（东财 datacenter）

def _em_datacenter(report: str, day: str, pagesize: int = 500) -> list:
    out, page = [], 1
    s = _session()
    while True:
        r = s.get("https://datacenter-web.eastmoney.com/api/data/v1/get",
                  params={"reportName": report, "columns": "ALL",
                          "filter": f"(TRADE_DATE<='{day}')(TRADE_DATE>='{day}')",
                          "pageNumber": page, "pageSize": pagesize,
                          "source": "WEB", "client": "WEB"}, timeout=20)
        res = r.json().get("result") or {}
        rows = res.get("data") or []
        out.extend(rows)
        if len(rows) < pagesize:
            break
        page += 1
        time.sleep(0.3)
    return out


def fetch_lhb_em(day: str) -> dict:
    """龙虎榜个股明细（2004 年起 27 万行，与 HiThink 对账逐分一致）。"""
    rows = _em_datacenter("RPT_DAILYBILLBOARD_DETAILSNEW", day)
    items = [{
        "code": x.get("SECURITY_CODE"), "name": x.get("SECURITY_NAME_ABBR"),
        "close": x.get("CLOSE_PRICE"), "pct": (x.get("CHANGE_RATE") or 0) / 100.0,
        "turnover": _pct(x.get("TURNOVERRATE")),
        "billboard_buy": x.get("BILLBOARD_BUY_AMT"),
        "billboard_sell": x.get("BILLBOARD_SELL_AMT"),
        "billboard_net": x.get("BILLBOARD_NET_AMT"),
        "billboard_amount": x.get("BILLBOARD_DEAL_AMT"),
        "reason": x.get("EXPLANATION") or x.get("EXPLAIN"),
    } for x in rows]
    return {"date": day, "source": "eastmoney_lhb_details", "n": len(items), "items": items}


def fetch_lhb_seats_em(day: str) -> dict:
    """龙虎榜席位级明细（2004 年起 219 万行；带上榜原因与 D1/D2/.../D30 后验涨跌幅）。"""
    rows = _em_datacenter("RPT_OPERATEDEPT_TRADE_DETAILSNEW", day)
    items = [{
        "code": x.get("SECURITY_CODE"), "name": x.get("SECURITY_NAME_ABBR"),
        "dept_code": x.get("OPERATEDEPT_CODE"), "dept_name": x.get("OPERATEDEPT_NAME"),
        "buy": x.get("ACT_BUY"), "sell": x.get("ACT_SELL"), "net": x.get("NET_AMT"),
        "reason": x.get("EXPLANATION"),
    } for x in rows]
    return {"date": day, "source": "eastmoney_lhb_seats", "n": len(items), "items": items}


# ---------------------------------------------------------------- ② 分钟级历史

def fetch_minute_sina(code: str, scale: int = 5, datalen: int = 1970) -> list:
    """新浪 getKLineData。实测深度(600000)：5分≈2月，15分≈6月，30分≈1年，60分≈2年。datalen>~2000 返回空。"""
    sym = ("sh" if code.startswith("6") else "sz") + code
    r = _session().get(
        "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData",
        params={"symbol": sym, "scale": scale, "ma": "no", "datalen": datalen},
        headers={"Referer": "https://finance.sina.com.cn"}, timeout=20)
    j = r.json()
    return [{"t": x["day"], "o": x["open"], "h": x["high"], "l": x["low"],
             "c": x["close"], "v": x["volume"]} for x in (j if isinstance(j, list) else [])]


def fetch_minute_tx(code: str, level: str = "m5", count: int = 800) -> list:
    """腾讯 mkline（ifzq 直连）。实测深度：m1≈3 交易日(≤800)，m5≈1 月(800)，count>800 只回 320。"""
    sym = ("sh" if code.startswith("6") else "sz") + code
    r = _session().get(f"https://ifzq.gtimg.cn/appstock/app/kline/mkline",
                       params={"param": f"{sym},{level},,{count}"}, timeout=20)
    arr = (r.json().get("data") or {}).get(sym, {}).get(level) or []
    return [{"t": x[0], "o": float(x[1]), "c": float(x[2]), "h": float(x[3]),
             "l": float(x[4]), "v": x[5] if len(x) > 5 else None} for x in arr]


def fetch_minute_baostock(code: str, freq: str = "5",
                          start: str = "2020-01-01", end: str = None) -> list:
    """baostock 分钟 K（5/15/30/60，实测 2020-01-02 起≈6 年）。禁双进程（台账铁律）。"""
    sys.path.insert(0, "/opt/data/python-libs")
    import baostock as bs  # noqa
    sym = ("sh." if code.startswith("6") else "sz.") + code
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login failed: {lg.error_msg}")
    try:
        rs = bs.query_history_k_data_plus(
            sym, "date,time,open,high,low,close,volume,amount",
            start_date=start, end_date=end or datetime.now(BJT).strftime("%Y-%m-%d"),
            frequency=freq, adjustflag="3")
        out = []
        while rs.error_code == "0" and rs.next():
            d, t, o, h, l, c, v, a = rs.get_row_data()
            # baostock 分钟级 time 格式 YYYYMMDDHHMMSSmmm
            hhmm = f"{t[8:10]}:{t[10:12]}" if len(t) >= 12 else t
            out.append({"t": f"{d} {hhmm}",
                        "o": float(o), "h": float(h), "l": float(l),
                        "c": float(c), "v": float(v), "a": float(a)})
        return out
    finally:
        bs.logout()


# ---------------------------------------------------------------- CLI

FETCHERS = {
    "auction_zt": ("auction_zt", fetch_auction_zt),
    "auction_top": ("auction_top", fetch_auction_top),
    "zt_pool_em": ("zt_pool_em", fetch_zt_pool_em),
    "lhb_em": ("lhb_em", fetch_lhb_em),
    "lhb_seats_em": ("lhb_seats_em", fetch_lhb_seats_em),
}


def main():
    import argparse
    ap = argparse.ArgumentParser(description="数据破壁 fetcher（PIT 安全缓存）")
    ap.add_argument("--kind", required=True, choices=list(FETCHERS))
    ap.add_argument("--dates", required=True, help="逗号分隔 YYYY-MM-DD")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    kind, fn = FETCHERS[args.kind]
    for day in args.dates.split(","):
        day = day.strip()
        try:
            obj, how = get_or_fetch(kind, day, fn, force=args.force)
            if obj is None:
                print(f"{day}: {how}（当日未过 15:05 BJT 定型时刻，拒写）", flush=True)
            else:
                print(f"{day}: {how} n={obj['n']} -> {cached_path(kind, day)}", flush=True)
        except QuotaExhausted:
            print(f"{day}: QUOTA_EXHAUSTED（不毒缓存，配额重置后重跑）", flush=True)
            break
        except Exception as e:
            print(f"{day}: ERROR {type(e).__name__}: {e}", flush=True)
        time.sleep(1.0)


if __name__ == "__main__":
    main()
