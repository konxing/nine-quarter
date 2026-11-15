"""SQLite 存储层：schema、连接、幂等写入。

第一版仅用 SQLite（WAL 模式）。所有决策记录追加保存，不覆盖历史。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    code TEXT PRIMARY KEY,
    code_num TEXT NOT NULL,
    name TEXT NOT NULL,
    industry TEXT DEFAULT '',
    total_mv REAL,
    list_date TEXT DEFAULT '',
    out_date TEXT DEFAULT '',
    type TEXT DEFAULT '1',
    status TEXT DEFAULT '1',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trade_calendar (
    date TEXT PRIMARY KEY,
    is_trading_day INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_bars (
    code TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, preclose REAL,
    volume REAL, amount REAL, turn REAL,
    trade_status INTEGER DEFAULT 1,
    pct_chg REAL, pe_ttm REAL, pb_mrq REAL, is_st INTEGER DEFAULT 0,
    PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_bars_date ON daily_bars(date);

CREATE TABLE IF NOT EXISTS index_bars (
    code TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, preclose REAL,
    volume REAL, amount REAL, pct_chg REAL,
    PRIMARY KEY (code, date)
);

CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    summary TEXT DEFAULT '',
    source TEXT DEFAULT '',
    url TEXT DEFAULT '',
    publish_time TEXT DEFAULT '',
    fetched_at TEXT NOT NULL,
    scope TEXT NOT NULL,
    stock_code TEXT DEFAULT '',
    category TEXT DEFAULT 'news',
    sentiment TEXT DEFAULT '',
    horizon TEXT DEFAULT '',
    affected_codes TEXT DEFAULT '',
    verified INTEGER DEFAULT 0,
    relevant INTEGER DEFAULT 1,
    title_hash TEXT NOT NULL,
    ai_analyzed INTEGER DEFAULT 0,
    UNIQUE(title_hash, publish_time)
);

CREATE TABLE IF NOT EXISTS screen_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL UNIQUE,
    rule_version TEXT NOT NULL,
    market_env TEXT NOT NULL,
    candidates TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_decisions (
    run_date TEXT PRIMARY KEY,
    model TEXT DEFAULT '',
    ai_status TEXT NOT NULL,
    ai_raw TEXT DEFAULT '',
    market_comment TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS picks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT DEFAULT '',
    action TEXT NOT NULL,
    ref_price REAL, ref_price_time TEXT,
    reason TEXT DEFAULT '',
    bull_logic TEXT DEFAULT '',
    bear_risks TEXT DEFAULT '',
    horizon TEXT DEFAULT '',
    buy_trigger TEXT DEFAULT '',
    invalid_condition TEXT DEFAULT '',
    edge_vs_peers TEXT DEFAULT '',
    potential_level TEXT DEFAULT '',
    suggested_weight REAL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(run_date, code)
);

CREATE TABLE IF NOT EXISTS pick_outcomes (
    pick_id INTEGER NOT NULL,
    checkpoint INTEGER NOT NULL,
    eval_date TEXT NOT NULL,
    ret_pct REAL,
    industry_ret_pct REAL,
    index_ret_pct REAL,
    excess_vs_index REAL,
    PRIMARY KEY (pick_id, checkpoint)
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_date TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT DEFAULT '',
    side TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    target_weight REAL DEFAULT 0,
    planned_shares INTEGER DEFAULT 0,
    ref_price REAL DEFAULT 0,
    filled_date TEXT DEFAULT '',
    filled_price REAL DEFAULT 0,
    filled_shares INTEGER DEFAULT 0,
    fees REAL DEFAULT 0,
    reason TEXT DEFAULT '',
    wait_days INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- A failed order is counted at most once per trading date, regardless of scheduler retries.
-- Separate table avoids rewriting existing orders when upgrading an older SQLite database.
CREATE TABLE IF NOT EXISTS order_attempts (
    order_id INTEGER NOT NULL,
    attempt_date TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (order_id, attempt_date)
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    side TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    price REAL NOT NULL,
    shares INTEGER NOT NULL,
    amount REAL NOT NULL,
    commission REAL DEFAULT 0,
    stamp_tax REAL DEFAULT 0,
    transfer_fee REAL DEFAULT 0,
    price_source TEXT DEFAULT 'daily_open',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS position_lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    buy_date TEXT NOT NULL,
    shares INTEGER NOT NULL,
    cost_amount REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    initial_capital REAL NOT NULL,
    cash REAL NOT NULL,
    realized_pnl REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_daily (
    date TEXT PRIMARY KEY,
    cash REAL NOT NULL,
    market_value REAL NOT NULL,
    total_assets REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    realized_pnl REAL NOT NULL,
    cum_return REAL NOT NULL,
    peak_assets REAL NOT NULL,
    max_drawdown REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS position_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_date TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT DEFAULT '',
    action TEXT NOT NULL,
    reason TEXT DEFAULT '',
    ref_price REAL,
    created_at TEXT NOT NULL,
    UNIQUE(decision_date, code)
);

CREATE TABLE IF NOT EXISTS position_decision_outcomes (
    decision_id INTEGER NOT NULL,
    checkpoint INTEGER NOT NULL,
    eval_date TEXT NOT NULL,
    ret_pct REAL,
    index_ret_pct REAL,
    PRIMARY KEY (decision_id, checkpoint)
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_date TEXT NOT NULL UNIQUE,
    target_date TEXT NOT NULL,
    ai_status TEXT NOT NULL,
    quant_json TEXT NOT NULL,
    report_md TEXT DEFAULT '',
    ai_raw TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_date TEXT NOT NULL,
    category TEXT DEFAULT '',
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    evidence TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name TEXT NOT NULL,
    biz_date TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'running',
    message TEXT DEFAULT '',
    UNIQUE(job_name, biz_date)
);

CREATE TABLE IF NOT EXISTS data_status (
    source TEXT PRIMARY KEY,
    last_success_date TEXT DEFAULT '',
    last_attempt TEXT DEFAULT '',
    status TEXT DEFAULT '',
    message TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | str) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        # 旧库迁移：未经 AI 分析的新闻应标记为未验证
        conn.execute("UPDATE news SET verified=0 WHERE ai_analyzed=0 AND verified=1")
        conn.commit()
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection):
    """事务上下文：异常自动回滚。"""
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise