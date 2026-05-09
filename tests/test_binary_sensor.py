"""Tests for binary sensor helper functions."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from custom_components.euromoto.binary_sensor import (
    _active_event,
    _session_state,
)
from custom_components.euromoto.scraper import TrackEvent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(start: date, end: date, name: str = "Test") -> TrackEvent:
    return TrackEvent(
        name=name,
        date_start=datetime(start.year, start.month, start.day),
        date_end=datetime(end.year, end.month, end.day),
        track_url=None,
        country="DE",
    )


SCHEDULE = [
    {"day": "friday",   "time_start": "09:00", "time_end": "09:30", "session": "FP1", "cls": "Superbike", "race": False},
    {"day": "saturday", "time_start": "14:00", "time_end": "14:25", "session": "Race 1", "cls": "Supersport", "race": True},
    {"day": "sunday",   "time_start": "10:50", "time_end": "11:15", "session": "Race 1", "cls": "Superbike", "race": True},
]


# ---------------------------------------------------------------------------
# _active_event
# ---------------------------------------------------------------------------

class TestActiveEvent:
    def test_active_during_weekend(self):
        today = date.today()
        ev = _make_event(today - timedelta(days=1), today + timedelta(days=1))
        assert _active_event([ev]) is ev

    def test_none_before_weekend(self):
        tomorrow = date.today() + timedelta(days=1)
        ev = _make_event(tomorrow, tomorrow + timedelta(days=2))
        assert _active_event([ev]) is None

    def test_none_after_weekend(self):
        yesterday = date.today() - timedelta(days=1)
        ev = _make_event(yesterday - timedelta(days=2), yesterday)
        assert _active_event([ev]) is None

    def test_empty_calendar(self):
        assert _active_event([]) is None

    def test_multiple_events_picks_current(self):
        today = date.today()
        past = _make_event(today - timedelta(days=10), today - timedelta(days=8), "Past")
        current = _make_event(today - timedelta(days=1), today + timedelta(days=1), "Current")
        future = _make_event(today + timedelta(days=5), today + timedelta(days=7), "Future")
        assert _active_event([past, current, future]) is current


# ---------------------------------------------------------------------------
# _session_state
# ---------------------------------------------------------------------------

class TestSessionState:
    def _event_start_for_friday(self) -> date:
        """Return the most recent Friday (for schedule test anchoring)."""
        today = date.today()
        days_since_friday = (today.weekday() - 4) % 7
        return today - timedelta(days=days_since_friday)

    def test_no_session_outside_race_weekend_days(self, monkeypatch):
        # Use a Monday for event_start so SCHEDULE days are in the future
        monday = date(2026, 5, 4)  # known Monday
        # No monkeypatching needed – if today's weekday is not Fri/Sat/Sun, returns False
        active, race, s = _session_state(SCHEDULE, monday)
        today_wd = date.today().weekday()
        if today_wd not in (4, 5, 6):
            assert active is False
            assert race is False
            assert s is None

    def test_empty_schedule(self):
        today = date.today()
        active, race, s = _session_state([], today)
        assert active is False
        assert race is False
        assert s is None

    def test_session_detection_during_practice(self, monkeypatch):
        """Simulate Friday FP1 session 09:10 (inside 09:00-09:30)."""
        friday = date(2026, 5, 8)  # Known Friday
        fake_now = datetime(2026, 5, 8, 9, 10)  # Friday 09:10
        monkeypatch.setattr(
            "custom_components.euromoto.binary_sensor.datetime",
            type("MockDT", (), {"now": staticmethod(lambda: fake_now), "combine": datetime.combine})(),
        )
        active, race, s = _session_state(SCHEDULE, friday)
        assert active is True
        assert race is False
        assert s is not None
        assert s["session"] == "FP1"

    def test_race_detection(self, monkeypatch):
        """Simulate Saturday Race 1 at 14:10."""
        friday = date(2026, 5, 8)
        fake_now = datetime(2026, 5, 9, 14, 10)  # Saturday 14:10
        monkeypatch.setattr(
            "custom_components.euromoto.binary_sensor.datetime",
            type("MockDT", (), {"now": staticmethod(lambda: fake_now), "combine": datetime.combine})(),
        )
        active, race, s = _session_state(SCHEDULE, friday)
        assert active is True
        assert race is True
        assert s["session"] == "Race 1"

    def test_between_sessions(self, monkeypatch):
        """Simulate Saturday 11:00 – between FP1 and Race 1 (nothing active)."""
        friday = date(2026, 5, 8)
        fake_now = datetime(2026, 5, 9, 11, 0)  # Saturday 11:00
        monkeypatch.setattr(
            "custom_components.euromoto.binary_sensor.datetime",
            type("MockDT", (), {"now": staticmethod(lambda: fake_now), "combine": datetime.combine})(),
        )
        active, race, s = _session_state(SCHEDULE, friday)
        assert active is False
        assert race is False
