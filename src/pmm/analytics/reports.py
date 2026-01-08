from __future__ import annotations
import sqlite3
import pandas as pd

def top_markets_by_trade_notional(conn: sqlite3.Connection, run_id: str, n: int = 10) -> pd.DataFrame:
    q = '''
    SELECT condition_id, COALESCE(SUM(price*size),0) as notional
    FROM trades
    WHERE run_id=?
    GROUP BY condition_id
    ORDER BY notional DESC
    LIMIT ?
    '''
    return pd.read_sql_query(q, conn, params=(run_id, n))

def latest_account(conn: sqlite3.Connection, run_id: str) -> pd.DataFrame:
    q = "SELECT * FROM account_state WHERE run_id=?"
    return pd.read_sql_query(q, conn, params=(run_id,))

def recent_risk_events(conn: sqlite3.Connection, run_id: str, n: int = 50) -> pd.DataFrame:
    q = "SELECT * FROM risk_events WHERE run_id=? ORDER BY ts DESC LIMIT ?"
    return pd.read_sql_query(q, conn, params=(run_id, n))

def latest_positions(conn: sqlite3.Connection, run_id: str, n: int = 200) -> pd.DataFrame:
    q = '''
    SELECT token_id, ts, qty, avg_cost, realized_pnl, unrealized_pnl, cash, equity
    FROM positions
    WHERE run_id=?
    ORDER BY ts DESC
    LIMIT ?
    '''
    return pd.read_sql_query(q, conn, params=(run_id, n))
