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
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    NOT NULL UNIQUE,
    name        TEXT    NOT NULL,
    industry_id INTEGER REFERENCES industry(id),
    market      TEXT    CHECK(market IN ('SH','SZ','BJ','HK')) DEFAULT 'SH',
    created_at  TEXT    DEFAULT (datetime('now','localtime')),
    updated_at  TEXT    DEFAULT (datetime('now','localtime'))
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
    FOREIGN KEY (stock_id) REFERENCES stocks(id),
    UNIQUE(stock_id, step)
);
"""

# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_stocks_code   ON stocks(code);",
    "CREATE INDEX IF NOT EXISTS idx_stocks_industry_id ON stocks(industry_id);",
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

def migrate_v1_to_v2(db_path: str | None = None) -> dict:
    """Migrate DB from v1 (industry TEXT) to v2 (industry_id FK, UNIQUE constraints).

    Returns a dict with status info.  Idempotent — safe to run multiple times.
    Only performs destructive operations when strictly necessary;
    for dev-stage databases with empty dependent tables, prefers DROP+rebuild.
    """
    path = db_path or DB_PATH
    if path == ":memory:":
        return {"status": "skipped", "reason": "in-memory database"}
    if not os.path.exists(path):
        return {"status": "skipped", "reason": "database file not found"}

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON;")

    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(stocks)").fetchall()}

        # --- stocks: industry TEXT → industry_id INTEGER FK ---
        if "industry" in columns and "industry_id" not in columns:
            # 1) Insert distinct industry names into industry table
            industries = {
                row[0]: row[1] for row in
                conn.execute("SELECT DISTINCT id, industry FROM stocks WHERE industry IS NOT NULL").fetchall()
            }
            id_map = {}  # stock_id -> industry_id
            for stock_id, ind_name in industries.items():
                cur = conn.execute("SELECT id FROM industry WHERE name = ?", (ind_name,))
                row = cur.fetchone()
                if row:
                    id_map[stock_id] = row[0]
                else:
                    cur = conn.execute("INSERT INTO industry (name) VALUES (?)", (ind_name,))
                    id_map[stock_id] = cur.lastrowid

            # 2) Add industry_id column, populate, drop old industry column
            conn.execute("ALTER TABLE stocks ADD COLUMN industry_id INTEGER REFERENCES industry(id);")
            for stock_id, ind_id in id_map.items():
                conn.execute("UPDATE stocks SET industry_id = ? WHERE id = ?", (ind_id, stock_id))

            # SQLite cannot DROP COLUMN directly (before 3.35).  Rebuild table.
            # Must commit first — PRAGMA foreign_keys=OFF has no effect mid-transaction.
            conn.commit()
            conn.execute("PRAGMA foreign_keys=OFF;")
            conn.execute("""
                CREATE TABLE stocks_new (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    code        TEXT    NOT NULL UNIQUE,
                    name        TEXT    NOT NULL,
                    industry_id INTEGER REFERENCES industry(id),
                    market      TEXT    CHECK(market IN ('SH','SZ','BJ','HK')) DEFAULT 'SH',
                    created_at  TEXT    DEFAULT (datetime('now','localtime')),
                    updated_at  TEXT    DEFAULT (datetime('now','localtime'))
                );
            """)
            conn.execute("""
                INSERT INTO stocks_new (id, code, name, industry_id, market, created_at, updated_at)
                SELECT id, code, name, industry_id, market, created_at, updated_at FROM stocks;
            """)
            conn.execute("DROP TABLE stocks;")
            conn.execute("ALTER TABLE stocks_new RENAME TO stocks;")
            conn.execute("PRAGMA foreign_keys=ON;")

            # Rebuild index
            conn.execute("CREATE INDEX IF NOT EXISTS idx_stocks_code        ON stocks(code);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_stocks_industry_id ON stocks(industry_id);")
            print("[migrate] stocks: industry TEXT → industry_id FK — done")
        elif "industry_id" not in columns:
            print("[migrate] stocks: no industry column found, nothing to migrate")

        # --- execution_plan: add UNIQUE(stock_id, step) ---
        # Rebuild approach since SQLite doesn't support ALTER ADD CONSTRAINT
        plan_columns = {row[1] for row in conn.execute("PRAGMA table_info(execution_plan)").fetchall()}
        if "stock_id" in plan_columns:
            # Check if UNIQUE already exists by inspecting the CREATE TABLE SQL
            plan_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='execution_plan'"
            ).fetchone()
            if plan_sql and "UNIQUE" not in plan_sql[0]:
                conn.commit()
                conn.execute("PRAGMA foreign_keys=OFF;")
                conn.execute("""
                    CREATE TABLE execution_plan_new (
                        id                INTEGER PRIMARY KEY AUTOINCREMENT,
                        stock_id          INTEGER NOT NULL,
                        step              INTEGER NOT NULL,
                        action            TEXT    NOT NULL,
                        position_pct      REAL,
                        trigger_condition TEXT,
                        price_range       TEXT,
                        status            TEXT    DEFAULT 'pending' CHECK(status IN ('pending','triggered','executed','cancelled')),
                        FOREIGN KEY (stock_id) REFERENCES stocks(id),
                        UNIQUE(stock_id, step)
                    );
                """)
                conn.execute("""
                    INSERT INTO execution_plan_new SELECT * FROM execution_plan;
                """)
                conn.execute("DROP TABLE execution_plan;")
                conn.execute("ALTER TABLE execution_plan_new RENAME TO execution_plan;")
                conn.execute("PRAGMA foreign_keys=ON;")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_execution_plan_stock  ON execution_plan(stock_id);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_execution_plan_status ON execution_plan(status);")
                print("[migrate] execution_plan: added UNIQUE(stock_id, step) — done")

        # --- journal: FK already present in v1, verify ---
        journal_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='journal'"
        ).fetchone()
        if journal_sql and "FOREIGN KEY" not in journal_sql[0]:
            # Shouldn't happen with our schema, but handle gracefully
            conn.commit()
            conn.execute("PRAGMA foreign_keys=OFF;")
            conn.execute("""
                CREATE TABLE journal_new (
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
            """)
            conn.execute("INSERT INTO journal_new SELECT * FROM journal;")
            conn.execute("DROP TABLE journal;")
            conn.execute("ALTER TABLE journal_new RENAME TO journal;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_date     ON journal(date);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_stock_id ON journal(stock_id);")
            print("[migrate] journal: added FOREIGN KEY on stock_id — done")

        conn.commit()
        return {"status": "ok", "db_path": path}

    except Exception as e:
        conn.rollback()
        return {"status": "error", "error": str(e)}
    finally:
        conn.close()


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
