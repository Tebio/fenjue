# FenJue Console Architecture
# All agents follow this contract.

framework:
  stack: "FastAPI + Jinja2 + htmx + Chart.js (CDN)"
  layout: "CSS Grid, single-page app"
  theme: "dark, monospace, Bloomberg-terminal style"
  responsive: "mobile-first with breakpoints"

base_template: "console/templates/base.html"
  - 3-column grid: sidebar(200px) | main(flex) | right-panel(300px)
  - sidebar: navigation links to all sections
  - main: active section content (swapped by htmx)
  - right-panel: AI Copilot / Explain (always visible)

color_palette:
  bg: "#0a0a0f"
  card: "#141420"
  border: "#252540"
  text: "#c0c0d0"
  accent: "#00d4aa"        # green — buy/success
  danger: "#ff4466"        # red — sell/danger
  warning: "#ffaa33"       # amber — neutral/caution
  muted: "#606078"

components:
  card: "bg-[card] border border-[border] rounded p-4"
  stat: "text-2xl font-mono"
  label: "text-xs text-[muted] uppercase tracking-wider"
  btn: "px-3 py-1.5 rounded text-sm border border-[border] hover:bg-[accent]/10"
  badge-s: "bg-[accent]/10 text-[accent] px-2 py-0.5 rounded text-xs"
  badge-a: "bg-[warning]/10 text-[warning] px-2 py-0.5 rounded text-xs"
  badge-b: "bg-[muted]/10 text-[muted] px-2 py-0.5 rounded text-xs"
  star: "text-[accent]"  # ★ filled
  star-empty: "text-[muted]" # ☆ empty

endpoints (each agent adds routes to console/routes/):
  GET /console/          → dashboard (Agent 1)
  GET /console/charts    → charts (Agent 2)
  GET /console/settings  → settings (Agent 3)
  GET /console/backtest  → backtest (Agent 4)
  GET /console/journal   → journal (Agent 5)
  GET /console/report    → daily report (Agent 6)
  GET /console/explain   → explain (Agent 7)
  POST /console/auth     → auth (Agent 8)
  GET /console/sim       → simulation (Agent 9)
  GET /console/copilot   → copilot (Agent 10)

data_source:
  All data from Engine API: http://localhost:8001/{score,watchlist,regime,run}
  Use fetch() in JS or httpx in routes.
