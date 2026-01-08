from __future__ import annotations
from pmm.market.gamma import GammaClient

def fetch_top_liquidity_markets(gamma: GammaClient, *, limit: int, order_field: str, ascending: bool,
                               only_active: bool, only_open: bool) -> list[dict]:
    # Gamma allows ordering by a comma-separated list of fields. We'll use the configured field. citeturn9view0
    active = True if only_active else None
    closed = False if only_open else None
    markets = gamma.get_markets(limit=limit, offset=0, active=active, closed=closed, order=order_field, ascending=ascending)

    out = []
    for m in markets:
        condition_id = m.get("conditionId") or m.get("condition_id")
        if not condition_id:
            continue
        out.append({
            "condition_id": condition_id,
            "market_id": str(m.get("id")) if m.get("id") is not None else None,
            "question": m.get("question"),
            "slug": m.get("slug"),
            "liquidity_num": float(m.get("liquidityNum") or m.get("liquidity_num") or 0.0),
            "volume_num": float(m.get("volumeNum") or m.get("volume_num") or 0.0),
            "active": 1 if (m.get("active") is True) else 0,
            "closed": 1 if (m.get("closed") is True) else 0,
            "accepting_orders": 1 if (m.get("acceptingOrders") is True) else 0,
            "clob_token_ids": m.get("clobTokenIds") or m.get("clob_token_ids"),
        })
    # Defensive: enforce limit after parsing.
    out.sort(key=lambda x: x["liquidity_num"], reverse=True)
    return out[:limit]
