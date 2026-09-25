#!/usr/bin/env python3
"""engine/ops_briefing.py — 盘前作战单（2026-09-14 立，当夜 v2 修两宗罪）

每交易日 9:25 BJT 由 cron 调起，stdout 原样推送 QQ。

v2 修正（2026-09-14 用户二连抓包）：
1. 日期歧义——全单禁用裸"今天/明天/昨天"，一律写绝对日期+星期；
   头部写明「数据截至 X 收盘 · 执行日 Y」。
2. 影子/真实不分——系统不知道用户真实成交，"没买却喊卖"摧毁信任。
   作战单拆两个账本：
   【真实持仓】= config/watchlist.json（用户亲口维护的票）
   【信号影子单】= 系统按"信号已执行"记账，一律加"若你跟了"前提，没跟=忽略。
"""
import json, os, sys, datetime

ROOT = "/opt/data/fenjue"
D = ROOT + "/data"
LEDGER = D + "/ops_briefing_ledger.jsonl"
sys.path.insert(0, ROOT + "/engine")

BJT = datetime.timezone(datetime.timedelta(hours=8))
today = datetime.datetime.now(BJT).date()
if os.environ.get("OPS_DATE"):  # 测试用：伪造执行日
    today = datetime.date.fromisoformat(os.environ["OPS_DATE"])
WD = "一二三四五六日"


def fmt(d):
    return f"{d.month}/{d.day}(周{WD[d.weekday()]})"


def jload(p, default=None):
    try:
        return json.loads(open(p, encoding="utf-8").read())
    except Exception:
        return default


def main():
    st = jload(ROOT + "/docs/ops-state.json", {})
    reg = st.get("regime") or {}
    regime = reg.get("regime", "?")
    lu, ld = reg.get("limit_ups", "?"), reg.get("limit_downs", "?")

    # 深档低位买入名单（与面板同函数，v2 口径：簇门=深档件(-25%)≥5，出手票=深跌件(≤-35%)）；deep_lastd=信号日（最近交易日）
    deep_lastd, deep_list, deep_cluster = "?", [], 0
    try:
        from dashboard_build import deep_low_scan
        deep_lastd, deep_list, deep_cluster = deep_low_scan()
    except Exception:
        pass
    sig_date = datetime.date.fromisoformat(deep_lastd) if deep_lastd != "?" else None

    # 季节档
    boost = ""
    try:
        sm = jload(D + "/seasonal_modulation.json", {})
        mm = f"{today.month:02d}"
        mult = (((sm.get("rules") or {}).get("LIMITDOWN_NEXT_DAY") or {}).get("boost_months") or {}).get(mm, 1.0)
        if mult != 1.0:
            boost = f" · {today.month}月跌停接档×{mult}"
    except Exception:
        pass

    # B5 信号影子（仅最近交易日有效，隔日自动过期）
    b5_open, b5_am = [], []
    b5_date = ""
    blines = [json.loads(l) for l in open(D + "/banlu_signals.jsonl", encoding="utf-8") if l.strip()] \
        if os.path.exists(D + "/banlu_signals.jsonl") else []
    if blines:
        b5_date = blines[-1]["date"]
        if b5_date == deep_lastd:
            for b in blines:
                if b["date"] != b5_date:
                    continue
                (b5_am if b.get("sealed") else b5_open).append(f'{b["name"]} {b["code"]}')

    # 影子 T+1：上一张作战单的买入名单 → 今天尾盘卖
    ledger = []
    if os.path.exists(LEDGER):
        ledger = [json.loads(l) for l in open(LEDGER, encoding="utf-8") if l.strip()]
    t1 = ledger[-1] if ledger else None

    # 真实持仓
    pos = (jload(ROOT + "/config/watchlist.json", {}).get("positions")) or []

    # 观察池临启动
    focus = [f for f in (st.get("focus") or []) if "观察池" in f.get("src", "")]
    pool_names = "、".join(f["target"].split("(")[0] for f in focus[:6])

    # ══ 输出 ══
    L = []
    L.append(f'📋 作战单 · 执行日 {fmt(today)}')
    L.append(f'数据截至 {fmt(sig_date) if sig_date else "?"}收盘 · {regime} · 涨停{lu}/跌停{ld}{boost}')
    L.append("")

    L.append("🏦 你的真实持仓（watchlist 账本）")
    if pos:
        for p in pos[:4]:
            lv = " / ".join(f'{k}{v}' for k, v in list((p.get("levels") or {}).items())[:3])
            L.append(f'· {p["name"]} {p["code"]}：{lv}')
        L.append('越线雷达会在 9:45/10:30/13:35/14:45 ⚠️ 喊你')
    else:
        L.append('（空）')
    L.append("")

    L.append("👻 信号影子单（系统假设你跟了信号；没跟=忽略，别硬卖）")
    n = 0
    if t1 and t1.get("buys"):
        n += 1
        L.append(f'{n}. 若你 {fmt(datetime.date.fromisoformat(t1["date"]))} 跟买了 '
                 f'{"、".join(t1["buys"])} → {fmt(today)} 尾盘卖（T+1 到点必卖）')
    if b5_am:
        n += 1
        L.append(f'{n}. 若你 {fmt(datetime.date.fromisoformat(b5_date))} 跟买了封板票 '
                 f'{"、".join(b5_am)} → {fmt(today)} 早盘兑现（+2.11%/65.2%）')
    if b5_open:
        n += 1
        L.append(f'{n}. 若你 {fmt(datetime.date.fromisoformat(b5_date))} 跟买了未封板票 '
                 f'{"、".join(b5_open)} → {fmt(today)} 9:30 开盘即走（断板即跑）')
    if n == 0:
        L.append('影子单今天没有待处理的卖出。')
    L.append("")

    L.append("🟢 今日新信号（9:32 竞价确认后才算数）")
    if sig_date:
        sell_d = today  # T+1 尾盘 = 下一个交易日尾盘；交易日历无分钟级需求，按下个交易日近似
        picks = "、".join(f'{nm} {c}({p:+.1f}%)' for c, p, nm in deep_list[:5])
        # 2026-09-22 v2 口径（解剖台双段铁证 #152）：簇门=深档件(收≤MA60×0.75)≥5，
        # 出手票=其中深跌件(收≤MA60×0.65)；裸底座主张已 DEAD，本口径=锐化后存活子集，不再挂底座状态。
        if deep_cluster >= 5 and deep_list:
            L.append(f'1. 深档低位·深跌件（{fmt(sig_date)} 跌停+深度≤-35% · 深档簇{deep_cluster}只 · '
                     f'出手件 T+10 61%/+8.65% · 19-22 +1.77%/23-26 +11.33% 双段正 · 最差批-26%优于旧T+5）：{picks}')
            L.append(f'   {fmt(today)} 9:32 竞价非一字跌停 → 开盘买（深度最深优先，最多5只分散）。'
                     f'出场：T+10 尾盘（2026-09-25 起，深档修复需 5-10 天，T+5 常割在修复中途）；一字跌停=作废')
            L.append('   持仓中强度分档（8年实测）：次日收 ≥+3% → T+5 期望 +11~15%/正收益 88% 拿满；'
                     '次日平淡±3% → +5.2%；【次日跌 ≥3% → 只剩 +1.5% → 提前离场】')
        elif deep_cluster >= 5:
            L.append(f'1. 深档低位：{fmt(sig_date)} 深档簇{deep_cluster}只≥5 但无一只深度≤-35% → 不出手'
                     f'（-35~-25% 浅带近段已死 51%/+0.30%，宁可错过）')
        elif deep_cluster > 0:
            L.append(f'1. 深档低位：{fmt(sig_date)} 深档件仅 {deep_cluster} 只（零星日<5）→ 不出手'
                     f'（零星日 T+5 41.8%/-1.26% 有毒）')
        else:
            L.append(f'1. 深档低位：{deep_lastd} 无合格标的')
    # 妖股摇篮（DEMON_CRADLE_CLUSTER）：只在成簇日说话（年 1-3 次）
    try:
        from dashboard_build import cradle_scan
        cr_d, cr_list, cr_cluster = cradle_scan()
    except Exception:
        cr_d, cr_list, cr_cluster = None, [], False
    if cr_cluster and cr_d == deep_lastd:
        picks = "、".join(f'{nm} {c}({p:+.1f}%)' for c, p, nm in cr_list[:6])
        L.append(f'1b. 🔥妖股摇篮·踩踏修复首板潮（{fmt(cr_d)} 全市场 {len(cr_list)} 只成簇）：{picks}'
                 f'{"…" if len(cr_list) > 6 else ""}')
        L.append(f'   {fmt(today)} 9:30 开盘买（分散 3-5 只，别单挑）；8 年口径 T+5 73.8%/+7.74、T+20 82.5%/+14.67，'
                 f'但 6 成收益来自 2024-02 一个月——这是结构性机会不是日常策略；孤板日（<3 只）绝不出手。')
    if pool_names:
        L.append(f'2. 观察池临启动（触发制，不用盯）：{pool_names} 等')
        L.append('   只观察不挂单（G7容量死刑+当周8触发7亏实锤）：「它涨停+板块≥3只涨停」时雷达会报，但不排队')
    # ⚔️ X规则线（xrules_daily 19:15 判定落盘，全保真口径）：T1-MEGA/X2/X3 状态一览
    try:
        _xs = json.loads(open(D + "/xrules_state.json").read())
        if _xs.get("date") == deep_lastd:
            L.append(f'3. ⚔️X规则线（{_xs["date"]} {_xs["regime"]} · 跌停{_xs["ldc"]} · 缺口低簇{_xs["gap_cluster"]} · 恐慌streak{_xs["streak"]}）：')
            for _rule, _label in (("T1-MEGA", "T1-MEGA巨簇分散"), ("X3", "X3恐慌狙击")):
                _r = _xs.get("rules", {}).get(_rule, {})
                if _r.get("fired"):
                    _pk = "、".join(f'{p["name"]}{p["code"]}' for p in _r.get("picks", [])[:5])
                    L.append(f'   🔥{_label}触发 → {_pk}{"…" if len(_r.get("picks", [])) > 5 else ""}')
                    L.append(f'      买：{_xs["entry_day"]}开盘；卖：{"T+3收盘" if _rule == "T1-MEGA" else "T+5收盘或-12%止损"}')
                    if _r.get("vr_dropped"):
                        L.append(f'      （已剔量比<1 票 {_r["vr_dropped"]} 只）')
                else:
                    L.append(f'   · {_label}：未触发（{_r.get("why", "?")}）')
            _sh = _xs.get("shadow") or {}
            if _sh:
                _sl = " · ".join(f'{r} {s["n"]}单{s["win%"]:.0f}%胜/{s["mean%"]:+.1f}%（在途{s.get("open", 0)}）'
                                 for r, s in _sh.items())
                L.append(f'   📒影子对账：{_sl}（巨簇日逐批中位仅+0.9%/41%批次亏损，单批胜负方差大，看累计别看单批）')
    except FileNotFoundError:
        pass
    L.append("")
    L.append("⏰ 买只在 9:32-9:45 · 卖只在尾盘/点名的早盘 · 其余时间不操作")
    L.append("📖 规则+证据 → tebio.github.io/fenjue")

    # 台账：记今日买入名单（影子），供下一交易日 T+1 提醒；同日幂等
    entry = {"date": str(today),
             "buys": [f'{nm} {c}' for c, p, nm in deep_list[:5]]}
    ledger = [e for e in ledger if e.get("date") != str(today)]
    ledger.append(entry)
    with open(LEDGER, "w", encoding="utf-8") as f:
        for e in ledger[-40:]:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    print("\n".join(L))


if __name__ == "__main__":
    main()
