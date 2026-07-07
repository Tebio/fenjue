"""
FenJue Engine V1 — FastAPI 应用 (4 endpoints).

Endpoints:
    GET  /score?code=600141
    GET  /watchlist
    GET  /regime
    POST /run
"""

import os
import sys
from datetime import datetime
from pathlib import Path

# Ensure the project root is on the path so `engine` is importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import yaml
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from engine.database import get_db, create_tables
from engine.regime.market import MarketRegime

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CONFIG_PATH = os.environ.get("FENJUE_CONFIG", str(_PROJECT_ROOT / "config" / "fenjue.yaml"))


def _load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


_config = _load_config()
_api_cfg = _config.get("api", {})
_host = _api_cfg.get("host", "0.0.0.0")
_port = int(_api_cfg.get("port", 8001))
_cors_origins = _api_cfg.get("cors_origins", ["*"])

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="FenJue Engine V1",
    version="1.0.0",
    description="焚诀引擎 — 7-table SQLite + scoring / watchlist / regime / run",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Startup — ensure tables exist
# ---------------------------------------------------------------------------
@app.on_event("startup")
def _startup():
    create_tables()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}

# ---------------------------------------------------------------------------
# 1. GET /score?code=600141
# ---------------------------------------------------------------------------
@app.get("/score")
async def get_score(code: str = Query(..., description="Stock code, e.g. 600141")):
    """Return the latest daily score for a stock."""
    db = None
    try:
        with get_db() as db:
            # Resolve stock_id
            stock = db.execute("SELECT id, code, name FROM stocks WHERE code = ?", (code,)).fetchone()
            if stock is None:
                raise HTTPException(status_code=404, detail=f"Stock {code} not found")

            latest = db.execute(
                """SELECT total_score, industry_score, flow_score, inst_score,
                          margin_score, quant_score, expect_score,
                          expectation_gap, confidence, tier, regime
                   FROM daily_score
                   WHERE stock_id = ?
                   ORDER BY date DESC
                   LIMIT 1""",
                (stock["id"],),
            ).fetchone()

        if latest is None:
            # No score yet — return a sensible stub
            return {
                "code": stock["code"],
                "name": stock["name"],
                "total": None,
                "scores": {},
                "tier": None,
                "confidence": None,
                "message": "No score snapshot available yet",
            }

        return {
            "code": stock["code"],
            "name": stock["name"],
            "total": latest["total_score"],
            "scores": {
                "industry": latest["industry_score"],
                "flow": latest["flow_score"],
                "inst": latest["inst_score"],
                "margin": latest["margin_score"],
                "quant": latest["quant_score"],
                "expect": latest["expect_score"],
            },
            "expectation_gap": latest["expectation_gap"],
            "tier": latest["tier"],
            "confidence": latest["confidence"],
        }
    finally:
        if db is not None:
            db.close()


# ---------------------------------------------------------------------------
# 2. GET /watchlist
# ---------------------------------------------------------------------------
@app.get("/watchlist")
async def get_watchlist():
    """Return current watchlist with joined stock info."""
    with get_db() as db:
        rows = db.execute(
            """SELECT s.code, s.name,
                      w.tier, w.odds, w.win_rate, w.cycle,
                      COALESCE(
                          (SELECT d.total_score FROM daily_score d
                           WHERE d.stock_id = w.stock_id
                           ORDER BY d.date DESC LIMIT 1),
                          0
                      ) AS total
               FROM watchlist w
               JOIN stocks s ON s.id = w.stock_id
               ORDER BY w.tier, total DESC"""
        ).fetchall()

    return [
        {
            "code": r["code"],
            "name": r["name"],
            "price": None,  # live-price to be filled by market-data layer later
            "total": r["total"],
            "tier": r["tier"],
            "odds": r["odds"],
            "win_rate": r["win_rate"],
            "cycle": r["cycle"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# 3. GET /regime
# ---------------------------------------------------------------------------
@app.get("/regime")
async def get_regime():
    """Return current market regime via MarketRegime (single source of truth)."""
    with get_db() as db:
        tier_counts = db.execute(
            """SELECT tier, COUNT(*) AS cnt
               FROM daily_score
               WHERE date = (SELECT MAX(date) FROM daily_score)
               GROUP BY tier"""
        ).fetchall()

    tiers = {r["tier"]: r["cnt"] for r in tier_counts}
    result = MarketRegime(CONFIG_PATH).assess(tier_counts=tiers)

    return {
        "current": result["regime"],
        "max_position": result["max_position"],
        "sector_multiplier": result["sector_multiplier"],
        "sector_weights": {},
        "capital_style": result["capital_style"],
        "tier_counts": result["tier_counts"],
    }


# ---------------------------------------------------------------------------
# 4. POST /run
# ---------------------------------------------------------------------------
@app.post("/run")
async def trigger_run():
    """Trigger a scoring update run (stub — actual engine logic TBD)."""
    timestamp = datetime.now().isoformat()

    with get_db() as db:
        count = db.execute("SELECT COUNT(*) AS cnt FROM stocks").fetchone()["cnt"]

    return {
        "status": "ok",
        "timestamp": timestamp,
        "count": count,
        "message": f"Scoring run triggered for {count} stocks (engine logic TBD)",
    }


# ---------------------------------------------------------------------------
# Main — uvicorn entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.app:app", host=_host, port=_port, reload=True)
