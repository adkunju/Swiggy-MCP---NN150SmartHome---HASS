from __future__ import annotations

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import CONF_BASE_URL, DEFAULT_BASE_URL, DOMAIN


class SwiggyBridgeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            try:
                session = aiohttp.ClientSession()
                try:
                    async with session.get(f"{base_url}/api/status", timeout=10) as resp:
                        if resp.status != 200:
                            errors["base"] = "cannot_connect"
                finally:
                    await session.close()
            except aiohttp.ClientError:
                errors["base"] = "cannot_connect"

            if not errors:
                await self.async_set_unique_id(base_url)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Swiggy MCP Bridge",
                    data={CONF_BASE_URL: base_url},
                )

        schema = vol.Schema({vol.Required(CONF_BASE_URL, default=DEFAULT_BASE_URL): str})
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SwiggyBridgeOptionsFlow(config_entry)


class SwiggyBridgeOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL)
        schema = vol.Schema({vol.Required(CONF_BASE_URL, default=current): str})
        return self.async_show_form(step_id="init", data_schema=schema)
