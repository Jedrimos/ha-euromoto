"""Calendar platform for Euro Moto race weekends."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    LIVETIMING_URL,
    LIVESTREAM_URL,
    SCHEDULE_FALLBACK,
    SCHEDULES_BY_SLUG,
    TICKETS_URL,
)
from .coordinator import EuroMotoCoordinator
from .scraper import TrackEvent

_DEVICE_INFO = DeviceInfo(identifiers={(DOMAIN, "euromoto")}, name="EuroMoto")

_DAY_WEEKDAY = {"friday": 4, "saturday": 5, "sunday": 6}

_SESSION_ICON = {
    "FP1": "🔵", "FP2": "🔵", "FP3": "🔵",
    "PreP": "🟡",
    "Q1": "🟡", "Q2": "🟡",
    "Superpole": "🟡", "Superpole 1": "🟡", "Superpole 2": "🟡",
    "Warm-up": "🟠",
    "Race 1": "🏁", "Race 2": "🏁",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EuroMotoCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EuroMotoCalendar(coordinator)], update_before_add=True)


def _event_slug(event: TrackEvent) -> str:
    if not event.track_url:
        return ""
    return event.track_url.rstrip("/").rsplit("/", 1)[-1]


def _to_calendar_event(event: TrackEvent, round_num: int) -> CalendarEvent:
    """Compact all-day event covering the full race weekend."""
    start = event.date_start.date()
    end = event.date_end.date() + timedelta(days=1)  # HA: exclusive end for all-day
    country = f" ({event.country})" if event.country else ""
    description = (
        f"Runde {round_num} · {TICKETS_URL}\n"
        f"📺 {LIVESTREAM_URL}\n"
        f"⏱️ {LIVETIMING_URL}"
    )
    return CalendarEvent(
        start=start,
        end=end,
        summary=f"Euro Moto {event.name}{country}",
        description=description,
        location=event.details.get("adresse") if event.details else None,
    )


def _session_date(event: TrackEvent, day_key: str) -> date | None:
    target_wd = _DAY_WEEKDAY.get(day_key)
    if target_wd is None:
        return None
    delta = (target_wd - event.date_start.weekday()) % 7
    d = event.date_start.date() + timedelta(days=delta)
    return d if d <= event.date_end.date() else None


def _session_to_calendar_event(
    event: TrackEvent,
    session: dict,
    round_num: int,
) -> CalendarEvent | None:
    """Timed CalendarEvent for a single session."""
    day_key = session.get("day", "")
    time_start = session.get("time_start", "")
    time_end = session.get("time_end", "")
    if not day_key or not time_start:
        return None

    d = _session_date(event, day_key)
    if d is None:
        return None

    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Berlin")
        h_s, m_s = map(int, time_start.split(":"))
        start_dt = datetime(d.year, d.month, d.day, h_s, m_s, tzinfo=tz)
        if time_end:
            h_e, m_e = map(int, time_end.split(":"))
            end_dt = datetime(d.year, d.month, d.day, h_e, m_e, tzinfo=tz)
        else:
            end_dt = start_dt + timedelta(minutes=30)
    except (ValueError, ImportError):
        return None

    session_name = session.get("session", "")
    cls = session.get("cls", "")
    is_streamed = session.get("streamed", False)

    icon = _SESSION_ICON.get(session_name, "📋")
    stream_tag = " 📺" if is_streamed else ""
    # Short summary: icon + session name + class + stream indicator
    summary = f"{icon} {session_name} – {cls}{stream_tag}"

    # Minimal description: just what matters
    if is_streamed:
        description = f"📺 {LIVESTREAM_URL}"
    else:
        description = f"⏱️ {LIVETIMING_URL}"

    return CalendarEvent(
        start=start_dt,
        end=end_dt,
        summary=summary,
        description=description,
    )


class EuroMotoCalendar(CoordinatorEntity[EuroMotoCoordinator], CalendarEntity):
    _attr_name = "EuroMoto Race Calendar"
    _attr_icon = "mdi:calendar-star"
    _attr_device_info = _DEVICE_INFO

    def __init__(self, coordinator: EuroMotoCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = "euromoto_race_calendar"
        self.entity_id = "calendar.euromoto_race_calendar"

    @property
    def event(self) -> CalendarEvent | None:
        """Return current or next upcoming race weekend event."""
        today = date.today()
        for i, ev in enumerate(self.coordinator.data.calendar):
            if ev.date_start.date() <= today <= ev.date_end.date():
                return _to_calendar_event(ev, i + 1)
            if ev.date_start.date() > today:
                return _to_calendar_event(ev, i + 1)
        return None

    def _schedule_for(self, event: TrackEvent, is_current: bool) -> list[dict]:
        """Pick the best schedule for a given event."""
        if is_current and self.coordinator.data.schedule:
            return self.coordinator.data.schedule
        slug = _event_slug(event)
        return SCHEDULES_BY_SLUG.get(slug, SCHEDULE_FALLBACK)

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        result: list[CalendarEvent] = []
        today = date.today()

        for i, ev in enumerate(self.coordinator.data.calendar):
            round_num = i + 1
            is_current = (
                ev.date_end.date() >= today
                and (i == 0 or self.coordinator.data.calendar[i - 1].date_end.date() < today)
            )

            # All-day overview for the weekend
            ev_start_dt = datetime(
                ev.date_start.year, ev.date_start.month, ev.date_start.day,
                tzinfo=timezone.utc,
            )
            excl_end = ev.date_end.date() + timedelta(days=1)
            ev_end_dt = datetime(excl_end.year, excl_end.month, excl_end.day, tzinfo=timezone.utc)
            if ev_end_dt >= start_date and ev_start_dt <= end_date:
                result.append(_to_calendar_event(ev, round_num))

            # All individual sessions as timed events
            schedule = self._schedule_for(ev, is_current)
            for session in schedule:
                cal_ev = _session_to_calendar_event(ev, session, round_num)
                if cal_ev is None:
                    continue
                # cal_ev.start is a timezone-aware datetime – compare directly
                if cal_ev.end >= start_date and cal_ev.start <= end_date:
                    result.append(cal_ev)

        return result
