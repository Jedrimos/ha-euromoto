"""EURO MOTO / IDM Home Assistant integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_CLASSES, CONF_FAVORITE_RIDERS, CLASS_SUPERBIKE, CLASS_SUPERSPORT
from .coordinator import EuroMotoCoordinator

PLATFORMS = [Platform.SENSOR, Platform.CALENDAR, Platform.WEATHER, Platform.BINARY_SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    enabled_classes: list[str] = entry.options.get(
        CONF_CLASSES, entry.data.get(CONF_CLASSES, [CLASS_SUPERBIKE, CLASS_SUPERSPORT])
    )
    favorite_riders: list[int] = entry.options.get(
        CONF_FAVORITE_RIDERS, entry.data.get(CONF_FAVORITE_RIDERS, [])
    )
    coordinator = EuroMotoCoordinator(hass, enabled_classes, favorite_riders)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: EuroMotoCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
