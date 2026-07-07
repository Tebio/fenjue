"""FenJue Console — Bloomberg Terminal-style control panel.
Mounts on FastAPI, serves htmx-powered single-page app.
All routes are HTML fragments rendered into base.html.
"""
import os
import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

console_app = FastAPI(title="FenJue Console")


# ============================================================
# Round 1 routes — Dashboard, Charts, Settings
# ============================================================
def _try_import_route(module_path: str, route_path: str):
    """Lazy-load route modules; ignore if not yet built."""
    try:
        mod = __import__(module_path, fromlist=["router"])
        console_app.include_router(mod.router)
        print(f"  [✓] {route_path}")
    except Exception as e:
        print(f"  [ ] {route_path} — {e}")


_try_import_route("console.routes.dashboard", "/console/dashboard")
_try_import_route("console.routes.charts", "/console/charts")
_try_import_route("console.routes.settings", "/console/settings")

# Round 2
_try_import_route("console.routes.backtest", "/console/backtest")
_try_import_route("console.routes.journal", "/console/journal")
_try_import_route("console.routes.report", "/console/report")

# Round 3
_try_import_route("console.routes.explain", "/console/explain")
_try_import_route("console.routes.auth", "/console/auth")
_try_import_route("console.routes.simulation", "/console/sim")
_try_import_route("console.routes.copilot", "/console/copilot")


# ============================================================
# Base template
# ============================================================
@console_app.get("/console")
async def console_entry():
    """Return the full SPA shell."""
    template_path = _PROJECT_ROOT / "console" / "templates" / "base.html"
    if template_path.exists():
        return __import__("fastapi.responses", fromlist=["HTMLResponse"]).HTMLResponse(
            template_path.read_text(encoding="utf-8")
        )
    return {"status": "ok", "message": "FenJue Console — load base.html"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(console_app, host="0.0.0.0", port=8002)
