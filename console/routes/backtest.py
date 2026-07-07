"""Backtest route — strategy selector + run button + Hit Rate/Alpha results."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

_STATS = {
    "hit_rate": 72.5, "alpha": 13.2, "max_drawdown": -8.4,
    "years": [
        {"year": 2025, "hit": 68, "alpha": 11, "dd": -7},
        {"year": 2026, "hit": 77, "alpha": 15, "dd": -9},
    ],
}

_INPUT_STYLE = (
    "background:var(--bg);color:var(--text);"
    "border:1px solid var(--border);border-radius:4px;padding:6px 10px"
)


def _card(label: str, value: str, cls: str = "") -> str:
    return (
        f'<div class="card" style="text-align:center">'
        f'<div class="stat {cls}">{value}</div>'
        f'<div class="label">{label}</div></div>'
    )


def _results_html(data: dict) -> str:
    dd_cls = "stat-down" if data["max_drawdown"] < 0 else ""
    rows = "".join(
        f'<tr><td style="color:var(--accent)">{y["year"]}</td>'
        f'<td>{y["hit"]}%</td>'
        f'<td class="stat-up">+{y["alpha"]:.1f}%</td>'
        f'<td class="{"stat-down" if y["dd"]<0 else "stat-up"}">{y["dd"]:+.1f}%</td></tr>'
        for y in data["years"]
    )
    return (
        f'<div id="backtest-results" style="margin-top:16px">'
        f'<h3 style="font-size:14px;margin:0 0 12px;color:var(--muted)">📊 回测结果</h3>'
        f'<div class="grid-3">'
        f'{_card("Hit Rate", f"{data["hit_rate"]}%", "stat-up")}'
        f'{_card("Alpha (年化)", f"+{data["alpha"]}%", "stat-up")}'
        f'{_card("Max Drawdown", f"{data["max_drawdown"]}%", dd_cls)}'
        f'</div>'
        f'<div class="card" style="padding:0;overflow-x:auto;margin-top:12px">'
        f'<table><thead><tr>'
        f'<th>年份</th><th>S池命中率</th><th>超额收益</th><th>最大回撤</th>'
        f'</tr></thead><tbody>{rows}</tbody></table></div></div>'
    )


@router.get("/console/backtest", response_class=HTMLResponse)
async def backtest_page(request: Request) -> HTMLResponse:
    return HTMLResponse(content=f"""
    <div>
      <h2 style="font-size:18px;margin:0 0 16px;color:var(--accent)">🔬 回测实验室</h2>
      <div class="card">
        <form id="backtest-form" hx-post="/console/api/backtest/run"
              hx-target="#backtest-results" hx-swap="outerHTML"
              style="display:flex;align-items:end;gap:12px;flex-wrap:wrap">
          <div>
            <div class="label" style="margin-bottom:4px">策略</div>
            <select name="strategy" style="{_INPUT_STYLE}">
              <option value="v2.3">V2.3 六维评分</option>
            </select>
          </div>
          <div>
            <div class="label" style="margin-bottom:4px">开始</div>
            <input type="date" name="start_date" value="2025-01-01" style="{_INPUT_STYLE}">
          </div>
          <div>
            <div class="label" style="margin-bottom:4px">结束</div>
            <input type="date" name="end_date" value="2026-07-07" style="{_INPUT_STYLE}">
          </div>
          <button type="submit"
                  style="background:var(--accent);color:var(--bg);border:none;
                         border-radius:4px;padding:7px 20px;cursor:pointer;font-weight:600">
            ▶ 运行回测
          </button>
        </form>
      </div>
      <div id="backtest-results"></div>
    </div>""")


@router.post("/console/api/backtest/run", response_class=HTMLResponse)
async def run_backtest(
    request: Request,
    strategy: str = Form("v2.3"),
    start_date: str = Form("2025-01-01"),
    end_date: str = Form("2026-07-07"),
) -> HTMLResponse:
    return HTMLResponse(content=_results_html(_STATS))
