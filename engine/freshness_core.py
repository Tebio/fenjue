#!/usr/bin/env python3
"""engine/freshness_core.py — 数据时效判定唯一出处（DATA-01 数据面监控机）

为什么单立这个模块（spec 现状证据 3/6）：
- build_daily_state.py:74 的 freshness() 是局部函数，24 处调用各自传参、用**字符串比日期**，
  无交易日概念、无严重级别（本期只看不改，P1 收编时全部指向这里）；
- regime_daily_append 旧 _intended_day() 把「数据断供」翻译成「假日」的 root cause 就是
  「谁都在自己数天数」——滞后必须按官方交易日历算（#330-B）。

纪律：
1. 滞后 = trading_days_between()，只读 **本地缓存** data/trade_calendar/<year>.json
   （官方 baostock 日历的落盘副本）。**严禁联网抓数**——日历缓存不可用 → raise
   CalendarUnavailable，不许猜节假日（同 #330-D「日历不可用按数据不全处理」）。
2. date_expr 解析不出 → 返回 None（调用方判 unknown_date），**绝不静默降级成 ok**。
3. 本模块零写盘、零打印；退出码语义在 engine/data_health.py。

date_expr 语法（spec 接口契约）：
  "[-1].date"         JSON 数组末元素的 date 字段（支持 dotted： "[-1]._meta.date"）
  "[-1].date|jsonl"   JSONL 末行的 date 字段（字段名任意，如 "[-1].signal_date|jsonl"）
  "[-1][N]"           JSON 数组末元素的第 N 项（list-of-list 的日期列，如 "[-1][0]"；
                      DATA-09 新增，fund_cache/cap_hist 单文件形态）
  "_meta.date"        JSON 字典的 dotted 路径（如 "sig_date"）
  "none"              显式不做新鲜度检查（DATA-09 新增）：该数据集无机器可读日期，
                      体检必须报 unknown_date + freshness_unknown=True——
                      「不检查」必须显式可见，不许静默当 ok
                      （dbt「neither warn_after nor error_after → 不检查」同纪律，
                      见 docs/plan/references/data-contract-baseline.md §1）
  "dir:last_bar[:字段]" 目录模式：取最近写入的 ≤25 个 .json，读各自末 bar 的日期字段
                      （默认 "date"，新浪缓存用 "dir:last_bar:day"），取最大值。
                      spec 风险 2：本期 freshness 只看末端日期，不看覆盖率。
  "dir:last_bar[N]"   目录 list-of-list 模式（DATA-09 新增）：末 bar 是 list，取第 N 项
                      作日期。mtime 不可信（cap_hist 实证：mtime 10-03 内容停在 09-18；
                      fund_cache 实证：71 个空数组文件 mtime 最新）——因此本形态按
                      mtime 降序扫描，**跳过空/坏文件不计入样本**，取前 ≤25 个
                      能产出有效日期的文件的最大值（总读取数上限 DIR_SCAN_CAP 防爆）。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
CAL_DIR = ROOT / "data" / "trade_calendar"
REGISTRY_YAML = ROOT / "data" / "datasets_registry.yaml"
WHITELIST_YAML = ROOT / "data" / "stale_whitelist.yaml"

STATUSES = ("ok", "stale", "fatal_lag", "missing", "unregistered", "unknown_date")
# 参与退出码 1 的状态（cron 报红）；stale/unknown_date 只进报告与状态机
FATAL_STATUSES = ("fatal_lag", "missing", "unregistered")


def is_blocking(status: str, severity: str | None = None) -> bool:
    """该条目是否应阻断（cron 报红 / 进 🚨 段）。**唯一口径**，消费者只许调这里。

    missing / unregistered / fatal_lag 一律阻断。
    unknown_date 仅在 severity == "fatal" 时阻断 —— 「日期解析不出」对致命数据集
    等于「无法证明数据是新的」，按断供处理；不许因为"我不知道"就报绿。
    这与 #330 的纪律同源：数据不可信不许被翻译成「今天没事」。
    warn / info 级的 unknown_date 只进报告与状态机，不阻断（避免非关键集结构微调就炸 cron）。
    """
    if status in FATAL_STATUSES:
        return True
    return status == "unknown_date" and severity == "fatal"
SEVERITIES = ("fatal", "warn", "info")
REQUIRED_FIELDS = ("path", "date_expr", "cadence", "max_lag", "severity", "blocks", "owner")
DIR_SAMPLE = 300        # 目录模式最多读的近期文件数（体检 <60s/<300MB 纪律）。
                        # 25 → 300（2026-10-20 #332/P0）：兜底班曾把 188 只退市股文件白刷
                        # mtime（内容零变化），25 采样全落在僵尸文件上 → big_kcache 假 fatal_lag。
                        # 根修在 update_kcache 零变化不写盘；此处加采样余量防任何批量触写
                        # 再吃光样本。300 × ~130KB ≈ 40MB / ~1s，预算内。
DIR_SCAN_CAP = 5000      # dir:last_bar[N] 跳过空/坏文件时的总读取上限（fund_cache 实测 71 空文件顶头）。
                         # 200 → 5000（2026-10-20 #332/P0）：硬不变量 DIR_SAMPLE ≤ DIR_SCAN_CAP
                         # （golden 空文件挨饿用例实抓：采样 300 而总读 200 时有效文件永远读不到）。
                         # 5000 ≥ fund_cache 全量文件数（3377），兜底全扫也在秒级。
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_IDX_RE = re.compile(r"^\[-1\]\[(\d+)\]$")          # "[-1][0]" 单文件 list-of-list
_DIR_IDX_RE = re.compile(r"^last_bar\[(\d+)\]$")    # "dir:last_bar[0]" 目录 list-of-list


class CalendarUnavailable(RuntimeError):
    """官方交易日历本地缓存缺失/为空——不许猜，让上层按基建错误退出（exit 2）。"""


class RegistryError(ValueError):
    """注册表配置错误（fatal 无 blocks / 缺字段 / 未登记消费者）——exit 2。"""


# ---------------------------------------------------------------------------
# 官方交易日历（只读本地缓存；联网刷新是 trade_calendar.py 的事，不归本模块）
# ---------------------------------------------------------------------------

def _load_year(year: int) -> list[str]:
    fp = CAL_DIR / f"{year}.json"
    if not fp.exists():
        raise CalendarUnavailable(f"交易日历缓存缺失：{fp}（先跑 engine/trade_calendar.py 或任一 kcache 班刷新）")
    try:
        arr = json.loads(fp.read_text())
    except Exception as e:
        raise CalendarUnavailable(f"交易日历缓存损坏：{fp}（{e}）")
    if not arr:
        raise CalendarUnavailable(f"交易日历缓存为空：{fp}")
    return arr


def trading_days_between(d_from: str, d_to: str) -> int:
    """(d_from, d_to] 内的官方交易日数（滞后口径）；d_to <= d_from → 0。

    禁止用自然日差（周五→周一滞后=1 不是 3）。日历不可用 → raise，不许猜。
    """
    if not (_DATE_RE.match(d_from or "") and _DATE_RE.match(d_to or "")):
        raise ValueError(f"日期必须是 YYYY-MM-DD：{d_from!r} {d_to!r}")
    if d_to <= d_from:
        return 0
    days: list[str] = []
    for y in range(int(d_from[:4]), int(d_to[:4]) + 1):
        days.extend(_load_year(y))
    return sum(1 for d in days if d_from < d <= d_to)


def is_trading_day(day: str) -> bool:
    return day in set(_load_year(int(day[:4])))


def prev_trading_day(day: str) -> str:
    """day 之前最近的官方交易日（可跨年，逐年往回找缓存）。找不到 → raise。"""
    y = int(day[:4])
    for _ in range(3):
        prev = [d for d in _load_year(y) if d < day]
        if prev:
            return prev[-1]
        y -= 1
    raise CalendarUnavailable(f"找不到 {day} 之前的交易日（缓存覆盖不足）")


# ---------------------------------------------------------------------------
# date_expr 解析（解析不出 → None，绝不猜）
# ---------------------------------------------------------------------------

def _dig(obj, dotted: str):
    """dotted 路径下钻；任一环缺失/类型不对 → None。"""
    cur = obj
    for k in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
        if cur is None:
            return None
    return cur if isinstance(cur, str) and _DATE_RE.match(cur) else None


def _dir_last_bar(path: Path, expr: str):
    """目录模式：最近写入的 ≤DIR_SAMPLE 个 .json 的末 bar 日期字段，取最大值。

    只看不更新的目录会停在旧日期（= 正确的 stale 信号，不是误判）。
    半截写入的文件 json 解析失败 → 跳过（#330-D3：写入非原子，读到半截不许崩）。
    """
    parts = expr.split(":")
    field = parts[2] if len(parts) > 2 and parts[2] else "date"
    if not path.is_dir():
        return None
    try:
        files = sorted(path.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    except Exception:
        return None
    best = None
    for fp in files[:DIR_SAMPLE]:
        try:
            arr = json.loads(fp.read_text())
        except Exception:
            continue
        if isinstance(arr, dict):  # 容忍 {"data": [...]} 一层包裹
            arr = next((v for v in arr.values() if isinstance(v, list)), [])
        if not isinstance(arr, list) or not arr or not isinstance(arr[-1], dict):
            continue
        d = arr[-1].get(field)
        if isinstance(d, str) and _DATE_RE.match(d) and (best is None or d > best):
            best = d
    return best


def _dir_last_bar_index(path: Path, idx: int):
    """目录 list-of-list 模式（"dir:last_bar[N]"，DATA-09 新增，与 dict 版互不改动）。

    与 _dir_last_bar 的两处语义差异（都由实测驱动，不许合并回旧函数）：
    1. 末 bar 是 list，日期 = arr[-1][idx]（fund_cache/cap_hist 的第 0 项）；
    2. mtime 不可信：fund_cache 有 71 个空数组文件占据 mtime 最新位置（2026-10-20 实测），
       若按旧「mtime 前 25 个一刀切」，采样会被空文件吃光而误报 unknown_date。
       因此本形态跳过空/坏文件**不计入** DIR_SAMPLE，只把「能产出有效日期的文件」
       计入样本；总读取数受 DIR_SCAN_CAP 限制（防大规模 schema 漂移时体检超时）。
    读到的最大日期即结果；一个有效文件都没有 → None（unknown_date 由调用方判）。
    """
    if not path.is_dir():
        return None
    try:
        files = sorted(path.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    except Exception:
        return None
    best = None
    sampled = 0
    for fp in files[:DIR_SCAN_CAP]:
        if sampled >= DIR_SAMPLE:
            break
        try:
            arr = json.loads(fp.read_text())
        except Exception:
            continue                       # 半截写入/坏文件：跳过不计数（#330-D3）
        if isinstance(arr, dict):          # 容忍 {"data": [...]} 一层包裹
            arr = next((v for v in arr.values() if isinstance(v, list)), [])
        if not isinstance(arr, list) or not arr or not isinstance(arr[-1], list):
            continue                       # 空数组/非 list-of-list：跳过不计数
        last = arr[-1]
        if idx >= len(last):
            continue
        d = last[idx]
        if isinstance(d, str) and _DATE_RE.match(d):
            sampled += 1
            if best is None or d > best:
                best = d
    return best


def extract_date(path: Path, date_expr: str):
    """按 date_expr 解析末端日期 → "YYYY-MM-DD" 或 None（unknown_date 由调用方判）。

    "none"（DATA-09）：显式不检查，恒返回 None——调用方（assess）据此打
    unknown_date + freshness_unknown=True，「不检查」显式可见而非静默 ok。
    """
    if date_expr == "none":
        return None
    try:
        if date_expr.startswith("dir:"):
            m = _DIR_IDX_RE.match(date_expr.split(":")[1] if ":" in date_expr else "")
            if m:
                return _dir_last_bar_index(path, int(m.group(1)))
            return _dir_last_bar(path, date_expr)
        jsonl = date_expr.endswith("|jsonl")
        expr = date_expr[:-len("|jsonl")] if jsonl else date_expr
        m = _IDX_RE.match(expr)
        if m:                            # "[-1][N]"：list-of-list 末元素第 N 项
            idx = int(m.group(1))
            if jsonl:
                last = None
                with path.open() as f:
                    for line in f:
                        if line.strip():
                            last = line
                obj = json.loads(last) if last else None
            else:
                arr = json.loads(path.read_text())
                obj = arr[-1] if isinstance(arr, list) and arr else None
            if isinstance(obj, list) and idx < len(obj):
                d = obj[idx]
                return d if isinstance(d, str) and _DATE_RE.match(d) else None
            return None
        if expr.startswith("[-1]."):
            if jsonl:
                last = None
                with path.open() as f:
                    for line in f:
                        if line.strip():
                            last = line
                obj = json.loads(last) if last else None
            else:
                arr = json.loads(path.read_text())
                obj = arr[-1] if isinstance(arr, list) and arr else None
            return _dig(obj, expr[len("[-1]."):]) if isinstance(obj, dict) else None
        return _dig(json.loads(path.read_text()), expr)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 注册表加载与配置校验（配置错误 → RegistryError → exit 2）
# ---------------------------------------------------------------------------

def _yaml():
    """PyYAML 加载（含 3.14 无 yaml 的兜底）。load_registry 与本模块白名单共用。"""
    try:
        import yaml
        return yaml
    except ModuleNotFoundError:
        # 2026-10-20 #332/P0：cron runner 的 python3.14 无 PyYAML（四个生产班因此全灭）。
        # 主修复在 wrapper 层（exec venv python，同 #330-A 判据）；此处兜底是为监控机/
        # 熔断器自身的健壮性——freshness_core 是 breaker 与 data_health 的公共依赖，
        # 它崩 = 熔断器崩 = 下游全灭。/opt/data/lazy-packages 有纯 Python PyYAML 6.0.3
        # （其 _yaml C 扩展是 cp313 编译，PyYAML 会自动退回纯 Python 解析，功能无损）。
        import sys as _sys
        _sys.path.insert(0, "/opt/data/lazy-packages")
        import yaml  # noqa: E402
        return yaml


def load_registry(path: str | Path | None = None) -> dict:
    yaml = _yaml()
    fp = Path(path) if path else REGISTRY_YAML
    doc = yaml.safe_load(fp.read_text())
    if not isinstance(doc, dict) or not isinstance(doc.get("datasets"), dict):
        raise RegistryError(f"注册表结构错误：{fp}（缺 datasets 映射）")
    return doc


def validate_registry(doc: dict) -> list[str]:
    """返回配置错误列表（空 = 通过）。fatal 必带 blocks（spec 验收反例 C）。"""
    errors: list[str] = []
    ds = doc.get("datasets") or {}
    consumers = set(doc.get("consumers") or [])
    for key, spec in ds.items():
        if not isinstance(spec, dict):
            errors.append(f"{key}: 条目必须是映射")
            continue
        for fld in REQUIRED_FIELDS:
            if fld not in spec:
                errors.append(f"{key}: 缺必填字段 {fld}")
        sev = spec.get("severity")
        if sev not in SEVERITIES:
            errors.append(f"{key}: severity={sev!r} 非法（须为 {SEVERITIES}）")
        if sev == "fatal" and not spec.get("blocks"):
            errors.append(f"{key}: severity=fatal 但 blocks 为空——fatal 必须声明阻塞面，否则告警无人认领")
        unknown = sorted(set(spec.get("blocks") or []) - consumers)
        if unknown:
            errors.append(f"{key}: blocks 含未登记消费者 {unknown}（须先加进 consumers 清单）")
        ml = spec.get("max_lag")
        if not isinstance(ml, int) or ml < 0:
            errors.append(f"{key}: max_lag 必须是非负整数（{ml!r}）")
    missing = [k for k in (doc.get("mandatory") or []) if k not in ds]
    if missing:
        errors.append(f"mandatory 必注册集缺条目：{missing}（防新数据集绕过注册）")
    return errors


# ---------------------------------------------------------------------------
# 单条目体检
# ---------------------------------------------------------------------------

def assess(key: str, spec: dict, ref_date: str, root: Path = ROOT) -> dict:
    """{key,path,date,status,severity,lag,cadence,max_lag,blocks,owner,reason}

    status 判定：路径缺失→missing；date_expr="none"→unknown_date + freshness_unknown
    （显式不检查，不许静默当 ok）；日期解析不出→unknown_date（禁止降级 ok）；
    lag>max_lag→fatal_lag(severity=fatal) 或 stale(warn/info)；否则 ok。
    日历不可用 → trading_days_between raise（上层按基建错误 exit 2，不许猜）。
    """
    rec = {"key": key, "path": spec["path"], "date": None, "status": None,
           "severity": spec["severity"], "lag": None, "cadence": spec["cadence"],
           "max_lag": spec["max_lag"], "blocks": list(spec["blocks"]),
           "owner": spec["owner"], "reason": ""}
    path = root / spec["path"]
    if not path.exists():
        rec["status"] = "missing"
        rec["reason"] = f"路径不存在：{spec['path']}"
        return rec
    if spec["date_expr"] == "none":
        # DATA-09：无机器可读日期的数据集（如 industry_map）显式不检查新鲜度。
        # dbt/Dagster 同纪律：「不检查」必须显式可见，不许静默当 ok（契约基线 §1）。
        # status=unknown_date → 不进 ok 计数、进 ⚠️ 段；severity=info → 不阻断。
        rec["status"] = "unknown_date"
        rec["freshness_unknown"] = True
        rec["reason"] = ("date_expr=\"none\"：该数据集无机器可读日期，显式不做新鲜度检查"
                         "（freshness_unknown，靠人工复核；见注册表 note）")
        return rec
    date = extract_date(path, spec["date_expr"])
    rec["date"] = date
    if date is None:
        rec["status"] = "unknown_date"
        rec["reason"] = f"date_expr {spec['date_expr']!r} 解析不出 YYYY-MM-DD（表达式写错或产物结构变了）"
        return rec
    lag = trading_days_between(date, ref_date)
    rec["lag"] = lag
    if lag > spec["max_lag"]:
        rec["status"] = "fatal_lag" if spec["severity"] == "fatal" else "stale"
        rec["reason"] = f"滞后 {lag} 交易日 > max_lag {spec['max_lag']}（末端 {date}，基准 {ref_date}）"
    else:
        rec["status"] = "ok"
        if date > ref_date:
            rec["reason"] = f"末端 {date} 超前于基准 {ref_date}（次日执行件/预写，正常）"
    return rec

# ---------------------------------------------------------------------------
# 退市/停牌白名单 + 目录级覆盖率（DATA-06 补，AGENTS #353）
# ---------------------------------------------------------------------------
# 三类语义（与 data/stale_whitelist.yaml 头注释同源，改一边必须改另一边）：
#   退市股   永远停更，从覆盖率分母剔除（停在退市日是对的）；
#   停牌股   还会复牌，留在分母，滞后单列 suspended（仍要报，不许静默豁免）；
#   其余停更 数据源/生产者事故，计入 stale_active，阈值降级由 data_health 执行。
# ---------------------------------------------------------------------------

def load_whitelist(path: str | Path | None = None) -> dict:
    """→ {"delisted": set[str], "suspended": {code: info}}。

    文件缺失/损坏 → 空集（白名单是分母修正的优化，不是闸：没了它覆盖率只是变保守，
    不许让体检崩）。delisted = source 名单 − exclude（锚点误伤）∪ additions（基准日后新退市）。
    """
    fp = Path(path) if path else WHITELIST_YAML
    try:
        doc = _yaml().safe_load(fp.read_text()) or {}
        dl = doc.get("delisted") or {}
        src = Path(dl.get("source") or "")
        if not src.is_absolute():
            src = ROOT / src
        codes = set()
        if src.exists():
            raw = _json_load_silent(src) or {}
            codes = set(raw.get("codes") or [])
        codes -= set(dl.get("exclude") or [])
        codes |= set((dl.get("additions") or {}).keys())
        susp = doc.get("suspended") or {}
        return {"delisted": codes, "suspended": susp if isinstance(susp, dict) else {}}
    except Exception:
        return {"delisted": set(), "suspended": {}}


def _json_load_silent(path: Path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return None


_CODE_RE = re.compile(r"(\d{6})")
_TAIL_BYTES = 1024  # 单文件末 bar ~150B，1KB 覆盖约 5 根 bar（目录文件均为单行 JSON，实测）


def _stem_code(stem: str) -> str:
    """文件名 → 6 位代码：big_kcache/fund_cache 用裸代码，kcache 用 sh600176 前缀。"""
    m = _CODE_RE.search(stem)
    return m.group(1) if m else stem


def _tail_last_date(fp: Path, field: str | None):
    """读文件尾 1KB 取最后一个 YYYY-MM-DD（field 指定时要求 "field": "date" 形态）。

    不整文件 json.loads：big_kcache 3377 文件 ×130KB ≈ 440MB，超体检 60s/300MB 纪律；
    单行 JSON 的末 bar 必在尾部，正则末匹配即可。空数组/坏文件 → None（计入 empty）。
    """
    try:
        with fp.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - _TAIL_BYTES))
            tail = f.read().decode("utf-8", errors="ignore")
    except Exception:
        return None
    if field:
        hits = re.findall(r'"%s"\s*:\s*"(\d{4}-\d{2}-\d{2})"' % re.escape(field), tail)
    else:
        hits = re.findall(r"\d{4}-\d{2}-\d{2}", tail)
    return hits[-1] if hits else None


def dir_coverage(path: Path, date_expr: str, ref_date: str, max_lag: int,
                 whitelist: dict | None = None) -> dict:
    """目录类数据集的逐文件覆盖率（只看末端日期，与 dir:last_bar 同口径）。

    → {total, empty, delisted_excluded, active, current, suspended, stale_active,
       coverage_pct}；suspended/stale_active 是 code 列表（stale_active 截断 50 防爆）。
    日历不可用 → trading_days_between raise（与 assess 同纪律，上浮 exit 2，不许猜）。
    """
    wl = whitelist or {"delisted": set(), "suspended": {}}
    delisted, suspended = set(wl.get("delisted") or set()), dict(wl.get("suspended") or {})
    # date_expr 形态 → 末 bar 日期字段（dict-bar 目录用字段名；list-of-list 用裸日期）
    field = None
    if date_expr.startswith("dir:"):
        parts = date_expr.split(":")
        if len(parts) > 2 and parts[2] and not _DIR_IDX_RE.match(parts[2]):
            field = parts[2]
    res = {"total": 0, "empty": 0, "delisted_excluded": 0, "active": 0, "current": 0,
           "suspended": [], "stale_active": [], "stale_active_total": 0, "coverage_pct": None}
    if not path.is_dir():
        return res
    for fp in sorted(path.glob("*.json")):
        res["total"] += 1
        code = _stem_code(fp.stem)
        d = _tail_last_date(fp, field)
        if d is None:
            res["empty"] += 1
            continue
        if code in delisted:
            res["delisted_excluded"] += 1     # 退市股：停在退市日是对的，不进分母
            continue
        res["active"] += 1
        if trading_days_between(d, ref_date) <= max_lag:
            res["current"] += 1
        elif code in suspended:
            res["suspended"].append(code)     # 停牌股：滞后仍要报，单列不豁免
        else:
            res["stale_active_total"] += 1
            if len(res["stale_active"]) < 50:
                res["stale_active"].append(code)
    if res["active"]:
        res["coverage_pct"] = round(res["current"] / res["active"] * 100, 1)
    return res


# ---------------------------------------------------------------------------
# 展示级新鲜度（build_daily_state 收编，2026-10-20 #332/P2）
# 这是 bds 的**旧展示口径**：字符串比日期、无交易日概念、无 severity，产物契约是
# {file, mtime, date_field, date, status}（status ∈ ok/stale/missing/unknown_date），
# 供日度状态包/面板做「逐源清单」展示。它与 assess() 的治理口径（交易日滞后 × severity
# × blocks）**刻意并存**：前者是展示，后者是熔断/告警判决。收编只把判定出处收到本模块
# （单一定义原则），口径一字未改（纯重构纪律：同输入输出逐字节一致）。
# 新代码禁止再引这套展示口径——治理判定一律走 assess()/is_blocking()。
# ---------------------------------------------------------------------------

def legacy_fresh_status(date_value, ref_date) -> str:
    """bds 旧判定：无日期 → unknown_date；有 ref_date 则字符串比较 ok/stale；无 ref → ok。"""
    if not date_value:
        return "unknown_date"
    if ref_date:
        return "ok" if date_value >= ref_date else "stale"
    return "ok"


def mtime_bjt(path) -> str:
    """文件 mtime 的 BJT「YYYY-MM-DD HH:MM」；读不到 → "unknown"。"""
    try:
        return datetime.fromtimestamp(Path(path).stat().st_mtime,
                                      timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "unknown"


def legacy_fresh_entry(root, rel, date_field, date_value, ref_date) -> dict:
    """bds 新鲜度条目（产物契约见本节头注释）；路径不存在 → status=missing。"""
    p = Path(root) / rel
    if not p.exists():
        return {"file": rel, "mtime": "unknown", "date_field": date_field,
                "date": None, "status": "missing"}
    return {"file": rel, "mtime": mtime_bjt(p), "date_field": date_field,
            "date": date_value, "status": legacy_fresh_status(date_value, ref_date)}
