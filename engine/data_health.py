#!/usr/bin/env python3
"""engine/data_health.py — 数据面监控机（DATA-01，与 line_health.py 同构）

读声明式注册表 data/datasets_registry.yaml → 体检全部数据集的时效/存在性 →
落四输出 + 幂等状态 + 晨报段。使「数据断供」在下游被静默消费之前就变成一条
可见的 fatal 告警（#330-A/B：kcache 冻三天、权威时间轴停两天，下游照常跑）。

只读+落盘，**不自动补数、不自动重跑生产者**（纪律同 line_health #278）。
严禁联网抓数：交易日历只读本地缓存（freshness_core 口径），日历不可用 → exit 2。

输出（INTERFACES I0：UTF-8 无 BOM，原子写）：
  data/data_health.json        机器可读全量（_meta 带 version/date/generated_at）
  data/data_health_state.json  阈值机状态（同日重跑覆盖当日记录，不重复计数）
  data/data_health_report.md   晨报/作战单段落
  data/health/YYYY-MM-DD.json  时序快照（按 BJT 运行日，同日重跑覆盖）
stdout：仅「新增 fatal 触发」时打印（看门狗纪律：无触发零输出）；
       配置/基建错误（exit 2）打印错误本身——这也是触发。

用法：
  .venv/bin/python engine/data_health.py [--ref-date YYYY-MM-DD] [--report]
                                         [--only KEY ...] [--registry PATH]
                                         [--outputs-dir DIR]
退出码：0=无 fatal；1=存在 fatal_lag/missing/unregistered（cron 报红）；
        2=配置错误（fatal 无 blocks 等）或基建错误（交易日历不可用）。
--ref-date 默认 = 最近已收盘交易日（交易日 16:00 前取前一交易日，防盘前误报）。
--outputs-dir 供反例/沙盒体检把四输出写到别处，不污染生产产物。
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
sys.path.insert(0, str(ROOT / "engine"))
import freshness_core as fc  # noqa: E402

VERSION = "data_health/1.0 (2026-10-20, DATA-01)"
DATA = ROOT / "data"
SEAM_SIDE = DATA / "seam_metrics.json"  # DATA-07：update_kcache 的 SEAM-FIX 指标化侧车
SEAM_ABNORMAL_STREAK_DEMOTE = 2  # 连续 N 个记录日 seam_err>0 → big_kcache 降为 stale


def load_seam_metrics() -> dict | None:
    """读 SEAM 侧车（DATA-07）。缺失/损坏 → None（kcache 班没跑过或落盘失败，不算错误）。

    返回 {"today": {当日累计或 None}, "abnormal_streak_days": n, "days": {...}}。
    异常定义（写死）：seam_err > 0（复权漂移后全量重拉失败/行数异常）——
    seam_fixed 本身不是病（分红送配后重拉是正常维护），重拉失败才是。
    """
    try:
        st = json.loads(SEAM_SIDE.read_text())
        days = st.get("days") or {}
        if not isinstance(days, dict):
            return None
        today = bjt_now().date().isoformat()
        streak = 0
        for d in sorted(days, reverse=True):  # 从最新记录日往回数连续异常
            if (days[d] or {}).get("seam_err", 0) > 0:
                streak += 1
            else:
                break
        return {"today": days.get(today), "abnormal_streak_days": streak,
                "days": days, "updated_at": st.get("updated_at")}
    except Exception:
        return None


def bjt_now() -> datetime:
    """带 +08:00 时区的北京当前时刻（INTERFACES I0：时间戳必须 ISO8601 带时区）。"""
    return datetime.now(timezone(timedelta(hours=8)))


def default_ref_date() -> str:
    """最近已收盘交易日：交易日 16:00 BJT 后为今天，否则前一交易日（含周末/假日回退）。

    9:25 作战单在盘前消费：若基准取「今天」，昨晚数据必被误判滞后 1 天（假 fatal）。
    """
    now = bjt_now()
    today = now.date().isoformat()
    if fc.is_trading_day(today) and now.hour >= 16:
        return today
    return fc.prev_trading_day(today)


# ---------------------------------------------------------------------------
# 体检
# ---------------------------------------------------------------------------

def check_all(ref_date: str | None = None, only: list[str] | None = None,
              registry_path: str | None = None) -> dict:
    """{_meta:{version,date,generated_at,registry_version}, items:{key:{...}}, summary:{...}}

    零写盘。配置错误 → RegistryError；日历不可用 → CalendarUnavailable（都由 main 兜底 exit 2）。
    """
    doc = fc.load_registry(registry_path)
    errors = fc.validate_registry(doc)
    if errors:
        raise fc.RegistryError("；".join(errors))
    ref = ref_date or default_ref_date()
    items: dict[str, dict] = {}
    for key, spec in (doc.get("datasets") or {}).items():
        if only and key not in only:
            continue
        items[key] = fc.assess(key, spec, ref, ROOT)
    # 必注册集缺条目 → unregistered（伪条目，防新数据集绕过注册）
    for key in (doc.get("mandatory") or []):
        if key not in items and key not in (doc.get("datasets") or {}):
            if only and key not in only:
                continue
            items[key] = {"key": key, "path": None, "date": None, "status": "unregistered",
                          "severity": "fatal", "lag": None, "cadence": None, "max_lag": None,
                          "blocks": [], "owner": None,
                          "reason": "在 mandatory 必注册集但未注册——监控机对它失明"}
    # DATA-07 SEAM-FIX 指标化：连续多日 seam 异常（重拉失败）→ big_kcache 由 ok 降为 stale
    # （spec 接口契约）。stale 不阻断（warn 级），但进报告 ⚠️ 段——接缝腐蚀是慢性病，
    # 不配 fatal 的「断供」语义。只降不升：本来就 fatal/stale 的不动。
    seam = load_seam_metrics()
    if seam and seam["abnormal_streak_days"] >= SEAM_ABNORMAL_STREAK_DEMOTE:
        bk = items.get("big_kcache")
        if bk and bk["status"] == "ok":
            bk["status"] = "stale"
            bk["reason"] = (bk["reason"] + "；" if bk["reason"] else "") + \
                (f"SEAM 连续 {seam['abnormal_streak_days']} 个记录日重拉失败"
                 f"（seam_err>0，见 data/seam_metrics.json）→ 降级 stale")
    summary = {s: 0 for s in fc.STATUSES}
    for it in items.values():
        summary[it["status"]] += 1
    summary["total"] = len(items)
    # 注册表**内容指纹**（2026-10-20 补）：手写的 registry_version 在有人改 path/severity/blocks 时不会变，
    # 拿它当"配置一致性凭证"必然失真。fingerprint = 注册表文件字节 md5，改一个字节就变。
    # 用途见 breaker._load_health：指纹不一致 = 体检结论可能出自从前的注册表 → 熔断判定不可信，必须显式暴露。
    import hashlib as _hl
    try:
        _reg_bytes = (ROOT / "data/datasets_registry.yaml").read_bytes()
        _reg_fp = _hl.md5(_reg_bytes).hexdigest()
    except Exception:
        _reg_fp = None
    result = {"_meta": {"version": VERSION, "date": bjt_now().date().isoformat(),
                        "generated_at": bjt_now().isoformat(timespec="seconds"),
                        "registry_version": doc.get("registry_version"),
                        "registry_fingerprint": _reg_fp,
                        "ref_date": ref, "ref_source": "--ref-date" if ref_date else "auto(最近已收盘交易日)",
                        "discipline": "read-only + 落盘 + 提案；不自动补数/重跑（#278 同纪律）"},
              "items": items, "summary": summary}
    if seam:  # metrics.seam：当日 SEAM-FIX 计数进体检产物（spec 验收：数值 == 当日 SEAM-FIX 计数）
        result["metrics"] = {"seam": seam}
    return result


# ---------------------------------------------------------------------------
# 阈值机状态（按日幂等；新增 fatal 才告警）
# ---------------------------------------------------------------------------

def threshold_machine(result: dict, state_path: Path) -> tuple[dict, list[str]]:
    today = bjt_now().date().isoformat()
    try:
        st = json.loads(state_path.read_text())
    except Exception:
        st = {}
    items_state = st.setdefault("items", {})
    alerts: list[str] = []
    for key, it in result["items"].items():
        e = items_state.setdefault(key, {"history": [], "bad_since": None,
                                         "fatal_days": 0, "fatal_active": False})
        hist = [h for h in e["history"] if h["date"] != today]  # 同日重跑覆盖=幂等
        hist.append({"date": today, "status": it["status"], "sev": it.get("severity"),
                     "lag": it["lag"], "ref": result["_meta"]["ref_date"]})
        e["history"] = hist[-30:]
        is_fatal = fc.is_blocking(it["status"], it.get("severity"))
        # 新增触发才告警（line_health threats 段同形态）：fatal_active 是跨重跑持续的
        # 标志位——同日重跑/连续多日同故障都不重复吵，恢复后再断才重新告警。
        if is_fatal and not e.get("fatal_active"):  # .get：兼容手写/旧版 state
            blocks = "、".join(it.get("blocks") or []) or "（未声明阻塞面）"
            alerts.append(f"[数据断供] {key}：{it['status']}（{it['reason']}）→ 静默污染下游：{blocks}；"
                          f"owner={it.get('owner')}——监控机只告警不自动补数")
        e["fatal_active"] = is_fatal
        streak = 0
        for h in reversed(e["history"]):
            if fc.is_blocking(h["status"], h.get("sev")):
                streak += 1
            else:
                break
        e["fatal_days"] = streak
        e["bad_since"] = e["history"][-streak]["date"] if streak else None
    st["updated_at"] = bjt_now().isoformat(timespec="seconds")
    st["date"] = today
    _atomic_write(state_path, json.dumps(st, ensure_ascii=False, indent=1))
    return st, alerts


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def render_report(result: dict, state: dict) -> str:
    meta, items, summary = result["_meta"], result["items"], result["summary"]
    L = [f"# 数据面监控 · {meta['date']}（体检基准 ref={meta['ref_date']}，{meta['ref_source']}）",
         "",
         f"注册 {summary['total']} 项：" +
         " · ".join(f"{s} {summary[s]}" for s in fc.STATUSES if summary[s]),
         f"version={meta['version']} · registry={meta['registry_version']} · generated_at={meta['generated_at']}",
         ""]
    istate = (state or {}).get("items") or {}
    fatal = [it for it in items.values() if fc.is_blocking(it["status"], it.get("severity"))]
    L.append(f"## 🚨 致命（{len(fatal)} 项，断供=下游结论不可信）")
    if fatal:
        for it in sorted(fatal, key=lambda x: x["key"]):
            days = (istate.get(it["key"]) or {}).get("fatal_days", 1)
            L.append(f"- **{it['key']}** `{it['status']}`：{it['reason']}（连续 {days} 天）")
            L.append(f"  阻塞：{'、'.join(it['blocks']) or '（未声明）'} ｜ owner：{it['owner']}")
    else:
        L.append("（无）")
    L.append("")
    degraded = [it for it in items.values() if it["status"] in ("stale", "unknown_date")
                and not fc.is_blocking(it["status"], it.get("severity"))]
    L.append(f"## ⚠️ 滞后/日期异常（{len(degraded)} 项）")
    if degraded:
        for it in sorted(degraded, key=lambda x: x["key"]):
            L.append(f"- **{it['key']}** `{it['status']}`：{it['reason']} ｜ owner：{it['owner']}")
    else:
        L.append("（无）")
    L += ["", "## 明细", "",
          "| key | status | severity | 末端日期 | lag(交易日) | max_lag | owner |",
          "|---|---|---|---|---|---|---|"]
    for key in sorted(items):
        it = items[key]
        L.append(f"| {key} | {it['status']} | {it['severity']} | {it['date'] or '—'} | "
                 f"{'—' if it['lag'] is None else it['lag']} | "
                 f"{'—' if it['max_lag'] is None else it['max_lag']} | {it['owner'] or '—'} |")
    L.append("")
    return "\n".join(L)


def write_outputs(result: dict, out_dir: Path) -> tuple[dict, list[str]]:
    state, alerts = threshold_machine(result, out_dir / "data_health_state.json")
    _atomic_write(out_dir / "data_health.json", json.dumps(result, ensure_ascii=False, indent=1))
    _atomic_write(out_dir / "data_health_report.md", render_report(result, state))
    snap = out_dir / "health" / f"{bjt_now().date().isoformat()}.json"
    _atomic_write(snap, json.dumps(result, ensure_ascii=False, indent=1))
    return state, alerts


# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DATA-01 数据面监控机")
    ap.add_argument("--ref-date", default=None, help="体检基准日 YYYY-MM-DD（默认=最近已收盘交易日）")
    ap.add_argument("--report", action="store_true", help="强制打印晨报段落")
    ap.add_argument("--only", nargs="+", default=None, help="只体检指定 key（调试用）")
    ap.add_argument("--registry", default=None, help="注册表路径（默认 data/datasets_registry.yaml）")
    ap.add_argument("--outputs-dir", default=None, help="四输出落盘目录（默认 data/，沙盒体检用）")
    args = ap.parse_args(argv)
    out_dir = Path(args.outputs_dir) if args.outputs_dir else DATA

    t0 = time.time()
    try:
        result = check_all(args.ref_date, args.only, args.registry)
    except fc.RegistryError as e:
        print(f"【数据面监控·配置错误】{e}")          # 配置错误也是触发，必须发声
        return 2
    except fc.CalendarUnavailable as e:
        print(f"【数据面监控·基建错误】交易日历不可用：{e}——不许猜节假日，体检中止")
        return 2
    result["_meta"]["elapsed_s"] = round(time.time() - t0, 2)
    state, alerts = write_outputs(result, out_dir)
    if alerts:
        print(f"【数据面告警 {result['_meta']['date']}】（ref={result['_meta']['ref_date']}）")
        for a in alerts:
            print(a)
    if args.report:
        print(render_report(result, state))
    has_fatal = any(fc.is_blocking(it["status"], it.get("severity")) for it in result["items"].values())
    return 1 if has_fatal else 0


if __name__ == "__main__":
    sys.exit(main())
