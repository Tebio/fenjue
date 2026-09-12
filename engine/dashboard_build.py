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


def jload(p, default=None):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def esc(s):
    return html.escape(str(s), quote=False)


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
                         "首板+板块梯队≥3+市值20-400亿 · 测量级通过 影子验证中", FRONT_RULE))
    # ── 反转族 ──
    rev = jload(D / "reversal_list.json", {})
    if rev and rev.get("candidates"):
        rows = [[esc(c["code"]), esc(c["name"]), pct(c["close_chg"]), f'{c["amt_yi"]:.0f}亿']
                for c in rev["candidates"][:8]]
        secs.append(card("反转族 · 明日观察名单", table(["代码", "名称", "今日跌幅", "成交额"], rows),
                         f'{esc(rev.get("date", ""))} 收盘扫描 · 外部复审 +0.139%/49.8% 净口径', REV_RULE))
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
    body = "\n".join(secs)
    OUT.write_text(TPL.replace("__DATE__", today).replace("__BODY__", body)
                   .replace("__STAMP__", datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
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
