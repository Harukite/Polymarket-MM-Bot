from __future__ import annotations
import json
import sqlite3
import time
from typing import Any, Iterable, Optional
from pmm.utils.time import now_iso

# Upsert order status with full lifecycle updates: PLACED, PARTIAL, FILLED, CANCELED
def upsert_order(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    row = dict(row)
    row["meta_json"] = json.dumps(row.get("meta_json") or {}, ensure_ascii=False)
    conn.execute(
        '''
        INSERT INTO orders(run_id, local_order_id, venue_order_id, condition_id, token_id, side, price, size, post_only,
                           status, created_ts, updated_ts, meta_json)
        VALUES(:run_id,:local_order_id,:venue_order_id,:condition_id,:token_id,:side,:price,:size,:post_only,
               :status,:created_ts,:updated_ts,:meta_json)
        ON CONFLICT(run_id, local_order_id) DO UPDATE SET
          venue_order_id=excluded.venue_order_id,
          condition_id=COALESCE(excluded.condition_id, orders.condition_id),
          token_id=excluded.token_id,
          side=excluded.side,
          price=excluded.price,
          size=excluded.size,
          post_only=excluded.post_only,
          status=excluded.status,
          updated_ts=excluded.updated_ts,
          meta_json=excluded.meta_json
        ''',
        row,
    )

# --- orderbook snapshots ---
def insert_orderbook(
    conn: sqlite3.Connection,
    run_id: str,
    token_id: str,
    ts: int,
    best_bid: float | None,
    best_ask: float | None,
    midpoint: float | None,
    bids: Any,
    asks: Any,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO orderbooks(run_id, token_id, ts, best_bid, best_ask, midpoint, bids_json, asks_json)
        VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            str(run_id),
            str(token_id),
            int(ts),
            float(best_bid) if best_bid is not None else None,
            float(best_ask) if best_ask is not None else None,
            float(midpoint) if midpoint is not None else None,
            json.dumps(bids or [], ensure_ascii=False),
            json.dumps(asks or [], ensure_ascii=False),
        ),
    )

# --- trades & user tape ---
def insert_trade(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    row = dict(row)
    row["raw_json"] = json.dumps(row.get("raw_json") or {}, ensure_ascii=False)
    conn.execute(
        """
        INSERT OR REPLACE INTO trades(run_id, trade_id, venue_order_id, condition_id, token_id, side, price, size, status, ts, raw_json)
        VALUES(:run_id,:trade_id,:venue_order_id,:condition_id,:token_id,:side,:price,:size,:status,:ts,:raw_json)
        """,
        row,
    )

def insert_user_event(conn: sqlite3.Connection, run_id: str, event_id: str, event_type: str, ts: int, raw: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO tape_user_events(run_id, event_id, event_type, ts, raw_json)
        VALUES(?,?,?,?,?)
        """,
        (str(run_id), str(event_id), str(event_type), int(ts), json.dumps(raw or {}, ensure_ascii=False)),
    )

# --- risk events ---
def insert_risk_event(
    conn: sqlite3.Connection,
    run_id: str,
    ts: int,
    level: str,
    code: str,
    message: str,
    meta: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO risk_events(run_id, ts, level, code, message, meta_json)
        VALUES(?,?,?,?,?,?)
        """,
        (str(run_id), int(ts), str(level), str(code), str(message), json.dumps(meta or {}, ensure_ascii=False)),
    )

# Insert or update balance/exposure for live exposure management
def upsert_balance(conn: sqlite3.Connection, run_id: str, cash: float, equity: float, gross_exposure: float) -> None:
    conn.execute(
        '''
        INSERT OR REPLACE INTO account_state(run_id, ts, cash, equity, gross_exposure, meta_json)
        VALUES(?, ?, ?, ?, ?, ?)
        ''',
        (run_id, int(time.time()), cash, equity, gross_exposure, json.dumps({}, ensure_ascii=False)),
    )
def insert_run(conn: sqlite3.Connection, run_id: str, mode: str, config: dict[str, Any]) -> None:
    """
    插入新的运行记录，包括模式（paper / live）和配置信息。
    """
    conn.execute(
        '''
        INSERT INTO runs(run_id, mode, started_at, config_json)
        VALUES(?,?,datetime('now'),?)
        ''',
        (run_id, mode, json.dumps(config, ensure_ascii=False)),
    )

def insert_market(conn: sqlite3.Connection, condition_id: str, market_id: str, question: str, slug: str, liquidity_num: float, volume_num: float, active: int, closed: int, accepting_orders: int, clob_token_ids: list[str]) -> None:
    """
    插入新的市场记录，包括条件 ID、市场 ID、问题、slug、流动性、成交量、是否活跃、是否关闭、是否接受订单、CLOB token IDs。
    """
    conn.execute(
        '''
        INSERT INTO markets(condition_id, market_id, question, slug, liquidity_num, volume_num, active, closed, accepting_orders, clob_token_ids)
        VALUES(?,?,?,?,?,?,?,?,?,?)
        ''',
        (condition_id, market_id, question, slug, liquidity_num, volume_num, active, closed, accepting_orders, json.dumps(clob_token_ids, ensure_ascii=False)),
    )
def list_universe(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """
    从数据库中查询市场列表，按流动性（liquidity）排序，限制返回数量。
    """
    cur = conn.execute(
        "SELECT * FROM markets ORDER BY liquidity_num DESC LIMIT ?",
        (limit,),
    )
    return cur.fetchall()
def upsert_markets(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> None:
    """
    插入或更新市场数据，确保每个市场的数据是最新的。
    """
    sql = '''
    INSERT INTO markets(condition_id, market_id, question, slug, liquidity_num, volume_num, active, closed, accepting_orders, clob_token_ids, updated_at)
    VALUES(:condition_id, :market_id, :question, :slug, :liquidity_num, :volume_num, :active, :closed, :accepting_orders, :clob_token_ids, :updated_at)
    ON CONFLICT(condition_id) DO UPDATE SET
      market_id=excluded.market_id,
      question=excluded.question,
      slug=excluded.slug,
      liquidity_num=excluded.liquidity_num,
      volume_num=excluded.volume_num,
      active=excluded.active,
      closed=excluded.closed,
      accepting_orders=excluded.accepting_orders,
      clob_token_ids=excluded.clob_token_ids,
      updated_at=excluded.updated_at
    '''
    conn.executemany(sql, [{**r, "updated_at": now_iso()} for r in rows])

def get_calibration(conn: sqlite3.Connection, condition_id: str) -> Optional[sqlite3.Row]:
    """
    从数据库中获取市场的 calibration 信息。
    """
    cur = conn.execute(
        "SELECT * FROM market_calibration WHERE condition_id=?",
        (condition_id,)
    )
    return cur.fetchone()

def upsert_calibration(conn: sqlite3.Connection, condition_id: str, alpha: float, target_spread_bps: float,
                       max_usd: float, quote_refresh_sec: float, cancel_reprice_sec: float, state: dict[str, Any]) -> None:
    """
    插入或更新市场校准数据（alpha、target_spread_bps、max_usd、quote_refresh_sec、cancel_reprice_sec）
    """
    conn.execute(
        '''
        INSERT INTO market_calibration(condition_id, alpha, target_spread_bps, max_usd, quote_refresh_sec, cancel_reprice_sec, updated_at, state_json)
        VALUES(?,?,?,?,?,?,datetime('now'),?)
        ON CONFLICT(condition_id) DO UPDATE SET
          alpha=excluded.alpha,
          target_spread_bps=excluded.target_spread_bps,
          max_usd=excluded.max_usd,
          quote_refresh_sec=excluded.quote_refresh_sec,
          cancel_reprice_sec=excluded.cancel_reprice_sec,
          updated_at=excluded.updated_at,
          state_json=excluded.state_json
        ''',
        (condition_id, alpha, target_spread_bps, max_usd, quote_refresh_sec, cancel_reprice_sec, json.dumps(state)),
    )

def insert_pnl_snapshot(conn: sqlite3.Connection, run_id: str, ts: int, gross_usd: float, realized_usd: float,
                         unrealized_usd: float, cash: float, equity: float, raw: dict[str, Any] | None = None) -> None:
    """
    插入或更新 PnL 快照数据
    """
    conn.execute(
        '''
        INSERT OR REPLACE INTO pnl_snapshots(run_id, ts, gross_usd, realized_usd, unrealized_usd, cash, equity, raw_json)
        VALUES(?,?,?,?,?,?,?,?)
        ''',
        (run_id, ts, gross_usd, realized_usd, unrealized_usd, cash, equity, json.dumps(raw or {}, ensure_ascii=False)),
    )

def insert_position_snapshot(conn: sqlite3.Connection, run_id: str, token_id: str, ts: int,
                             qty: float, avg_cost: float, realized: float, unrealized: float, cash: float, equity: float, meta: dict[str, Any] | None = None) -> None:
    """
    插入或更新持仓快照数据
    """
    conn.execute(
        '''
        INSERT INTO positions(run_id, token_id, ts, qty, avg_cost, realized_pnl, unrealized_pnl, cash, equity, meta_json)
        VALUES(?,?,?,?,?,?,?,?,?,?)
        ''',
        (run_id, token_id, ts, qty, avg_cost, realized, unrealized, cash, equity, json.dumps(meta or {}, ensure_ascii=False)),
    )