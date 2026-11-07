from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_BASE_URL, DOMAIN
from .coordinator import SwiggyBridgeCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]

ADD_TO_CART_SCHEMA = vol.Schema(
    {
        vol.Required("item_id"): cv.string,
        vol.Optional("quantity", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    coordinator = SwiggyBridgeCoordinator(hass, entry.data[CONF_BASE_URL], session)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def handle_add_to_cart(call: ServiceCall) -> None:
        for coord in hass.data[DOMAIN].values():
            try:
                await coord.async_call(
                    "instamart",
                    "add_to_cart",
                    {"item_id": call.data["item_id"], "quantity": call.data["quantity"]},
                )
            except Exception as exc:  # noqa: BLE001 -- surface to the HA UI
                raise HomeAssistantError(f"Adding to the Instamart cart failed: {exc}") from exc

    if not hass.services.has_service(DOMAIN, "add_to_cart"):
        hass.services.async_register(DOMAIN, "add_to_cart", handle_add_to_cart, schema=ADD_TO_CART_SCHEMA)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, "add_to_cart")
    return ok
