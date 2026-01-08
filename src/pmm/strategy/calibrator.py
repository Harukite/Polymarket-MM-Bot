from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Any

@dataclass
class MarketCalibState:
    fills: int = 0
    quotes: int = 0
    markout_sum: float = 0.0
    realized_spread_sum: float = 0.0

@dataclass
class MarketCalibParams:
    alpha: float
    target_spread_bps: float
    max_usd: float
    quote_refresh_sec: float
    cancel_reprice_sec: float
    state: MarketCalibState = field(default_factory=MarketCalibState)

class Calibrator:
    """
    Per-market adaptive calibration:
    - Increase spread if markout negative (adverse selection)
    - Decrease spread if no fills for long time
    This is intentionally light-weight and safe.
    """
    def __init__(self, base_alpha: float, base_spread_bps: float, base_max_usd: float,
                 base_quote_refresh_sec: float, base_cancel_reprice_sec: float):
        self.base_alpha = base_alpha
        self.base_spread_bps = base_spread_bps
        self.base_max_usd = base_max_usd
        self.base_quote_refresh_sec = base_quote_refresh_sec
        self.base_cancel_reprice_sec = base_cancel_reprice_sec

    def next_params(self, prev: MarketCalibParams) -> MarketCalibParams:
        st = prev.state
        if st.quotes <= 0:
            return prev

        fill_rate = st.fills / max(1, st.quotes)
        avg_markout = st.markout_sum / max(1, st.fills)
        # Heuristic adjustment
        spread = prev.target_spread_bps

        if st.fills >= 5 and avg_markout < 0:
            spread *= 1.0 + min(0.50, abs(avg_markout) * 5.0)  # up to +50%
        elif fill_rate < 0.01 and st.quotes > 500:
            spread *= 0.90  # tighten slowly if no fills

        spread = float(max(20.0, min(spread, 500.0)))
        # Refresh cadence: slower if spread is wide (less aggressive)
        quote_refresh = float(min(10.0, max(1.0, prev.quote_refresh_sec * (spread / prev.target_spread_bps))))
        cancel_reprice = float(min(60.0, max(5.0, prev.cancel_reprice_sec * (spread / prev.target_spread_bps))))
        return MarketCalibParams(
            alpha=prev.alpha,
            target_spread_bps=spread,
            max_usd=prev.max_usd,
            quote_refresh_sec=quote_refresh,
            cancel_reprice_sec=cancel_reprice,
            state=st,
        )

    def init_params(self) -> MarketCalibParams:
        return MarketCalibParams(
            alpha=self.base_alpha,
            target_spread_bps=self.base_spread_bps,
            max_usd=self.base_max_usd,
            quote_refresh_sec=self.base_quote_refresh_sec,
            cancel_reprice_sec=self.base_cancel_reprice_sec,
        )

    @staticmethod
    def to_state_json(p: MarketCalibParams) -> dict[str, Any]:
        return {
            "fills": p.state.fills,
            "quotes": p.state.quotes,
            "markout_sum": p.state.markout_sum,
            "realized_spread_sum": p.state.realized_spread_sum,
        }

    @staticmethod
    def from_state_json(d: dict[str, Any]) -> MarketCalibState:
        return MarketCalibState(
            fills=int(d.get("fills", 0)),
            quotes=int(d.get("quotes", 0)),
            markout_sum=float(d.get("markout_sum", 0.0)),
            realized_spread_sum=float(d.get("realized_spread_sum", 0.0)),
        )
