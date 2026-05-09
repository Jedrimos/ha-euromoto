"""Calendar platform for EURO MOTO / IDM race weekends."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LIVETIMING_URL, LIVESTREAM_URL, TICKETS_URL
from .coordinator import EuroMotoCoordinator
from .scraper import TrackEvent

_DEVICE_INFO = DeviceInfo(identifiers={(DOMAIN, "euromoto")}, name="EuroMoto")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EuroMotoCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EuroMotoCalendar(coordinator)], update_before_add=True)


def _to_calendar_event(event: TrackEvent, round_num: int) -> CalendarEvent:
    start = event.date_start.date()
    # HA all-day events: end is exclusive (day after last day)
    end = event.date_end.date() + timedelta(days=1)
    country = f" {event.country}" if event.country else ""
    description_parts = [
        f"Runde {round_num}",
        f"🎫 Tickets: {TICKETS_URL}",
        f"📺 Livestream: {LIVESTREAM_URL}",
        f"⏱️ Live-Timing: {LIVETIMING_URL}",
    ]
    if event.details:
        length = event.details.get("laenge")
        if length:
            description_parts.insert(1, f"📏 Streckenlänge: {length} km")
    return CalendarEvent(
        start=start,
        end=end,
        summary=f"IDM {event.name}{country}",
        description="\n".join(description_parts),
        location=event.details.get("adresse") if event.details else None,
    )


class EuroMotoCalendar(CoordinatorEntity[EuroMotoCoordinator], CalendarEntity):
    _attr_has_entity_name = True
    _attr_name = "Race Calendar"
    _attr_icon = "mdi:calendar-star"
    _attr_device_info = _DEVICE_INFO

    def __init__(self, coordinator: EuroMotoCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = "euromoto_race_calendar"
        self.entity_id = "calendar.euromoto_race_calendar"

    @property
    def event(self) -> CalendarEvent | None:
        """Return current ongoing event or next upcoming event."""
        today = date.today()
        for i, ev in enumerate(self.coordinator.data.calendar):
            start = ev.date_start.date()
            end = ev.date_end.date()
            if start <= today <= end:
                return _to_calendar_event(ev, i + 1)
            if start > today:
                return _to_calendar_event(ev, i + 1)
        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        result: list[CalendarEvent] = []
        for i, ev in enumerate(self.coordinator.data.calendar):
            ev_start = datetime(
                ev.date_start.year, ev.date_start.month, ev.date_start.day,
                tzinfo=timezone.utc,
            )
            _end_date = ev.date_end.date() + timedelta(days=1)
            ev_end = datetime(_end_date.year, _end_date.month, _end_date.day, tzinfo=timezone.utc)
            if ev_end >= start_date and ev_start <= end_date:
                result.append(_to_calendar_event(ev, i + 1))
        return result
