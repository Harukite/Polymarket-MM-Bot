from __future__ import annotations
from typing import Dict, Optional
import logging

log = logging.getLogger("pmm.exposure_manager")

class ExposureManager:
    def __init__(self, max_exposure_per_market: float, max_total_exposure: float, post_only: bool):
        self.max_exposure_per_market = max_exposure_per_market
        self.max_total_exposure = max_total_exposure
        self.post_only = post_only

    def is_exposure_safe(self, token_id: str, qty: float, current_exposure: float) -> bool:
        if current_exposure + abs(qty) > self.max_total_exposure:
            log.warning(f"Total exposure exceeded: {current_exposure} + {qty} > {self.max_total_exposure}")
            return False
        if abs(qty) > self.max_exposure_per_market:
            log.warning(f"Exposure per market exceeded for {token_id}: {qty} > {self.max_exposure_per_market}")
            return False
        return True

    def check_post_only(self, token_id: str, price: float, side: str, best_bid: Optional[float], best_ask: Optional[float]) -> bool:
        if self.post_only:
            if side == "BUY" and price >= (best_ask or float('inf')):
                log.warning(f"Post-only restriction violated for {token_id}: {side} order at {price} >= best ask {best_ask}")
                return False
            if side == "SELL" and price <= (best_bid or float('-inf')):
                log.warning(f"Post-only restriction violated for {token_id}: {side} order at {price} <= best bid {best_bid}")
                return False
        return True
