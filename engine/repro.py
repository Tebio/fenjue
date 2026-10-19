#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine/repro.py — 可复现锚：结果文件 `_meta` 盖章层 + 实验索引（#263⑥ 根治）。

设计要点（2026-10-16 卡 t_67a94908，AGENTS #295）：
  1. **收口**：所有写结果 JSON 的脚本改调 `write_result(...)`，一处盖章一处索引；
     旧脚本不改公式/口径，只在落盘处多一次 merge（见 `stamp` 的「只加不覆盖」语义）。
  2. **索引**：`data/results_index.jsonl` 每行 = 一次实验（一条结果文件一次落盘）。
     追加写（I0 约定 JSONL 用 `a`），行内带文件 sha256 → 可查「这条结论对应哪版文件」。
  3. **锚字段**（INTERFACES I8 + 本卡扩展，只加字段不改契约）：
     generated_at / params_hash / data_snapshot / code_version / inputs / owner
     + entry（代码入口）/ runtime_s / card / git_dirty / provenance。
  4. **provenance 取值**：`live`=本次运行盖章；`git_reconstructed`=回填时按 git 历史重建；
     `legacy_unknown`=回填且无法重建（工作区已脏或从未提交）——**不得冒充 live**。

用法：
  .venv/bin/python engine/repro.py audit            # 列出缺 _meta 的新结果文件（警告级）
  .venv/bin/python engine/repro.py audit --strict   # 有缺失则退出码 1（verify.sh 默认不用）
  .venv/bin/python engine/repro.py stamp FILE...    # 回填单个/多个文件（重建 git hash → 索引）
  .venv/bin/python engine/repro.py index            # 打印索引统计
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
INDEX = ROOT / "data" / "results_index.jsonl"

# 结果文件识别（audit 用）：data/ 下 名字带 _YYYYMMDD 的 .json
RESULT_RE = re.compile(r"_\d{8}(_[A-Za-z0-9\u4e00-\u9fff]+)*\.json$")
# 非「研究结果」的目录：原始数据/缓存/按日快照/私有
SKIP_DIRS = {
    "big_kcache", "kcache", "m60_cache", "raw_kcache", "delist_kcache_iso", "cap_hist",
    "guba_rank", "private", "__pycache__", "cb_m5", "hithink", "consensus_snapshots",
    "commodity", "margin", "feedback", "trade_calendar", "auction", "auction_zt",
    "auction_deep", "lhb_em", "lhb_seats_em", "zt_pool_em", "gold_stock_cache",
}
_GIT_CACHE: dict[str, str] = {}


# ── 基础工具 ────────────────────────────────────────────────────────────────

def git_short() -> str:
    """当前 HEAD 短 sha；取不到返回 'unknown'（不抛错，锚层不能反过来炸掉研究脚本）。"""
    if "head" in _GIT_CACHE:
        return _GIT_CACHE["head"]
    try:
        sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        sha = ""
    _GIT_CACHE["head"] = sha or "unknown"
    return _GIT_CACHE["head"]


def git_dirty() -> bool:
    """工作区是否有未提交改动（有 → 结论无法用 sha 精确重建，锚里如实标注）。"""
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
                             capture_output=True, text=True, timeout=30).stdout
        return bool(out.strip())
    except Exception:
        return True


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def params_hash(params) -> str | None:
    """参数指纹（canonical JSON → sha256 前 12 位）；无参数一律 None（不编造）。"""
    if params is None:
        return None
    if isinstance(params, dict) and not params:
        return None
    blob = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+08:00")


# ── 盖章 ────────────────────────────────────────────────────────────────────

_FILL = object()  # 占位：显式区分「未提供」与「提供 None」


def stamp(doc: dict, *, owner: str, entry: str, inputs=None, params=None,
          data_snapshot=None, runtime_s=None, card=None, provenance: str = "live",
          generated_at=None, extra=None) -> dict:
    """把 `_meta` 合并进 doc（**只加不覆盖**：已有键一律保留）。

    「只加不覆盖」是本卡纪律的落点——回填/重跑都不能抹掉原脚本写下的口径说明，
    例如 hedge_test.py 的「净收益式」「对冲口径」这类人读证据。
    """
    meta = doc.get("_meta")
    if not isinstance(meta, dict):
        meta = {}
        doc["_meta"] = meta
    meta.setdefault("generated_at", generated_at or now_iso())
    meta.setdefault("owner", owner)
    meta.setdefault("entry", entry)
    meta.setdefault("inputs", list(inputs or []))
    meta.setdefault("data_snapshot", data_snapshot)
    meta.setdefault("params_hash", params_hash(params))
    meta.setdefault("params", params)
    meta.setdefault("code_version", git_short())
    meta.setdefault("git_dirty", git_dirty())
    meta.setdefault("runtime_s", round(runtime_s, 3) if runtime_s is not None else None)
    meta.setdefault("provenance", provenance)
    if card:
        meta.setdefault("card", card)
    if extra:
        for k, v in extra.items():
            meta.setdefault(k, v)
    return doc


def append_index(path: Path, *, owner, entry, card=None, provenance="live",
                 data_snapshot=None, params_hash_v=None, code_version=None,
                 runtime_s=None, sha256=None, extra=None) -> dict:
    """追加一行实验索引（一次落盘 = 一行）。返回该行。"""
    path = Path(path)
    rel = str(path.relative_to(ROOT)) if str(path).startswith(str(ROOT)) else str(path)
    if sha256 is None:
        sha256 = file_sha256(path)
    row = {
        "ts": now_iso(),
        "path": rel,
        "owner": owner,
        "entry": entry,
        "card": card,
        "code_version": code_version or git_short(),
        "params_hash": params_hash_v,
        "data_snapshot": data_snapshot,
        "provenance": provenance,
        "runtime_s": round(runtime_s, 3) if runtime_s is not None else None,
        "sha256": sha256,
        "bytes": path.stat().st_size if path.exists() else None,
    }
    if extra:
        row.update(extra)
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    with open(INDEX, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def write_result(path, doc: dict, *, owner: str, entry: str, inputs=None, params=None,
                 data_snapshot=None, runtime_s=None, card=None, provenance="live",
                 indent=1, extra_meta=None, index_extra=None) -> dict:
    """结果文件唯一出口：盖章 → 原子写 → 索引。返回写下的 _meta。

    原子写按 I0（先 .tmp 再 os.replace）。
    """
    path = Path(path)
    stamp(doc, owner=owner, entry=entry, inputs=inputs, params=params,
          data_snapshot=data_snapshot, runtime_s=runtime_s, card=card,
          provenance=provenance, extra=extra_meta)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=indent), encoding="utf-8")
    os.replace(tmp, path)
    meta = doc["_meta"]
    append_index(path, owner=owner, entry=entry, card=card, provenance=provenance,
                 data_snapshot=meta.get("data_snapshot"), params_hash_v=meta.get("params_hash"),
                 code_version=meta.get("code_version"), runtime_s=meta.get("runtime_s"),
                 extra=index_extra)
    return meta


# ── 回填 ────────────────────────────────────────────────────────────────────

def git_introducing_sha(path: Path) -> str | None:
    """该文件最近一次被提交的 sha；从未提交返回 None。"""
    try:
        sha = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%h", "--",
                              str(path.relative_to(ROOT))],
                             capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return None
    return sha or None


def git_tracked_clean(path: Path) -> bool:
    """文件已被 git 跟踪且工作区副本与 HEAD 一致（→ 可按 sha 精确重建）。"""
    try:
        rel = str(path.relative_to(ROOT))
        por = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", rel],
                             capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return False
    return por == ""


def backfill(path: Path, *, card="t_67a94908", index_only=False) -> dict:
    """给既有结果文件补 `_meta`（只加不覆盖）并写索引。

    provenance: git_reconstructed（已提交且工作区一致）/ legacy_unknown（其余）。
    """
    path = Path(path)
    d = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(d, dict):
        return {"path": str(path), "skipped": "not_object"}
    _old = d.get("_meta")
    old: dict = _old if isinstance(_old, dict) else {}
    clean = git_tracked_clean(path)
    sha = git_introducing_sha(path) if clean else None
    prov = "git_reconstructed" if sha else "legacy_unknown"
    entry = old.get("entry") or old.get("owner") or old.get("script") or "unknown(legacy)"
    owner = old.get("owner") or old.get("script") or "unknown(legacy)"
    meta: dict = {}
    if not index_only:
        stamped = stamp(d, owner=owner, entry=entry,
                        inputs=old.get("inputs"), params=None,
                        data_snapshot=old.get("data_snapshot"),
                        provenance=prov, generated_at=old.get("generated_at") or None,
                        extra={"code_version": sha or "legacy", "git_dirty": not clean,
                               "params_hash": old.get("params_hash"),
                               "backfill_card": card,
                               "backfill_note": ("git_reconstructed: 文件已提交且工作区一致，可按 code_version 重建"
                                                 if sha else
                                                 "legacy_unknown: 未提交或工作区已脏 → 无法按 sha 重建，params 不可考")})
        meta = stamped.get("_meta") or {}
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    else:
        meta = d.get("_meta") or {}
    row = append_index(path, owner=owner, entry=entry, card=card, provenance=prov,
                       data_snapshot=meta.get("data_snapshot"),
                       params_hash_v=meta.get("params_hash"),
                       code_version=meta.get("code_version"),
                       extra={"backfilled": True})
    return {"path": str(path.relative_to(ROOT)), "provenance": prov,
            "code_version": meta.get("code_version"), "sha256": row["sha256"][:12]}


# ── 审计（防呆闸，警告级）────────────────────────────────────────────────────

def iter_result_files():
    for p in sorted((ROOT / "data").rglob("*.json")):
        try:
            rel_parts = p.relative_to(ROOT / "data").parts
        except ValueError:
            continue
        if set(rel_parts[:-1]) & SKIP_DIRS:
            continue
        if not RESULT_RE.search(p.name):
            continue
        yield p


def audit(verbose=False) -> list[Path]:
    missing = []
    for p in iter_result_files():
        try:
            if p.stat().st_size > 30_000_000:
                continue
            d = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if not (isinstance(d, dict) and isinstance(d.get("_meta"), dict) and d["_meta"]):
            missing.append(p)
            if verbose:
                print("  缺 _meta:", p.relative_to(ROOT))
    return missing


def index_stats() -> dict:
    if not INDEX.exists():
        return {"rows": 0}
    rows = [json.loads(l) for l in INDEX.read_text(encoding="utf-8").splitlines() if l.strip()]
    prov = {}
    for r in rows:
        prov[r.get("provenance")] = prov.get(r.get("provenance"), 0) + 1
    return {"rows": len(rows), "by_provenance": prov,
            "files_indexed": len({r["path"] for r in rows})}


def main() -> int:
    ap = argparse.ArgumentParser(description="结果文件 _meta 盖章层 + 实验索引")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit"); a.add_argument("-v", "--verbose", action="store_true")
    a.add_argument("--strict", action="store_true")
    s = sub.add_parser("stamp"); s.add_argument("files", nargs="+")
    sub.add_parser("index")
    args = ap.parse_args()

    if args.cmd == "audit":
        miss = audit(verbose=args.verbose)
        print(f"结果文件缺 _meta: {len(miss)} 个（警告级，不阻断）")
        for p in miss[:40]:
            print("  ⚠️", p.relative_to(ROOT))
        if len(miss) > 40:
            print(f"  … 另有 {len(miss)-40} 个")
        return 1 if (args.strict and miss) else 0

    if args.cmd == "stamp":
        for f in args.files:
            p = Path(f)
            if not p.is_absolute():
                p = ROOT / f
            print(json.dumps(backfill(p), ensure_ascii=False))
        return 0

    if args.cmd == "index":
        print(json.dumps(index_stats(), ensure_ascii=False, indent=1))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
