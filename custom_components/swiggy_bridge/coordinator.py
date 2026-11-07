"""
DataUpdateCoordinator that polls the add-on's /api/poll endpoint.

/api/poll isolates each server/operation on the add-on side and returns
per-op {"ok": bool, ...} entries instead of raising, so one refused op (e.g.
a 403 before Swiggy grants access) never blanks out the others. Only a total
failure to reach the add-on fails the coordinator update.

Polling interval adapts to keep Swiggy traffic low:
  - 5 min normally
  - 60 s while an order is in progress (so status/ETA stay fresh)
  - 15 s in the add-on's demo mode (stub data, no Swiggy traffic)
"""
from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ACTIVE_ORDER_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEMO_SCAN_INTERVAL,
    DOMAIN,
    TERMINAL_ORDER_STATES,
)

log = logging.getLogger(__name__)


def active_order(orders) -> dict | None:
    """First order that isn't finished yet, or None. `orders` may be None
    (data unavailable) or a list of order dicts."""
    if not isinstance(orders, list):
        return None
    for order in orders:
        if isinstance(order, dict) and str(order.get("status", "")).lower() not in TERMINAL_ORDER_STATES:
            return order
    return None


class SwiggyBridgeCoordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass: HomeAssistant, base_url: str, session: aiohttp.ClientSession) -> None:
        super().__init__(
            hass,
            log,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.base_url = base_url.rstrip("/")
        self._session = session

    @property
    def demo(self) -> bool:
        return bool((self.data or {}).get("_meta", {}).get("demo"))

    async def _async_update_data(self) -> dict:
        try:
            async with self._session.get(
                f"{self.base_url}/api/poll", timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status == 401:
                    # Add-on is up but not logged in to Swiggy yet -- not a
                    # transport failure; the add-on's own UI handles login.
                    log.debug("Bridge reports not authenticated yet")
                    return {}
                resp.raise_for_status()
                body = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise UpdateFailed(f"Could not reach Swiggy MCP Bridge at {self.base_url}: {exc}") from exc

        if not body.get("ok"):
            raise UpdateFailed(f"Bridge returned an error: {body.get('error')}")

        data = body["data"]
        self._adapt_interval(data)
        return data

    def _adapt_interval(self, data: dict) -> None:
        if data.get("_meta", {}).get("demo"):
            seconds = DEMO_SCAN_INTERVAL
        else:
            orders = data.get("instamart", {}).get("list_orders", {})
            has_active = orders.get("ok") and active_order(orders.get("data")) is not None
            seconds = ACTIVE_ORDER_SCAN_INTERVAL if has_active else DEFAULT_SCAN_INTERVAL
        new = timedelta(seconds=seconds)
        if self.update_interval != new:
            log.debug("Polling interval -> %ss", seconds)
            self.update_interval = new

    def op(self, server: str, operation: str):
        """An op's data if it succeeded, else None. Never raises."""
        entry = (self.data or {}).get(server, {}).get(operation)
        if entry and entry.get("ok"):
            return entry.get("data")
        return None

    async def async_call(self, server: str, op: str, arguments: dict | None = None) -> dict:
        """Run a write op (clear_cart, add_to_cart) through the add-on, which
        maps the logical op name to the real MCP tool name."""
        async with self._session.post(
            f"{self.base_url}/api/{server}/call",
            json={"op": op, "arguments": arguments or {}},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            body = await resp.json(content_type=None)
        if not body.get("ok"):
            raise RuntimeError(body.get("error") or f"HTTP {resp.status}")
        # Refresh right away (not the debounced async_request_refresh), so the
        # dashboard reflects the change immediately even on repeated presses.
        await self.async_refresh()
        return body.get("data")
