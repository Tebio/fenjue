"""Quick integration test for FenJue API endpoints."""
import os
import sys
import tempfile

sys.path.insert(0, ".")

# Create temp DB *before* importing app (so DB_PATH resolves during startup)
db_fd, db_path = tempfile.mkstemp(suffix=".db", prefix="fenjue_test_")
os.close(db_fd)
os.environ["FENJUE_DB_PATH"] = db_path

from fastapi.testclient import TestClient
from engine.database import create_tables, get_db
from api.app import app

client = TestClient(app)


def seed():
    with get_db(db_path) as db:
        db.execute(
            "INSERT INTO stocks(id,code,name,market) VALUES(1,'600141','兴发集团','SH')"
        )
        db.execute(
            """INSERT INTO daily_score(stock_id,date,total_score,
               industry_score,flow_score,inst_score,margin_score,
               quant_score,expect_score,expectation_gap,confidence,tier,regime)
               VALUES(1,date('now'),7.2,7.5,6.8,7.0,6.5,5.0,7.3,0.8,0.85,'S','risk_on')"""
        )
        db.execute(
            "INSERT INTO watchlist(stock_id,tier,odds,win_rate,cycle) VALUES(1,'S',2.5,0.65,'主升')"
        )


def test_score():
    r = client.get("/score?code=600141")
    assert r.status_code == 200, f"score failed: {r.status_code} {r.text}"
    data = r.json()
    assert data["code"] == "600141"
    assert data["total"] == 7.2
    assert data["tier"] == "S"
    assert "industry" in data["scores"]
    print(f"  GET /score?code=600141 → OK: {data['code']} tier={data['tier']} total={data['total']}")


def test_score_404():
    r = client.get("/score?code=999999")
    assert r.status_code == 404
    print("  GET /score?code=999999 → 404 OK")


def test_watchlist():
    r = client.get("/watchlist")
    assert r.status_code == 200
    wl = r.json()
    assert len(wl) == 1
    assert wl[0]["code"] == "600141"
    assert wl[0]["tier"] == "S"
    assert wl[0]["cycle"] == "主升"
    print(f"  GET /watchlist → OK: {len(wl)} items")


def test_regime():
    r = client.get("/regime")
    assert r.status_code == 200
    reg = r.json()
    assert reg["current"] == "risk_neutral"  # 1 S-tier → risk_neutral
    assert reg["max_position"] == 0.6
    assert "tier_counts" in reg
    print(f"  GET /regime → OK: {reg['current']} max_pos={reg['max_position']}")


def test_run():
    r = client.post("/run")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "count" in data
    print(f"  POST /run → OK: status={data['status']} count={data['count']}")


if __name__ == "__main__":
    try:
        with client:
            seed()
            test_score()
            test_score_404()
            test_watchlist()
            test_regime()
            test_run()
        print("\n✅ All 4 endpoints respond correctly")
    finally:
        os.unlink(db_path)
