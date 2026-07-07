"""
FenJue Console — Charts route (simple: stock selector + 1 Chart.js line chart).
All data hardcoded; no DB dependencies.
"""
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/console", tags=["charts"])

# ── Hardcoded stocks ──────────────────────────────────────────────────────
STOCKS = [
    {"code": "600141", "name": "兴发集团"},
    {"code": "600206", "name": "有研新材"},
    {"code": "002409", "name": "雅克科技"},
    {"code": "600584", "name": "长电科技"},
    {"code": "002428", "name": "云南锗业"},
]

DATES = ["07-01", "07-02", "07-03", "07-04", "07-05", "07-06", "07-07"]

# Per-stock 7-day data: {code: {"total": [...], "industry": [...]}}
CHART_DATA = {
    "600141": {"total": [7.0, 7.1, 7.2, 7.3, 7.4, 7.5, 7.5], "industry": [6.5, 6.7, 6.8, 7.0, 7.2, 7.3, 7.4]},
    "600206": {"total": [5.5, 5.8, 6.0, 6.3, 6.5, 6.4, 6.2], "industry": [4.5, 4.8, 5.0, 5.2, 5.5, 5.3, 5.1]},
    "002409": {"total": [6.0, 6.2, 6.5, 6.8, 7.0, 7.2, 7.3], "industry": [5.0, 5.3, 5.5, 5.8, 6.0, 6.2, 6.4]},
    "600584": {"total": [4.5, 4.7, 5.0, 5.2, 5.5, 5.3, 5.0], "industry": [3.5, 3.8, 4.0, 4.2, 4.5, 4.3, 4.0]},
    "002428": {"total": [8.0, 8.1, 8.3, 8.5, 8.6, 8.4, 8.2], "industry": [7.0, 7.2, 7.5, 7.6, 7.8, 7.5, 7.2]},
}

# ── HTML fragment ─────────────────────────────────────────────────────────
CHARTS_HTML = """\
<div id="charts-page">
  <div class="card" style="margin-bottom:16px">
    <div class="card-title">📈 评分图表</div>
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">
      <label style="color:var(--muted);font-size:11px">股票:</label>
      <select id="chart-stock-select"
              style="background:var(--bg);color:var(--text);border:1px solid var(--border);
                     border-radius:4px;padding:6px 10px;font-family:inherit;font-size:13px;
                     min-width:200px"
              onchange="loadStockChart(this.value)">
        {% for s in stocks %}
        <option value="{{ s.code }}" {% if s.code == default_code %}selected{% endif %}>
          {{ s.code }} {{ s.name }}
        </option>
        {% endfor %}
      </select>
      <span id="chart-status" style="color:var(--muted);font-size:11px"></span>
    </div>
  </div>

  <div class="card" style="position:relative;min-height:360px">
    <div class="card-title">📉 评分趋势 (7日)</div>
    <div style="position:relative;height:300px">
      <canvas id="scoreChart"></canvas>
    </div>
  </div>
</div>

<script>
const C = {
  accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#00d4aa',
  text: getComputedStyle(document.documentElement).getPropertyValue('--text').trim() || '#c0c0d0',
  muted: getComputedStyle(document.documentElement).getPropertyValue('--muted').trim() || '#606078',
  bg: getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() || '#0a0a0f',
  card: getComputedStyle(document.documentElement).getPropertyValue('--card').trim() || '#141420',
  border: getComputedStyle(document.documentElement).getPropertyValue('--border').trim() || '#252540',
};

Chart.defaults.color = C.text;
Chart.defaults.borderColor = C.border;
Chart.defaults.font.family = "'SF Mono','JetBrains Mono',monospace";
Chart.defaults.font.size = 11;

let scoreChart = null;

function hexToRgba(hex, alpha) {
  const h = hex.replace('#', '');
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

async function loadStockChart(code) {
  const statusEl = document.getElementById('chart-status');
  statusEl.textContent = '⏳ 加载中...';
  try {
    const resp = await fetch('/console/api/chart-data?code=' + encodeURIComponent(code));
    if (!resp.ok) throw new Error(resp.status + ' ' + resp.statusText);
    const data = await resp.json();
    renderLineChart(data.dates, data.total, data.industry);
    statusEl.textContent = '✅';
  } catch (err) {
    statusEl.textContent = '❌ 加载失败: ' + err.message;
  }
}

function renderLineChart(labels, totals, industries) {
  const ctx = document.getElementById('scoreChart').getContext('2d');
  if (scoreChart) scoreChart.destroy();
  scoreChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: '总分',
          data: totals,
          borderColor: '#00d4aa',
          backgroundColor: hexToRgba('#00d4aa', 0.1),
          borderWidth: 2,
          tension: 0.3,
          fill: true,
          pointRadius: 3,
          pointHoverRadius: 5,
        },
        {
          label: '产业趋势分',
          data: industries,
          borderColor: '#4a9eff',
          backgroundColor: hexToRgba('#4a9eff', 0.1),
          borderWidth: 2,
          tension: 0.3,
          fill: true,
          pointRadius: 3,
          pointHoverRadius: 5,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: 'index' },
      plugins: {
        legend: {
          labels: { usePointStyle: true, padding: 20, color: C.text, font: { size: 10 } },
        },
        tooltip: {
          backgroundColor: C.card, titleColor: C.text, bodyColor: C.text,
          borderColor: C.border, borderWidth: 1,
        },
      },
      scales: {
        x: {
          grid: { color: hexToRgba(C.border, 0.3) },
          ticks: { color: C.muted, font: { size: 9 } },
        },
        y: {
          min: 4, max: 9,
          grid: { color: hexToRgba(C.border, 0.3) },
          ticks: { color: C.muted, font: { size: 9 }, stepSize: 0.5 },
        },
      },
    },
  });
}

(function() {
  const sel = document.getElementById('chart-stock-select');
  if (sel && sel.value) loadStockChart(sel.value);
})();
</script>
"""


# ── Routes ────────────────────────────────────────────────────────────────

@router.get("/charts", response_class=HTMLResponse)
async def charts_page():
    from jinja2 import Template
    html = Template(CHARTS_HTML).render(stocks=STOCKS, default_code=STOCKS[0]["code"])
    return HTMLResponse(html)


@router.get("/api/chart-data")
async def chart_data(code: str = Query(..., description="Stock code, e.g. 600141")):
    d = CHART_DATA.get(code, {"total": [], "industry": []})
    return {"dates": DATES, "total": d["total"], "industry": d["industry"]}
