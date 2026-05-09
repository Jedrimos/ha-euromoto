"""Binary sensor platform for EURO MOTO / IDM."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LIVETIMING_URL, LIVESTREAM_URL
from .coordinator import EuroMotoCoordinator
from .scraper import TrackEvent

_DAY_WEEKDAY = {"friday": 4, "saturday": 5, "sunday": 6}


def _active_event(calendar: list[TrackEvent]) -> TrackEvent | None:
    today = date.today()
    for ev in calendar:
        if ev.date_start.date() <= today <= ev.date_end.date():
            return ev
    return None


def _session_state(
    schedule: list[dict], event_start: date
) -> tuple[bool, bool, dict | None]:
    """Return (any_session_active, race_active, session_dict)."""
    now = datetime.now()
    current_weekday = now.weekday()
    day_key = {4: "friday", 5: "saturday", 6: "sunday"}.get(current_weekday)
    if not day_key:
        return False, False, None

    target_weekday = _DAY_WEEKDAY[day_key]
    delta = (target_weekday - event_start.weekday()) % 7
    session_date = event_start + timedelta(days=delta)

    for s in schedule:
        if s.get("day") != day_key:
            continue
        try:
            sh, sm = map(int, s["time_start"].split(":"))
            start_dt = datetime.combine(session_date, time(sh, sm))
            if s.get("time_end"):
                eh, em = map(int, s["time_end"].split(":"))
                end_dt = datetime.combine(session_date, time(eh, em))
            else:
                end_dt = start_dt + timedelta(minutes=30)
            if start_dt <= now <= end_dt:
                return True, s.get("race", False), s
        except (ValueError, AttributeError, KeyError):
            continue
    return False, False, None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EuroMotoCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        RaceWeekendBinarySensor(coordinator),
        SessionActiveBinarySensor(coordinator),
        RaceActiveBinarySensor(coordinator),
    ], update_before_add=True)


class _EuroMotoBinarySensor(
    CoordinatorEntity[EuroMotoCoordinator], BinarySensorEntity
):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: EuroMotoCoordinator, unique_suffix: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"euromoto_{unique_suffix}"

    def _active_ev(self) -> TrackEvent | None:
        return _active_event(self.coordinator.data.calendar)

    def _session_info(self) -> tuple[bool, bool, dict | None]:
        ev = self._active_ev()
        if not ev:
            return False, False, None
        return _session_state(self.coordinator.data.schedule, ev.date_start.date())


class RaceWeekendBinarySensor(_EuroMotoBinarySensor):
    _attr_name = "Race Weekend"
    _attr_icon = "mdi:racing-helmet"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: EuroMotoCoordinator) -> None:
        super().__init__(coordinator, "bs_race_weekend")

    @property
    def is_on(self) -> bool:
        return self._active_ev() is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ev = self._active_ev()
        if not ev:
            return {}
        from .const import NATION_FLAGS
        return {
            "event_name": ev.name,
            "country": ev.country,
            "flag": NATION_FLAGS.get(ev.country or "", ""),
            "livetiming_url": LIVETIMING_URL,
            "livestream_url": LIVESTREAM_URL,
        }


class SessionActiveBinarySensor(_EuroMotoBinarySensor):
    _attr_name = "Session Active"
    _attr_icon = "mdi:timer-play"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: EuroMotoCoordinator) -> None:
        super().__init__(coordinator, "bs_session_active")

    @property
    def is_on(self) -> bool:
        active, _, _ = self._session_info()
        return active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        _, _, s = self._session_info()
        if not s:
            return {}
        return {
            "session": s.get("session"),
            "class": s.get("cls"),
            "time_start": s.get("time_start"),
            "time_end": s.get("time_end"),
            "is_race": s.get("race", False),
        }


class RaceActiveBinarySensor(_EuroMotoBinarySensor):
    _attr_name = "Race Active"
    _attr_icon = "mdi:flag-checkered"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: EuroMotoCoordinator) -> None:
        super().__init__(coordinator, "bs_race_active")

    @property
    def is_on(self) -> bool:
        _, race_active, _ = self._session_info()
        return race_active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        _, is_race, s = self._session_info()
        if not s or not is_race:
            return {}
        return {
            "session": s.get("session"),
            "class": s.get("cls"),
            "time_start": s.get("time_start"),
            "time_end": s.get("time_end"),
        }
