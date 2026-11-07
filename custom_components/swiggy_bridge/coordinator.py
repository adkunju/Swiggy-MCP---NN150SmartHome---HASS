"""
DataUpdateCoordinator that polls the add-on's /api/poll endpoint.

Design note (this is the bug we're explicitly avoiding): /api/poll already
isolates each server/operation on the add-on side, returning per-op
{"ok": bool, ...} entries instead of raising. So even if, say, Instamart's
`list_orders` 403s because production access hasn't come through yet, the
other operations (cart, addresses, Dineout bookings, ...) still populate.
We must NOT wrap the whole poll in a single try/except that discards
everything on one bad sub-result -- only a total connection failure to the
add-on itself should mark the coordinator update as failed.
"""
from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

log = logging.getLogger(__name__)


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

    async def _async_update_data(self) -> dict:
        try:
            async with self._session.get(f"{self.base_url}/api/poll", timeout=20) as resp:
                if resp.status == 401:
                    # Add-on is up but not authenticated -- not a transport
                    # failure, so surface an empty-but-valid snapshot rather
                    # than spamming reauth; the add-on's own UI handles login.
                    log.debug("Bridge reports not authenticated yet")
                    return {}
                resp.raise_for_status()
                body = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as exc:
            # This is the one case that SHOULD fail the whole update: we
            # couldn't even reach the add-on.
            raise UpdateFailed(f"Could not reach Swiggy MCP Bridge at {self.base_url}: {exc}") from exc

        if not body.get("ok"):
            raise UpdateFailed(f"Bridge returned an error: {body.get('error')}")

        return body["data"]  # {server: {op: {"ok": bool, "data"/"error": ...}}}

    def op(self, server: str, operation: str):
        """Helper for entities: returns the op's data dict if it succeeded,
        else None -- never raises, so one failing op leaves other entities
        unaffected rather than making the whole coordinator object useless."""
        entry = (self.data or {}).get(server, {}).get(operation)
        if entry and entry.get("ok"):
            return entry.get("data")
        return None
