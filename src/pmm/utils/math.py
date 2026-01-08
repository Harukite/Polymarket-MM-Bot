from __future__ import annotations
from decimal import Decimal, ROUND_DOWN

def quantize_price(p: float, tick: float) -> float:
    if tick <= 0:
        return float(p)
    d = Decimal(str(p))
    t = Decimal(str(tick))
    q = (d / t).to_integral_value(rounding=ROUND_DOWN) * t
    return float(q)

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))
