from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SwiggyBridgeCoordinator
from .sensor import _active_order, _device_info


class InstamartOrderActiveBinarySensor(CoordinatorEntity[SwiggyBridgeCoordinator], BinarySensorEntity):
    _attr_name = "Instamart Order Active"
    _attr_icon = "mdi:cart-arrow-right"

    def __init__(self, coordinator: SwiggyBridgeCoordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.base_url}_instamart_order_active"
        self._attr_device_info = _device_info(coordinator)

    @property
    def is_on(self) -> bool:
        return _active_order(self.coordinator.op("instamart", "list_orders")) is not None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator: SwiggyBridgeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([InstamartOrderActiveBinarySensor(coordinator)])
