#!/usr/bin/env python3
"""engine/breaker.py — 熔断泛化（DATA-07，spec docs/plan/specs/DATA-07-circuit-breaker.md 裁决修订 R1）

数据不合格时下游拒写/降级，而不是只在报告里告警。三类语义（R1，写死在本文件）：

  ① WRITE_BLOCK  追加型/记账型：命中阻断项 → 不写盘 + 记事件 + 调用方非零退出
                 （写进历史序列就永久污染：权威时间轴/X规则线/影子盘）
  ② DEGRADE_MARK 展示型：照写，但产物必须带 data_stale:true + 依赖项清单
                 （拒写会让用户在数据断供时什么都收不到，比带警告的次优产物更糟）
  ③ EXEMPT       检查器/告警通道：恒放行（熔断告警器=掐断告警，明令禁止）。
                 本表写死在此，**禁止由注册表 blocks 决定**——否则给注册表加一行
                 就能静音告警器。

判定口径：freshness_core.is_blocking 是唯一阻断口径，禁止在此另写状态元组。
输入：data/data_health.json（DATA-06 产物，20:35 体检班落盘）+ 注册表 blocks。
性能纪律：优先复用 data_health.json 的体检结论；仅当调用方 ref_date 与体检基准
不一致时，对该 writer 相关的数据集做增量时效判定（不重跑全量体检）。

fail-open：data_health.json 缺失/损坏 → 全部放行，但必须写 breaker_events.jsonl
记录"health 未知"（监控机自己挂了不许让全线停摆，事后可审计）。
回滚开关：data/breaker_disabled.flag 存在即全部放行（仍记事件）。

边界（spec R1-④）：只覆盖注册表 consumers 点名的生产下游；engine/ 下 200+
研究脚本可重跑、产物可弃、不喂生产，**不在熔断范围**。
未登记的 writer 调 allow() → raise UnknownWriterError（新增生产下游必须先登记，
不登记就绕过熔断比不熔断更糟）。

用法：
  import breaker
  ok, reason = breaker.allow("权威时间轴")            # WRITE_BLOCK：False 则不写盘+exit 1
  mark = breaker.stale_mark("面板20:40")              # DEGRADE_MARK：产物带 mark
  # mark = {"data_stale": bool, "stale_datasets": [...], "reason": str}
CLI：
  .venv/bin/python engine/breaker.py <writer> [ref_date]   # 阻断 → exit 1
  .venv/bin/python engine/breaker.py --mark <writer> [ref_date]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
sys.path.insert(0, str(ROOT / "engine"))
import freshness_core as fc  # noqa: E402

DATA = ROOT / "data"
HEALTH_JSON = DATA / "data_health.json"
EVENTS = DATA / "breaker_events.jsonl"
DISABLE_FLAG = DATA / "breaker_disabled.flag"

# ── 三类语义（R1 裁决，写死；EXEMPT 尤其不许改由注册表驱动）──
WRITE_BLOCK = {"权威时间轴", "X规则线", "影子盘"}
DEGRADE_MARK = {"作战单9:25", "面板20:40", "日度状态包", "深档名单", "周期仪"}
# 2026-10-20：移除"晨报"——从未实现的下游（注册表登记了依赖，但 cron 无作业、line_health_report 零引用）。
# 留一个不存在的名字会让豁免表看起来比实际更宽。
EXEMPT_WRITERS = {"盘前自检", "line_health", "data_health", "回测族"}
KNOWN_WRITERS = WRITE_BLOCK | DEGRADE_MARK | EXEMPT_WRITERS


class UnknownWriterError(ValueError):
    """未登记的 writer：新增生产下游必须先在本文件登记类别，防绕过熔断。"""


def _bjt_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=8)))


def _log_event(writer: str, ref_date, blocking: list, decision: str, reason: str) -> None:
    """追加事件（审计线索）。事件写不进不许拖垮下游——吞异常但留 stderr。"""
    rec = {"ts": _bjt_now().isoformat(timespec="seconds"),
           "ref_date": ref_date, "writer": writer,
           "blocking_datasets": [b["key"] for b in blocking],
           "blocking_detail": blocking,
           "decision": decision, "reason": reason}
    try:
        with EVENTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[breaker][WARN] 事件落盘失败：{e}", file=sys.stderr)


def _load_health() -> dict | None:
    """读体检产物；缺失/损坏/结构不对 → None（fail-open 由调用方执行）。"""
    try:
        h = json.loads(HEALTH_JSON.read_text(encoding="utf-8"))
        if not isinstance(h, dict) or not isinstance(h.get("items"), dict):
            return None
        return h
    except Exception:
        return None


def _registry_drift(health: dict, root: Path = ROOT) -> str | None:
    """体检产物里的注册表指纹 vs 当前注册表 → 不一致返回说明串，一致/无法判定返回 None。

    2026-10-20 补（主 agent 审计发现）：熔断依赖 data_health.json 的**缓存结论**。若注册表被改
    （新增数据集 / 改 path / 改 severity）而体检没重跑，熔断会拿旧结论静默放行——看起来在拦，
    其实没拦，与"unknown_date 报绿""空 verdicts 判通过"同族。手写的 registry_version 挡不住这个
    （改配置的人不会记得改版本号），所以用内容指纹。
    无法判定（旧产物缺该字段）时返回 None 不阻断——避免升级后所有下游都被警告淹没。
    """
    import hashlib
    fp = ((health.get("_meta") or {}).get("registry_fingerprint"))
    if not fp:
        return None
    try:
        cur = hashlib.md5((root / "data/datasets_registry.yaml").read_bytes()).hexdigest()
    except Exception:
        return None
    if cur == fp:
        return None
    return (f"注册表内容指纹不一致（体检产物 {fp[:8]}… vs 当前 {cur[:8]}…）"
            f"——体检结论出自从前的注册表，本轮熔断判定不可信")


def _relevant_specs(writer: str, root: Path = ROOT) -> dict:
    """注册表里 blocks 点名该 writer 的数据集 {key: spec}。"""
    doc = fc.load_registry()
    return {k: s for k, s in (doc.get("datasets") or {}).items()
            if isinstance(s, dict) and writer in (s.get("blocks") or [])}


def _blocking_datasets(writer: str, ref_date: str | None, root: Path = ROOT):
    """→ (blocking list[dict] | None, ref_used)。blocking=None 表示 health 未知（fail-open）。"""
    specs = _relevant_specs(writer, root)
    health = _load_health()
    if health is None:
        return None, ref_date
    health_ref = (health.get("_meta") or {}).get("ref_date")
    ref = ref_date or health_ref
    blocking: list[dict] = []
    for key, spec in specs.items():
        it = None
        if ref == health_ref:
            it = (health["items"] or {}).get(key)  # 快路径：直接复用体检结论
        if it is None:
            # ref 与体检基准不一致（或条目缺失）→ 只对该数据集做增量时效判定，
            # 不重跑全量体检（性能纪律）。日历不可用 → 上浮（基建错误不许猜）。
            # ref 走到这里必为 str：ref 为 None 只可能是 health_ref 也是 None，
            # 而那时 ref == health_ref 已在上面的快路径命中。
            assert isinstance(ref, str), "ref_date 缺失且体检基准缺失——health json 结构异常"
            it = fc.assess(key, spec, ref, root)
        if fc.is_blocking(it.get("status") or "", it.get("severity")):
            blocking.append({"key": key, "status": it.get("status"),
                             "severity": it.get("severity"), "reason": it.get("reason")})
    return blocking, ref


def _decide(writer: str, ref_date: str | None, root: Path = ROOT) -> dict:
    """三类语义的唯一判定函数（allow/stale_mark 都是它的薄壳，防两处出结论）。"""
    if writer not in KNOWN_WRITERS:
        raise UnknownWriterError(
            f"writer {writer!r} 未登记：生产下游必须先登记进 breaker.py 的三类表 "
            f"（WRITE_BLOCK/DEGRADE_MARK/EXEMPT_WRITERS）——不登记就绕过熔断，比不熔断更糟")
    if DISABLE_FLAG.exists():
        reason = "data/breaker_disabled.flag 存在：熔断全局关闭（spec 回滚开关），全部放行"
        _log_event(writer, ref_date, [], "disabled", reason)
        return {"allow": True, "data_stale": False, "stale_datasets": [],
                "decision": "disabled", "reason": reason, "ref_date": ref_date}
    if writer in EXEMPT_WRITERS:
        reason = "exempt：检查器/告警通道永不熔断（豁免表写死在 breaker.py，注册表改不动它）"
        _log_event(writer, ref_date, [], "exempt", reason)
        return {"allow": True, "data_stale": False, "stale_datasets": [],
                "decision": "exempt", "reason": reason, "ref_date": ref_date}
    blocking, ref = _blocking_datasets(writer, ref_date, root)
    # 注册表漂移闸（2026-10-20 补）：体检产物的注册表指纹与当前不一致 → 结论不可信。
    # 行为选 fail-open + data_stale=True，权衡如下：
    #   fail-closed 会让"改了注册表还没重跑体检"这个几分钟的窗口把全线停摆（用户什么都收不到），
    #   而漂移本身不意味着数据坏；放行但打标 + 事件留痕，既能继续产出又不谎报"数据没问题"。
    # 注意 stale=True 对 DEGRADE_MARK 意味着产物带 data_stale，对 WRITE_BLOCK 意味着照写——
    # 这是有意为之：无法判定时宁可产出可追责的东西，也不静默停摆。
    if blocking is not None:
        _h = _load_health()
        _drift = _registry_drift(_h, root) if _h else None
        if _drift:
            _log_event(writer, ref, [], "stale_health", _drift)
            import sys as _sys
            print(f"⚠️  {_drift}", file=_sys.stderr)
            return {"allow": True, "data_stale": True, "stale_datasets": ["<registry_drift>"],
                    "decision": "stale_health", "reason": _drift, "ref_date": ref}
    if blocking is None:
        reason = "health 未知（data_health.json 缺失/损坏）→ fail-open 放行；监控机自身故障不许全线停摆"
        _log_event(writer, ref, [], "fail_open", reason)
        return {"allow": True, "data_stale": False, "stale_datasets": [],
                "decision": "fail_open", "reason": reason, "ref_date": ref}
    if not blocking:
        return {"allow": True, "data_stale": False, "stale_datasets": [],
                "decision": "allow", "reason": "ok", "ref_date": ref}
    names = "、".join(f'{b["key"]}[{b["status"]}]' for b in blocking)
    detail = "；".join(b["reason"] or "" for b in blocking)
    if writer in WRITE_BLOCK:
        reason = f"被 {names} 阻断（{detail}）——追加型下游拒写，防历史序列永久污染"
        _log_event(writer, ref, blocking, "blocked", reason)
        return {"allow": False, "data_stale": False, "stale_datasets": [],
                "decision": "blocked", "reason": reason, "ref_date": ref}
    # DEGRADE_MARK：照写但打标
    reason = f"降级放行（照写+data_stale 标记）：{names}（{detail}）"
    _log_event(writer, ref, blocking, "degraded", reason)
    return {"allow": True, "data_stale": True,
            "stale_datasets": [f'{b["key"]}[{b["status"]}]' for b in blocking],
            "decision": "degraded", "reason": reason, "ref_date": ref}


def allow(writer: str, ref_date: str | None = None, root: Path = ROOT) -> tuple[bool, str]:
    """spec 接口契约：writer 被任一阻断数据集点名 → (False, 原因)。

    EXEMPT 恒 True；WRITE_BLOCK 命中阻断项 → False；DEGRADE_MARK → True（stale 标记
    走 stale_mark() 取结构化 payload）；未登记 writer → raise UnknownWriterError。
    data_health.json 缺失/损坏 → (True, "health 未知…") fail-open 且记事件。
    ref_date=None → 用体检基准日（推荐生产路径；显式历史补跑日才传具体日期）。
    """
    d = _decide(writer, ref_date, root)
    return d["allow"], d["reason"]


def stale_mark(writer: str, ref_date: str | None = None, root: Path = ROOT) -> dict:
    """DEGRADE_MARK 下游打标用：{"data_stale": bool, "stale_datasets": [...], "reason": str}。

    正常 → data_stale=False。对 WRITE_BLOCK  writer 调用本函数等价于 allow() 的判定，
    但被阻断时仍返回 data_stale=False + reason 说明 blocked（拒写语义由调用方执行）。
    """
    d = _decide(writer, ref_date, root)
    return {"data_stale": d["data_stale"], "stale_datasets": d["stale_datasets"],
            "decision": d["decision"], "reason": d["reason"], "ref_date": d["ref_date"],
            "allow": d["allow"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DATA-07 熔断判定 CLI")
    ap.add_argument("--mark", action="store_true", help="输出 stale_mark 结构化 payload")
    ap.add_argument("writer")
    ap.add_argument("ref_date", nargs="?", default=None)
    args = ap.parse_args(argv)
    if args.mark:
        print(json.dumps(stale_mark(args.writer, args.ref_date), ensure_ascii=False, indent=1))
        return 0
    ok, reason = allow(args.writer, args.ref_date)
    print(json.dumps({"writer": args.writer, "allow": ok, "reason": reason},
                     ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
