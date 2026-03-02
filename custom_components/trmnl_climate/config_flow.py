from __future__ import annotations

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import area_registry as ar, selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CHART_DAILY_AVERAGE,
    CHART_DAILY_MINMAX,
    CHART_RESOLUTION_1H,
    CHART_RESOLUTION_2H,
    CHART_RESOLUTION_6H,
    CHART_TYPE_24H,
    CHART_TYPE_7DAY,
    CHART_TYPE_DISABLED,
    CONF_CHART_AREA,
    CONF_CHART_DAILY_MODE,
    CONF_CHART_RESOLUTION,
    CONF_CHART_SENSOR,
    CONF_CHART_TYPE,
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
    """Options flow for chart configuration."""

    def __init__(self, config_entry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        cur = self._entry.options

        # Build dynamic area list from the area registry
        area_reg = ar.async_get(self.hass)
        area_choices = [{"value": "", "label": "Auto-select (first matching area)"}]
        area_choices += sorted(
            [{"value": a.id, "label": a.name} for a in area_reg.async_list_areas()],
            key=lambda x: x["label"],
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_CHART_TYPE,
                    default=cur.get(CONF_CHART_TYPE, CHART_TYPE_DISABLED),
                ): selector.SelectSelector(selector.SelectSelectorConfig(
                    options=[
                        {"value": CHART_TYPE_DISABLED, "label": "Disabled"},
                        {"value": CHART_TYPE_24H,      "label": "24h trend"},
                        {"value": CHART_TYPE_7DAY,     "label": "7-day averages"},
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )),
                vol.Required(
                    CONF_CHART_SENSOR,
                    default=cur.get(CONF_CHART_SENSOR, "temperature"),
                ): selector.SelectSelector(selector.SelectSelectorConfig(
                    options=[
                        {"value": "temperature",              "label": "Temperature"},
                        {"value": "humidity",                 "label": "Humidity"},
                        {"value": "carbon_dioxide",           "label": "CO₂"},
                        {"value": "pressure",                 "label": "Pressure"},
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )),
                vol.Required(
                    CONF_CHART_AREA,
                    default=cur.get(CONF_CHART_AREA, ""),
                ): selector.SelectSelector(selector.SelectSelectorConfig(
                    options=area_choices,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )),
                vol.Required(
                    CONF_CHART_RESOLUTION,
                    default=cur.get(CONF_CHART_RESOLUTION, CHART_RESOLUTION_1H),
                ): selector.SelectSelector(selector.SelectSelectorConfig(
                    options=[
                        {"value": CHART_RESOLUTION_1H, "label": "Hourly (24 points)"},
                        {"value": CHART_RESOLUTION_2H, "label": "Every 2h (12 points)"},
                        {"value": CHART_RESOLUTION_6H, "label": "Every 6h (4 points)"},
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )),
                vol.Required(
                    CONF_CHART_DAILY_MODE,
                    default=cur.get(CONF_CHART_DAILY_MODE, CHART_DAILY_MINMAX),
                ): selector.SelectSelector(selector.SelectSelectorConfig(
                    options=[
                        {"value": CHART_DAILY_MINMAX,   "label": "Daily min / max + average"},
                        {"value": CHART_DAILY_AVERAGE,  "label": "Daily average only"},
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )),
            }),
        )
