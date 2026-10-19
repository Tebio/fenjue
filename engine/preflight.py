#!/usr/bin/env python3
"""engine/preflight.py — 下单前体检 CLI（第四波「全面升级」集成卡 t_fdbe6e13；第五波加 --from-state，#295）

一条命令回答「这票现在能不能买」：python3 engine/preflight.py 601398

七段一页（全部只读既有产物拼合，不发明新信号、不改任何生产代码/数据）：
  ① regime 闸门      env_state.env_state()（唯一环境源）+ regime_timeline_hcap 最新态 + regime_age 段龄
  ② 命中存活线       ops-state(deep_low/b5) / reversal_confirmed / watch_pool / pead_pool_state /
                     gold_current → 逐条映射 data/line_health.json 健康分（危重/走弱/ICU 直接红字）
  ③ KNN 相似样本投票 复用 similarity_daily._grid_score/_features_at（GridCF-D 同款引擎，单票即时算，
                     学习集=信号日前全部股票日 PIT）；历史分位 ≤0.20 → 「别碰」（#276/#279 排除层实证）
  ④ 黑名单           近 5 交易日 HiThink 龙虎榜玉兰路席位出货名单（#275：上榜=局部顶，玉兰路最强）+
                     名称含 ST/退（退市整理期）
  ⑤ 簇状态           xrules_state（ldc/gap_cluster/panic_cluster vs 簇门）+ ops-state 深档簇计数
  ⑥ 位置带           console_banks / console_dividend_sectors / console_sectors（命中才显示）
  ⑦ 总结论           🟢/🟡/🔴 + 一句理由

【--from-state（#295 日态包优先读）】用法：`preflight.py <code> --from-state [路径]`
  ① ② ⑤ + 持仓哨兵 四段改从权威日态包 data/daily_state/<date>.json 取数，**渲染与直连版共用同一份
  打印逻辑**（只换取值来源，不改任何判据/文案）；包缺、包日期落后最新交易日、或包内 unknown 时
  自动回落直连并在输出里明标，绝不拿陈包当今日用。
  ③ KNN（单票即时打分）④ 黑名单 ⑥ 位置带 仍直连——理由见 docs/daily_state-schema.md §5。

裁决规则（写死，不猜）：
  🔴 = ST/退市整理期 | 玉兰路近 5 日命中 | KNN 分位≤0.20 | 命中线 grade∈{critical,weak} 或 status∈{ICU,DECAYING}
  🟢 = 今日 ≥1 条 healthy 存活线命中 且无任何红线 且关键段无 unknown/stale
  🟡 = 其余（含：无命中=无信号不主动买；任一关键段 unknown/过期 → 最高只给 🟡）

纪律：每段带新鲜度戳（产品日期 vs 最新交易日），过期明写；数据缺失显示 unknown 不猜。
内存：单票级打分 + 学习集四轴列（沿用 similarity_daily 瘦加载口径，不跑 selfcheck、不载 15 维全阵）。
"""
import json
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path("/opt/data/fenjue")
D = ROOT / "data"
BJT = timezone(timedelta(hours=8))

# 触发源 → line_health 线 id（None=无独立条目，按台账状态标注）
LINE_MAP = {
    "deep_low": "LIMITDOWN_LOW_DEEP35",
    "b5": "BANLU_B5",
    "watch_pool": "WATCHPOOL_GRAD",
    "pead_pool": "PEAD_LOW_POOL",
    "gold_solo_fresh": "GOLD_SOLO_FRESH_MONTHLY",
    "reversal_confirmed": None,  # 反转族本体 ICU（#281），line_health 无独立条目
}
RED_GRADES = {"critical", "weak"}
RED_STATUS = {"ICU", "DECAYING", "DEAD"}
KNN_BOTTOM_Q = 0.20  # #276/#279：bottom 20% = 别碰排除层
BLACKLIST_SEAT = "玉兰路"
LHB_LOOKBACK_DAYS = 5


def _jload(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def _mtime(p):
    try:
        return datetime.fromtimestamp(Path(p).stat().st_mtime, BJT).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "unknown"


def _fresh_tag(date_str, latest_trading):
    """数据日期 vs 最新交易日 → 新鲜度戳。"""
    if not date_str:
        return "unknown"
    return "✅" if date_str >= latest_trading else f"⚠️过期(截至{date_str})"


# ---------------- ① regime 闸门 ----------------

def sec_regime(latest_trading):
    out = {"lines": [], "fresh": "unknown", "regime": None}
    tl = _jload(D / "regime_timeline_hcap.json")
    age = _jload(D / "regime_age.json")
    if not tl or not age:
        out["lines"].append("regime 时间轴/段龄产物缺失 → unknown")
        return out
    last = tl[-1]  # hcap 轴=dict 列表（AGENTS：勿按 tuple 解包）
    latest_age = age.get("latest")
    cur = age.get("ages", {}).get(latest_age) or age.get("today") or {}
    out["fresh"] = _fresh_tag(last.get("date"), latest_trading)
    out["regime"] = last.get("regime")
    out["lines"].append(
        f"regime={last.get('regime')} 段龄={cur.get('age', '?')} "
        f"(轴 {last.get('date')} {out['fresh']}；涨停{last.get('boards')} 跌停{last.get('downs')})")
    # 环境快照（趋势门/杠杆门/四象限/下阶段概率）走唯一源 env_state
    try:
        sys.path.insert(0, str(ROOT / "engine"))
        import env_state
        es = env_state.env_state(latest_trading)
        out["lines"].append(
            f"趋势门={es.get('trend_gate')} 杠杆门={es.get('margin_gate')} "
            f"四象限={es.get('quadrant') or 'unknown'} 下阶段={es.get('next_top')}({(es.get('next_prob') or 0) * 100:.0f}%)")
    except Exception as e:
        out["lines"].append(f"env_state 读取失败({e}) → 趋势/杠杆门 unknown")
    return out


# ---------------- ② 命中存活线 ----------------

def sec_lines(code, today_bjt, latest_trading):
    """返回 (hits, meta)：hits=[{src,line,grade,status,score,note,actionable}]"""
    hits, meta = [], []
    lh = _jload(D / "line_health.json") or {}
    lh_lines = lh.get("lines", {})
    lh_date = (lh.get("_meta") or {}).get("date")

    def add(src, line_id, note, actionable):
        e = {"src": src, "note": note, "actionable": actionable}
        if line_id and line_id in lh_lines:
            l = lh_lines[line_id]
            e.update(line=line_id, grade=l.get("grade") or "unknown",
                     status=l.get("status"), score=l.get("score"))
        elif line_id:
            e.update(line=line_id, grade="unknown", status="unknown", score=None)
        else:
            e.update(line="反转族_T-1大跌", grade="ICU", status="ICU", score=None)
        hits.append(e)

    # ops-state（深档触发 + B5），行动窗口=buy_day
    ops = _jload(ROOT / "docs/ops-state.json")
    if ops:
        sd, bd = ops.get("sig_date"), ops.get("buy_day")
        meta.append(f"ops-state 信号日{sd} 买入日{bd} {_fresh_tag(sd, latest_trading)}")
        actionable = (bd == today_bjt)
        for r in ops.get("deep_low") or []:
            if str(r.get("code")) == code:
                add("deep_low", LINE_MAP["deep_low"], f"深档低位v2 触发 pct={r.get('pct')}", actionable)
        b5 = ops.get("b5") or {}
        for item in (b5.get("sealed") or []) + (b5.get("unsealed") or []):
            if code in str(item):
                add("b5", LINE_MAP["b5"], f"B5 半路板（{b5.get('date')}）", b5.get("date") == today_bjt)
    else:
        meta.append("ops-state.json 缺失")

    # reversal_confirmed（今日竞价确认名单）
    rev = _jload(D / "reversal_confirmed.json")
    if rev:
        rd = rev.get("date")
        meta.append(f"reversal_confirmed {rd} n={len(rev.get('executable') or [])} "
                    f"{'✅今日' if rd == today_bjt else _fresh_tag(rd, latest_trading)}")
        for r in rev.get("executable") or []:
            if str(r.get("code")) == code:
                add("reversal_confirmed", None,
                    f"反转族确认 收{r.get('close_chg')}% 开{r.get('open_chg')}% 梯队{r.get('ladder')}",
                    rd == today_bjt)

    # watch_pool（状态制）
    wp = _jload(D / "watch_pool.json")
    if wp:
        meta.append(f"watch_pool mtime={_mtime(D / 'watch_pool.json')}")
        for r in wp.get("pool") or []:
            if str(r.get("code")) == code:
                add("watch_pool", LINE_MAP["watch_pool"],
                    f"观察池 {r.get('status')} 入池{r.get('entry_date')} @{r.get('entry_close')}", True)

    # pead_pool_state
    ps = _jload(D / "pead_pool_state.json")
    if ps:
        pd_ = (ps.get("processed_dates") or ["?"])[-1]
        meta.append(f"pead_pool 处理至{pd_} {_fresh_tag(pd_, latest_trading)}")
        for bucket in ("holdings", "pending"):
            for r in ps.get(bucket) or []:
                if str(r.get("code")) == code:
                    add("pead_pool", LINE_MAP["pead_pool"], f"预增低位池 {bucket}", True)

    # gold_current（月度金股 独家+年内首入）
    gold = _jload(D / "gold_current.json")
    if gold:
        meta.append(f"gold_current {gold.get('month')} 入场日{gold.get('entry_day')} "
                    f"solo_fresh={len(gold.get('solo_fresh') or [])}")
        for r in gold.get("solo_fresh") or []:
            if code in str(r):
                add("gold_solo_fresh", LINE_MAP["gold_solo_fresh"], f"金股独家首入 {gold.get('month')}", True)

    meta.append(f"line_health 体检日{lh_date} {_fresh_tag(lh_date, today_bjt)}")
    return hits, meta


# ---------------- ③ KNN 相似样本投票（复用 similarity_daily 同款引擎） ----------------

def sec_knn(code, latest_trading):
    out = {"lines": [], "pct_rank": None, "bottom": None, "fresh": "unknown"}
    try:
        import similarity_daily as sdmod
    except Exception as e:
        out["lines"].append(f"similarity_daily 导入失败({e}) → unknown")
        return out
    npz = D / "similarity_features.npz"
    if not npz.exists():
        out["lines"].append("similarity_features.npz 缺失 → unknown")
        return out
    t0 = time.time()
    z = np.load(npz)
    calendar = z["calendar"].tolist()
    didx = z["didx"]
    if latest_trading not in calendar:
        out["lines"].append(f"特征矩阵日历尾={calendar[-1]} < 最新交易日{latest_trading} → ⚠️过期，unknown")
        return out
    ti = calendar.index(latest_trading)
    li = np.where(didx < ti)[0]  # PIT：信号日前全部股票日
    Fsub = z["F"][:, [0, 2, 6, 8]].copy()  # depth60/ret60/volr5/log_cap 四轴
    R = z["R"].copy()
    fv = sdmod._features_at(code, latest_trading)
    if fv is None:
        out["lines"].append(f"{latest_trading} 无 bar 或历史不足 → unknown")
        return out
    pred_l, _, _ = sdmod._grid_score(Fsub[li], R[li], Fsub[li])
    hist5 = np.sort(pred_l[:, 1])
    pred, level, cell_n = sdmod._grid_score(Fsub[li], R[li], fv.reshape(1, 4))
    rank = float(np.searchsorted(hist5, pred[0, 1]) / len(hist5))
    out.update(pct_rank=rank, bottom=rank <= KNN_BOTTOM_Q,
               fresh=f"✅(学习{len(li):,}行→{latest_trading}, {time.time()-t0:.0f}s)")
    out["lines"].append(
        f"T+1 {pred[0,0]*100:+.2f}% / T+5 {pred[0,1]*100:+.2f}% / T+20 {pred[0,2]*100:+.2f}% "
        f"| 历史分位 {rank:.2f}（别碰线≤{KNN_BOTTOM_Q}）| 邻居 {int(cell_n[0])} 格层级 lv{int(level[0])}")
    if out["bottom"]:
        out["lines"].append("⚠️ 落 bottom 20% —— #276/#279 实证排除层：别碰")
    return out


# ---------------- ④ 黑名单 ----------------

def sec_blacklist(code, name, latest_trading):
    out = {"lines": [], "hit": False, "fresh": "unknown"}
    if any(t in (name or "") for t in ("ST", "退")):
        out["hit"] = True
        out["lines"].append(f"⛔ 名称含 ST/退（{name}）= 风险警示/退市整理期，直接排除")
    dirs = sorted((D / "hithink").glob("2026-*/lhb_hot.json"))[-LHB_LOOKBACK_DAYS:]
    if not dirs:
        out["lines"].append("hithink 龙虎榜日产物缺失 → 席位黑名单 unknown")
        return out
    seat_hits, lhb_days = [], []
    for p in dirs:
        day = p.parent.name
        j = _jload(p) or {}
        for it in (j.get("data") or {}).get("hot_money_items") or []:
            for r in it.get("rows") or []:
                if str(r.get("ticker")) == code:
                    lhb_days.append(f"{day}({it.get('name')})")
                    if BLACKLIST_SEAT in str(it.get("name")):
                        seat_hits.append(day)
    out["fresh"] = f"✅(近{len(dirs)}交易日 {dirs[0].parent.name}~{dirs[-1].parent.name})"
    if seat_hits:
        out["hit"] = True
        out["lines"].append(f"⛔ 玉兰路席位出货名单命中：{', '.join(seat_hits)}（#275：买侧 T20 -9.19pp 最强出货信号）")
    if lhb_days:
        out["lines"].append(f"近5日上过龙虎榜：{', '.join(lhb_days)}（#275：上榜=局部顶，T+20 全桶负漂移，持仓一周内减）")
    if not out["lines"]:
        out["lines"].append("近5日龙虎榜无该票，名称无 ST/退 → 干净")
    return out


# ---------------- ⑤ 簇状态 ----------------

def sec_cluster(latest_trading):
    out = {"lines": [], "fresh": "unknown"}
    xr = _jload(D / "xrules_state.json")
    if xr:
        out["fresh"] = _fresh_tag(xr.get("date"), latest_trading)
        rules = xr.get("rules") or {}
        bits = [f"xrules {xr.get('date')} {out['fresh']}: 跌停簇{xr.get('ldc')} "
                f"缺口簇{xr.get('gap_cluster')} 恐慌簇{xr.get('panic_cluster')}"]
        for rid, r in rules.items():
            if r.get("retired"):
                continue
            if r.get("fired"):
                bits.append(f"  {rid} 已触发")
            else:
                bits.append(f"  {rid} 未触发（{r.get('why')}）")
        out["lines"] = bits
    ops = _jload(ROOT / "docs/ops-state.json")
    if ops:
        n = len(ops.get("deep_low") or [])
        out["lines"].append(f"深档低位v2 当日同线触发 {n} 只 vs 簇门≥5 → {'过门' if n >= 5 else '未过门'}")
    if not out["lines"]:
        out["lines"].append("簇状态产物缺失 → unknown")
    return out


# ---------------- ⑥ 位置带（操作台宇宙命中才显示） ----------------

def sec_zone(code):
    out = {"lines": [], "fresh": "unknown", "hit": False}
    for fp, label in (("console_banks.json", "银行操作台"),
                      ("console_dividend_sectors.json", "红利板块操作台"),
                      ("console_sectors.json", "通用板块操作台")):
        j = _jload(D / fp)
        if not j:
            continue
        rows = []
        if "rows" in j:
            rows = j["rows"]
        else:
            for sect in j.values():
                rows += sect.get("rows") or []
        for r in rows:
            if str(r.get("code")) == code:
                mt = _mtime(D / fp)
                stale = "⚠️过期" if mt[:10] < "2026-10-01" else "✅"
                out["hit"] = True
                out["lines"].append(
                    f"{label}（{mt} {stale}）：{r.get('zone')} / {r.get('action')} "
                    f"现价{r.get('price')} 买{r.get('bands', {}).get('buy')} "
                    f"卖{r.get('bands', {}).get('sell')} 清{r.get('bands', {}).get('clear')}")
    if not out["lines"]:
        out["lines"].append("不在操作台宇宙（银行/红利/通用板块均无此票）→ unknown")
    return out


# ---------------- ⑦ 持仓哨兵（持仓股附加段） ----------------

def sec_holding(code):
    wl = _jload(ROOT / "config/watchlist.json") or {}
    for p in wl.get("positions") or []:
        if str(p.get("code")) == code:
            lv = " / ".join(f"{k}:{v}" for k, v in (p.get("levels") or {}).items())
            return [f"持仓 {p.get('name')}（{_mtime(ROOT / 'config/watchlist.json')}）：{p.get('note')}",
                    f"关键位 {lv}"]
    return []


# ---------------- 结论 ----------------

def verdict(reg, hits, knn, bl, zone):
    red, yellow = [], []
    if bl["hit"]:
        red.append("黑名单命中")
    if knn["bottom"]:
        red.append(f"KNN 分位 {knn['pct_rank']:.2f}≤0.20 别碰层")
    actionable_healthy = []
    for h in hits:
        if h["grade"] in RED_GRADES or h["status"] in RED_STATUS:
            red.append(f"命中线 {h['line']} 状态 {h['status']}/{h['grade']}")
        elif h["actionable"] and h["grade"] == "healthy":
            actionable_healthy.append(h["line"])
    if knn["pct_rank"] is None:
        yellow.append("KNN unknown")
    for lbl, s in (("regime", reg["fresh"]), ("簇状态", None)):
        if s == "unknown":
            yellow.append(f"{lbl} unknown")
    if red:
        return "🔴", "；".join(red[:2])
    if actionable_healthy and not yellow:
        return "🟢", f"命中健康线 {actionable_healthy[0]}，各段无红线"
    if not hits:
        return "🟡", "今日无存活线命中=无信号不主动买" + ("；" + "；".join(yellow) if yellow else "")
    return "🟡", "；".join(yellow) if yellow else "有命中但非全部绿灯"


# ---------------- 主流程 ----------------

def main():
    code = sys.argv[1].strip().zfill(6) if len(sys.argv) > 1 else ""
    if not (code.isdigit() and len(code) == 6):
        print("用法: python3 engine/preflight.py <6位股票代码>")
        sys.exit(1)
    today_bjt = datetime.now(BJT).date().isoformat()
    idx = _jload(D / "index_sh000001.json") or []
    latest_trading = idx[-1]["date"] if idx else today_bjt
    ind = _jload(D / "industry_map.json") or {}
    name = (ind.get(code) or {}).get("name", "?")

    print(f"========== 下单前体检 {code} {name} ==========")
    print(f"体检生成 {datetime.now(BJT):%Y-%m-%d %H:%M} BJT | 最新交易日 {latest_trading} | 只读拼合，不发明新信号")

    reg = sec_regime(latest_trading)
    print(f"\n① regime 闸门 [{reg['fresh']}]")
    for l in reg["lines"]:
        print(f"   {l}")

    hits, meta = sec_lines(code, today_bjt, latest_trading)
    print("\n② 命中存活线")
    if hits:
        for h in hits:
            act = "今日可执行" if h["actionable"] else "非今日窗口"
            flag = "⛔" if (h["grade"] in RED_GRADES or h["status"] in RED_STATUS) else ""
            print(f"   {flag}[{h['src']}] {h['note']} → {h['line']} "
                  f"health={h['status']}/{h['grade']}/score={h['score']}（{act}）")
    else:
        print("   无命中（ops-state/reversal/watch_pool/pead/gold 均无此票）")
    print("   源新鲜度: " + " | ".join(meta))

    knn = sec_knn(code, latest_trading)
    print(f"\n③ KNN 相似样本投票 [{knn['fresh']}]")
    for l in knn["lines"]:
        print(f"   {l}")

    bl = sec_blacklist(code, name, latest_trading)
    print(f"\n④ 黑名单 [{bl['fresh']}]")
    for l in bl["lines"]:
        print(f"   {l}")

    cl = sec_cluster(latest_trading)
    print(f"\n⑤ 簇状态 [{cl['fresh']}]")
    for l in cl["lines"]:
        print(f"   {l}")

    zn = sec_zone(code)
    print("\n⑥ 位置带")
    for l in zn["lines"]:
        print(f"   {l}")

    hold = sec_holding(code)
    if hold:
        print("\n⑦ 持仓哨兵")
        for l in hold:
            print(f"   {l}")

    v, reason = verdict(reg, hits, knn, bl, zn)
    print(f"\n结论: {v} {reason}")
    print("（研究辅助，非买卖指令；unknown=数据缺失不猜）")


if __name__ == "__main__":
    main()
