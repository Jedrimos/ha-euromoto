"""Binary sensor platform for EURO MOTO / IDM."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DAY_MAP,
    DOMAIN,
    LIVETIMING_URL,
    LIVESTREAM_URL,
    NATION_FLAGS,
    WEEKDAY_DAY,
)
from .coordinator import EuroMotoCoordinator
from .scraper import TrackEvent

_DEVICE_INFO = DeviceInfo(identifiers={(DOMAIN, "euromoto")}, name="EuroMoto")


def _active_event(calendar: list[TrackEvent]) -> TrackEvent | None:
    today = date.today()
    for ev in calendar:
        if ev.date_start.date() <= today <= ev.date_end.date():
            return ev
    return None


def _session_state(
    schedule: list[dict], event_start: date
) -> tuple[bool, bool, dict | None]:
    """Return (any_session_active, race_active, session_dict) for the current moment."""
    now = datetime.now()
    day_key = WEEKDAY_DAY.get(now.weekday())
    if not day_key:
        return False, False, None

    delta = (DAY_MAP[day_key] - event_start.weekday()) % 7
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
    _attr_device_info = _DEVICE_INFO

    def __init__(self, coordinator: EuroMotoCoordinator, unique_suffix: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"euromoto_{unique_suffix}"
        self._cached_ev: TrackEvent | None = None
        self._cached_session: tuple[bool, bool, dict | None] = (False, False, None)

    def _handle_coordinator_update(self) -> None:
        """Compute shared state once per coordinator push, before HA reads properties."""
        self._cached_ev = _active_event(self.coordinator.data.calendar)
        if self._cached_ev:
            self._cached_session = _session_state(
                self.coordinator.data.schedule, self._cached_ev.date_start.date()
            )
        else:
            self._cached_session = (False, False, None)
        super()._handle_coordinator_update()


class RaceWeekendBinarySensor(_EuroMotoBinarySensor):
    _attr_name = "Race Weekend"
    _attr_icon = "mdi:racing-helmet"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: EuroMotoCoordinator) -> None:
        super().__init__(coordinator, "bs_race_weekend")
        self.entity_id = "binary_sensor.euromoto_race_weekend"

    @property
    def is_on(self) -> bool:
        return self._cached_ev is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ev = self._cached_ev
        if not ev:
            return {}
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
        self.entity_id = "binary_sensor.euromoto_session_active"

    @property
    def is_on(self) -> bool:
        active, _, _ = self._cached_session
        return active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        _, _, s = self._cached_session
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
        self.entity_id = "binary_sensor.euromoto_race_active"

    @property
    def is_on(self) -> bool:
        _, race_active, _ = self._cached_session
        return race_active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        _, is_race, s = self._cached_session
        if not s or not is_race:
            return {}
        return {
            "session": s.get("session"),
            "class": s.get("cls"),
            "time_start": s.get("time_start"),
            "time_end": s.get("time_end"),
        }
