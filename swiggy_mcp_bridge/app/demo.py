"""
Demo mode: stub Instamart data, so the add-on + integration can be shown
working end to end before Swiggy grants production access (their access
application asks for a demo video built against a stub).

Nothing here talks to Swiggy. Everything is labelled as demo data in the UI.

The order lifecycle is driven by the clock since the last reset:
  0-60 s     placed
  60-120 s   packed
  120-240 s  out_for_delivery
  240 s+     delivered
"""
from __future__ import annotations

import copy
import time
from datetime import datetime, timedelta, timezone

PHASES = [
    (60, "placed"),
    (120, "packed"),
    (240, "out_for_delivery"),
]
TOTAL_SECONDS = 240

CATALOG = {
    "demo-milk": {"id": "demo-milk", "name": "Amul Taaza Toned Milk 500 ml", "price": 28},
    "demo-bread": {"id": "demo-bread", "name": "Harvest Gold White Bread", "price": 45},
    "demo-eggs": {"id": "demo-eggs", "name": "Farm Fresh Eggs (6 pcs)", "price": 54},
    "demo-bananas": {"id": "demo-bananas", "name": "Robusta Bananas (6 pcs)", "price": 39},
}

ADDRESSES = [
    {"id": "demo-home", "label": "Home", "line1": "Demo address (stub data)", "is_default": True},
    {"id": "demo-work", "label": "Work", "line1": "Demo address (stub data)", "is_default": False},
]

TOOLS = [
    {"name": "get_cart", "description": "[demo stub] Current Instamart cart"},
    {"name": "clear_cart", "description": "[demo stub] Empty the Instamart cart"},
    {"name": "add_to_cart", "description": "[demo stub] Add an item to the cart", "inputSchema": {
        "type": "object", "properties": {"item_id": {"type": "string"}, "quantity": {"type": "integer"}},
        "required": ["item_id"]}},
    {"name": "get_orders", "description": "[demo stub] Recent Instamart orders"},
    {"name": "get_addresses", "description": "[demo stub] Saved delivery addresses"},
]


class DemoState:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.started_at = time.time()
        self.cart = {"demo-milk": 2, "demo-bread": 1, "demo-eggs": 1}

    # ---- views ----

    def _cart_view(self) -> dict:
        items = []
        for item_id, qty in self.cart.items():
            product = CATALOG.get(item_id, {"id": item_id, "name": item_id, "price": 0})
            items.append({**product, "quantity": qty, "line_total": product["price"] * qty})
        return {"items": items, "total": sum(i["line_total"] for i in items), "demo": True}

    def _order_view(self) -> dict:
        elapsed = time.time() - self.started_at
        status = "delivered"
        for until, name in PHASES:
            if elapsed < until:
                status = name
                break
        eta = datetime.fromtimestamp(self.started_at + TOTAL_SECONDS, tz=timezone.utc)
        return {
            "order_id": "DEMO-1001",
            "status": status,
            "eta": eta.isoformat(),
            "store_name": "Instamart (demo store)",
            "billed_amount": 182,
            "items": [
                {"name": CATALOG["demo-milk"]["name"], "quantity": 2},
                {"name": CATALOG["demo-bananas"]["name"], "quantity": 1},
                {"name": CATALOG["demo-bread"]["name"], "quantity": 1},
            ],
            "demo": True,
        }

    # ---- operations (by logical op name, same names as tool_map.py) ----

    def run(self, op: str, arguments: dict | None = None):
        arguments = arguments or {}
        if op == "get_cart":
            return self._cart_view()
        if op == "list_orders":
            return [self._order_view()]
        if op == "list_addresses":
            return copy.deepcopy(ADDRESSES)
        if op == "clear_cart":
            self.cart = {}
            return self._cart_view()
        if op == "add_to_cart":
            item_id = str(arguments.get("item_id", ""))
            if item_id not in CATALOG:
                raise KeyError(f"unknown demo item {item_id!r}; try one of {sorted(CATALOG)}")
            qty = int(arguments.get("quantity", 1))
            self.cart[item_id] = self.cart.get(item_id, 0) + qty
            return self._cart_view()
        raise KeyError(f"demo mode has no operation {op!r}")

    def snapshot(self, ops: list[str]) -> dict:
        out = {}
        for op in ops:
            try:
                out[op] = {"ok": True, "data": self.run(op)}
            except KeyError as exc:
                out[op] = {"ok": False, "error": "unsupported", "detail": str(exc)}
        return out

    def seconds_since_reset(self) -> int:
        return int(time.time() - self.started_at)


READ_OPS = ["get_cart", "list_orders", "list_addresses"]
