"""Sensor platform for EURO MOTO / IDM."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CLASS_SUPERBIKE,
    CLASS_SUPERSPORT,
    CLASS_SPORTBIKE,
    CONF_CLASSES,
    TICKETS_URL,
    LIVESTREAM_URL,
    LIVETIMING_URL,
)
from .coordinator import EuroMotoCoordinator, EuroMotoData
from .scraper import TrackEvent

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EuroMotoCoordinator = hass.data[DOMAIN][entry.entry_id]
    enabled_classes: list[str] = entry.options.get(
        CONF_CLASSES, entry.data.get(CONF_CLASSES, [CLASS_SUPERBIKE, CLASS_SUPERSPORT])
    )

    entities: list[SensorEntity] = [
        NextEventSensor(coordinator),
        SeasonCalendarSensor(coordinator),
        RaceWeekendSensor(coordinator),
    ]
    for cls in enabled_classes:
        entities.append(StandingsSensor(coordinator, cls))

    async_add_entities(entities, update_before_add=True)


def _event_status(event: TrackEvent) -> str:
    today = date.today()
    start = event.date_start.date()
    end = event.date_end.date()
    if end < today:
        return "completed"
    if start <= today <= end:
        return "live"
    return "upcoming"


def _next_event(data: EuroMotoData) -> TrackEvent | None:
    today = date.today()
    upcoming = [e for e in data.calendar if e.date_end.date() >= today]
    return upcoming[0] if upcoming else None


class _EuroMotoSensor(CoordinatorEntity[EuroMotoCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: EuroMotoCoordinator, unique_suffix: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"euromoto_{unique_suffix}"


class NextEventSensor(_EuroMotoSensor):
    _attr_icon = "mdi:racing-helmet"
    _attr_name = "Next Event"
    _attr_translation_key = "next_event"

    def __init__(self, coordinator: EuroMotoCoordinator) -> None:
        super().__init__(coordinator, "next_event")

    @property
    def native_value(self) -> str | None:
        event = _next_event(self.coordinator.data)
        return event.name if event else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        event = _next_event(self.coordinator.data)
        if not event:
            return {}
        today = date.today()
        start = event.date_start.date()
        end = event.date_end.date()
        days_until = max(0, (start - today).days)
        is_race_weekend = start <= today <= end

        details = event.details or {}
        length = details.get("laenge")
        if length and isinstance(length, str):
            length = length.replace("km", "").replace(",", ".").strip()
            try:
                length = float(length)
            except ValueError:
                length = None

        def _int_detail(key: str) -> int | None:
            v = details.get(key)
            if v is None:
                return None
            try:
                return int(v)
            except (ValueError, TypeError):
                return None

        return {
            "date_start": event.date_start.date().isoformat(),
            "date_end": event.date_end.date().isoformat(),
            "days_until": days_until,
            "is_race_weekend": is_race_weekend,
            "country": event.country,
            "track_url": event.track_url,
            "track_length_km": length,
            "track_corners_right": _int_detail("rechtskurven"),
            "track_corners_left": _int_detail("linkskurven"),
            "track_longest_straight_m": _int_detail("laengste_gerade"),
            "track_address": details.get("adresse"),
            "tickets_url": TICKETS_URL,
            "livestream_url": LIVESTREAM_URL,
            "livetiming_url": LIVETIMING_URL,
        }


class SeasonCalendarSensor(_EuroMotoSensor):
    _attr_icon = "mdi:calendar-month"
    _attr_name = "Season Calendar"
    _attr_translation_key = "season_calendar"
    _attr_native_unit_of_measurement = "events"

    def __init__(self, coordinator: EuroMotoCoordinator) -> None:
        super().__init__(coordinator, "season_calendar")

    @property
    def native_value(self) -> int:
        today = date.today()
        return sum(
            1 for e in self.coordinator.data.calendar if e.date_end.date() >= today
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        today = date.today()
        total = len(data.calendar)
        completed = sum(1 for e in data.calendar if e.date_end.date() < today)
        remaining = total - completed

        events_list = [
            {
                "round": i + 1,
                "name": e.name,
                "date_start": e.date_start.date().isoformat(),
                "date_end": e.date_end.date().isoformat(),
                "country": e.country,
                "status": _event_status(e),
            }
            for i, e in enumerate(data.calendar)
        ]

        return {
            "season": data.season,
            "total_events": total,
            "completed_events": completed,
            "remaining_events": remaining,
            "events": events_list,
        }


class StandingsSensor(_EuroMotoSensor):
    _attr_icon = "mdi:trophy"

    _SUFFIX_MAP = {
        CLASS_SUPERBIKE: "sbk_standings",
        CLASS_SUPERSPORT: "ssp_standings",
        CLASS_SPORTBIKE: "spb_standings",
    }
    _NAME_MAP = {
        CLASS_SUPERBIKE: "Superbike Standings",
        CLASS_SUPERSPORT: "Supersport Standings",
        CLASS_SPORTBIKE: "Sportbike Standings",
    }

    def __init__(self, coordinator: EuroMotoCoordinator, cls: str) -> None:
        super().__init__(coordinator, self._SUFFIX_MAP.get(cls, f"{cls.lower()}_standings"))
        self._cls = cls
        self._attr_name = self._NAME_MAP.get(cls, f"{cls} Standings")

    @property
    def _standings(self) -> list[dict[str, Any]]:
        return self.coordinator.data.standings.get(self._cls, [])

    @property
    def native_value(self) -> str | None:
        standings = self._standings
        if not standings:
            return None
        leader = standings[0]
        return leader.get("name")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "class": self._cls,
            "season": self.coordinator.data.season,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "standings": self._standings,
        }


class RaceWeekendSensor(_EuroMotoSensor):
    _attr_icon = "mdi:flag-checkered"
    _attr_name = "Race Weekend"
    _attr_translation_key = "race_weekend"

    def __init__(self, coordinator: EuroMotoCoordinator) -> None:
        super().__init__(coordinator, "race_weekend")

    @property
    def native_value(self) -> str:
        today = date.today()
        for e in self.coordinator.data.calendar:
            if e.date_start.date() <= today <= e.date_end.date():
                return "active"
        return "inactive"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        today = date.today()
        active_event: TrackEvent | None = None
        for e in self.coordinator.data.calendar:
            if e.date_start.date() <= today <= e.date_end.date():
                active_event = e
                break

        if not active_event:
            return {}

        day_names = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
                     4: "Friday", 5: "Saturday", 6: "Sunday"}
        return {
            "event_name": active_event.name,
            "day": day_names.get(today.weekday(), ""),
            "livetiming_url": LIVETIMING_URL,
            "livestream_url": LIVESTREAM_URL,
        }
