DOMAIN = "swiggy_bridge"

CONF_BASE_URL = "base_url"

# The add-on does not publish port 8099 on the host (its API has no auth), so
# Home Assistant has to reach it on the Supervisor's internal network by the
# add-on's hostname. That hostname is "<repo hash>-swiggy-mcp-bridge", where
# the hash is the first 8 hex chars of sha1(repository URL as added to the
# add-on store, lowercased). This default assumes the repo was added as
# https://github.com/adkunju/Swiggy-MCP---NN150SmartHome---HASS -- if setup
# says it can't connect, copy the real hostname from the add-on's Info tab.
DEFAULT_BASE_URL = "http://1fb9fa61-swiggy-mcp-bridge:8099"

# Polling intervals in seconds (see coordinator.py).
DEFAULT_SCAN_INTERVAL = 300
ACTIVE_ORDER_SCAN_INTERVAL = 60
DEMO_SCAN_INTERVAL = 15

TERMINAL_ORDER_STATES = {"delivered", "cancelled", "canceled", "failed", "refunded"}
