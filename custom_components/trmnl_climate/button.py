from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([TrmnlClimatePushButton(entry)])


class TrmnlClimatePushButton(ButtonEntity):
    _attr_name = "Push to TRMNL"
    _attr_icon = "mdi:cloud-upload"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_push_button"

    async def async_press(self) -> None:
        push = self.hass.data[DOMAIN][self._entry.entry_id]["push"]
        await push()
