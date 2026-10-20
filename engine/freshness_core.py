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
  "[-1].date|jsonl"   JSONL 末行的 date 字段
  "_meta.date"        JSON 字典的 dotted 路径（如 "sig_date"）
  "dir:last_bar[:字段]" 目录模式：取最近写入的 ≤25 个 .json，读各自末 bar 的日期字段
                      （默认 "date"，新浪缓存用 "dir:last_bar:day"），取最大值。
                      spec 风险 2：本期 freshness 只看末端日期，不看覆盖率。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
CAL_DIR = ROOT / "data" / "trade_calendar"
REGISTRY_YAML = ROOT / "data" / "datasets_registry.yaml"

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
DIR_SAMPLE = 25          # 目录模式最多读的近期文件数（体检 <60s/<300MB 纪律）
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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


def extract_date(path: Path, date_expr: str):
    """按 date_expr 解析末端日期 → "YYYY-MM-DD" 或 None（unknown_date 由调用方判）。"""
    try:
        if date_expr.startswith("dir:"):
            return _dir_last_bar(path, date_expr)
        jsonl = date_expr.endswith("|jsonl")
        expr = date_expr[:-len("|jsonl")] if jsonl else date_expr
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

def load_registry(path: str | Path | None = None) -> dict:
    import yaml
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

    status 判定：路径缺失→missing；日期解析不出→unknown_date（禁止降级 ok）；
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
