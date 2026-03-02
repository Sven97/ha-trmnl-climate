from __future__ import annotations

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector
from homeassistant.helpers.selector import (
    AreaSelector,
    AreaSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_AREA_FILTER,
    CONF_CHART_HOURS,
    CONF_CHART_SENSOR_TYPES,
    CONF_PUSH_INTERVAL,
    CONF_SHOW_CHART,
    CONF_WEBHOOK_URL,
    DOMAIN,
    SENSOR_DISPLAY_ORDER,
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
    """Options flow for display and push settings."""

    def __init__(self, config_entry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        opts = self._entry.options

        sensor_type_options = [
            {"value": dc, "label": dc.replace("_", " ").title()}
            for dc in SENSOR_DISPLAY_ORDER
        ]
        chart_hours_options = [
            {"value": "6", "label": "6 h"},
            {"value": "12", "label": "12 h"},
            {"value": "24", "label": "24 h"},
        ]

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_SHOW_CHART,
                    default=opts.get(CONF_SHOW_CHART, False),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_AREA_FILTER,
                    default=opts.get(CONF_AREA_FILTER, []),
                ): AreaSelector(AreaSelectorConfig(multiple=True)),
                vol.Optional(
                    CONF_CHART_SENSOR_TYPES,
                    default=opts.get(CONF_CHART_SENSOR_TYPES, []),
                ): SelectSelector(SelectSelectorConfig(
                    options=sensor_type_options,
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )),
                vol.Optional(
                    CONF_CHART_HOURS,
                    default=opts.get(CONF_CHART_HOURS, "24"),
                ): SelectSelector(SelectSelectorConfig(
                    options=chart_hours_options,
                    multiple=False,
                    mode=SelectSelectorMode.LIST,
                )),
                vol.Optional(
                    CONF_PUSH_INTERVAL,
                    default=opts.get(CONF_PUSH_INTERVAL, 15),
                ): NumberSelector(NumberSelectorConfig(
                    min=5,
                    max=60,
                    step=5,
                    mode=NumberSelectorMode.BOX,
                )),
            }),
        )
