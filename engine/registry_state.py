#!/usr/bin/env python3
"""engine/registry_state.py — REGISTRY 状态机（第四波卡 t_897ee796；#262-D「注册制无状态机」落地=GOV-01 首期）

背景（实测，2026-10-16）：
  - `law_pipeline.REGISTRY` 共 118 条**函数**、零状态字段；`claims_registry.yaml` 67 条、
    `state`/`status` 字段 **0 命中**（#270 实锤）——即「已死/ICU 的线」在代码层拦不住任何调用。
  - 状态此前只活在 AGENTS.md 台账与 claims_state.json（周审计机器）里，两处口径互不知情。

本模块做四件事（**只读台账 + 只写状态文件 + 只报警告**，绝不改信号逻辑/参数/cron）：
  ① 状态字段：给 118 条 REGISTRY 线逐条落 `state`（口径=INTERFACES I6 冻结枚举
     IDEA/RESEARCH/CANDIDATE/SHADOW/LIVE/ICU/DEAD）+ `layer`（L1 机制 / L2 注册 / EXP 实验变体）
     + `family`（家族 FDR 分组）+ `verdict`（submit PASS/REJECT，与 state 正交）。
  ② 守卫：`guard_call()` / `guard_names()` —— 调用 ICU/DEAD 线时打 `[WARN]` 并落日志，
     **永不阻断**（防误伤既有 cron：#283 只提案不执行、#278 同纪律）。
  ③ 家族 FDR：按家族聚合试探次数与幸存数，给出期望假阳（0.05×m）与 DSR 分母建议——
     #263⑧「111 条 REGISTRY=111 次试探，无按家族控制」的机器可读落地。
  ④ 状态迁移**只接受提案文件**（`docs/proposals/*.json`，需 `approved_by: user`），
     AI 不得直接改状态；每次迁移追加 `data/registry/state_ledger.jsonl` 留痕（可审计）。

用法：
  .venv/bin/python engine/registry_state.py --init       # 从台账逐条映射初始状态（幂等：已存在则不覆盖）
  .venv/bin/python engine/registry_state.py --doc        # 生成 docs/registry-state-mapping.md（映射表，供用户过目）
  .venv/bin/python engine/registry_state.py --apply      # 应用 docs/proposals/*.json 里已批准的迁移
  .venv/bin/python engine/registry_state.py --check 组合_跌停低_深跌 [名称...]   # 查询状态（退出码 0）
  .venv/bin/python engine/registry_state.py --families   # 家族 FDR 报表
  .venv/bin/python engine/registry_state.py --audit      # 调用面体检：谁在调用 ICU/DEAD 线

口径与纪律（写死，别在会话里重新发明）：
  - 状态文件路径 = `data/registry/state.json`（INTERFACES I6 冻结路径与字段；本模块只**追加**字段）。
  - 初始状态**全部来自台账**：claims_state.json（周审计机器状态机）+ claims_registry.yaml +
    law_pipeline submit 判决产物 + AGENTS.md 生产线清单。每条都带 `source` 字段写清依据，可逐条复核。
  - 「已过容量闸」凭证只信带 K1/K5 数值的条目（#270：16 条 CROSS_LOW_* 只有布尔位=被污染），
    故 `g7_trusted` 字段显式记录该判据。
  - 状态迁移的三条硬规则：①只读 docs/proposals/*.json ②必须 approved_by=user ③必须落 ledger。
"""
import argparse
import glob
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
DATA = ROOT / "data"
STATE_PATH = DATA / "registry" / "state.json"      # INTERFACES I6（冻结路径）
LEDGER_PATH = DATA / "registry" / "state_ledger.jsonl"
GUARD_LOG = DATA / "registry" / "guard_log.jsonl"
PROPOSAL_DIR = ROOT / "docs" / "proposals"
MAPPING_DOC = ROOT / "docs" / "registry-state-mapping.md"
CLAIMS_YAML = DATA / "claims_registry.yaml"
CLAIMS_STATE = DATA / "claims_state.json"
LINE_HEALTH = DATA / "line_health.json"
VERSION = "registry_state/1.0 (2026-10-16, t_897ee796)"

# INTERFACES I6 冻结枚举（禁止在本模块自造新状态值）
STATES = ("IDEA", "RESEARCH", "CANDIDATE", "SHADOW", "LIVE", "ICU", "DEAD")
# 生产脚本只许调用 LIVE / SHADOW（I6）；研究脚本可调用 CANDIDATE/RESEARCH；ICU/DEAD 一律告警
CALLABLE_PROD = ("LIVE", "SHADOW")
WARN_STATES = ("ICU", "DEAD")
BLOCKED_PROD = tuple(s for s in STATES if s not in CALLABLE_PROD)

# ── 生产线清单（LIVE 白名单）：每条必须带 AGENTS.md 台账依据与生产 cron 消费者 ──
# 判据（2026-10-16 实测 jobs.json 69 个 job + 全仓库 grep）：
#   ①台账明示「生产在跑」②有 cron/脚本**真实调用该 REGISTRY 键**。
# 说明：「深档低位 v2」的生产实现是 `dashboard_build.deep_low_scan()`（被 ops_briefing 调用），
#   不是 REGISTRY 键（无同名探测器）；REGISTRY 里的「组合_跌停低_深跌」= L2 主张（claims_state=CANDIDATE），
#   二者是「生产实现 vs 注册主张」两层，别混（混了会把 LIVE 判错）。
LIVE_LINES = {
    "banlu_b5_MA60上": ("B5 半路板生产线：cron stock_banlu_daily.py → engine/banlu_daily.py 调本探测器", "#238/#279"),
    "预增低位池_v1": ("预增低位池生产线：cron stock_pead_pool.py → engine/pead_pool.py 调本探测器", "#241/#251"),
}
# SHADOW（只记账不推送）：claims_shadow 的注册表桥 + close-entry 族
SHADOW_NOTE = "claims_shadow 影子盘在记账（只影子不推送）"

# ── 家族 FDR 分组 ──
# 判据优先级（防误归）：①家族名出现在线名**开头**（如「反转族_MA60下_gap≤-3」→ 反转族，
#   不能因为含 "gap" 被算成缺口族）②再按关键词包含匹配。
FAMILY_PREFIX = [
    ("反转族", "反转族"),
    ("跌停接", "跌停族"),
    ("跌停次日接", "跌停族"),
    ("组合_跌停低", "跌停族"),
    ("交叉_跌停低", "跌停族"),
    ("组合_缺口", "缺口族"),
    ("交叉_缺口", "缺口族"),
    ("缺口低开", "缺口族"),
    ("组合_触板", "触板族"),
    ("交叉_触板", "触板族"),
    ("妖股摇篮", "妖股族"),
    ("妖股启动", "妖股族"),
    ("三连阴", "形态族"),
    ("反复票", "池与名单族"),
    ("预增低位池", "预增族"),
]
FAMILY_RULES = [
    ("跌停族", ("跌停",)),
    ("缺口族", ("缺口",)),
    ("反转族", ("反转", "恐慌深度", "输家", "250日")),
    ("预增族", ("PEAD", "预增")),
    ("金股族", ("金股", "gold", "GOLD")),
    ("妖股族", ("妖股", "摇篮", "涨停洗盘", "缩量涨停", "放量涨停", "首板", "二连板", "半路板", "banlu", "frontrun")),
    ("形态族", ("避雷针", "大长腿", "高窄旗形", "旗形", "缠论", "三连阴", "N字", "双响")),
    ("均线族", ("金叉", "上穿", "TD9", "MA20")),
    ("突破族", ("海龟", "突破", "缩量横盘")),
    ("事件族", ("PEAD_", "调样", "龙虎榜", "LHB", "解禁", "公告", "REBALANCE")),
    ("池与名单族", ("观察池", "watch", "watchpool", "反复票", "RESEAL", "涨停池")),
]


def bjt_stamp():
    return (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat(timespec="seconds")


def bjt_date():
    return (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat()


def jload(p, default=None):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def family_of(name):
    for key, fam in FAMILY_PREFIX:
        if name.startswith(key):
            return fam
    for fam, keys in FAMILY_RULES:
        if any(k in name for k in keys):
            return fam
    return "其他"


def load_registry_keys():
    """从 law_pipeline 取 REGISTRY 键（惰性 import，避免模块级循环依赖）。"""
    sys.path.insert(0, str(ROOT / "engine"))
    import law_pipeline as lp
    return list(lp.REGISTRY.keys())


def load_claims():
    import yaml
    doc = yaml.safe_load(CLAIMS_YAML.read_text())
    return doc["claims"]


def _load_claims_safe():
    try:
        return load_claims()
    except Exception:
        return []


def load_submit_verdicts():
    """从 law_pipeline submit 产物汇总每条线**最新一次**判决（口径：文件名的日期后缀）。"""
    out = {}
    for fp in sorted(glob.glob(str(DATA / "law_pipeline_submit_*.json"))):
        day = re.search(r"_(\d{8})\.json$", fp)
        day = day.group(1) if day else "00000000"
        doc = jload(fp, {}) or {}
        for name, v in doc.items():
            if isinstance(v, dict) and "判决" in v:
                out[name] = {"verdict": "PASS" if v["判决"].startswith("PASS") else "REJECT",
                             "gates": v.get("闸门", {}), "date": day, "file": Path(fp).name}
    return out


def load_candle_verdicts():
    """candle（全量跑）判决汇总：用于把「跑过但未 submit」的线从 IDEA 里区分出来（诚实记账）。"""
    out = {}
    for fp in sorted(glob.glob(str(DATA / "law_pipeline_candle_*.json"))):
        for name, v in (jload(fp, {}) or {}).items():
            if isinstance(v, dict) and "判决" in v:
                out[name] = {"verdict": v["判决"], "file": Path(fp).name}
    return out


def build_initial_state():
    """逐条映射初始状态。返回 (items, 依据统计)。所有字段来源可审计。"""
    keys = load_registry_keys()
    claims = load_claims()
    cstate = jload(CLAIMS_STATE, {}) or {}
    lh = jload(LINE_HEALTH, {}) or {}
    verdicts = load_submit_verdicts()
    candle = load_candle_verdicts()

    det2claim = {}
    for c in claims:
        det2claim.setdefault(c.get("detector"), []).append(c)
    lh_by_id = lh.get("lines", {})

    shadow_bridge = set()
    try:
        sys.path.insert(0, str(ROOT / "engine"))
        import claims_shadow as cs
        shadow_bridge |= set(cs.REGISTRY_SHADOW_CLAIMS.values())
        shadow_bridge |= set()  # CLOSE_ENTRY_CLAIMS 以 claim_id 记账，不在 REGISTRY 名空间
    except Exception:
        pass

    items, stats = {}, {"by_state": {}, "by_layer": {}, "by_family": {}}
    for k in keys:
        cl = det2claim.get(k, [])
        fam = family_of(k)
        it = {"id": k, "family": fam, "since": bjt_date(), "evidence": "", "source": ""}
        if cl:
            c = cl[-1]                      # 同名探测器多主张时取最后注册的（现状 118 键中 0 例冲突）
            cid = c["id"]
            g7 = c.get("g7_槽10") or {}
            st = (cstate.get(cid) or {}).get("status", "CANDIDATE")
            it["claim_id"] = cid
            it["layer"] = "L2"               # L2 = 注册主张层（有 claims_registry 条目）
            it["g7_trusted"] = ("K1_年化%" in g7)   # #270：只信带 K1/K5 数值的条目
            it["g7_k1_annual"] = g7.get("K1_年化%")
            it["g7_k5_annual"] = g7.get("K5_年化%")
            it["g7_flag_raw"] = g7.get("过G7")      # 原样保留（已实测被污染，不作凭证）
            it["evidence"] = f"claims_registry#{cid}"
            if st == "DEAD":
                it["state"] = "DEAD"
                it["source"] = "claims_state.json=DEAD（周审计机器）+ AGENTS 台账"
            elif st == "DECAYING":
                it["state"] = "ICU"
                it["source"] = "claims_state.json=DECAYING（降级中）→ 映射 ICU"
            else:
                lh_rec = lh_by_id.get(cid) or {}
                exp = LIVE_LINES.get(k)
                if exp:
                    it["state"] = "LIVE"
                    it["source"] = f"AGENTS 生产线清单（{exp[1]}）：{exp[0]}"
                elif k in shadow_bridge or cid in ("PEAD_LOW_POOL", "MAINLINE_DIP_RSI2",
                                                   "YAO_LAUNCH_FIRSTBOARD", "THREE_DOWN_GOLD"):
                    it["state"] = "SHADOW"
                    it["source"] = f"claims_shadow 桥（{SHADOW_NOTE}）"
                else:
                    it["state"] = "CANDIDATE"
                    it["source"] = "claims_state.json=CANDIDATE（过闸门、未上生产）"
                if lh_rec.get("grade"):
                    it["health_grade"] = lh_rec.get("grade")
                if lh_rec.get("status") and lh_rec["status"] != "CANDIDATE":
                    it["health_status"] = lh_rec["status"]
        else:
            v = verdicts.get(k)
            it["layer"] = "EXP"              # EXP = 实验变体（组合×交叉×滤），无注册条目
            if v:
                it["verdict"] = v["verdict"]
                it["submit_file"] = v["file"]
                it["submit_date"] = v["date"]
                if v["verdict"] == "PASS":
                    it["state"] = "CANDIDATE"
                    it["source"] = f"submit {v['date']} PASS（过闸门，未注册条目）"
                else:
                    it["state"] = "RESEARCH"       # I6 枚举内：未过闸门=仍在研究层
                    failed = [g for g, ok in v["gates"].items() if str(ok) != "✅"]
                    it["reject_reason"] = "挂：" + "、".join(failed) if failed else "REJECT"
                    it["source"] = f"submit {v['date']} REJECT（{it['reject_reason']}）"
            else:
                it["state"] = "IDEA"
                if k in candle:
                    it["candle_run"] = candle[k]["file"]
                    it["source"] = (f"无 claims 条目、无 submit，但已在 candle 全量跑过"
                                    f"（{candle[k]['file']}）→ IDEA（已测未提交）")
                else:
                    it["source"] = "无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA）"
        items[k] = it
        stats["by_state"][it["state"]] = stats["by_state"].get(it["state"], 0) + 1
        stats["by_layer"][it["layer"]] = stats["by_layer"].get(it["layer"], 0) + 1
        stats["by_family"][fam] = stats["by_family"].get(fam, 0) + 1
    return items, stats


def family_fdr(items):
    """家族级 FDR：m=家族内已做 submit 的试探数，期望假阳≈0.05m（Harvey t_NW≥3 是逐格门，
    这里给家族层「幸存数必须超过期望假阳」的粗判据 + DSR 分母建议）。"""
    fams = {}
    for it in items.values():
        f = fams.setdefault(it["family"], {"trials": 0, "survivors": 0, "lines": 0,
                                           "rejected": 0, "unsubmitted": 0, "members": []})
        f["lines"] += 1
        f["members"].append(it["id"])
        if it.get("verdict") == "PASS":
            f["trials"] += 1
            if it["state"] in ("LIVE", "SHADOW", "CANDIDATE"):
                f["survivors"] += 1
        elif it.get("verdict") == "REJECT":
            f["trials"] += 1
            f["rejected"] += 1
        else:
            f["unsubmitted"] += 1
    for name, f in fams.items():
        f["expected_false_positives"] = round(0.05 * f["trials"], 2)
        f["dsr_trials_suggested"] = f["trials"] + 7491  # 与 dsr_recount 的既有全局 trials 合并口径
        f["verdict"] = ("survivors_exceed_fp" if f["survivors"] > f["expected_false_positives"]
                        else "insufficient_or_at_noise")
    return fams


def write_state(items, stats, fams, note="init"):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "_meta": {"version": VERSION, "updated_at": bjt_stamp(), "date": bjt_date(),
                  "schema": "INTERFACES I6 data/registry/state.json（追加字段：layer/family/verdict/…）",
                  "discipline": "只读台账 + 只报警告；状态迁移只接受 docs/proposals/ 已批准提案",
                  "counts": stats},
        "families": fams,
        "items": sorted(items.values(), key=lambda x: x["id"]),
    }
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    tmp.replace(STATE_PATH)
    with LEDGER_PATH.open("a") as f:
        f.write(json.dumps({"_meta": {"ts": bjt_stamp(), "note": note}, "counts": stats},
                           ensure_ascii=False) + "\n")
    return doc


def write_mapping_doc(items, stats, fams):
    lines = []
    lines.append("# REGISTRY 状态映射表（初始状态逐条依据 · 2026-10-16 卡 t_897ee796）\n")
    lines.append("> 本表是 `engine/registry_state.py --init` 生成初始状态的**唯一依据**，供用户过目后再进代码运行。")
    lines.append("> 状态枚举 = `INTERFACES.md` I6 冻结值 `IDEA/RESEARCH/CANDIDATE/SHADOW/LIVE/ICU/DEAD`；")
    lines.append("> 卡的「L1/L2/候选/ICU/DEAD/REJECT」落在两个正交字段上：`layer`（L1 机制 / L2 注册 / EXP 实验变体）"
                 "与 `state`，另加 `verdict`（submit PASS/**REJECT**，与 state 正交，REJECT 映射 state=RESEARCH 见 §规则）。\n")
    lines.append("## 映射规则（写死，逐条可复核）\n")
    lines.append("| 台账事实 | → state | → layer |")
    lines.append("|---|---|---|")
    lines.append("| claims_state.json = DEAD（周审计机器） | DEAD | L2 |")
    lines.append("| claims_state.json = DECAYING | ICU | L2 |")
    lines.append("| 在 AGENTS 生产线清单（有 cron 消费） | LIVE | L2 |")
    lines.append("| claims_shadow 注册表桥（只记账） | SHADOW | L2 |")
    lines.append("| claims_state = CANDIDATE，未上生产 | CANDIDATE | L2 |")
    lines.append("| 无 claims 条目 + submit PASS | CANDIDATE | EXP |")
    lines.append("| 无 claims 条目 + submit REJECT | RESEARCH（`reject_reason` 记挂哪闸） | EXP |")
    lines.append("| 无 claims 条目 + 无 submit 判决 | IDEA | EXP |")
    lines.append("")
    lines.append("**容量凭证纪律（#270）**：`g7_trusted` 仅在 `g7_槽10` 带 `K1_年化%` 数值时为 true；"
                 "16 条 `CROSS_LOW_*` 只有布尔位 `{\"过G7\": true}`，已实测被不同批次脚本污染，**不作凭证**。\n")
    lines.append(f"**统计**：state `{stats['by_state']}`；layer `{stats['by_layer']}`；"
                 f"家族 `{stats['by_family']}`\n")

    lines.append("## 家族 FDR（#263⑧ 落地）\n")
    lines.append("| 家族 | 线数 | 已 submit 试探 m | 幸存 | REJECT | 期望假阳 0.05m | 判据 |")
    lines.append("|---|---|---|---|---|---|---|")
    for name, f in sorted(fams.items(), key=lambda kv: -kv[1]["trials"]):
        lines.append(f"| {name} | {f['lines']} | {f['trials']} | {f['survivors']} | {f['rejected']} | "
                     f"{f['expected_false_positives']} | {f['verdict']} |")
    lines.append("")
    lines.append("> 读法：家族内「幸存数 > 期望假阳」只是粗筛（本体系多数格无 p 值，只有 t_NW）；"
                 "DSR 重算的分母建议见 `families.*.dsr_trials_suggested`。\n")

    lines.append("## 逐条映射（118 条）\n")
    lines.append("| # | REGISTRY 线 | layer | state | family | verdict | g7可信 | 依据 source |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for i, it in enumerate(sorted(items.values(), key=lambda x: x["id"]), 1):
        g7 = "—" if it.get("g7_trusted") is None else ("是" if it["g7_trusted"] else "否")
        lines.append(f"| {i} | {it['id']} | {it['layer']} | {it['state']} | {it['family']} | "
                     f"{it.get('verdict', '—')} | {g7} | {it['source']} |")
    lines.append("")
    lines.append("## 迁移通道（AI 不得直接改状态）\n")
    lines.append("状态迁移只接受 `docs/proposals/*.json`，字段：`{\"id\":…, \"from\":…, \"to\":…, "
                 "\"evidence\":…, \"approved_by\":\"user\", \"approved_at\":\"YYYY-MM-DD\"}`；"
                 "`--apply` 逐条校验（from 必须与当前一致、to 必须在 I6 枚举内）并追加 "
                 "`data/registry/state_ledger.jsonl`。")
    MAPPING_DOC.write_text("\n".join(lines))
    return MAPPING_DOC


# ── 守卫 ────────────────────────────────────────────────────────────────
_STATE_CACHE = {"mtime": None, "items": {}}


def _items():
    if not STATE_PATH.exists():
        return {}
    m = STATE_PATH.stat().st_mtime
    if _STATE_CACHE["mtime"] != m:
        _STATE_CACHE["items"] = {it["id"]: it for it in jload(STATE_PATH, {}).get("items", [])}
        _STATE_CACHE["mtime"] = m
    return _STATE_CACHE["items"]


def guard_call(name, where="", mode="research"):
    """调用处守卫：ICU/DEAD 报警告，**永不阻断**。返回 True=可调用（含警告情形）。
    mode='prod' 时 LIVE/SHADOW 之外也提示（I6 契约：生产只许调 LIVE/SHADOW）。"""
    it = _items().get(name)
    if not it:
        return True
    st = it["state"]
    warn = st in WARN_STATES or (mode == "prod" and st not in CALLABLE_PROD)
    if warn:
        msg = f"[WARN] registry: 调用 {name}（state={st}, layer={it['layer']}, family={it['family']}）"
        if st in WARN_STATES:
            msg += " —— 该线已判停/ICU，结果不得用于推送或注册（#283 只提案纪律）"
        else:
            msg += f" —— I6 契约：生产只许调用 LIVE/SHADOW，当前 {st}"
        if where:
            msg += f" [{where}]"
        print(msg, file=sys.stderr)
        try:
            GUARD_LOG.parent.mkdir(parents=True, exist_ok=True)
            with GUARD_LOG.open("a") as f:
                f.write(json.dumps({"ts": bjt_stamp(), "id": name, "state": st, "layer": it["layer"],
                                    "family": it["family"], "where": where, "mode": mode},
                                   ensure_ascii=False) + "\n")
        except Exception:
            pass
    return True


def guard_names(names, where="", mode="research"):
    for n in names:
        guard_call(n, where=where, mode=mode)


# ── 迁移：只吃提案文件 ───────────────────────────────────────────────────
def apply_proposals():
    doc = jload(STATE_PATH, {})
    items = {it["id"]: it for it in doc.get("items", [])}
    proposals = sorted(glob.glob(str(PROPOSAL_DIR / "*.json")))
    applied, skipped = [], []
    for fp in proposals:
        try:
            p = json.loads(Path(fp).read_text())
        except Exception as e:
            skipped.append((Path(fp).name, f"解析失败 {e}"))
            continue
        for ent in (p if isinstance(p, list) else [p]):
            pid = ent.get("id")
            if not pid or pid not in items:
                skipped.append((Path(fp).name, f"未知 id {pid}"))
                continue
            if ent.get("approved_by") != "user":
                skipped.append((pid, "未批准（approved_by != user），AI 不得自行迁移"))
                continue
            to = ent.get("to")
            if to not in STATES:
                skipped.append((pid, f"目标状态 {to} 不在 I6 枚举"))
                continue
            cur = items[pid]["state"]
            if ent.get("from") and ent["from"] != cur:
                skipped.append((pid, f"from={ent['from']} 与当前 {cur} 不一致（防并发错改）"))
                continue
            items[pid].update(state=to, since=ent.get("approved_at") or bjt_date(),
                              evidence=ent.get("evidence", items[pid].get("evidence", "")),
                              source=f"提案 {Path(fp).name}（approved_by=user）")
            applied.append((pid, cur, to))
    if applied:
        doc["items"] = sorted(items.values(), key=lambda x: x["id"])
        doc["_meta"]["updated_at"] = bjt_stamp()
        tmp = STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
        tmp.replace(STATE_PATH)
        with LEDGER_PATH.open("a") as f:
            for pid, old, new in applied:
                f.write(json.dumps({"_meta": {"ts": bjt_stamp(), "kind": "transition"},
                                    "id": pid, "from": old, "to": new}, ensure_ascii=False) + "\n")
    return applied, skipped


# ── 调用面体检 ──────────────────────────────────────────────────────────
def _cron_prod_files():
    """生产入口文件集：cron wrapper 的 runpy 目标（19 个 engine 模块）+ /opt/data/scripts/*.py，
    再沿 import 链向上闭包（engine↔engine、engine→scripts、scripts→engine）。
    这样「生产调用面」= 真会被 cron 执行到的文件，而不是「仓库里存在即算」。"""
    prod = {fp for fp in glob.glob("/opt/data/scripts/*.py")}
    for fp in glob.glob("/opt/data/scripts/*.py"):
        try:
            txt = Path(fp).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in re.finditer(r'run_path\(\s*"([^"]+)"', txt):
            prod.add(m.group(1))
    # import 闭包（限定 engine/ 与 /opt/data/scripts/ 两个命名空间）
    resolve = {}
    for d in (ROOT / "engine", Path("/opt/data/scripts")):
        for fp in glob.glob(str(d / "*.py")):
            resolve.setdefault(Path(fp).stem, fp)
    frontier = list(prod)
    seen = set(prod)
    while frontier:
        fp = frontier.pop()
        try:
            txt = Path(fp).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in re.finditer(r'^\s*(?:from\s+([A-Za-z_][\w]*)\s+import|import\s+([A-Za-z_][\w]*))',
                             txt, re.M):
            mod = m.group(1) or m.group(2)
            tgt = resolve.get(mod)
            if tgt and tgt not in seen:
                seen.add(tgt)
                prod.add(tgt)
                frontier.append(tgt)
    return prod


def audit_callers():
    """扫 cron/脚本/engine，列出「正在调用 ICU/DEAD 线」的清单（预期反转族命中，如实报）。

    精确性处理：CJK 键名会互为子串（`TD9买入` ⊂ `TD9买入滤`），故用**最长匹配归属**——
    一个文件里若同时出现 A 与其超串 B，则计入 B 不计入 A（防把调用 B 的错记成调用 A）。
    消费方分三类，判读完全不同：prod（生产可达：cron runpy 目标 + import 闭包）/
    shadow（claims_shadow 影子记账桥，按设计记账不算事故）/ research（研究脚本，许可调用但结果不得推送）。
    """
    items = _items()
    bad = {k: v for k, v in items.items() if v["state"] in WARN_STATES}
    keys_sorted = sorted(bad, key=len, reverse=True)
    prod_files = _cron_prod_files()
    files = []
    for pat in ("engine/*.py", "scripts/*.py", "scheduler/*.py", "api/*.py",
                "/opt/data/scripts/*.py", "/opt/data/scripts/*.sh"):
        files += glob.glob(pat if pat.startswith("/") else str(ROOT / pat))
    callers = {}
    for fp in sorted(set(files)):
        if fp.endswith(("law_pipeline.py", "registry_state.py")):
            continue
        try:
            txt = Path(fp).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for name in keys_sorted:
            if name not in txt:
                continue
            # 最长匹配：若更长的键也出现在同一文件，则跳过本键（归属给更长的）
            if any(o != name and name in o and o in txt for o in keys_sorted):
                continue
            kind = ("shadow" if fp.endswith("claims_shadow.py")
                    else "prod" if fp in prod_files else "research")
            callers.setdefault(name, []).append((fp, kind))
    rows = []
    for name, it in sorted(bad.items(), key=lambda kv: (kv[1]["state"], kv[1]["family"])):
        fl = callers.get(name, [])
        rows.append({"id": name, "state": it["state"], "family": it["family"], "layer": it["layer"],
                     "source": it.get("source", ""),
                     "prod": sorted({f for f, k in fl if k == "prod"}),
                     "shadow": sorted({f for f, k in fl if k == "shadow"}),
                     "research": sorted({f for f, k in fl if k == "research"})})
    cron_jobs = jload("/opt/data/cron/jobs.json", {}) or {}
    return rows, cron_jobs.get("jobs", [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true", help="从台账逐条映射初始状态（写在 --doc 之后）")
    ap.add_argument("--doc", action="store_true", help="生成映射表 docs/registry-state-mapping.md")
    ap.add_argument("--apply", action="store_true", help="应用 docs/proposals/*.json 已批准提案")
    ap.add_argument("--check", nargs="*", help="查询指定线状态")
    ap.add_argument("--families", action="store_true")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--force", action="store_true", help="--init 时覆盖既有状态（默认幂等保留）")
    args = ap.parse_args()

    if args.check:
        items = _items()
        rc = 0
        for n in args.check:
            it = items.get(n)
            if not it:
                print(f"{n}: 未知（不在 REGISTRY 118 条内）")
                rc = 1
            else:
                print(f"{n}: state={it['state']} layer={it['layer']} family={it['family']} "
                      f"verdict={it.get('verdict', '—')} since={it.get('since')} | {it['source']}")
        return rc

    if args.families:
        doc = jload(STATE_PATH, {}) or {}
        fams = doc.get("families") or family_fdr({it["id"]: it for it in doc.get("items", [])})
        for name, f in sorted(fams.items(), key=lambda kv: -kv[1]["trials"]):
            print(f"{name:8} 线{f['lines']:3} 试探{f['trials']:3} 幸存{f['survivors']:3} "
                  f"REJECT{f['rejected']:3} 期望假阳{f['expected_false_positives']:5} {f['verdict']}")
        return 0

    if args.audit:
        rows, jobs = audit_callers()
        claims = _load_claims_safe()
        print(f"cron jobs: {len(jobs)}  |  REGISTRY 线 {len(_items())} 条，ICU/DEAD {len(rows)} 条")
        n_prod = sum(1 for r in rows if r["prod"])
        n_shadow = sum(1 for r in rows if r["shadow"])
        n_res = sum(1 for r in rows if r["research"])
        print(f"其中：被 生产 cron 入口 调用 {n_prod} 条 ｜ 被影子桥调用 {n_shadow} 条 ｜ 仅研究脚本 {n_res} 条"
              f" ｜ 零引用 {sum(1 for r in rows if not (r['prod'] or r['shadow'] or r['research']))} 条")
        outpath = DATA / "registry" / "caller_audit.json"
        outpath.parent.mkdir(parents=True, exist_ok=True)
        outpath.write_text(json.dumps(
            {"_meta": {"version": VERSION, "built_at": bjt_stamp(), "date": bjt_date(),
                       "note": "ICU/DEAD 线调用面体检；prod=生产 cron 入口（真事故面）"
                               "；shadow=claims_shadow 影子桥（按设计记账）；research=研究脚本"},
             "rows": rows}, ensure_ascii=False, indent=1))
        for r in rows:
            kind = ("生产" if r["prod"] else "影子" if r["shadow"] else "研究" if r["research"] else "零引用")
            print(f"  [{r['state']:4}] {kind} {r['family']:6} {r['id']}")
            if r["prod"]:
                for c in r["prod"]:
                    print(f"        ⚠ 生产入口 ← {c}")
            for c in r["research"][:3]:
                print(f"        ← {c}")
        print("落盘", outpath)
        return 0

    if args.apply:
        applied, skipped = apply_proposals()
        for pid, old, new in applied:
            print(f"应用：{pid} {old}→{new}")
        for pid, why in skipped:
            print(f"跳过：{pid} — {why}")
        return 0

    items, stats = build_initial_state()
    fams = family_fdr(items)
    if args.doc:
        p = write_mapping_doc(items, stats, fams)
        print("映射表已写", p)
        print("state:", stats["by_state"])
        print("layer:", stats["by_layer"])
    if args.init:
        if STATE_PATH.exists() and not args.force:
            doc = jload(STATE_PATH, {})
            print(f"状态文件已存在（{len(doc.get('items', []))} 条），幂等保留；--force 覆盖")
            return 0
        write_state(items, stats, fams, note="init from ledger")
        print("状态已写", STATE_PATH)
        print("state:", stats["by_state"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
