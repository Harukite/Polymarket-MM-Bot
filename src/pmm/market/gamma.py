from __future__ import annotations
import requests
import logging
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger("pmm.gamma")

class GammaClient:
    def __init__(self, host: str):
        self.host = host.rstrip("/")
        self.last_url: str | None = None

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(min=0.5, max=8))
    def get_markets(self, *, limit: int, offset: int, active: bool | None, closed: bool | None,
                    order: str, ascending: bool) -> list[dict]:
        params = {"limit": limit, "offset": offset, "order": order, "ascending": str(ascending).lower()}
        if active is not None:
            params["active"] = str(active).lower()
        if closed is not None:
            params["closed"] = str(closed).lower()
        url = f"{self.host}/markets"
        r = requests.get(url, params=params, timeout=20)
        self.last_url = getattr(r, "url", None) or url
        # 频繁输出会导致仪表盘闪烁，默认降级为 debug；链接会在仪表盘里展示
        log.debug("🌐 Gamma GET %s", self.last_url)
        r.raise_for_status()
        return r.json()
