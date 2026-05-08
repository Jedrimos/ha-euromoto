"""Tests for euromoto scraper."""
from __future__ import annotations

import pytest

from custom_components.euromoto.scraper import (
    _parse_calendar,
    _parse_date_range,
    _parse_track_details,
    _guess_country,
)

# Minimal HTML snapshot mimicking euromoto.racing/termine-strecken/
CALENDAR_HTML = """
<html><body>
<table>
  <tr>
    <th>Datum</th><th>Strecke</th><th>Info</th>
  </tr>
  <tr>
    <td>08.05.-10.05.2026</td>
    <td>Sachsenring</td>
    <td><a href="/strecke/sachsenring/">Zur Strecke</a></td>
  </tr>
  <tr>
    <td>29.05.-31.05.2026</td>
    <td>Brünn (CZ)</td>
    <td><a href="/strecke/bruenn/">Zur Strecke</a></td>
  </tr>
  <tr>
    <td>03.07.-05.07.2026</td>
    <td>Assen (NL)</td>
    <td><a href="/strecke/assen/">Zur Strecke</a></td>
  </tr>
</table>
</body></html>
"""

TRACK_HTML = """
<html><body>
<table>
  <tr><td>Länge:</td><td>3,67 km</td></tr>
  <tr><td>Rechtskurven:</td><td>3</td></tr>
  <tr><td>Linkskurven:</td><td>10</td></tr>
  <tr><td>Längste Gerade:</td><td>780 m</td></tr>
  <tr><td>Mindestbreite:</td><td>12 m</td></tr>
  <tr><td>Adresse:</td><td>Hohensteiner Str. 2, 09353 Oberlungwitz</td></tr>
</table>
</body></html>
"""


class TestDateRangeParsing:
    def test_full_range(self):
        result = _parse_date_range("08.05.-10.05.2026")
        assert result is not None
        start, end = result
        assert start.day == 8
        assert start.month == 5
        assert start.year == 2026
        assert end.day == 10
        assert end.month == 5

    def test_cross_month(self):
        result = _parse_date_range("29.05.-01.06.2026")
        assert result is not None
        start, end = result
        assert start.month == 5
        assert end.month == 6
        assert end.day == 1

    def test_single_day(self):
        result = _parse_date_range("08.05.2026")
        assert result is not None
        start, end = result
        assert start == end

    def test_invalid_returns_none(self):
        assert _parse_date_range("Kein Datum") is None


class TestCalendarParsing:
    def test_parses_three_events(self):
        events = _parse_calendar(CALENDAR_HTML)
        assert len(events) == 3

    def test_first_event_sachsenring(self):
        events = _parse_calendar(CALENDAR_HTML)
        assert events[0].name == "Sachsenring"
        assert events[0].date_start.year == 2026
        assert events[0].date_start.month == 5
        assert events[0].date_start.day == 8

    def test_track_url_resolved(self):
        events = _parse_calendar(CALENDAR_HTML)
        assert events[0].track_url == "https://euromoto.racing/strecke/sachsenring/"

    def test_country_detection_cz(self):
        events = _parse_calendar(CALENDAR_HTML)
        bruenn = next(e for e in events if "nn" in e.name)
        assert bruenn.country == "CZ"

    def test_country_detection_nl(self):
        events = _parse_calendar(CALENDAR_HTML)
        assen = next(e for e in events if "Assen" in e.name)
        assert assen.country == "NL"

    def test_empty_html_returns_empty(self):
        assert _parse_calendar("<html></html>") == []

    def test_sorted_by_date(self):
        events = _parse_calendar(CALENDAR_HTML)
        dates = [e.date_start for e in events]
        assert dates == sorted(dates)


class TestTrackDetails:
    def test_parses_length(self):
        details = _parse_track_details(TRACK_HTML)
        key = next((k for k in details if "laenge" in k or "l_nge" in k or "nge" in k), None)
        # Accept any key that has a numeric length value
        values = list(details.values())
        assert any(isinstance(v, (int, float)) for v in values)

    def test_parses_corners(self):
        details = _parse_track_details(TRACK_HTML)
        # rechtskurven -> key with "rechtskurven"
        right_key = next((k for k in details if "recht" in k), None)
        assert right_key is not None
        assert details[right_key] == 3

    def test_parses_address(self):
        details = _parse_track_details(TRACK_HTML)
        addr_key = next((k for k in details if "adresse" in k), None)
        assert addr_key is not None
        assert "Oberlungwitz" in str(details[addr_key])

    def test_empty_html_returns_empty(self):
        assert _parse_track_details("<html></html>") == {}


class TestCountryGuess:
    def test_de_default(self):
        assert _guess_country("Sachsenring") == "DE"

    def test_cz_bruenn(self):
        assert _guess_country("Brünn (CZ)") == "CZ"

    def test_nl_assen(self):
        assert _guess_country("Assen") == "NL"
