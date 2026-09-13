```python
#!/usr/bin/env python3
"""engine/hithink_sectors.py — HiThink(同花顺) 板块指数目录 + 成分股 周更管线

口径
  - 数据源: HiThink 官方 API, Base https://fuyao.aicubes.cn, 认证头 X-api-key
    (key 从 /opt/data/.env 的 HITHINK_API_KEY 读取; 本文件不打印、不落盘 key)
  - 端点实测日期: 2026-09-13
      GET /api/a-share-index/catalog/ths-index-list
          -> {code:0, data:{timestamp, item:[{thscode:"885431.TI", name:"新能源汽车"}, ...]}}
          实测 size 参数被忽略, 一次返回大批量; 本代码同时兼容两种形态:
            (a) 一次性全量 (data.item, 无 pagination / pages==1)
            (b) 分页 (data.pagination.pages, page+size)
          去重按 thscode + "翻页无新增即停", 防端点忽略 size 时死循环
      GET /api/a-share-index/constituents/ths-stock-list?thscode=886042.TI
          -> {code:0, data:{timestamp, item:[{thscode:"000021.SZ", ticker:"000021", name:"深科技"}, ...]}}
          单次只接受一个指数(不接受逗号分隔)
      错误形态: {code:404, message:"Route not found"}
  - 速率自律: 0.3s/请求; 网络层失败重试 3 次, 指数退避 0.3/0.6/1.2s
    业务错误码(400/401/403/404) 不重试, 直接交给调用方判定
  - 本文件只落成分映射, 不产出任何买卖信号/模拟盘输出,
    因此 T+1 断言与 0.0015/边 手续费口径不适用(纯数据管线)。

数据源路径 / 输出路径
  ROOT        = /opt/data/fenjue
  输出根       = ROOT/data/hithink/sectors
  指数目录     = ROOT/data/hithink/sectors/catalog_YYYYMMDD.json         (含 fetch_date)
  成分股       = ROOT/data/hithink/sectors/constituents/<thscode>.json
                 (断点续跑: 文件存在且 fetch_date == 当日 → 跳过, 不重复请求)
  反向映射     = ROOT/data/hithink/sectors/stock_sectors_YYYYMMDD.json
                 { "000021": [{"thscode":"885431.TI","name":"新能源汽车"}, ...], ... }
                 key 为 ticker 6 位(不含 .SZ/.SH/.BJ 后缀), value 按 thscode 升序

环境变量
  HT_DATE   覆盖 today (YYYY-MM-DD), 用于补跑/回放; 缺省 date.today()
  HT_LIMIT  只处理目录前 N 个指数(调试用, 缺省 0 = 全量)

看门狗纪律
  - 目录拉取失败(code!=0 / 网络错 / item 空) → stderr 报 FATAL, 退出码 2
  - 成分个别失败 → stderr WARN, 继续跑完; 最后 stdout 打失败清单, 退出码 1
    (重跑当日幂等: 已成功落盘的在下一轮会被跳过, 只补失败项)
  - 全部成功 → 退出码 0

已知限制
  - 成分股是"当前快照", 无历史成分变更时点。做历史截面概念归类时,
    必须取 落盘日 <= 信号日 的快照文件, 否则构成前视。本条是使用纪律, 非代码可保证。
  - 板块可能重名/改名, thscode 为唯一键; 反向映射里保留 name 仅供人读。
  - 部分板块可能合法返回 0 成分(指数无成分股), 记为成功但成分数 0。
  - 限流阈值未实测, 0.3s/请求为保守自律值; 若持续超时/被限, 调大 SLEEP。
  - 目录端点 size/page 行为不稳定, 依赖 thscode 去重 + 无新增即停的兜底逻辑。

随机对照(铁律8, seed 固定 = 20260913)
  随机抽 20 个板块, 交叉校验 "成分文件 → 反向映射" 的包含关系与板块名一致性。
  这是内部一致性对照, 用于抓 mapping 构建 bug(重复/丢失/错名)。
"""

import json
import os
import random
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
OUT_ROOT = ROOT / "data" / "hithink" / "sectors"
CONST_DIR = OUT_ROOT / "constituents"
ENV_PATH = Path("/opt/data/.env")

BASE = "https://fuyao.aicubes.cn"
CATALOG_EP = "/api/a-share-index/catalog/ths-index-list"
CONST_EP = "/api/a-share-index/constituents/ths-stock-list"
API_MEASURED_ON = "2026-09-13"

SLEEP = 0.3
RETRIES = 3
TIMEOUT = 30
PROGRESS_EVERY = 200
SEED = 20260913
CROSSCHECK_N = 20


def log(msg):
    print(msg, flush=True)


def load_key():
    if not ENV_PATH.exists():
        return None
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line.startswith("HITHINK_API_KEY="):
            v = line.split("=", 1)[1].strip()
            return v or None
    return None


KEY = load_key()
if not KEY:
    print("FATAL: HITHINK_API_KEY missing in /opt/data/.env",
          file=sys.stderr, flush=True)
    sys.exit(2)


# ---------------------------------------------------------------- HTTP layer

def _curl_json(path):
    r = subprocess.run(
        ["curl", "-sL", "--max-time", str(TIMEOUT),
         "-H", f"X-api-key: {KEY}", BASE + path],
        capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"},
    )
    if r.returncode != 0:
        raise RuntimeError(f"curl rc={r.returncode}: {r.stderr.strip()[:200]}")
    body = r.stdout.strip()
    if not body:
        raise RuntimeError("empty body")
    return json.loads(body)


def get(path):
    """GET + 0.3s 自律限速 + 最多 RETRIES 次指数退避重试。

    只在网络/解析层失败时抛异常。业务错误码(400/401/403/404)直接返回,
    由调用方判定, 不浪费重试。
    """
    last = None
    for attempt in range(RETRIES):
        try:
            j = _curl_json(path)
            code = j.get("code")
            if code in (0, 200, 400, 401, 403, 404):
                time.sleep(SLEEP)
                return j
            last = RuntimeError(f"code={code} message={j.get('message')}")
        except Exception as e:  # noqa: BLE001 - 网络/JSON 统一重试
            last = e
        if attempt < RETRIES - 1:
            time.sleep(SLEEP * (2 ** attempt))  # 0.3 / 0.6 / 1.2
    raise last if isinstance(last, BaseException) else RuntimeError(str(last))


# ---------------------------------------------------------------- fetchers

def fetch_catalog():
    """兼容 (a) 一次性全量 (b) 分页 两种形态。

    返回 (items, meta): items=[{thscode,name,...}], meta={"timestamp","pagination"}
    失败抛异常(目录失败=致命)。
    """
    items, seen = [], set()
    page, pages = 1, 1
    meta = {}
    while True:
        j = get(f"{CATALOG_EP}?page={page}&size=200")
        code = j.get("code")
        if code != 0:
            raise RuntimeError(f"catalog code={code} message={j.get('message')}")
        data = j.get("data") or {}
        meta = {"timestamp": data.get("timestamp"),
                "pagination": data.get("pagination")}
        added = 0
        for it in data.get("item") or []:
            ths = it.get("thscode")
            if not ths or ths in seen:
                continue
            seen.add(ths)
            rec = dict(it)
            rec.setdefault("name", "")
            items.append(rec)
            added += 1
        pag = data.get("pagination") or {}
        try:
            pages = int(pag.get("pages") or 1)
        except Exception:  # noqa: BLE001
            pages = 1
        if page >= pages:
            break
        if added == 0:
            # 端点忽略 size 一次返回全量 → 翻页无新增, 停止, 防死循环
            break
        page += 1
    return items, meta


def fetch_constituents(thscode):
    """单指数成分股。返回 (item_list, api_timestamp); 失败抛异常。"""
    j = get(f"{CONST_EP}?thscode={thscode}")
    code = j.get("code")
    if code != 0:
        raise RuntimeError(f"code={code} message={j.get('message')}")
    data = j.get("data") or {}
    raw = data.get("item")
    items = raw if isinstance(raw, list) else []
    return items, data.get("timestamp")


def read_cache(fp, today):
    """断点续跑: 文件存在且 fetch_date == today 才复用, 否则返回 None(重拉)。"""
    if not fp.exists():
        return None
    try:
        j = json.loads(fp.read_text())
    except Exception:  # noqa: BLE001 - 半截文件/损坏 → 重拉
        return None
    if j.get("fetch_date") != today:
        return None
    items = (j.get("data") or {}).get("item")
    return items if isinstance(items, list) else None


# ---------------------------------------------------------------- crosscheck

def crosscheck(board_names, board_tickers, reverse_map,
               seed=SEED, n=CROSSCHECK_N):
    """固定 seed 随机抽板块, 校验 成分集合 → 反向映射 的包含关系与命名一致。

    返回 (抽样板块数, 校验成分边数, 不一致明细)。
    """
    rng = random.Random(seed)
    boards = sorted(board_tickers)
    if not boards:
        return 0, 0, []
    sample = rng.sample(boards, min(n, len(boards)))
    edges = 0
    bad = []
    for b in sample:
        for tk in sorted(board_tickers.get(b) or ()):
            edges += 1
            entries = reverse_map.get(tk) or []
            hits = [e for e in entries if e.get("thscode") == b]
            if len(hits) != 1:
                bad.append((b, tk, f"reverse-miss({len(hits)})"))
            elif hits[0].get("name") != board_names.get(b):
                bad.append((b, tk, "name-mismatch"))
    return len(sample), edges, bad


# ---------------------------------------------------------------- main

def main():
    today = os.environ.get("HT_DATE") or date.today().isoformat()
    tag = today.replace("-", "")
    limit = int(os.environ.get("HT_LIMIT") or 0)

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    CONST_DIR.mkdir(parents=True, exist_ok=True)

    log(f"=== HiThink 板块成分周更 date={today} "
        f"(api_measured_on={API_MEASURED_ON}) ===")

    # 1) 指数目录 —— 失败即致命
    try:
        items, meta = fetch_catalog()
    except Exception as e:  # noqa: BLE001
        print(f"FATAL: catalog fetch failed: {e}", file=sys.stderr, flush=True)
        return 2
    if not items:
        print("FATAL: catalog empty (code=0 but item=[])",
              file=sys.stderr, flush=True)
        return 2

    if limit > 0:
        items = items[:limit]
        log(f"HT_LIMIT={limit} 生效(调试模式)")
        # 目录文件按全量语义落盘, 调试时不覆盖
    cat_path = OUT_ROOT / f"catalog_{tag}.json"
    cat_path.write_text(json.dumps({
        "fetch_date": today,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "endpoint": CATALOG_EP,
        "api_measured_on": API_MEASURED_ON,
        "api_timestamp": meta.get("timestamp"),
        "count": len(items),
        "item": items,
    }, ensure_ascii=False))
    log(f"catalog: {len(items)} 个指数 → {cat_path}")

    # 2) 逐指数拉成分(断点续跑) + 3) 同步构建反向映射
    stock_map = {}      # ticker6 -> {thscode: 板块名}
    board_names = {}    # thscode -> 板块名
    board_sizes = {}    # thscode -> 成分数(仅成功)
    board_tickers = {}  # thscode -> set(ticker6)(仅成功)

    ok = skipped = 0
    failed = []
    total = len(items)

    for idx, it in enumerate(items, 1):
        ths = it["thscode"]
        name = it.get("name") or ths
        board_names[ths] = name
        fp = CONST_DIR / f"{ths}.json"

        cons = read_cache(fp, today)
        if cons is not None:
            skipped += 1
        else:
            try:
                cons, api_ts = fetch_constituents(ths)
            except Exception as e:  # noqa: BLE001
                failed.append((ths, name, str(e)))
                print(f"WARN constituents {ths} {name}: {e}",
                      file=sys.stderr, flush=True)
                cons = None
            if cons is not None:
                fp.write_text(json.dumps({
                    "fetch_date": today,
                    "fetched_at": datetime.now(timezone.utc)
                    .isoformat(timespec="seconds"),
                    "thscode": ths,
                    "name": name,
                    "endpoint": CONST_EP,
                    "api_measured_on": API_MEASURED_ON,
                    "code": 0,
                    "data": {"item": cons, "timestamp": api_ts},
                }, ensure_ascii=False))
                ok += 1

        if cons is not None:
            board_sizes[ths] = len(cons)
            tks = board_tickers.setdefault(ths, set())
            for c in cons:
                if not isinstance(c, dict):
                    continue
                tk = c.get("ticker") or (c.get("thscode") or "").split(".")[0]
                if not tk:
                    continue
                tks.add(tk)
                stock_map.setdefault(tk, {})[ths] = name

        if idx % PROGRESS_EVERY == 0 or idx == total:
            log(f"  ... {idx}/{total}  ok={ok} skip={skipped} fail={len(failed)}")

    # 3) 反向映射落盘
    reverse = {
        tk: [{"thscode": t, "name": n} for t, n in sorted(slots.items())]
        for tk, slots in sorted(stock_map.items())
    }
    rev_path = OUT_ROOT / f"stock_sectors_{tag}.json"
    rev_path.write_text(json.dumps(reverse, ensure_ascii=False))

    # 4) 汇报
    n_stocks = len(reverse)
    n_links = sum(len(v) for v in reverse.values())
    avg = (n_links / n_stocks) if n_stocks else 0.0
    top = sorted(((sz, ths, board_names.get(ths, ths))
                  for ths, sz in board_sizes.items()),
                 key=lambda x: (-x[0], x[1]))[:10]

    log("")
    log(f"指数总数          : {total}")
    log(f"成分成功(本轮新拉): {ok}")
    log(f"成分命中当日缓存  : {skipped}")
    log(f"成分失败          : {len(failed)}")
    log(f"覆盖股票数        : {n_stocks}")
    log(f"板块-股票链接数   : {n_links}")
    log(f"每票平均板块数    : {avg:.2f}")
    log("最大的10个板块(按成分数):")
    for sz, ths, nm in top:
        log(f"  {ths:<14} {nm}  {sz}")

    if failed:
        log(f"失败清单 ({len(failed)}):")
        for ths, nm, err in failed:
            log(f"  {ths} {nm}: {err}")

    n_chk, n_edges, bad = crosscheck(board_names, board_tickers, reverse)
    log(f"随机对照(seed={SEED}): 抽 {n_chk} 个板块 / {n_edges} 条成分边, "
        f"不一致 {len(bad)}")
    for b, tk, why in bad[:10]:
        log(f"  对照失败 {b} {tk} {why}")

    log(f"反向映射 → {rev_path}")

    if failed:
        log("NOTE: 部分成分拉取失败; 当日重跑本脚本幂等补齐(已拉取的会跳过)。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```