"""Switch platform for EURO MOTO / IDM – No-Spoiler mode."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([NoSpoilerSwitch(entry.entry_id)])


class NoSpoilerSwitch(SwitchEntity, RestoreEntity):
    """Hide race results until user explicitly turns this off.

    Combine with conditional cards in Lovelace to suppress standings/grid.
    """

    _attr_has_entity_name = True
    _attr_name = "No-Spoiler Modus"
    _attr_icon = "mdi:eye-off"
    _attr_should_poll = False

    def __init__(self, entry_id: str) -> None:
        self._attr_unique_id = f"euromoto_no_spoiler_{entry_id}"
        self._is_on = False

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        if last is not None:
            self._is_on = last.state == "on"

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "description": (
                "Wenn AN: Ergebnisse in Lovelace per conditional card ausblenden. "
                "Erfordert conditional-Karten mit Bedingung state=off."
            )
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._is_on = False
        self.async_write_ha_state()
