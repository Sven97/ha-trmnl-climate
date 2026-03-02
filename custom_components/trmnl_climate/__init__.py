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
    CHART_TYPE_PREFERRED,
    CLIMATE_DEVICE_CLASSES,
    CONF_SHOW_CHART,
    CONF_WEBHOOK_URL,
    DOMAIN,
    PUSH_INTERVAL_MINUTES,
    SENSOR_DISPLAY_ORDER,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["button"]

_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    webhook_url = entry.data[CONF_WEBHOOK_URL]

    async def push_climate_data(_now=None) -> None:
        areas_data = _build_areas_data(hass)
        if not areas_data:
            _LOGGER.debug("No climate sensors found in any area — skipping push")
            return

        merge_vars: dict = {
            "areas": areas_data,
            "last_updated": dt_util.now().strftime("%H:%M"),
        }

        chart_data = await _build_chart_data(hass, entry.options)
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
    entry.async_on_unload(
        async_track_time_interval(
            hass,
            push_climate_data,
            timedelta(minutes=PUSH_INTERVAL_MINUTES),
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


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
) -> dict[str, list[dict]]:
    """Return {device_class: [{entity_id, area_name, unit}]} for all classes with data."""
    area_reg = ar.async_get(hass)
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

    # one entity per (device_class, area) pair
    seen: dict[str, set[str]] = {}   # device_class -> set of area_ids already added
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

    # Sort each class's entity list by area name for consistent ordering
    for dc in result:
        result[dc].sort(key=lambda x: x["area_name"])

    return result


def _build_aligned_series(
    states_map: dict,
    entities: list[dict],
    start,
    tz,
) -> tuple[list[str], list[dict]]:
    """
    Bucket 24h state history into hourly averages.

    Returns (labels, series):
    - labels: HH:MM strings only for hours that have data in ANY series
    - series[i].data: values aligned to labels, None for missing hours
    """
    entity_buckets: dict[str, dict[int, list[float]]] = {}
    all_keys: set[int] = set()
    start_local = start.astimezone(tz)

    for e in entities:
        buckets: dict[int, list[float]] = defaultdict(list)
        for s in states_map.get(e["entity_id"], []):
            try:
                v = float(s.state)
            except (ValueError, AttributeError):
                continue
            key = int((s.last_changed.astimezone(tz) - start_local).total_seconds() // 3600)
            if 0 <= key < 24:
                buckets[key].append(v)
                all_keys.add(key)
        entity_buckets[e["entity_id"]] = buckets

    if not all_keys:
        return [], []

    sorted_keys = sorted(all_keys)
    labels = [
        (start_local + timedelta(hours=k)).strftime("%H:%M")
        for k in sorted_keys
    ]

    series = []
    for e in entities:
        buckets = entity_buckets[e["entity_id"]]
        data = [
            round(sum(buckets[k]) / len(buckets[k]), 1) if k in buckets else None
            for k in sorted_keys
        ]
        if any(v is not None for v in data):
            series.append({"label": e["area_name"], "data": data})

    return labels, series


async def _build_chart_data(hass: HomeAssistant, options: dict) -> dict:
    """Build charts array — one entry per device class that has 24h history."""
    if not options.get(CONF_SHOW_CHART, False):
        return {}

    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.history import get_significant_states
    except ImportError:
        _LOGGER.debug("Recorder not available — chart data skipped")
        return {}

    entities_by_class = _find_chart_entities_by_class(hass)
    if not entities_by_class:
        return {}

    # Single recorder query for all entities across all device classes
    all_entity_ids = [
        e["entity_id"]
        for entities in entities_by_class.values()
        for e in entities
    ]

    now = dt_util.now()
    tz = now.tzinfo
    start = now - timedelta(hours=24)

    try:
        states_map = await get_instance(hass).async_add_executor_job(
            get_significant_states,
            hass, start, now, all_entity_ids,
            None, True, False, False, True,
        )
    except Exception as err:
        _LOGGER.warning("Failed to fetch chart history: %s", err)
        return {}

    charts = []
    for device_class in CHART_SENSOR_ORDER:
        entities = entities_by_class.get(device_class)
        if not entities:
            continue

        labels, series = _build_aligned_series(states_map, entities, start, tz)
        if not series:
            continue

        # Use areaspline for single-series air quality charts; spline for multi-series
        # (overlapping fills on e-ink are unreadable with multiple series)
        preferred = CHART_TYPE_PREFERRED.get(device_class, "spline")
        chart_type = preferred if len(series) == 1 else "spline"

        charts.append({
            "unit": entities[0]["unit"],
            "chart_type": chart_type,
            "labels": labels,
            "series": series,
        })

    return {"charts": charts} if charts else {}
