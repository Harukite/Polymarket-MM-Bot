from __future__ import annotations
import logging
from pmm.execution.exchange_base import ExchangeBase, PlaceOrderResult
from pmm.config import Settings

log = logging.getLogger("pmm.live_exchange")

class LiveExchange(ExchangeBase):
    """
    Live execution via official py-clob-client, following Polymarket docs.
    - Derive or reuse L2 API creds (apiKey/secret/passphrase) citeturn1view0turn6view0
    - Create & sign orders then POST /order via client.post_order citeturn7view0
    """
    def __init__(self, settings: Settings):
        from py_clob_client.client import ClobClient
        self.settings = settings
        if not settings.private_key:
            raise ValueError("PMM_PRIVATE_KEY is required for live mode")
        self.client = ClobClient(
            settings.clob_host,
            key=settings.private_key,
            chain_id=settings.chain_id,
            signature_type=settings.signature_type if settings.signature_type in (1,2) else None,
            funder=settings.funder or None,
        )
        # L2 creds
        if settings.api_key and settings.api_secret and settings.api_passphrase:
            self.client.set_api_creds({
                "apiKey": settings.api_key,
                "secret": settings.api_secret,
                "passphrase": settings.api_passphrase,
            })
            log.info("Using existing L2 API creds from environment.")
        else:
            creds = self.client.create_or_derive_api_creds()  # docs show this for placing orders citeturn7view0
            self.client.set_api_creds(creds)
            log.warning("Derived L2 API creds at runtime. Persist them into .env for stability.")

    def place_limit(self, *, token_id: str, side: str, price: float, size: float, post_only: bool, meta: dict) -> PlaceOrderResult:
        from py_clob_client.clob_types import OrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY, SELL

        try:
            order_args = OrderArgs(
                price=float(price),
                size=float(size),
                side=BUY if side.upper() == "BUY" else SELL,
                token_id=str(token_id),
            )
            signed = self.client.create_order(order_args)
            # Only GTC is used in this scaffold; GTD/FAK/FOK can be added later.
            resp = self.client.post_order(signed, OrderType.GTC, post_only=bool(post_only))
            # Response format includes success/errorMsg/orderId citeturn7view0
            ok = bool(resp.get("success", False))
            if not ok:
                return PlaceOrderResult(success=False, error=resp.get("errorMsg") or "unknown", raw=resp)
            return PlaceOrderResult(success=True, venue_order_id=resp.get("orderId"), raw=resp)
        except Exception as e:
            log.exception("place_limit failed")
            return PlaceOrderResult(success=False, error=str(e), raw={"exception": str(e)})

    def cancel(self, *, venue_order_id: str) -> bool:
        try:
            # py-clob-client has cancel endpoint wrappers; we call cancel_order if available.
            if hasattr(self.client, "cancel"):
                self.client.cancel(venue_order_id)
            elif hasattr(self.client, "cancel_order"):
                self.client.cancel_order(venue_order_id)
            else:
                # fallback: REST delete /order
                self.client.delete_order(venue_order_id)  # type: ignore[attr-defined]
            return True
        except Exception:
            log.exception("cancel failed")
            return False
