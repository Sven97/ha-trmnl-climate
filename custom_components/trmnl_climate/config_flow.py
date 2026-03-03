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
    CONF_AREAS,
    CONF_CHART_HOURS,
    CONF_CHART_SENSOR_TYPE,
    CONF_CHART_TYPE,
    CONF_DISPLAY_MODE,
    CONF_PUSH_INTERVAL,
    CONF_SENSOR_TYPES,
    CONF_WEBHOOK_URL,
    DOMAIN,
    SENSOR_DISPLAY_ORDER,
)

_DISPLAY_MODE_OPTIONS = [
    {"value": "values", "label": "Values — current sensor readings"},
    {"value": "chart",  "label": "Chart — history or gauges"},
]

_SENSOR_TYPE_LABELS = {
    "temperature":                "Temperature",
    "humidity":                   "Humidity",
    "carbon_dioxide":             "CO₂",
    "pressure":                   "Pressure",
    "pm25":                       "PM2.5",
    "pm10":                       "PM10",
    "volatile_organic_compounds": "VOC",
    "nitrogen_dioxide":           "NO₂",
    "carbon_monoxide":            "CO",
}
_CHART_TYPE_OPTIONS = [
    {"value": "line",  "label": "Line chart — history over time"},
    {"value": "gauge", "label": "Gauge — current value"},
]
_CHART_HOURS_OPTIONS = [
    {"value": "6",  "label": "6 h"},
    {"value": "12", "label": "12 h"},
    {"value": "24", "label": "24 h"},
]


def _sensor_type_options(hass, area_filter: list[str]) -> list[dict]:
    """Return sensor type options actually present in the selected areas."""
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)
    found: set[str] = set()

    for entity in entity_reg.entities.values():
        if not entity.entity_id.startswith("sensor.") or entity.disabled_by is not None:
            continue
        state = hass.states.get(entity.entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            continue
        dc = state.attributes.get("device_class")
        if dc not in CLIMATE_DEVICE_CLASSES:
            continue
        area_id = entity.area_id
        if area_id is None and entity.device_id:
            device = device_reg.async_get(entity.device_id)
            if device:
                area_id = device.area_id
        if area_id is None:
            continue
        if area_filter and area_id not in area_filter:
            continue
        found.add(dc)

    return [
        {"value": dc, "label": _SENSOR_TYPE_LABELS.get(dc, dc.replace("_", " ").title())}
        for dc in SENSOR_DISPLAY_ORDER if dc in found
    ]


def _areas_with_climate_sensors(hass) -> list[dict]:
    """Return [{"value": area_id, "label": area_name}] for areas with any climate sensor."""
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
        if state.attributes.get("device_class") not in CLIMATE_DEVICE_CLASSES:
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
    """Options flow: push interval → areas → display mode → (chart style)."""

    def __init__(self, config_entry) -> None:
        self._entry = config_entry
        self._options: dict = dict(config_entry.options)

    # ------------------------------------------------------------------
    # Step 1: push interval
    # ------------------------------------------------------------------

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_areas()

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
            }),
        )

    # ------------------------------------------------------------------
    # Step 2: area selection (max 4)
    # ------------------------------------------------------------------

    async def async_step_areas(self, user_input=None):
        errors = {}
        if user_input is not None:
            if len(user_input.get(CONF_AREAS, [])) > 4:
                errors[CONF_AREAS] = "too_many_areas"
            else:
                self._options.update(user_input)
                return await self.async_step_display()

        opts = self._options
        area_options = _areas_with_climate_sensors(self.hass)
        valid_ids = {o["value"] for o in area_options}
        default_areas = [a for a in opts.get(CONF_AREAS, []) if a in valid_ids]

        return self.async_show_form(
            step_id="areas",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_AREAS,
                    default=default_areas,
                ): SelectSelector(SelectSelectorConfig(
                    options=area_options,
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )),
            }),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Step 3: display mode (values or chart)
    # ------------------------------------------------------------------

    async def async_step_display(self, user_input=None):
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_sensor_types()

        opts = self._options
        return self.async_show_form(
            step_id="display",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_DISPLAY_MODE,
                    default=opts.get(CONF_DISPLAY_MODE, "values"),
                ): SelectSelector(SelectSelectorConfig(
                    options=_DISPLAY_MODE_OPTIONS,
                    multiple=False,
                    mode=SelectSelectorMode.LIST,
                )),
            }),
        )

    # ------------------------------------------------------------------
    # Step 4: sensor type selection
    #   values mode → multi-select → create entry
    #   chart mode  → single-select → step 5
    # ------------------------------------------------------------------

    async def async_step_sensor_types(self, user_input=None):
        mode = self._options.get(CONF_DISPLAY_MODE, "values")
        area_filter = list(self._options.get(CONF_AREAS, []))
        type_options = _sensor_type_options(self.hass, area_filter)
        valid = {o["value"] for o in type_options}

        if user_input is not None:
            self._options.update(user_input)
            if mode == "chart":
                return await self.async_step_chart_type()
            return self.async_create_entry(data=self._options)

        opts = self._options
        if mode == "values":
            default = [t for t in opts.get(CONF_SENSOR_TYPES, []) if t in valid]
            schema = vol.Schema({
                vol.Optional(CONF_SENSOR_TYPES, default=default): SelectSelector(
                    SelectSelectorConfig(
                        options=type_options,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            })
        else:
            current = opts.get(CONF_CHART_SENSOR_TYPE)
            default = current if current in valid else (type_options[0]["value"] if type_options else "temperature")
            schema = vol.Schema({
                vol.Required(CONF_CHART_SENSOR_TYPE, default=default): SelectSelector(
                    SelectSelectorConfig(
                        options=type_options,
                        multiple=False,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            })

        return self.async_show_form(
            step_id="sensor_types",
            data_schema=schema,
        )

    # ------------------------------------------------------------------
    # Step 5 (only for chart mode): chart type + history window
    # ------------------------------------------------------------------

    async def async_step_chart_type(self, user_input=None):
        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(data=self._options)

        opts = self._options
        schema: dict = {
            vol.Required(
                CONF_CHART_TYPE,
                default=opts.get(CONF_CHART_TYPE, "line"),
            ): SelectSelector(SelectSelectorConfig(
                options=_CHART_TYPE_OPTIONS,
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
        }

        return self.async_show_form(
            step_id="chart_type",
            data_schema=vol.Schema(schema),
        )
