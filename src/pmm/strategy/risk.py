from __future__ import annotations
from dataclasses import dataclass

@dataclass
class RiskLimits:
    alpha: float
    max_usd_per_market: float
    max_gross_usd: float

class RiskManager:
    def __init__(self, limits: RiskLimits):
        self.limits = limits

    def size_scale(self) -> float:
        # Conservative: alpha>1 => scale down (e.g., alpha=1.5 => 0.67)
        return 1.0 / max(1.0, self.limits.alpha)
