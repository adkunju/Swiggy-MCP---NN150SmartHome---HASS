from __future__ import annotations

import aiohttp
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SwiggyBridgeCoordinator
from .sensor import _device_info


class InstamartClearCartButton(CoordinatorEntity[SwiggyBridgeCoordinator], ButtonEntity):
    _attr_name = "Instamart Clear Cart"
    _attr_icon = "mdi:cart-remove"

    def __init__(self, coordinator: SwiggyBridgeCoordinator, session: aiohttp.ClientSession):
        super().__init__(coordinator)
        self._session = session
        self._attr_unique_id = f"{coordinator.base_url}_instamart_clear_cart"
        self._attr_device_info = _device_info(coordinator)

    async def async_press(self) -> None:
        async with self._session.post(
            f"{self.coordinator.base_url}/api/instamart/call",
            json={"tool": "clear_cart", "arguments": {}},
            timeout=20,
        ) as resp:
            resp.raise_for_status()
        await self.coordinator.async_request_refresh()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator: SwiggyBridgeCoordinator = hass.data[DOMAIN][entry.entry_id]
    session = async_get_clientsession(hass)
    async_add_entities([InstamartClearCartButton(coordinator, session)])
