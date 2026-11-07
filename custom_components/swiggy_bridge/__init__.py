from __future__ import annotations

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_BASE_URL, DOMAIN
from .coordinator import SwiggyBridgeCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session: aiohttp.ClientSession = async_get_clientsession(hass)
    coordinator = SwiggyBridgeCoordinator(hass, entry.data[CONF_BASE_URL], session)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def handle_add_to_cart(call):
        item_id = call.data["item_id"]
        quantity = call.data.get("quantity", 1)
        async with session.post(
            f"{coordinator.base_url}/api/instamart/call",
            json={"tool": "add_to_cart", "arguments": {"item_id": item_id, "quantity": quantity}},
            timeout=20,
        ) as resp:
            resp.raise_for_status()
        await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, "add_to_cart", handle_add_to_cart)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return ok
