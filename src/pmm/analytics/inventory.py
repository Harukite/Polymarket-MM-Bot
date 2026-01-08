from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

@dataclass
class Position:
    qty: float = 0.0
    avg_cost: float = 0.0   # average execution price
    realized: float = 0.0

class InventoryEngine:
    """
    Inventory + PnL model (token-level):
    - BUY increases qty; updates avg_cost
    - SELL decreases qty; realized pnl = (sell_price - avg_cost) * size
    - Unrealized pnl marked to midpoint where available
    """
    def __init__(self, starting_cash: float = 1000.0):
        self.cash = float(starting_cash)
        self.pos: Dict[str, Position] = {}

    def apply_fill(self, token_id: str, side: str, price: float, size: float, fee: float = 0.0) -> None:
        token_id = str(token_id)
        side = side.upper()
        price = float(price)
        size = float(size)
        fee = float(fee or 0.0)

        p = self.pos.get(token_id, Position())
        if side == "BUY":
            cost = price * size + fee
            new_qty = p.qty + size
            if new_qty > 1e-12:
                p.avg_cost = (p.avg_cost * p.qty + price * size) / new_qty
            p.qty = new_qty
            self.cash -= cost
        else:
            # SELL
            proceeds = price * size - fee
            sell_size = min(size, p.qty)  # conservative: do not allow short in accounting
            p.realized += (price - p.avg_cost) * sell_size
            p.qty -= sell_size
            if p.qty <= 1e-12:
                p.qty = 0.0
                p.avg_cost = 0.0
            self.cash += proceeds

        self.pos[token_id] = p

    def mark(self, midpoint_by_token: Dict[str, float]) -> Tuple[float, float, float, Dict[str, float]]:
        unreal = 0.0
        gross = 0.0
        marks: Dict[str, float] = {}
        for tid, p in self.pos.items():
            mid = midpoint_by_token.get(tid)
            if mid is None:
                continue
            mid = float(mid)
            marks[tid] = mid
            gross += abs(p.qty) * mid
            unreal += (mid - p.avg_cost) * p.qty
        equity = self.cash + sum((midpoint_by_token.get(tid, 0.0) or 0.0) * p.qty for tid, p in self.pos.items())
        return gross, self.realized_total(), unreal, marks  # realized tracked per-position below

    def realized_total(self) -> float:
        return sum(p.realized for p in self.pos.values())

    def equity(self, midpoint_by_token: Dict[str, float]) -> float:
        eq = self.cash
        for tid, p in self.pos.items():
            mid = midpoint_by_token.get(tid)
            if mid is not None:
                eq += float(mid) * p.qty
        return eq

def load_fills_from_trades(conn: sqlite3.Connection, run_id: str, since_ts: int) -> list[dict]:
    # We interpret "trades" rows as fills. side/price/size must be present.
    cur = conn.execute(
        "SELECT * FROM trades WHERE run_id=? AND ts>? ORDER BY ts ASC",
        (run_id, since_ts),
    )
    out = []
    for r in cur.fetchall():
        if r["price"] is None or r["size"] is None or r["side"] is None:
            continue
        out.append({
            "token_id": r["token_id"],
            "side": str(r["side"]).upper(),
            "price": float(r["price"]),
            "size": float(r["size"]),
            "fee": 0.0,
            "ts": int(r["ts"]),
            "trade_id": r["trade_id"],
        })
    return out
