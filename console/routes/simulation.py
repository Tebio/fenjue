"""Simulation route — scenario radio select + run → re-rank S-pool under different regimes."""
from __future__ import annotations
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

# (label, [(产业, 原权重, 新权重), ...], [(排名, 代码, 名称, 原评分, 新评分), ...])
_S: dict[str, tuple] = {
    "ai_fade": ("AI退潮", [
        ("AI材料",1.05,0.80),("半导体",1.00,0.85),("机器人",0.85,0.70),("军工电子",1.00,1.20),("新能源",0.70,0.65)
    ], [
        ("600072","中船科技",5.8,7.2),("600584","长电科技",6.8,7.0),("002428","云南锗业",7.8,6.9),
        ("600141","兴发集团",8.2,6.5),("002409","雅克科技",7.2,6.3),
    ]),
    "us_crash": ("美股大跌5%", [
        ("AI材料",1.05,0.74),("半导体",1.00,0.70),("机器人",0.85,0.60),("军工电子",1.00,0.70),("新能源",0.70,0.49)
    ], [
        ("600072","中船科技",5.8,5.0),("600584","长电科技",6.8,4.8),("002428","云南锗业",7.8,4.5),
        ("002384","东山精密",6.5,4.2),("600141","兴发集团",8.2,4.0),
    ]),
    "domestic_sub": ("国产替代加强", [
        ("AI材料",1.05,1.25),("半导体",1.00,1.30),("机器人",0.85,0.95),("军工电子",1.00,1.10),("新能源",0.70,0.60)
    ], [
        ("600584","长电科技",6.8,8.0),("002409","雅克科技",7.2,7.8),("600141","兴发集团",8.2,7.5),
        ("002428","云南锗业",7.8,7.2),("600206","有研新材",7.5,6.8),
    ]),
    "military_boom": ("军工爆发", [
        ("AI材料",1.05,0.90),("半导体",1.00,0.85),("机器人",0.85,0.80),("军工电子",1.00,1.50),("新能源",0.70,0.55)
    ], [
        ("600072","中船科技",5.8,8.5),("002428","云南锗业",7.8,7.5),("600141","兴发集团",8.2,7.0),
        ("002409","雅克科技",7.2,6.8),("600584","长电科技",6.8,6.5),
    ]),
    "risk_off": ("Risk Off", [
        ("AI材料",1.05,0.63),("半导体",1.00,0.55),("机器人",0.85,0.51),("军工电子",1.00,0.65),("新能源",0.70,0.40)
    ], [
        ("600584","长电科技",6.8,5.5),("600072","中船科技",5.8,5.2),("002428","云南锗业",7.8,5.0),
        ("600141","兴发集团",8.2,4.8),("002409","雅克科技",7.2,4.5),
    ]),
}


def _results(scenario_key: str) -> str:
    _, inds, spool = _S.get(scenario_key, _S["ai_fade"])
    irows = "".join(
        f'<tr><td>{n}</td><td style="color:var(--muted)">×{o:.2f}</td>'
        f'<td style="color:var(--accent)">×{w:.2f}</td>'
        f'<td class="{"stat-up" if (d:=w-o)>0 else "stat-down"}">{d:+.2f}</td></tr>'
        for n, o, w in inds
    )
    srows = "".join(
        f'<tr><td style="color:var(--accent)">{i+1}</td><td>{c}</td><td>{n}</td>'
        f'<td style="color:var(--muted)">{o:.1f}</td>'
        f'<td style="color:var(--accent)">{w:.1f}</td>'
        f'<td class="{"stat-up" if (d:=w-o)>0 else "stat-down"}">{d:+.1f}</td></tr>'
        for i, (c, n, o, w) in enumerate(spool)
    )
    return f"""<div id="sim-results" style="margin-top:16px">
<h3 style="font-size:14px;margin:0 0 10px;color:var(--muted)">🏭 产业雷达变化</h3>
<div class="card" style="padding:0;overflow-x:auto;margin-bottom:14px">
<table><thead><tr><th>产业</th><th>原权重</th><th>新权重</th><th>变化</th></tr></thead><tbody>{irows}</tbody></table></div>
<h3 style="font-size:14px;margin:0 0 10px;color:var(--muted)">🏆 新S池排名</h3>
<div class="card" style="padding:0;overflow-x:auto">
<table><thead><tr><th>排名</th><th>代码</th><th>名称</th><th>原评分</th><th>新评分</th><th>变化</th></tr></thead><tbody>{srows}</tbody></table></div></div>"""


_OPTS = "\n".join(
    f'<label style="margin-right:16px;cursor:pointer;font-size:13px">'
    f'<input type="radio" name="scenario" value="{k}"{" checked" if k=="ai_fade" else ""}> {v[0]}</label>'
    for k, v in _S.items()
)


@router.get("/console/sim", response_class=HTMLResponse)
async def sim_page(request: Request) -> HTMLResponse:
    return HTMLResponse(content=f"""<div>
<h2 style="font-size:18px;margin:0 0 16px;color:var(--accent)">🧪 情景模拟</h2>
<div class="card">
<form id="sim-form" hx-post="/console/api/sim/run" hx-target="#sim-results" hx-swap="outerHTML">
<div style="margin-bottom:12px">{_OPTS}</div>
<button type="submit" style="background:var(--accent);color:var(--bg);border:none;
border-radius:4px;padding:7px 20px;cursor:pointer;font-weight:600">▶ 运行模拟</button>
</form></div><div id="sim-results"></div></div>""")


@router.post("/console/api/sim/run", response_class=HTMLResponse)
async def run_sim(request: Request, scenario: str = Form("ai_fade")) -> HTMLResponse:
    return HTMLResponse(content=_results(scenario))
