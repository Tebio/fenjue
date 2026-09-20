#!/usr/bin/env python3
"""engine/dashboard_build.py — 焚诀操作台静态面板构建（2026-09-14 v3 大改版）

v3（用户裁决「好，你上线」）：四 Tab = 今日 / 我的钱 / 研究库 / 证据库。
- 今日页 = KPI 健康条 + 行动单：真实持仓 vs 信号影子两本账分开（没跟的信号不喊卖），
  全部绝对日期+星期（禁用裸"今天/明天"），交易日历取自 index_sh000001.json。
- 研究库 = 测过的东西有个家：策略分工 / 季节月份层(seasonal_modulation.json) /
  攒数据(转债cb_m5·影子盘·妖股四段) / 证伪墓地（防复活）。
- 我的钱 = 持仓哨兵 + 收割席位 + 股息锚/银行委托单。
- 证据库 = 信号明细 + 模拟盘锦标赛（每个玩法写明"当时怎么模拟的"）+ 全部原始表。
stdlib 零依赖；任一数据源缺失降级为「未生成」卡片，不崩。
"""
import json, html, re, datetime
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
D = ROOT / "data"
OUT = ROOT / "docs/index.html"

REV_RULE = ("买点：明日 9:32 竞价确认（剔一字跌停/高开超1/3抢跑）后开盘价买入——延迟入场单调烧钱，开盘即最优；"
            "卖点：T+1 尾盘（大涨未涨停当日尾盘兑现；涨停则拿隔夜、次日早盘卖——离场日开盘卖是全场最差）；"
            "作废：竞价被剔除或 9:40 前打回平盘。")
FRONT_RULE = ("买点：信号日盘中冲板/封板时打板（收盘前未封=不建仓）；"
              "卖点：次日早盘兑现（涨停隔夜 +2.11%/65.2% 实测）；"
              "作废：封板失败、次日低开破昨收、或板块梯队当日散掉（涨停<3只）。")
NORTH_RULE = ("季度慢变量，只当过滤器不当买点：北向增持+持仓浮盈=多拿一档的证据；"
              "北向减持+跌破关键位=减仓证据；单看北向买入=没有 edge（机构漂移已被闸门证伪）。")
FILL_NOTE = (" fill 实测（m60）：9/11 五单 4 只早盘封死尾盘买不进，3/5 盘中有开缝——"
             "影子收益=纸面口径，实战须在封板 bar 排队，fill 率影子期继续定量。")

WD = "一二三四五六日"


def jload(p, default=None):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def esc(s):
    return html.escape(str(s), quote=False)


def fmt_d(iso):
    """'2026-09-15' → '9/15(周二)'"""
    try:
        d = datetime.date.fromisoformat(str(iso)[:10])
        return f"{d.month}/{d.day}(周{WD[d.weekday()]})"
    except Exception:
        return str(iso)


def next_cal_day(cal, after_iso):
    """交易日历中 after_iso 之后的第一个交易日；日历没有未来日期时按工作日估算（跳过周末）。"""
    for d in cal:
        if d > after_iso:
            return d
    try:
        d = datetime.date.fromisoformat(after_iso) + datetime.timedelta(days=1)
        while d.weekday() >= 5:  # 节假日无法预知，只跳周末
            d += datetime.timedelta(days=1)
        return d.isoformat()
    except Exception:
        return after_iso


def fetch_quotes(codes):
    """Sina 批量实时价（盘后=收盘价）。返回 {code: (price, pct)}。代理/直连双通道。"""
    import subprocess
    out = {}
    url = "https://hq.sinajs.cn/list=" + ",".join(("sh" if c.startswith("6") else "sz") + c for c in codes)
    for env in (None, {"PATH": "/usr/bin:/bin"}):
        try:
            r = subprocess.run(["curl", "-sL", "--max-time", "15",
                                "-H", "Referer: https://finance.sina.com.cn/", url],
                               capture_output=True, env=env)
            text = r.stdout.decode("gb18030", errors="ignore")
            import re as _re
            for mcode, payload in _re.findall(r'hq_str_(?:sh|sz)(\\d{6})="([^"]*)"', text):
                parts = payload.split(",")
                if len(parts) > 3 and float(parts[1] or 0) > 0:
                    price, prev = float(parts[3]), float(parts[2])
                    out[mcode] = (price, (price / prev - 1) * 100 if prev > 0 else 0)
        except Exception:
            pass
        if out:
            break
    return out


def badge_regime(r):
    m = {"主线期": ("#0f7b3d", "#e6f4ea"), "妖股期": ("#b45309", "#fef3e2"),
         "恐慌期": ("#c0392b", "#fdecea"), "平淡期": ("#6b6b66", "#f1f1ef")}
    fg, bg = m.get(r, ("#6b6b66", "#f1f1ef"))
    return f'<span class="badge" style="color:{fg};background:{bg}">{esc(r)}</span>'


def card(title, inner, hint="", rule="", collapsed=False, tab="证据库"):
    # hint/rule 是自家文本，允许内嵌 HTML（链接等）；标题仍转义
    h = f'<span class="hint">{hint}</span>' if hint else ""
    r = f'<div class="rule">{rule}</div>' if rule else ""
    if collapsed:
        return (f'<details class="card" data-tab="{tab}"><summary>{esc(title)}{h}</summary>'
                f'<div class="cardbody">{r}{inner}</div></details>')
    return f'<section class="card" data-tab="{tab}"><h2>{esc(title)}{h}</h2>{r}{inner}</section>'


def table(headers, rows):
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>'


def pct(x, plus=True):
    """红涨绿跌（A股口径）。"""
    try:
        x = float(str(x).replace('%', '').replace('+', ''))
    except (TypeError, ValueError):
        return '<span class="muted">—</span>'
    v = round(x, 2)
    cls = "up" if v > 0 else "dn" if v < 0 else "muted"
    sign = "+" if plus and v > 0 else ""
    return f'<span class="{cls}">{sign}{v}%</span>'


BANK_LINE = re.compile(
    r"^(\S+?)\((\d{6})\) ([\d.]+) \(([^)]*)\) 息率([\d.]+)% PB([\d.]+) \| (\S+?) \| "
    r"买≤([\d.]+) 加≤([\d.]+) 卖([\d.]+) 清≥([\d.]+) \| 距买入(\S+?) MA20 ([\d.]+)\(([^)]*)\)(📌贴线)?"
    r"(?:.*?宣告([\d.]+)%→(买入区|持有区|卖出区|清仓区)(⚖️分歧)?)?")
ORDER_LINE = re.compile(
    r"^(\S+?)\s*(?:📌贴线)?\s*\[(\S+?)\]\s*买([\d.]+)/加([\d.]+)/([\d.]+)/5%线([\d.]+)\s*卖([\d.]+)\s*清([\d.]+)")


def parse_bank(text):
    rows, orders = [], []
    for line in text.splitlines():
        line = line.strip()
        m = BANK_LINE.match(line)
        if m:
            (name, code, price, chg, dy, pb, zone, buy, add, sell, clear,
             dist, ma20, mad, pin, dy_decl, zone_decl, dv) = m.groups()
            zcls = "up" if "买入区" in zone else "muted" if "持有区" in zone else "dn"
            decl_cell = ""
            if dy_decl:
                dcls = "dn" if dv else "muted"
                decl_cell = f"<br><span class='{dcls}'>宣告{dy_decl}%→{esc(zone_decl)}{'⚖️' if dv else ''}</span>"
            rows.append([f"{esc(name)}<br><span class='muted'>{code}</span>",
                         f"{price}<br>{pct(chg)}", f"{dy}%{decl_cell}", pb,
                         f'<span class="{zcls}">{esc(zone)}</span>',
                         buy, sell, clear, f'<span class="muted">{esc(dist)}</span>'])
            continue
        m2 = ORDER_LINE.match(line)
        if m2:
            name, op, buy, a1, a2, a3, sell, clear = m2.groups()
            ocls = "up" if op == "加仓" else "dn" if op == "减仓" else "muted"
            orders.append([esc(name), f'<span class="{ocls}">{esc(op)}</span>', buy,
                           f"{a1}/{a2}/{a3}", sell, clear])
    return rows, orders


def cradle_scan():
    """妖股摇篮（2026-09-19 demon_anatomy 产物，DEMON_CRADLE_CLUSTER 主张）：
    首板(60日无板) + 板日缩量<1.5 + 距60日高≤-25% + PIT市值<50亿，全库扫描；
    只在当日全市场同类信号≥3（成簇）时有效（孤板日 T+5 -0.33% 毒）。
    返回 (最近交易日, [(code, pct, name)], 成簇与否)。
    口径与 law_pipeline._demon_cradle 逐行对齐（改这里必须同步改它）。"""
    import glob as _g
    try:
        names = {str(s["code"]).zfill(6): s.get("name", "")
                 for s in json.loads((D / "main_board_codes.json").read_text())["stocks"]}
        caps = {}
        for fp in _g.glob(str(D / "cap_hist" / "*.json")):
            try:
                rows = json.loads(open(fp).read())
                if rows:
                    caps[fp.rsplit("/", 1)[-1][:6]] = rows[-1][2]
            except Exception:
                pass
        idx = json.loads((D / "index_sh000001.json").read_text())
        lastd = idx[-1]["date"]
        ov = {}
        ovf = D / "kcache_today_overlay.json"
        if ovf.exists():
            try:
                ov = json.loads(ovf.read_text())
                if ov and next(iter(ov.values()))["date"] > lastd:
                    lastd = next(iter(ov.values()))["date"]
            except Exception:
                ov = {}
        out = []
        for fp in _g.glob(str(D / "big_kcache" / "*.json")):
            c0 = fp.rsplit("/", 1)[-1].replace(".json", "")
            if c0[:2] not in ("60", "00"):
                continue
            try:
                ks = json.loads(open(fp).read())
                if ov and c0 in ov and (not ks or ov[c0]["date"] > ks[-1]["date"]):
                    b = ov[c0]
                    ks = ks + [{"date": b["date"], "open": b["open"], "high": b["high"],
                                "low": b["low"], "close": b["close"], "volume": b["volume"]}]
                if len(ks) < 62 or ks[-1]["date"] != lastd:
                    continue
                j = len(ks) - 1
                c = [k["close"] for k in ks]
                v = [k["volume"] for k in ks]
                h = [k["high"] for k in ks]
                if c[j - 1] <= 0 or c[j] / c[j - 1] - 1 < 0.098:
                    continue
                if any(c[k - 1] > 0 and c[k] / c[k - 1] - 1 >= 0.098 for k in range(max(1, j - 60), j)):
                    continue                       # 60日内有板=非首板
                base5 = [v[k] for k in range(j - 5, j) if v[k] > 0]
                if not base5 or v[j] <= 0 or v[j] / (sum(base5) / len(base5)) >= 1.5:
                    continue                       # 非缩量板
                hi60 = max(h[j - 60:j])
                if hi60 <= 0 or c[j - 1] / hi60 - 1 > -0.25:
                    continue                       # 非深跌位
                cap = caps.get(c0)
                if cap is None or cap >= 50:
                    continue
                nm0 = names.get(c0, "")
                if "ST" in nm0 or "退" in nm0:
                    continue
                out.append((c0, round((c[j] / c[j - 1] - 1) * 100, 1), nm0))
            except Exception:
                continue
        return lastd, out, len(out) >= 3
    except Exception:
        return None, [], False


def deep_low_scan():
    """深档低位（≤-9.5% 且 MA60下）全库扫描。返回 (最近交易日, [(code, pct), ...])。"""
    import glob as _g
    try:
        names = {str(s["code"]).zfill(6): s.get("name", "")
                 for s in json.loads((D / "main_board_codes.json").read_text())["stocks"]}
        idx = json.loads((D / "index_sh000001.json").read_text())  # 仅用日期；000001.json=平安银行(撞代码)
        lastd = idx[-1]["date"]
        ov = {}
        ovf = D / "kcache_today_overlay.json"
        if ovf.exists():
            try:
                ov = json.loads(ovf.read_text())
                if ov and next(iter(ov.values()))["date"] > lastd:
                    lastd = next(iter(ov.values()))["date"]
            except Exception:
                ov = {}
        out = []
        for fp in _g.glob(str(D / "big_kcache" / "*.json")):
            c0 = fp.rsplit("/", 1)[-1].replace(".json", "")
            if c0[:2] not in ("60", "00"):
                continue
            try:
                ks = json.loads(open(fp).read())
                if ov and c0 in ov and (not ks or ov[c0]["date"] > ks[-1]["date"]):
                    b = ov[c0]
                    ks = ks + [{"date": b["date"], "open": b["open"], "high": b["high"],
                                "low": b["low"], "close": b["close"], "volume": b["volume"]}]
                if len(ks) < 61 or ks[-1]["date"] != lastd:
                    continue
                p0 = (ks[-1]["close"] / ks[-2]["close"] - 1) * 100
                if p0 <= -9.5:
                    ma = sum(k["close"] for k in ks[-60:]) / 60
                    if ks[-1]["close"] < ma:
                        nm0 = names.get(c0, "")
                        if "ST" in nm0 or "退" in nm0:
                            continue     # 2026-09-18：风险警示/退市整理期剔除（*ST英飞实测 -10% 可达但不可做）
                        out.append((c0, p0, nm0))
            except Exception:
                continue
        return lastd, sorted(out, key=lambda x: x[1])
    except Exception:
        return "?", []


def kpi(name, pill, pill_cls, big, small, line):
    return (f'<div class="kpi"><div class="kpi-head"><span class="kpi-name">{name}</span>'
            f'<span class="pill {pill_cls}">{pill}</span></div>'
            f'<div class="kpi-big">{big} <small>{small}</small></div>'
            f'<div class="kpi-line">{line}</div></div>')


def callout(cls, icon, inner):
    return f'<div class="callout {cls}"><span class="ic">{icon}</span><div>{inner}</div></div>'


def step(no, bg, fg, title, desc):
    return (f'<div class="step"><div class="no" style="background:{bg};color:{fg}">{no}</div>'
            f'<div><div class="t">{title}</div><div class="d">{desc}</div></div></div>')


def main():
    today = datetime.date.today().isoformat()
    S = {"今日": [], "我的钱": [], "研究库": [], "证据库": []}

    # ══ 数据装载（全部只读）══
    _deep_lastd, _deep = deep_low_scan()
    wp = jload(D / "watch_pool.json", {})
    rev = jload(D / "reversal_list.json", {})
    reg = None
    rl = D / "regime_log.jsonl"
    if rl.exists():
        lines = rl.read_text().strip().splitlines()
        if lines:
            reg = json.loads(lines[-1])
    cal = [k["date"] for k in jload(D / "index_sh000001.json", [])]
    sig_date = _deep_lastd if _deep_lastd != "?" else (reg["date"] if reg else today)
    buy_day = next_cal_day(cal, sig_date)
    sell_day = next_cal_day(cal, buy_day)

    # 季节档
    _sm = jload(D / "seasonal_modulation.json", {})
    _mm = today[5:7]
    _rules = (_sm.get("rules") or {})
    _mult = ((_rules.get("LIMITDOWN_NEXT_DAY") or {}).get("boost_months") or {}).get(_mm, 1.0)
    _seas = f"{int(_mm)}月档×{_mult}" if _mult != 1.0 else f"{int(_mm)}月平月档×1.0"

    # 反转族健康度
    _claims_state = jload(D / "claims_state.json", {})
    _rev_r = None
    try:
        _rev_r = _claims_state["REVERSAL_OPEN_T1"]["history"][-1]["verdicts"]["1"][0]
    except Exception:
        pass
    _rev_sick = _rev_r is None or _rev_r < 0.05

    # 持仓哨兵（真实持仓账本=watchlist.json）——先算 flags，行动单和明细表共用
    watch = jload(ROOT / "config/watchlist.json", {})
    q = {}
    pos_flags = []   # (name, code, note, price, chg, [flag_html])
    if watch and watch.get("positions"):
        codes = [p["code"] for p in watch["positions"]] + [a["code"] for a in watch.get("anchors", [])]
        q = fetch_quotes(codes)
        for c in codes:  # sina 9:15 前返回空 → kcache 昨收顶上
            if c not in q:
                try:
                    ks = json.loads((D / "big_kcache" / f"{c}.json").read_text())
                    q[c] = (ks[-1]["close"], (ks[-1]["close"] / ks[-2]["close"] - 1) * 100)
                except Exception:
                    pass
        for p in watch["positions"]:
            if p["code"] not in q:
                continue
            price, chg = q[p["code"]]
            flags = []
            for lv, desc in p["levels"].items():
                lv = float(lv)
                bear = any(k in desc for k in ("止损", "防线", "假突破", "作废", "低点"))
                if bear and price < lv:
                    flags.append(f'<span class="dn">⚠️破{esc(desc)}</span>')
                elif not bear and price > lv:
                    flags.append(f'<span class="up">✅过{esc(desc)}</span>')
            pos_flags.append((p, price, chg, flags))

    # B5 信号影子（仅最近交易日有效，隔日自动过期）
    b5_open, b5_am, b5_date = [], [], ""
    blines = []
    try:
        blines = [json.loads(l) for l in open(D / "banlu_signals.jsonl") if l.strip()]
    except Exception:
        pass
    if blines:
        b5_date = blines[-1]["date"]
        if b5_date == sig_date:
            for b in blines:
                if b["date"] != b5_date:
                    continue
                (b5_am if b.get("sealed") else b5_open).append(f'{b["name"]} {b["code"]}')

    # 影子 T+1 台账
    ledger = []
    try:
        ledger = [json.loads(l) for l in open(D / "ops_briefing_ledger.jsonl") if l.strip()]
    except Exception:
        pass
    t1 = ledger[-1] if ledger else None
    t1_sell_day = next_cal_day(cal, t1["date"]) if t1 else None
    t1_alive = t1 and t1_sell_day and t1_sell_day >= today and t1.get("buys")

    # 观察池临启动（窗口期前3）
    lin = []
    if wp and wp.get("pool"):
        lin = sorted((e for e in wp["pool"] if 1 <= e.get("days", 0) <= 5),
                     key=lambda e: (not e.get("shrink"), e["days"], -e["volratio"]))[:3]

    # ⚔️ X规则线（xrules_daily 19:15 落盘）：T1-MEGA/X2/X3 状态
    _xs = jload(D / "xrules_state.json", {})
    xrules_html = ""
    if _xs.get("date") == sig_date:
        rows = []
        for rule, label in (("T1-MEGA", "T1-MEGA巨簇分散"), ("X2", "X2妖股大簇"), ("X3", "X3恐慌狙击")):
            r = _xs.get("rules", {}).get(rule, {})
            if r.get("fired"):
                pk = "、".join(f'{p["name"]}{p.get("ladder", 0) >= 3 and "🪜" or ""}' for p in r.get("picks", [])[:5])
                rows.append(f'<span class="up">🔥{label}</span> → {esc(pk)}（买{_xs["entry_day"]}开盘，卖{"T+3" if rule == "T1-MEGA" else "T+5/-12%"}）')
            else:
                rows.append(f'<span class="mut">· {label}：{esc(r.get("why", "?"))}</span>')
        xrules_html = (f'<div class="mut">{_xs["date"]} {_xs["regime"]} · 跌停{_xs["ldc"]} · 缺口低簇{_xs["gap_cluster"]} · 恐慌streak{_xs["streak"]}</div>'
                       + "<br>".join(rows))

    # ══ 今日 ══
    # KPI 健康条
    n_deep = len(_deep)
    lin_n = len([e for e in (wp or {}).get("pool", []) if 1 <= e.get("days", 0) <= 5]) if wp else 0
    n_rev = len(rev.get("candidates", [])) if rev else 0
    kpis = '<div class="kpis">' + "".join([
        kpi("🥇 深档低位", "🟢健康", "ok", "57.8%", "赔率1.34 · T+1",
            '跌停+MA60下方 · 8年1.4万次（剔买不到的一字跌停）· T+1 均赢+5.82%/均亏-4.34% · '
            'T+5 胜率69.7%/赔率1.56（近250日 +3.98% 比 T+1 +0.82% 更稳）· 六道闸门全过 · '
            f'上次命中：宏盛股份9/14涨停✓ · {_seas}'
            + (f' · <b>信号{min(n_deep,3)}只</b>' if n_deep else ' · 今日无标的')),
        kpi("🏗️ 观察池临启动", "🟢健康", "ok", "58.9%", "历史口径",
            f'71.6%入池3日内启动 · {lin_n}只在窗口期 · 影子验证中'),
        kpi("⚡ B5半路板", "🟢健康", "ok", "48.7%", "低胜率厚尾",
            '盘中冲+6%才算信号 · 平淡/恐慌期 · <b>MA60上方</b>（低位版挂2/6已剔除）· T+5 +1.36% 靠右尾 · 雷达10:30/14:45喊'),
        kpi("🔄 反转族", "🟡关禁闭", "wp", "49.8%", "没过50%红线",
            f'{n_rev}只宽清单（跌≥3% 主体无edge：8年浅档 -0.07%、高位超跌 -2.69%）'
            f' · 只有「跌停×MA60下」那格过闸门（+5.09%/71.6%），已单独拆出'
            + (f' · 滚动边际{"+" if (_rev_r or 0)>=0 else ""}{_rev_r:.2f}pp贴线' if _rev_r is not None else '')),
    ]) + '</div>'

    # 真实持仓 callout
    pos_items = []
    for p, price, chg, flags in pos_flags:
        lv = " / ".join(f'{k}{v}' for k, v in list(p["levels"].items())[:3])
        fl = " ".join(flags)
        pos_items.append(f'· <b>{esc(p["name"])}</b> {price:.2f}：{fl or "区间内"} <span class="small">（{esc(lv)}）</span>')
    real_callout = callout("c-gray", "🏦",
                           "<b>你的真实持仓（watchlist 账本，你亲口维护的票）</b><br>"
                           + ("<br>".join(pos_items) if pos_items else "（空）")
                           + '<br><span class="small">越线雷达 9:45/10:30/13:35/14:45 会 ⚠️ 喊你</span>')

    # 信号影子单 callout
    ghost = []
    if t1_alive:
        ghost.append(f'· 若你 {fmt_d(t1["date"])} 跟买了 <b>{"、".join(t1["buys"][:5])}</b>'
                     f' → <b>{fmt_d(t1_sell_day)} 尾盘卖</b>（T+1 到点必卖，无论盈亏）')
    if b5_am:
        ghost.append(f'· 若你 {fmt_d(b5_date)} 跟买了封板票 <b>{"、".join(b5_am)}</b>'
                     f' → <b>{fmt_d(buy_day)} 早盘找高点卖</b>（涨停隔夜+2.11%/65.2%）')
    if b5_open:
        ghost.append(f'· 若你 {fmt_d(b5_date)} 跟买了未封板票 <b>{"、".join(b5_open)}</b>'
                     f' → <b>{fmt_d(buy_day)} 9:30 开盘即走</b>（断板即跑，低开断板大面率40.8%）')
    ghost_callout = callout("c-yellow", "👻",
                            "<b>信号影子单（系统假设你跟了信号；没跟 = 忽略，别硬卖）</b><br>"
                            + ("<br>".join(ghost) if ghost else "影子单没有待处理的卖出。")
                            + '<br><span class="small">系统看不到你的券商成交，只能按「信号已执行」记账；'
                              '你跟了哪单告诉我一声，就转进真实账本。</span>')

    # 新信号 steps
    steps = []
    if _deep and len(_deep) >= 5:
        names = "、".join(f'{nm}({c},{p:+.1f}%)' for c, p, nm in _deep[:3])
        steps.append(step("1", "#edf5ee", "#1e7e34",
                          f'{fmt_d(buy_day)} 9:32 买 · {names}',
                          f'{fmt_d(sig_date)} 跌停+低位（成簇日{len(_deep)}只 · 胜率57.6%）。竞价不是一字跌停 → 开盘买 → '
                          f'<b>{fmt_d(sell_day)} 尾盘卖</b>。一字跌停 = 作废。'))
    elif _deep:
        steps.append(step("1", "#f7f6f3", "#9b9a97",
                          f'{fmt_d(buy_day)} · 深档低位零星日（{len(_deep)}只）不出手',
                          f'{fmt_d(sig_date)} 仅 {len(_deep)} 只（<5 成簇线）。零星日信号 8 年全 weekday 负期望，'
                          f'可执行形态=成簇日 ≥5 只。没簇 = 空仓休息，空仓也是操作。'))
    else:
        steps.append(step("1", "#f7f6f3", "#9b9a97",
                          f'{fmt_d(buy_day)} · 深档低位无合格标的',
                          f'{fmt_d(sig_date)} 没有「跌停+低位」的票。没信号 = 空仓休息，空仓也是操作。'))
    # 妖股摇篮（DEMON_CRADLE_CLUSTER）：只在成簇日出现（年 1-3 次，平时静默）
    try:
        _crd, _cr, _crc = cradle_scan()
    except Exception:
        _crd, _cr, _crc = None, [], False
    if _crc and _crd == sig_date:
        _crn = "、".join(f'{nm}({c},{p:+.1f}%)' for c, p, nm in _cr[:4])
        steps.append(step("1b", "#fdf2e9", "#b3541e",
                          f'{fmt_d(buy_day)} 9:30 · 🔥妖股摇篮 {_crn}',
                          f'{fmt_d(sig_date)} 全市场 {len(_cr)} 只「首板缩量深跌小市值」成簇（≥3）。'
                          f'8年 T+5 73.8%/+7.74、T+20 82.5%/+14.67，但 6 成收益来自 2024-02 一个月——'
                          f'分散 3-5 只别单挑；孤板日绝不出手。'))
    if lin:
        pool_names = "、".join(f'{e["name"]}({e["code"]})' for e in lin)
        steps.append(step("2", "#f7f6f3", "#73726e",
                          f'等QQ喊 · {pool_names}（先不买）',
                          '只有「它涨停+同板块≥3只涨停」才挂涨停价排队；涨2-5%没涨停不买、绿了不买、跌了更不买。'
                          '梯队成型雷达会喊，不用盯。破入池前低=作废。'))
    steps.append(step("3", "#f7f6f3", "#73726e",
                      'B5 半路板（触发制）',
                      '盘中冲 +6% 且平淡/恐慌期、且收盘价在 <b>MA60 上方</b>才算信号，雷达 10:30/14:45 会喊；没喊 = 没信号。'
                      '（MA60 下方的半路板 submit 挂 2/6，已从推送剔除）'))

    action_html = (
        '<div id="nownow" style="font-size:18px;font-weight:700;padding:13px 16px;'
        'background:var(--soft);border-radius:8px;line-height:1.6;margin-bottom:12px">读取当前时间…</div>'
        + kpis
        + f'<h3 style="margin:16px 0 6px">{fmt_d(buy_day)} 要做的事 <span class="small">全部绝对日期，没有「今天/明天」</span></h3>'
        + real_callout + ghost_callout + "".join(steps)
        + callout("c-yellow", "⏰", "<b>时间纪律</b>：买只在 9:32~9:45 · 卖只在尾盘（或上面点名的早盘）· "
                                   "其余时间不操作。每个交易日 9:25 QQ 发「作战单」，与本页同源。"))
    S["今日"].append(card("📋 行动单", action_html,
                          f"数据截至 {fmt_d(sig_date)}收盘 · 执行日 {fmt_d(buy_day)}", tab="今日"))
    if xrules_html:
        S["今日"].append(card("⚔️ X规则线 · 每晚19:15保真判定", xrules_html, tab="今日"))

    # 市场状态
    if reg:
        st = reg["stats"]
        S["今日"].append(card(f"市场状态 · {fmt_d(reg['date'])}", f"""
<div class="statrow"><div><div class="big">{badge_regime(reg['regime'])}</div>
<div class="muted">周期仪 · {esc(reg['date'])}</div></div>
<div class="stat"><div class="num">{st['limit_ups']}<span class="muted"> / {st['limit_downs']}</span></div><div class="muted">涨停 / 跌停</div></div>
<div class="stat"><div class="num">{pct(st['index_pct'])}</div><div class="muted">指数</div></div></div>
<div class="muted" style="margin-top:10px">主线板块：{"、".join(f"{esc(n)}({c})" for n, c in st["top_sectors"][:4])} · 周期仪是油门不是方向盘：恐慌期=打板fill黄金期，主线期=红利拿稳别手痒</div>""",
                              "每日 15:40 盘后扫描", tab="今日"))

    # 作战手册
    S["今日"].append(card("🎯 作战手册 · 2026-09 起",
                          """<table><tr><th>层</th><th>规则</th></tr>
<tr><td><b>底仓 60-70%</b></td><td>大部分钱买会分红的股票（银行为主），放着收租不动。只有跌得很便宜（分红率≥4.5%）才加买。<b>永远不要全卖</b>——折腾来回去还不如躺着（实测少赚13%）</td></tr>
<tr><td><b>进攻仓 0-30%</b></td><td>小部分钱玩短线，<b>只在市场冷清/恐慌的日子玩</b>（热闹日子玩=送钱，实测-2.6%）；买的票第二天没涨停就立刻卖掉，不许心疼留着</td></tr>
<tr><td><b>禁区（碰都别碰）</b></td><td>借钱炒股/全押一个板块/买跌停板/当天买当天卖/跟游资买/看新闻买/挂低价等回踩/炸板回封/金叉长线——全部实测亏钱</td></tr></table>""",
                          "每条规则带证据编号 · <a href='playbook-202609.md' style='color:#c0392b'>完整版+kill线 →</a>",
                          tab="今日"))

    # QQ 配合说明
    S["今日"].append(card("📲 怎么配合 QQ 推送用这页",
                          """<table><tr><th>QQ 推送</th><th>对应本页版块</th><th>动作</th></tr>
<tr><td>9:25 盘前作战单</td><td>📋 行动单（本页第一卡）</td><td>先卖后买，影子单没跟=忽略</td></tr>
<tr><td>9:32 反转族竞价确认</td><td>证据库 · 反转名单（ICU期不推）</td><td>确认通过→开盘买；被剔→作废</td></tr>
<tr><td>9:45/10:30/13:35/14:45 盘中雷达</td><td>行动单 · 真实持仓⚠️ / 观察池</td><td>⚠️破位=按纪律执行；梯队成型→挂涨停价排队</td></tr>
<tr><td>15:40 周期仪</td><td>市场状态徽章</td><td>周期切换=仓位档调整</td></tr>
<tr><td>16:05 / 19:00 后委托单/影子</td><td>我的钱 · 银行委托单</td><td>次日盘前照委托单挂单</td></tr></table>""",
                          "QQ=触发器（有事才说话），本页=证据库（盘后全貌+规则原文）",
                          "顺序：收到 QQ 推送 → 来这页找对应版块看规则和实测口径 → 按作废条件执行。别只看推送就动手。",
                          collapsed=True, tab="今日"))

    # ══ 我的钱 ══
    if pos_flags:
        rows = []
        for p, price, chg, flags in pos_flags:
            _mk = ("sh" if p["code"].startswith("6") else "sz") + p["code"]
            rows.append([f"{esc(p['name'])}<br><span class='muted'>{p['code']}</span>",
                         f'<span data-q="{_mk}" data-f="p">{price:.2f}</span>',
                         f'<span data-q="{_mk}" data-f="r">{pct(chg)}</span>',
                         f'<span class="muted">{esc(p["note"])}</span>',
                         " ".join(flags) or '<span class="muted">区间内</span>'])
        S["我的钱"].append(card("持仓哨兵", table(["标的", "现价", "今日", "备注", "关键位"], rows),
                                "config/watchlist.json · 越线自动标记", tab="我的钱"))
    if watch:
        arows = []
        for a in watch.get("anchors", []):
            if a["code"] not in q:
                continue
            price, chg = q[a["code"]]
            in_zone = price <= a["buy"]
            _mk = ("sh" if a["code"].startswith("6") else "sz") + a["code"]
            arows.append([esc(a["name"]),
                          f'<span data-q="{_mk}" data-f="p">{price:.2f}</span>', f'{a["buy"]:.2f}',
                          f'<span data-q="{_mk}" data-f="z" data-buy="{a["buy"]:.2f}">'
                          + ('<span class="up">🟢买入区内</span>' if in_zone
                             else f'<span class="muted">线上方{(price/a["buy"]-1)*100:+.1f}%</span>')
                          + '</span>'])
        if arows:
            S["我的钱"].append(card("股息锚买入区", table(["标的", "现价", "买入线", "状态"], arows),
                                    "现价≤线=可建仓/加仓", tab="我的钱"))
    bf = D / "bank_console_latest.txt"
    if bf.exists():
        import os as _os
        _bt = datetime.datetime.fromtimestamp(_os.path.getmtime(bf)).strftime("%m-%d %H:%M")
        rows, orders = parse_bank(bf.read_text())
        if rows:
            S["我的钱"].append(card("银行股操作台", table(
                ["标的", "现价", "息率", "PB", "状态", "买入线", "卖出线", "清仓线", "距买入"], rows),
                f"股息率锚 · 样本外 60.1% 胜率 · 生成于 {_bt}（价格线仅分红/财报后调整，跨日仍有效）",
                "规则：买入区=可建仓/加仓（阶梯挂单 买线/-4%/-8%）；卖出区=减仓不清仓；清仓区=清仓离场。价格线不随日内波动。",
                tab="我的钱"))
        if orders:
            S["我的钱"].append(card("银行 · 委托单", table(
                ["标的", "操作", "买入", "加仓阶梯", "卖出", "清仓"], orders),
                f"生成于 {_bt} · 价格线在下个交易日 16:05 重建前持续有效，盘前照抄挂单即可",
                tab="我的钱"))
    # 收割型席位 × 持仓
    SHOUGE_SEATS = {"T王", "山东帮", "温州帮"}
    hdirs2 = sorted((D / "hithink").glob("2026-*"))
    if hdirs2 and watch and watch.get("positions"):
        lhb = jload(hdirs2[-1] / "lhb_hot.json", {})
        watch_codes = {p["code"]: p["name"] for p in watch["positions"]}
        hits = []
        for seat in ((lhb or {}).get("data", {}).get("hot_money_items") or []):
            if seat["name"] not in SHOUGE_SEATS:
                continue
            for r in seat.get("rows") or []:
                if (r.get("hot_money_item_net_value") or 0) > 0 and r["ticker"] in watch_codes:
                    hits.append([esc(watch_codes[r["ticker"]]), esc(seat["name"]),
                                 f'{(r["hot_money_item_net_value"])/1e4:.0f}万',
                                 '<span class="dn">次日=出货窗口</span>'])
        body = (table(["持仓标的", "收割席位", "净买入", "提示"], hits) if hits
                else '<div class="muted">今日持仓与收割型席位无交叉 ✅</div>')
        S["我的钱"].append(card("收割型席位 · 持仓反向提示", body,
                                f"{esc(hdirs2[-1].name)} 龙虎榜 · T王/山东帮/温州帮净买入你的持仓=警惕",
                                tab="我的钱"))

    # ══ 研究库 ══
    ov = []
    ov.append(["🥇 深档低位", "71.6%", "🟢健康",
               f"信号 {n_deep} 只 · {_seas}" if n_deep else f"今日无（没大跌日就没票）· {_seas}",
               "跌停且收盘在 MA60 下方 → 次日开盘买，持有 5 天。上方的不做"])
    ov.append(["🏗️ 观察池临启动", "58.9%", "🟢健康",
               f"{lin_n} 只在窗口期" if lin_n else "今日无",
               "等它首板+板块 3 只涨停才买，雷达会喊"])
    ov.append(["⚡ B5 半路板", "48.7%", "🟢健康",
               "触发制：盘中冲 +6% 才算信号；T+5 +1.36%（低胜率厚尾）",
               "平淡/恐慌期 + 收盘在 <b>MA60 上方</b>；低位版挂 2/6 已剔除，10:30/14:45 雷达喊"])
    ov.append(["🔄 反转族", "49.8%", "🟡重症监护",
               f"{n_rev} 只宽清单（主体无 edge：浅档 -0.07%、高位超跌 -2.69%）",
               "只做「跌停+MA60下」那格；整份清单不推"])
    S["研究库"].append(card("📋 策略分工 · 每个策略每天最多盯 3 只",
                            table(["策略", "胜率", "状态", "今日", "怎么用它（一句话）"], ov),
                            "胜率=8 年实测净口径 · 🟢=可动手 🟡=只看不动",
                            "纪律：同一时刻只执行一个策略的信号；都没信号=今天空仓休息，空仓也是操作。",
                            tab="研究库"))

    # 季节月份层
    try:
        boosts = (_rules.get("LIMITDOWN_NEXT_DAY") or {}).get("boost_months") or {}
        note = (_rules.get("LIMITDOWN_NEXT_DAY") or {}).get("note", "")
        max_mult = (_rules.get("LIMITDOWN_NEXT_DAY") or {}).get("max_mult", 1.2)
        month_rows = []
        for m in ["01", "02", "07", "09", "12"]:
            mult = boosts.get(m, 1.0)
            tag = {2: '<span class="up">加仓×1.15 · 双高格（64.4%胜率/盈亏比2.02，384格扫描唯一存活）</span>',
                   7: '<span class="dn">减仓 · 2026-07 全策略崩（8年唯一负7月）</span>'}.get(int(m), "")
            if not tag:
                tag = (f'<span class="up">加仓×{mult}</span>' if mult > 1.0 else '<span class="muted">×1.0 平月</span>')
            cur = ' <b>← 当前</b>' if m == _mm else ""
            month_rows.append([f"{int(m)}月{cur}", tag])
        S["研究库"].append(card("📅 季节月份层 · 直接调仓位",
                                table(["月份", "跌停接档位（实测）"], month_rows) +
                                f'<div class="muted" style="margin-top:8px">{esc(note)} · 调制上限×{max_mult}（{_sm.get("discipline","")} ）· 数据源 seasonal_modulation.json（{_sm.get("version","")}）</div>',
                                "8年逐月实测 · 月度超额已剥离大盘beta",
                                "用法：加档月=信号仓位×系数，减仓月=能不做就不做。2月黄金月过完即复验。",
                                tab="研究库"))
    except Exception:
        pass

    # 在攒数据
    try:
        import glob as _g2
        cb_days = len(_g2.glob(str(D / "cb_m5" / "*")))
        shadow_lines = 0
        try:
            shadow_lines = sum(1 for l in open(D / "claims_shadow.jsonl") if l.strip())
        except Exception:
            pass
        S["研究库"].append(card("🧪 在攒数据（够样本才终审，都有明确终止条件）",
                                table(["研究", "怎么测的", "目前发现", "状态"], [
            ["转债T+0联动",
             "正股涨停那一刻买它的可转债，看几分钟后卖赚不赚（5分钟粒度）",
             "5分钟内进：100次里61次赚+2.14%；1小时后进=买顶（60min粒度已被击毙-0.20%）",
             f'<span class="tag">攒数中 · 已攒{cb_days}个交易日，目标2-3个月</span>'],
            ["首板抢跑影子盘",
             "首板+板块3只涨停的票，模拟封板bar排队买入，记次日真实涨跌",
             "纸面100次里59次赚，但封死板买不进——真实赚多少影子盘说了算",
             f'<span class="tag">影子中 · 已登记{shadow_lines}单，20个交易日见分晓</span>'],
            ["妖股生命周期四段论",
             "8年所有连板票，分启动/晋级/分歧/二波四段各算存活率",
             "缩量涨停晋级率是放量1.6-1.8倍（持有规则）；断板低开100次里41次大面→立即走；二波只做距前高<10%的老龙",
             '<span class="tag">规则撰写中</span>'],
        ]), "每条都写明怎么测的、结论是什么、现在什么状态", tab="研究库"))
    except Exception:
        pass

    # 证伪墓地
    S["研究库"].append(card("🪦 证伪墓地（测死了的，立碑防复活）",
                            table(["玩法", "怎么测的", "死因"], [
        ["打板族（首板次日追/连板追）", "8年全部首板/连板票，次日开盘买", "四种市场状态全亏；「别人打板吃香」是幸存者幻觉"],
        ["盘中机械做T（正T+反T）", "2年分钟线模拟，9种正T+6种反T参数", "每日期望-0.06~-0.20%，稳定亏钱机器，躺平即最优"],
        ["看新闻买股", "新浪/财联社2500+条资讯提及后买入", "全象限负期望——利好兑现在发布前已完成"],
        ["跟龙虎榜席位买", "一年龙虎榜，跟机构/知名席位次日买", "隔夜缺口收割公告效应；只配当过滤器/反向指标"],
        ["缠论/海龟突破/均线金叉", "底分型+背驰三重确认 vs 随机对照", "复杂确认是负增量噪音，跑输随机"],
        ["缩量晋级追买", "缩量涨停次日开盘追（submit双REJECT）", "晋级率高≠能买——晋级时买不进，断板全亏"],
        ["绞肉机/彩票因子", "全市场8年含退市股", "-54%/-56%，黑名单榜首，永禁"],
    ]), "复活任何一条前，必须先过 law_pipeline 六道闸门", tab="研究库"))

    # ══ 证据库 ══
    # 信号明细（行动单的全量版本）
    if _deep:
        rows_d = [[f'{esc(nm)}<br><span class="muted">{c0}</span>',
                   pct(p0), '<span class="up">MA60下✓</span>',
                   '<span class="muted">跌停接L2+ +2.65%/57.6%（剔一字后）</span>',
                   "竞价一字跌停=作废；封死板买不进则放弃",
                   f'<span data-q="{("sh" if c0.startswith("6") else "sz")+c0}" data-f="r"><span class="muted">…</span></span>']
                  for c0, p0, nm in _deep[:5]]
        S["证据库"].append(card("深档低位 · 信号明细",
                                table(["标的", "昨跌幅", "位置", "历史口径", "作废条件", "现在"], rows_d),
                                f"{fmt_d(sig_date)} 深档≤-9.5%全扫 · 只留MA60下（高位断板大面已剔除）",
                                "全库扫描不是名单切片——9/14 宏盛股份涨停就是这条的命中。",
                                collapsed=True, tab="证据库"))
    if lin:
        pick_rows = []
        for e in lin:
            _mk = ("sh" if str(e["code"]).startswith("6") else "sz") + str(e["code"]).zfill(6)
            pick_rows.append([f"{esc(e['name'])}<br><span class='muted'>{e['code']}</span>",
                              f'<span data-q="{_mk}" data-f="r"><span class="muted">…</span></span>'
                              f'<br><span data-q="{_mk}" data-f="j"></span>',
                              f'第{e["days"]}天 · 量比{e["volratio"]}x' + (" · 缩量持稳" if e.get("shrink") else ""),
                              "梯队≥3涨停+自身首板=触发；破入池前低=作废"])
        S["证据库"].append(card("观察池临启动 · 信号明细",
                                table(["标的", "现在（30秒刷新）", "池内状态", "触发/作废"], pick_rows),
                                "排序=缩量持稳>天数>量比 · 梯队成型雷达会QQ推送",
                                "⚠️ 合法买点只有一种：它涨停（且板块≥3只涨停）→ 挂涨停价排队。"
                                "58.9%是历史口径（封死板买不进有水分），实战 edge 介于 +1.79% 与 -0.52% 之间。",
                                collapsed=True, tab="证据库"))
    if b5_open or b5_am:
        rows_b = ([[esc(x), "未封板", '<span class="dn">开盘即走（断板即跑铁律）</span>'] for x in b5_open]
                  + [[esc(x), "封板在手", '<span class="up">早盘兑现（隔夜+2.11%/65.2%实测）</span>'] for x in b5_am])
        S["证据库"].append(card("⚡ B5 处置明细（影子单）",
                                table(["标的", "状态", "动作"], rows_b),
                                f"{fmt_d(b5_date)} 信号 · 反人群打板不留恋",
                                collapsed=True, tab="证据库"))

    # 反转族
    if _rev_sick and rev and rev.get("candidates"):
        S["证据库"].append(card("🔄 反转族 · 重症监护中（不出首选）",
                                f'<div class="muted">滚动250日边际贡献 {"+" if _rev_r and _rev_r>=0 else ""}{_rev_r:.2f}pp 贴线（健康线 0.05pp）· '
                                f'T+1 胜率 49.8% 未过 50% 用户规则线 · 名单在下方可查，但体系当前不主动推它。</div>',
                                "2026-09-14 盘中用户裁决：胜率<50%或滚动edge贴线的主张降级为观察，不进首选",
                                "恢复条件：claims_audit 滚动边际回到 +0.05pp 以上。历史上它 +0.139%/46万样本是真的，"
                                "但最近一年近乎熄火——是真衰减还是风格期，影子盘继续量。",
                                collapsed=True, tab="证据库"))
    try:
        cf = D / "reversal_confirmed.json"
        if cf.exists():
            c = json.loads(cf.read_text())
            if c.get("date") == today and c.get("executable"):
                rows_c = []
                for x in c["executable"][:8]:
                    mk = ("sh" if x["code"].startswith("6") else "sz") + x["code"]
                    rows_c.append([f'{esc(x.get("name",""))}<br><span class="muted">{x["code"]}</span>',
                                   f'开{x["open_chg"]:+.1f}%',
                                   f'<span data-q="{mk}" data-f="r"><span class="muted">…</span></span>'])
                S["证据库"].append(card("反转族 · 今日确认单（宽清单已停推）",
                                        table(["标的", "竞价", "现在"], rows_c) +
                                        f'<div class="muted" style="margin-top:6px">共 {c["n"]} 只可执行 · '
                                        f'高开{c["high_open"]}只（{"❌宽清单抢跑作废" if c.get("voided") else "未动作废线"}）· '
                                        f'2026-09-18 起宽清单停推（8年 49.8% 未过红线），仅「跌停+MA60下方」组进推送，此表帐目照记</div>',
                                        f"{fmt_d(today)} 9:32 竞价确认 · 实时价30秒刷",
                                        collapsed=True, tab="证据库"))
    except Exception:
        pass
    if rev and rev.get("candidates"):
        rows = [[esc(c["code"]), esc(c["name"]), pct(c["close_chg"]), f'{c["amt_yi"]:.0f}亿']
                for c in rev["candidates"][:8]]
        S["证据库"].append(card(f"反转族 · 待确认名单（{fmt_d(rev.get('date', ''))} 收盘扫）",
                                table(["代码", "名称", "当日跌幅", "成交额"], rows),
                                "收盘扫描 · 外部复审 +0.139%/49.8% 净口径", REV_RULE,
                                collapsed=True, tab="证据库"))

    # 跌幅深度 × MA60位置 8年网格（2026-09-18 新增：回答"该推跌停的还是几个点的"）
    try:
        grid = jload(D / "depth_position_grid_20260918.json", {})
        if grid.get("rows"):
            ORDER = ["跌停 ≤-9.5%", "深 -7~-9.5%", "中 -5~-7%", "浅 -3~-5%"]
            cell = {(r["bucket"], r["pos"]): r for r in grid["rows"]}
            rows_g = []
            for b in ORDER:
                lo, hi = cell.get((b, "MA60下")), cell.get((b, "MA60上"))
                def fmt1(x):
                    if not x:
                        return "—"
                    cls = "up" if x["mean"] > 0.05 else ("dn" if x["mean"] < -0.05 else "muted")
                    return (f'<span class="{cls}">{x["mean"]:+.2f}%</span>'
                            f'<br><span class="muted">{x["win"]:.0f}%胜 · n={x["n"]:,}</span>')
                rows_g.append([esc(b), fmt1(lo), fmt1(hi)])
            S["证据库"].append(card("📐 跌幅深度 × MA60位置 · 8年网格（新增证据）",
                                    table(["跌幅档", "MA60 下方（低位）", "MA60 上方（高位）"], rows_g),
                                    grid.get("口径", ""),
                                    "怎么读：钱只在「跌得深 <b>且</b> 在 MA60 下方」那一格。"
                                    "高位超跌/高位跌停两格是负期望——名单里混进它们就是亏的来源。"
                                    "（2026-09-18 全主板全历史 T+1 自测；与 submit 的 T+5 口径不同）",
                                    collapsed=True, tab="证据库"))
    except Exception:
        pass

    # 跌停接 位置拆分 · 闸门终审
    try:
        sub = jload(D / f"law_pipeline_submit_{today.replace('-', '')}.json", {})
        keys = ["跌停次日接_剔一字", "跌停接_MA60下", "跌停接_MA60上"]
        if any(k in sub for k in keys):
            rows_s = []
            for k in keys:
                v = sub.get(k)
                if not v:
                    continue
                g = v.get("闸门", {})
                nfail = sum(1 for x in g.values() if "❌" in str(x))
                verdict = ('<span class="up">通过</span>' if nfail == 0
                           else f'<span class="dn">否决（{nfail}/6 闸门挂）</span>')
                regseg = v.get("regime分段", {})
                reg_txt = " ".join(f'{kk[:2]}{vv["mean%"]:+.1f}%' for kk, vv in regseg.items())
                fs = v.get("全样本", {})
                rows_s.append([esc(k), verdict,
                               f'{fs.get("win%", 0):.1f}% / {fs.get("mean%", 0):+.2f}%',
                               f'<span class="muted">{esc(reg_txt)}</span>',
                               f'{v.get("每票每年触发", 0):.2f} 次'])
            S["证据库"].append(card("🚦 跌停接 · 位置拆分闸门终审（2026-09-18）",
                                    table(["信号", "判决", "T+5 胜率/均值", "regime 分段", "每票每年"], rows_s),
                                    "law_pipeline submit · 六道硬闸门（t_NW≥3/双段/regime≥3-4/市值≥4-5/位置匹配边际>0/0.3%成本仍正）",
                                    "关键：<b>位置过滤把一条「恐慌期专属」信号变成全闸门通过</b>——"
                                    "不加位置过滤的跌停接挂在 G3（regime 只有恐慌期为正）。"
                                    "但注意 DSR=0：它的钱有很大一块是恐慌日的市场反弹（beta）。",
                                    collapsed=True, tab="证据库"))
    except Exception:
        pass

    # 第二轴细分批（2026-09-18）：位置方向二次验证（网格→submit）
    try:
        sa = jload(D / "second_axis_submit_20260918.json", {})
        sg = sa.get("signals", {})
        if sg:
            rows_a = []
            for k, v in sg.items():
                nf = "❌" if "REJECT" in str(v.get("verdict")) else "✅"
                tag = ("采纳" if v.get("adopted") else
                       ("否决" if "REJECT" in str(v.get("verdict")) else "不采纳"))
                rows_a.append([esc(k), f'{nf} {esc(str(v.get("verdict","")))}',
                               f'{v.get("T5_win",0):.1f}% / {v.get("T5_mean",0):+.2f}%',
                               f'<span class="muted">n={v.get("n",0)} · 每票每年{v.get("per_stock_year",0)}</span>',
                               f'<b>{tag}</b>'])
            S["证据库"].append(card("🧭 第二轴 · 位置细分批（2026-09-18）",
                                    table(["信号", "闸门判决", "T+5 胜率/均值", "样本/频率", "处置"], rows_a),
                                    "第二轴网格 → law_pipeline submit · 8 年全市场口径（3333 只含退市）",
                                    "规律：<b>位置方向跟信号族性质绑定</b>——接跌类（跌停接/恐慌深度/首板低位）要 MA60 <b>下方</b>；"
                                    "追强类（B5 半路板）要 MA60 <b>上方</b>（上 +1.36% vs 下 +0.39% 挂 2/6，已从推送剔除）。"
                                    "「缩量档」原以为更优，闸门实测 T+1/T+5 都略低（+4.54% vs +5.09%、频率砍 84%）→ <b>不采纳</b>。",
                                    collapsed=True, tab="证据库"))
    except Exception:
        pass

    # 观察池全名单
    if wp and wp.get("pool"):
        _secmap = {}
        try:
            import glob as _g
            _secf = json.loads(open(sorted(_g.glob(str(D / "hithink/sectors/stock_sectors_*.json")))[-1]).read())
            _STOP = {"融资融券", "深股通", "沪股通", "国企改革", "次新股", "ST股"}
            for c0, arr in _secf.items():
                tags = [e["name"] for e in arr if e.get("name") and e["name"] not in _STOP][:2]
                _secmap[str(c0).zfill(6)] = "|".join(tags)
        except Exception:
            pass

        def _wrow(e):
            _mk = ("sh" if str(e["code"]).startswith("6") else "sz") + str(e["code"]).zfill(6)
            return [esc(e["code"]), esc(e["name"]),
                    f'<span class="muted">{esc(_secmap.get(str(e["code"]).zfill(6), "—"))}</span>',
                    f'<span class="muted">{esc(e["entry_date"])}</span>',
                    f'{e["volratio"]}x', pct(e["pct"]), str(e.get("days", 0)),
                    '<span class="up">缩量持稳</span>' if e.get("shrink") else '<span class="muted">观察中</span>',
                    f'<span data-q="{_mk}" data-f="r"><span class="muted">…</span></span>']
        _pool_sorted = sorted(wp["pool"], key=lambda e: -e["volratio"])
        rows = [_wrow(e) for e in _pool_sorted[:3]]
        if len(_pool_sorted) > 3:
            rows.append([f'<details><summary class="muted">展开其余 {len(_pool_sorted)-3} 只（不用盯）</summary>'
                         + table(["代码", "名称", "板块", "入池", "量比", "当日", "天数", "状态", "现在"],
                                 [_wrow(e) for e in _pool_sorted[3:]]) + '</details>',
                         "", "", "", "", "", "", "", ""])
        S["证据库"].append(card("放量异动观察池 · 全名单",
                                table(["代码", "名称", "板块", "入池", "量比", "当日", "天数", "状态", "现在"], rows),
                                f'{esc(wp.get("updated", ""))} · 放量未板+缩量横盘不破=启动前形态（002519 原型）',
                                "用法：放量只是入池门票（异动2.4x基率），真正加分项是入池后缩量持稳；"
                                "该票板块当日≥3只涨停=梯队成型；破入池日前低=出局。",
                                collapsed=True, tab="证据库"))

    # 首板抢跑影子
    fr = []
    sf = D / "claims_shadow.jsonl"
    if sf.exists():
        for line in sf.read_text().splitlines():
            r = json.loads(line)
            if r["claim"] == "FRONTRUN_FIRSTBOARD_V2":
                fr.append(r)
    if fr:
        _names = {}
        try:
            _names = {str(s["code"]).zfill(6): s.get("name", "")
                      for s in json.loads((D / "main_board_codes.json").read_text())["stocks"]}
        except Exception:
            pass
        by_date = {}
        for r in fr:
            by_date.setdefault(r["signal_date"], []).append(r)
        rows = []
        for dt in sorted(by_date, reverse=True)[:3]:
            for r in by_date[dt]:
                # 注册表桥新记录只有 claim/code/entry/signal_date/tier（r1/r5 回填后才出现）——
                # 2026-09-19 实锤：r["r1"] KeyError 会把整盘面构建炸掉（19:20 cron 静默失败）。
                rows.append([f'<span class="muted">{esc(dt)}</span>',
                             f'{esc(_names.get(r["code"], ""))}<br><span class="muted">{esc(r["code"])}</span>',
                             pct(r["r1"] * 100 if r.get("r1") is not None else None),
                             pct(r["r5"] * 100 if r.get("r5") is not None else None),
                             '<span class="muted">未成交</span>' if r.get("untradeable") else (
                                 '<span class="ok">在车上</span>' if r["entry"] else '<span class="muted">待回填</span>')])
        S["证据库"].append(card("首板抢跑 · 影子名单", table(["信号日", "标的", "T+1", "T+5", "状态"], rows),
                                "首板+板块梯队≥3+市值20-400亿 · 测量级通过 影子验证中",
                                FRONT_RULE + FILL_NOTE, collapsed=True, tab="证据库"))

    # 主张影子汇总
    summ = jload(D / "claims_shadow_summary.json", {})
    rows = []
    for claim, tiers in (summ or {}).items():
        for tier, tags in tiers.items():
            r1, r5 = tags.get("r1"), tags.get("r5")
            if r1 or r5:
                rows.append([esc(claim), esc(tier),
                             f'{r1["mean%"]}%/{r1["win%"]}%' if r1 else "—",
                             f'{r5["mean%"]}%/{r5["win%"]}%' if r5 else "—",
                             str((r5 or r1)["n"])])
    S["证据库"].append(card("主张影子表现",
                            table(["主张", "档", "T+1 均值/胜率", "T+5 均值/胜率", "n"], rows) if rows
                            else '<div class="muted">影子期积累中（2026-09-11 起，20 交易日见分晓）</div>',
                            "L5 前向验证 · kill 线滚动审计，不达标自动降级",
                            collapsed=True, tab="证据库"))

    # 模拟盘锦标赛（每个玩法写明"当时怎么模拟的"）
    tour = jload(D / "sim_tournament_20260912.json", {})
    if tour and tour.get("strategies"):
        NAMES = {"reversal": "🔄 反转/跌停接（每日最深3只）❌已枪毙", "scalp_overnight": "⚡ 短差（打板吃隔夜缺口）",
                 "short_optimized": "🚀 打板优化（涨停隔夜次早卖）", "short_t1": "📅 短线（打板次日尾盘）",
                 "dividend_hold": "💰 股息躺平", "dividend_t": "🔁 股息做T",
                 "long_trend": "📈 长线（金叉/破年线次早卖）", "long_optimized": "📈 长线优化（破位当日尾盘卖）",
                 "swing_t5": "🌊 波段（打板拿5天）"}
        DESC = {"reversal": "每天买跌得最深的3只、第二天卖。已永久开除——最深的票=正在连续跌停的票",
                "scalp_overnight": "打板买入后只持有一夜，次日尾盘卖，吃隔夜高开缺口",
                "short_optimized": "收盘前涨停的票模拟涨停价排队买入（买不进则放弃），拿隔夜，次日早盘卖",
                "short_t1": "同打板优化，但持有到次日尾盘才卖",
                "dividend_hold": "买入一篮子高股息银行股后完全不动，只收分红+价差，2年零操作",
                "dividend_t": "同样高股息篮子，但每天做T。结论：折腾不如躺平",
                "long_trend": "跌破年线的票次日买、破位次日早卖",
                "long_optimized": "同上，但破位当日尾盘就卖",
                "swing_t5": "打板买入后拿满5个交易日再卖"}
        rows = []
        for k, v in sorted(tour["strategies"].items(), key=lambda x: -x[1]["return%"]):
            rows.append([NAMES.get(k, k), pct(v["return%"]), f'{v["maxDD%"]}%',
                         f'{v["trades"]}笔/{v["win%"]}%' if v["trades"] else "拿死不动",
                         pct(v["avg%"]) if v["trades"] else '<span class="muted">—</span>',
                         f'<span class="muted" style="font-size:11.5px">{DESC.get(k, "")}</span>'])
        slip = ""
        rt = jload(D / "sim_retest_t1_20260912.json", {})
        if rt:
            r2, r3 = rt["R2_对账"], rt["R3_连板跌停"]
            slip = (f'T+1合规终审（用户抓包修正）：跌停接top3 = -78%（{r3["入场日再跌停笔数"]}笔/{r3["占C臂比例%"]}% 撞连板跌停，'
                    f'子集均{r3["该子集均笔%"]}%）。引擎对账✓：全量跌3% {r2["A_全量跌3%(期望≈+0.139/晚段≈0)"]["avg%"]}%'
                    f'、全量跌停接 {r2["B_全量跌停接(期望≈+0.26)"]["avg%"]}% 复现框架。'
                    f'统计意义 edge 存在但"每日最深3只"策略化失败——最深的票=正在连板跌停的票。')
        split = jload(D / "sim_regime_split_8y_20260912.json", {}) or jload(D / "sim_regime_split_20260912.json", {})
        if split:
            slip += (' 8年总决算：打板优化纸面均笔每年 +1.6~2.9% 八年全稳——信号 edge 没死；'
                     '衰减在可成交层：fillable 子集 2024 +3.22%（强于纸面）→ 2026 -0.06%（远弱于纸面+1.79%），'
                     '抢单竞争逐年恶化。8年证伪：长线金叉 -57~-63%、跌停接 -82%。')
        zoo = jload(D / "strategy_zoo_20260911.json", {})
        era_rows = []
        for k, v in (zoo or {}).items():
            if not isinstance(v, dict) or "前半" not in v:
                continue
            f1 = v["前半"].get("T+1尾盘", {})
            l1 = v["后半"].get("T+1尾盘", {})
            fw, lw = f1.get("win%"), l1.get("win%")
            if fw is None or lw is None:
                continue
            trend = ('<span class="up">↑变强</span>' if lw - fw >= 1
                     else '<span class="dn">↓衰退</span>' if lw - fw <= -1 else '<span class="muted">→持平</span>')
            era_rows.append([esc(k.split(" ", 1)[-1]), f"{fw}%", f"{lw}%", pct(l1.get("mean%")), trend])
        era_rows.sort(key=lambda r: -float(r[2].rstrip('%')))
        era_html = ("<div style='margin-top:14px'><b>分时代胜率（前半=2019-22 / 后半=2023-26，T+1净口径）</b>"
                    + table(["策略", "19-22 胜率", "23-26 胜率", "后段均笔", "趋势"], era_rows)
                    + "<div class='muted' style='margin-top:6px'>另：红利锚（不在此表，长线口径）胜率 57.5%→60.1% 逆势上升；"
                      "2026 年真实图景=挤板/追高全灭，活的是两端（深跌接+红利躺平）。</div></div>")
        S["证据库"].append(card("模拟盘锦标赛 · 两年各10万",
                                table(["玩法", "收益", "最大回撤", "笔数/胜率", "均笔", "当时怎么模拟的"], rows) + era_html,
                                f'{tour["window"][0]} ~ {tour["window"][1]} · 基准(上证) +{tour["bench%"]}% · 净口径 m60成交验证',
                                f'历史重放≠未来。所以 2026-09-11 起开了实战影子盘：信号照发、虚拟买入、记真实涨跌，'
                                f'20 个交易日后出第一份真实对账单——纸面成绩有几分真，前向数据说了算。{slip}',
                                collapsed=True, tab="证据库"))

    # 游资口味
    taste = jload(D / "seat_gene_rolling.json", {})
    if taste and taste.get("seats"):
        rows = []
        for nm, s in list(taste["seats"].items())[:8]:
            t5 = s.get("buy_dir_T5") or {}
            if nm in ("T王", "温州帮", "山东帮"):
                note = '<span class="badge" style="color:#c0392b;background:#fdecea">收割型</span> 上榜次日=出货窗口'
            else:
                note = '<span class="muted">跟单无 edge，仅作环境证据</span>'
            rows.append([esc(nm), "、".join(c for c, _ in s["top_concepts"][:3]),
                         pct(t5.get("avg%")) if t5 else "—", note])
        S["证据库"].append(card("游资口味 · 滚动 90 天",
                                table(["席位", "近 90 天偏好", "买向 T+5", "备注"], rows),
                                f'{esc(taste.get("window", ""))} · 口味半年换血，每周六更新',
                                collapsed=True, tab="证据库"))

    # 北向
    north = None
    for p in sorted(D.glob("north_profile_*.json")):
        north = jload(p)
    if north:
        mv = north["moves"]
        inc = sorted(north.get("increase_stocks", []),
                     key=lambda s: -((s.get("ratio") or 0) - (s.get("prev_ratio") or 0)))[:10]

        def _chg(s):
            try:
                v = float(s["change"]) / 1e8
                cls = "up" if v > 0 else "dn" if v < 0 else "muted"
                return f'<span class="{cls}">{v:+.2f}</span>'
            except (TypeError, ValueError):
                return '<span class="muted">—</span>'
        rows = [[esc(s["code"]), f'{s["ratio"]:.1f}%', _chg(s) + '<span class="muted">亿股</span>',
                 f'<span class="muted">{esc(s["industry"].split("、")[0][1:])}</span>'] for s in inc]
        S["证据库"].append(card("北向资金 · 季报画像", f"""
<div class="statrow"><div class="stat"><div class="num">{mv['增持+新进']}</div><div class="muted">增持+新进</div></div>
<div class="stat"><div class="num">{mv['减持']}</div><div class="muted">减持</div></div>
<div class="stat"><div class="num">{north['coverage']['with_north']}</div><div class="muted">覆盖个股</div></div></div>
<div style="margin-top:10px">{table(["代码", "北向持股", "环比变动", "行业"], rows)}</div>""",
                                f'季度慢变量 · 截至 {esc(north.get("latest_quarter", ""))}', NORTH_RULE,
                                collapsed=True, tab="证据库"))

    # 涨停全景
    reasons = {}
    hdirs = sorted((D / "hithink").glob("2026-*"))
    if hdirs:
        pool = jload(hdirs[-1] / "limit_up_pool.json", {})
        for it in (pool or {}).get("data", {}).get("item", []):
            reasons[it.get("ticker", "")] = it.get("limit_up_reason", "")
    if reg and reg.get("boards"):
        rows = []
        for b in sorted(reg["boards"], key=lambda b: -b["cap"])[:10]:
            rsn = reasons.get(b["code"], "")
            rows.append([esc(b["code"]), esc(b["name"]), pct(b.get("pct")), f'{b["cap"]:.0f}亿',
                         f'<span class="muted">{esc(rsn)}</span>'])
        S["证据库"].append(card(f"涨停全景 · 市值前 10（{fmt_d(reg['date'])}）",
                                table(["代码", "名称", "涨幅", "市值", "涨停原因"], rows),
                                "周期仪全量扫描 + HiThink 题材归因", collapsed=True, tab="证据库"))

    # ══ 组装 ══
    # 打法库（2026-09-20 终版：全部过了池级+组合层+细分三审的规则链 + 证伪禁令墙）
    S["研究库"].insert(0, card("⚔️ 打法库 · 全规则链终版（2026-09-20 三审全过）", f"""
<table><thead><tr><th>打法</th><th>扳机</th><th>买/卖</th><th>8年验证</th><th>频率</th></tr></thead><tbody>
<tr><td><b>X3 恐慌狙击</b></td><td>恐慌期streak≥2+大簇日+非周一</td><td>浅跌前3次日开盘 / T+5或-12%</td><td><span class="up">58%胜 · 盈亏比2.09 · +37.5% · MDD-7.1%</span></td><td>~12次/年</td></tr>
<tr><td><b>X2 收益王</b></td><td>妖股/恐慌期+大簇日</td><td>同上</td><td><span class="up">54%胜 · +51.4% · MDD-6.9%</span></td><td>~26次/年</td></tr>
<tr><td><b>T1-MEGA v2 巨簇分散</b></td><td>缺口低簇≥20（任意regime，妖股/恐慌全仓平淡/主线半仓）</td><td>量比前10次日开盘 / T+3收盘</td><td><span class="up">组合层+107%（+53,661元/5万）· 55%胜</span></td><td>~6-15次/年</td></tr>
<tr><td><b>J5 平衡版</b></td><td>妖股/恐慌期+恐慌streak≥2</td><td>浅跌前3 / T+5或-12%</td><td><span class="up">48%胜 · +42.6% · MDD-19.7% · 大市值格68%最肥</span></td><td>~40次/年</td></tr>
<tr><td><b>红利底仓+网格做T</b></td><td>5只股息锚在买入区（常备）</td><td>底仓不动；±1.5%网格10%库存股T</td><td><span class="up">底仓~15%/年 + 做T增强3~6%/年（江苏银行实测24.2%）</span></td><td>每日</td></tr>
</tbody></table>
<div class="rule" style="margin-top:10px">🚫 证伪禁令墙（全有统计背书，勿复活）：打板/排队（G7死刑+当周8触发7亏）· 高位板块异动追（t=-4.3）· 妖股断魂刀（-6.94%期望）·
缺口低机械T+1高频（-57%）· 盘中轮动追龙头（封板速度差）· 底部板块起色买篮子（纯beta零超额）· 启动前夜预测（信息不可见）。</div>
<div class="muted" style="margin-top:6px">剂量定律：「簇规模」是反转族总开关（日簇≥20 = 77%/+2.73%，1-3只 = 42%/-0.27%）· 梯队≥3 = 日级信号唯一活的选择器（恐慌期×梯队 T+3 81%/+6.59%）·
选票方向：距60日高点最近者优先（恐慌中的相对强度）· 全部规则待影子盘前向判决，历史数字按乐观版理解。</div>""",
                                "X3/X2/T1-MEGA/J5/红利做T + 禁令墙", collapsed=False, tab="研究库"))

    body = "\n".join(h for tab in ("今日", "我的钱", "研究库", "证据库") for h in S[tab])
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    # B 架构（2026-09-20）：数据/渲染分离——面板=静态壳+dashboard.json，60s自刷新，数据更新无需重建HTML
    dash = {"built_at": stamp, "sig_date": sig_date, "sig_fmt": fmt_d(sig_date),
            "buy_day": buy_day, "buy_fmt": fmt_d(buy_day),
            "tabs": ["今日", "我的钱", "研究库", "证据库"],
            "cards": [{"tab": tab, "html": h} for tab in ("今日", "我的钱", "研究库", "证据库") for h in S[tab]]}
    (OUT.parent / "dashboard.json").write_text(json.dumps(dash, ensure_ascii=False))
    if "--legacy" in __import__("sys").argv:
        OUT.write_text(TPL.replace("__DATE__", today).replace("__BODY__", body)
                       .replace("__STAMP__", stamp)
                       .replace("__SIG__", fmt_d(sig_date)).replace("__BUYDAY__", fmt_d(buy_day)))

    # ops-state.json（人机共用单一事实源）
    ops = {
        "version": 2,
        "built_at": stamp,
        "sig_date": sig_date, "buy_day": buy_day, "sell_day": sell_day,
        "regime": reg and {"date": reg["date"], "regime": reg["regime"], "limit_ups": reg["stats"]["limit_ups"],
                            "limit_downs": reg["stats"]["limit_downs"]},
        "deep_low": [{"code": c, "name": nm, "pct": round(p, 2)} for c, p, nm in _deep[:5]],
        "focus": [{"src": "🎯观察池临启动", "target": f'{e["name"]}({e["code"]})',
                   "info": f'第{e["days"]}天 · 量比{e["volratio"]}x' + (" · 缩量持稳" if e.get("shrink") else ""),
                   "window": "梯队≥3涨停+自身首板=触发"} for e in lin],
        "positions_alert": [{"code": p["code"], "name": p["name"],
                             "flags": [re.sub(r"<[^>]+>", "", f0) for f0 in flags]}
                            for p, price, chg, flags in pos_flags if flags],
        "shadow_t1": t1 if t1_alive else None,
        "b5": {"date": b5_date, "sealed": b5_am, "unsealed": b5_open},
        "playbook": "playbook-202609.md",
        "kill_lines": {"countercrowd_board": "平淡/恐慌期 fillable 影子 20 交易日均值<0 → 进攻仓归零",
                       "dividend_anchor": "买入区滚动胜率跌破对照 → 降级复审"},
        "links": {"panel": "https://tebio.github.io/fenjue/", "ops_state": "https://tebio.github.io/fenjue/ops-state.json"},
    }
    (OUT.parent / "ops-state.json").write_text(json.dumps(ops, ensure_ascii=False, indent=1))
    print(f"built {OUT.parent / 'dashboard.json'} cards={len(dash['cards'])}（渲染壳=docs/index.html 静态，--legacy 才写整页）")


TPL = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache,no-store,must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<title>焚诀操作台</title>
<style>
:root{--text:#37352f;--muted:#9b9a97;--bg:#fff;--divider:#ededeb;--soft:#f7f6f3}
*{margin:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font:15px/1.7 ui-sans-serif,-apple-system,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;font-variant-numeric:tabular-nums}
.wrap{max-width:820px;margin:0 auto;padding:40px 18px 80px}
h1{font-size:24px;font-weight:700;letter-spacing:.5px}
.sub{color:var(--muted);font-size:13px;margin-top:4px}
.card{margin-top:26px}
h2{font-size:16px;font-weight:700;padding-bottom:8px;border-bottom:1px solid var(--divider);margin-bottom:12px}
h3{font-size:15px}
.hint{float:right;font-size:11px;font-weight:400;color:var(--muted);margin-top:3px}
.rule{background:var(--soft);border-radius:6px;padding:10px 14px;font-size:12.5px;color:#6b6b66;margin-bottom:12px;line-height:1.7}
.statrow{display:flex;gap:36px;align-items:flex-start;flex-wrap:wrap}
.big{font-size:17px}
.num{font-size:22px;font-weight:600}
.muted{color:var(--muted);font-size:12.5px}
.small{font-size:12px;color:var(--muted)}
.badge{display:inline-block;padding:2px 10px;border-radius:4px;font-size:13px;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--muted);font-weight:500;font-size:12px;padding:4px 8px 4px 0;border-bottom:1px solid var(--divider);white-space:nowrap}
td{padding:6px 8px 6px 0;border-bottom:1px solid var(--divider);vertical-align:top}
tr:last-child td{border-bottom:none}
details.card summary{font-size:15px;font-weight:600;padding-bottom:8px;border-bottom:1px solid var(--divider);cursor:pointer;list-style:none}
details.card summary::before{content:"▸ ";color:var(--muted)}
details.card[open] summary::before{content:"▾ "}
details.card .cardbody{padding-top:12px}
.tabbar{display:flex;gap:6px;margin-top:16px;position:sticky;top:0;background:var(--bg);padding:10px 0;z-index:9;border-bottom:1px solid var(--divider)}
.tabbtn{border:1px solid var(--divider);background:var(--soft);color:var(--muted);border-radius:8px;padding:8px 14px;font-size:14px;cursor:pointer;font-weight:500;font-family:inherit}
.tabbtn.active{background:var(--text);color:#fff;border-color:var(--text)}
.card[data-tab]{display:none}
.card[data-tab].showtab{display:block}
.up{color:#c0392b}.dn{color:#0f7b3d}.ok{color:#0f7b3d;font-size:12px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:10px 0}
.kpi{border:1px solid var(--divider);border-radius:10px;padding:11px 13px}
.kpi-head{display:flex;justify-content:space-between;align-items:center;gap:6px}
.kpi-name{font-weight:600;font-size:13px}
.pill{font-size:11px;padding:1px 8px;border-radius:20px;font-weight:600;flex:none}
.pill.ok{background:#e7f4ea;color:#1e7e34}
.pill.wp{background:#fdf3e3;color:#9a6b1a}
.kpi-big{font-size:21px;font-weight:800;margin-top:3px}
.kpi-big small{font-size:11px;font-weight:400;color:var(--muted)}
.kpi-line{font-size:11.5px;color:#73726e;margin-top:3px;line-height:1.5}
.callout{display:flex;gap:11px;border-radius:8px;padding:11px 15px;margin:9px 0;font-size:13.5px;line-height:1.7}
.callout .ic{flex:none}
.c-gray{background:var(--soft)}
.c-yellow{background:#fdf3e0}
.c-red{background:#fdeceb}
.c-green{background:#edf5ee}
.step{display:flex;gap:12px;margin:11px 0}
.step .no{flex:none;width:24px;height:24px;border-radius:50%;font-size:13px;font-weight:700;display:flex;align-items:center;justify-content:center;margin-top:3px}
.step .t{font-weight:600;font-size:14.5px}
.step .d{font-size:13px;color:#5c5a55}
.tag{display:inline-block;font-size:11px;padding:0 7px;border-radius:4px;background:var(--soft);color:#73726e}
.foot{margin-top:44px;padding-top:16px;border-top:1px solid var(--divider);color:var(--muted);font-size:12px;line-height:1.8}
</style></head><body><div class="wrap">
<h1>焚诀操作台</h1>
<div class="sub">数据截至 __SIG__收盘 · 执行日 __BUYDAY__ · 构建于 __STAMP__ · <span id="cd">…</span> · <span id="livepulse" style="color:#c0392b"></span></div>
<div class="tabbar" id="tabbar">
<button class="tabbtn active" data-tab="今日">📋 今日</button>
<button class="tabbtn" data-tab="我的钱">💰 我的钱</button>
<button class="tabbtn" data-tab="研究库">🔬 研究库</button>
<button class="tabbtn" data-tab="证据库">🗂️ 证据库</button>
</div>
__BODY__
<div class="foot">焚诀 Research Engine · 交易日自动重建：09:40 竞价后 / 10:40 雷达后 / 13:35 午后 / 14:50 尾盘 / 15:20 收盘快报 / 15:50 反转名单 / 16:15 委托单后 / 19:20 晚间 / 20:40 数据齐<br>
非交易日不重建（显示最近交易日数据，版块日期戳为准）· 红涨绿跌 · 胜率均值均为净口径（扣 0.15% 费用）· 所有策略结论带作废条件与 kill 线 · 研究辅助，不是买卖指令</div>
</div>
<script>
(function(){
var TABS=["今日","我的钱","研究库","证据库"];
var btns=document.querySelectorAll(".tabbtn");
function show(tab){
  if(TABS.indexOf(tab)<0)tab="今日";
  document.querySelectorAll(".card[data-tab]").forEach(function(c){
    c.classList.toggle("showtab", c.getAttribute("data-tab")===tab);
  });
  btns.forEach(function(b){b.classList.toggle("active", b.getAttribute("data-tab")===tab);});
  try{localStorage.setItem("fj_tab",tab);}catch(e){}
}
btns.forEach(function(b){b.onclick=function(){show(b.getAttribute("data-tab"));};});
var saved=null;try{saved=localStorage.getItem("fj_tab");}catch(e){}
show(saved||"今日");
// ── 更新倒计时（槽位与 cron 表逐一对齐，改表必改这里）──
var SLOTS=["09:40","10:40","13:35","14:50","15:20","15:50","16:15","19:20","20:40"];
function next(){
  var n=new Date();
  for(var d=0;d<8;d++){
    var t=new Date(n.getFullYear(),n.getMonth(),n.getDate()+d);
    var wd=t.getDay();
    if(wd===0||wd===6)continue;
    for(var i=0;i<SLOTS.length;i++){
      var p=SLOTS[i].split(":");
      var s=new Date(t.getFullYear(),t.getMonth(),t.getDate(),+p[0],+p[1]);
      if(s>n)return s;
    }
  }
  return null;
}
function tick(){
  var s=next(),el=document.getElementById("cd");
  if(!s){el.textContent="下次更新未知";return;}
  var ms=s-new Date(),h=Math.floor(ms/36e5),m=Math.ceil(ms%36e5/6e4);
  el.textContent="下次更新 "+(s.getHours()<10?"0":"")+s.getHours()+":"+(s.getMinutes()<10?"0":"")+s.getMinutes()+
    (h>0?"（"+h+"小时"+m+"分后）":"（"+m+"分钟后）");
}
tick();setInterval(tick,30000);
// ── 盘中自动刷新：交易日 9:25-15:10 BJT 每 3 分钟重载 ──
function bjt(){var n=new Date();return new Date(n.getTime()+(n.getTimezoneOffset()+480)*60000);}
var b=bjt(),wd=b.getDay(),hh=b.getHours()*60+b.getMinutes();
if(wd>=1&&wd<=5&&hh>=565&&hh<=910){setTimeout(function(){location.reload();},180000);}
// ── 实时报价（JSONP 注入 qt.gtimg.cn，静态页免跨域）──
(function(){
var nodes=document.querySelectorAll("[data-q]");
if(!nodes.length)return;
var codes=[];nodes.forEach(function(n){var c=n.getAttribute("data-q");if(codes.indexOf(c)<0)codes.push(c);});
var b3=bjt(),w3=b3.getDay(),m3=b3.getHours()*60+b3.getMinutes();
var live=(w3>=1&&w3<=5&&m3>=555&&m3<=905); // 9:15-15:05 BJT
function paint(){
  var s=document.createElement("script");
  s.src="https://qt.gtimg.cn/q="+codes.join(",")+"&_="+Date.now();
  s.onload=function(){
    codes.forEach(function(c){
      var v=window["v_"+c];if(!v)return;
      var f=v.split("~");if(f.length<33)return;
      var price=parseFloat(f[3]),prev=parseFloat(f[4]);
      if(!(price>0)||!(prev>0))return;
      var r=(price/prev-1)*100;
      document.querySelectorAll('[data-q="'+c+'"]').forEach(function(n){
        var k=n.getAttribute("data-f");
        if(k==="p")n.textContent=price.toFixed(2);
        else if(k==="r"){var cls=r>0?"up":r<0?"dn":"muted";
          n.innerHTML='<span class="'+cls+'">'+(r>0?"+":"")+r.toFixed(2)+"%</span>";}
        else if(k==="z"){var buy=parseFloat(n.getAttribute("data-buy"));
          n.innerHTML=price<=buy?'<span class="up">🟢买入区内</span>':'<span class="muted">线上方'+((price/buy-1)*100).toFixed(1)+"%</span>";}
        else if(k==="j"){
          var j,jc;
          if(r>=9.7){j="🔥首板！挂涨停价排队";jc="up";}
          else if(r>=5){j="🟡冲板中（未封不追）";jc="up";}
          else if(r>=1.5){j="⚪跟风涨（非首板不买）";jc="muted";}
          else if(r>-1.5){j="⚪横盘蓄力（继续观察）";jc="muted";}
          else{j="🔴转弱（梯队热它跌=弱，别碰）";jc="dn";}
          n.innerHTML='<span class="'+jc+'" style="font-size:12px">'+j+"</span>";}
      });
    });
    var lp=document.getElementById("livepulse");
    if(lp){var n2=bjt();lp.textContent="实时 "+("0"+n2.getHours()).slice(-2)+":"+("0"+n2.getMinutes()).slice(-2)+":"+("0"+n2.getSeconds()).slice(-2);}
    s.remove();
  };
  s.onerror=function(){s.remove();};
  document.head.appendChild(s);
}
paint(); if(live)setInterval(paint,30000);
})();
(function(){
var el=document.getElementById("nownow");if(!el)return;
var b2=bjt(),w=b2.getDay(),m=b2.getHours()*60+b2.getMinutes();
var msg,color="#37352f";
if(w===0||w===6){msg="📴 今天不开市。不用操作，想看就翻翻「研究库」。";}
else if(m<565){msg="🌅 盘前：照「我的钱」页的银行委托单挂单。挂完收工。9:25 QQ 发作战单。";}
else if(m<572){msg="⏳ 竞价中：别动手，等 9:32 确认。";}
else if(m<585){msg="🟢 买入窗口（9:32-9:45）：行动单有票才买，没票=今天不买。";color="#c0392b";}
else if(m<630){msg="🪑 窗口已过。别追，等雷达班。";}
else if(m<885){msg="🪑 现在什么都不用干。QQ 不喊你=没事。盯盘不产生收益。";}
else if(m<900){msg="🔴 卖出窗口（14:45-15:00）：该卖的短线票现在卖，无论盈亏。";color="#0f7b3d";}
else if(m<940){msg="📊 收盘了。等 15:40 周期仪徽章，定明天仓位。";}
else{msg="🌙 晚间：看「我的钱」页委托单，下个交易日 9:25 前照挂即可。";}
el.textContent=msg;el.style.color=color;
})();
})();
</script>
</body></html>"""


if __name__ == "__main__":
    main()
