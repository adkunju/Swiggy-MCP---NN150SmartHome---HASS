"""
Maps our own logical operation names to the real MCP tool names on each
Swiggy server. Swiggy doesn't publish exact tool names/schemas outside the
Builders Club program, so these are PLACEHOLDERS -- call GET /api/<server>/tools
from the add-on UI once you have real access, then edit /data/tool_map.json
(the add-on UI has a page for this) to match what's actually returned. This
file only supplies the defaults used until that override exists.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger("swiggy_bridge.tool_map")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
OVERRIDE_FILE = DATA_DIR / "tool_map.json"

DEFAULTS = {
    "instamart": {
        "list_orders": "get_orders",        # TODO verify against tools/list
        "get_cart": "get_cart",
        "clear_cart": "clear_cart",
        "add_to_cart": "add_to_cart",
        "list_addresses": "get_addresses",
    },
    "dineout": {
        "list_bookings": "get_bookings",    # TODO verify against tools/list
        "search_restaurants": "search_restaurants",
    },
    "food": {
        # Food is not currently available to third-party Builders Club
        # integrators (per mcp.swiggy.com, Food access is ChatGPT-only as of
        # this writing) -- left empty on purpose. Don't enable "food" in the
        # add-on options until that changes.
    },
}


def load() -> dict:
    merged = {server: dict(ops) for server, ops in DEFAULTS.items()}
    if OVERRIDE_FILE.exists():
        try:
            override = json.loads(OVERRIDE_FILE.read_text())
            for server, ops in override.items():
                merged.setdefault(server, {}).update(ops)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Ignoring malformed tool_map.json: %s", exc)
    return merged


def save(mapping: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OVERRIDE_FILE.write_text(json.dumps(mapping, indent=2))
