from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SwiggyBridgeCoordinator, active_order
from .sensor import SwiggyEntity


class InstamartOrderActiveBinarySensor(SwiggyEntity, BinarySensorEntity):
    def __init__(self, coordinator: SwiggyBridgeCoordinator):
        super().__init__(coordinator, "instamart_order_active", "Instamart order active", "mdi:cart-arrow-right")

    @property
    def is_on(self) -> bool | None:
        orders = self.coordinator.op("instamart", "list_orders")
        if orders is None:
            return None
        return active_order(orders) is not None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    coordinator: SwiggyBridgeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([InstamartOrderActiveBinarySensor(coordinator)])
