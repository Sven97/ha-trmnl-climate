from __future__ import annotations

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector

from .const import (
    CONF_SHOW_CHART,
    CONF_WEBHOOK_URL,
    DOMAIN,
)


class TrmnlClimateConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for TRMNL HA Climate Connector."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            url = user_input[CONF_WEBHOOK_URL].strip()

            if not url.startswith("https://"):
                errors[CONF_WEBHOOK_URL] = "invalid_url"
            else:
                try:
                    session = async_get_clientsession(self.hass)
                    async with session.post(
                        url,
                        json={"merge_variables": {}},
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status not in (200, 201, 202):
                            errors[CONF_WEBHOOK_URL] = "cannot_connect"
                except Exception:
                    errors[CONF_WEBHOOK_URL] = "cannot_connect"

            if not errors:
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="TRMNL HA Climate Connector",
                    data={CONF_WEBHOOK_URL: url},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_WEBHOOK_URL): str}),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return TrmnlClimateOptionsFlow(config_entry)


class TrmnlClimateOptionsFlow(config_entries.OptionsFlow):
    """Options flow — single toggle to enable 24h history charts."""

    def __init__(self, config_entry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_SHOW_CHART,
                    default=self._entry.options.get(CONF_SHOW_CHART, False),
                ): selector.BooleanSelector(),
            }),
        )
