#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
engine/hithink_index_history.py — HiThink 同花顺板块指数历史日线回填 (增量/断点续跑)

口径:
  - 数据源: HiThink /api/a-share-index/prices/historical?thscode=..&interval=1d&start=<ms>&end=<ms>
  - adjust=null (原始价; 板块指数不参与个股前复权, 比率安全)
  - date_ms(UTC 毫秒戳) -> YYYY-MM-DD, 按 UTC 日期直接转换
  - 单请求区间严格 <10 年 (实测 end-start>10年 -> code=1003); 内部分块 CHUNK_DAYS=9年
  - 增量: 已有文件从 (文件最后日期 + 1 天) 起拉取, 按 date 去重合并 (新 bar 覆盖同日旧 bar)
  - 原子落盘: <thscode>.json.tmp -> Path.replace -> <thscode>.json

输入:  /opt/data/fenjue/data/hithink/sectors/catalog_*.json   (取文件名排序最新一份)
输出:  /opt/data/fenjue/data/hithink/index_hist/<thscode>.json
       {thscode, name, fetch_date, item:[{date,open,high,low,close,volume,turnover},...]}

速率: 0.3s/请求; 失败 3 次指数退避 (0.3/0.6/1.2 s)
看门狗: catalog 缺失 -> stderr 报错 + exit(2)
随机对照: 本任务为数据回填, 无信号构造, 不涉及随机对照 (如后续用于回测, 由回测脚本自行固定 seed)

已知限制:
  - 依赖系统 curl 二进制 (子进程 env 只保留 PATH)
  - 板块指数发布日之前无数据 (上游决定), 非交易日无 bar
  - catalog 结构非标准时走启发式 (显式 indices/indexes/sectors key -> .TI/881xx 过滤 -> 全量)
  - 无法绕过上游 10 年区间限制 / 历史深度限制
  - 不打印 / 不落盘 API key
"""
import json
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
SECTORS_DIR = ROOT / "data/hithink/sectors"
OUT_DIR = ROOT / "data/hithink/index_hist"
ENV_FILE = Path("/opt/data/.env")
BASE = "https://fuyao.aicubes.cn"

START_DEFAULT = date(2019, 1, 1)
CHUNK_DAYS = 365 * 9            # < 10 年上限 (上游硬约束)
RATE_SLEEP = 0.3                # 正常请求间隔
RETRY_MAX = 3                   # 失败重试次数 (指数退避底 0.3s)


# --------------------------------------------------------------------------
# 认证
# --------------------------------------------------------------------------
def _load_key():
    if not ENV_FILE.exists():
        print(f"FATAL: {ENV_FILE} missing", file=sys.stderr)
        sys.exit(2)
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("HITHINK_API_KEY="):
            k = line.split("=", 1)[1].strip()
            if k:
                return k
    print("FATAL: HITHINK_API_KEY missing in /opt/data/.env", file=sys.stderr)
    sys.exit(2)


KEY = _load_key()


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def _curl_json(path):
    r = subprocess.run(
        ["curl", "-sL", "--max-time", "30",
         "-H", f"X-api-key: {KEY}", BASE + path],
        capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"},
    )
    if r.returncode != 0:
        raise RuntimeError(f"curl rc={r.returncode} stderr={(r.stderr or '')[:200]}")
    return json.loads(r.stdout)


def _get_json(path, attempts=RETRY_MAX):
    """code!=0 / 解析失败 / curl 失败 -> 指数退避重试 attempts 次。"""
    last = None
    for i in range(attempts):
        try:
            r = _curl_json(path)
            if r.get("code") == 0:
                return r
            last = f"code={r.get('code')} msg={r.get('message')}"
        except Exception as e:  # noqa: BLE001
            last = repr(e)
        if i < attempts - 1:
            time.sleep(0.3 * (2 ** i))
    raise RuntimeError(f"API failed {attempts}x: {last}")


# --------------------------------------------------------------------------
# 时间工具
# --------------------------------------------------------------------------
def _ms_start(dt_):
    return int(datetime(dt_.year, dt_.month, dt_.day,
                        tzinfo=timezone.utc).timestamp() * 1000)


def _ms_end_inclusive(dt_):
    """当天 23:59:59.999 UTC, 保证包含当日 bar。"""
    return _ms_start(dt_ + timedelta(days=1)) - 1


def _date_chunks(start, end, chunk_days=CHUNK_DAYS):
    cur = start
    while cur <= end:
        ce = cur + timedelta(days=chunk_days - 1)
        if ce > end:
            ce = end
        yield cur, ce
        cur = ce + timedelta(days=1)


def _ms_to_isodate(dms):
    return datetime.fromtimestamp(int(dms) / 1000.0, tz=timezone.utc).date().isoformat()


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
def fetch_range(thscode, s, e):
    """单区间拉取 (调用方保证 e-s < 10年)。返回 item 列表。"""
    path = (f"/api/a-share-index/prices/historical?thscode={thscode}"
            f"&interval=1d&start={_ms_start(s)}&end={_ms_end_inclusive(e)}")
    r = _get_json(path)
    data = r.get("data") or {}
    return data.get("item") or []


# --------------------------------------------------------------------------
# catalog
# --------------------------------------------------------------------------
def load_catalog():
    """返回 (path, parsed_json)。缺失/解析失败 -> exit(2)。"""
    if not SECTORS_DIR.exists():
        print(f"FATAL: sectors dir missing: {SECTORS_DIR}", file=sys.stderr)
        sys.exit(2)
    files = sorted(SECTORS_DIR.glob("catalog_*.json"))
    if not files:
        print(f"FATAL: no catalog_*.json under {SECTORS_DIR}", file=sys.stderr)
        sys.exit(2)
    p = files[-1]
    try:
        data = json.loads(p.read_text())
    except Exception as e:  # noqa: BLE001
        print(f"FATAL: catalog parse error {p}: {e}", file=sys.stderr)
        sys.exit(2)
    return p, data


def _is_index_code(tc):
    s = str(tc)
    if s.endswith(".TI"):
        return True
    if s[:3] in ("881", "885", "886", "888"):
        return True
    return False


def _norm_entries(lst):
    out = {}
    for n in lst:
        if not isinstance(n, dict):
            continue
        tc = n.get("thscode") or n.get("code") or n.get("index_code")
        if not tc:
            continue
        nm = n.get("name") or n.get("sec_name") or n.get("index_name") or ""
        out[str(tc)] = str(nm)
    return out


def extract_indices(cat):
    """从 catalog 抓 {thscode: name}。容错多种结构。"""
    if isinstance(cat, dict):
        for k in ("indices", "indexes", "sectors", "sector_list", "index_list"):
            v = cat.get(k)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return _norm_entries(v)
            if isinstance(v, dict) and v:
                out = {}
                for tck, vv in v.items():
                    nm = vv.get("name") if isinstance(vv, dict) else (vv if isinstance(vv, str) else "")
                    out[str(tck)] = str(nm or "")
                return out

    pool = []

    def walk(node):
        if isinstance(node, dict):
            if "thscode" in node:
                pool.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(cat)
    filtered = [n for n in pool if _is_index_code(n.get("thscode", ""))]
    chosen = filtered if filtered else pool
    return _norm_entries(chosen)


# --------------------------------------------------------------------------
# 合并 / 拉取
# --------------------------------------------------------------------------
def merge_index(thscode, existing_items, end_date):
    """增量拉取并合并。返回 (items_sorted, new_bar_count)。"""
    by_date = {}
    for it in (existing_items or []):
        if isinstance(it, dict) and it.get("date"):
            by_date[it["date"]] = it

    if by_date:
        try:
            start = date.fromisoformat(max(by_date)) + timedelta(days=1)
        except Exception:  # noqa: BLE001
            start = START_DEFAULT
    else:
        start = START_DEFAULT

    new_bars = 0
    if start <= end_date:
        for cs, ce in _date_chunks(start, end_date):
            raw = fetch_range(thscode, cs, ce)
            for row in raw:
                dms = row.get("date_ms")
                if dms is None:
                    continue
                try:
                    d = _ms_to_isodate(dms)
                except Exception:  # noqa: BLE001
                    continue
                by_date[d] = {
                    "date": d,
                    "open": row.get("open_price"),
                    "high": row.get("high_price"),
                    "low": row.get("low_price"),
                    "close": row.get("close_price"),
                    "volume": row.get("volume"),
                    "turnover": row.get("turnover"),
                }
                new_bars += 1
            time.sleep(RATE_SLEEP)

    items = [by_date[d] for d in sorted(by_date)]
    return items, new_bars


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    cat_path, cat = load_catalog()
    indices = extract_indices(cat)
    if not indices:
        print(f"FATAL: no index entries extracted from {cat_path}", file=sys.stderr)
        sys.exit(2)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today()
    fetch_date = today.isoformat()
    n_total = len(indices)

    print(f"[index_hist] catalog={cat_path.name} indices={n_total} "
          f"range={START_DEFAULT.isoformat()}..{fetch_date}")

    ok = 0
    fail = 0
    total_bars = 0
    new_bars_total = 0
    min_d = None
    max_d = None

    for i, (tc, name) in enumerate(indices.items(), 1):
        out_path = OUT_DIR / f"{tc}.json"
        try:
            existing = []
            if out_path.exists():
                try:
                    old = json.loads(out_path.read_text())
                    existing = (old.get("item") if isinstance(old, dict) else None) or []
                except Exception as e:  # noqa: BLE001
                    print(f"WARN {tc}: corrupt existing file -> refetch full: {e}")
                    existing = []

            items, nb = merge_index(tc, existing, today)

            doc = {
                "thscode": tc,
                "name": name,
                "fetch_date": fetch_date,
                "item": items,
            }
            tmp = Path(str(out_path) + ".tmp")
            tmp.write_text(json.dumps(doc, ensure_ascii=False))
            tmp.replace(out_path)

            ok += 1
            total_bars += len(items)
            new_bars_total += nb
            if items:
                ds = [x["date"] for x in items if x.get("date")]
                if ds:
                    mn, mx = min(ds), max(ds)
                    min_d = mn if (min_d is None or mn < min_d) else min_d
                    max_d = mx if (max_d is None or mx > max_d) else max_d
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"ERR {tc} ({name}): {e}")

        if i % 50 == 0:
            print(f"[index_hist] progress {i}/{n_total} ok={ok} fail={fail} "
                  f"new_bars={new_bars_total}")

    print("")
    print(f"[index_hist] DONE indices={n_total} ok={ok} fail={fail}")
    print(f"[index_hist] total_bars={total_bars} new_bars={new_bars_total}")
    if min_d:
        print(f"[index_hist] date range: {min_d} ~ {max_d}")
    else:
        print("[index_hist] date range: <empty>")
    print(f"[index_hist] out={OUT_DIR}")


if __name__ == "__main__":
    main()
