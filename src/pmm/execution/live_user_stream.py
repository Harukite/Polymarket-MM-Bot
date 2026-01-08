from __future__ import annotations
import json
import logging
import threading
import time
import uuid
from typing import Iterable, Optional

from websocket import WebSocketApp  # websocket-client
from pmm.db import repo

log = logging.getLogger("pmm.user_stream")

class UserStream:
    """
    Connects to Polymarket CLOB user websocket and records:
    - raw user events into tape_user_events
    - trade events into trades table
    - order events into orders table status updates (best-effort)

    WebSocket base + subscription format:
    - wss://ws-subscriptions-clob.polymarket.com/ws/user
    - send {"type":"user","auth":{apiKey,secret,passphrase},"markets":[conditionId,...]} citeturn6view0turn2view0turn4search0
    - user channel emits trade/order messages citeturn3view1
    """
    def __init__(self, *, run_id: str, db_path: str, wss_base: str, api_key: str, api_secret: str, api_passphrase: str,
                 markets: Optional[Iterable[str]] = None, ping_sec: int = 10):
        self.run_id = run_id
        self.db_path = str(db_path)
        self._conn = None
        self.wss_base = wss_base.rstrip("/")
        self.auth = {"apiKey": api_key, "secret": api_secret, "passphrase": api_passphrase}
        self.markets = list(markets or [])
        self.ping_sec = ping_sec
        self._ws: Optional[WebSocketApp] = None
        self._thread: Optional[threading.Thread] = None

    def _on_open(self, ws: WebSocketApp):
        sub = {"type": "user", "auth": self.auth, "markets": self.markets}
        ws.send(json.dumps(sub))
        log.info("UserStream subscribed (markets=%s)", len(self.markets))
        # heartbeat
        def ping_loop():
            while True:
                try:
                    ws.send("PING")
                except Exception:
                    return
                time.sleep(self.ping_sec)
        threading.Thread(target=ping_loop, daemon=True).start()

    def _on_message(self, ws: WebSocketApp, message: str):
        # docs show that message is JSON for events; we guard for PONG etc.
        if message in ("PONG", "PING"):
            return
        if self._conn is None:
            return
        try:
            data = json.loads(message)
        except Exception:
            log.debug("non-json message: %r", message[:200])
            return

        event_type = str(data.get("event_type") or data.get("type") or "unknown")
        event_id = str(data.get("id") or data.get("taker_order_id") or uuid.uuid4())

        ts = int(data.get("timestamp") or data.get("matchtime") or time.time())
        repo.insert_user_event(self._conn, self.run_id, event_id, event_type, ts, data)

        # trade message
        if (data.get("event_type") == "trade") or (str(data.get("type")).upper() == "TRADE"):
            repo.insert_trade(self._conn, {
                "run_id": self.run_id,
                "trade_id": str(data.get("id") or event_id),
                "venue_order_id": str(data.get("taker_order_id") or ""),
                "condition_id": data.get("market"),
                "token_id": data.get("asset_id"),
                "side": data.get("side"),
                "price": float(data.get("price")) if data.get("price") is not None else None,
                "size": float(data.get("size")) if data.get("size") is not None else None,
                "status": data.get("status"),
                "ts": ts,
                "raw_json": data,
            })
            return

        # order message
        if (data.get("event_type") == "order"):
            # We don't always know local_order_id. Here we update by venue_order_id where possible.
            venue_order_id = str(data.get("id") or "")
            # Best-effort: update any matching order rows by venue_order_id.
            if venue_order_id:
                self._conn.execute(
                    '''
                    UPDATE orders SET
                      status=?,
                      updated_ts=?
                    WHERE run_id=? AND venue_order_id=?
                    ''',
                    (str(data.get("type") or "UPDATE"), ts, self.run_id, venue_order_id),
                )

    def _on_error(self, ws: WebSocketApp, error: Exception):
        log.error("UserStream error: %s", error)

    def _on_close(self, ws: WebSocketApp, close_status_code, close_msg):
        log.warning("UserStream closed: %s %s", close_status_code, close_msg)

    def start(self):
        url = f"{self.wss_base}/ws/user"
        self._ws = WebSocketApp(
            url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        def run():
            # 每个线程独立 sqlite 连接，避免跨线程使用同一 connection
            from pmm.db.schema import connect, init_db
            self._conn = connect(self.db_path)
            init_db(self._conn)
            # auto reconnect
            backoff = 1.0
            while True:
                try:
                    self._ws.run_forever(ping_interval=None)  # we manage PING manually
                except Exception as e:
                    log.exception("UserStream run_forever exception: %s", e)
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        log.info("UserStream thread started")

