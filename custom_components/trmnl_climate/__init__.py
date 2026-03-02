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
    CHART_DAILY_MINMAX,
    CHART_TYPE_24H,
    CHART_TYPE_7DAY,
    CHART_TYPE_DISABLED,
    CLIMATE_DEVICE_CLASSES,
    CONF_CHART_AREA,
    CONF_CHART_DAILY_MODE,
    CONF_CHART_RESOLUTION,
    CONF_CHART_SENSOR,
    CONF_CHART_TYPE,
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

        chart_data = await _build_chart_data(hass, entry.options)

        merge_vars: dict = {
            "areas": areas_data,
            "last_updated": dt_util.now().strftime("%H:%M"),
        }
        if chart_data:
            merge_vars["chart"] = chart_data

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

def _find_chart_entity(
    hass: HomeAssistant,
    device_class: str,
    target_area_id: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Return (entity_id, area_name, unit) for the first matching sensor."""
    area_reg = ar.async_get(hass)
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

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

        if target_area_id and area_id != target_area_id:
            continue
        if area_id is None:
            continue

        area = area_reg.async_get_area(area_id)
        return (
            entity.entity_id,
            area.name if area else "",
            state.attributes.get("unit_of_measurement", ""),
        )

    return None, None, None


async def _build_chart_data(hass: HomeAssistant, options: dict) -> dict | None:
    """Build chart payload from recorder statistics based on user options."""
    chart_type = options.get(CONF_CHART_TYPE, CHART_TYPE_DISABLED)
    if chart_type == CHART_TYPE_DISABLED:
        return None

    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import statistics_during_period
    except ImportError:
        _LOGGER.debug("Recorder not available — chart data skipped")
        return None

    device_class = options.get(CONF_CHART_SENSOR, "temperature")
    target_area_id = options.get(CONF_CHART_AREA) or None

    entity_id, area_name, unit = _find_chart_entity(hass, device_class, target_area_id)
    if not entity_id:
        _LOGGER.debug(
            "No chart entity found for device_class=%s area=%s",
            device_class, target_area_id,
        )
        return None

    label = f"{area_name} {device_class.replace('_', ' ').title()}"
    now = dt_util.now()

    try:
        if chart_type == CHART_TYPE_24H:
            resolution_h = int(options.get(CONF_CHART_RESOLUTION, "1"))
            stats = await get_instance(hass).async_add_executor_job(
                statistics_during_period,
                hass,
                now - timedelta(hours=24),
                None,
                {entity_id},
                "hour",
                None,
                {"mean"},
            )
            rows = [r for r in stats.get(entity_id, []) if r.mean is not None]
            sampled = rows[::resolution_h]
            if not sampled:
                return None

            points = [
                {
                    "t": r.start.astimezone(now.tzinfo).strftime("%H:%M"),
                    "v": round(r.mean, 1),
                }
                for r in sampled
            ]
            return {"type": "24h", "label": label, "unit": unit, "points": points}

        if chart_type == CHART_TYPE_7DAY:
            daily_mode = options.get(CONF_CHART_DAILY_MODE, CHART_DAILY_MINMAX)
            stat_types = (
                {"mean", "min", "max"} if daily_mode == CHART_DAILY_MINMAX else {"mean"}
            )
            stats = await get_instance(hass).async_add_executor_job(
                statistics_during_period,
                hass,
                now - timedelta(days=7),
                None,
                {entity_id},
                "day",
                None,
                stat_types,
            )
            rows = stats.get(entity_id, [])
            if not rows:
                return None

            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            days = []
            for r in rows:
                entry: dict = {
                    "t": day_names[r.start.astimezone(now.tzinfo).weekday()],
                    "avg": round(r.mean, 1) if r.mean is not None else None,
                }
                if daily_mode == CHART_DAILY_MINMAX:
                    entry["min"] = round(r.min, 1) if r.min is not None else None
                    entry["max"] = round(r.max, 1) if r.max is not None else None
                days.append(entry)

            return {
                "type": "7day",
                "mode": daily_mode,
                "label": label,
                "unit": unit,
                "days": days,
            }

    except Exception as err:
        _LOGGER.warning("Failed to build chart data: %s", err)

    return None
