from __future__ import annotations
import time
import os
from dataclasses import dataclass, field
from typing import Deque, Tuple
from collections import deque

@dataclass
class CircuitConfig:
    max_reject_rate: float = 0.30     # rejected / (placed+rejected) over window
    window_sec: int = 300
    max_cancels_per_min: int = 120
    max_errors: int = 10

    @staticmethod
    def from_env(*, is_paper: bool) -> "CircuitConfig":
        """
        从环境变量读取熔断阈值。
        - 实盘默认更严格
        - paper/dry-run 默认更宽松，避免研究/回测被“撤单风暴”阈值误伤
        """
        def _f(name: str, default: float) -> float:
            try:
                return float(os.getenv(name, str(default)))
            except Exception:
                return float(default)
        def _i(name: str, default: int) -> int:
            try:
                return int(float(os.getenv(name, str(default))))
            except Exception:
                return int(default)

        # paper 默认阈值更大（可用 PMM_CB_MAX_CANCELS_PER_MIN_PAPER 覆盖）
        paper_cancels_default = 10_000
        return CircuitConfig(
            max_reject_rate=_f("PMM_CB_MAX_REJECT_RATE", 0.30),
            window_sec=_i("PMM_CB_WINDOW_SEC", 300),
            max_cancels_per_min=_i(
                "PMM_CB_MAX_CANCELS_PER_MIN_PAPER" if is_paper else "PMM_CB_MAX_CANCELS_PER_MIN",
                paper_cancels_default if is_paper else 120,
            ),
            max_errors=_i("PMM_CB_MAX_ERRORS", 10),
        )

@dataclass
class CircuitState:
    placed: int = 0
    rejected: int = 0
    errors: int = 0
    cancel_events: Deque[int] = field(default_factory=deque)  # timestamps

class CircuitBreaker:
    def __init__(self, cfg: CircuitConfig):
        self.cfg = cfg
        self.state = CircuitState()
        self._start_ts = int(time.time())

    def record_place(self, ok: bool) -> None:
        self.state.placed += 1
        if not ok:
            self.state.rejected += 1

    def record_cancel(self) -> None:
        now = int(time.time())
        self.state.cancel_events.append(now)
        # trim
        while self.state.cancel_events and now - self.state.cancel_events[0] > 60:
            self.state.cancel_events.popleft()

    def record_error(self) -> None:
        self.state.errors += 1

    def should_halt(self) -> tuple[bool, str]:
        # reject rate window
        denom = max(1, self.state.placed)
        reject_rate = self.state.rejected / denom
        if reject_rate >= self.cfg.max_reject_rate and self.state.placed >= 20:
            return True, f"reject_rate={reject_rate:.2%} over placed={self.state.placed}"
        if len(self.state.cancel_events) > self.cfg.max_cancels_per_min:
            return True, f"cancel_rate={len(self.state.cancel_events)}/min"
        if self.state.errors >= self.cfg.max_errors:
            return True, f"errors={self.state.errors}"
        return False, ""
