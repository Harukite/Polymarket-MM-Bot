from __future__ import annotations
import sqlite3

SCHEMA_SQL = '''
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  mode TEXT NOT NULL,
  started_at TEXT NOT NULL,
  config_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS markets (
  condition_id TEXT PRIMARY KEY,
  market_id TEXT,
  question TEXT,
  slug TEXT,
  liquidity_num REAL,
  volume_num REAL,
  active INTEGER,
  closed INTEGER,
  accepting_orders INTEGER,
  clob_token_ids TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orderbooks (
  run_id TEXT NOT NULL,
  token_id TEXT NOT NULL,
  ts INTEGER NOT NULL,
  best_bid REAL,
  best_ask REAL,
  midpoint REAL,
  bids_json TEXT,
  asks_json TEXT,
  PRIMARY KEY (run_id, token_id, ts)
);

CREATE TABLE IF NOT EXISTS orders (
  run_id TEXT NOT NULL,
  local_order_id TEXT NOT NULL,
  venue_order_id TEXT,
  condition_id TEXT,
  token_id TEXT NOT NULL,
  side TEXT NOT NULL, -- BUY/SELL
  price REAL NOT NULL,
  size REAL NOT NULL,
  post_only INTEGER NOT NULL,
  status TEXT NOT NULL, -- NEW/PLACED/CANCELED/FILLED/PARTIAL/REJECTED/ERROR
  created_ts INTEGER NOT NULL,
  updated_ts INTEGER NOT NULL,
  meta_json TEXT,
  PRIMARY KEY (run_id, local_order_id)
);

CREATE TABLE IF NOT EXISTS trades (
  run_id TEXT NOT NULL,
  trade_id TEXT NOT NULL,
  venue_order_id TEXT,
  condition_id TEXT,
  token_id TEXT,
  side TEXT,
  price REAL,
  size REAL,
  status TEXT,
  ts INTEGER NOT NULL,
  raw_json TEXT,
  PRIMARY KEY (run_id, trade_id)
);

CREATE TABLE IF NOT EXISTS tape_user_events (
  run_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  ts INTEGER NOT NULL,
  raw_json TEXT NOT NULL,
  PRIMARY KEY (run_id, event_id)
);

CREATE TABLE IF NOT EXISTS market_calibration (
  condition_id TEXT PRIMARY KEY,
  alpha REAL NOT NULL,
  target_spread_bps REAL NOT NULL,
  max_usd REAL NOT NULL,
  quote_refresh_sec REAL NOT NULL,
  cancel_reprice_sec REAL NOT NULL,
  updated_at TEXT NOT NULL,
  state_json TEXT
);

-- Inventory / positions per token
CREATE TABLE IF NOT EXISTS positions (
  run_id TEXT NOT NULL,
  token_id TEXT NOT NULL,
  ts INTEGER NOT NULL,
  qty REAL NOT NULL,
  avg_cost REAL NOT NULL,
  realized_pnl REAL NOT NULL,
  unrealized_pnl REAL NOT NULL,
  cash REAL NOT NULL,
  equity REAL NOT NULL,
  meta_json TEXT,
  PRIMARY KEY (run_id, token_id, ts)
);

-- Latest account snapshot (one row per run)
CREATE TABLE IF NOT EXISTS account_state (
    run_id TEXT NOT NULL,
    ts INTEGER NOT NULL,
    cash REAL NOT NULL,
    equity REAL NOT NULL,
    gross_exposure REAL NOT NULL,
    meta_json TEXT,
    PRIMARY KEY (run_id, ts)
);

-- risk/circuit breaker events
CREATE TABLE IF NOT EXISTS risk_events (
  run_id TEXT NOT NULL,
  ts INTEGER NOT NULL,
  level TEXT NOT NULL,   -- INFO/WARN/ERROR
  code TEXT NOT NULL,
  message TEXT NOT NULL,
  meta_json TEXT,
  PRIMARY KEY (run_id, ts, code)
);

CREATE TABLE IF NOT EXISTS pnl_snapshots (
  run_id TEXT NOT NULL,
  ts INTEGER NOT NULL,
  gross_usd REAL NOT NULL,
  realized_usd REAL NOT NULL,
  unrealized_usd REAL NOT NULL,
  cash REAL NOT NULL,
  equity REAL NOT NULL,
  raw_json TEXT,
  PRIMARY KEY (run_id, ts)
);
'''

def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
