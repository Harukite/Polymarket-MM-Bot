from __future__ import annotations
import logging
from typing import Any, Optional
import os

import httpx

from py_clob_client.endpoints import GET_ORDER_BOOK, GET_TICK_SIZE, MID_POINT

log = logging.getLogger("pmm.clob_public")

class ClobPublic:
    def __init__(self, host: str, chain_id: int = 137):
        # py-clob-client 内部用的是无 timeout 的全局 httpx client，网络抖动会卡死。
        # 这里我们自己维护一个带 timeout 的 httpx client，避免 live loop 被阻塞。
        self.host = str(host).rstrip("/")
        self.chain_id = chain_id
        timeout_sec = float(os.getenv("PMM_HTTP_TIMEOUT_SEC", "5.0"))
        self._http = httpx.Client(http2=True, timeout=httpx.Timeout(timeout_sec))

    def close(self) -> None:
        try:
            self._http.close()
        except Exception:
            pass

    def _get_json(self, path: str, *, params: dict[str, Any]) -> Any:
        url = f"{self.host}{path}"
        # 轻量重试：避免瞬时网络抖动导致整轮失败
        last_err: Exception | None = None
        for _ in range(2):
            try:
                resp = self._http.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError as e:
                last_err = e
        if last_err:
            raise last_err
        raise RuntimeError("unknown http error")

    def get_midpoint(self, token_id: str) -> Optional[float]:
        try:
            # Public Methods include getMidpoint()/get_midpoint() citeturn1view1
            r = self._get_json(MID_POINT, params={"token_id": str(token_id)})
            mid = r.get("mid") if isinstance(r, dict) else None
            return float(mid) if mid is not None else None
        except Exception:
            log.exception("get_midpoint failed for token_id=%s", token_id)
            return None

    def get_orderbook(self, token_id: str) -> dict[str, Any] | None:
        try:
            # Public Methods include getOrderBook()/get_order_book() citeturn1view1
            r = self._get_json(GET_ORDER_BOOK, params={"token_id": str(token_id)})
            return r if isinstance(r, dict) else None
        except Exception:
            log.exception("get_order_book failed for token_id=%s", token_id)
            return None

    def get_tick_size(self, token_id: str) -> Optional[float]:
        try:
            r = self._get_json(GET_TICK_SIZE, params={"token_id": str(token_id)})
            if isinstance(r, dict):
                v = r.get("minimum_tick_size") or r.get("tick_size") or r.get("tickSize") or r.get("tick")
                return float(v) if v is not None else None
            return None
        except Exception:
            log.exception("get_tick_size failed for token_id=%s", token_id)
            return None
