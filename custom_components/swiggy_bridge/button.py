from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SwiggyBridgeCoordinator
from .sensor import SwiggyEntity


class InstamartClearCartButton(SwiggyEntity, ButtonEntity):
    def __init__(self, coordinator: SwiggyBridgeCoordinator):
        super().__init__(coordinator, "instamart_clear_cart", "Instamart clear cart", "mdi:cart-remove")

    async def async_press(self) -> None:
        try:
            await self.coordinator.async_call("instamart", "clear_cart")
        except Exception as exc:  # noqa: BLE001 -- surface to the HA UI
            raise HomeAssistantError(f"Clearing the Instamart cart failed: {exc}") from exc


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    coordinator: SwiggyBridgeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([InstamartClearCartButton(coordinator)])
