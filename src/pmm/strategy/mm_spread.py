from __future__ import annotations
from dataclasses import dataclass
from pmm.utils.math import clamp

@dataclass
class Quote:
    side: str   # BUY/SELL
    price: float
    size: float

class SymmetricSpreadMM:
    """
    Simple symmetric spread strategy around midpoint:
    - price = mid +/- spread/2
    - size based on max_usd and alpha scaling
    """
    def __init__(self, *, target_spread_bps: float, max_usd: float, alpha_scale: float):
        self.target_spread_bps = target_spread_bps
        self.max_usd = max_usd
        self.alpha_scale = alpha_scale

    def quotes(self, midpoint: float) -> list[Quote]:
        mid = float(midpoint)
        spread = mid * (self.target_spread_bps / 10000.0)
        bid = clamp(mid - spread/2, 0.001, 0.999)
        ask = clamp(mid + spread/2, 0.001, 0.999)
        usd_each_side = (self.max_usd / 2.0) * self.alpha_scale
        # approximate shares: usd / price for BUY, usd / (1-price) for SELL can be complex;
        # in CLOB it's expressed as size in outcome tokens (shares). We'll use usd/price as a proxy.
        bid_size = max(1.0, usd_each_side / max(0.01, bid))
        ask_size = max(1.0, usd_each_side / max(0.01, ask))
        return [Quote("BUY", bid, bid_size), Quote("SELL", ask, ask_size)]
