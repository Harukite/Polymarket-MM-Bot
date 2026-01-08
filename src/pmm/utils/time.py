from __future__ import annotations
import time
from datetime import datetime, timezone

def now_ts() -> int:
    return int(time.time())

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
