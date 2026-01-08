from __future__ import annotations
from pydantic import BaseModel, Field
import os

class Settings(BaseModel):
    # Core
    mode: str = Field(default_factory=lambda: os.getenv("PMM_MODE", "paper"))
    db_path: str = Field(default_factory=lambda: os.getenv("PMM_DB_PATH", "./data/pmm.sqlite"))
    log_level: str = Field(default_factory=lambda: os.getenv("PMM_LOG_LEVEL", "INFO"))

    # Universe (Gamma)
    gamma_host: str = Field(default_factory=lambda: os.getenv("PMM_GAMMA_HOST", "https://gamma-api.polymarket.com"))
    universe_limit: int = Field(default_factory=lambda: int(os.getenv("PMM_UNIVERSE_LIMIT", "50")))
    universe_order_field: str = Field(default_factory=lambda: os.getenv("PMM_UNIVERSE_ORDER_FIELD", "liquidityNum"))
    universe_ascending: bool = Field(default_factory=lambda: os.getenv("PMM_UNIVERSE_ASCENDING", "false").lower() == "true")
    only_active: bool = Field(default_factory=lambda: os.getenv("PMM_ONLY_ACTIVE", "true").lower() == "true")
    only_open: bool = Field(default_factory=lambda: os.getenv("PMM_ONLY_OPEN", "true").lower() == "true")

    # Execution (CLOB)
    clob_host: str = Field(default_factory=lambda: os.getenv("PMM_CLOB_HOST", "https://clob.polymarket.com"))
    chain_id: int = Field(default_factory=lambda: int(os.getenv("PMM_CHAIN_ID", "137")))
    private_key: str = Field(default_factory=lambda: os.getenv("PMM_PRIVATE_KEY", ""))
    signature_type: int = Field(default_factory=lambda: int(os.getenv("PMM_SIGNATURE_TYPE", "0")))
    funder: str = Field(default_factory=lambda: os.getenv("PMM_FUNDER", ""))

    api_key: str = Field(default_factory=lambda: os.getenv("PMM_API_KEY", ""))
    api_secret: str = Field(default_factory=lambda: os.getenv("PMM_API_SECRET", ""))
    api_passphrase: str = Field(default_factory=lambda: os.getenv("PMM_API_PASSPHRASE", ""))

    # Accounting
    starting_cash: float = Field(default_factory=lambda: float(os.getenv("PMM_STARTING_CASH", "1000")))

    # Risk / sizing
    alpha: float = Field(default_factory=lambda: float(os.getenv("PMM_ALPHA", "1.5")))
    max_usd_per_market: float = Field(default_factory=lambda: float(os.getenv("PMM_MAX_USD_PER_MARKET", "50")))
    min_usd_per_market: float = Field(default_factory=lambda: float(os.getenv("PMM_MIN_USD_PER_MARKET", "5")))
    max_gross_usd: float = Field(default_factory=lambda: float(os.getenv("PMM_MAX_GROSS_USD", "500")))
    post_only: bool = Field(default_factory=lambda: os.getenv("PMM_POST_ONLY", "true").lower() == "true")
    tick_buffer: float = Field(default_factory=lambda: float(os.getenv("PMM_TICK_BUFFER", "0.0")))

    # Strategy knobs
    target_spread_bps: float = Field(default_factory=lambda: float(os.getenv("PMM_TARGET_SPREAD_BPS", "60")))
    quote_refresh_sec: float = Field(default_factory=lambda: float(os.getenv("PMM_QUOTE_REFRESH_SEC", "3")))
    cancel_reprice_sec: float = Field(default_factory=lambda: float(os.getenv("PMM_CANCEL_REPRICE_SEC", "15")))
    max_orders_per_market: int = Field(default_factory=lambda: int(os.getenv("PMM_MAX_ORDERS_PER_MARKET", "2")))

    # Capital allocation
    enable_allocator: bool = Field(default_factory=lambda: os.getenv("PMM_ENABLE_ALLOCATOR", "true").lower() == "true")
    alloc_liquidity_power: float = Field(default_factory=lambda: float(os.getenv("PMM_ALLOC_LIQUIDITY_POWER", "0.5")))  # sqrt(liq)
    alloc_quality_k: float = Field(default_factory=lambda: float(os.getenv("PMM_ALLOC_QUALITY_K", "2.0")))  # penalty strength

    # Trade tape
    enable_wss_user: bool = Field(default_factory=lambda: os.getenv("PMM_ENABLE_WSS_USER", "true").lower() == "true")
    wss_base: str = Field(default_factory=lambda: os.getenv("PMM_WSS_BASE", "wss://ws-subscriptions-clob.polymarket.com"))
    wss_ping_sec: int = Field(default_factory=lambda: int(os.getenv("PMM_WSS_PING_SEC", "10")))

def load_settings() -> Settings:
    return Settings()
