#!/usr/bin/env python3
"""engine/build_daily_state.py — 每日状态总线（权威日态包，#295 卡 t_85e130a4）

一句话：把「环境/触发/健康/KNN/持仓/簇」从一个包发出去，消费端不再各读八个产物。

纪律（写死）：
  * **只读拼合，不重算任何信号**——所有数字直接来自既有产物；本脚本不含任何信号逻辑、不写其他产物；
  * 缺源写 unknown 不猜（进顶层 `unknown[]`，段落里显示 unknown）；
  * **幂等**：同日重跑原子覆盖整包（.tmp → os.replace），不追加、不重复计数；
  * 环境量只走 `env_state` 唯一源；KNN 只搬 `similarity_daily` 落盘结果（当前触发名单内的票）。

用法：
  .venv/bin/python engine/build_daily_state.py                 # 默认=指数产物最新交易日
  .venv/bin/python engine/build_daily_state.py --date 2026-10-15
  .venv/bin/python engine/build_daily_state.py --section regime|cluster|holdings|health|freshness|one_line

产物：data/daily_state/<date>.json（schema 见 docs/daily_state-schema.md）
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
D = ROOT / "data"
BJT = timezone(timedelta(hours=8))
OUTDIR = D / "daily_state"
CLUSTER_GATE = 5  # 深档簇门（既有口径 ≥5，见 preflight sec_cluster）

# 触发源 → 包内 key；kind=pool 表示状态制（无单日日期，按 updated 判新鲜）
SRC_FILES = {
    "ops_state": "docs/ops-state.json",
    "reversal_confirmed": "data/reversal_confirmed.json",
    "watch_pool": "data/watch_pool.json",
    "pead_pool_state": "data/pead_pool_state.json",
    "gold_current": "data/gold_current.json",
    "line_health": "data/line_health.json",
    "xrules_state": "data/xrules_state.json",
    "regime_timeline_hcap": "data/regime_timeline_hcap.json",
    "regime_age": "data/regime_age.json",
    "index_sh000001": "data/index_sh000001.json",
    "watchlist": "config/watchlist.json",
}

# 时效判定唯一出处（#332/P2：本文件 18 处展示级新鲜度调用全部指向 freshness_core，
# 旧局部 freshness()/mtime_str() 判定口径已删除，mtime_str 只剩薄壳兼容 watchlist 段）
sys.path.insert(0, str(ROOT / "engine")) if str(ROOT / "engine") not in sys.path else None
import freshness_core as fc  # noqa: E402


# ---------------- 基础工具 ----------------

def jload(rel, default=None):
    try:
        return json.loads((ROOT / rel).read_text(encoding="utf-8"))
    except Exception:
        return default


def git_sha():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, timeout=10).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def mtime_str(rel):
    """薄壳：实现已收编 freshness_core.mtime_bjt（#332/P2）。"""
    return fc.mtime_bjt(ROOT / rel)


# ---------------- 各段 ----------------

def build_regime(day, fresh, unknown):
    axis = None
    tl = jload("data/regime_timeline_hcap.json")
    if isinstance(tl, list) and tl:
        last = tl[-1]
        axis = {"date": last.get("date"), "regime": last.get("regime"),
                "boards": last.get("boards"), "downs": last.get("downs"),
                "small_pct": last.get("small%"), "conc": last.get("conc"), "idx": last.get("idx")}
        fresh["regime_axis"] = fc.legacy_fresh_entry(ROOT, "data/regime_timeline_hcap.json", "date", axis["date"], day)
    else:
        unknown.append("regime_timeline_hcap.json 缺失/空")
        fresh["regime_axis"] = fc.legacy_fresh_entry(ROOT, "data/regime_timeline_hcap.json", "date", None, day)

    age_entry = None
    age = jload("data/regime_age.json")
    if isinstance(age, dict):
        cur = (age.get("ages") or {}).get(age.get("latest")) or age.get("today") or {}
        age_entry = {"regime": cur.get("regime"), "age": cur.get("age"), "latest": age.get("latest")}
        fresh["regime_age"] = fc.legacy_fresh_entry(ROOT, "data/regime_age.json", "latest", age.get("latest"), day)
    else:
        unknown.append("regime_age.json 缺失")
        fresh["regime_age"] = fc.legacy_fresh_entry(ROOT, "data/regime_age.json", "latest", None, day)

    env = None
    try:
        sys.path.insert(0, str(ROOT / "engine"))
        import env_state as esmod
        env = esmod.env_state(day)
    except Exception as e:
        unknown.append(f"env_state 调用失败: {e}")
    return {"axis": axis, "age_entry": age_entry, "env": env}


def _compact(rows, fields):
    out = []
    for r in rows or []:
        if isinstance(r, str):
            out.append([r])
            continue
        out.append([r.get(f) for f in fields])
    return out


def build_lines(day, fresh, unknown):
    # ---- 触发清单（五源） ----
    trig = {}

    ops = jload("docs/ops-state.json")
    if isinstance(ops, dict):
        fresh["ops_state"] = fc.legacy_fresh_entry(ROOT, "docs/ops-state.json", "sig_date", ops.get("sig_date"), day)
        trig["ops_state"] = {
            "sig_date": ops.get("sig_date"), "buy_day": ops.get("buy_day"), "sell_day": ops.get("sell_day"),
            "deep_low": _compact(ops.get("deep_low"), ["code", "name", "pct"]),
            "deep_low_fields": ["code", "name", "pct"],
            "b5": ops.get("b5") or {}, "focus": ops.get("focus") or [],
        }
    else:
        unknown.append("docs/ops-state.json 缺失")
        fresh["ops_state"] = fc.legacy_fresh_entry(ROOT, "docs/ops-state.json", "sig_date", None, day)
        trig["ops_state"] = {"deep_low": [], "b5": {}, "focus": []}

    rev = jload("data/reversal_confirmed.json")
    if isinstance(rev, dict):
        rdate = rev.get("date")
        # 9:32 竞价确认名单=次日执行件：新鲜度判据为「≥ 包日」
        fresh["reversal_confirmed"] = fc.legacy_fresh_entry(ROOT, "data/reversal_confirmed.json", "date", rdate, day)
        if rdate and day and rdate < day:
            fresh["reversal_confirmed"]["status"] = "stale"
        trig["reversal_confirmed"] = {
            "date": rdate, "n": rev.get("n"), "cluster_ok": rev.get("cluster_ok"),
            "deep_low_n": rev.get("deep_low_n"),
            "fields": ["code", "name", "close_chg", "open_chg", "ladder"],
            "rows": _compact(rev.get("executable"), ["code", "name", "close_chg", "open_chg", "ladder"]),
        }
    else:
        unknown.append("data/reversal_confirmed.json 缺失")
        fresh["reversal_confirmed"] = fc.legacy_fresh_entry(ROOT, "data/reversal_confirmed.json", "date", None, day)
        trig["reversal_confirmed"] = {"rows": [], "fields": ["code", "name", "close_chg", "open_chg", "ladder"]}

    wp = jload("data/watch_pool.json")
    if isinstance(wp, dict):
        fresh["watch_pool"] = fc.legacy_fresh_entry(ROOT, "data/watch_pool.json", "updated", wp.get("updated"), day)
        trig["watch_pool"] = {"updated": wp.get("updated"), "variant": wp.get("variant"),
                              "fields": ["code", "name", "status", "entry_date", "entry_close", "days"],
                              "rows": _compact(wp.get("pool"),
                                               ["code", "name", "status", "entry_date", "entry_close", "days"])}
    else:
        unknown.append("data/watch_pool.json 缺失")
        fresh["watch_pool"] = fc.legacy_fresh_entry(ROOT, "data/watch_pool.json", "updated", None, day)
        trig["watch_pool"] = {"rows": []}

    ps = jload("data/pead_pool_state.json")
    if isinstance(ps, dict):
        pdates = ps.get("processed_dates") or []
        last = pdates[-1] if pdates else None
        fresh["pead_pool_state"] = fc.legacy_fresh_entry(ROOT, "data/pead_pool_state.json", "processed_dates[-1]", last, day)
        trig["pead_pool_state"] = {"processed_last": last,
                                   "fields": ["code", "name"],
                                   "holdings": _compact(ps.get("holdings"), ["code", "name"]),
                                   "pending": _compact(ps.get("pending"), ["code", "name"])}
    else:
        trig["pead_pool_state"] = {"holdings": [], "pending": []}

    gold = jload("data/gold_current.json")
    if isinstance(gold, dict):
        fresh["gold_current"] = fc.legacy_fresh_entry(ROOT, "data/gold_current.json", "entry_day", gold.get("entry_day"), day)
        trig["gold_current"] = {"month": gold.get("month"), "entry_day": gold.get("entry_day"),
                                "total": gold.get("total"),
                                "solo_fresh": _compact(gold.get("solo_fresh"), ["code", "name"])}
    else:
        trig["gold_current"] = {"solo_fresh": []}

    # ---- 命中反查索引（去重归并五源） ----
    hits = {}
    for r in trig["ops_state"]["deep_low"]:
        if r and r[0]:
            hits.setdefault(str(r[0]), []).append("deep_low")
    for k in ("sealed", "unsealed"):
        for it in (trig["ops_state"]["b5"].get(k) or []):
            code = str(it).split()[0] if it else None
            if code and code.isdigit():
                hits.setdefault(code, []).append("b5")
    for r in trig["reversal_confirmed"]["rows"]:
        if r and r[0]:
            hits.setdefault(str(r[0]), []).append("reversal_confirmed")
    for r in trig["watch_pool"]["rows"]:
        if r and r[0]:
            hits.setdefault(str(r[0]), []).append("watch_pool")
    for bucket in ("holdings", "pending"):
        for r in trig["pead_pool_state"][bucket]:
            if r and r[0]:
                hits.setdefault(str(r[0]), []).append("pead_pool")
    for r in trig["gold_current"]["solo_fresh"]:
        if r and r[0]:
            hits.setdefault(str(r[0]), []).append("gold_solo_fresh")

    # ---- 线健康摘要（line_health.json 的 status/grade/score） ----
    lh = jload("data/line_health.json")
    if isinstance(lh, dict):
        lmeta = lh.get("_meta") or {}
        fresh["line_health"] = fc.legacy_fresh_entry(ROOT, "data/line_health.json", "_meta.date", lmeta.get("date"), day)
        llines = lh.get("lines") or {}
        health = {
            "date": lmeta.get("date"), "version": lmeta.get("version"), "built_at": lmeta.get("built_at"),
            "n_lines": len(llines),
            "grade_counts": {},
            "critical_weak": [],
            "lines": {k: {"status": v.get("status"), "grade": v.get("grade") or "unknown",
                          "score": v.get("score"), "horizon": v.get("horizon")}
                      for k, v in llines.items()},
            "threats": [{"id": t.get("id"), "title": t.get("title"), "status": t.get("status")}
                        for t in (lh.get("threats") or [])],
            "n_proposals": len(lh.get("proposals") or []),
            "proposals": lh.get("proposals") or [],
        }
        for v in llines.values():
            g = v.get("grade") or "unknown"
            health["grade_counts"][g] = health["grade_counts"].get(g, 0) + 1
            if g in ("critical", "weak") or v.get("status") in ("ICU", "DECAYING", "DEAD"):
                health["critical_weak"].append({"line": k, "status": v.get("status"), "grade": g})
    else:
        unknown.append("data/line_health.json 缺失")
        health = {"n_lines": 0, "grade_counts": {}, "critical_weak": [], "lines": {}, "threats": [], "n_proposals": 0}
        fresh["line_health"] = fc.legacy_fresh_entry(ROOT, "data/line_health.json", "_meta.date", None, day)

    return {"health": health,
            "triggers": trig,
            "hits_index": {k: sorted(set(v)) for k, v in sorted(hits.items())}}


def build_knn(day, triggers, fresh, unknown):
    fp = D / f"similarity_daily_{day.replace('-', '')}.json"
    if not fp.exists():
        unknown.append(f"similarity_daily_{day.replace('-', '')}.json 缺失（KNN 未落盘）")
        fresh["similarity_daily"] = fc.legacy_fresh_entry(ROOT, str(fp.relative_to(ROOT)), "date", None, day)
        return {"date": day, "status": "missing", "scores": [], "trigger_codes": []}
    j = json.loads(fp.read_text(encoding="utf-8"))
    fresh["similarity_daily"] = fc.legacy_fresh_entry(ROOT, str(fp.relative_to(ROOT)), "date", j.get("date"), day)
    # 只嵌入当日触发名单内的票（全量仍在原产物，包内控体积）
    trig_codes = set()
    for r in triggers["ops_state"]["deep_low"]:
        if r and r[0]:
            trig_codes.add(str(r[0]))
    for r in triggers["reversal_confirmed"]["rows"]:
        if r and r[0]:
            trig_codes.add(str(r[0]))
    for r in triggers["watch_pool"]["rows"]:
        if r and r[0]:
            trig_codes.add(str(r[0]))
    for k in ("sealed", "unsealed"):
        for it in (triggers["ops_state"]["b5"].get(k) or []):
            c = str(it).split()[0] if it else ""
            if c.isdigit():
                trig_codes.add(c)
    scores = []
    for s in j.get("scores") or []:
        c = str(s.get("code"))
        if c not in trig_codes:
            continue
        scores.append({"code": c, "name": s.get("name"),
                       "src": s.get("sources"),
                       "t1": s.get("knn_t1_pct"), "t5": s.get("knn_t5_pct"), "t20": s.get("knn_t20_pct"),
                       "pct_rank": s.get("pct_rank_hist"), "top_decile": s.get("top_decile"),
                       "n_neighbors": s.get("n_neighbors"), "level": s.get("grid_level")})
    return {"date": j.get("date"), "status": "ok",
            "engine": (j.get("_meta") or {}).get("engine"),
            "learn_rows": (j.get("_meta") or {}).get("learn_rows"),
            "hist_quantiles": j.get("hist_score_t5_quantiles"),
            "n_total": len(j.get("scores") or []),
            "trigger_codes": sorted(trig_codes),
            "scores": scores}


def build_cluster(day, triggers, fresh, unknown):
    xr = jload("data/xrules_state.json")
    out = {"deep_low_n": len(triggers["ops_state"]["deep_low"]), "cluster_gate": CLUSTER_GATE}
    if isinstance(xr, dict):
        fresh["xrules_state"] = fc.legacy_fresh_entry(ROOT, "data/xrules_state.json", "date", xr.get("date"), day)
        out["xrules"] = {"date": xr.get("date"), "regime": xr.get("regime"), "ldc": xr.get("ldc"),
                         "gap_cluster": xr.get("gap_cluster"), "panic_cluster": xr.get("panic_cluster"),
                         "streak": xr.get("streak"), "entry_day": xr.get("entry_day"),
                         "rules": xr.get("rules") or {}, "shadow": xr.get("shadow") or {}}
    else:
        unknown.append("data/xrules_state.json 缺失")
        fresh["xrules_state"] = fc.legacy_fresh_entry(ROOT, "data/xrules_state.json", "date", None, day)
        out["xrules"] = None
    out["pass"] = out["deep_low_n"] >= CLUSTER_GATE
    return out


def build_holdings(day, triggers, fresh, unknown):
    wl = jload("config/watchlist.json")
    positions, alerts = [], []
    if isinstance(wl, dict):
        fresh["watchlist"] = {"file": "config/watchlist.json", "mtime": mtime_str("config/watchlist.json"),
                              "date_field": "mtime(状态制)", "date": mtime_str("config/watchlist.json")[:10],
                              "status": "ok"}
        for p in wl.get("positions") or []:
            positions.append({"code": str(p.get("code")), "name": p.get("name"), "note": p.get("note"),
                              "levels": p.get("levels") or {}})
        anchors = [{"code": str(a.get("code")), "name": a.get("name"), "buy": a.get("buy")}
                   for a in (wl.get("anchors") or [])]
    else:
        anchors = []
        unknown.append("config/watchlist.json 缺失")
        fresh["watchlist"] = {"file": "config/watchlist.json", "mtime": "unknown", "date_field": "mtime(状态制)",
                              "date": None, "status": "missing"}
    ops = jload("docs/ops-state.json") or {}
    for r in ops.get("positions_alert") or []:
        alerts.append({"code": str(r.get("code")), "name": r.get("name"), "flags": r.get("flags") or []})
    return {"positions": positions, "alerts": alerts, "dividend_anchors": anchors}


# ---------------- 段落渲染（与 preflight 共用同一函数，保证逐段一致） ----------------

def render_regime(reg, ref_date):
    """返回 (lines, fresh_tag)——消费端直接取用可打印行。"""
    out, tag = [], "unknown"
    axis, env = reg.get("axis"), reg.get("env")
    if not axis:
        return ["regime 时间轴产物缺失 → unknown"], tag
    age = (reg.get("age_entry") or {}).get("age", "?")
    tag = f"axis={axis.get('date')}"
    out.append(f"regime={axis.get('regime')} 段龄={age} "
               f"(轴 {axis.get('date')}；涨停{axis.get('boards')} 跌停{axis.get('downs')})")
    if env:
        out.append(f"趋势门={env.get('trend_gate')} 杠杆门={env.get('margin_gate')} "
                   f"四象限={env.get('quadrant') or 'unknown'} 下阶段={env.get('next_top')}"
                   f"({(env.get('next_prob') or 0) * 100:.0f}%)")
    else:
        out.append("env_state 快照缺失 → 趋势/杠杆门 unknown")
    return out, tag


def render_cluster(cl):
    out = []
    xr = cl.get("xrules")
    if xr:
        out.append(f"xrules {xr.get('date')}: 跌停簇{xr.get('ldc')} 缺口簇{xr.get('gap_cluster')} "
                   f"恐慌簇{xr.get('panic_cluster')} 恐慌streak{xr.get('streak')}")
        for rid, r in (xr.get("rules") or {}).items():
            if r.get("retired"):
                continue
            out.append(f"  {rid} {'已触发' if r.get('fired') else '未触发'}（{r.get('why')}）")
    else:
        out.append("簇状态产物缺失 → unknown")
    out.append(f"深档低位v2 当日同线触发 {cl.get('deep_low_n')} 只 vs 簇门≥{cl.get('cluster_gate')} "
               f"→ {'过门' if cl.get('pass') else '未过门'}")
    return out


def render_holdings(hd):
    out = []
    for p in hd.get("positions") or []:
        lv = " / ".join(f"{k}:{v}" for k, v in (p.get("levels") or {}).items())
        out.append(f"持仓 {p.get('name')}（{p.get('code')}）：{p.get('note')}")
        out.append(f"  关键位 {lv}")
    for a in hd.get("alerts") or []:
        out.append(f"哨兵 {a.get('name')}（{a.get('code')}）：{' '.join(a.get('flags') or [])}")
    if not out:
        out.append("无持仓哨兵配置（config/watchlist.json positions 为空）")
    return out


def render_health(h):
    out = [f"存活线 {h.get('n_lines')} 条，grade 分布 {h.get('grade_counts')}"]
    for c in h.get("critical_weak") or []:
        out.append(f"  ⛔ {c['line']} status={c['status']} grade={c['grade']}")
    for t in h.get("threats") or []:
        out.append(f"  威胁 {t['id']} {t['title'][:28]} → {t['status']}")
    out.append(f"待裁决提案 {h.get('n_proposals')} 条")
    return out


def render_freshness(fresh):
    out = []
    for k, v in sorted(fresh.items()):
        mark = {"ok": "✅", "stale": "⚠️过期", "missing": "❌缺失"}.get(v.get("status"), "?")
        out.append(f"{mark} {k}: {v.get('date')}（mtime {v.get('mtime')}）")
    return out


def one_line(pack):
    reg = pack["regime"].get("axis") or {}
    env = pack["regime"].get("env") or {}
    h = pack["lines"]["health"]
    st = pack.get("_meta", {}).get("stale_sources") or []
    return (f"{pack['date']} {reg.get('regime')}(第{(pack['regime'].get('age_entry') or {}).get('age', '?')}天) | "
            f"趋势门{env.get('trend_gate')} 杠杆门{env.get('margin_gate')} {env.get('quadrant') or '?'} | "
            f"触发 deep_low{pack['cluster'].get('deep_low_n')} 反转{len(pack['lines']['triggers']['reversal_confirmed']['rows'])} "
            f"观察池{len(pack['lines']['triggers']['watch_pool']['rows'])} | "
            f"线健康 {h.get('n_lines')} 条（危重{len(h.get('critical_weak') or [])}）| "
            f"KNN {pack['knn'].get('status')} | 过期源{len(st)}")


# ---------------- 主流程 ----------------

def build(day=None):
    t0 = time.time()
    idx = jload("data/index_sh000001.json") or []
    latest = idx[-1]["date"] if idx else datetime.now(BJT).date().isoformat()
    day = day or latest
    # DATA-07 熔断（R1-②展示型降级）：状态包照写，_meta 带 data_stale + 依赖项清单。
    # 默认路径用体检基准日；显式 --date 才以该日为基准。（变量名 _brk：本地 stale 已被占）
    _brk = {"data_stale": False, "stale_datasets": [], "reason": ""}
    try:
        sys.path.insert(0, str(ROOT / "engine")) if str(ROOT / "engine") not in sys.path else None
        import breaker
        _brk = breaker.stale_mark("日度状态包", None if day == latest else day)
    except Exception:
        pass
    fresh, unknown = {}, []

    fresh["index_sh000001"] = fc.legacy_fresh_entry(ROOT, "data/index_sh000001.json", "date", latest, day)

    reg = build_regime(day, fresh, unknown)
    lines = build_lines(day, fresh, unknown)
    knn = build_knn(day, lines["triggers"], fresh, unknown)

    if knn.get("status") != "ok":
        unknown.append("KNN 段落缺失 → 消费端 KNN 分位 unknown")

    cluster = build_cluster(day, lines["triggers"], fresh, unknown)
    holdings = build_holdings(day, lines["triggers"], fresh, unknown)

    stale = [k for k, v in fresh.items() if v.get("status") in ("stale", "missing")]

    # 交易日历：下一交易日（用指数日历 + 简单工作日推算，仅作提示不参与判据）
    nxt = None
    dates = [r["date"] for r in idx]
    if day in dates:
        i = dates.index(day)
        if i + 1 < len(dates):
            nxt = dates[i + 1]
        else:
            d = _date.fromisoformat(day) + timedelta(days=1)
            while d.weekday() >= 5:
                d += timedelta(days=1)
            nxt = d.isoformat()

    pack = {
        "_meta": {
            "version": "daily_state/1.0",
            "generated_at": datetime.now(BJT).isoformat(timespec="seconds"),
            "code_version": git_sha(),
            "data_snapshot": day,
            "owner": "engine.build_daily_state",
            "rule": "只读拼合既有产物，不重算信号；缺源写 unknown；同日重跑覆盖（幂等）",
            "cluster_gate": CLUSTER_GATE,
            "stale_sources": stale,
            # DATA-07 熔断降级标记（注册表 blocks 驱动，与 freshness 段互补：一个是逐源
            # 新鲜度清单，一个是「阻断级依赖是否命中」的机器可读判决）
            "data_stale": bool(_brk.get("data_stale")),
            "stale_datasets": _brk.get("stale_datasets") or [],
            "inputs": sorted({v["file"] for v in fresh.values()}),
            "elapsed_s": None,  # 收尾填
        },
        "date": day,
        "trading_day": {"latest_in_index": latest, "is_trading_day": day in dates, "next": nxt},
        "regime": reg,
        "lines": lines,
        "knn": knn,
        "cluster": cluster,
        "holdings": holdings,
        "freshness": fresh,
        "unknown": unknown,
    }
    reg_lines, _ = render_regime(reg, day)
    pack["sections"] = {
        "regime": reg_lines,
        "cluster": render_cluster(cluster),
        "holdings": render_holdings(holdings),
        "health": render_health(lines["health"]),
        "freshness": render_freshness(fresh),
    }
    pack["sections"]["one_line"] = one_line(pack)
    pack["_meta"]["elapsed_s"] = round(time.time() - t0, 2)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    op = OUTDIR / f"{day}.json"
    tmp = OUTDIR / f".{day}.json.tmp"
    tmp.write_text(json.dumps(pack, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, op)
    return op, pack


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--section", default=None,
                    choices=["regime", "cluster", "holdings", "health", "freshness", "one_line"])
    a = ap.parse_args()
    op, pack = build(a.date)
    if a.section:
        sec = pack["sections"][a.section]
        if isinstance(sec, list):
            print("\n".join(sec))
        else:
            print(sec)
        sys.exit(0)
    print(f"daily_state → {op}")
    print(f"  {pack['sections']['one_line']}")
    print(f"  段龄 {pack['trading_day']} | 过期/缺失源 {pack['_meta']['stale_sources']}")
    print(f"  触发 {len(pack['lines']['hits_index'])} 只票命中；KNN 嵌入 {len(pack['knn'].get('scores') or [])} 条"
          f"（全量 {pack['knn'].get('n_total')}）")
    if pack["unknown"]:
        print("  unknown: " + " | ".join(pack["unknown"][:6]))


if __name__ == "__main__":
    main()
