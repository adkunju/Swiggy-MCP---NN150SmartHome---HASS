"""
Sensors built from whatever /api/poll returns. Field names inside each
payload (e.g. cart.get("total")) are best-effort guesses based on the
"feature areas" Swiggy documents publicly (cart management, order
tracking, address book) -- they are NOT confirmed against a real response,
since tool schemas aren't published outside the Builders Club program.
Once you can hit /api/instamart/tools for real, check the actual shapes
and adjust the `.get(...)` chains below.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SwiggyBridgeCoordinator


def _device_info(coordinator: SwiggyBridgeCoordinator) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.base_url)},
        name="Swiggy MCP Bridge",
        manufacturer="Swiggy (unofficial)",
        model="Builders Club MCP",
    )


def _active_order(orders: list | None) -> dict | None:
    if not orders:
        return None
    terminal = {"delivered", "cancelled", "failed"}
    for order in orders:
        if str(order.get("status", "")).lower() not in terminal:
            return order
    return None


class _BaseSensor(CoordinatorEntity[SwiggyBridgeCoordinator], SensorEntity):
    def __init__(self, coordinator: SwiggyBridgeCoordinator, key: str, name: str, icon: str | None = None):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.base_url}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = _device_info(coordinator)


class InstamartCartTotalSensor(_BaseSensor):
    _attr_native_unit_of_measurement = "INR"
    _attr_device_class = "monetary"

    def __init__(self, coordinator):
        super().__init__(coordinator, "instamart_cart_total", "Instamart Cart Total", "mdi:currency-inr")

    @property
    def native_value(self):
        cart = self.coordinator.op("instamart", "get_cart")
        if not cart:
            return None
        return cart.get("total") or cart.get("total_amount")


class InstamartCartItemsSensor(_BaseSensor):
    def __init__(self, coordinator):
        super().__init__(coordinator, "instamart_cart_items", "Instamart Cart Items", "mdi:cart-outline")

    @property
    def native_value(self):
        cart = self.coordinator.op("instamart", "get_cart")
        if not cart:
            return None
        items = cart.get("items", [])
        return len(items)

    @property
    def extra_state_attributes(self):
        cart = self.coordinator.op("instamart", "get_cart")
        return {"items": cart.get("items", [])} if cart else {}


class InstamartOrderStatusSensor(_BaseSensor):
    def __init__(self, coordinator):
        super().__init__(coordinator, "instamart_order_status", "Instamart Order Status", "mdi:truck-delivery-outline")

    @property
    def native_value(self):
        order = _active_order(self.coordinator.op("instamart", "list_orders"))
        return order.get("status") if order else "no_active_order"


class InstamartOrderEtaSensor(_BaseSensor):
    _attr_device_class = "timestamp"

    def __init__(self, coordinator):
        super().__init__(coordinator, "instamart_order_eta", "Instamart Order ETA", "mdi:clock-outline")

    @property
    def native_value(self):
        order = _active_order(self.coordinator.op("instamart", "list_orders"))
        return order.get("eta") if order else None


class InstamartBilledAmountSensor(_BaseSensor):
    _attr_native_unit_of_measurement = "INR"
    _attr_device_class = "monetary"

    def __init__(self, coordinator):
        super().__init__(coordinator, "instamart_billed_amount", "Instamart Billed Amount", "mdi:receipt-text-outline")

    @property
    def native_value(self):
        order = _active_order(self.coordinator.op("instamart", "list_orders"))
        return order.get("billed_amount") if order else None


class InstamartDeliveryAddressSensor(_BaseSensor):
    def __init__(self, coordinator):
        super().__init__(coordinator, "instamart_delivery_address", "Instamart Delivery Address", "mdi:map-marker-outline")

    @property
    def native_value(self):
        addresses = self.coordinator.op("instamart", "list_addresses")
        if not addresses:
            return None
        default = next((a for a in addresses if a.get("is_default")), addresses[0])
        return default.get("label") or default.get("line1")


class DineoutUpcomingBookingSensor(_BaseSensor):
    def __init__(self, coordinator):
        super().__init__(coordinator, "dineout_upcoming_booking", "Dineout Upcoming Booking", "mdi:silverware-fork-knife")

    @property
    def native_value(self):
        bookings = self.coordinator.op("dineout", "list_bookings")
        if not bookings:
            return "none"
        upcoming = bookings[0]
        return f"{upcoming.get('restaurant_name', '?')} @ {upcoming.get('slot', '?')}"


SENSOR_CLASSES_BY_SERVER = {
    "instamart": [
        InstamartCartTotalSensor,
        InstamartCartItemsSensor,
        InstamartOrderStatusSensor,
        InstamartOrderEtaSensor,
        InstamartBilledAmountSensor,
        InstamartDeliveryAddressSensor,
    ],
    "dineout": [DineoutUpcomingBookingSensor],
}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator: SwiggyBridgeCoordinator = hass.data[DOMAIN][entry.entry_id]
    enabled = (coordinator.data or {}).keys() or SENSOR_CLASSES_BY_SERVER.keys()

    entities = []
    for server, classes in SENSOR_CLASSES_BY_SERVER.items():
        if server in enabled or not coordinator.data:
            entities.extend(cls(coordinator) for cls in classes)

    async_add_entities(entities)
