from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
    CONF_CHART_COUNT,
    CONF_CHART1_AREAS,
    CONF_CHART1_HOURS,
    CONF_CHART1_SENSOR_TYPE,
    CONF_CHART1_TYPE,
    CONF_CHART2_AREAS,
    CONF_CHART2_HOURS,
    CONF_CHART2_SENSOR_TYPE,
    CONF_CHART2_TYPE,
    CONF_PUSH_INTERVAL,
    CONF_WEBHOOK_URL,
    DOMAIN,
    GAUGE_RANGES,
    SENSOR_DISPLAY_ORDER,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["button"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    webhook_url = entry.data[CONF_WEBHOOK_URL]

    async def push_climate_data() -> None:
        options = entry.options
        areas_data = _build_areas_data(hass)
        if not areas_data:
            _LOGGER.debug("No climate sensors found in any area — skipping push")
            return

        merge_vars: dict = {
            "areas": areas_data,
            "last_updated": dt_util.now().strftime("%H:%M"),
        }

        chart_count = int(options.get(CONF_CHART_COUNT, 0))
        if chart_count >= 1:
            data = await _build_single_chart(hass, options, 1)
            if data:
                merge_vars["chart1"] = data
        if chart_count >= 2:
            data = await _build_single_chart(hass, options, 2)
            if data:
                merge_vars["chart2"] = data

        session = async_get_clientsession(hass)
        try:
            async with session.post(
                webhook_url,
                json={"merge_variables": merge_vars},
                timeout=10,
            ) as resp:
                if resp.status not in (200, 201, 202):
                    _LOGGER.warning(
                        "TRMNL push failed with status %s: %s",
                        resp.status,
                        await resp.text(),
                    )
                else:
                    _LOGGER.debug("TRMNL push successful (%s areas)", len(areas_data))
        except Exception as err:
            _LOGGER.error("Error pushing climate data to TRMNL: %s", err)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"push": push_climate_data}

    # Set up the button entity first so it exists before we try to press it
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Look up the button entity_id so the interval fires it via the service,
    # recording each push as a button press event in HA history.
    button_entity_id = er.async_get(hass).async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_push_button"
    )

    async def _trigger_push(_now=None) -> None:
        if button_entity_id:
            await hass.services.async_call(
                "button", "press",
                {"entity_id": button_entity_id},
                blocking=True,
            )
        else:
            await push_climate_data()

    # Initial push on startup
    await _trigger_push()

    push_interval = int(entry.options.get(CONF_PUSH_INTERVAL, 15))
    entry.async_on_unload(
        async_track_time_interval(
            hass,
            _trigger_push,
            timedelta(minutes=push_interval),
        )
    )

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change (picks up new push_interval etc.)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


# ---------------------------------------------------------------------------
# Current sensor data
# ---------------------------------------------------------------------------

def _build_areas_data(hass: HomeAssistant) -> list[dict]:
    """Return climate sensors grouped by area, sorted by area name."""
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

        area_id = entity.area_id
        if area_id is None and entity.device_id:
            device = device_reg.async_get(entity.device_id)
            if device:
                area_id = device.area_id

        if area_id is None:
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

    return sorted(areas.values(), key=lambda a: a["area"])


# ---------------------------------------------------------------------------
# Chart / history data
# ---------------------------------------------------------------------------

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

        device_class = state.attributes.get("device_class")
        if device_class != sensor_type:
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
    return result


def _build_gauge_chart(
    hass: HomeAssistant,
    sensor_type: str,
    area_filter: list[str],
) -> dict | None:
    """Build gauge chart data using current sensor states."""
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
        "sensor_type": sensor_type,
        "unit": unit,
        "labels": labels,
        "series": series,
    }


async def _build_single_chart(
    hass: HomeAssistant,
    options: dict,
    chart_num: int,
) -> dict | None:
    """Dispatch to gauge or line chart builder for chart slot 1 or 2."""
    sensor_type = options.get(f"chart{chart_num}_sensor_type", "temperature" if chart_num == 1 else "humidity")
    area_filter = options.get(f"chart{chart_num}_areas", [])
    chart_type = options.get(f"chart{chart_num}_type", "line")

    if chart_type == "gauge":
        return _build_gauge_chart(hass, sensor_type, area_filter)

    chart_hours = int(options.get(f"chart{chart_num}_hours", 24))
    return await _build_timeseries_chart(hass, sensor_type, area_filter, chart_hours)
