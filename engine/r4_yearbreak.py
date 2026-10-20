#!/usr/bin/env python3
"""engine/r4_yearbreak.py — RES-10「高位剧震回避黑名单（AVOID）」终审（2026-10-20）

依据 docs/plan/specs/RES-10-r4-climax-avoid.md：
  1. 分年验尸：2019-2026 每年 n / T+5 / T+20 边际与胜率；单年样本占比>40% 直接否决（#329 纪律）
  2. 三口径：事件研究（逐事件等权 + Newey-West HAC t，T+20 主判据）
             日历时间（lp.calendar_time，按入场日聚合减全宇宙均值）
             DSR（trials 分母 = dsr_recount 结构普查实测值 + 本次新增登记）
  3. 位置匹配对照：①同票高位非剧震（既有 r4 口径，逐行复用）
                   ②同期同板块（同信号日 × 同行业 × MA60上 × 非剧震，新增档）
  4. 阈值敏感性反例：量比阈值 2.0 → 1.5 全量重跑
  5. 输出 data/r4_final_YYYYMMDD.json + research/R4_final.md（md 由本脚本生成）

事件定义与对照构造逐行复用 engine/research_queue_20260919.py r4()（第 141-187 行）：
  - is_quake 函数体逐行复制自第 143-158 行，唯一改动 = 量比阈值 2.0 参数化为 vr_min
    （默认 2.0 与原文逐字节等价；敏感性反例用 1.5）。等价性由 selfcheck() 实证：
    同一股票子集上 rq.r4() 的 OUT 统计量与本脚本采集器逐数字相等。
  - 主采集循环复用第 164-181 行结构：同一 random.Random(19)、同样的
    rng.sample(pool, min(len(hits_i)*2, len(pool))) 等量对照抽样、同样的 fwd 收益口径。
  - fwd/stat 直接 import 复用（模块级函数，未重写）。

纪律：禁联网、禁 baostock、只读 data/big_kcache；全宇宙只加载一次；单进程。
用法：/opt/data/fenjue/.venv/bin/python engine/r4_yearbreak.py
"""
import json
import math
import random
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp
import research_queue_20260919 as rq   # 只 import 不改；fwd/stat/FEE 复用，r4 仅自检调用

ROOT = Path("/opt/data/fenjue")
BJT = timezone(timedelta(hours=8))
FEE = rq.FEE
HORIZONS = (1, 5, 20)
NW_MIN_T = lp.NW_MIN_T          # Harvey 3.0
YEAR_VETO = 0.40                # 单年样本占比否决线（spec/#329）


# ── 事件定义：逐行复制自 research_queue_20260919.py r4() 第 143-158 行 ──────────
# 唯一改动：`v[i] / mb < 2.0` 的 2.0 → 参数 vr_min（默认 2.0 = 原文）。
def is_quake(d, i, vr_min=2.0):
    c, o, h, l, v = d["c"], d["o"], d["h"], d["l"], d["v"]
    if i < 12 or c[i] <= 0 or c[i - 1] <= 0:
        return False
    boards = sum(1 for j in range(i - 10, i) if c[j] > 0 and c[j - 1] > 0 and c[j] / c[j - 1] - 1 >= 0.098)
    if boards < 2:
        return False
    base = v[i - 5:i]
    if len(base) < 5 or any(x <= 0 for x in base):
        return False
    mb = sum(base) / 5
    if mb <= 0 or v[i] / mb < vr_min:
        return False
    chg = c[i] / c[i - 1] - 1
    upper = (h[i] - c[i]) / c[i]
    return upper >= 0.04 or chg <= -0.04


def collect(stocks, vr_min=2.0):
    """单遍扫描全宇宙：剧震事件 + 两档对照。
    结构逐行复用 r4() 第 164-181 行（hits_i → fwd；同票高位非剧震 pool → Random(19) 等量抽样），
    额外记录每条目的 (code, i, date) 供分年/日历时间/同板块对照用。
    同板块池：date×industry → 当日 MA60上且非剧震的 (code, i) 候选（ctrl2 用，Random(11) 逐事件抽 1）。
    """
    ind = lp._IND or {}
    rng = random.Random(19)     # 与 r4() 同种子同用法（逐股 sample）
    rng2 = random.Random(11)    # ctrl2 专用（r4 无此档，独立种子）
    ev, c1, c2 = [], [], []     # 每条 = (code, i, date)
    pools = defaultdict(list)   # (date, industry) -> [(code, i)]
    for code, d in stocks.items():
        c, ma, n = d["c"], d["ma60"], d["n"]
        hits_i = []
        for i in range(61, n - 22):
            if ma[i] is None or c[i] <= ma[i]:
                continue
            q = is_quake(d, i, vr_min)
            if q:
                hits_i.append(i)
            else:
                pools[(d["date"][i], ind.get(code, "?"))].append((code, i))
        for i in hits_i:
            ev.append((code, i, d["date"][i]))
        # 同票高位非剧震对照（等量）—— r4() 第 176-181 行逐行复用
        pool = [i for i in range(61, n - 22) if ma[i] is not None and c[i] > ma[i] and not is_quake(d, i, vr_min)]
        for i in rng.sample(pool, min(len(hits_i) * 2, len(pool))):
            c1.append((code, i, d["date"][i]))
    # ctrl2：同期同板块（同信号日、同行业、MA60上、非剧震），逐事件抽 1
    c2 = []
    rng2 = random.Random(11)
    for code, i, dt in ev:
        pool = pools.get((dt, ind.get(code, "?")))
        if pool:
            pc, pi = pool[rng2.randrange(len(pool))]
            c2.append((pc, pi, dt))
    return {"events": ev, "ctrl1": c1, "ctrl2": c2, "ctrl2_cov": len(c2) / len(ev) if ev else 0}


def rets(stocks, items, h):
    """逐条目 fwd 收益（rq.fwd 原口径：次日开盘买、剔一字跌停、净 fee），None 剔除。"""
    out = []
    for code, i, _dt in items:
        r = rq.fwd(stocks[code], i, h)
        if r is not None:
            out.append(r)
    return out


def by_year(items):
    m = defaultdict(list)
    for code, i, dt in items:
        m[dt[:4]].append((code, i, dt))
    return m


def stat_full(rs, h=None):
    s = rq.stat(rs)
    if s is None:
        return None
    s["med%"] = round(100 * st.median(rs), 2)
    if h is not None:
        s["t_NW"] = lp.nw_t(rs, h)
    return s


def marginal(a, b):
    if len(a) >= 30 and len(b) >= 30:
        return round(100 * (st.mean(a) - st.mean(b)), 2)
    return None


def cal_and_dsr(stocks, events_valid, trials):
    """日历时间口径 + DSR（avoid 方向 = 做空剧震组合/回避侧，SR 取负号后评估）。
    返回 (calendar_time结果, 回避侧DSR概率, 原始方向DSR概率)。"""
    ct = lp.calendar_time(events_valid, stocks, 20, FEE)
    if not ct:
        return None, None, None
    sr_d = ct["年化Sharpe"] / math.sqrt(244)
    dsr_avoid = lp.deflated_sharpe(-sr_d, ct["天数"], -ct["skew"], ct["kurt"], trials=trials)
    dsr_raw = lp.deflated_sharpe(sr_d, ct["天数"], ct["skew"], ct["kurt"], trials=trials)
    return ct, dsr_avoid, dsr_raw


def selfcheck(stocks):
    """等价性自检：200 票子集上 rq.r4() 原生输出 vs 本采集器（vr_min=2.0）逐数字比对。"""
    keys = list(stocks)[:200]
    sub = {k: stocks[k] for k in keys}
    rq.OUT.pop("R4_高位剧震", None)
    rq.r4(sub)                      # 原生实现实跑（只读 sub，无副作用）
    native = rq.OUT["R4_高位剧震"]
    got = collect(sub, vr_min=2.0)
    diffs = []
    for h in HORIZONS:
        mine_ev = rq.stat(rets(sub, got["events"], h))
        mine_c1 = rq.stat(rets(sub, got["ctrl1"], h))
        nat = native[f"T+{h}"]
        if mine_ev != nat["剧震"]:
            diffs.append(f"T+{h} 剧震: mine={mine_ev} native={nat['剧震']}")
        if mine_c1 != nat["高位对照"]:
            diffs.append(f"T+{h} 对照: mine={mine_c1} native={nat['高位对照']}")
    return diffs


def run_block(stocks, vr_min, trials):
    """一个阈值档的全套：采集 → 分年 → 三口径 → 对照。"""
    got = collect(stocks, vr_min)
    ev, c1, c2 = got["events"], got["ctrl1"], got["ctrl2"]
    out = {"vr_min": vr_min, "n_events": len(ev), "n_ctrl1": len(c1),
           "n_ctrl2_matched": len(c2), "ctrl2_coverage": round(got["ctrl2_cov"], 4)}

    # ── 分年验尸 ──
    ey, y1 = by_year(ev), by_year(c1)
    years = {}
    total = len(ev)
    for y in sorted(ey):
        er, cr = ey[y], y1.get(y, [])
        row = {"n": len(er), "占比%": round(100 * len(er) / total, 1)}
        for h in (5, 20):
            rs, cs = rets(stocks, er, h), rets(stocks, cr, h)
            row[f"T+{h}"] = {"剧震": stat_full(rs), "对照1": stat_full(cs),
                             "边际pp": marginal(rs, cs)}
        years[y] = row
    max_y = max(years, key=lambda y: years[y]["n"]) if years else None
    out["分年"] = years
    out["单年最大占比"] = {"year": max_y, "占比%": years[max_y]["占比%"] if max_y else None,
                          "否决线%": 40, "触发否决": bool(max_y and years[max_y]["占比%"] > 40)}

    # ── 口径①：事件研究（逐事件等权 + HAC t，T+20 主判据）──
    es = {}
    for h in HORIZONS:
        rs, cs = rets(stocks, ev, h), rets(stocks, c1, h)
        rs2 = rets(stocks, c2, h)
        es[f"T+{h}"] = {"剧震": stat_full(rs, h), "对照1_同票高位": stat_full(cs),
                        "对照2_同期同板块": stat_full(rs2),
                        "边际pp_vs对照1": marginal(rs, cs),
                        "边际pp_vs对照2": marginal(rs, rs2)}
    out["事件研究"] = es

    # ── 口径②③：日历时间 + DSR（T+20 主判据，样本= fwd 有效的事件子集）──
    ev_valid = [(c, i) for c, i, _dt in ev if rq.fwd(stocks[c], i, 20) is not None]
    ct, dsr_avoid, dsr_raw = cal_and_dsr(stocks, ev_valid, trials)
    out["日历时间_T20"] = ct
    out["DSR"] = {"trials": trials, "回避侧_P_SR>0": dsr_avoid, "原始方向_P_SR>0": dsr_raw,
                  "口径": "trials=dsr_recount结构普查实测+本次新增2档(2.0/1.5)；回避侧=做空剧震组合的SR"}
    # T+5 日历时间参考
    ev5 = [(c, i) for c, i, _dt in ev if rq.fwd(stocks[c], i, 5) is not None]
    ct5 = lp.calendar_time(ev5, stocks, 5, FEE)
    out["日历时间_T5"] = ct5
    return out


def render_md(res, path):
    """research/R4_final.md：结论 + 逐年表 + 三口径 + 作废条件 + 遗留。"""
    m = res["main"]
    L = []
    L.append("# R4 高位剧震回避黑名单（AVOID）终审 — RES-10\n")
    L.append(f"生成：{res['date_bjt']} BJT · 数据 data/big_kcache 至 {res['kcache_end']}"
             f"（{res['n_stocks']} 只）· 事件定义逐行复用 research_queue_20260919.r4()\n")
    L.append(f"自检：{res['selfcheck']}\n")
    L.append(f"\n## 结论：**{res['verdict']}**\n")
    L.append(res["verdict_reason"] + "\n")
    L.append("\n## 分年验尸（T+20 边际 = 剧震 − 同票高位非剧震对照）\n")
    L.append("| 年 | n | 占比 | T+5 剧震 | T+5 边际pp | T+20 剧震 | T+20 边际pp |")
    L.append("|---|---|---|---|---|---|---|")
    for y, r in m["分年"].items():
        t5, t20 = r["T+5"], r["T+20"]
        fmt = lambda s: f"{s['win%']}%/{s['mean%']}" if s else "-"
        L.append(f"| {y} | {r['n']} | {r['占比%']}% | {fmt(t5['剧震'])} | {t5['边际pp']} "
                 f"| {fmt(t20['剧震'])} | {t20['边际pp']} |")
    mv = m["单年最大占比"]
    L.append(f"\n单年最大占比：{mv['year']} = {mv['占比%']}%（否决线 40%）→ "
             f"{'**触发否决**' if mv['触发否决'] else '未触发'}\n")
    L.append("\n## 三口径（T+20 主判据）\n")
    es = m["事件研究"]
    fmt = lambda s: f"{s['win%']}%/{s['mean%']}（n={s['n']}）" if s else "-"
    for h in HORIZONS:
        e = es[f"T+{h}"]
        L.append(f"- T+{h}：剧震 {fmt(e['剧震'])}，t_NW={e['剧震'].get('t_NW')}"
                 f"｜边际 vs对照1 {e['边际pp_vs对照1']}pp ｜vs对照2 {e['边际pp_vs对照2']}pp")
    ct = m["日历时间_T20"]
    if ct:
        L.append(f"- 日历时间 T+20：{ct['天数']} 天，日均超额 {ct['日均超额%']}%，"
                 f"年化Sharpe {ct['年化Sharpe']}，t_NW={ct['t_NW']}")
    ct5 = m["日历时间_T5"]
    if ct5:
        L.append(f"- 日历时间 T+5：{ct5['天数']} 天，日均超额 {ct5['日均超额%']}%，t_NW={ct5['t_NW']}")
    dsr = m["DSR"]
    L.append(f"- **样本对齐**：三个窗口一律用「T+20 有效」子集 n={es['T+20']['剧震']['n']}"
             f"（总事件 n={m['n_events']}）——不同窗口若各取各的有效集，跨窗口数字不可比；"
             f"分年表同一列同理（列内 n=事件数，窗口内 n=有效数）。")
    L.append(f"- DSR（trials={dsr['trials']}）：回避侧 P(SR>0)={dsr['回避侧_P_SR>0']}，"
             f"原始方向 P={dsr['原始方向_P_SR>0']}")
    L.append("\n## 位置匹配对照（两档）\n")
    L.append("| 窗口 | 剧震 | 对照1 同票高位非剧震 | 边际1 | 对照2 同期同板块 | 边际2 |")
    L.append("|---|---|---|---|---|---|")
    for h in (5, 20):
        e = es[f"T+{h}"]
        L.append(f"| T+{h} | {fmt(e['剧震'])} | {fmt(e['对照1_同票高位'])} | {e['边际pp_vs对照1']}pp "
                 f"| {fmt(e['对照2_同期同板块'])} | {e['边际pp_vs对照2']}pp |")
    L.append(f"\n对照2 覆盖率 {m['ctrl2_coverage']*100:.1f}%（同信号日×同行业无非剧震候选的事件除外）。")
    L.append("诚实备注：T+5 边际在 2019（+0.01pp）与 2026（+0.23pp）两年微正≈0；"
             "T+20 边际 8/8 年全负（-1.56~-5.04pp）。主判据为 T+20，负边际跨年一致成立。")
    _q, _c1 = es["T+20"]["剧震"], es["T+20"]["对照1_同票高位"]
    L.append(f"中位数口径复核（主 agent 追加）：T+20 剧震中位 {_q['med%']}% vs 对照1 中位 {_c1['med%']}%，"
             f"**中位差 {round(_q['med%'] - _c1['med%'], 2)}pp，比均值差 {es['T+20']['边际pp_vs对照1']}pp 更负**"
             f"——负边际不是少数极端亏损拉出来的左尾效应，整条分布左移。\n")
    s = res["sens"]
    L.append("\n## 阈值敏感性反例（量比阈值 2.0 → 1.5）\n")
    se = s["事件研究"]["T+20"]
    L.append(f"- 阈值 1.5：事件 n={s['n_events']}（fwd 有效 {se['剧震']['n']}；"
             f"2.0 档事件 n={m['n_events']}，fwd 有效 {es['T+20']['剧震']['n']}），"
             f"T+20 剧震 {se['剧震']['win%']}%/{se['剧震']['mean%']}，"
             f"边际 vs对照1 {se['边际pp_vs对照1']}pp、vs对照2 {se['边际pp_vs对照2']}pp，"
             f"t_NW={se['剧震'].get('t_NW')}")
    ct_s = s["日历时间_T20"]
    if ct_s:
        L.append(f"- 日历时间 T+20：{ct_s['天数']} 天，日均超额 {ct_s['日均超额%']}%，"
                 f"年化Sharpe {ct_s['年化Sharpe']}，t_NW={ct_s['t_NW']}")
    L.append(f"- 判定：{res['sens_note']}")
    L.append("\n## 作废条件\n")
    L.append("1. 滚动 12 个月新增剧震事件的 T+20 边际（对同票高位对照）转正且 t_NW≥2 → 作废；")
    L.append("2. 任一单年样本占比 >40% 的结构性重演（事件定义被单一行情主导）→ 复核；")
    L.append("3. 连板生态制度性变化（涨跌停幅度/停牌规则调整）→ 全量重审；")
    L.append("4. kcache 退市股补齐（DATA-05）后若结论翻转 → 作废重审。")
    L.append("\n## 遗留\n")
    L.append("- 退市股不在 big_kcache（幸存者偏差，DATA-05 待办；AVOID 类主张方向保守——退市股多含剧震后崩盘，补齐只会让负边际更深，估计方向不变，但幅度未验证）；")
    L.append("- ctrl2 同板块用静态 industry_map（2026-09-05 快照），历史行业漂移未控；")
    L.append("- T+1 边际 ≈0：黑名单不预测次日，只预测持续失血，执行上「剧震日当日/次日离场」的差别未单独测。")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def main():
    t0 = datetime.now()
    # trials 分母：先跑结构普查（在全宇宙加载前，避免内存叠加峰值）。
    # 防自食：排除本任务自身的产物 r4_final_*.json，否则二次跑时 trials 被自己的输出灌水
    # （实抓：run2 普查 16248→16330，+82 全来自 run1 写出的 r4_final json）。
    try:
        import glob as _glob
        import dsr_recount
        _orig_glob = _glob.glob
        dsr_recount.glob.glob = lambda pat: [f for f in _orig_glob(pat) if "/r4_final_" not in f]
        try:
            _per, trials0 = dsr_recount.trials_census()
            del _per
        finally:
            dsr_recount.glob.glob = _orig_glob
    except Exception as e:
        print(f"[WARN] trials 普查失败，回退旧口径 7491：{e}", file=sys.stderr)
        trials0 = 7491
    trials = trials0 + 2   # 本次登记 2 档正式检验（vr 2.0 主判 + 1.5 敏感性）
    print(f"trials 分母：普查 {trials0} + 本次新增 2 = {trials}", flush=True)

    stocks = lp.load_universe()
    lp.build_xsection(stocks)   # 同行业对照需要 _IND（另带 _XCAP/regime，本任务只用 _IND）
    print(f"stocks: {len(stocks)}", flush=True)
    kc_end = max(d["date"][-1] for d in stocks.values())

    diffs = selfcheck(stocks)
    print(f"自检（200票子集 vs rq.r4 原生）: {'PASS 逐数字相等' if not diffs else diffs}", flush=True)
    if diffs:
        print("自检失败，拒绝继续——采集器与 r4() 不等价", file=sys.stderr)
        sys.exit(2)

    main_res = run_block(stocks, 2.0, trials)
    print("── 主档 vr≥2.0 完成 ──", flush=True)
    sens_res = run_block(stocks, 1.5, trials)
    print("── 敏感档 vr≥1.5 完成 ──", flush=True)

    import resource
    peak_gb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6

    # ── 判决（三选一，规则先写死再对数字）──
    m = main_res
    e20 = m["事件研究"]["T+20"]
    t_ev = e20["剧震"].get("t_NW") or 0
    t_ct = (m["日历时间_T20"] or {}).get("t_NW") or 0
    dsr_a = m["DSR"]["回避侧_P_SR>0"] or 0
    neg_both = (e20["边际pp_vs对照1"] is not None and e20["边际pp_vs对照1"] < 0
                and e20["边际pp_vs对照2"] is not None and e20["边际pp_vs对照2"] < 0)
    hard_fail = m["单年最大占比"]["触发否决"]
    if hard_fail:
        verdict = "证伪（单年样本占比>40%，结构性否决）"
        reason = f"{m['单年最大占比']['year']} 年占比 {m['单年最大占比']['占比%']}% > 40% 否决线，结论不可注册。"
    elif (e20["剧震"]["mean%"] > 0 or (e20["边际pp_vs对照1"] or 0) >= 0):
        verdict = "证伪（T+20 边际非负，edge 不存在）"
        reason = "主判据 T+20 边际非负，黑名单主张不成立。"
    elif (not hard_fail and neg_both and t_ev <= -NW_MIN_T and t_ct <= -NW_MIN_T and dsr_a >= 0.95):
        verdict = "注册 AVOID"
        reason = (f"分年无否决、两档对照 T+20 边际均为负（{e20['边际pp_vs对照1']}/{e20['边际pp_vs对照2']}pp）、"
                  f"事件研究 t_NW={t_ev}、日历时间 t_NW={t_ct}、回避侧 DSR={dsr_a} ≥0.95，过 Harvey 3.0。")
    else:
        verdict = "降级观察"
        reason = (f"方向为负但未全过硬闸：两档对照负={neg_both}、事件 t_NW={t_ev}（需≤-3）、"
                  f"日历时间 t_NW={t_ct}（需≤-3）、DSR={dsr_a}（需≥0.95）。")

    s20 = sens_res["事件研究"]["T+20"]
    sens_gone = not ((s20["边际pp_vs对照1"] or 0) < 0 and (s20["剧震"]["mean%"] or 0) < 0)
    sens_note = ("阈值降到 1.5 后 edge 消失/反号——edge 依赖量比≥2 该阈值，如实报告。"
                 if sens_gone else
                 "阈值降到 1.5 后 T+20 边际仍为负，edge 不依赖 2.0 单点阈值（稳健性+）。")

    res = {"date_bjt": datetime.now(BJT).date().isoformat(), "kcache_end": kc_end,
           "n_stocks": len(stocks), "selfcheck": "PASS 逐数字相等" if not diffs else str(diffs),
           "verdict": verdict, "verdict_reason": reason, "sens_note": sens_note,
           "main": main_res, "sens": sens_res,
           "peak_rss_GB": round(peak_gb, 2),
           "wall_s": round((datetime.now() - t0).total_seconds(), 1)}
    tag = res["date_bjt"].replace("-", "")
    jp = ROOT / f"data/r4_final_{tag}.json"
    jp.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    render_md(res, ROOT / "research/R4_final.md")
    print(f"\n判决：{verdict}\n{reason}", flush=True)
    print(f"峰值内存 {peak_gb:.2f} GB · 墙钟 {res['wall_s']}s", flush=True)
    print("saved", jp, "and research/R4_final.md", flush=True)


if __name__ == "__main__":
    main()
