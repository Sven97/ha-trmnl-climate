from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

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
    GAUGE_RANGES,
    SENSOR_DISPLAY_ORDER,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["button"]


class TrmnlPushCoordinator:
    """Pushes climate data to TRMNL on a schedule; also supports on-demand refresh."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry

    async def async_refresh(self) -> None:
        """Push climate data to TRMNL immediately (called by button and timer)."""
        try:
            await self._async_push()
        except Exception as err:
            _LOGGER.error("Error pushing climate data to TRMNL: %s", err)

    async def _async_push(self) -> None:
        webhook_url = self._entry.data[CONF_WEBHOOK_URL]
        options = self._entry.options

        area_filter = list(options.get(CONF_AREAS, []))
        sensor_type_filter = list(options.get(CONF_SENSOR_TYPES, []))
        areas_data = _build_areas_data(self.hass, area_filter, sensor_type_filter)
        if not areas_data:
            _LOGGER.debug("No climate sensors found in any area — skipping push")
            return

        merge_vars: dict = {
            "areas": areas_data,
            "last_updated": dt_util.now().strftime("%H:%M"),
        }

        if options.get(CONF_DISPLAY_MODE) == "chart":
            chart_type = options.get(CONF_CHART_TYPE, "line")
            chart_hours = int(options.get(CONF_CHART_HOURS, 24))

            sensor_type = options.get(CONF_CHART_SENSOR_TYPE)
            if not sensor_type:
                available = _available_sensor_types_in_areas(self.hass, area_filter)
                sensor_type = available[0] if available else None

            if sensor_type:
                data = await _build_chart(
                    self.hass, chart_type, sensor_type, area_filter, chart_hours
                )
                if data:
                    merge_vars["chart"] = data

        session = async_get_clientsession(self.hass)
        async with session.post(
            webhook_url,
            json={"merge_variables": merge_vars},
            timeout=10,
        ) as resp:
            if resp.status not in (200, 201, 202):
                raise RuntimeError(
                    f"TRMNL push failed: HTTP {resp.status} — {await resp.text()}"
                )

        _LOGGER.debug("TRMNL push successful (%s areas)", len(areas_data))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = TrmnlPushCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    push_interval = int(entry.options.get(CONF_PUSH_INTERVAL, 15))

    @callback
    def _handle_interval(_now) -> None:
        hass.async_create_task(coordinator.async_refresh())

    entry.async_on_unload(
        async_track_time_interval(hass, _handle_interval, timedelta(minutes=push_interval))
    )

    await coordinator.async_refresh()

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


# ---------------------------------------------------------------------------
# Current sensor data
# ---------------------------------------------------------------------------

def _build_areas_data(
    hass: HomeAssistant,
    area_filter: list[str],
    sensor_type_filter: list[str],
) -> list[dict]:
    """Return climate sensors grouped by area, sorted by area name. Capped at 4."""
    area_reg = ar.async_get(hass)
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

    areas: dict[str, dict] = {}

    for entity in entity_reg.entities.values():
        if not entity.entity_id.startswith("sensor."):
            continue
        if entity.disabled_by is not None:
            continue

        state = hass.states.get(entity.entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            continue

        device_class = state.attributes.get("device_class")
        if device_class not in CLIMATE_DEVICE_CLASSES:
            continue
        if sensor_type_filter and device_class not in sensor_type_filter:
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

        area = area_reg.async_get_area(area_id)
        if area is None:
            continue

        if area_id not in areas:
            areas[area_id] = {"area": area.name, "sensors": []}

        areas[area_id]["sensors"].append({
            "state": state.state,
            "unit": state.attributes.get("unit_of_measurement", ""),
            "device_class": device_class,
        })

    order = {dc: i for i, dc in enumerate(SENSOR_DISPLAY_ORDER)}
    for area in areas.values():
        area["sensors"].sort(key=lambda s: order.get(s["device_class"], 99))

    return sorted(areas.values(), key=lambda a: a["area"])[:4]


# ---------------------------------------------------------------------------
# Chart data
# ---------------------------------------------------------------------------

def _available_sensor_types_in_areas(
    hass: HomeAssistant,
    area_filter: list[str],
) -> list[str]:
    """Return sensor types (in SENSOR_DISPLAY_ORDER) present in the filtered areas."""
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

    return [dc for dc in SENSOR_DISPLAY_ORDER if dc in found]


def _find_chart_entities_by_class(
    hass: HomeAssistant,
    sensor_type: str,
    area_filter: list[str],
) -> list[dict]:
    """Return [{entity_id, area_name, unit}] for one sensor type — one entity per area."""
    area_reg = ar.async_get(hass)
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

    seen_areas: set[str] = set()
    result: list[dict] = []

    for entity in entity_reg.entities.values():
        if not entity.entity_id.startswith("sensor."):
            continue
        if entity.disabled_by is not None:
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

        if area_id is None:
            continue

        if area_filter and area_id not in area_filter:
            continue

        area = area_reg.async_get_area(area_id)
        if area is None:
            continue

        if area_id in seen_areas:
            continue
        seen_areas.add(area_id)

        result.append({
            "entity_id": entity.entity_id,
            "area_name": area.name,
            "unit": state.attributes.get("unit_of_measurement", ""),
        })

    result.sort(key=lambda x: x["area_name"])
    return result[:4]


async def _build_chart(
    hass: HomeAssistant,
    chart_type: str,
    sensor_type: str,
    area_filter: list[str],
    chart_hours: int,
) -> dict | None:
    if chart_type == "gauge":
        return _build_gauge_chart(hass, sensor_type, area_filter)
    return await _build_timeseries_chart(hass, sensor_type, area_filter, chart_hours)


def _build_gauge_chart(
    hass: HomeAssistant,
    sensor_type: str,
    area_filter: list[str],
) -> dict | None:
    """Build gauge chart data from current sensor states."""
    entities = _find_chart_entities_by_class(hass, sensor_type, area_filter)
    if not entities:
        return None

    gauges = []
    unit = ""
    for e in entities:
        state = hass.states.get(e["entity_id"])
        if state is None or state.state in ("unknown", "unavailable"):
            continue
        try:
            value = float(state.state)
        except (ValueError, AttributeError):
            continue
        if not unit:
            unit = e["unit"]
        gauges.append({"area": e["area_name"], "value": value})

    if not gauges:
        return None

    g_min, g_max = GAUGE_RANGES.get(sensor_type, (0, 100))
    return {
        "type": "gauge",
        "sensor_type": sensor_type,
        "title": sensor_type.replace("_", " ").title(),
        "unit": unit,
        "min": g_min,
        "max": g_max,
        "gauges": gauges,
    }


async def _build_timeseries_chart(
    hass: HomeAssistant,
    sensor_type: str,
    area_filter: list[str],
    chart_hours: int,
) -> dict | None:
    """Build line chart data from recorder history."""
    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.history import get_significant_states
    except ImportError:
        _LOGGER.debug("Recorder not available — chart data skipped")
        return None

    entities = _find_chart_entities_by_class(hass, sensor_type, area_filter)
    if not entities:
        return None

    all_entity_ids = [e["entity_id"] for e in entities]
    unit = entities[0]["unit"] if entities else ""
    num_buckets = 24
    bucket_minutes = chart_hours * 60 // num_buckets

    now = dt_util.now()
    tz = now.tzinfo
    start = now - timedelta(hours=chart_hours)
    start_local = start.astimezone(tz)

    try:
        states_map = await get_instance(hass).async_add_executor_job(
            get_significant_states,
            hass, start, now, all_entity_ids,
            None, True, False, False, True,
        )
    except Exception as err:
        _LOGGER.warning("Failed to fetch chart history: %s", err)
        return None

    entity_buckets: dict[str, dict[int, list[float]]] = {}
    all_bucket_keys: set[int] = set()

    for e in entities:
        buckets: dict[int, list[float]] = defaultdict(list)
        for s in states_map.get(e["entity_id"], []):
            try:
                v = float(s.state)
            except (ValueError, AttributeError):
                continue
            elapsed = (s.last_changed.astimezone(tz) - start_local).total_seconds()
            key = int(elapsed / (bucket_minutes * 60))
            if 0 <= key < num_buckets:
                buckets[key].append(v)
                all_bucket_keys.add(key)
        entity_buckets[e["entity_id"]] = dict(buckets)

    if not all_bucket_keys:
        return None

    sorted_keys = sorted(all_bucket_keys)
    labels = [
        (start_local + timedelta(minutes=k * bucket_minutes)).strftime("%H:%M")
        for k in sorted_keys
    ]

    series = []
    for e in entities:
        buckets = entity_buckets[e["entity_id"]]
        data = [
            round(sum(buckets[k]) / len(buckets[k]), 1) if k in buckets else None
            for k in sorted_keys
        ]
        if not any(v is not None for v in data):
            continue
        series.append({"label": e["area_name"], "data": data})

    if not series:
        return None

    return {
        "type": "line",
        "sensor_type": sensor_type,
        "title": sensor_type.replace("_", " ").title(),
        "unit": unit,
        "labels": labels,
        "series": series,
    }
