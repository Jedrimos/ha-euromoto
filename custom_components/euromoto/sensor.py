"""Sensor platform for EURO MOTO / IDM."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_CLASSES,
    CONF_FAVORITE_RIDERS,
    CLASS_SUPERBIKE,
    CLASS_SUPERSPORT,
    CLASS_SPORTBIKE,
    DAY_MAP,
    DOMAIN,
    DRIVER_SENSOR_COUNT,
    LIVETIMING_URL,
    LIVESTREAM_URL,
    NATION_FLAGS,
    TICKETS_URL,
)
from .coordinator import EuroMotoCoordinator, EuroMotoData
from .scraper import TrackEvent

_LOGGER = logging.getLogger(__name__)

_CLASS_SHORT = {
    CLASS_SUPERBIKE: "sbk",
    CLASS_SUPERSPORT: "ssp",
    CLASS_SPORTBIKE: "spb",
}


def _flag(nation: str | None) -> str:
    if not nation:
        return ""
    return NATION_FLAGS.get(nation.upper(), "")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EuroMotoCoordinator = hass.data[DOMAIN][entry.entry_id]
    enabled_classes: list[str] = entry.options.get(
        CONF_CLASSES, entry.data.get(CONF_CLASSES, [CLASS_SUPERBIKE, CLASS_SUPERSPORT])
    )
    favorite_riders: list[int] = entry.options.get(
        CONF_FAVORITE_RIDERS, entry.data.get(CONF_FAVORITE_RIDERS, [])
    )

    entities: list[SensorEntity] = [
        NextEventSensor(coordinator),
        SeasonCalendarSensor(coordinator),
        RaceWeekendSensor(coordinator),
        WeekendScheduleSensor(coordinator),
        SessionCountdownSensor(coordinator),
    ]
    for cls in enabled_classes:
        entities.append(StandingsSensor(coordinator, cls))
        entities.append(StartingGridSensor(coordinator, cls))
        entities.append(AllRidersSensor(coordinator, cls))
        for pos in range(1, DRIVER_SENSOR_COUNT + 1):
            entities.append(DriverPositionSensor(coordinator, cls, pos))

    for number in favorite_riders:
        entities.append(FavoriteRiderSensor(coordinator, number, enabled_classes))

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


# ---------------------------------------------------------------------------
# Next Event
# ---------------------------------------------------------------------------

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

        def _num(key: str) -> int | float | None:
            v = details.get(key)
            if v is None:
                return None
            try:
                return float(str(v).replace(",", ".").split()[0])
            except (ValueError, TypeError):
                return None

        country = event.country
        return {
            "date_start": event.date_start.date().isoformat(),
            "date_end": event.date_end.date().isoformat(),
            "days_until": days_until,
            "is_race_weekend": is_race_weekend,
            "country": country,
            "country_flag": _flag(country),
            "track_url": event.track_url,
            "track_length_km": _num("laenge"),
            "track_corners_right": _num("rechtskurven"),
            "track_corners_left": _num("linkskurven"),
            "track_longest_straight_m": _num("laengste_gerade"),
            "track_address": details.get("adresse"),
            "tickets_url": TICKETS_URL,
            "livestream_url": LIVESTREAM_URL,
            "livetiming_url": LIVETIMING_URL,
        }


# ---------------------------------------------------------------------------
# Season Calendar
# ---------------------------------------------------------------------------

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
        return sum(1 for e in self.coordinator.data.calendar if e.date_end.date() >= today)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        today = date.today()
        total = len(data.calendar)
        completed = sum(1 for e in data.calendar if e.date_end.date() < today)

        return {
            "season": data.season,
            "total_events": total,
            "completed_events": completed,
            "remaining_events": total - completed,
            "events": [
                {
                    "round": i + 1,
                    "name": e.name,
                    "date_start": e.date_start.date().isoformat(),
                    "date_end": e.date_end.date().isoformat(),
                    "country": e.country,
                    "country_flag": _flag(e.country),
                    "status": _event_status(e),
                }
                for i, e in enumerate(data.calendar)
            ],
        }


# ---------------------------------------------------------------------------
# Championship Standings (summary – leader as state)
# ---------------------------------------------------------------------------

class StandingsSensor(_EuroMotoSensor):
    _attr_icon = "mdi:trophy"

    _SUFFIX_MAP = {CLASS_SUPERBIKE: "sbk_standings", CLASS_SUPERSPORT: "ssp_standings", CLASS_SPORTBIKE: "spb_standings"}
    _NAME_MAP = {CLASS_SUPERBIKE: "Superbike Standings", CLASS_SUPERSPORT: "Supersport Standings", CLASS_SPORTBIKE: "Sportbike Standings"}

    def __init__(self, coordinator: EuroMotoCoordinator, cls: str) -> None:
        super().__init__(coordinator, self._SUFFIX_MAP.get(cls, f"{cls.lower()}_standings"))
        self._cls = cls
        self._attr_name = self._NAME_MAP.get(cls, f"{cls} Standings")

    @property
    def _standings(self) -> list[dict[str, Any]]:
        return self.coordinator.data.standings.get(self._cls, [])

    @property
    def native_value(self) -> str | None:
        s = self._standings
        return s[0].get("name") if s else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "class": self._cls,
            "season": self.coordinator.data.season,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "standings": self._standings,
        }


# ---------------------------------------------------------------------------
# All Riders + Bikes sensor
# ---------------------------------------------------------------------------

class AllRidersSensor(_EuroMotoSensor):
    _attr_icon = "mdi:account-group"

    _SUFFIX_MAP = {CLASS_SUPERBIKE: "sbk_riders", CLASS_SUPERSPORT: "ssp_riders", CLASS_SPORTBIKE: "spb_riders"}
    _NAME_MAP = {CLASS_SUPERBIKE: "Superbike Riders", CLASS_SUPERSPORT: "Supersport Riders", CLASS_SPORTBIKE: "Sportbike Riders"}

    def __init__(self, coordinator: EuroMotoCoordinator, cls: str) -> None:
        super().__init__(coordinator, self._SUFFIX_MAP.get(cls, f"{cls.lower()}_riders"))
        self._cls = cls
        self._attr_name = self._NAME_MAP.get(cls, f"{cls} Riders")

    @property
    def _standings(self) -> list[dict[str, Any]]:
        return self.coordinator.data.standings.get(self._cls, [])

    @property
    def native_value(self) -> int:
        return len(self._standings)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        riders = [
            {
                "pos": r.get("pos"),
                "number": r.get("number"),
                "name": r.get("name"),
                "nation": r.get("nation"),
                "flag": _flag(r.get("nation")),
                "bike": r.get("bike"),
                "points": r.get("points"),
            }
            for r in self._standings
        ]
        # Group by bike brand for quick overview
        bikes: dict[str, list[str]] = {}
        for r in self._standings:
            bike = r.get("bike") or "Unbekannt"
            bikes.setdefault(bike, []).append(r.get("name") or "")
        return {
            "class": self._cls,
            "rider_count": len(riders),
            "riders": riders,
            "bikes_overview": {k: len(v) for k, v in sorted(bikes.items())},
        }


# ---------------------------------------------------------------------------
# Driver Position Sensors  P1–P10
# ---------------------------------------------------------------------------

class DriverPositionSensor(_EuroMotoSensor):
    _attr_icon = "mdi:account-star"

    def __init__(self, coordinator: EuroMotoCoordinator, cls: str, pos: int) -> None:
        short = _CLASS_SHORT.get(cls, cls.lower())
        super().__init__(coordinator, f"{short}_p{pos}")
        self._cls = cls
        self._pos = pos
        self._attr_name = f"{cls} P{pos}"

    def _entry(self) -> dict[str, Any] | None:
        for r in self.coordinator.data.standings.get(self._cls, []):
            if r.get("pos") == self._pos:
                return r
        return None

    @property
    def native_value(self) -> str:
        e = self._entry()
        return e.get("name") if e else "–"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        e = self._entry()
        if not e:
            return {"position": self._pos, "class": self._cls}
        nation = e.get("nation")
        return {
            "position": e.get("pos"),
            "number": e.get("number"),
            "nation": nation,
            "flag": _flag(nation),
            "bike": e.get("bike"),
            "points": e.get("points"),
            "class": self._cls,
        }


# ---------------------------------------------------------------------------
# Starting Grid Sensor
# ---------------------------------------------------------------------------

class StartingGridSensor(_EuroMotoSensor):
    _attr_icon = "mdi:flag-checkered"

    _SUFFIX_MAP = {CLASS_SUPERBIKE: "sbk_grid", CLASS_SUPERSPORT: "ssp_grid", CLASS_SPORTBIKE: "spb_grid"}
    _NAME_MAP = {CLASS_SUPERBIKE: "Superbike Starting Grid", CLASS_SUPERSPORT: "Supersport Starting Grid", CLASS_SPORTBIKE: "Sportbike Starting Grid"}

    def __init__(self, coordinator: EuroMotoCoordinator, cls: str) -> None:
        super().__init__(coordinator, self._SUFFIX_MAP.get(cls, f"{cls.lower()}_grid"))
        self._cls = cls
        self._attr_name = self._NAME_MAP.get(cls, f"{cls} Starting Grid")

    @property
    def _grid(self) -> list[dict[str, Any]]:
        return self.coordinator.data.grid.get(self._cls, [])

    @property
    def native_value(self) -> str:
        g = self._grid
        return g[0].get("name") if g else "–"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"class": self._cls, "season": self.coordinator.data.season, "grid": self._grid}


# ---------------------------------------------------------------------------
# Favorite Rider (one sensor per configured rider number)
# ---------------------------------------------------------------------------

class FavoriteRiderSensor(_EuroMotoSensor):
    _attr_icon = "mdi:account-heart"

    def __init__(self, coordinator: EuroMotoCoordinator, rider_number: int, enabled_classes: list[str]) -> None:
        super().__init__(coordinator, f"favorite_rider_{rider_number}")
        self._rider_number = rider_number
        self._enabled_classes = enabled_classes
        self._attr_name = f"Lieblingsfahrer #{rider_number}"

    def _find(self) -> tuple[str, dict[str, Any]] | None:
        for cls in self._enabled_classes:
            for entry in self.coordinator.data.standings.get(cls, []):
                if entry.get("number") == self._rider_number:
                    return cls, entry
        return None

    @property
    def available(self) -> bool:
        return self._find() is not None

    @property
    def native_value(self) -> str | None:
        found = self._find()
        return found[1].get("name") if found else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        found = self._find()
        if not found:
            return {"number": self._rider_number}
        cls, e = found
        nation = e.get("nation")
        return {
            "number": e.get("number"),
            "position": e.get("pos"),
            "nation": nation,
            "flag": _flag(nation),
            "bike": e.get("bike"),
            "points": e.get("points"),
            "class": cls,
        }


# ---------------------------------------------------------------------------
# Race Weekend
# ---------------------------------------------------------------------------

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
            "country_flag": _flag(active_event.country),
            "day": day_names.get(today.weekday(), ""),
            "livetiming_url": LIVETIMING_URL,
            "livestream_url": LIVESTREAM_URL,
        }


# ---------------------------------------------------------------------------
# Schedule helpers
# ---------------------------------------------------------------------------

_DAY_DE = {"friday": "Freitag", "saturday": "Samstag", "sunday": "Sonntag"}
_SESSION_ICON = {
    "FP1": "🔵", "FP2": "🔵", "FP3": "🔵",
    "Training": "🔵",
    "PreP": "🟡",
    "Qualifying": "🟡", "Superpole": "🟡",
    "Warm-up": "🟠",
    "Race 1": "🏁", "Race 2": "🏁",
}


def _event_start(calendar: list) -> date | None:
    """Return the start date of the next or current event."""
    today = date.today()
    for ev in calendar:
        if ev.date_end.date() >= today:
            return ev.date_start.date()
    return None


def _sessions_for_day(schedule: list[dict], day: str) -> list[dict]:
    return [s for s in schedule if s.get("day") == day]


def _next_session(schedule: list[dict], event_date_start: date) -> dict | None:
    """Return the first session that hasn't finished yet."""
    now = datetime.now()
    for day_key, weekday_offset in DAY_MAP.items():
        session_date = event_date_start + timedelta(
            days=(weekday_offset - event_date_start.weekday()) % 7
        )
        for s in _sessions_for_day(schedule, day_key):
            try:
                h, m = (
                    map(int, s["time_end"].split(":"))
                    if s.get("time_end")
                    else map(int, s["time_start"].split(":"))
                )
                session_end = datetime.combine(session_date, time(h, m))
                if session_end > now:
                    return {**s, "date": session_date.isoformat()}
            except (ValueError, AttributeError):
                continue
    return None


def _upcoming_session(
    schedule: list[dict], event_date_start: date
) -> tuple[int | None, dict | None]:
    """Return (minutes_until_start, session) for the next session not yet started."""
    now = datetime.now()
    for day_key, weekday_offset in DAY_MAP.items():
        delta = (weekday_offset - event_date_start.weekday()) % 7
        session_date = event_date_start + timedelta(days=delta)
        for s in _sessions_for_day(schedule, day_key):
            try:
                h, m = map(int, s["time_start"].split(":"))
                session_start = datetime.combine(session_date, time(h, m))
                diff = (session_start - now).total_seconds() / 60
                if diff > 0:
                    return round(diff), s
            except (ValueError, AttributeError, KeyError):
                continue
    return None, None


# ---------------------------------------------------------------------------
# Session Countdown Sensor – minutes until the next session starts
# ---------------------------------------------------------------------------

class SessionCountdownSensor(_EuroMotoSensor):
    _attr_icon = "mdi:timer-sand"
    _attr_name = "Session Countdown"
    _attr_native_unit_of_measurement = "min"

    def __init__(self, coordinator: EuroMotoCoordinator) -> None:
        super().__init__(coordinator, "session_countdown")
        self._cached_minutes: int | None = None
        self._cached_next: dict | None = None

    def _handle_coordinator_update(self) -> None:
        start = _event_start(self.coordinator.data.calendar)
        if start and self.coordinator.data.schedule:
            self._cached_minutes, self._cached_next = _upcoming_session(
                self.coordinator.data.schedule, start
            )
        else:
            self._cached_minutes, self._cached_next = None, None
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> int | None:
        return self._cached_minutes

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._cached_next
        if not s:
            return {}
        return {
            "session": s.get("session"),
            "class": s.get("cls"),
            "day": _DAY_DE.get(s.get("day", ""), s.get("day", "")),
            "time_start": s.get("time_start"),
            "time_end": s.get("time_end"),
        }


class WeekendScheduleSensor(_EuroMotoSensor):
    _attr_icon = "mdi:calendar-clock"
    _attr_name = "Weekend Schedule"

    def __init__(self, coordinator: EuroMotoCoordinator) -> None:
        super().__init__(coordinator, "weekend_schedule")

    @property
    def native_value(self) -> str | None:
        schedule = self.coordinator.data.schedule
        start = _event_start(self.coordinator.data.calendar)
        if not schedule or not start:
            return None
        nxt = _next_session(schedule, start)
        if not nxt:
            return "Kein weiteres Event"
        icon = _SESSION_ICON.get(nxt.get("session", ""), "📋")
        day_de = _DAY_DE.get(nxt.get("day", ""), nxt.get("day", ""))
        return f"{icon} {nxt.get('session')} {nxt.get('cls')} – {day_de} {nxt.get('time_start')}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        schedule = self.coordinator.data.schedule
        start = _event_start(self.coordinator.data.calendar)
        if not schedule:
            return {}

        def _format(s: dict) -> dict:
            time_range = s["time_start"]
            if s.get("time_end"):
                time_range += f"–{s['time_end']}"
            return {
                "day": _DAY_DE.get(s.get("day", ""), s.get("day", "")),
                "time": time_range,
                "session": s.get("session"),
                "class": s.get("cls"),
                "icon": _SESSION_ICON.get(s.get("session", ""), "📋"),
                "is_race": s.get("race", False),
            }

        return {
            "next_session": _next_session(schedule, start) if start else None,
            "friday": [_format(s) for s in _sessions_for_day(schedule, "friday")],
            "saturday": [_format(s) for s in _sessions_for_day(schedule, "saturday")],
            "sunday": [_format(s) for s in _sessions_for_day(schedule, "sunday")],
            "all_sessions": [_format(s) for s in schedule],
        }
