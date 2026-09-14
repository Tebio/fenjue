#!/usr/bin/env python3
"""engine/dashboard_build.py — 焚诀操作台静态面板构建（2026-09-12 v2）

v2 修订（用户裁决）：红涨绿跌（A股口径）；银行委托单结构化表格；
各版块补买点/卖点/作废/备注；北向加操作建议；涨停全景挂涨停原因（消息面）。
stdlib 零依赖；任一数据源缺失降级为「未生成」卡片，不崩。
"""
import json, html, re, datetime
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
D = ROOT / "data"
OUT = ROOT / "docs/index.html"

# ── 反转族操作规则（AGENTS.md #17/#35 实测口径）──
REV_RULE = ("买点：明日 9:32 竞价确认（剔一字跌停/高开超1/3抢跑）后开盘价买入——延迟入场单调烧钱，开盘即最优；"
            "卖点：T+1 尾盘（大涨未涨停当日尾盘兑现；涨停则拿隔夜、次日早盘卖——离场日开盘卖是全场最差）；"
            "作废：竞价被剔除或 9:40 前打回平盘。")
FRONT_RULE = ("买点：信号日盘中冲板/封板时打板（收盘前未封=不建仓）；"
              "卖点：次日早盘兑现（涨停隔夜 +2.11%/65.2% 实测）；"
              "作废：封板失败、次日低开破昨收、或板块梯队当日散掉（涨停<3只）。")
NORTH_RULE = ("季度慢变量，只当过滤器不当买点：北向增持+持仓浮盈=多拿一档的证据；"
              "北向减持+跌破关键位=减仓证据；单看北向买入=没有 edge（机构漂移已被闸门证伪）。")
# G5 实测（data/frontrun_fill_20260912.json，m60 封板结构）：9/11 五单中 4 只 10:30 前封死、
# 尾盘一封到底买不进；3/5 盘中有开缝=排队成交窗口。close-entry 口径乐观，实战=封板 bar 打板。
FILL_NOTE = (" fill 实测（m60）：9/11 五单 4 只早盘封死尾盘买不进，3/5 盘中有开缝——"
             "影子收益=纸面口径，实战须在封板 bar 排队，fill 率影子期继续定量。")


def jload(p, default=None):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def esc(s):
    return html.escape(str(s), quote=False)


def fetch_quotes(codes):
    """Sina 批量实时价（盘后=收盘价）。返回 {code: (price, pct)}。代理/直连双通道。"""
    import subprocess
    out = {}
    url = "https://hq.sinajs.cn/list=" + ",".join(("sh" if c.startswith("6") else "sz") + c for c in codes)
    for env in (None, {"PATH": "/usr/bin:/bin"}):  # None=继承代理；裸 PATH=直连兜底
        try:
            r = subprocess.run(["curl", "-sL", "--max-time", "15",
                                "-H", "Referer: https://finance.sina.com.cn/", url],
                               capture_output=True, env=env)
            text = r.stdout.decode("gb18030", errors="ignore")
            import re as _re
            for mcode, payload in _re.findall(r'hq_str_(?:sh|sz)(\d{6})="([^"]*)"', text):
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


def card(title, inner, hint="", rule="", collapsed=False):
    """collapsed=True → 证据库卡片默认折叠（<details>），减瀑布流信息冗余（2026-09-14 用户裁决）。
    tab 由标题前缀自动归组（2026-09-14 用户裁决：切换菜单替代瀑布流）。"""
    h = f'<span class="hint">{esc(hint)}</span>' if hint else ""
    r = f'<div class="rule">{esc(rule)}</div>' if rule else ""
    tab = "证据库" if collapsed else "作战"
    for prefix, t2 in _TABMAP:
        if title.startswith(prefix):
            tab = t2
            break
    if collapsed:
        return (f'<details class="card" data-tab="{tab}"><summary>{esc(title)}{h}</summary>'
                f'<div class="cardbody">{r}{inner}</div></details>')
    return f'<section class="card" data-tab="{tab}"><h2>{esc(title)}{h}</h2>{r}{inner}</section>'


_TABMAP = [
    ("市场状态", "作战"), ("🎯 作战手册", "作战"), ("📌 今日焦点", "作战"),
    ("🥇 明日首选", "作战"), ("⚡ B5", "作战"), ("📲 怎么配合", "作战"),
    ("持仓哨兵", "持仓"), ("股息锚", "持仓"), ("银行股", "持仓"), ("银行 ·", "持仓"),
    ("收割型席位", "持仓"),
    ("📋 策略分工", "候选池"),
    ("放量异动观察池", "候选池"), ("首板抢跑", "候选池"), ("反转族", "候选池"),
]
_TABS = ["作战", "持仓", "候选池", "证据库"]


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
    r"买≤([\d.]+) 加≤([\d.]+) 卖([\d.]+) 清≥([\d.]+) \| 距买入(\S+?) MA20 ([\d.]+)\(([^)]*)\)(📌贴线)?")
ORDER_LINE = re.compile(
    r"^(\S+?)\s*(?:📌贴线)?\s*\[(\S+?)\]\s*买([\d.]+)/加([\d.]+)/([\d.]+)/5%线([\d.]+)\s*卖([\d.]+)\s*清([\d.]+)")


def deep_low_scan():
    """深档低位（≤-9.5% 且 MA60下）全库扫描。返回 (最近交易日, [(code, pct), ...])。
    2026-09-14：首选层0+策略总览共用，只扫一次。"""
    import glob as _g
    try:
        names = {str(s["code"]).zfill(6): s.get("name", "")
                 for s in json.loads((D / "main_board_codes.json").read_text())["stocks"]}
        idx = json.loads((D / "big_kcache" / "000001.json").read_text())
        lastd = idx[-1]["date"]
        # 2026-09-14: 合并收盘快报覆盖层（15:10 新浪快照），让深档扫描盘后立即可用
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
                        out.append((c0, p0, names.get(c0, "")))
            except Exception:
                continue
        return lastd, sorted(out, key=lambda x: x[1])
    except Exception:
        return None, []


def parse_bank(text):
    rows, orders = [], []
    for line in text.splitlines():
        line = line.strip()
        m = BANK_LINE.match(line)
        if m:
            (name, code, price, chg, dy, pb, zone, buy, add, sell, clear,
             dist, ma20, mad, pin) = m.groups()
            zcls = "up" if "买入区" in zone else "muted" if "持有区" in zone else "dn"
            rows.append([f"{esc(name)}<br><span class='muted'>{code}</span>",
                         f"{price}<br>{pct(chg)}", f"{dy}%", pb,
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


def main():
    today = datetime.date.today().isoformat()
    secs = []
    # ── 每日操作时间表（2026-09-14 用户令：80岁老人也能看懂的显眼窗口期标注）──
    secs.insert(0, card("🕐 现在该干嘛",
                        """<div id="nownow" style="font-size:19px;font-weight:700;padding:14px 16px;background:var(--soft);border-radius:8px;line-height:1.6">读取当前时间…</div>
<table style="margin-top:12px"><tr><th>时间</th><th>动作（每天就这几件事）</th></tr>
<tr><td>9:25 前</td><td>照「持仓」页的银行委托单挂单。挂完就不用管了</td></tr>
<tr><td>9:32</td><td>看 QQ 确认单：说"作废"今天就别买；说"可执行"才进下一步</td></tr>
<tr><td>9:32–9:45</td><td><b>买入窗口（每天唯一）</b>：首选卡里有票才买，没票=今天不买。9:45 后一律不追</td></tr>
<tr><td>10:30</td><td>看 QQ 雷达：喊"梯队成型/冲板"才动手，没喊=继续休息</td></tr>
<tr><td>10:30–14:45</td><td><b>什么都不干</b>。QQ 不喊就是没事</td></tr>
<tr><td>14:45–15:00</td><td><b>卖出窗口</b>：昨天买的短线票，这个时间卖掉（无论盈亏）</td></tr>
<tr><td>15:40 后</td><td>看这页"市场状态"徽章，定明天仓位；晚上看委托单</td></tr></table>
<div style="margin-top:10px"><b>📲 QQ 什么时候会喊你（不用自己盯）</b>
<table><tr><th>触发</th><th>什么时候</th></tr>
<tr><td>反转族确认单（能买/作废）</td><td>每交易日 9:32 准点</td></tr>
<tr><td>雷达（冲板候选+梯队成型+持仓破位）</td><td>10:30 / 13:35 / 14:45 三班</td></tr>
<tr><td>梯队成型（观察池票的板块≥3只涨停）</td><td>雷达班次里顺带报</td></tr>
<tr><td>持仓破关键位 ⚠️</td><td>雷达班次里顺带报</td></tr>
<tr><td>周期仪（明天仓位规则）</td><td>15:40</td></tr>
<tr><td>银行委托单+影子回填</td><td>16:05 / 19:00 后</td></tr></table></div>""",
                        "规则只有三条：买入只在 9:32-9:45、卖出只在尾盘、其余时间不操作",
                        "为什么：延迟买入每小时烧掉 0.2% 收益（实测）；开盘卖是全场最差卖点（实测）；"
                        "盘中盯盘不产生收益只产生冲动。QQ 会主动喊你，不用你盯。"))
    _deep_lastd, _deep = deep_low_scan()  # 策略总览+首选层0共用（只扫一次）
    wp = jload(D / "watch_pool.json", {})          # 策略总览+观察池卡共用
    rev = jload(D / "reversal_list.json", {})      # 策略总览+首选层2+反转卡共用
    reg = None
    rl = D / "regime_log.jsonl"
    if rl.exists():
        lines = rl.read_text().strip().splitlines()
        if lines:
            reg = json.loads(lines[-1])
    if reg:
        st = reg["stats"]
        secs.append(card(f"市场状态 · {reg['date']}（最近交易日）" if reg["date"] != today else "市场状态 · 今日", f"""
<div class="statrow"><div><div class="big">{badge_regime(reg['regime'])}</div>
<div class="muted">周期仪 · {esc(reg['date'])}</div></div>
<div class="stat"><div class="num">{st['limit_ups']}<span class="muted"> / {st['limit_downs']}</span></div><div class="muted">涨停 / 跌停</div></div>
<div class="stat"><div class="num">{pct(st['index_pct'])}</div><div class="muted">指数</div></div></div>
<div class="muted" style="margin-top:10px">主线板块：{"、".join(f"{esc(n)}({c})" for n, c in st["top_sectors"][:4])}</div>""",
                         "每日 15:40 盘后扫描"))
    focus_rows = []  # G7 焦点区：(来源, 标的, 信息, 启动窗口)
    # ── 持仓哨兵（G2）──
    watch = jload(ROOT / "config/watchlist.json", {})
    if watch and watch.get("positions"):
        codes = [p["code"] for p in watch["positions"]] + [a["code"] for a in watch.get("anchors", [])]
        q = fetch_quotes(codes)
        # K3修（2026-09-14 盘前）：sina 9:15 前返回空 → 哨兵/锚卡消失。缺报价的票用 kcache 昨收顶上。
        for c in codes:
            if c not in q:
                kf = D / "big_kcache" / f"{c}.json"
                try:
                    ks = json.loads(kf.read_text())
                    q[c] = (ks[-1]["close"], (ks[-1]["close"] / ks[-2]["close"] - 1) * 100)
                except Exception:
                    pass
        rows = []
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
            _mk = ("sh" if p["code"].startswith("6") else "sz") + p["code"]
            rows.append([f"{esc(p['name'])}<br><span class='muted'>{p['code']}</span>",
                         f'<span data-q="{_mk}" data-f="p">{price:.2f}</span>',
                         f'<span data-q="{_mk}" data-f="r">{pct(chg)}</span>',
                         f'<span class="muted">{esc(p["note"])}</span>',
                         " ".join(flags) or '<span class="muted">区间内</span>'])
            if any("⚠️破" in f0 for f0 in flags):
                focus_rows.append(("⚠️持仓破位", f"{esc(p['name'])}({p['code']})",
                                   " ".join(flags), "立即检查纪律 · 假突破收不回5日-0.53%实测"))
        if rows:
            secs.append(card("持仓哨兵", table(["标的", "现价", "今日", "备注", "关键位"], rows),
                             "config/watchlist.json · 越线自动标记"))
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
            secs.append(card("股息锚买入区", table(["标的", "现价", "买入线", "状态"], arows),
                             "现价≤线=可建仓/加仓"))
    # ── 候选池总览（2026-09-14 用户令：按策略分开+标胜率+每策略≤3只，小学生可读）──
    try:
        ov = []
        # 深档低位（层0扫描结果 _deep 可能存在）
        n_deep = len(_deep)
        ov.append(["🥇 深档低位", "57.6%", "🟢健康",
                   f"今日 {n_deep} 只" if n_deep else "今日无（没大跌日就没票）",
                   "大跌次日开盘买，后天尾盘卖"])
        lin_n = len([e for e in (wp or {}).get("pool", []) if 1 <= e.get("days", 0) <= 5]) if wp else 0
        ov.append(["🏗️ 观察池临启动", "58.9%", "🟢健康",
                   f"{lin_n} 只在窗口期（页面上只列前 3）" if lin_n else "今日无",
                   "等它首板+板块 3 只涨停才买，雷达会喊"])
        ov.append(["⚡ B5 半路板", "56.9%", "🟢健康",
                   "触发制：盘中冲 +6% 才算信号", "只在平淡/恐慌期，10:30/14:45 雷达喊"])
        n_rev = len(rev.get("candidates", [])) if rev else 0
        ov.append(["🔄 反转族", "49.8%", "🟡重症监护",
                   f"{n_rev} 只（胜率没过 50% 红线，不主动推）", "最近一年 edge 贴线，降级观察"])
        secs.append(card("📋 策略分工一览 · 每个策略每天最多盯 3 只",
                         table(["策略", "胜率", "状态", "今日", "怎么用它（一句话）"], ov),
                         "胜率=8 年实测净口径 · 🟢=可动手 🟡=只看不动",
                         "纪律：同一时刻只执行一个策略的信号；都没信号=今天空仓休息，空仓也是操作。"))
    except Exception:
        pass
    # ── 观察池（G1）──（wp 已在 main() 开头预载）
    if wp and wp.get("pool"):
        # K3修（2026-09-14 用户抓包）：池内票没标板块，梯队无从盯起——挂 HiThink 板块映射
        _secmap = {}
        try:
            import glob as _g
            _sm = json.loads(open(sorted(_g.glob(str(D / "hithink/sectors/stock_sectors_*.json")))[-1]).read())
            _STOP = {"融资融券", "深股通", "沪股通", "国企改革", "次新股", "ST股"}
            for c0, arr in _sm.items():
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
                                 [_wrow(e) for e in _pool_sorted[3:]]) + '</details>', "", "", "", "", "", "", "", ""])
        # G7 焦点：临启动票（第1-5天=窗口期；中位2日/71.6%≤3日毕业，实测分布）；上限8条防爆版
        for e in sorted((e for e in wp["pool"] if 1 <= e.get("days", 0) <= 5),
                        key=lambda e: (e["days"], -e["volratio"]))[:8]:
            win = ("🔥高发窗口" if e["days"] <= 3 else "窗口尾（第4-5天）")
            sec_tag = _secmap.get(str(e["code"]).zfill(6), "")
            focus_rows.append(("🎯观察池临启动", f"{esc(e['name'])}({e['code']})",
                               f'量比{e["volratio"]}x · 第{e["days"]}天 · {esc(sec_tag)}' + (" · 缩量持稳" if e.get("shrink") else ""),
                               win + ' · 梯队+首板=抢跑口径+1.79%/58.9%'))
        hint = f'{esc(wp.get("updated", ""))} · 放量未板+缩量横盘不破=启动前形态（002519 原型）'
        secs.append(card("放量异动观察池", table(["代码", "名称", "板块", "入池", "量比", "当日", "天数", "状态", "现在"], rows),
                         hint,
                         "用法：量比大≠好——放量只是入池门票（异动2.4x基率），真正加分项是入池后缩量持稳；"
                         "该票板块当日≥3只涨停=梯队成型，雷达10:30/14:45会在QQ单独提醒；破入池日前低=出局。"))
    # ── 银行委托单（表格化）──
    bf = D / "bank_console_latest.txt"
    if bf.exists():
        import os as _os
        _bt = datetime.datetime.fromtimestamp(_os.path.getmtime(bf)).strftime("%m-%d %H:%M")
        rows, orders = parse_bank(bf.read_text())
        if rows:
            secs.append(card("银行股操作台", table(
                ["标的", "现价", "息率", "PB", "状态", "买入线", "卖出线", "清仓线", "距买入"], rows),
                f"股息率锚 · 样本外 60.1% 胜率 · 生成于 {_bt}（价格线仅分红/财报后调整，跨日仍有效）",
                "规则：买入区=可建仓/加仓（阶梯挂单 买线/-4%/-8%）；卖出区=减仓不清仓；清仓区=清仓离场。价格线不随日内波动。"))
        if orders:
            secs.append(card("银行 · 委托单", table(
                ["标的", "操作", "买入", "加仓阶梯", "卖出", "清仓"], orders),
                f"生成于 {_bt} · 价格线在下个交易日 16:05 重建前持续有效，盘前照抄挂单即可"))
    # ── frontrun 影子 ──
    fr = []
    sf = D / "claims_shadow.jsonl"
    if sf.exists():
        for line in sf.read_text().splitlines():
            r = json.loads(line)
            if r["claim"] == "FRONTRUN_FIRSTBOARD_V2":
                fr.append(r)
    if fr:
        # K3修（2026-09-14 用户抓包）：抢跑表只有代码没名称——补名称映射
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
                rows.append([f'<span class="muted">{esc(dt)}</span>',
                             f'{esc(_names.get(r["code"], ""))}<br><span class="muted">{esc(r["code"])}</span>',
                             pct(r["r1"] * 100 if r["r1"] is not None else None),
                             pct(r["r5"] * 100 if r["r5"] is not None else None),
                             '<span class="muted">未成交</span>' if r.get("untradeable") else (
                                 '<span class="ok">在车上</span>' if r["entry"] else '<span class="muted">待回填</span>')])
        secs.append(card("首板抢跑 · 影子名单", table(["信号日", "标的", "T+1", "T+5", "状态"], rows),
                         "首板+板块梯队≥3+市值20-400亿 · 测量级通过 影子验证中", FRONT_RULE + FILL_NOTE))
        latest_dt = max(by_date) if by_date else None
        if latest_dt:
            for r in by_date[latest_dt]:
                focus_rows.append(("🚀首板抢跑", f'{esc(_names.get(r["code"], ""))}({esc(r["code"])})', "封板 bar 排队打板（开盘追-0.52%已证伪）",
                                   f"{latest_dt} 已封板 · 隔夜+2.11%/65.2%"))
    # ── 明日首选（2026-09-14 用户令：页面要显示"如果是我，最可能买哪只"）──
    # 2026-09-14 盘中用户裁决（实锤）：①胜率<50%的主张不进首选卡（反转族T+1=49.8%且滚动edge贴线+0.02pp→降级观察，不再当头条）；
    # ②首选排序按主张健康度：B5(56.9% submit 6/6)>抢跑(58.9% 四regime全正)>观察池临启动>反转族(重症监护)。
    pick_rows = []
    _claims_state = jload(D / "claims_state.json", {})
    _rev_r = None
    try:  # claims_state 结构：history[-1].verdicts["1"][0] = 滚动250日边际贡献(pp)
        _rev_r = _claims_state["REVERSAL_OPEN_T1"]["history"][-1]["verdicts"]["1"][0]
    except Exception:
        pass
    _rev_sick = _rev_r is None or _rev_r < 0.05  # 滚动边际<0.05pp=贴线重症（无数据按重症处理，宁缺勿推）
    # 首选层0：深档低位（LIMITDOWN_NEXT_DAY L2+ 57.6% 健康主张）——main() 开头 deep_low_scan() 已扫
    # 2026-09-14 实锤教训：宏盛股份(周五-9.9%唯一低位)今早涨停，但旧预筛从 reversal_list 按成交额截前60把它切掉了。
    if _deep:
        rows_d = [[f'{esc(nm)}<br><span class="muted">{c0}</span>',
                   pct(p0), '<span class="up">MA60下✓</span>',
                   '<span class="muted">跌停接L2+ +2.65%/57.6%（剔一字后）</span>',
                   "竞价一字跌停=作废；封死板买不进则放弃",
                   f'<span data-q="{("sh" if c0.startswith("6") else "sz")+c0}" data-f="r"><span class="muted">…</span></span>']
                  for c0, p0, nm in _deep[:3]]
        secs.append(card("🥇 首选 · 深档低位（胜率57.6% · 跌停接）",
                         table(["标的", "昨跌幅", "位置", "历史口径", "作废条件", "现在"], rows_d),
                         f"{_deep_lastd} 深档≤-9.5%全扫 · 只留MA60下（高位断板大面已剔除）",
                         "这是全库扫描不是名单切片——9/14 宏盛股份涨停就是这条的命中。"
                         "买点=次日开盘（竞价确认非一字），T+1尾盘兑现。"))
    # 首选层1：观察池临启动（缩量持稳优先，触发=梯队≥3涨停+首板，雷达10:30/14:45推送）
    if wp and wp.get("pool"):
        lin = sorted((e for e in wp["pool"] if 1 <= e.get("days", 0) <= 5),
                     key=lambda e: (not e.get("shrink"), e["days"], -e["volratio"]))[:3]
        for e in lin:
            _mk = ("sh" if str(e["code"]).startswith("6") else "sz") + str(e["code"]).zfill(6)
            pick_rows.append([f"{esc(e['name'])}<br><span class='muted'>{e['code']}</span>",
                              f'<span data-q="{_mk}" data-f="r"><span class="muted">…</span></span>'
                              f'<br><span data-q="{_mk}" data-f="j"></span>',
                              f'第{e["days"]}天 · 量比{e["volratio"]}x' + (" · 缩量持稳" if e.get("shrink") else ""),
                              "梯队≥3涨停+自身首板=触发；破入池前低=作废"])
    if pick_rows:
        secs.append(card("🥇 首选 · 观察池临启动（胜率58.9% · 触发制）",
                         table(["标的", "现在（30秒刷新）", "池内状态", "触发/作废"], pick_rows),
                         "排序=缩量持稳>天数>量比 · 梯队成型雷达会QQ推送",
                         "⚠️ 合法买点只有一种：它今天涨停（且它板块≥3只涨停）→ 挂涨停价排队。"
                         "红了2-5%没涨停=跟风，不买；绿了=转弱，不买；跌了=更不是抄底，不买。"
                         "任何其它价位买=无信号操作。58.9%是历史口径（封死板买不进有水分），"
                         "实战 edge 介于 +1.79% 与 -0.52% 之间。"))
    # 首选层2：反转族预筛（仅当主张健康；贴线期降级为观察注释——用户规则：胜率<50%不推）
    pick_rows = []  # 防串行：层1的池子行数列数不同，重置
    if rev and rev.get("candidates") and not _rev_sick:
        pre = []
        for c in rev["candidates"][:60]:  # 深度前60逐一算位置（建页离线，成本可接受）
            kf = D / "big_kcache" / f'{c["code"]}.json'
            if not kf.exists():
                continue
            try:
                ks = json.loads(kf.read_text())
                if len(ks) < 61 or ks[-1]["date"] != rev.get("date"):
                    continue
                ma60 = sum(k["close"] for k in ks[-60:]) / 60
                below = ks[-1]["close"] < ma60
                depth = c["close_chg"]
                band = ("≤-9.5%" if depth <= -9.5 else "-7~-9.5%" if depth <= -7 else
                        "-5~-7%" if depth <= -5 else "-3~-5%")
                edge = {"≤-9.5%": "档均+1.10%", "-7~-9.5%": "档均+0.42%",
                        "-5~-7%": "档均+0.17%", "-3~-5%": "档均+0.03%"}[band]
                # 排序分：深档优先 + MA60下加分 + 流动性
                score = ({"≤-9.5%": 4, "-7~-9.5%": 3, "-5~-7%": 2, "-3~-5%": 1}[band]
                         + (2 if below else 0) + min(c.get("amt_yi", 0) / 20, 1))
                pre.append((score, c, band, edge, below))
            except Exception:
                continue
        for score, c, band, edge, below in sorted(pre, key=lambda x: -x[0])[:3]:
            pick_rows.append([f"{esc(c['name'])}<br><span class='muted'>{c['code']}</span>",
                              pct(c["close_chg"]), band,
                              '<span class="up">MA60下✓</span>' if below else '<span class="muted">MA60上</span>',
                              f'<span class="muted">{edge} · 净口径</span>',
                              "竞价剔一字/抢跑>1/3作废"])
        if pick_rows:
            secs.append(card("🥇 明日首选 · 规则排序预筛（非买卖指令）",
                             table(["标的", "今日", "深度档", "位置", "历史档口径", "作废条件"], pick_rows),
                             f'{esc(rev.get("date", ""))} 数据 · 反转族×位置×流动性三维排序',
                             "执行前提=明日 9:32 竞价确认通过（QQ会推确认结果）；开盘买→T+1尾盘卖；"
                             "深档若为高位断板大面（MA60上）降级观察。9:40 打回平盘=放弃。"))
    # B5 未封持仓处置提示
    if _rev_sick and rev and rev.get("candidates"):
        secs.append(card("🔄 反转族 · 重症监护中（不出首选）",
                         f'<div class="muted">滚动250日边际贡献 +{_rev_r:.2f}pp 贴线（健康线 0.05pp）· '
                         f'T+1 胜率 49.8% 未过 50% 用户规则线 · 名单仍在下方证据区可查，但体系当前不主动推它。</div>',
                         "2026-09-14 盘中用户裁决：胜率<50%或滚动edge贴线的主张降级为观察，不进首选",
                         "恢复条件：claims_audit 滚动边际回到 +0.05pp 以上。历史上它 +0.139%/46万样本是真的，"
                         "但最近一年近乎熄火——是真衰减还是风格期，影子盘继续量。"))
    try:
        blines = [json.loads(l) for l in open(D / "banlu_signals.jsonl") if l.strip()]
        if blines:
            lastd = blines[-1]["date"]
            uns = [b for b in blines if b["date"] == lastd and not b.get("sealed")]
            sealed = [b for b in blines if b["date"] == lastd and b.get("sealed")]
            rows_b = ([[f'{esc(b["name"])}({b["code"]})', "未封板",
                        '<span class="dn">开盘即走（断板即跑铁律）</span>'] for b in uns]
                      + [[f'{esc(b["name"])}({b["code"]})', "封板在手",
                          '<span class="up">早盘兑现（隔夜+2.11%/65.2%实测）</span>'] for b in sealed])
            if rows_b:
                secs.append(card("⚡ B5 持仓处置",
                                 table(["标的", "状态", "动作"], rows_b),
                                 f"{lastd} 信号 · 反人群打板不留恋"))
    except Exception:
        pass
    # ── 反转族 ──（rev 已在 main() 开头预载）
    if rev and rev.get("candidates"):
        rows = [[esc(c["code"]), esc(c["name"]), pct(c["close_chg"]), f'{c["amt_yi"]:.0f}亿']
                for c in rev["candidates"][:8]]
        secs.append(card(f"反转族 · 待确认名单（{esc(rev.get("date", ""))} 收盘扫）", table(["代码", "名称", "当日跌幅", "成交额"], rows),
                         f'{esc(rev.get("date", ""))} 收盘扫描 · 外部复审 +0.139%/49.8% 净口径', REV_RULE))
        if not _rev_sick:  # ICU期不上焦点（用户红线：胜率<50%不推）
            for c in rev["candidates"][:3]:
                focus_rows.append(("🔄反转族", f"{esc(c['name'])}({c['code']})",
                                   f'昨{c["close_chg"]:.1f}% · 额{c["amt_yi"]:.0f}亿 · T+1净+0.139%/49.8%',
                                   "明日 9:32 竞价确认"))
    # ── 主张影子汇总 ──
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
    secs.append(card("主张影子表现",
                     table(["主张", "档", "T+1 均值/胜率", "T+5 均值/胜率", "n"], rows) if rows
                     else '<div class="muted">影子期积累中（2026-09-11 起，20 交易日见分晓）</div>',
                     "L5 前向验证 · kill 线滚动审计，不达标自动降级", collapsed=True))
    # ── 模拟盘锦标赛（G11）──
    tour = jload(D / "sim_tournament_20260912.json", {})
    audit = jload(D / "sim_audit_20260912.json", {})
    if tour and tour.get("strategies"):
        NAMES = {"reversal": "🔄 反转/跌停接（每日最深3只）❌已枪毙", "scalp_overnight": "⚡ 短差（打板吃隔夜缺口）",
                 "short_optimized": "🚀 打板优化（涨停隔夜次早卖）", "short_t1": "📅 短线（打板次日尾盘）",
                 "dividend_hold": "💰 股息躺平", "dividend_t": "🔁 股息做T",
                 "long_trend": "📈 长线（金叉/破年线次早卖）", "long_optimized": "📈 长线优化（破位当日尾盘卖）",
                 "swing_t5": "🌊 波段（打板拿5天）"}
        rows = []
        for k, v in sorted(tour["strategies"].items(), key=lambda x: -x[1]["return%"]):
            rows.append([NAMES.get(k, k), pct(v["return%"]), f'{v["maxDD%"]}%',
                         f'{v["trades"]}笔/{v["win%"]}%' if v["trades"] else "拿死不动",
                         pct(v["avg%"]) if v["trades"] else '<span class="muted">—</span>'])
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
            slip += (f' 8年总决算：打板优化纸面均笔每年 +1.6~2.9% 八年全稳——信号 edge 没死；'
                     f'衰减在可成交层：fillable 子集 2024 +3.22%（强于纸面）→ 2026 -0.06%（远弱于纸面+1.79%），'
                     f'抢单竞争逐年恶化。8年证伪：长线金叉 -57~-63%、跌停接 -82%。')
        elif audit:
            tiers = audit.get("B_tiers", {})
            deep = tiers.get("≤-9.5", {})
            slip = (f'审计：收益引擎=跌停接子集（{deep.get("n")}笔 均{deep.get("avg%")}%），-5~-9.5%中间档为负期望。'
                    f'滑点：入场贵0.3%→权益{audit.get("D_slip0.003_equity")}x、贵0.5%→{audit.get("D_slip0.005_equity")}x（命门）。'
                    f'赔率{audit.get("E_payoff_ratio")}（均赢{audit.get("E_avg_win%")}%/均亏{audit.get("E_avg_loss%")}%）')
        # 分时代胜率表（2026-09-14 用户令：标注26年vs往年差异）
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
            name = k.split(" ", 1)[-1]
            era_rows.append([esc(name), f"{fw}%", f"{lw}%",
                             pct(l1.get("mean%")), trend])
        era_rows.sort(key=lambda r: -float(r[2].rstrip('%')))
        era_html = ("<div style='margin-top:14px'><b>分时代胜率（前半=2019-22 / 后半=2023-26，T+1净口径）</b>"
                    + table(["策略", "19-22 胜率", "23-26 胜率", "后段均笔", "趋势"], era_rows)
                    + "<div class='muted' style='margin-top:6px'>另：红利锚（不在此表，长线口径）胜率 57.5%→60.1% 逆势上升；"
                      "2026 年真实图景=挤板/追高全灭，活的是两端（深跌接+红利躺平）。</div></div>")
        secs.append(card("模拟盘锦标赛 · 两年各10万", table(["玩法", "收益", "最大回撤", "笔数/胜率", "均笔"], rows) + era_html,
                         f'{tour["window"][0]} ~ {tour["window"][1]} · 基准(上证) +{tour["bench%"]}% · 净口径 m60成交验证',
                         f'历史重放≠未来。{slip}', collapsed=True))
    # ── 席位口味 ──
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
        secs.append(card("游资口味 · 滚动 90 天", table(["席位", "近 90 天偏好", "买向 T+5", "备注"], rows),
                         f'{esc(taste.get("window", ""))} · 口味半年换血，每周六更新', collapsed=True))
    # ── 收割型反向提示（G4：持仓×收割席位交叉）──
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
        secs.append(card("收割型席位 · 持仓反向提示", body,
                         f'{esc(hdirs2[-1].name)} 龙虎榜 · T王/山东帮/温州帮净买入你的持仓=警惕'))
    # ── 北向 ──
    north = None
    for p in sorted(D.glob("north_profile_*.json")):
        north = jload(p)
    if north:
        mv = north["moves"]
        inc = sorted(north.get("increase_stocks", []),
                     key=lambda s: -((s.get("ratio") or 0) - (s.get("prev_ratio") or 0)))[:10]
        def _chg(s):
            # K3修（2026-09-14 用户抓包）：north_profile 的 change 是字符串股数，原代码只认数值 → 全渲染成"—亿股"
            try:
                v = float(s["change"]) / 1e8
                cls = "up" if v > 0 else "dn" if v < 0 else "muted"
                return f'<span class="{cls}">{v:+.2f}</span>'
            except (TypeError, ValueError):
                return '<span class="muted">—</span>'
        rows = [[esc(s["code"]), f'{s["ratio"]:.1f}%', _chg(s) + '<span class="muted">亿股</span>',
                 f'<span class="muted">{esc(s["industry"].split("、")[0][1:])}</span>'] for s in inc]
        secs.append(card("北向资金 · 季报画像", f"""
<div class="statrow"><div class="stat"><div class="num">{mv['增持+新进']}</div><div class="muted">增持+新进</div></div>
<div class="stat"><div class="num">{mv['减持']}</div><div class="muted">减持</div></div>
<div class="stat"><div class="num">{north['coverage']['with_north']}</div><div class="muted">覆盖个股</div></div></div>
<div style="margin-top:10px">{table(["代码", "北向持股", "环比变动", "行业"], rows)}</div>""",
                         f'季度慢变量 · 截至 {esc(north.get("latest_quarter", ""))}', NORTH_RULE, collapsed=True))
    # ── 涨停全景（挂涨停原因=消息面）──
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
            rows.append([esc(b["code"]), esc(b["name"]), pct(b["pct"]), f'{b["cap"]:.0f}亿',
                         f'<span class="muted">{esc(rsn)}</span>'])
        secs.append(card(f"涨停全景 · 市值前 10（{esc(reg["date"])}）", table(["代码", "名称", "涨幅", "市值", "涨停原因"], rows),
                         "周期仪全量扫描 + HiThink 题材归因", collapsed=True))
    # ── G7 焦点置顶（市场状态之后第一位）──
    # QQ联动说明卡（2026-09-14 用户令：页面内说明QQ推送与本页关系）
    secs.insert(1, card("📲 怎么配合 QQ 推送用这页",
                        """<table><tr><th>QQ 推送</th><th>对应本页版块</th><th>动作</th></tr>
<tr><td>9:32 反转族竞价确认</td><td>🥇明日首选 / 🔄反转族名单</td><td>确认通过→开盘买；被剔→作废</td></tr>
<tr><td>10:30 / 14:45 盘中雷达</td><td>持仓哨兵⚠️ / 观察池 / 冲板候选</td><td>⚠️破位=按处置树执行；冲板票对焦点区梯队</td></tr>
<tr><td>15:40 周期仪</td><td>市场状态徽章</td><td>周期切换=仓位档调整（平淡/恐慌期才开进攻仓）</td></tr>
<tr><td>19:00 后影子/委托单系列</td><td>银行委托单 / 主张影子 / B5处置</td><td>次日盘前照委托单挂单</td></tr></table>""",
                        "QQ=触发器（有事才说话），本页=证据库（盘后全貌+规则原文）",
                        "顺序：收到 QQ 推送 → 来这页找对应版块看规则和实测口径 → 按作废条件执行。别只看推送就动手。",
                        collapsed=True))
    # 作战手册卡（playbook-202609.md 摘要，静态规则层）——置顶第2位，焦点区第3位
    secs.insert(1, card("🎯 作战手册 · 2026-09 起",
                     """<table><tr><th>层</th><th>规则</th></tr>
<tr><td><b>底仓 60-70%</b></td><td>大部分钱买会分红的股票（银行为主），放着收租不动。只有跌得很便宜（分红率≥4.5%）才加买。<b>永远不要全卖</b>——折腾来回去还不如躺着（实测少赚13%）</td></tr>
<tr><td><b>进攻仓 0-30%</b></td><td>小部分钱玩短线，<b>只在市场冷清/恐慌的日子玩</b>（热闹日子玩=送钱，实测-2.6%）；买的票第二天没涨停就立刻卖掉，不许心疼留着</td></tr>
<tr><td><b>禁区（碰都别碰）</b></td><td>借钱炒股/全押一个板块/买跌停板/当天买当天卖/跟游资买/看新闻买/挂低价等回踩/炸板回封/金叉长线——全部实测亏钱</td></tr></table>""",
                     "每条规则带证据编号 · <a href='playbook-202609.md' style='color:#c0392b'>完整版+kill线 →</a>",
                     "周期仪是油门不是方向盘：恐慌期=打板fill黄金期（没人抢），主线期=红利拿稳别手痒"))
    if focus_rows:
        _pri = {"⚠️": 0, "🥇": 1, "🎯": 2, "🚀": 3, "🔄": 4}
        focus_rows = sorted(focus_rows, key=lambda r: _pri.get(r[0][:1], 5))[:8]
        def _flive(t):
            m0 = re.search(r"\((\d{6})\)", t)
            if not m0:
                return '<span class="muted">—</span>'
            c0 = m0.group(1)
            mk = ("sh" if c0.startswith("6") else "sz") + c0
            return (f'<span data-q="{mk}" data-f="r"><span class="muted">…</span></span>'
                    f'<br><span data-q="{mk}" data-f="j"></span>')
        body_f = table(["来源", "标的", "现在", "关键信息", "启动窗口/时点"],
                       [[f"<b>{s}</b>", t, _flive(t), i, w] for s, t, i, w in focus_rows])
        focus_card = card(f"📌 焦点清单 · 只看这一屏（数据 {reg["date"] if reg else today}）", body_f,
                          "观察池毕业中位 2 天 · 71.6% 在入池 3 日内启动（8 年实测分布）",
                          "破位优先处理 > 临启动盯梯队 > 抢跑排队 > 反转等竞价。其余卡片是证据库，这屏是行动清单。")
        secs.insert(2, focus_card)
    # ── 卡片显式排序（2026-09-14 用户令：按行动优先级排，首选卡按胜率降序）──
    _ORDER = {
        "🕐 现在该干嘛": 1, "市场状态": 2, "📌 焦点清单": 3,
        "🥇 首选 · 观察池临启动": 4,      # 58.9%
        "🥇 首选 · 深档低位": 5,          # 57.6%
        "⚡ B5": 6, "🔄 反转族 · 重症监护": 7,
        "🎯 作战手册": 8, "📲 怎么配合": 9,
        "📋 策略分工": 1, "放量异动观察池": 2, "首板抢跑": 3, "反转族 · 待确认": 4,
        "持仓哨兵": 1, "股息锚": 2, "银行股操作台": 3, "银行 ·": 4, "收割型席位": 5,
    }
    def _rank(html_s):
        m = re.search(r'data-tab="([^"]+)"', html_s)
        tab = m.group(1) if m else "证据库"
        t = re.sub(r"<[^>]+>", "", html_s)[:40]
        rnk = 99
        for prefix, r0 in _ORDER.items():
            if t.startswith(re.sub(r"<[^>]+>", "", prefix)):
                rnk = r0
                break
        return (tab, rnk)
    # 证据库保持胜率无关的原序；作战/候选池/持仓按 _ORDER
    secs.sort(key=lambda s: ({"作战": 0, "持仓": 1, "候选池": 2}.get(_rank(s)[0], 3), _rank(s)[1]))
    body = "\n".join(secs)
    OUT.write_text(TPL.replace("__DATE__", today).replace("__BODY__", body)
                   .replace("__STAMP__", datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
    # ── 人机共用状态契约（2026-09-13 用户裁决：你我都顺手的前端=单一事实源）──
    # docs/ops-state.json：面板渲染源数据聚合。人看 index.html，agent 读这个 JSON。
    ops = {
        "version": 1, "built_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "regime": reg and {"date": reg["date"], "regime": reg["regime"], "limit_ups": reg["stats"]["limit_ups"],
                            "limit_downs": reg["stats"]["limit_downs"]},
        "focus": [{"src": s, "target": t2, "info": re.sub(r"<[^>]+>", "", i), "window": re.sub(r"<[^>]+>", "", w)}
                  for s, t2, i, w in focus_rows],
        "watch_pool_top": [{"code": e["code"], "name": e["name"], "days": e.get("days"), "volratio": e["volratio"]}
                           for e in sorted(wp.get("pool", []), key=lambda e: -e["volratio"])[:10]] if wp else [],
        "playbook": "playbook-202609.md",
        "kill_lines": {"countercrowd_board": "平淡/恐慌期 fillable 影子 20 交易日均值<0 → 进攻仓归零",
                       "dividend_anchor": "买入区滚动胜率跌破对照 → 降级复审"},
        "links": {"panel": "https://tebio.github.io/fenjue/", "ops_state": "https://tebio.github.io/fenjue/ops-state.json"},
    }
    (OUT.parent / "ops-state.json").write_text(json.dumps(ops, ensure_ascii=False, indent=1))
    print(f"built {OUT} sections={len(secs)}")


TPL = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache,no-store,must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<title>焚诀操作台</title>
<style>
:root{--text:#37352f;--muted:#9b9a97;--bg:#fff;--divider:#ededeb;--soft:#f7f6f3}
*{margin:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font:15px/1.65 ui-sans-serif,-apple-system,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;font-variant-numeric:tabular-nums}
.wrap{max-width:760px;margin:0 auto;padding:56px 22px 80px}
h1{font-size:26px;font-weight:700;letter-spacing:.5px}
.sub{color:var(--muted);font-size:13px;margin-top:4px}
.card{margin-top:34px}
h2{font-size:15px;font-weight:600;padding-bottom:8px;border-bottom:1px solid var(--divider);margin-bottom:12px}
.hint{float:right;font-size:11px;font-weight:400;color:var(--muted);margin-top:3px}
.rule{background:var(--soft);border-radius:6px;padding:10px 14px;font-size:12.5px;color:#6b6b66;margin-bottom:12px;line-height:1.7}
.statrow{display:flex;gap:36px;align-items:flex-start;flex-wrap:wrap}
.big{font-size:17px}
.num{font-size:22px;font-weight:600}
.muted{color:var(--muted);font-size:12.5px}
.badge{display:inline-block;padding:2px 10px;border-radius:4px;font-size:13px;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--muted);font-weight:500;font-size:12px;padding:4px 8px 4px 0;border-bottom:1px solid var(--divider);white-space:nowrap}
td{padding:6px 8px 6px 0;border-bottom:1px solid var(--divider);vertical-align:top}
tr:last-child td{border-bottom:none}
details.card summary{font-size:15px;font-weight:600;padding-bottom:8px;border-bottom:1px solid var(--divider);cursor:pointer;list-style:none}
details.card summary::before{content:"▸ ";color:var(--muted)}
details.card[open] summary::before{content:"▾ "}
details.card .cardbody{padding-top:12px}
.tabbar{display:flex;gap:8px;margin-top:18px;position:sticky;top:0;background:var(--bg);padding:10px 0;z-index:9;border-bottom:1px solid var(--divider)}
.tabbtn{border:1px solid var(--divider);background:var(--soft);color:var(--muted);border-radius:8px;padding:7px 14px;font-size:13.5px;cursor:pointer;font-weight:500}
.tabbtn.active{background:var(--text);color:#fff;border-color:var(--text)}
.card[data-tab]{display:none}
.card[data-tab].showtab{display:block}
.up{color:#c0392b}.dn{color:#0f7b3d}.ok{color:#0f7b3d;font-size:12px}
.pre{background:var(--soft);border-radius:6px;padding:14px 16px;font:12.5px/1.7 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre-wrap;word-break:break-all}
.foot{margin-top:48px;padding-top:16px;border-top:1px solid var(--divider);color:var(--muted);font-size:12px}
</style></head><body><div class="wrap">
<h1>焚诀操作台</h1>
<div class="sub">__DATE__ · 研究辅助，不是买卖指令 · 构建于 __STAMP__ · <span id="cd">…</span> · <span id="livepulse" style="color:#c0392b"></span></div>
<div class="tabbar" id="tabbar">
<button class="tabbtn active" data-tab="作战">⚔️ 作战</button>
<button class="tabbtn" data-tab="持仓">💰 持仓/底仓</button>
<button class="tabbtn" data-tab="候选池">🔭 候选池</button>
<button class="tabbtn" data-tab="证据库">📚 证据库</button>
</div>
__BODY__
<div class="foot">焚诀 Research Engine · 交易日自动重建：09:40 竞价后 / 10:40 雷达后 / 13:35 午后 / 14:50 尾盘 / 15:20 收盘快报 / 15:50 反转名单 / 16:15 委托单后 / 19:20 晚间 / 20:40 数据齐<br>
非交易日不重建（显示最近交易日数据，版块日期戳为准）· 红涨绿跌 · 胜率均值均为净口径（扣 0.15% 费用）· 所有策略结论带作废条件与 kill 线</div>
</div>
<script>
(function(){
// ── 标签页切换（2026-09-14：切换菜单替代瀑布流）──
var btns=document.querySelectorAll(".tabbtn");
function show(tab){
  document.querySelectorAll(".card[data-tab]").forEach(function(c){
    c.classList.toggle("showtab", c.getAttribute("data-tab")===tab);
  });
  btns.forEach(function(b){b.classList.toggle("active", b.getAttribute("data-tab")===tab);});
  try{localStorage.setItem("fj_tab",tab);}catch(e){}
}
btns.forEach(function(b){b.onclick=function(){show(b.getAttribute("data-tab"));};});
var saved=null;try{saved=localStorage.getItem("fj_tab");}catch(e){}
show(saved||"作战");
// ── 更新倒计时 ──
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
// ── 盘中自动刷新（2026-09-14 用户裁决）：交易日 9:25-15:10 BJT 每 3 分钟重载 ──
function bjt(){var n=new Date();return new Date(n.getTime()+(n.getTimezoneOffset()+480)*60000);}
var b=bjt(),wd=b.getDay(),hh=b.getHours()*60+b.getMinutes();
if(wd>=1&&wd<=5&&hh>=565&&hh<=910){setTimeout(function(){location.reload();},180000);}
// ── 实时报价（JSONP 注入 qt.gtimg.cn，静态页免跨域；2026-09-14 用户令）──
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
        else if(k==="j"){ // 强弱判定（2026-09-14 用户令：转弱/跟风标注，新手防误买）
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
if(w===0||w===6){msg="📴 今天不开市。不用操作，想看就翻翻「证据库」。";}
else if(m<565){msg="🌅 盘前：照「持仓」页的银行委托单挂单。挂完收工。";}
else if(m<572){msg="⏳ 竞价中：别动手，等 9:32 QQ 确认单。";}
else if(m<585){msg="🟢 买入窗口（9:32-9:45）：首选卡有票才买，没票=今天不买。看 QQ 确认单！";color="#c0392b";}
else if(m<630){msg="🪑 窗口已过。别追，等 10:30 雷达。";}
else if(m<885){msg="🪑 现在什么都不用干。QQ 不喊你=没事。盯盘不产生收益。";}
else if(m<900){msg="🔴 卖出窗口（14:45-15:00）：昨天买的短线票现在卖，无论盈亏。";color="#0f7b3d";}
else if(m<940){msg="📊 收盘了。等 15:40 周期仪徽章，定明天仓位。";}
else{msg="🌙 晚间：看「持仓」页委托单，明天 9:25 前照挂即可。";}
el.textContent=msg;el.style.color=color;
})();
})();
</script>
</body></html>"""

if __name__ == "__main__":
    main()
