"""
Sensors built from the add-on's /api/poll snapshot.

Field names inside each payload (cart["total"], order["eta"], ...) match the
add-on's demo data and are best guesses for the real Swiggy responses, which
aren't published outside the Builders Club program. Once real access works,
compare against "List tools" / a real payload and adjust the lookups here.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import SwiggyBridgeCoordinator, active_order


def device_info(coordinator: SwiggyBridgeCoordinator) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.base_url)},
        name="Swiggy MCP Bridge",
        manufacturer="Swiggy (unofficial integration)",
        model="Builders Club MCP",
    )


class SwiggyEntity(CoordinatorEntity[SwiggyBridgeCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: SwiggyBridgeCoordinator, key: str, name: str, icon: str | None = None):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.base_url}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = device_info(coordinator)

    @property
    def extra_state_attributes(self):
        return {"demo_data": True} if self.coordinator.demo else {}


def _cart(coordinator):
    cart = coordinator.op("instamart", "get_cart")
    return cart if isinstance(cart, dict) else None


def _orders(coordinator):
    return coordinator.op("instamart", "list_orders")


class InstamartCartTotalSensor(SwiggyEntity, SensorEntity):
    _attr_native_unit_of_measurement = "INR"
    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(self, coordinator):
        super().__init__(coordinator, "instamart_cart_total", "Instamart cart total", "mdi:currency-inr")

    @property
    def native_value(self):
        cart = _cart(self.coordinator)
        if cart is None:
            return None
        return cart.get("total", cart.get("total_amount"))


class InstamartCartItemsSensor(SwiggyEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator, "instamart_cart_items", "Instamart cart items", "mdi:cart-outline")

    @property
    def native_value(self):
        cart = _cart(self.coordinator)
        if cart is None:
            return None
        return sum(int(i.get("quantity", 1)) for i in cart.get("items", []))

    @property
    def extra_state_attributes(self):
        attrs = dict(super().extra_state_attributes)
        cart = _cart(self.coordinator)
        if cart:
            attrs["items"] = [
                f"{i.get('quantity', 1)} × {i.get('name', i.get('id', '?'))}" for i in cart.get("items", [])
            ]
        return attrs


class InstamartOrderStatusSensor(SwiggyEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator, "instamart_order_status", "Instamart order status", "mdi:truck-delivery-outline")

    @property
    def native_value(self):
        orders = _orders(self.coordinator)
        if orders is None:
            return None  # data unavailable (e.g. no access yet) -- not "no order"
        order = active_order(orders)
        if order:
            return order.get("status")
        # Show the most recent finished order's status (e.g. "delivered") so
        # automations can trigger on the transition into it.
        if isinstance(orders, list) and orders and isinstance(orders[0], dict):
            return orders[0].get("status")
        return "no_active_order"

    @property
    def extra_state_attributes(self):
        attrs = dict(super().extra_state_attributes)
        orders = _orders(self.coordinator)
        order = active_order(orders) or (orders[0] if isinstance(orders, list) and orders else None)
        if isinstance(order, dict):
            for key in ("order_id", "store_name"):
                if key in order:
                    attrs[key] = order[key]
            if "items" in order:
                attrs["items"] = [f"{i.get('quantity', 1)} × {i.get('name', '?')}" for i in order["items"]]
        return attrs


class InstamartOrderEtaSensor(SwiggyEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator):
        super().__init__(coordinator, "instamart_order_eta", "Instamart order ETA", "mdi:clock-outline")

    @property
    def native_value(self):
        order = active_order(_orders(self.coordinator))
        if not order or not order.get("eta"):
            return None
        eta = dt_util.parse_datetime(str(order["eta"]))
        if eta is None:
            return None
        return eta if eta.tzinfo else eta.replace(tzinfo=dt_util.UTC)


class InstamartBilledAmountSensor(SwiggyEntity, SensorEntity):
    _attr_native_unit_of_measurement = "INR"
    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(self, coordinator):
        super().__init__(coordinator, "instamart_billed_amount", "Instamart billed amount", "mdi:receipt-text-outline")

    @property
    def native_value(self):
        order = active_order(_orders(self.coordinator))
        return order.get("billed_amount") if order else None


class InstamartDeliveryAddressSensor(SwiggyEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator, "instamart_delivery_address", "Instamart delivery address", "mdi:map-marker-outline")

    @property
    def native_value(self):
        addresses = self.coordinator.op("instamart", "list_addresses")
        if not isinstance(addresses, list) or not addresses:
            return None
        default = next((a for a in addresses if a.get("is_default")), addresses[0])
        return default.get("label") or default.get("line1")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    coordinator: SwiggyBridgeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        cls(coordinator)
        for cls in (
            InstamartCartTotalSensor,
            InstamartCartItemsSensor,
            InstamartOrderStatusSensor,
            InstamartOrderEtaSensor,
            InstamartBilledAmountSensor,
            InstamartDeliveryAddressSensor,
        )
    )
