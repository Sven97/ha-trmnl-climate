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

from .const import (
    CLIMATE_DEVICE_CLASSES,
    CONF_WEBHOOK_URL,
    DOMAIN,
    PUSH_INTERVAL_MINUTES,
    SENSOR_DISPLAY_ORDER,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    webhook_url = entry.data[CONF_WEBHOOK_URL]

    async def push_climate_data(_now=None) -> None:
        areas_data = _build_areas_data(hass)
        if not areas_data:
            _LOGGER.debug("No climate sensors found in any area — skipping push")
            return

        payload = {"merge_variables": {"areas": areas_data}}
        session = async_get_clientsession(hass)
        try:
            async with session.post(
                webhook_url,
                json=payload,
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

    # Push once immediately, then on the interval
    await push_climate_data()
    entry.async_on_unload(
        async_track_time_interval(
            hass,
            push_climate_data,
            timedelta(minutes=PUSH_INTERVAL_MINUTES),
        )
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return True


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

        # Entity-level area takes priority, then fall back to the device's area
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
