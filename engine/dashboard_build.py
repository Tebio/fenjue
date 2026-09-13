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


def card(title, inner, hint="", rule=""):
    h = f'<span class="hint">{esc(hint)}</span>' if hint else ""
    r = f'<div class="rule">{esc(rule)}</div>' if rule else ""
    return f'<section class="card"><h2>{esc(title)}{h}</h2>{r}{inner}</section>'


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
    # ── 周期仪 ──
    reg = None
    rl = D / "regime_log.jsonl"
    if rl.exists():
        lines = rl.read_text().strip().splitlines()
        if lines:
            reg = json.loads(lines[-1])
    if reg:
        st = reg["stats"]
        secs.append(card("市场状态", f"""
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
            rows.append([f"{esc(p['name'])}<br><span class='muted'>{p['code']}</span>",
                         f"{price:.2f}", pct(chg),
                         f'<span class="muted">{esc(p["note"])}</span>',
                         " ".join(flags) or '<span class="muted">区间内</span>'])
            if any("⚠️破" in f0 for f0 in flags):
                focus_rows.append(("⚠️持仓破位", f"{esc(p['name'])}({p['code']})",
                                   " ".join(flags), "立即检查纪律"))
        if rows:
            secs.append(card("持仓哨兵", table(["标的", "现价", "今日", "备注", "关键位"], rows),
                             "config/watchlist.json · 越线自动标记"))
        arows = []
        for a in watch.get("anchors", []):
            if a["code"] not in q:
                continue
            price, chg = q[a["code"]]
            in_zone = price <= a["buy"]
            arows.append([esc(a["name"]), f"{price:.2f}", f'{a["buy"]:.2f}',
                          '<span class="up">🟢买入区内</span>' if in_zone
                          else f'<span class="muted">线上方{(price/a["buy"]-1)*100:+.1f}%</span>'])
        if arows:
            secs.append(card("股息锚买入区", table(["标的", "现价", "买入线", "状态"], arows),
                             "现价≤线=可建仓/加仓"))
    # ── 观察池（G1）──
    wp = jload(D / "watch_pool.json", {})
    if wp and wp.get("pool"):
        rows = []
        for e in sorted(wp["pool"], key=lambda e: -e["volratio"])[:10]:
            rows.append([esc(e["code"]), esc(e["name"]), f'<span class="muted">{esc(e["entry_date"])}</span>',
                         f'{e["volratio"]}x', pct(e["pct"]), str(e.get("days", 0)),
                         '<span class="up">缩量持稳</span>' if e.get("shrink") else '<span class="muted">观察中</span>'])
        # G7 焦点：临启动票（第1-5天=窗口期；中位2日/71.6%≤3日毕业，实测分布）；上限8条防爆版
        for e in sorted((e for e in wp["pool"] if 1 <= e.get("days", 0) <= 5),
                        key=lambda e: (e["days"], -e["volratio"]))[:8]:
            win = ("🔥高发窗口" if e["days"] <= 3 else "窗口尾（第4-5天）")
            focus_rows.append(("🎯观察池临启动", f"{esc(e['name'])}({e['code']})",
                               f'量比{e["volratio"]}x · 第{e["days"]}天' + (" · 缩量持稳" if e.get("shrink") else ""),
                               win))
        hint = f'{esc(wp.get("updated", ""))} · 放量未板+缩量横盘不破=启动前形态（002519 原型）'
        secs.append(card("放量异动观察池", table(["代码", "名称", "入池", "量比", "当日", "天数", "状态"], rows),
                         hint,
                         "用法：池内票出现板块梯队+首板=抢跑买点（frontrun 规则条）；破入池日前低=出局。"))
    # ── 银行委托单（表格化）──
    bf = D / "bank_console_latest.txt"
    if bf.exists():
        rows, orders = parse_bank(bf.read_text())
        if rows:
            secs.append(card("银行股操作台", table(
                ["标的", "现价", "息率", "PB", "状态", "买入线", "卖出线", "清仓线", "距买入"], rows),
                "股息率锚 · 样本外 60.1% 胜率 · 价格线仅分红/财报后调整",
                "规则：买入区=可建仓/加仓（阶梯挂单 买线/-4%/-8%）；卖出区=减仓不清仓；清仓区=清仓离场。价格线不随日内波动。"))
        if orders:
            secs.append(card("银行 · 明日委托单", table(
                ["标的", "操作", "买入", "加仓阶梯", "卖出", "清仓"], orders),
                "明早盘前照抄挂单即可"))
    # ── frontrun 影子 ──
    fr = []
    sf = D / "claims_shadow.jsonl"
    if sf.exists():
        for line in sf.read_text().splitlines():
            r = json.loads(line)
            if r["claim"] == "FRONTRUN_FIRSTBOARD_V2":
                fr.append(r)
    if fr:
        by_date = {}
        for r in fr:
            by_date.setdefault(r["signal_date"], []).append(r)
        rows = []
        for dt in sorted(by_date, reverse=True)[:3]:
            for r in by_date[dt]:
                rows.append([f'<span class="muted">{esc(dt)}</span>', esc(r["code"]),
                             pct(r["r1"] * 100 if r["r1"] is not None else None),
                             pct(r["r5"] * 100 if r["r5"] is not None else None),
                             '<span class="muted">未成交</span>' if r.get("untradeable") else (
                                 '<span class="ok">在车上</span>' if r["entry"] else '<span class="muted">待回填</span>')])
        secs.append(card("首板抢跑 · 影子名单", table(["信号日", "代码", "T+1", "T+5", "状态"], rows),
                         "首板+板块梯队≥3+市值20-400亿 · 测量级通过 影子验证中", FRONT_RULE + FILL_NOTE))
        latest_dt = max(by_date) if by_date else None
        if latest_dt:
            for r in by_date[latest_dt]:
                focus_rows.append(("🚀首板抢跑", esc(r["code"]), "封板 bar 排队打板",
                                   f"{latest_dt} 已封板"))
    # ── 反转族 ──
    rev = jload(D / "reversal_list.json", {})
    if rev and rev.get("candidates"):
        rows = [[esc(c["code"]), esc(c["name"]), pct(c["close_chg"]), f'{c["amt_yi"]:.0f}亿']
                for c in rev["candidates"][:8]]
        secs.append(card("反转族 · 明日观察名单", table(["代码", "名称", "今日跌幅", "成交额"], rows),
                         f'{esc(rev.get("date", ""))} 收盘扫描 · 外部复审 +0.139%/49.8% 净口径', REV_RULE))
        for c in rev["candidates"][:3]:
            focus_rows.append(("🔄反转族", f"{esc(c['name'])}({c['code']})",
                               f'昨{c["close_chg"]:.1f}% · 额{c["amt_yi"]:.0f}亿',
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
                     "L5 前向验证 · kill 线滚动审计，不达标自动降级"))
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
        secs.append(card("模拟盘锦标赛 · 两年各10万", table(["玩法", "收益", "最大回撤", "笔数/胜率", "均笔"], rows),
                         f'{tour["window"][0]} ~ {tour["window"][1]} · 基准(上证) +{tour["bench%"]}% · 净口径 m60成交验证',
                         f'历史重放≠未来。{slip}'))
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
                         f'{esc(taste.get("window", ""))} · 口味半年换血，每周六更新'))
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
        rows = [[esc(s["code"]), f'{s["ratio"]:.1f}%', pct(s["change"] / 1e8 if isinstance(s["change"], (int, float)) else None, plus=False) + '<span class="muted">亿股</span>',
                 f'<span class="muted">{esc(s["industry"].split("、")[0][1:])}</span>'] for s in inc]
        secs.append(card("北向资金 · 季报画像", f"""
<div class="statrow"><div class="stat"><div class="num">{mv['增持+新进']}</div><div class="muted">增持+新进</div></div>
<div class="stat"><div class="num">{mv['减持']}</div><div class="muted">减持</div></div>
<div class="stat"><div class="num">{north['coverage']['with_north']}</div><div class="muted">覆盖个股</div></div></div>
<div style="margin-top:10px">{table(["代码", "北向持股", "环比变动", "行业"], rows)}</div>""",
                         f'季度慢变量 · 截至 {esc(north.get("latest_quarter", ""))}', NORTH_RULE))
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
        secs.append(card("今日涨停全景 · 市值前 10", table(["代码", "名称", "涨幅", "市值", "涨停原因"], rows),
                         "周期仪全量扫描 + HiThink 题材归因"))
    # ── G7 焦点置顶（市场状态之后第一位）──
    # 作战手册卡（playbook-202609.md 摘要，静态规则层）——置顶第2位，焦点区第3位
    secs.insert(1, card("🎯 作战手册 · 2026-09 起",
                     """<table><tr><th>层</th><th>规则</th></tr>
<tr><td><b>底仓 60-70%</b></td><td>红利躺平：连续≥3年分红+息率≥4.5%买入线，核心仓不清（轮动清仓跑输躺平13pp）</td></tr>
<tr><td><b>进攻仓 0-30%</b></td><td><b>反人群打板</b>：只在<span class="dn">平淡/恐慌期</span>开仓（主线/妖股期开缝有毒-2.6~-2.9%已实测）；断板即跑，禁止宽容持有</td></tr>
<tr><td><b>禁区</b></td><td>杠杆/单板块/跌停接/做T/跟席位/看新闻买/回踩限价/炸板回封/金叉长线</td></tr></table>""",
                     "每条规则带证据编号 · <a href='playbook-202609.md' style='color:#c0392b'>完整版+kill线 →</a>",
                     "周期仪是油门不是方向盘：恐慌期=打板fill黄金期（没人抢），主线期=红利拿稳别手痒"))
    if focus_rows:
        body_f = table(["来源", "标的", "关键信息", "启动窗口/时点"],
                       [[f"<b>{s}</b>", t, i, w] for s, t, i, w in focus_rows])
        focus_card = card("📌 今日焦点 · 只看这一屏", body_f,
                          "观察池毕业中位 2 天 · 71.6% 在入池 3 日内启动（8 年实测分布）",
                          "破位优先处理 > 临启动盯梯队 > 抢跑排队 > 反转等竞价。其余卡片是证据库，这屏是行动清单。")
        secs.insert(2, focus_card)
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
.up{color:#c0392b}.dn{color:#0f7b3d}.ok{color:#0f7b3d;font-size:12px}
.pre{background:var(--soft);border-radius:6px;padding:14px 16px;font:12.5px/1.7 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre-wrap;word-break:break-all}
.foot{margin-top:48px;padding-top:16px;border-top:1px solid var(--divider);color:var(--muted);font-size:12px}
</style></head><body><div class="wrap">
<h1>焚诀操作台</h1>
<div class="sub">__DATE__ · 研究辅助，不是买卖指令 · 数据构建于 __STAMP__</div>
__BODY__
<div class="foot">焚诀 Research Engine · 各版块数据由盘后 cron 自动落盘，本页静态快照每交易日更新<br>
红涨绿跌 · 胜率均值均为净口径（扣 0.15% 费用）· 所有策略结论带作废条件与 kill 线</div>
</div></body></html>"""

if __name__ == "__main__":
    main()
