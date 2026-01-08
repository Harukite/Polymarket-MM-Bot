from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

@dataclass
class PlaceOrderResult:
    success: bool
    venue_order_id: Optional[str] = None
    error: Optional[str] = None
    raw: dict | None = None

class ExchangeBase:
    def place_limit(self, *, token_id: str, side: str, price: float, size: float, post_only: bool, meta: dict) -> PlaceOrderResult:
        raise NotImplementedError

    def cancel(self, *, venue_order_id: str) -> bool:
        raise NotImplementedError
