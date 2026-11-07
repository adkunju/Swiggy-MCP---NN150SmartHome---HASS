from __future__ import annotations

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_BASE_URL, DEFAULT_BASE_URL, DOMAIN


class SwiggyBridgeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _can_reach(self, base_url: str) -> bool:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                f"{base_url}/api/status", timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                return resp.status == 200
        except (aiohttp.ClientError, TimeoutError):
            return False

    async def async_step_user(self, user_input: dict | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].strip().rstrip("/")
            if await self._can_reach(base_url):
                await self.async_set_unique_id(base_url)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Swiggy MCP Bridge", data={CONF_BASE_URL: base_url})
            errors["base"] = "cannot_connect"

        default = (user_input or {}).get(CONF_BASE_URL, DEFAULT_BASE_URL)
        schema = vol.Schema({vol.Required(CONF_BASE_URL, default=default): str})
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
