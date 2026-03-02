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
    CHART_SENSOR_ORDER,
    CHART_TYPE_SHORT,
    CHART_YAXIS_RIGHT,
    CLIMATE_DEVICE_CLASSES,
    CONF_AREA_FILTER,
    CONF_CHART_HOURS,
    CONF_CHART_SENSOR_TYPES,
    CONF_PUSH_INTERVAL,
    CONF_SHOW_CHART,
    CONF_WEBHOOK_URL,
    DOMAIN,
    SENSOR_DISPLAY_ORDER,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["button"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    webhook_url = entry.data[CONF_WEBHOOK_URL]

    async def push_climate_data(_now=None) -> None:
        options = entry.options
        areas_data = _build_areas_data(hass)
        if not areas_data:
            _LOGGER.debug("No climate sensors found in any area — skipping push")
            return

        merge_vars: dict = {
            "areas": areas_data,
            "last_updated": dt_util.now().strftime("%H:%M"),
        }

        chart_data = await _build_chart_data(hass, options)
        merge_vars.update(chart_data)

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

    await push_climate_data()

    push_interval = int(entry.options.get(CONF_PUSH_INTERVAL, 15))
    entry.async_on_unload(
        async_track_time_interval(
            hass,
            push_climate_data,
            timedelta(minutes=push_interval),
        )
    )

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
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

def _find_chart_entities_by_class(hass: HomeAssistant, options: dict) -> dict[str, list[dict]]:
    """Return {device_class: [{entity_id, area_name, unit}]} — one entity per area."""
    area_filter: list[str] = options.get(CONF_AREA_FILTER, [])

    area_reg = ar.async_get(hass)
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

    seen: dict[str, set[str]] = {}
    result: dict[str, list[dict]] = {}

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

        if area_filter and area_id not in area_filter:
            continue

        area = area_reg.async_get_area(area_id)
        if area is None:
            continue

        seen.setdefault(device_class, set())
        if area_id in seen[device_class]:
            continue
        seen[device_class].add(area_id)

        result.setdefault(device_class, [])
        result[device_class].append({
            "entity_id": entity.entity_id,
            "area_name": area.name,
            "unit": state.attributes.get("unit_of_measurement", ""),
        })

    for dc in result:
        result[dc].sort(key=lambda x: x["area_name"])

    return result


async def _build_chart_data(hass: HomeAssistant, options: dict) -> dict:
    """
    Build a single combined chart with all sensor types.

    Returns {"chart": {labels, left_unit, right_unit, has_right, series}}
    where each series has {label, y_axis (0=left, 1=right), data}.
    All series share the same x-axis labels (union of hourly buckets).
    """
    if not options.get(CONF_SHOW_CHART, False):
        return {}

    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.history import get_significant_states
    except ImportError:
        _LOGGER.debug("Recorder not available — chart data skipped")
        return {}

    entities_by_class = _find_chart_entities_by_class(hass, options)
    if not entities_by_class:
        return {}

    # Filter to selected sensor types (empty = all)
    chart_sensor_types: list[str] = options.get(CONF_CHART_SENSOR_TYPES, [])
    if chart_sensor_types:
        entities_by_class = {
            dc: ents
            for dc, ents in entities_by_class.items()
            if dc in chart_sensor_types
        }
    if not entities_by_class:
        return {}

    all_entity_ids = [
        e["entity_id"]
        for ents in entities_by_class.values()
        for e in ents
    ]

    chart_hours = int(options.get(CONF_CHART_HOURS, 24))
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
        return {}

    # Bucket all entities into hourly averages
    entity_buckets: dict[str, dict[int, list[float]]] = {}
    all_hour_keys: set[int] = set()

    for entity_id in all_entity_ids:
        buckets: dict[int, list[float]] = defaultdict(list)
        for s in states_map.get(entity_id, []):
            try:
                v = float(s.state)
            except (ValueError, AttributeError):
                continue
            key = int((s.last_changed.astimezone(tz) - start_local).total_seconds() // 3600)
            if 0 <= key < chart_hours:
                buckets[key].append(v)
                all_hour_keys.add(key)
        entity_buckets[entity_id] = buckets

    if not all_hour_keys:
        return {}

    sorted_keys = sorted(all_hour_keys)
    labels = [
        (start_local + timedelta(hours=k)).strftime("%H:%M")
        for k in sorted_keys
    ]

    # Determine charted classes and y-axis units
    charted_classes = [dc for dc in CHART_SENSOR_ORDER if dc in entities_by_class]
    multi_type = len(charted_classes) > 1

    left_unit = ""
    right_unit = ""
    for dc in charted_classes:
        if dc not in CHART_YAXIS_RIGHT and not left_unit:
            left_unit = entities_by_class[dc][0]["unit"]
        if dc in CHART_YAXIS_RIGHT and not right_unit:
            right_unit = entities_by_class[dc][0]["unit"]

    # Build series aligned to shared labels
    series = []
    has_right = False

    for device_class in charted_classes:
        y_axis = 1 if device_class in CHART_YAXIS_RIGHT else 0
        if y_axis == 1:
            has_right = True

        short = CHART_TYPE_SHORT.get(device_class, device_class)

        for e in entities_by_class[device_class]:
            buckets = entity_buckets[e["entity_id"]]
            data = [
                round(sum(buckets[k]) / len(buckets[k]), 1) if k in buckets else None
                for k in sorted_keys
            ]
            if not any(v is not None for v in data):
                continue

            label = f"{e['area_name']} {short}" if multi_type else e["area_name"]
            series.append({"label": label, "y_axis": y_axis, "data": data})

    if not series:
        return {}

    return {
        "chart": {
            "labels": labels,
            "left_unit": left_unit,
            "right_unit": right_unit,
            "has_right": has_right,
            "series": series,
        }
    }
