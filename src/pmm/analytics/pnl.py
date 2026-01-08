from __future__ import annotations
import json
import sqlite3
from typing import Any
from pmm.analytics.inventory import InventoryEngine, load_fills_from_trades
from pmm.db import repo
from pmm.utils.time import now_ts

def snapshot_pnl(conn: sqlite3.Connection, run_id: str, inv: InventoryEngine, midpoint_by_token: dict[str, float]) -> None:
    ts = now_ts()
    gross_exposure = 0.0
    unreal = 0.0
    # recompute gross exposure + unreal at mark
    for tid, p in inv.pos.items():
        mid = midpoint_by_token.get(tid)
        if mid is None:
            continue
        gross_exposure += abs(p.qty) * float(mid)
        unreal += (float(mid) - p.avg_cost) * p.qty

    realized = inv.realized_total()
    equity = inv.equity(midpoint_by_token)

    repo.insert_pnl_snapshot(
        conn, run_id, ts, gross_usd=gross_exposure, realized_usd=realized, unrealized_usd=unreal,
        cash=inv.cash, equity=equity, raw={"positions": {tid: {"qty": p.qty, "avg_cost": p.avg_cost, "realized": p.realized} for tid, p in inv.pos.items()}}
    )
    def upsert_account_state(conn: sqlite3.Connection, run_id: str, ts: int, cash: float, equity: float, 
                         gross_exposure: float, meta: dict[str, Any] | None = None) -> None:
        conn.execute(
            '''
            INSERT OR REPLACE INTO account_state(run_id, ts, cash, equity, gross_exposure, meta_json)
            VALUES(?,?,?,?,?,?)
            ''',
            (run_id, ts, cash, equity, gross_exposure, json.dumps(meta or {}, ensure_ascii=False)),
        )

