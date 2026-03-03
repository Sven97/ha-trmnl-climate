from __future__ import annotations

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CLIMATE_DEVICE_CLASSES,
    CONF_CHART_COUNT,
    CONF_CHART_HOURS,
    CONF_CHART1_AREAS,
    CONF_CHART1_SENSOR_TYPE,
    CONF_CHART1_TYPE,
    CONF_CHART2_AREAS,
    CONF_CHART2_SENSOR_TYPE,
    CONF_CHART2_TYPE,
    CONF_PUSH_INTERVAL,
    CONF_WEBHOOK_URL,
    DOMAIN,
    SENSOR_DISPLAY_ORDER,
)

_CHART_COUNT_OPTIONS = [
    {"value": "0", "label": "No charts"},
    {"value": "1", "label": "1 chart"},
    {"value": "2", "label": "2 charts"},
]
_CHART_HOURS_OPTIONS = [
    {"value": "6",  "label": "6 h"},
    {"value": "12", "label": "12 h"},
    {"value": "24", "label": "24 h"},
]
_CHART_TYPE_OPTIONS = [
    {"value": "line",  "label": "Line"},
    {"value": "bar",   "label": "Bar"},
    {"value": "gauge", "label": "Gauge"},
]


def _available_sensor_types(hass) -> list[str]:
    """Return device classes (in display order) that have at least one live entity."""
    entity_reg = er.async_get(hass)
    found: set[str] = set()
    for entity in entity_reg.entities.values():
        if not entity.entity_id.startswith("sensor.") or entity.disabled_by is not None:
            continue
        state = hass.states.get(entity.entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            continue
        dc = state.attributes.get("device_class")
        if dc in CLIMATE_DEVICE_CLASSES:
            found.add(dc)
    return [dc for dc in SENSOR_DISPLAY_ORDER if dc in found]


def _areas_with_sensor_type(hass, sensor_type: str) -> list[dict]:
    """Return [{"value": area_id, "label": area_name}] for areas that have the sensor type."""
    area_reg = ar.async_get(hass)
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)
    seen: set[str] = set()
    options: list[dict] = []
    for entity in entity_reg.entities.values():
        if not entity.entity_id.startswith("sensor.") or entity.disabled_by is not None:
            continue
        state = hass.states.get(entity.entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            continue
        if state.attributes.get("device_class") != sensor_type:
            continue
        area_id = entity.area_id
        if area_id is None and entity.device_id:
            device = device_reg.async_get(entity.device_id)
            if device:
                area_id = device.area_id
        if area_id is None or area_id in seen:
            continue
        area = area_reg.async_get_area(area_id)
        if area is None:
            continue
        seen.add(area_id)
        options.append({"value": area_id, "label": area.name})
    return sorted(options, key=lambda x: x["label"])


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
    """Multi-step options flow."""

    def __init__(self, config_entry) -> None:
        self._entry = config_entry
        self._options: dict = dict(config_entry.options)

    # ------------------------------------------------------------------
    # Step 1: global settings
    # ------------------------------------------------------------------

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            self._options.update(user_input)
            if int(user_input.get(CONF_CHART_COUNT, 0)) >= 1:
                return await self.async_step_chart1()
            return self.async_create_entry(data=self._options)

        opts = self._options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_PUSH_INTERVAL,
                    default=opts.get(CONF_PUSH_INTERVAL, 15),
                ): NumberSelector(NumberSelectorConfig(
                    min=5, max=60, step=5, mode=NumberSelectorMode.BOX,
                )),
                vol.Required(
                    CONF_CHART_COUNT,
                    default=opts.get(CONF_CHART_COUNT, "0"),
                ): SelectSelector(SelectSelectorConfig(
                    options=_CHART_COUNT_OPTIONS,
                    multiple=False,
                    mode=SelectSelectorMode.LIST,
                )),
                vol.Optional(
                    CONF_CHART_HOURS,
                    default=opts.get(CONF_CHART_HOURS, "24"),
                ): SelectSelector(SelectSelectorConfig(
                    options=_CHART_HOURS_OPTIONS,
                    multiple=False,
                    mode=SelectSelectorMode.LIST,
                )),
            }),
        )

    # ------------------------------------------------------------------
    # Step 2: chart 1 — sensor type + chart style
    # ------------------------------------------------------------------

    async def async_step_chart1(self, user_input=None):
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_chart1_areas()

        opts = self._options
        sensor_types = _available_sensor_types(self.hass)
        sensor_type_options = [
            {"value": dc, "label": dc.replace("_", " ").title()} for dc in sensor_types
        ] or [{"value": "temperature", "label": "Temperature"}]
        default_sensor = opts.get(CONF_CHART1_SENSOR_TYPE, sensor_type_options[0]["value"])

        return self.async_show_form(
            step_id="chart1",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_CHART1_SENSOR_TYPE,
                    default=default_sensor,
                ): SelectSelector(SelectSelectorConfig(
                    options=sensor_type_options,
                    multiple=False,
                    mode=SelectSelectorMode.LIST,
                )),
                vol.Required(
                    CONF_CHART1_TYPE,
                    default=opts.get(CONF_CHART1_TYPE, "line"),
                ): SelectSelector(SelectSelectorConfig(
                    options=_CHART_TYPE_OPTIONS,
                    multiple=False,
                    mode=SelectSelectorMode.LIST,
                )),
            }),
        )

    # ------------------------------------------------------------------
    # Step 3: chart 1 — area filter
    # ------------------------------------------------------------------

    async def async_step_chart1_areas(self, user_input=None):
        if user_input is not None:
            self._options.update(user_input)
            if int(self._options.get(CONF_CHART_COUNT, 1)) >= 2:
                return await self.async_step_chart2()
            return self.async_create_entry(data=self._options)

        opts = self._options
        sensor_type = opts.get(CONF_CHART1_SENSOR_TYPE, "temperature")
        area_options = _areas_with_sensor_type(self.hass, sensor_type)
        valid_ids = {o["value"] for o in area_options}
        default_areas = [a for a in opts.get(CONF_CHART1_AREAS, []) if a in valid_ids]

        return self.async_show_form(
            step_id="chart1_areas",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_CHART1_AREAS,
                    default=default_areas,
                ): SelectSelector(SelectSelectorConfig(
                    options=area_options,
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )),
            }),
        )

    # ------------------------------------------------------------------
    # Step 4: chart 2 — sensor type + chart style
    # ------------------------------------------------------------------

    async def async_step_chart2(self, user_input=None):
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_chart2_areas()

        opts = self._options
        sensor_types = _available_sensor_types(self.hass)
        sensor_type_options = [
            {"value": dc, "label": dc.replace("_", " ").title()} for dc in sensor_types
        ] or [{"value": "humidity", "label": "Humidity"}]
        default_sensor = opts.get(CONF_CHART2_SENSOR_TYPE, sensor_type_options[0]["value"])

        return self.async_show_form(
            step_id="chart2",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_CHART2_SENSOR_TYPE,
                    default=default_sensor,
                ): SelectSelector(SelectSelectorConfig(
                    options=sensor_type_options,
                    multiple=False,
                    mode=SelectSelectorMode.LIST,
                )),
                vol.Required(
                    CONF_CHART2_TYPE,
                    default=opts.get(CONF_CHART2_TYPE, "line"),
                ): SelectSelector(SelectSelectorConfig(
                    options=_CHART_TYPE_OPTIONS,
                    multiple=False,
                    mode=SelectSelectorMode.LIST,
                )),
            }),
        )

    # ------------------------------------------------------------------
    # Step 5: chart 2 — area filter
    # ------------------------------------------------------------------

    async def async_step_chart2_areas(self, user_input=None):
        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(data=self._options)

        opts = self._options
        sensor_type = opts.get(CONF_CHART2_SENSOR_TYPE, "humidity")
        area_options = _areas_with_sensor_type(self.hass, sensor_type)
        valid_ids = {o["value"] for o in area_options}
        default_areas = [a for a in opts.get(CONF_CHART2_AREAS, []) if a in valid_ids]

        return self.async_show_form(
            step_id="chart2_areas",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_CHART2_AREAS,
                    default=default_areas,
                ): SelectSelector(SelectSelectorConfig(
                    options=area_options,
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )),
            }),
        )
