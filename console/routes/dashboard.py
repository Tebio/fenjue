"""
Dashboard route — market status cards + industry radar + watchlist table.

Returns an HTML fragment (not a full page) intended for the #content div.
Calls Engine API at http://localhost:8001 for /regime and /watchlist.
Falls back to placeholder data when the API is unreachable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import yaml

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

# ---------------------------------------------------------------------------
# Paths & engine URL
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config" / "fenjue.yaml"
_ENGINE_URL = "http://localhost:8001"


def _load_config() -> dict[str, Any]:
    """Load fenjue.yaml, returning empty dict on failure."""
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Default / fallback data (used when engine API is unreachable)
# ---------------------------------------------------------------------------
_DEFAULT_REGIME: dict[str, Any] = {
    "current": "risk_neutral",
    "max_position": 0.60,
    "sector_multiplier": 1.05,
    "capital_style": "balanced",
    "tier_counts": {"S": 3, "A": 8, "B": 15},
}

_DEFAULT_WATCHLIST: list[dict[str, Any]] = [
    {
        "code": "600141", "name": "兴发集团", "price": 18.52, "total": 8.2,
        "tier": "S", "odds": 3.5, "win_rate": 0.65, "cycle": "1-3月",
        "expectation_gap": 0.12,
    },
    {
        "code": "002428", "name": "云南锗业", "price": 15.80, "total": 7.8,
        "tier": "S", "odds": 2.8, "win_rate": 0.60, "cycle": "1-3月",
        "expectation_gap": 0.08,
    },
    {
        "code": "600206", "name": "有研新材", "price": 12.30, "total": 7.5,
        "tier": "A", "odds": 2.2, "win_rate": 0.55, "cycle": "3-6月",
        "expectation_gap": 0.05,
    },
    {
        "code": "002409", "name": "雅克科技", "price": 42.10, "total": 7.2,
        "tier": "A", "odds": 2.0, "win_rate": 0.52, "cycle": "3-6月",
        "expectation_gap": 0.03,
    },
    {
        "code": "600584", "name": "长电科技", "price": 28.60, "total": 6.8,
        "tier": "A", "odds": 1.8, "win_rate": 0.50, "cycle": "6月+",
        "expectation_gap": 0.02,
    },
    {
        "code": "002384", "name": "东山精密", "price": 22.40, "total": 6.5,
        "tier": "B", "odds": 1.5, "win_rate": 0.45, "cycle": "6月+",
        "expectation_gap": 0.01,
    },
    {
        "code": "688716", "name": "中研股份", "price": 35.20, "total": 6.2,
        "tier": "B", "odds": 1.3, "win_rate": 0.40, "cycle": "6月+",
        "expectation_gap": -0.02,
    },
    {
        "code": "600072", "name": "中船科技", "price": 19.80, "total": 5.8,
        "tier": "B", "odds": 1.2, "win_rate": 0.38, "cycle": "6月+",
        "expectation_gap": -0.05,
    },
]

_DEFAULT_INDUSTRIES: list[dict[str, Any]] = [
    {"name": "AI材料",  "heat": "★★★★★", "weight": 1.05, "stage": "主升初期"},
    {"name": "半导体",  "heat": "★★★★☆", "weight": 1.00, "stage": "发酵期"},
    {"name": "机器人",  "heat": "★★★☆☆", "weight": 0.85, "stage": "调整蓄势"},
    {"name": "军工电子", "heat": "★★★☆☆", "weight": 1.00, "stage": "蓄势期"},
    {"name": "新能源",  "heat": "★☆☆☆☆", "weight": 0.70, "stage": "低谷期"},
]

_REGIME_LABELS: dict[str, str] = {
    "risk_on":      "Risk-On",
    "risk_neutral": "风险中性",
    "risk_off":     "Risk-Off",
    "crisis":       "Crisis",
}

_REGIME_CLASS: dict[str, str] = {
    "risk_on":      "stat-up",
    "risk_neutral": "",
    "risk_off":     "stat-down",
    "crisis":       "stat-down",
}


# ---------------------------------------------------------------------------
# Helpers — HTML builders (pure functions, no side effects)
# ---------------------------------------------------------------------------

def _parse_stars(heat: str) -> list[tuple[str, str]]:
    """Parse a heat string e.g. '★★★☆☆' → [(★,star), (★,star), …, (☆,star-empty)].

    Returns list of (character, css_class) tuples.
    """
    result: list[tuple[str, str]] = []
    for ch in heat:
        if ch == "★":
            result.append((ch, "star"))
        elif ch == "☆":
            result.append((ch, "star-empty"))
        # ignore any other character
    return result


def _build_regime_cards(regime: dict[str, Any]) -> str:
    """Row 1 — Four market-status cards in grid-4."""
    current = regime.get("current", "risk_neutral")
    max_pos = regime.get("max_position", 0.60)
    cap_style = regime.get("capital_style", "balanced")
    mult = regime.get("sector_multiplier", 1.05)
    label = _REGIME_LABELS.get(current, current)
    rc = _REGIME_CLASS.get(current, "")

    # "量化主导" star rating based on regime confidence
    star_count = 5 if current == "risk_on" else 4 if current == "risk_neutral" else 3
    quant_stars = "".join("★" for _ in range(star_count))

    # "纳指参考" label
    nasdaq_label = {"risk_on": "上行", "risk_neutral": "震荡", "risk_off": "承压", "crisis": "暴跌"}

    return f"""
    <div class="grid-4">
      <div class="card">
        <div class="card-title">市场状态</div>
        <div class="stat {rc}">{label}</div>
        <div class="label">资本风格: {cap_style}</div>
      </div>
      <div class="card">
        <div class="card-title">仓位上限</div>
        <div class="stat">{int(max_pos * 100)}%</div>
        <div class="label">单票上限: {int(max_pos * 50)}%</div>
      </div>
      <div class="card">
        <div class="card-title">量化主导</div>
        <div class="stat" style="color:var(--accent)">{quant_stars}</div>
        <div class="label">量价信号强度</div>
      </div>
      <div class="card">
        <div class="card-title">纳指参考</div>
        <div class="stat">{nasdaq_label.get(current, "震荡")}</div>
        <div class="label">联动系数: {mult:.2f}x</div>
      </div>
    </div>
    """


def _build_industry_radar(regime_mult: float) -> str:
    """Row 2 — Five industry radar cards (grid-5 via inline style).

    Loads industries from fenjue.yaml's ``industry_tree``; falls back to
    ``_DEFAULT_INDUSTRIES``.  Applies the regime multiplier to show
    adjusted (or unadjusted, when weight differs) sector weights.
    """
    config = _load_config()
    industry_tree: dict = config.get("industry_tree", {})

    if industry_tree:
        industries: list[dict[str, Any]] = []
        for name, info in industry_tree.items():
            raw_weight = info.get("weight", 1.0)
            industries.append({
                "name": name,
                "heat": info.get("heat", "☆☆☆☆☆"),
                "weight": raw_weight,
                "stage": info.get("stage", ""),
                "adjusted": round(raw_weight * regime_mult, 2),
            })
    else:
        industries = []
        for ind in _DEFAULT_INDUSTRIES:
            ind_copy = dict(ind)
            ind_copy["adjusted"] = round(ind_copy["weight"] * regime_mult, 2)
            industries.append(ind_copy)

    cards_html = '<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:12px">\n'

    for ind in industries[:5]:
        stars = _parse_stars(ind["heat"])
        stars_html = "".join(
            f'<span class="{cls}">{ch}</span>' for ch, cls in stars
        )
        adjusted = ind.get("adjusted", ind["weight"])
        adj_class = (
            "stat-down" if adjusted < ind["weight"]
            else "stat-up" if adjusted > ind["weight"]
            else ""
        )

        cards_html += f"""
      <div class="card" style="text-align:center">
        <div class="card-title">{ind['name']}</div>
        <div style="font-size:18px;margin:8px 0">{stars_html}</div>
        <div class="stat {adj_class}" style="font-size:18px">×{adjusted:.2f}</div>
        <div class="label">{ind['stage']}</div>
      </div>"""

    cards_html += "\n    </div>"
    return cards_html


def _build_watchlist_table(watchlist: list[dict[str, Any]]) -> str:
    """Row 3 — Watchlist table with S/A/B rows; S rows get accent highlight."""
    rows_html = ""

    for item in watchlist:
        tier = item.get("tier", "B")
        code = item.get("code", "")
        name = item.get("name", "")
        price = item.get("price")
        total = item.get("total", 0)
        odds = item.get("odds", 0)
        win_rate = item.get("win_rate", 0)
        cycle = item.get("cycle", "")
        gap = item.get("expectation_gap", item.get("gap", 0))

        badge_cls = {"S": "badge-s", "A": "badge-a", "B": "badge-b"}.get(tier, "badge-b")

        price_str = f"{price:.2f}" if price is not None else "—"
        total_str = f"{total:.1f}" if total else "—"
        odds_str = f"{odds:.1f}x" if odds else "—"
        win_str = f"{int(win_rate * 100)}%" if win_rate else "—"
        gap_str = f"{gap:+.2f}" if gap else "—"
        gap_class = "stat-up" if gap and gap > 0 else "stat-down" if gap and gap < 0 else ""

        # Simulated score change (real data would diff against previous day)
        change_val = 0.3 if tier == "S" else 0.2 if tier == "A" else -0.1
        change_class = "stat-up" if change_val > 0 else "stat-down"

        row_style = ' style="background:rgba(0,212,170,0.08)"' if tier == "S" else ""

        rows_html += f"""
        <tr{row_style}>
          <td><span class="{badge_cls}">{tier}</span></td>
          <td style="color:var(--accent)">{code}</td>
          <td>{name}</td>
          <td>{price_str}</td>
          <td style="font-weight:600">{total_str}</td>
          <td class="{change_class}">{change_val:+.1f}</td>
          <td>{odds_str}</td>
          <td>{win_str}</td>
          <td class="{gap_class}">{gap_str}</td>
          <td style="color:var(--muted)">{cycle}</td>
        </tr>"""

    return f"""
    <table>
      <thead>
        <tr>
          <th>池</th><th>代码</th><th>名称</th><th>现价</th>
          <th>总分</th><th>变化</th><th>赔率</th><th>胜率</th>
          <th>认知差</th><th>兑现周期</th>
        </tr>
      </thead>
      <tbody>{rows_html}
      </tbody>
    </table>
    """


def _build_score_changes(watchlist: list[dict[str, Any]]) -> str:
    """Bottom row — score-change summary derived from watchlist data."""
    items: list[str] = []
    for item in watchlist:
        tier = item.get("tier", "")
        code = item.get("code", "")
        name = item.get("name", "")
        # Simulated delta — real impl would diff daily_score rows
        if tier == "S":
            delta = 0.3
        elif tier == "A":
            delta = 0.2
        else:
            delta = -0.1
        arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        cls = "stat-up" if delta > 0 else "stat-down"
        items.append(
            f'<span class="{cls}" style="white-space:nowrap">'
            f"{code} {name} {arrow}{abs(delta):.1f}</span>"
        )

    items_html = "\n        ".join(items)
    return f"""
    <div class="card" style="margin-top:16px">
      <div class="card-title">今日评分变化</div>
      <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:12px">
        {items_html}
      </div>
    </div>
    """


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/console/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """Return the full dashboard HTML fragment for the #content div.

    Fetches /regime and /watchlist from the Engine API; gracefully degrades
    to hardcoded placeholder data when the API is not reachable.
    """
    regime: dict[str, Any] = dict(_DEFAULT_REGIME)
    watchlist: list[dict[str, Any]] = list(_DEFAULT_WATCHLIST)

    # ── try the real engine API ──────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Regime
            try:
                resp = await client.get(f"{_ENGINE_URL}/regime")
                if resp.status_code == 200:
                    regime = resp.json()
            except Exception:
                pass

            # Watchlist
            try:
                resp = await client.get(f"{_ENGINE_URL}/watchlist")
                if resp.status_code == 200:
                    watchlist = resp.json()
            except Exception:
                pass
    except Exception:
        pass

    # ── assemble HTML ────────────────────────────────────────────────────
    regime_cards   = _build_regime_cards(regime)
    industry_radar = _build_industry_radar(regime.get("sector_multiplier", 1.05))
    wl_table       = _build_watchlist_table(watchlist)
    score_changes  = _build_score_changes(watchlist)

    tier_counts = regime.get("tier_counts", {})
    s_count = tier_counts.get("S", 0)
    a_count = tier_counts.get("A", 0)
    b_count = tier_counts.get("B", 0)

    html = f"""
    <div>
      <h2 style="font-size:18px;margin:0 0 16px;color:var(--accent)">📡 Dashboard</h2>

      <!-- Row 1: Market Status -->
      {regime_cards}

      <!-- Row 2: Industry Radar -->
      <h3 style="font-size:14px;margin:20px 0 12px;color:var(--muted)">🏭 产业雷达</h3>
      {industry_radar}

      <!-- Row 3: Watchlist -->
      <h3 style="font-size:14px;margin:20px 0 12px;color:var(--muted)">
        📋 Watchlist
        <span style="font-size:11px;font-weight:400;margin-left:8px">
          S <span class="badge-s">{s_count}</span>
          A <span class="badge-a">{a_count}</span>
          B <span class="badge-b">{b_count}</span>
        </span>
      </h3>
      <div class="card" style="padding:0;overflow-x:auto">
        {wl_table}
      </div>

      <!-- Score Changes -->
      {score_changes}
    </div>
    """

    return HTMLResponse(content=html)
