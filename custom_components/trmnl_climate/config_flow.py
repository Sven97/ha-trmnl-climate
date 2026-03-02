from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import aiohttp

from .const import DOMAIN, CONF_WEBHOOK_URL

STEP_SCHEMA = vol.Schema({
    vol.Required(CONF_WEBHOOK_URL): str,
})


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
                # Test reachability with an empty merge_variables payload
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
            data_schema=STEP_SCHEMA,
            errors=errors,
        )
