#!/usr/bin/env python3
"""生成 FenJue 静态站点 → GitHub Pages"""
import json, sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "index.html"

# ── hardcoded data (until scheduler feeds real scores) ──
DATA = {
    "updated": "2026-07-07T23:55:00+08:00",
    "regime": {"current": "risk_neutral", "max_position": 0.6, "capital_style": "balanced"},
    "industries": [
        {"name":"AI材料","heat":"★★★★★","weight":1.05,"stage":"主升初期"},
        {"name":"半导体","heat":"★★★★☆","weight":1.00,"stage":"发酵期"},
        {"name":"机器人","heat":"★★★☆☆","weight":0.89,"stage":"调整蓄势"},
        {"name":"军工电子","heat":"★★★☆☆","weight":1.05,"stage":"蓄势期"},
    ],
    "watchlist": [
        {"code":"600141","name":"兴发集团","price":"实时","tier":"S","score":8.2,"odds":3.5,"win_rate":0.65,"cycle":"1-3月"},
        {"code":"002428","name":"云南锗业","price":"实时","tier":"S","score":7.8,"odds":2.8,"win_rate":0.60,"cycle":"1-3月"},
        {"code":"600206","name":"有研新材","price":"实时","tier":"A","score":7.5,"odds":2.2,"win_rate":0.55,"cycle":"3-6月"},
        {"code":"002409","name":"雅克科技","price":"实时","tier":"A","score":7.2,"odds":2.0,"win_rate":0.52,"cycle":"3-6月"},
        {"code":"600584","name":"长电科技","price":"实时","tier":"A","score":6.8,"odds":1.8,"win_rate":0.50,"cycle":"6月+"},
        {"code":"002384","name":"东山精密","price":"实时","tier":"B","score":6.5,"odds":1.5,"win_rate":0.45,"cycle":"6月+"},
        {"code":"688716","name":"中研股份","price":"实时","tier":"B","score":6.2,"odds":1.3,"win_rate":0.40,"cycle":"6月+"},
        {"code":"600072","name":"中船科技","price":"实时","tier":"B","score":5.8,"odds":1.2,"win_rate":0.38,"cycle":"6月+"},
    ]
}

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>焚诀 Console</title>
<style>
:root{{--bg:#0a0e14;--card:#131820;--border:#1e2733;--accent:#00d4aa;--text:#c5cdd8;--muted:#5c6b7a;--danger:#e0556a}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.5;padding:24px;max-width:960px;margin:0 auto}}
h1{{font-size:22px;color:var(--accent);margin-bottom:4px}}
.updated{{font-size:11px;color:var(--muted);margin-bottom:20px}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:14px}}
.card-title{{font-size:13px;font-weight:600;color:var(--accent);margin-bottom:10px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}}
.stat{{text-align:center;padding:10px}}
.stat-val{{font-size:24px;font-weight:700;color:var(--accent)}}
.stat-label{{font-size:10px;color:var(--muted)}}
.industry-row{{display:flex;align-items:center;padding:8px 0;border-bottom:1px solid var(--border)}}
.industry-name{{width:80px;font-size:13px}}
.stars{{color:#f0c040}}
.industry-weight{{color:var(--accent);margin-left:auto;font-size:12px}}
.industry-stage{{font-size:11px;color:var(--muted);width:60px;text-align:right}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{text-align:left;padding:8px 6px;border-bottom:1px solid var(--border);color:var(--muted);font-weight:500}}
td{{padding:8px 6px;border-bottom:1px solid rgba(30,39,51,.5)}}
.badge-s{{background:rgba(0,212,170,.15);color:var(--accent);padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}}
.badge-a{{background:rgba(255,193,7,.12);color:#ffc107;padding:2px 8px;border-radius:4px;font-size:11px}}
.badge-b{{background:rgba(92,107,122,.15);color:var(--muted);padding:2px 8px;border-radius:4px;font-size:11px}}
.up{{color:var(--accent)}}.down{{color:var(--danger)}}
footer{{text-align:center;color:var(--muted);font-size:10px;margin-top:30px;padding:20px 0}}
</style></head>
<body>
<h1>🔥 焚诀 Console</h1>
<p class="updated">更新: {updated}</p>

<div class="card"><div class="card-title">📊 市场状态</div><div class="grid">
<div class="stat"><div class="stat-val">{regime}</div><div class="stat-label">市场状态</div></div>
<div class="stat"><div class="stat-val">{max_pos:.0%}</div><div class="stat-label">仓位上限</div></div>
<div class="stat"><div class="stat-val">{capital}</div><div class="stat-label">资本风格</div></div>
</div></div>

<div class="card"><div class="card-title">🏭 产业雷达</div>
{industries}
</div>

<div class="card"><div class="card-title">📋 自选池</div>
<table><thead><tr><th>池</th><th>代码</th><th>名称</th><th>总分</th><th>赔率</th><th>胜率</th><th>兑现周期</th></tr></thead><tbody>
{watchlist}
</tbody></table></div>

<footer>焚诀 V1 · 自动化投研中台 · 数据每日更新</footer>
</body></html>"""

def build():
    ind_rows = ""
    for i in DATA["industries"]:
        ind_rows += f"""<div class="industry-row">
  <span class="industry-name">{i['name']}</span>
  <span class="stars">{i['heat']}</span>
  <span class="industry-weight">×{i['weight']:.2f}</span>
  <span class="industry-stage">{i['stage']}</span>
</div>"""

    wl_rows = ""
    for w in DATA["watchlist"]:
        badge = f"badge-{w['tier'].lower()}"
        wl_rows += f"""<tr>
  <td><span class="{badge}">{w['tier']}</span></td>
  <td>{w['code']}</td><td>{w['name']}</td>
  <td style="font-weight:600">{w['score']:.1f}</td>
  <td>{w['odds']:.1f}x</td>
  <td>{int(w['win_rate']*100)}%</td>
  <td>{w['cycle']}</td>
</tr>"""

    html = HTML.format(
        updated=DATA["updated"],
        regime=DATA["regime"]["current"].replace("_", " ").title(),
        max_pos=DATA["regime"]["max_position"],
        capital=DATA["regime"]["capital_style"],
        industries=ind_rows,
        watchlist=wl_rows,
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"Wrote {len(html)} bytes → {OUT}")

if __name__ == "__main__":
    build()
