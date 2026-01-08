from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass
class MarketInfo:
    condition_id: str
    token_yes: str
    token_no: str
    tick_size: float | None = None
    min_size: float | None = None

@dataclass
class StrategyDecision:
    token_id: str
    desired_orders: list[dict[str, Any]]  # {side, price, size, post_only, meta}

class StrategyBase:
    def on_tick(self, market: MarketInfo, midpoint_yes: float, midpoint_no: float) -> list[StrategyDecision]:
        raise NotImplementedError
