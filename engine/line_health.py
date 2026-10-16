#!/usr/bin/env python3
"""engine/line_health.py — 信号生命周期监控机（第三波卡 t_6f42f1a1，#278 红队对称）

每天收盘后对全部存活线体检。**只读+落盘+提案**：不改注册状态、不改参数、不自动升降级
（纪律同 #278：提案人工裁决；状态机投票权仍归每周 claims_audit.py）。

① 注册存活线（claims_state != DEAD）：
   - 滚动 250 交易日 edge + 滚动/全量胜率（复用 claims_audit.marginals_ex，与注册审计同代码同口径）
   - 最近 20 笔影子单实绩（data/claims_shadow.jsonl）vs 注册基线
   - 外部背书线（detector 不在 REGISTRY）：有影子数据则跟踪影子，否则标 external_no_shadow
② 影子观察层 RES-07/08（读 factor_census 矩阵，零宇宙加载，不占额外内存）：
   - knn_vote 顶档（RES-07）+ ivol20 / pv_corr_ov10@妖股期 / pv_corr_cv20@妖股期 /
     volcv20@妖股期（RES-08）：滚动 250 日日均超额、滚动 60 日、日胜率
③ 降级阈值机（只产提案）：
   - 破线：任一 horizon 滚动 edge 越过 kill 线，连续 >=5 次体检 → 降级提案
   - 贴线：0 <= 余量 < 0.5pp 连续 >=3 次 → 观察名单（晨报列出，不推 QQ）
   - 恢复：提案激活中或 DECAYING 的线，滚动 edge 回到基线 70% 连续 >=3 次 → 恢复提案
④ #278 七条证据威胁 = 首批监控项 T1-T7（读既有数据文件，不重跑回测）

输出：
  data/line_health.json        机器可读全量（_meta 带版本锚）
  data/line_health_state.json  阈值机状态（按日幂等：同日重跑覆盖当日记录，不重复计数）
  data/line_health_report.md   晨报段落（供晨报 cron 引用）
  stdout                       仅「新增触发」时打印告警（看门狗纪律：无触发零输出）

用法：.venv/bin/python engine/line_health.py [--report] [--only CLAIM_ID ...]
  --report 强制打印晨报段落；--only 只扫指定注册线（调试/小样本验证用）
内存纪律：单宇宙加载一次、逐线顺序扫描，不多线并载（同 claims_audit 周审计的已验证形态）。
"""
import json, re, statistics as st, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
DATA = ROOT / "data"
OUT_JSON = DATA / "line_health.json"
STATE_JSON = DATA / "line_health_state.json"
REPORT_MD = DATA / "line_health_report.md"
CKPT_JSON = DATA / "line_health_checkpoint.json"  # 逐线 checkpoint：OOM/重跑续扫（同日有效）
REG_YAML = DATA / "claims_registry.yaml"
CLAIMS_STATE = DATA / "claims_state.json"
SHADOW = DATA / "claims_shadow.jsonl"

ROLL_N = 250          # 滚动窗口（交易日，与注册审计一致）
NEAR_BUFFER_PP = 0.5  # 贴线余量
BELOW_DAYS_N = 5      # 连续破线次数 → 降级提案
NEAR_DAYS_N = 3       # 连续贴线次数 → 观察名单
RECOVER_DAYS_N = 3    # 连续回到基线 70% → 恢复提案
RECOVER_RATIO = 0.7
SHADOW_N = 20         # 影子尾窗
VERSION = "line_health/1.0 (2026-10-15, t_6f42f1a1)"


def bjt_now():
    return datetime.now(timezone.utc) + timedelta(hours=8)


def load_universe_lean():
    """低内存版 load_universe（与 law_pipeline.load_universe 同值，15GB 机器白天防 OOM）：
    - 数值六列用 array('d')（索引/切片/比较语义与 list 一致，探测器无感）
    - ma60 仍是 list（前 60 根 None 语义保留，claims_audit 的 `is None` 判定不受影响）
    - date 列去重共享字符串（1900 个唯一值 vs 630 万独立对象）
    口径锚：ma60 前缀和算法逐行对齐 law_pipeline.load_universe；正确性验证 =
    --only 复跑对照 claims_state.json 里周审计（原版 loader）记录的 roll_pp。
    """
    import glob as _glob
    from array import array
    sys.path.insert(0, str(ROOT / "engine"))
    from law_pipeline import KC
    stocks = {}
    for fp in _glob.glob(str(KC / "*.json")):
        ks = json.loads(open(fp).read())
        if len(ks) < 300:
            continue
        c = [k["close"] for k in ks]
        pre = [0.0]
        for x in c:
            pre.append(pre[-1] + x)
        ma60 = [None] * 60 + [(pre[i + 1] - pre[i - 59]) / 60 for i in range(59, len(c) - 1)]
        ma60.append((pre[len(c)] - pre[len(c) - 60]) / 60)
        ma60 = ma60[:len(c)]  # 与原版相同的截断
        intern = {}
        dates = [intern.setdefault(k["date"], k["date"]) for k in ks]
        stocks[Path(fp).stem] = {
            "code": Path(fp).stem,
            "c": array("d", c), "o": array("d", (k["open"] for k in ks)),
            "h": array("d", (k["high"] for k in ks)), "l": array("d", (k["low"] for k in ks)),
            "v": array("d", (k.get("volume", 0) for k in ks)), "ma60": ma60,
            "amt": array("d", (k.get("amount", 0.0) for k in ks)),
            "date": dates, "n": len(ks),
        }
    return stocks


def jload(p, default=None):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


# ---------------- 影子账本 ----------------

def load_shadow():
    """{claim: [entry...]} 按 (signal_date) 排序；r 字段 None=未结算，统计时剔除"""
    sh = {}
    if not SHADOW.exists():
        return sh
    for line in SHADOW.open():
        try:
            r = json.loads(line)
        except Exception:
            continue
        sh.setdefault(r.get("claim"), []).append(r)
    for v in sh.values():
        v.sort(key=lambda r: r.get("signal_date", ""))
    return sh


def shadow_tail(shadow, claim, n=SHADOW_N, since=None):
    """最近 n 笔（可选 since 日期起）→ {r1: {n,mean%,win%}, ...}；影子是毛收益口径（含费前入场价差），
    与注册基线（边际 pp）不是同一口径，只按符号发散判读。"""
    rows = shadow.get(claim, [])
    if since:
        rows = [r for r in rows if r.get("signal_date", "") >= since]
    rows = rows[-n:]
    out = {}
    for k in ("r1", "r5", "r10"):
        vals = [r[k] for r in rows if isinstance(r.get(k), (int, float))]
        if vals:
            out[k] = {"n": len(vals), "mean_pp": round(100 * st.mean(vals), 2),
                      "win": round(100 * sum(1 for x in vals if x > 0) / len(vals), 1)}
    return {"window_n": len(rows), "horizons": out,
            "last_date": rows[-1].get("signal_date") if rows else None}


# ---------------- 注册存活线扫描 ----------------

def resolve_detector(det_key):
    """返回 (detector_name, is_external)。精确命中 REGISTRY 或 detector 字段写明
    'law_pipeline REGISTRY <名>' 的别名线走注册口径复跑；其余外部背书线只跟踪影子。"""
    sys.path.insert(0, str(ROOT / "engine"))
    from law_pipeline import REGISTRY
    if det_key in REGISTRY:
        return det_key, False
    m = re.search(r"REGISTRY\s*[：:]?\s*(\S+)", det_key or "")
    if m and m.group(1).rstrip("）)）") in REGISTRY:
        return m.group(1).rstrip("）)）"), False
    return det_key, True


def scan_lines(claims, cstate, shadow, only=None):
    """单宇宙逐线扫描（lean loader，峰值约为原版一半）。逐线 checkpoint：
    每扫完一条落盘 CKPT_JSON，进程被杀后重跑自动跳过已完成线（同日有效）。返回 {cid: line_dict}"""
    from law_pipeline import REGISTRY, build_xsection  # noqa
    from claims_audit import marginals_ex
    today = bjt_now().date().isoformat()
    ckpt = jload(CKPT_JSON, {}) or {}
    cached = ckpt.get("lines", {}) if ckpt.get("date") == today else {}
    lines = dict(cached)
    if cached:
        print(f"[line_health] checkpoint 复用 {len(cached)} 线", file=sys.stderr, flush=True)
    stocks = None

    def _save_ckpt():
        CKPT_JSON.write_text(json.dumps({"date": today, "lines": lines}, ensure_ascii=False))

    for c in claims:
        for fld in ("kill_line_pp", "baseline_pp"):
            if isinstance(c.get(fld), dict):
                c[fld] = {int(k): v for k, v in c[fld].items()}
        cid = c["id"]
        if only and cid not in only:
            continue
        if cid in lines:
            continue
        if cstate.get(cid, {}).get("status", "CANDIDATE") == "DEAD":
            continue
        det_key = c.get("detector", "")
        det_name, external = resolve_detector(det_key)
        rec = {"id": cid, "status": cstate.get(cid, {}).get("status", "CANDIDATE"),
               "detector": det_name, "external": external,
               "horizon": c.get("horizon") or [], "statement": c.get("statement", "")[:60]}
        sh = shadow_tail(shadow, cid)
        if sh["window_n"]:
            rec["shadow"] = sh
        if external:
            rec["note"] = "外部背书线：滚动 edge 不复跑，只跟踪影子/自有数据"
            lines[cid] = rec
            _save_ckpt()
            continue
        if stocks is None:
            t0 = time.time()
            stocks = load_universe_lean()
            build_xsection(stocks)
            print(f"[line_health] universe(lean) loaded {len(stocks)} 票 {time.time()-t0:.0f}s",
                  file=sys.stderr, flush=True)
        res = marginals_ex(REGISTRY[det_name], stocks, c.get("control", "random_entry"),
                           c["horizon"], entry=c.get("entry", "next_open"))
        hz = {}
        for h in c["horizon"]:
            if h not in res:
                hz[str(h)] = {"roll_pp": None, "note": "样本<30，本轮无滚动值"}
                continue
            v = res[h]
            kill = c["kill_line_pp"].get(h, 0.0)
            base = c["baseline_pp"].get(h)
            neg = c.get("direction") in ("negative", "neg")
            margin = None if v["roll_pp"] is None else (
                (kill - v["roll_pp"]) if neg else (v["roll_pp"] - kill))
            hz[str(h)] = {**v, "kill_pp": kill, "baseline_pp": base, "direction": "neg" if neg else "pos",
                          "margin_pp": None if margin is None else round(margin, 2),
                          "ok": None if margin is None else margin >= 0,
                          "near": None if margin is None else 0 <= margin < NEAR_BUFFER_PP}
        rec["horizons"] = hz
        # 影子发散：影子近 20 笔均值 <0 而注册基线 >0（仅共同 horizon：r1/r5/r10）
        dv = []
        for h in c["horizon"]:
            k = f"r{h}"
            if k in sh.get("horizons", {}):
                s5 = sh["horizons"][k]
                base = (c.get("baseline_pp") or {}).get(h)
                if s5["n"] >= 5 and s5["mean_pp"] < 0 and (base or 0) > 0:
                    dv.append({"h": h, "shadow_mean_pp": s5["mean_pp"], "shadow_n": s5["n"],
                               "baseline_pp": base})
        if dv:
            rec["shadow_divergence"] = dv
        rec["score"], rec["grade"] = health_score(rec, c)
        lines[cid] = rec
        _save_ckpt()
        print(f"[line_health] {cid} done score={rec['score']}", file=sys.stderr, flush=True)
    return lines


def health_score(rec, claim):
    """0-100 健康分：破线 -35/h（取最劣不叠加贴线）、贴线 -15/h、DECAYING -20、影子发散 -20。"""
    score = 100
    for v in rec.get("horizons", {}).values():
        if v.get("ok") is False:
            score -= 35
        elif v.get("near"):
            score -= 15
    if rec.get("status") == "DECAYING":
        score -= 20
    if rec.get("shadow_divergence"):
        score -= 20
    score = max(0, score)
    grade = "healthy" if score >= 80 else "watch" if score >= 60 else "weak" if score >= 40 else "critical"
    return score, grade


# ---------------- RES-07/08 影子观察层 ----------------

RES_MASKS = {  # 观察名 -> (npz 键, 说明, 来源)
    "knn_vote_top": ("dec:knn_vote", "RES-07 协同过滤打分顶档（T+5 期望分前 10%）", "#276/#277"),
    "ivol20": ("m_ivol20", "RES-08 低特质波动尾", "#277"),
    "pv_corr_ov10@yao": ("m_pv_corr_ov10@regime=妖股期", "RES-08 量价背离ov10×妖股期", "#277"),
    "pv_corr_cv20@yao": ("m_pv_corr_cv20@regime=妖股期", "RES-08 量价背离cv20×妖股期", "#277"),
    "volcv20@yao": ("m_volcv20@regime=妖股期", "RES-08 量变系数×妖股期", "#277"),
}


def res_layer():
    """读 factor_census 矩阵（~100MB，一次性），算各观察线的滚动日均超额（T+5，净费口径）。"""
    import numpy as np
    base, mask_f = DATA / "factor_census_base.npz", DATA / "factor_census_masks.npz"
    if not base.exists():
        return {"note": "factor_census_base.npz 缺失，RES 层跳过"}
    zb = np.load(base)
    zm = np.load(mask_f) if mask_f.exists() else None
    cal = zb["calendar"].tolist()
    ret5 = zb["ret_5"].astype("float64")
    import warnings
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    with np.errstate(all="ignore"):
        univ = np.nanmean(ret5, axis=1)  # 每日全宇宙均值
    w250, w60 = max(0, len(cal) - ROLL_N), max(0, len(cal) - 60)
    out = {}
    for name, (key, desc, ref) in RES_MASKS.items():
        try:
            if key.startswith("dec:"):
                if f"dec_{key[4:]}" not in zb:
                    out[name] = {"note": "dec 矩阵缺失", "desc": desc}
                    continue
                m = zb[f"dec_{key[4:]}"] == 9
            else:
                if zm is None or key not in zm:
                    out[name] = {"note": "mask 缺失", "desc": desc}
                    continue
                m = zm[key]
            sel = np.where(m, ret5, np.nan)
            with np.errstate(all="ignore"):
                daily_n = np.sum(m & np.isfinite(ret5), axis=1)
                daily_ex = np.nanmean(sel, axis=1) - univ
            valid = np.isfinite(daily_ex) & (daily_n >= 5)
            seg, seg60 = daily_ex[w250:][valid[w250:]], daily_ex[w60:][valid[w60:]]
            if len(seg) < 20:
                out[name] = {"note": f"有效日不足({len(seg)})", "desc": desc}
                continue
            out[name] = {"desc": desc, "ref": ref,
                         "roll250_pp": round(100 * float(np.mean(seg)), 3),
                         "roll60_pp": round(100 * float(np.mean(seg60)), 3) if len(seg60) else None,
                         "day_win": round(100 * float(np.mean(seg > 0)), 1),
                         "days": len(seg), "window_start": cal[w250]}
        except Exception as e:
            print(f"[WARN] res_layer {name}: {e}", file=sys.stderr)
            out[name] = {"note": f"计算失败: {e}", "desc": desc}
    return out


# ---------------- #278 七条威胁 = 首批监控项 ----------------

def _threat(tid, title, status, metrics, proposal=None):
    return {"id": tid, "title": title, "status": status, "metrics": metrics,
            "proposal": proposal, "source": "#278"}


def check_threats(shadow):
    """每条读既有产物文件；文件缺失→no_data 优雅降级；触发→triggered（含 #278 已立案的standing项）。"""
    T = []
    today = bjt_now().date()
    # T1 跌停次日接 T+1 腿（影子 60 日窗）
    s = shadow_tail(shadow, "LIMITDOWN_NEXT_DAY", n=10 ** 9,
                    since=(today - timedelta(days=60)).isoformat())
    r1 = s["horizons"].get("r1")
    if r1:
        trig = r1["n"] >= 20 and r1["mean_pp"] < 0
        T.append(_threat("T1", "跌停次日接 T+1 腿 edge 归零", "triggered" if trig else "ok",
                         {"r1": r1, "r5": s["horizons"].get("r5"), "window": "60d"},
                         "T+1 腿进 ICU 观察（#278 已提案，待裁决）" if trig else None))
    else:
        T.append(_threat("T1", "跌停次日接 T+1 腿", "no_data", {}))
    # T2 预增低位池：低价层口径 bug + 2026 组合模拟转负
    pp = ROOT / "engine/pead_pool.py"
    src = pp.read_text() if pp.exists() else ""
    trades = jload(DATA / "pead_pool_sim_trades.json", []) or []
    if not src and not trades:
        T.append(_threat("T2", "预增低位池", "no_data", {}))
    else:
        bug = ('"close"] < 5' in src or "'close'] < 5" in src) and "big_kcache_unadj" not in src
        t26 = [t["ret"] for t in trades if str(t.get("entry_d", "")).startswith("2026")]
        m26 = {"n": len(t26),
               "mean_pp": round(100 * st.mean(t26), 2) if t26 else None,
               "win": round(100 * sum(1 for x in t26 if x > 0) / len(t26), 1) if t26 else None}
        trig = bug or (t26 and st.mean(t26) < 0)
        T.append(_threat("T2", "预增低位池：低价层读前复权价 bug + 2026 转负",
                         "triggered" if trig else "ok",
                         {"price_bug_present": bug, "sim_2026": m26},
                         "PFX-01 口径修复 + 降置信，待裁决（#278 已提案）" if trig else None))
    # T3 摇篮线年集中
    cr = jload(DATA / "cradle_horizon_20260927.json", []) or []
    if cr:
        by_year = {}
        for e in cr:
            by_year.setdefault(str(e["date"])[:4], []).append(e)
        top_year = max(by_year, key=lambda y: len(by_year[y]))
        share = len(by_year[top_year]) / len(cr)
        y26 = by_year.get("2026", [])
        w26 = (round(sum(1 for e in y26 if (e.get("t20") or 0) > 0) / len(y26), 2)) if y26 else None
        stale = (today - datetime.fromtimestamp((DATA / "cradle_horizon_20260927.json").stat().st_mtime).date()).days
        trig = share > 0.4 and (w26 is None or w26 < 0.5)
        T.append(_threat("T3", "摇篮线 2024 单年依赖超限", "triggered" if trig else "ok",
                         {"top_year": top_year, "top_year_share": round(share, 2),
                          "y2026_t20_win": w26, "file_age_days": stale},
                         "降为年集中假设+推送降权（#278 已提案，待裁决）" if trig else None))
    else:
        T.append(_threat("T3", "摇篮线年集中", "no_data", {}))
    # T4 深档低位 v2：批次断档 + 影子变体 r5
    db = jload(DATA / "deep_batches_full_20260927.json", []) or []
    last_batch = max((e["date"] for e in db), default=None)
    gap = (today - datetime.strptime(last_batch, "%Y-%m-%d").date()).days if last_batch else None
    b26 = [e for e in db if e["date"].startswith("2026")]
    variants = {}
    for vc in ("COMP_LIMITDOWN_LOW_DEEP", "COMP_LIMITDOWN_LOW_SHRINK_XFUND",
               "COMP_LIMITDOWN_LOW_3DOWN_SHRINK", "COMP_LIMITDOWN_LOW_3DOWN_DEEP"):
        sv = shadow_tail(shadow, vc, n=10 ** 9, since="2026-08-19")
        if sv["horizons"].get("r5"):
            variants[vc] = sv["horizons"]["r5"]
    bad = [k for k, v in variants.items() if v["n"] >= 3 and v["win"] == 0]
    trig = bool(bad)
    T.append(_threat("T4", "深档低位 v2：2026 收益集中 + 近期影子走坏",
                     "triggered" if trig else "ok",
                     {"last_batch": last_batch, "days_since_batch": gap,
                      "batches_2026": {"n": len(b26),
                                       "win": round(sum(e["hit"] for e in b26) / len(b26), 2) if b26 else None},
                      "shadow_r5_since_0819": variants, "zero_win_variants": bad},
                     "维持存活降置信；影子 r20 仍负 → 进 ICU 提案（#278）" if trig else None))
    # T5 转债低价池信用等级
    cb = jload(DATA / "cb_low_price.json", {}) or {}
    pool = cb.get("pool", [])
    if not pool:
        T.append(_threat("T5", "转债低价池信用等级", "no_data", {}))
    else:
        junk = [{"code": p["code"], "name": p["name"], "rating": p.get("rating")}
                for p in pool if (p.get("rating") or "AA") in ("CCC+", "CCC", "CCC-", "CC", "C", "D")]
        T.append(_threat("T5", "转债低价池装入违约级债", "triggered" if junk else "ok",
                         {"pool_n": len(pool), "junk": junk, "pool_date": cb.get("date")},
                         "池加评级闸（剔 CCC 及以下）或推送标注「信用困境债≠债底」（#278 已提案）" if junk else None))
    # T6 股息锚 2026 实盘曲线
    dc = jload(DATA / "dividend_curve_exam2026.json", []) or []
    if len(dc) >= 2:
        ret = dc[-1][1] / dc[0][1] - 1
        diffs = [dc[i][1] / dc[i - 1][1] - 1 for i in range(1, len(dc))]
        trig = ret < 0
        T.append(_threat("T6", "股息锚 2026 实盘检验转负", "triggered" if trig else "ok",
                         {"curve_ret_pp": round(100 * ret, 2),
                          "day_win": round(100 * sum(1 for x in diffs if x > 0) / len(diffs), 1),
                          "span": [dc[0][0], dc[-1][0]]},
                         "列入月度上会体温表；TAX-01 红利税建模维持 backlog（#278）" if trig else None))
    else:
        T.append(_threat("T6", "股息锚 2026 实盘检验", "no_data", {}))
    # T7 金股×三连阴变体影子
    s7 = shadow_tail(shadow, "THREE_DOWN_GOLD")
    r5 = s7["horizons"].get("r5")
    if r5:
        trig = r5["n"] >= 10 and r5["mean_pp"] < 0
        T.append(_threat("T7", "金股×三连阴变体（THREE_DOWN_GOLD）影子走坏",
                         "triggered" if trig else "ok", {"r5": r5, "last": s7["last_date"]},
                         "变体降级观察，主线不动（#278 已提案，待裁决）" if trig else None))
    else:
        T.append(_threat("T7", "金股×三连阴变体", "no_data", {}))
    return T


# ---------------- 降级阈值机（只产提案） ----------------

def threshold_machine(lines, res, threats):
    """按日幂等更新状态；返回 (state, new_alerts[])。新增触发才进 new_alerts（QQ 用）。"""
    today = bjt_now().date().isoformat()
    st_file = jload(STATE_JSON, {}) or {}
    ls = st_file.setdefault("lines", {})
    alerts = []

    def _tail_count(hist, pred):
        n = 0
        for h in reversed(hist):
            if pred(h):
                n += 1
            else:
                break
        return n

    for cid, rec in lines.items():
        if rec.get("external") or not rec.get("horizons"):
            continue
        e = ls.setdefault(cid, {"history": [], "below_days": 0, "near_days": 0,
                                "recover_days": 0, "proposal": None, "proposal_since": None})
        hz = [v for v in rec["horizons"].values() if v.get("ok") is not None]
        if not hz:
            continue
        below = any(not v["ok"] for v in hz)
        near = (not below) and any(v["near"] for v in hz)
        recov = all(
            v["roll_pp"] is not None and v.get("baseline_pp") is not None
            and ((v["roll_pp"] <= RECOVER_RATIO * v["baseline_pp"]) if v["direction"] == "neg"
                 else (v["roll_pp"] >= RECOVER_RATIO * v["baseline_pp"]))
            for v in hz)
        hist = [h for h in e["history"] if h["date"] != today]  # 同日重跑覆盖=幂等
        hist.append({"date": today, "below": below, "near": near, "recover": recov})
        e["history"] = hist[-30:]
        e["below_days"] = _tail_count(e["history"], lambda h: h.get("below"))
        e["near_days"] = _tail_count(e["history"], lambda h: h.get("near") and not h.get("below"))
        e["recover_days"] = _tail_count(e["history"], lambda h: h.get("recover"))
        # 降级提案：连续破线
        if e["below_days"] >= BELOW_DAYS_N and e["proposal"] != "downgrade":
            e["proposal"], e["proposal_since"] = "downgrade", today
            worst = min((v for v in hz), key=lambda v: v["margin_pp"])
            alerts.append(f"[降级提案] {cid}：滚动 edge 连续 {e['below_days']} 次破 kill 线"
                          f"（最劣余量 {worst['margin_pp']}pp vs kill {worst['kill_pp']}pp）"
                          f"——建议人工裁决降级/ICU，监控机不自动执行")
        # 恢复提案：提案激活中/DECAYING，回到基线 70%
        if (e["proposal"] or rec.get("status") == "DECAYING") and \
                e["recover_days"] >= RECOVER_DAYS_N and e["proposal"] == "downgrade":
            e["proposal"] = None
            alerts.append(f"[恢复提案] {cid}：滚动 edge 连续 {e['recover_days']} 次回到基线 "
                          f"{int(RECOVER_RATIO*100)}% 以上——建议人工裁决解除降级")
    # RES 层阈值：滚动 250 日超额 <=0 → 销案观察提案；0~0.3pp → watch
    rs = st_file.setdefault("res", {})
    for name, r in res.items():
        if "roll250_pp" not in r:
            continue
        e = rs.setdefault(name, {"proposal": None})
        if r["roll250_pp"] <= 0 and e["proposal"] != "drop":
            e["proposal"] = "drop"
            alerts.append(f"[观察层销案提案] {name}（{r.get('desc','')}）：滚动250日日均超额 "
                          f"{r['roll250_pp']}pp 转负——建议人工裁决销案（RES 层不自动除名）")
        elif 0 < r["roll250_pp"] < 0.3:
            r["watch"] = True
    # 威胁项：新增触发才告警（standing 项只在晨报列）
    ts = st_file.setdefault("threats", {})
    for t in threats:
        e = ts.setdefault(t["id"], {"active": False})
        if t["status"] == "triggered" and not e["active"]:
            alerts.append(f"[威胁触发] {t['id']} {t['title']}：{t.get('proposal') or '见 line_health.json'}")
        e["active"] = t["status"] == "triggered"
    STATE_JSON.write_text(json.dumps(st_file, ensure_ascii=False, indent=1))
    return st_file, alerts


# ---------------- 输出 ----------------

def render_report(today, lines, res, threats, st_file):
    g = {"healthy": [], "watch": [], "weak": [], "critical": []}
    ext = []
    for cid, r in lines.items():
        (ext if r.get("external") else g[r.get("grade", "watch")]).append(cid)
    txt = [f"【信号线健康 · {today}】（滚动{ROLL_N}交易日口径，与注册审计同方法；只产提案不自动执行）",
           f"存活线 {sum(len(v) for v in g.values())} 条：健康 {len(g['healthy'])} / 观察 {len(g['watch'])}"
           f" / 走弱 {len(g['weak'])} / 危重 {len(g['critical'])}；外部背书线 {len(ext)} 条"]
    for gd, label in (("critical", "危重"), ("weak", "走弱")):
        for cid in g[gd]:
            r = lines[cid]
            hs = " ".join(f"T+{h} {v.get('roll_pp')}/{v.get('kill_pp')}pp"
                          for h, v in r.get("horizons", {}).items())
            txt.append(f"· {label} {cid}（{r['score']}分）：滚动edge/kill {hs}")
    near = [(cid, h, v) for cid, r in lines.items()
            for h, v in r.get("horizons", {}).items() if v.get("near")]
    if near:
        txt.append("· 贴线观察（余量<0.5pp，连续3次进观察名单）：" +
                   "；".join(f"{cid} T+{h} 余量{v['margin_pp']}pp" for cid, h, v in near))
    div = [(cid, d) for cid, r in lines.items() for d in r.get("shadow_divergence", [])]
    if div:
        txt.append("· 影子背离（近20笔均值<0 而注册基线为正）：" +
                   "；".join(f"{cid} T+{d['h']} {d['shadow_mean_pp']}pp(n={d['shadow_n']})" for cid, d in div))
    res_bits = [f"{n} {r['roll250_pp']}pp" for n, r in res.items() if "roll250_pp" in r]
    if res_bits:
        txt.append("· RES-07/08 观察层滚动250日：" + "、".join(res_bits))
    tmap = {"triggered": "触发中", "ok": "正常", "no_data": "无数据"}
    txt.append("· #278 威胁监控：" + "；".join(f"{t['id']}{tmap.get(t['status'], t['status'])}"
                                              for t in threats))
    props = [a for a in _all_proposals(st_file)]
    if props:
        txt.append(f"· 待裁决提案 {len(props)} 条：")
        txt += [f"  {i}) {p}" for i, p in enumerate(props, 1)]
    return "\n".join(txt) + "\n"


def _all_proposals(st_file):
    out = []
    for cid, e in (st_file.get("lines") or {}).items():
        if e.get("proposal") == "downgrade":
            out.append(f"{cid} 降级提案（{e.get('proposal_since')} 起，连续破线 {e.get('below_days')} 次）")
    for n, e in (st_file.get("res") or {}).items():
        if e.get("proposal") == "drop":
            out.append(f"RES 观察层 {n} 销案提案")
    for t in (st_file.get("threats") or {}).items():
        if t[1].get("active"):
            out.append(f"{t[0]} 威胁触发中（#278 提案待裁决）")
    return out


def main():
    args = sys.argv[1:]
    only = None
    if "--only" in args:
        i = args.index("--only")
        only = set(args[i + 1:])
    import yaml
    claims = yaml.safe_load(REG_YAML.read_text())["claims"]
    cstate = jload(CLAIMS_STATE, {}) or {}
    shadow = load_shadow()
    lines = scan_lines(claims, cstate, shadow, only)
    res = {} if only else res_layer()
    threats = check_threats(shadow)
    st_file, alerts = threshold_machine(lines, res, threats)
    today = bjt_now().date().isoformat()
    doc = {"_meta": {"version": VERSION, "built_at": bjt_now().isoformat(timespec="seconds"),
                     "date": today, "method": "rolling 250 trading days, same code as claims_audit.marginals_ex",
                     "discipline": "proposals only, no auto state change (#278)"},
           "lines": lines, "res_layer": res, "threats": threats,
           "proposals": _all_proposals(st_file)}
    OUT_JSON.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    report = render_report(today, lines, res, threats, st_file)
    REPORT_MD.write_text(report)
    if alerts:
        print(f"【信号线告警 {today}】")
        for a in alerts:
            print(a)
    if "--report" in args:
        print(report)
    if not alerts and "--report" not in args:
        pass  # 看门狗纪律：无触发零输出


if __name__ == "__main__":
    main()
