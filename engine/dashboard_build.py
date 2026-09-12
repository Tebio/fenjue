#!/usr/bin/env python3
"""engine/dashboard_build.py — 焚诀操作台静态面板构建（2026-09-12）

读取各 cron 落盘数据 → 生成 Notion 风格单文件 docs/index.html → GitHub Pages。
stdlib 零依赖；任一数据源缺失降级为「未生成」卡片，不崩。
数据源：regime_log.jsonl / bank_console_latest.txt / claims_shadow.jsonl /
  claims_shadow_summary.json / reversal_list.json / seat_gene_rolling.json / north_profile_*.json
"""
import json, html, datetime
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
D = ROOT / "data"
OUT = ROOT / "docs/index.html"


def jload(p, default=None):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def esc(s):
    return html.escape(str(s), quote=False)


def badge_regime(r):
    m = {"主线期": ("#0f7b3d", "#e6f4ea"), "妖股期": ("b45309", "#fef3e2"),
         "恐慌期": ("#c0392b", "#fdecea"), "平淡期": ("#6b6b66", "#f1f1ef")}
    fg, bg = m.get(r, ("#6b6b66", "#f1f1ef"))
    return f'<span class="badge" style="color:{fg};background:{bg}">{esc(r)}</span>'


def card(title, inner, hint=""):
    h = f'<span class="hint">{esc(hint)}</span>' if hint else ""
    return f'<section class="card"><h2>{esc(title)}{h}</h2>{inner}</section>'


def table(headers, rows):
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>'


def pct(x, plus=True):
    if x is None:
        return '<span class="muted">—</span>'
    v = round(x, 2)
    cls = "up" if v > 0 else "dn" if v < 0 else "muted"
    sign = "+" if plus and v > 0 else ""
    return f'<span class="{cls}">{sign}{v}%</span>'


def main():
    today = datetime.date.today().isoformat()
    # ── 周期仪 ──
    reg = None
    rl = D / "regime_log.jsonl"
    if rl.exists():
        lines = rl.read_text().strip().splitlines()
        if lines:
            reg = json.loads(lines[-1])
    # ── 银行委托单 ──
    bank = None
    bf = D / "bank_console_latest.txt"
    if bf.exists():
        bank = bf.read_text()
    # ── frontrun 影子 ──
    fr = []
    sf = D / "claims_shadow.jsonl"
    if sf.exists():
        for line in sf.read_text().splitlines():
            r = json.loads(line)
            if r["claim"] == "FRONTRUN_FIRSTBOARD_V2":
                fr.append(r)
    # ── 主张影子汇总 ──
    summ = jload(D / "claims_shadow_summary.json", {})
    # ── 反转族 ──
    rev = jload(D / "reversal_list.json", {})
    # ── 席位口味 ──
    taste = jload(D / "seat_gene_rolling.json", {})
    # ── 北向 ──
    north = None
    for p in sorted(D.glob("north_profile_*.json")):
        north = jload(p)
    # ── 组装 ──
    secs = []
    if reg:
        st = reg["stats"]
        lamp = "🟢" if reg["regime"] == "主线期" else "🟡" if reg["regime"] in ("妖股期", "平淡期") else "🔴"
        secs.append(card("市场状态", f"""
<div class="statrow"><div><div class="big">{badge_regime(reg['regime'])}</div>
<div class="muted">周期仪 · {esc(reg['date'])}</div></div>
<div class="stat"><div class="num">{st['limit_ups']}<span class="muted"> / {st['limit_downs']}</span></div><div class="muted">涨停 / 跌停</div></div>
<div class="stat"><div class="num">{pct(st['index_pct'])}</div><div class="muted">指数</div></div></div>
<div class="muted" style="margin-top:10px">主线板块：{"、".join(f"{esc(n)}({c})" for n, c in st["top_sectors"][:4])}</div>""", "每日 15:40 盘后扫描"))
    if bank:
        order = bank[bank.find("── 明日委托单"):] if "── 明日委托单" in bank else bank
        secs.append(card("银行股 · 明日委托单", f'<pre class="pre">{esc(order.strip())}</pre>',
                         "股息率锚 · 样本外 60.1% 胜率 · 价格线仅分红/财报后调整"))
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
                         "首板+板块梯队≥3+市值20-400亿 · 测量级通过 影子验证中"))
    if rev and rev.get("candidates"):
        rows = [[esc(c["code"]), esc(c["name"]), pct(c["close_chg"]), f'{c["amt_yi"]:.0f}亿']
                for c in rev["candidates"][:8]]
        secs.append(card("反转族 · 明日观察名单", table(["代码", "名称", "今日跌幅", "成交额"], rows),
                         f'{esc(rev.get("date", ""))} 收盘扫描 · 9:32 竞价确认后生效'))
    if summ:
        rows = []
        for claim, tiers in summ.items():
            for tier, tags in tiers.items():
                r1, r5 = tags.get("r1"), tags.get("r5")
                if r1 or r5:
                    rows.append([esc(claim), esc(tier),
                                 f'{r1["mean%"]}%/{r1["win%"]}%' if r1 else "—",
                                 f'{r5["mean%"]}%/{r5["win%"]}%' if r5 else "—",
                                 str((r5 or r1)["n"])])
        secs.append(card("主张影子表现", table(["主张", "档", "T+1 均值/胜率", "T+5 均值/胜率", "n"], rows) if rows
                         else '<div class="muted">影子期积累中（2026-09-11 起，20 交易日见分晓）</div>', "L5 前向验证 · kill 线滚动审计"))
    else:
        secs.append(card("主张影子表现", '<div class="muted">影子期积累中（2026-09-11 起，20 交易日见分晓）</div>', "L5 前向验证"))
    if taste and taste.get("seats"):
        rows = []
        for nm, s in list(taste["seats"].items())[:8]:
            t5 = s.get("buy_dir_T5") or {}
            warn = ' <span class="badge" style="color:#c0392b;background:#fdecea">收割型·反向</span>' if nm in ("T王", "温州帮", "山东帮") else ""
            rows.append([esc(nm) + warn, "、".join(c for c, _ in s["top_concepts"][:3]),
                         pct(t5.get("avg%")) if t5 else "—"])
        secs.append(card("游资口味 · 滚动 90 天", table(["席位", "近 90 天偏好", "买向 T+5"], rows),
                         f'{esc(taste.get("window", ""))} · 口味半年换血，此表每周六更新'))
    if north:
        mv = north["moves"]
        secs.append(card("北向资金 · 季报画像", f"""
<div class="statrow"><div class="stat"><div class="num">{mv['增持+新进']}</div><div class="muted">增持+新进</div></div>
<div class="stat"><div class="num">{mv['减持']}</div><div class="muted">减持</div></div>
<div class="stat"><div class="num">{north['coverage']['with_north']}</div><div class="muted">覆盖个股</div></div></div>
<div class="muted" style="margin-top:10px">增持行业：{"、".join(f"{esc(i.split('、')[0][1:])}({n})" for i, n in north["top_increase_industries"][:5])}</div>""",
                         f'季度慢变量 · 截至 {esc(north.get("latest_quarter", ""))}'))
    if reg and reg.get("boards"):
        rows = [[esc(b["code"]), esc(b["name"]), pct(b["pct"]), f'{b["cap"]:.0f}亿']
                for b in sorted(reg["boards"], key=lambda b: -b["cap"])[:10]]
        secs.append(card("今日涨停全景 · 市值前 10", table(["代码", "名称", "涨幅", "市值"], rows), "周期仪全量扫描"))
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
.statrow{display:flex;gap:36px;align-items:flex-start;flex-wrap:wrap}
.big{font-size:17px}
.num{font-size:22px;font-weight:600}
.muted{color:var(--muted);font-size:12.5px}
.badge{display:inline-block;padding:2px 10px;border-radius:4px;font-size:13px;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--muted);font-weight:500;font-size:12px;padding:4px 8px 4px 0;border-bottom:1px solid var(--divider)}
td{padding:6px 8px 6px 0;border-bottom:1px solid var(--divider)}
tr:last-child td{border-bottom:none}
.up{color:#0f7b3d}.dn{color:#c0392b}.ok{color:#0f7b3d;font-size:12px}
.pre{background:var(--soft);border-radius:6px;padding:14px 16px;font:12.5px/1.7 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre-wrap;word-break:break-all}
.foot{margin-top:48px;padding-top:16px;border-top:1px solid var(--divider);color:var(--muted);font-size:12px}
</style></head><body><div class="wrap">
<h1>焚诀操作台</h1>
<div class="sub">__DATE__ · 研究辅助，不是买卖指令 · 数据构建于 __STAMP__</div>
__BODY__
<div class="foot">焚诀 Research Engine · 各版块数据由盘后 cron 自动落盘，本页静态快照每交易日更新<br>
所有策略结论均带作废条件与 kill 线；胜率均值均为净口径（扣 0.15% 费用）</div>
</div></body></html>"""

if __name__ == "__main__":
    main()
