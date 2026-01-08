from __future__ import annotations
import os
import math
import uuid
import random
import time
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from pmm.execution.exchange_base import ExchangeBase, PlaceOrderResult
from pmm.db import repo

log = logging.getLogger("pmm.order_manager")

@dataclass
class LiveOrderState:
    local_order_id: str
    venue_order_id: str
    token_id: str
    side: str
    price: float
    size: float
    created_ts: int

@dataclass
class SimFillStats:
    fills: int = 0
    markout_sum: float = 0.0
    realized_spread_sum: float = 0.0

class OrderManager:
    """
    Practical order lifecycle manager:
    - Keeps a small set of live post-only orders per token
    - Cancels stale orders after cancel_reprice_sec
    - Reprices when price changes beyond tick
    - Enforces post-only guard against crossing best bid/ask
    """
    def __init__(self, *, run_id: str, conn, exchange: ExchangeBase, max_orders_per_token: int,
                 cancel_reprice_sec: float, post_only: bool, tick_size: float | None):
        self.run_id = run_id
        self.conn = conn
        self.exchange = exchange
        self.max_orders_per_token = int(max_orders_per_token)
        self.cancel_reprice_sec = float(cancel_reprice_sec)
        self.post_only = bool(post_only)
        self.tick_size = tick_size if (tick_size and tick_size > 0) else None
        self.live: Dict[str, List[LiveOrderState]] = {}  # token_id -> orders list
        self._rng = random.Random(self._seed_from_run_id(run_id))

    @staticmethod
    def _seed_from_run_id(run_id: str) -> int:
        # run_id 通常是 uuid；这里做一个稳定 seed，便于 paper 复现
        try:
            return uuid.UUID(str(run_id)).int & 0xFFFFFFFF
        except Exception:
            s = str(run_id or "pmm")
            return sum((i + 1) * ord(ch) for i, ch in enumerate(s)) & 0xFFFFFFFF

    def _now(self) -> int:
        return int(time.time())

    def _price_changed(self, old: float, new: float) -> bool:
        if self.tick_size:
            return abs(old - new) >= (self.tick_size - 1e-12)
        return abs(old - new) >= max(1e-4, old * 0.0001)

    def _guard_post_only(self, side: str, price: float, best_bid: float | None, best_ask: float | None) -> float | None:
        if not self.post_only:
            return price
        side = side.upper()
        if side == "BUY" and best_ask is not None:
            if price >= best_ask:
                # push below best ask by one tick
                adj = best_ask - (self.tick_size or 1e-3)
                return adj if adj > 0 else None
        if side == "SELL" and best_bid is not None:
            if price <= best_bid:
                adj = best_bid + (self.tick_size or 1e-3)
                return adj if adj < 1.0 else None
        return price

    def cancel_stale(self) -> int:
        now = self._now()
        cancels = 0
        for token_id, lst in list(self.live.items()):
            keep: List[LiveOrderState] = []
            for o in lst:
                if now - o.created_ts >= self.cancel_reprice_sec:
                    ok = self.exchange.cancel(venue_order_id=o.venue_order_id)
                    cancels += 1 if ok else 0
                    repo.upsert_order(self.conn, {
                        "run_id": self.run_id,
                        "local_order_id": o.local_order_id,
                        "venue_order_id": o.venue_order_id,
                        "condition_id": None,
                        "token_id": o.token_id,
                        "side": o.side,
                        "price": o.price,
                        "size": o.size,
                        "post_only": 1 if self.post_only else 0,
                        "status": "CANCELED" if ok else "ERROR",
                        "created_ts": o.created_ts,
                        "updated_ts": now,
                        "meta_json": {"reason": "stale", "ok": ok},
                    })
                else:
                    keep.append(o)
            self.live[token_id] = keep
        return cancels

    def simulate_fills(
        self,
        *,
        condition_id: str,
        token_id: str,
        midpoint: float | None,
        best_bid: float | None,
        best_ask: float | None,
        dt_sec: float,
        ts: int | None = None,
        intensity_override: float | None = None,
        depth_top: float | None = None,
    ) -> SimFillStats:
        """
        Paper/dry-run 模拟成交：
        - 使用真实盘口(best_bid/best_ask) + 我们的挂单价格，按概率生成 PARTIAL/FILLED trades
        - 写入 trades 表，并更新 orders 状态，同时维护 self.live 中的剩余 size
        """
        if not getattr(self.exchange, "is_paper", False):
            return SimFillStats()
        if os.getenv("PMM_PAPER_SIM_ENABLE", "true").lower() != "true":
            return SimFillStats()

        token_id = str(token_id)
        now = int(ts if ts is not None else self._now())
        lst = list(self.live.get(token_id, []))
        if not lst:
            return SimFillStats()

        tick = float(self.tick_size or 1e-3)
        mid = float(midpoint) if midpoint is not None else None
        dt = max(0.1, float(dt_sec))

        # 强度：每秒成交“到达率”（Poisson rate），越高越容易看到 trades
        # 经验：在 top N 市场做市，paper 想“像真的”但不刷屏，建议 0.001~0.01
        intensity = float(intensity_override) if intensity_override is not None else float(os.getenv("PMM_PAPER_FILL_INTENSITY", "0.003"))
        base_p = 1.0 - math.exp(-max(0.0, intensity) * dt)  # Poisson: P(at least one)

        out = SimFillStats()
        keep: list[LiveOrderState] = []

        for o in lst:
            side = o.side.upper()
            px = float(o.price)
            remaining = float(o.size)
            if remaining <= 1e-9:
                continue

            # 竞争力因子：离 best 越近越容易成交（按 tick 距离分段）
            competitive = 0.15
            if side == "BUY" and best_bid is not None:
                d_ticks = abs(px - float(best_bid)) / max(1e-9, tick)
            elif side == "SELL" and best_ask is not None:
                d_ticks = abs(px - float(best_ask)) / max(1e-9, tick)
            else:
                d_ticks = 9e9
            if d_ticks <= 0.5:
                competitive = 1.0
            elif d_ticks <= 1.5:
                competitive = 0.6
            elif d_ticks <= 2.5:
                competitive = 0.35
            elif d_ticks <= 4.5:
                competitive = 0.22

            # 距离 mid 越远，成交概率适当下降（更像真实做市：挂得太宽就少成交）
            edge_factor = 1.0
            if mid is not None and mid > 1e-9:
                edge_bps = abs(px - mid) / mid * 10000.0
                edge_factor = 1.0 / (1.0 + (edge_bps / 80.0))

            # 盘口/价差影响（spread_penalty）：
            # - mode=factor: 在这里直接进 p_fill（历史默认）
            # - mode=intensity: 把 spread 惩罚放到外层 intensity 自适应里（避免双重惩罚）
            spread_factor = 1.0
            spread_ticks = None
            if best_bid is not None and best_ask is not None:
                spread_ticks = max(0.0, (float(best_ask) - float(best_bid)) / max(1e-9, tick))
                mode = os.getenv("PMM_PAPER_SPREAD_MODE", "intensity").lower()
                if mode == "factor":
                    k = float(os.getenv("PMM_PAPER_SPREAD_K", "0.6"))
                    spread_factor = 1.0 / (1.0 + k * max(0.0, float(spread_ticks) - 1.0))

            p_fill = max(0.0, min(0.95, base_p * competitive * edge_factor * spread_factor))

            if self._rng.random() >= p_fill:
                keep.append(o)
                continue

            # ===== markout model (paper only) =====
            # 对 maker 更真实的成本不是“成交滑点”，而是成交后的价格漂移（adverse selection / markout）。
            # 模型：future_mid = mid * (1 + N(0, sigma_bps))
            sigma_bps = float(os.getenv("PMM_PAPER_MARKOUT_SIGMA_BPS", "20"))
            eps = self._rng.gauss(0.0, sigma_bps / 10000.0)
            future_mid = None
            if mid is not None:
                future_mid = max(0.001, min(0.999, float(mid) * (1.0 + eps)))

            # realized spread（以成交时 mid 为基准）
            realized_spread = 0.0
            if mid is not None:
                if side == "BUY":
                    realized_spread = (float(mid) - px) * 1.0
                else:
                    realized_spread = (px - float(mid)) * 1.0

            # partial / full
            allow_partial = os.getenv("PMM_PAPER_PARTIAL_FILL", "true").lower() == "true"
            full_prob = float(os.getenv("PMM_PAPER_FULL_FILL_PROB", "0.35"))
            if (not allow_partial) or (self._rng.random() < full_prob):
                frac = 1.0
            else:
                # 更合理的 partial size 分布：偏向“小部分成交”，偶尔出现较大 partial
                # 使用 Beta 分布（a,b 可调）
                a = float(os.getenv("PMM_PAPER_PARTIAL_BETA_A", "2.0"))
                b = float(os.getenv("PMM_PAPER_PARTIAL_BETA_B", "6.0"))
                raw = self._rng.betavariate(max(0.1, a), max(0.1, b))
                lo = float(os.getenv("PMM_PAPER_PARTIAL_MIN_FRAC", "0.05"))
                hi = float(os.getenv("PMM_PAPER_PARTIAL_MAX_FRAC", "0.60"))
                frac = lo + (hi - lo) * raw
            fill_size = max(1e-6, remaining * frac)
            fill_size = min(fill_size, remaining)
            new_remaining = remaining - fill_size
            status = "FILLED" if new_remaining <= 1e-9 else "PARTIAL"

            # markout（以 future_mid 为基准；若 mid 不可用则为 0）
            markout = 0.0
            if future_mid is not None:
                if side == "BUY":
                    markout = (float(future_mid) - px) * float(fill_size)
                else:
                    markout = (px - float(future_mid)) * float(fill_size)

            trade_id = f"paper-{uuid.uuid4()}"
            repo.insert_trade(self.conn, {
                "run_id": self.run_id,
                "trade_id": trade_id,
                "venue_order_id": o.venue_order_id,
                "condition_id": condition_id,
                "token_id": token_id,
                "side": side,
                "price": px,
                "size": float(fill_size),
                "status": status,
                "ts": now,
                "raw_json": {
                    "sim": True,
                    "p_fill": p_fill,
                    "competitive": competitive,
                    "edge_factor": edge_factor,
                    "spread_factor": spread_factor,
                    "spread_ticks": spread_ticks,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "mid": mid,
                    "future_mid": future_mid,
                    "markout": markout,
                    "realized_spread": realized_spread * float(fill_size),
                    "markout_sigma_bps": sigma_bps,
                    "intensity_used": intensity,
                    "depth_top": depth_top,
                },
            })

            repo.upsert_order(self.conn, {
                "run_id": self.run_id,
                "local_order_id": o.local_order_id,
                "venue_order_id": o.venue_order_id,
                "condition_id": condition_id,
                "token_id": token_id,
                "side": side,
                "price": px,
                # 这里用“剩余数量”更新 size，方便下一轮继续模拟 partial fills
                "size": float(max(0.0, new_remaining)),
                "post_only": 1 if self.post_only else 0,
                "status": status,
                "created_ts": o.created_ts,
                "updated_ts": now,
                "meta_json": {"reason": "paper_sim_fill", "fill_size": fill_size, "remaining": new_remaining},
            })

            out.fills += 1
            out.markout_sum += float(markout)
            out.realized_spread_sum += float(realized_spread) * float(fill_size)
            if status == "PARTIAL":
                o.size = float(new_remaining)
                keep.append(o)
            # FILLED: 不再 keep

        self.live[token_id] = keep
        return out

    def place_or_replace(self, *, condition_id: str, token_id: str, side: str, price: float, size: float,
                         best_bid: float | None = None, best_ask: float | None = None) -> PlaceOrderResult:
        now = self._now()
        token_id = str(token_id)
        side = side.upper()

        # post-only guard
        guarded_price = self._guard_post_only(side, float(price), best_bid, best_ask)
        if guarded_price is None:
            return PlaceOrderResult(success=False, error="post_only_guard_blocked", raw={"best_bid": best_bid, "best_ask": best_ask})
        price = float(guarded_price)

        existing = self.live.get(token_id, [])

        # Replace same-side order if price changed
        for o in list(existing):
            if o.side == side and self._price_changed(o.price, price):
                ok = self.exchange.cancel(venue_order_id=o.venue_order_id)
                repo.upsert_order(self.conn, {
                    "run_id": self.run_id,
                    "local_order_id": o.local_order_id,
                    "venue_order_id": o.venue_order_id,
                    "condition_id": condition_id,
                    "token_id": token_id,
                    "side": side,
                    "price": o.price,
                    "size": o.size,
                    "post_only": 1 if self.post_only else 0,
                    "status": "CANCELED" if ok else "ERROR",
                    "created_ts": o.created_ts,
                    "updated_ts": now,
                    "meta_json": {"reason": "reprice", "ok": ok, "new_price": price},
                })
                try:
                    existing.remove(o)
                except ValueError:
                    pass

        # Enforce cap by canceling oldest
        while len(existing) >= self.max_orders_per_token:
            o = existing.pop(0)
            ok = self.exchange.cancel(venue_order_id=o.venue_order_id)
            repo.upsert_order(self.conn, {
                "run_id": self.run_id,
                "local_order_id": o.local_order_id,
                "venue_order_id": o.venue_order_id,
                "condition_id": condition_id,
                "token_id": token_id,
                "side": o.side,
                "price": o.price,
                "size": o.size,
                "post_only": 1 if self.post_only else 0,
                "status": "CANCELED" if ok else "ERROR",
                "created_ts": o.created_ts,
                "updated_ts": now,
                "meta_json": {"reason": "cap", "ok": ok},
            })

        local_order_id = f"{self.run_id[:8]}-{condition_id[:6]}-{now}-{side}"
        res = self.exchange.place_limit(
            token_id=token_id,
            side=side,
            price=price,
            size=float(size),
            post_only=self.post_only,
            meta={"condition_id": condition_id},
        )
        status = "PLACED" if res.success else "REJECTED"
        repo.upsert_order(self.conn, {
            "run_id": self.run_id,
            "local_order_id": local_order_id,
            "venue_order_id": res.venue_order_id,
            "condition_id": condition_id,
            "token_id": token_id,
            "side": side,
            "price": price,
            "size": float(size),
            "post_only": 1 if self.post_only else 0,
            "status": status,
            "created_ts": now,
            "updated_ts": now,
            "meta_json": {"raw": res.raw, "err": res.error, "best_bid": best_bid, "best_ask": best_ask},
        })
        if res.success and res.venue_order_id:
            existing.append(LiveOrderState(
                local_order_id=local_order_id,
                venue_order_id=res.venue_order_id,
                token_id=token_id,
                side=side,
                price=price,
                size=float(size),
                created_ts=now,
            ))
        self.live[token_id] = existing
        return res
