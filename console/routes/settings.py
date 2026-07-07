"""
FenJue Console — Settings page.
Reads fenjue.yaml, renders editable HTML form, saves back on POST.
"""
from pathlib import Path
import math

import yaml
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config" / "fenjue.yaml"

WEIGHT_LABELS = {
    "industry_trend": "产业趋势",
    "capital_flow": "资金流向",
    "institutional": "机构持仓",
    "margin": "融资盘",
    "quantitative": "量化控盘",
    "expectation": "预期兑现",
}

WEIGHT_HELP = {
    "industry_trend": "代码自动查产业链映射树，匹配到AI材料/半导体等产业得分。不用你填数据。",
    "capital_flow": "基于换手率：3-10%正常得8分，>20%过热得3分，<1%冷清得4分。自动算。",
    "institutional": "暂用默认值5分，后续接东方财富机构持仓数据。调这个影响小。",
    "margin": "暂用默认值5分，后续接融资融券数据。当前不依赖外部接口。",
    "quantitative": "暂用默认值5分，后续接龙虎榜量化席位数据。权重小(×0.05)，影响微。",
    "expectation": "基于近20日涨幅：<5%得9分，5-15%得7分，15-30%得5分，>30%得3分。自动算。",
}

REGIME_LABELS = {
    "risk_on": "激进 (Risk-On)",
    "risk_neutral": "中性 (Neutral)",
    "risk_off": "防御 (Risk-Off)",
    "crisis": "避险 (Crisis)",
}

# ── helpers ──────────────────────────────────────────────────

def _stars_to_int(star_str: str) -> int:
    """★★★★★ → 5, ★★☆☆☆ → 2"""
    return star_str.count("★")


def _int_to_stars(n: int) -> str:
    """5 → ★★★★★, 2 → ★★☆☆☆"""
    return "★" * n + "☆" * (5 - n)


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _save_config(data: dict) -> None:
    with open(_CONFIG_PATH, "w", encoding="utf-8") as fh:
        yaml.dump(
            data,
            fh,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            width=120,
        )


# ── router ───────────────────────────────────────────────────

router = APIRouter()


@router.get("/console/settings", response_class=HTMLResponse)
async def get_settings():
    cfg = _load_config()

    # scoring weights
    weights = cfg.get("scoring", {}).get("weights", {})
    tiers = cfg.get("scoring", {}).get("tiers", {})

    # regime
    regime = cfg.get("regime", {})

    # industry tree — top-level only
    industry_tree = cfg.get("industry_tree", {})

    return _render_settings_html(weights, tiers, regime, industry_tree)


@router.post("/console/api/settings/save")
async def save_settings(request: Request):
    form = await request.form()
    cfg = _load_config()

    # ── 1. scoring weights ──
    weight_keys = list(WEIGHT_LABELS.keys())
    new_weights = {}
    for key in weight_keys:
        val = float(str(form.get(f"weight_{key}", 0)))
        new_weights[key] = round(val, 4)

    # validate sum ≈ 1.0
    total = sum(new_weights.values())
    if abs(total - 1.0) > 0.01:
        return HTMLResponse(
            _toast(f"❌ 权重合计 {total:.4f}，必须为 1.0", "error"),
            status_code=400,
        )

    cfg["scoring"]["weights"] = new_weights

    # ── 2. pool tiers ──
    cfg["scoring"]["tiers"] = {
        "s_pool": float(str(form.get("tier_s_pool", 7.5))),
        "a_pool": float(str(form.get("tier_a_pool", 6.5))),
        "b_pool": float(str(form.get("tier_b_pool", 5.0))),
    }

    # ── 3. regime ──
    for regime_key in REGIME_LABELS:
        max_pos_pct = float(str(form.get(f"regime_{regime_key}_max_position", 100)))
        sector_mult = float(str(form.get(f"regime_{regime_key}_sector_multiplier", 1.0)))
        cfg["regime"][regime_key] = {
            "max_position": round(max_pos_pct / 100.0, 2),
            "sector_multiplier": round(sector_mult, 4),
        }

    # ── 4. industry weights ──
    industry_names = list(cfg.get("industry_tree", {}).keys())
    for name in industry_names:
        safe_name = name.replace(" ", "_")
        heat_val = int(float(str(form.get(f"ind_heat_{safe_name}", 3))))
        weight_val = float(str(form.get(f"ind_weight_{safe_name}", 1.0)))
        stage_val = str(form.get(f"ind_stage_{safe_name}", cfg["industry_tree"][name].get("stage", "")))
        cfg["industry_tree"][name]["heat"] = _int_to_stars(heat_val)
        cfg["industry_tree"][name]["weight"] = round(weight_val, 4)
        cfg["industry_tree"][name]["stage"] = stage_val

    _save_config(cfg)

    # reload and re-render to show updated values
    cfg2 = _load_config()
    weights2 = cfg2.get("scoring", {}).get("weights", {})
    tiers2 = cfg2.get("scoring", {}).get("tiers", {})
    regime2 = cfg2.get("regime", {})
    industry_tree2 = cfg2.get("industry_tree", {})

    html = _render_settings_html(weights2, tiers2, regime2, industry_tree2)
    toast_html = _toast("✓ 已保存", "success")
    return HTMLResponse(toast_html + html)


# ── HTML renderers ───────────────────────────────────────────

def _toast(message: str, kind: str = "success") -> str:
    color = "var(--accent)" if kind == "success" else "var(--danger)"
    return f"""
<div id="toast" style="
  position:fixed;top:12px;right:20px;z-index:9999;
  background:var(--card);border:1px solid {color};color:{color};
  padding:10px 18px;border-radius:6px;font-size:13px;
  opacity:1;transition:opacity .4s;
" onload="setTimeout(()=>this.remove(),2500)">{message}</div>
"""


def _render_stars(name: str, current: int) -> str:
    """Render 5 clickable stars that toggle ★/☆"""
    stars_html = ""
    for i in range(1, 6):
        filled = i <= current
        cls = "star" if filled else "star-empty"
        sym = "★" if filled else "☆"
        stars_html += (
            f'<span class="{cls}" style="cursor:pointer;font-size:15px" '
            f'onclick="toggleStar(this,\'{name}\',{i})">{sym}</span>'
        )
    stars_html += f'<input type="hidden" name="{name}" id="{name}" value="{current}">'
    return stars_html


def _render_settings_html(
    weights: dict,
    tiers: dict,
    regime: dict,
    industry_tree: dict,
) -> str:
    # ── Section A: Scoring Weights ──
    weight_rows = ""
    for key, label in WEIGHT_LABELS.items():
        val = weights.get(key, 0)
        pct = int(val * 100)
        help_text = WEIGHT_HELP.get(key, "")
        weight_rows += f"""
        <div style="margin:14px 0">
          <div style="display:flex;align-items:center">
            <div style="width:110px;font-size:12px;color:var(--text)">{label}</div>
            <input type="range" name="weight_{key}" min="0" max="100" value="{pct}"
              style="flex:1;margin:0 12px;accent-color:var(--accent)"
              oninput="this.nextElementSibling.value=(this.value/100).toFixed(2)">
            <output style="width:45px;text-align:right;font-size:12px;color:var(--accent)">{(pct/100):.2f}</output>
          </div>
          <div style="font-size:10px;color:var(--muted);margin:2px 0 0 110px;line-height:1.4">💡 {help_text}</div>
        </div>"""

    # tier sliders
    tier_rows = ""
    tier_cfg = [
        ("tier_s_pool", "S池阈值", tiers.get("s_pool", 7.5)),
        ("tier_a_pool", "A池阈值", tiers.get("a_pool", 6.5)),
        ("tier_b_pool", "B池阈值", tiers.get("b_pool", 5.0)),
    ]
    for tkey, tlabel, tval in tier_cfg:
        tier_rows += f"""
        <div style="display:flex;align-items:center;margin:14px 0">
          <div style="width:110px;font-size:12px;color:var(--text)">{tlabel}</div>
          <input type="range" name="{tkey}" min="0" max="10" step="0.1" value="{tval}"
            style="flex:1;margin:0 12px;accent-color:var(--accent)"
            oninput="this.nextElementSibling.value=parseFloat(this.value).toFixed(1)">
          <output style="width:30px;text-align:right;font-size:12px;color:var(--accent)">{tval:.1f}</output>
        </div>"""

    # ── Section B: Regime ──
    regime_rows = ""
    for rkey, rlabel in REGIME_LABELS.items():
        r = regime.get(rkey, {})
        mp = int(r.get("max_position", 0) * 100)
        sm = r.get("sector_multiplier", 1.0)
        regime_rows += f"""
        <div class="card" style="margin-bottom:10px">
          <div class="card-title">{rlabel}</div>
          <div style="display:flex;align-items:center;margin:10px 0">
            <span style="width:70px;font-size:11px;color:var(--muted)">仓位上限</span>
            <input type="range" name="regime_{rkey}_max_position" min="0" max="100" step="5" value="{mp}"
              style="flex:1;margin:0 10px;accent-color:var(--accent)"
              oninput="this.nextElementSibling.textContent=this.value+'%'">
            <output style="width:40px;text-align:right;font-size:12px;color:var(--accent)">{mp}%</output>
          </div>
          <div style="display:flex;align-items:center;margin:10px 0">
            <span style="width:70px;font-size:11px;color:var(--muted)">产业乘数</span>
            <input type="range" name="regime_{rkey}_sector_multiplier" min="0.5" max="1.5" step="0.01" value="{sm}"
              style="flex:1;margin:0 10px;accent-color:var(--accent)"
              oninput="this.nextElementSibling.value=parseFloat(this.value).toFixed(2)">
            <output style="width:40px;text-align:right;font-size:12px;color:var(--accent)">{sm:.2f}</output>
          </div>
        </div>"""

    # ── Section C: Industry Weights ──
    industry_rows = ""
    for name, data in industry_tree.items():
        safe_name = name.replace(" ", "_")
        heat_str = data.get("heat", "★★★☆☆")
        heat_int = _stars_to_int(heat_str)
        weight = data.get("weight", 1.0)
        stage = data.get("stage", "")
        stars_html = _render_stars(f"ind_heat_{safe_name}", heat_int)
        industry_rows += f"""
        <tr>
          <td style="color:var(--text)">{name}</td>
          <td>{stars_html}</td>
          <td>
            <input type="number" name="ind_weight_{safe_name}" value="{weight}"
              step="0.01" min="0" max="2"
              style="width:70px;background:var(--card);border:1px solid var(--border);
              color:var(--accent);padding:3px 6px;border-radius:3px;font-size:12px;text-align:center">
          </td>
          <td>
            <input type="text" name="ind_stage_{safe_name}" value="{stage}"
              style="width:80px;background:var(--card);border:1px solid var(--border);
              color:var(--text);padding:3px 6px;border-radius:3px;font-size:12px">
          </td>
        </tr>"""

    # ── weight sum display ──
    weight_sum_pct = int(sum(weights.values()) * 100)

    return f"""
<!-- Settings Page -->
<div>
  <h2 style="font-size:18px;margin-bottom:4px">⚙️ 参数配置</h2>
  <p style="color:var(--muted);font-size:11px;margin-bottom:8px">调整评分权重、市场状态与产业雷达。拖动滑块后点底部「保存设置」即刻生效。</p>
  <div style="background:rgba(0,212,170,0.06);border-left:2px solid var(--accent);padding:10px 14px;margin-bottom:20px;border-radius:0 6px 6px 0;font-size:11px;color:var(--muted);line-height:1.6">
    <strong style="color:var(--accent)">💡 不知道怎么调？保持默认就行。</strong><br>
    产业趋势和资金流向是自动算的（代码自动查产业链+换手率），你不用管。<br>
    机构/融资/量化目前用默认值，后续接数据源后会自动更新。<br>
    想微调的话，只动「产业趋势」和「预期兑现」的权重就好，其他影响很小。
  </div>

  <form id="settings-form"
    hx-post="/console/api/settings/save"
    hx-target="#content"
    hx-swap="outerHTML"
    hx-indicator="#save-btn">

    <!-- ── A. Scoring Weights ── -->
    <div class="card">
      <div class="card-title">评分权重</div>
      {weight_rows}
      {tier_rows}
    </div>

    <!-- ── B. Regime ── -->
    <div class="card">
      <div class="card-title">市场状态</div>
      <div class="grid-2">
        {regime_rows}
      </div>
    </div>

    <!-- ── C. Industry Weights ── -->
    <div class="card">
      <div class="card-title">产业雷达</div>
      <table>
        <thead>
          <tr>
            <th>产业</th>
            <th>热度</th>
            <th>权重</th>
            <th>阶段</th>
          </tr>
        </thead>
        <tbody>
          {industry_rows}
        </tbody>
      </table>
    </div>

    <!-- ── D. Save ── -->
    <div style="margin-top:16px;display:flex;align-items:center;gap:12px">
      <button id="save-btn" type="submit"
        style="background:var(--accent);color:var(--bg);border:none;
        padding:10px 28px;border-radius:6px;font-weight:600;font-size:13px;cursor:pointer;
        font-family:inherit">
        💾 保存设置
      </button>
      <span class="htmx-indicator" style="color:var(--muted);font-size:11px">
        保存中...
      </span>
    </div>
  </form>
</div>

<script>
// ── Star toggle ──
function toggleStar(el, name, value) {{
  const container = el.parentElement;
  const current = parseInt(document.getElementById(name).value);
  // clicking the same star again deselects to one below
  const newVal = (value === current && current > 0) ? value - 1 : value;
  document.getElementById(name).value = newVal;
  // update all 5 stars in this group
  const stars = container.querySelectorAll('span[onclick]');
  stars.forEach((s, i) => {{
    if (i < newVal) {{
      s.className = 'star';
      s.textContent = '★';
    }} else {{
      s.className = 'star-empty';
      s.textContent = '☆';
    }}
  }});
}}

// ── Real-time weight sum tracker ──
(function() {{
  const sliders = document.querySelectorAll('input[name^="weight_"]');
  const display = document.getElementById('weight-sum-display');
  function updateSum() {{
    let sum = 0;
    sliders.forEach(s => sum += parseInt(s.value));
    display.textContent = '合计: ' + sum + '%';
    display.style.color = (sum === 100) ? 'var(--accent)' : 'var(--danger)';
  }}
  sliders.forEach(s => s.addEventListener('input', updateSum));
}})();
</script>
"""
