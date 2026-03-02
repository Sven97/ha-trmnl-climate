from __future__ import annotations

import logging
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
    CHART_SENSOR_LABELS,
    CHART_SENSOR_PRIORITY,
    CLIMATE_DEVICE_CLASSES,
    CONF_SHOW_1DAY,
    CONF_SHOW_7DAY,
    CONF_WEBHOOK_URL,
    DOMAIN,
    PUSH_INTERVAL_MINUTES,
    SENSOR_DISPLAY_ORDER,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["button"]


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

def _find_all_chart_entities(
    hass: HomeAssistant,
    device_class: str,
) -> list[dict]:
    """Return list of {entity_id, area_name, unit} for all matching sensors."""
    area_reg = ar.async_get(hass)
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

    seen_areas: set[str] = set()
    results: list[dict] = []

    for entity in entity_reg.entities.values():
        if not entity.entity_id.startswith("sensor."):
            continue
        if entity.disabled_by is not None:
            continue

        state = hass.states.get(entity.entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            continue
        if state.attributes.get("device_class") != device_class:
            continue

        area_id = entity.area_id
        if area_id is None and entity.device_id:
            device = device_reg.async_get(entity.device_id)
            if device:
                area_id = device.area_id

        if area_id is None or area_id in seen_areas:
            continue

        area = area_reg.async_get_area(area_id)
        if area is None:
            continue

        seen_areas.add(area_id)
        results.append({
            "entity_id": entity.entity_id,
            "area_name": area.name,
            "unit": state.attributes.get("unit_of_measurement", ""),
        })

    return sorted(results, key=lambda x: x["area_name"])


def _pick_device_class(hass: HomeAssistant) -> str | None:
    """Return the highest-priority device class that has at least one sensor."""
    entity_reg = er.async_get(hass)
    for dc in CHART_SENSOR_PRIORITY:
        for entity in entity_reg.entities.values():
            if not entity.entity_id.startswith("sensor."):
                continue
            state = hass.states.get(entity.entity_id)
            if state and state.attributes.get("device_class") == dc:
                return dc
    return None


async def _build_chart_data(hass: HomeAssistant, options: dict) -> dict:
    """Build chart_1d and/or chart_7d payloads based on user options."""
    show_1d = options.get(CONF_SHOW_1DAY, False)
    show_7d = options.get(CONF_SHOW_7DAY, False)

    if not show_1d and not show_7d:
        return {}

    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import statistics_during_period
    except ImportError:
        _LOGGER.debug("Recorder not available — chart data skipped")
        return {}

    device_class = _pick_device_class(hass)
    if not device_class:
        return {}

    entities = _find_all_chart_entities(hass, device_class)
    if not entities:
        return {}

    entity_ids = {e["entity_id"] for e in entities}
    label = CHART_SENSOR_LABELS.get(device_class, device_class.replace("_", " ").title())
    unit = entities[0]["unit"]
    now = dt_util.now()
    result: dict = {}

    try:
        if show_1d:
            stats = await get_instance(hass).async_add_executor_job(
                statistics_during_period,
                hass,
                now - timedelta(hours=24),
                None,
                entity_ids,
                "hour",
                None,
                {"mean"},
            )
            series = []
            for e in entities:
                rows = [r for r in stats.get(e["entity_id"], []) if r.mean is not None]
                if not rows:
                    continue
                series.append({
                    "label": e["area_name"],
                    "points": [
                        {
                            "t": r.start.astimezone(now.tzinfo).strftime("%H:%M"),
                            "v": round(r.mean, 1),
                        }
                        for r in rows
                    ],
                })
            if series:
                result["chart_1d"] = {"label": label, "unit": unit, "series": series}

        if show_7d:
            stats = await get_instance(hass).async_add_executor_job(
                statistics_during_period,
                hass,
                now - timedelta(days=7),
                None,
                entity_ids,
                "day",
                None,
                {"mean"},
            )
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            series = []
            for e in entities:
                rows = [r for r in stats.get(e["entity_id"], []) if r.mean is not None]
                if not rows:
                    continue
                series.append({
                    "label": e["area_name"],
                    "points": [
                        {
                            "t": day_names[r.start.astimezone(now.tzinfo).weekday()],
                            "v": round(r.mean, 1),
                        }
                        for r in rows
                    ],
                })
            if series:
                result["chart_7d"] = {"label": label, "unit": unit, "series": series}

    except Exception as err:
        _LOGGER.warning("Failed to build chart data: %s", err)

    return result
