from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Tuple

@dataclass
class MarketFeatures:
    condition_id: str
    liquidity_num: float
    # calibration-derived
    fills: int
    quotes: int
    markout_sum: float  # negative => adverse
    realized_spread_sum: float

def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default

class CapitalAllocator:
    """
    Capital allocation optimizer (conservative):
    - Distributes a global gross budget across markets.
    - Weights markets by liquidity^p and by a "quality" term derived from calibration:
        quality = exp(-k * max(0, -avg_markout)) * (0.5 + 0.5*fill_rate_norm)
    - Enforces min/max per-market caps.

    Goal: concentrate risk capital where (a) liquidity is strong and (b) recent fills are not showing adverse selection.
    """
    def __init__(self, *, total_budget_usd: float, min_per_market: float, max_per_market: float,
                 liquidity_power: float = 0.5, quality_k: float = 2.0):
        self.total_budget_usd = float(total_budget_usd)
        self.min_per_market = float(min_per_market)
        self.max_per_market = float(max_per_market)
        self.liquidity_power = float(liquidity_power)
        self.quality_k = float(quality_k)

    def allocate(self, feats: Iterable[MarketFeatures]) -> Dict[str, float]:
        feats = list(feats)
        if not feats:
            return {}
        # Base weight by liquidity
        w_raw = []
        for f in feats:
            liq = max(1e-9, float(f.liquidity_num))
            base = liq ** self.liquidity_power
            fill_rate = f.fills / max(1, f.quotes)
            # avg markout per fill; if negative, penalize
            avg_markout = f.markout_sum / max(1, f.fills)
            adverse = max(0.0, -avg_markout)
            quality = math.exp(-self.quality_k * adverse) * (0.5 + 0.5 * min(1.0, fill_rate * 20.0))
            w = base * max(0.05, min(1.5, quality))
            w_raw.append(w)

        s = sum(w_raw)
        if s <= 0:
            # fallback uniform
            w_raw = [1.0] * len(feats)
            s = float(len(feats))

        # First pass: proportional allocation
        alloc = {f.condition_id: (self.total_budget_usd * (w_raw[i]/s)) for i, f in enumerate(feats)}

        # Apply caps with iterative re-normalization
        fixed = {}
        remaining = self.total_budget_usd
        remaining_indices = set(range(len(feats)))

        # Enforce min first
        for i, f in enumerate(feats):
            if alloc[f.condition_id] < self.min_per_market:
                fixed[f.condition_id] = self.min_per_market
                remaining -= self.min_per_market
                remaining_indices.discard(i)

        if remaining <= 0:
            # too many mins; just return mins clipped
            return {cid: min(self.max_per_market, v) for cid, v in fixed.items()}

        # Recompute weights for remaining and allocate
        if remaining_indices:
            s2 = sum(w_raw[i] for i in remaining_indices)
            for i in remaining_indices:
                f = feats[i]
                alloc[f.condition_id] = remaining * (w_raw[i] / max(1e-12, s2))

        # Enforce max with one more pass; overflow redistributed
        overflow = 0.0
        under = []
        for f in feats:
            v = alloc[f.condition_id]
            if v > self.max_per_market:
                overflow += v - self.max_per_market
                alloc[f.condition_id] = self.max_per_market
            else:
                under.append(f.condition_id)

        if overflow > 0 and under:
            add = overflow / len(under)
            for cid in under:
                alloc[cid] = min(self.max_per_market, alloc[cid] + add)

        # Merge fixed mins
        alloc.update(fixed)
        return alloc
