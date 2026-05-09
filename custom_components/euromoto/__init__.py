"""EURO MOTO / IDM Home Assistant integration."""
from __future__ import annotations

import logging
import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, CONF_CLASSES, CONF_FAVORITE_RIDERS, CONF_LIVE_TENANT_ID, CLASS_SUPERBIKE, CLASS_SUPERSPORT
from .coordinator import EuroMotoCoordinator
from .dashboard import async_register_dashboard, async_remove_dashboard

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.CALENDAR, Platform.WEATHER, Platform.BINARY_SENSOR, Platform.SWITCH]

# unique_id → target entity_id for all entities with fixed unique_ids
_UID_TO_ENTITY_ID: dict[str, str] = {
    "euromoto_next_event": "sensor.euromoto_next_event",
    "euromoto_season_calendar": "sensor.euromoto_season_calendar",
    "euromoto_race_weekend": "sensor.euromoto_race_weekend",
    "euromoto_weekend_schedule": "sensor.euromoto_weekend_schedule",
    "euromoto_session_countdown": "sensor.euromoto_session_countdown",
    "euromoto_sbk_standings": "sensor.euromoto_sbk_standings",
    "euromoto_ssp_standings": "sensor.euromoto_ssp_standings",
    "euromoto_spb_standings": "sensor.euromoto_spb_standings",
    "euromoto_sbk_riders": "sensor.euromoto_sbk_riders",
    "euromoto_ssp_riders": "sensor.euromoto_ssp_riders",
    "euromoto_spb_riders": "sensor.euromoto_spb_riders",
    "euromoto_sbk_grid": "sensor.euromoto_sbk_grid",
    "euromoto_ssp_grid": "sensor.euromoto_ssp_grid",
    "euromoto_spb_grid": "sensor.euromoto_spb_grid",
    "euromoto_race_calendar": "calendar.euromoto_race_calendar",
    "euromoto_track_weather": "weather.euromoto_track_weather",
    "euromoto_bs_race_weekend": "binary_sensor.euromoto_race_weekend",
    "euromoto_bs_session_active": "binary_sensor.euromoto_session_active",
    "euromoto_bs_race_active": "binary_sensor.euromoto_race_active",
    **{f"euromoto_sbk_p{i}": f"sensor.euromoto_sbk_p{i}" for i in range(1, 11)},
    **{f"euromoto_ssp_p{i}": f"sensor.euromoto_ssp_p{i}" for i in range(1, 11)},
    **{f"euromoto_spb_p{i}": f"sensor.euromoto_spb_p{i}" for i in range(1, 11)},
}

_RE_FAVORITE = re.compile(r"^euromoto_favorite_rider_(\d+)$")
_RE_NO_SPOILER = re.compile(r"^euromoto_no_spoiler_")


def _migrate_entity_ids(hass: HomeAssistant, entry_id: str) -> None:
    """Rename legacy entity_ids to the canonical euromoto_ prefix (runs on every load, idempotent)."""
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry_id):
        uid = reg_entry.unique_id
        old_id = reg_entry.entity_id

        target = _UID_TO_ENTITY_ID.get(uid)
        if not target:
            m = _RE_FAVORITE.match(uid)
            if m:
                target = f"sensor.euromoto_rider_{m.group(1)}"
        if not target and _RE_NO_SPOILER.match(uid):
            target = "switch.euromoto_no_spoiler_modus"

        if target and old_id != target:
            if registry.async_get(target) is None:
                _LOGGER.info("EuroMoto: migrating entity %s → %s", old_id, target)
                registry.async_update_entity(old_id, new_entity_id=target)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _migrate_entity_ids(hass, entry.entry_id)

    enabled_classes: list[str] = entry.options.get(
        CONF_CLASSES, entry.data.get(CONF_CLASSES, [CLASS_SUPERBIKE, CLASS_SUPERSPORT])
    )
    favorite_riders: list[int] = entry.options.get(
        CONF_FAVORITE_RIDERS, entry.data.get(CONF_FAVORITE_RIDERS, [])
    )
    live_tenant_id: str = entry.options.get(
        CONF_LIVE_TENANT_ID, entry.data.get(CONF_LIVE_TENANT_ID, "c1")
    )
    coordinator = EuroMotoCoordinator(hass, enabled_classes, favorite_riders, live_tenant_id)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await async_register_dashboard(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: EuroMotoCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up Lovelace dashboard when the integration is fully removed."""
    await async_remove_dashboard(hass)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
