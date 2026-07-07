"""
FenJue Engine V1 — SQLite 7-table schema.

Tables:
  stocks         — 股票基础信息
  industry       — 行业树配置
  daily_score    — 每日评分快照
  watchlist      — 持仓观察池
  journal        — 交易日志
  backtest       — 回测记录
  execution_plan — 执行计划

Usage:
    from engine.database import get_db, create_tables
    create_tables()           # 建表 + 索引
    db = get_db()             # 获取连接
"""

import sqlite3
import os
from contextlib import contextmanager

# 默认数据库路径 — 可被调用方覆盖
DB_PATH = os.environ.get("FENJUE_DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "fenjue.db"))

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

DDL_STOCKS = """
CREATE TABLE IF NOT EXISTS stocks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT    NOT NULL UNIQUE,
    name       TEXT    NOT NULL,
    industry   TEXT,
    market     TEXT    CHECK(market IN ('SH','SZ','BJ','HK')) DEFAULT 'SH',
    created_at TEXT    DEFAULT (datetime('now','localtime')),
    updated_at TEXT    DEFAULT (datetime('now','localtime'))
);
"""

DDL_INDUSTRY = """
CREATE TABLE IF NOT EXISTS industry (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL UNIQUE,
    heat           TEXT,
    stage          TEXT,
    weight         REAL    DEFAULT 1.0,
    fail_condition TEXT
);
"""

DDL_DAILY_SCORE = """
CREATE TABLE IF NOT EXISTS daily_score (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_id        INTEGER NOT NULL,
    date            TEXT    NOT NULL DEFAULT (date('now','localtime')),
    total_score     REAL,
    industry_score  REAL,
    flow_score      REAL,
    inst_score      REAL,
    margin_score    REAL,
    quant_score     REAL,
    expect_score    REAL,
    expectation_gap REAL,
    confidence      REAL    CHECK(confidence >= 0),
    tier            TEXT    CHECK(tier IN ('S','A','B','C','D')),
    regime          TEXT,
    created_at      TEXT    DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (stock_id) REFERENCES stocks(id),
    UNIQUE(stock_id, date)
);
"""

DDL_WATCHLIST = """
CREATE TABLE IF NOT EXISTS watchlist (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_id   INTEGER NOT NULL UNIQUE,
    tier       TEXT    CHECK(tier IN ('S','A','B','C')),
    odds       REAL,
    win_rate   REAL    CHECK(win_rate >= 0 AND win_rate <= 1),
    cycle      TEXT,
    thesis     TEXT,
    fail_if    TEXT,
    build_plan TEXT,                  -- JSON
    added_at   TEXT    DEFAULT (datetime('now','localtime')),
    updated_at TEXT    DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (stock_id) REFERENCES stocks(id)
);
"""

DDL_JOURNAL = """
CREATE TABLE IF NOT EXISTS journal (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         TEXT    NOT NULL DEFAULT (date('now','localtime')),
    stock_id     INTEGER NOT NULL,
    action       TEXT    NOT NULL CHECK(action IN ('buy','sell','hold')),
    price        REAL,
    position_pct REAL,
    score        REAL,
    reason       TEXT,
    result       TEXT,
    created_at   TEXT    DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (stock_id) REFERENCES stocks(id)
);
"""

DDL_BACKTEST = """
CREATE TABLE IF NOT EXISTS backtest (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy     TEXT    NOT NULL,
    period       TEXT,
    hit_rate     REAL,
    alpha        REAL,
    max_drawdown REAL,
    details      TEXT,                -- JSON
    created_at   TEXT    DEFAULT (datetime('now','localtime'))
);
"""

DDL_EXECUTION_PLAN = """
CREATE TABLE IF NOT EXISTS execution_plan (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_id          INTEGER NOT NULL,
    step              INTEGER NOT NULL,
    action            TEXT    NOT NULL,
    position_pct      REAL,
    trigger_condition TEXT,
    price_range       TEXT,
    status            TEXT    DEFAULT 'pending' CHECK(status IN ('pending','triggered','executed','cancelled')),
    FOREIGN KEY (stock_id) REFERENCES stocks(id)
);
"""

# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_stocks_code   ON stocks(code);",
    "CREATE INDEX IF NOT EXISTS idx_stocks_industry ON stocks(industry);",
    "CREATE INDEX IF NOT EXISTS idx_industry_name  ON industry(name);",
    "CREATE INDEX IF NOT EXISTS idx_daily_score_stock_date ON daily_score(stock_id, date);",
    "CREATE INDEX IF NOT EXISTS idx_daily_score_date      ON daily_score(date);",
    "CREATE INDEX IF NOT EXISTS idx_daily_score_tier      ON daily_score(tier);",
    "CREATE INDEX IF NOT EXISTS idx_watchlist_stock_id ON watchlist(stock_id);",
    "CREATE INDEX IF NOT EXISTS idx_watchlist_tier    ON watchlist(tier);",
    "CREATE INDEX IF NOT EXISTS idx_journal_date      ON journal(date);",
    "CREATE INDEX IF NOT EXISTS idx_journal_stock_id  ON journal(stock_id);",
    "CREATE INDEX IF NOT EXISTS idx_backtest_strategy ON backtest(strategy);",
    "CREATE INDEX IF NOT EXISTS idx_execution_plan_stock  ON execution_plan(stock_id);",
    "CREATE INDEX IF NOT EXISTS idx_execution_plan_status ON execution_plan(status);",
]

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def create_tables(db_path: str | None = None) -> sqlite3.Connection:
    """Create all tables and indexes; returns a connection for convenience."""
    path = db_path or DB_PATH
    if path != ":memory:":
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute(DDL_STOCKS)
    conn.execute(DDL_INDUSTRY)
    conn.execute(DDL_DAILY_SCORE)
    conn.execute(DDL_WATCHLIST)
    conn.execute(DDL_JOURNAL)
    conn.execute(DDL_BACKTEST)
    conn.execute(DDL_EXECUTION_PLAN)
    for idx in INDEXES:
        conn.execute(idx)
    conn.commit()
    return conn


@contextmanager
def get_db(db_path: str | None = None, *, foreign_keys: bool = True):
    """Context-manager factory yielding a sqlite3.Connection (row_factory=Row).

    Usage:
        with get_db() as db:
            rows = db.execute("SELECT ...").fetchall()
    """
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    if foreign_keys:
        conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
