#!/usr/bin/env python3
"""engine/lineage.py — DATA-08 一期：血缘表（影响半径查询 + 加载时机械断言）

唯一真源 spec：docs/plan/specs/DATA-08-lineage.md（「自检修订 R1」优先于正文）。

一期范围（本次施工）：
  - data/lineage.yaml：dataset → direct（下游名）→ artifacts（glob）→ reports
  - impact(dataset_key)：某数据集断供时，哪些下游/产物/报告受影响
  - validate()：加载血缘表时强制执行的三条机械断言（一期验收本体，R1-③）：
      ① 每个下游 producer 指向的脚本真实存在（Path.exists()）
      ② 每个 artifacts glob 至少命中一个真实文件；当前确实无产物的条目必须显式
        标 allow_empty: true + allow_empty_reason（白名单可见，不许静默放宽）
      ③ trigger 写 cron job id 须能在 cron 快照（tests/golden/cron_snapshot.json，
        `hermes cron list` 的离线落盘）里查到；写 manual 须指向「文档路径:行号」，
        且该文件存在、该行确实含 producer 脚本名（防 manual 成逃生舱，R1-④）
    结构断言：direct 逐字 == 注册表 blocks；下游名 ∈ 注册表 consumers 封闭清单；
    血缘表覆盖全部注册数据集、不许出现未注册数据集。

二期（明确不在本期，阻塞于 DATA-08b）：
  stale_claims() —— claims_registry.yaml 没有 inputs 字段（2026-10-20 实测 grep=0），
  每条主张未声明依赖的数据集，没有数据源。此处只留显式 NotImplementedError 占位，
  不伪实现、不返回空列表冒充。

CLI：
  .venv/bin/python engine/lineage.py <dataset_key>   # 打印影响半径；数据集不存在 → 退出码 2
  .venv/bin/python engine/lineage.py --check          # 只跑 validate()，通过 → 退出码 0
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path("/opt/data/fenjue")
LINEAGE_YAML = ROOT / "data/lineage.yaml"
REGISTRY_YAML = ROOT / "data/datasets_registry.yaml"


class LineageError(ValueError):
    """血缘表结构/机械断言失败，或查询了未注册的数据集。不许静默返回空。"""


def _bjt_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=8)))


def load_registry(path: Path | None = None) -> dict:
    return yaml.safe_load((path or REGISTRY_YAML).read_text(encoding="utf-8"))


def _load_cron_ids(snapshot_path: Path) -> set[str]:
    try:
        import json
        doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
        return {j["id"] for j in doc.get("jobs") or []}
    except FileNotFoundError:
        raise LineageError(
            f"cron 快照缺失：{snapshot_path}——先落一份 `hermes cron list` 快照"
            f"（血缘表 trigger=cron 的离线比对源，重录纪律见血缘表头注释）")


def _check_manual(manual_ref: str, producer: str, root: Path, ctx: str, errors: list[str]) -> None:
    """manual trigger 防逃生舱校验（R1-④）：文档存在 + 行号合法 + 该行含脚本名。"""
    if ":" not in manual_ref:
        errors.append(f"{ctx}: manual 引用缺行号（应形如 docs/xx.md:14）：{manual_ref!r}")
        return
    doc_path, _, line_s = manual_ref.rpartition(":")
    fp = root / doc_path
    if not fp.exists():
        errors.append(f"{ctx}: manual 文档不存在：{doc_path}")
        return
    if not line_s.isdigit():
        errors.append(f"{ctx}: manual 行号非数字：{manual_ref!r}")
        return
    lines = fp.read_text(encoding="utf-8").splitlines()
    ln = int(line_s)
    if not (1 <= ln <= len(lines)):
        errors.append(f"{ctx}: manual 行号越界：{doc_path}:{ln}（文件共 {len(lines)} 行）")
        return
    script_name = Path(producer).name
    if script_name not in lines[ln - 1]:
        errors.append(f"{ctx}: manual 文档行 {doc_path}:{ln} 不含脚本名 {script_name!r}"
                      f"——manual 不许当逃生舱，必须指向真实记载该命令的行")


def validate(doc: dict | None = None, registry: dict | None = None,
             root: Path = ROOT) -> None:
    """加载血缘表时执行的全部断言。任一失败 raise LineageError（不许静默跳过）。"""
    if doc is None:
        doc = yaml.safe_load((root / "data/lineage.yaml").read_text(encoding="utf-8"))
    if registry is None:
        registry = load_registry(root / "data/datasets_registry.yaml")
    errors: list[str] = []
    if not isinstance(doc, dict) or not isinstance(doc.get("datasets"), dict):
        raise LineageError("lineage.yaml 结构错误：缺顶层 datasets 映射")
    downstreams = doc.get("downstreams")
    if not isinstance(downstreams, dict):
        raise LineageError("lineage.yaml 结构错误：缺顶层 downstreams 映射")

    reg_datasets = registry.get("datasets") or {}
    consumers = set(registry.get("consumers") or [])

    # ── 覆盖断言：血缘表必须覆盖全部注册数据集，且不许出现未注册数据集 ──
    missing = sorted(set(reg_datasets) - set(doc["datasets"]))
    extra = sorted(set(doc["datasets"]) - set(reg_datasets))
    if missing:
        errors.append(f"血缘表漏了注册数据集：{missing}")
    if extra:
        errors.append(f"血缘表出现未注册数据集：{extra}")

    # ── 一致性硬断言：direct 逐字 == 注册表 blocks；下游名 ∈ consumers 且有定义 ──
    for key, entry in doc["datasets"].items():
        if key not in reg_datasets:
            continue  # extra 已在上面记过
        direct = list((entry or {}).get("direct") or [])
        blocks = list(reg_datasets[key].get("blocks") or [])
        if direct != blocks:
            errors.append(f"数据集 {key}: direct {direct} 与注册表 blocks {blocks} 不逐字相等")
        for name in direct:
            if name not in consumers:
                errors.append(f"数据集 {key}: 下游名 {name!r} 不在注册表 consumers 封闭清单")
            if name not in downstreams:
                errors.append(f"数据集 {key}: 下游名 {name!r} 缺 downstreams 定义"
                              f"（禁止只登记概念名）")

    # ── 下游条目：producer/trigger 缺一即错（spec 血缘表字段增补要求）──
    for name, d in downstreams.items():
        ctx = f"下游 {name!r}"
        if name not in consumers:
            errors.append(f"{ctx}: 不在注册表 consumers 封闭清单")
        if not isinstance(d, dict):
            errors.append(f"{ctx}: 定义必须是映射")
            continue
        producer = d.get("producer")
        trigger = d.get("trigger")
        if not producer:
            errors.append(f"{ctx}: 缺 producer（脚本路径）")
        elif not (root / producer).exists():
            # 机械断言①：脚本真实存在
            errors.append(f"{ctx}: producer 脚本不存在：{producer}")
        if not trigger:
            errors.append(f"{ctx}: 缺 trigger（cron job id 或 manual）")
        elif not isinstance(trigger, dict) or len(trigger) != 1 or \
                not (set(trigger) <= {"cron", "manual"}):
            errors.append(f"{ctx}: trigger 必须恰为 {{cron: id}} 或 {{manual: 文档:行号}}之一：{trigger!r}")
        # 机械断言②：产物 glob 命中真实文件（allow_empty 白名单除外，且必须写明原因）
        arts = d.get("artifacts")
        if not isinstance(arts, list) or not arts:
            errors.append(f"{ctx}: artifacts 必须是非空列表（无产物的走 allow_empty 白名单）")
        else:
            for a in arts:
                glob_pat = (a or {}).get("glob")
                if not glob_pat:
                    errors.append(f"{ctx}: artifacts 条目缺 glob：{a!r}")
                    continue
                hits = list(root.glob(glob_pat))
                if hits:
                    continue
                if a.get("allow_empty") is True:
                    if not (a.get("allow_empty_reason") or "").strip():
                        errors.append(f"{ctx}: glob {glob_pat!r} 标了 allow_empty 但没写原因"
                                      f"——白名单必须显式可见")
                else:
                    errors.append(f"{ctx}: 产物 glob 零命中：{glob_pat!r}"
                                  f"（若产物当前确实不存在，加 allow_empty: true 并写明原因，不许放宽断言）")

    # ── 机械断言③：trigger 可查证 ──
    snap = doc.get("cron_snapshot") or "tests/golden/cron_snapshot.json"
    need_cron = any(isinstance(d, dict) and isinstance(d.get("trigger"), dict) and "cron" in d["trigger"]
                    for d in downstreams.values())
    cron_ids = _load_cron_ids(root / snap) if need_cron else set()
    for name, d in downstreams.items():
        if not isinstance(d, dict):
            continue
        t = d.get("trigger")
        if not isinstance(t, dict):
            continue
        ctx = f"下游 {name!r}"
        if "cron" in t:
            if t["cron"] not in cron_ids:
                errors.append(f"{ctx}: cron job id {t['cron']!r} 不在快照 {snap} 里"
                              f"（快照过期就重录；作业没了就不许登记这个下游为 cron 触发）")
        elif "manual" in t and d.get("producer"):
            _check_manual(str(t["manual"]), d["producer"], root, ctx, errors)

    if errors:
        raise LineageError("血缘表校验失败（加载即 raise，不许静默跳过）：\n  - " + "\n  - ".join(errors))


def load_lineage(path: Path | None = None, root: Path = ROOT) -> dict:
    """读 lineage.yaml 并立即 validate()——断言不过，表不可用。"""
    p = path or (root / "data/lineage.yaml")
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    validate(doc=doc, root=root)
    return doc


def impact(dataset_key: str, root: Path = ROOT) -> dict:
    """某数据集断供的影响半径。

    返回 {dataset, direct, artifacts, reports, built_at}：
      direct    [下游名]——逐字等于注册表该数据集的 blocks（validate 已断言）
      artifacts [{downstream, glob, path, exists, hits, (allow_empty, allow_empty_reason)}]
                path = 该 glob 最新命中文件的仓库相对路径（零命中且白名单 → None）
      reports   [str] 人读报告路径（各下游去重合并）
      built_at  ISO8601 带时区（BJT）
    数据集未注册 / 血缘表断言失败 → raise LineageError（不许静默返回空）。
    """
    registry = load_registry(root / "data/datasets_registry.yaml")
    reg_datasets = registry.get("datasets") or {}
    if dataset_key not in reg_datasets:
        raise LineageError(
            f"数据集 {dataset_key!r} 未在 datasets_registry.yaml 注册"
            f"（已注册：{sorted(reg_datasets)}）——影响半径只对注册数据集可答")
    doc = load_lineage(root=root)
    entry = doc["datasets"][dataset_key]
    downstreams = doc["downstreams"]
    artifacts: list[dict] = []
    reports: list[str] = []
    for name in entry["direct"]:
        d = downstreams[name]
        for a in d.get("artifacts") or []:
            hits = sorted(root.glob(a["glob"]))
            rec = {"downstream": name, "glob": a["glob"],
                   "path": str(hits[-1].relative_to(root)) if hits else None,
                   "exists": bool(hits), "hits": len(hits)}
            if a.get("allow_empty") is True:
                rec["allow_empty"] = True
                rec["allow_empty_reason"] = a.get("allow_empty_reason")
            artifacts.append(rec)
        for r in d.get("reports") or []:
            if r not in reports:
                reports.append(r)
    return {"dataset": dataset_key,
            "direct": list(entry["direct"]),
            "artifacts": artifacts,
            "reports": reports,
            "built_at": _bjt_now().isoformat(timespec="seconds")}


def stale_claims(ref_date: str | None = None) -> list[dict]:
    """二期接口占位——**阻塞于 DATA-08b，本期不实现**。

    spec「自检修订 R1」实测：data/claims_registry.yaml 只有 claims 一个顶层键，
    inputs 出现 0 次——每条主张未声明依赖哪些数据集，stale_claims 没有数据源。
    前置任务 DATA-08b（给 68 条主张补 inputs）完成前，本函数只许显式 raise，
    不许伪实现、不许返回空列表冒充「无受影响主张」。
    """
    raise NotImplementedError(
        "stale_claims() 阻塞于 DATA-08b：claims_registry.yaml 没有 inputs 字段"
        "（2026-10-20 实测 grep=0），主张未声明依赖的数据集，无数据源可算。"
        "见 docs/plan/specs/DATA-08-lineage.md「自检修订 R1」与 backlog DATA-08b。")


def _render(res: dict) -> str:
    L = [f"# 影响半径 · 数据集 {res['dataset']}（built_at={res['built_at']}）", ""]
    L.append(f"direct 下游（{len(res['direct'])}，== 注册表 blocks）：")
    for n in res["direct"]:
        L.append(f"  - {n}")
    L.append("")
    L.append(f"artifacts（{len(res['artifacts'])} 条 glob）：")
    for a in res["artifacts"]:
        mark = "OK " if a["exists"] else "空(白名单)"
        L.append(f"  [{mark}] {a['downstream']}: {a['glob']}"
                 f" → 命中 {a['hits']} 个" + (f"，最新 {a['path']}" if a["path"] else ""))
        if a.get("allow_empty"):
            L.append(f"         allow_empty 原因：{a['allow_empty_reason']}")
    L.append("")
    L.append(f"reports（{len(res['reports'])}）：" + ("、".join(res["reports"]) if res["reports"] else "（无）"))
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DATA-08 血缘表·影响半径查询")
    ap.add_argument("dataset_key", nargs="?", help="注册数据集 key（如 big_kcache）")
    ap.add_argument("--check", action="store_true", help="只跑 validate() 机械断言")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args(argv)
    try:
        if args.check:
            validate()
            print("lineage validate OK（结构 + 三条机械断言全过）")
            return 0
        if not args.dataset_key:
            ap.error("缺 dataset_key（或用 --check）")
        res = impact(args.dataset_key)
    except LineageError as e:
        print(f"【血缘表错误】{e}", file=sys.stderr)
        return 2
    if args.json:
        import json
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print(_render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
