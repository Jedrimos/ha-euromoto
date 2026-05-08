"""HTML scraper for euromoto.racing."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import aiohttp
from bs4 import BeautifulSoup

from .const import BASE_URL, CALENDAR_URL, COUNTRY_HINTS, TRACK_URL_TEMPLATE

_LOGGER = logging.getLogger(__name__)

# Matches:  08.05.-10.05.2026  or  08.-10.05.2026  or  08.05.2026
_DATE_RANGE_RE = re.compile(
    r"(\d{2})\.(\d{2})?\.?-(\d{2})\.(\d{2})\.(\d{4})"  # full range
    r"|(\d{2})\.(\d{2})\.(\d{4})"                        # single day
)


@dataclass
class TrackEvent:
    name: str
    date_start: datetime
    date_end: datetime
    track_url: str | None
    country: str | None
    details: dict[str, Any] = field(default_factory=dict)


def _parse_date_range(raw: str) -> tuple[datetime, datetime] | None:
    """Parse date range strings like '08.05.-10.05.2026' into (start, end)."""
    raw = raw.strip()
    m = _DATE_RANGE_RE.search(raw)
    if not m:
        return None
    g = m.groups()
    try:
        if g[0]:  # range form: s_day, s_month_opt, e_day, e_month, year
            s_day = int(g[0])
            e_day = int(g[2])
            e_month = int(g[3])
            year = int(g[4])
            s_month = int(g[1]) if g[1] else e_month
            start = datetime(year, s_month, s_day)
            end = datetime(year, e_month, e_day)
        else:  # single day form: s_day, s_month, year
            s_day = int(g[5])
            s_month = int(g[6])
            year = int(g[7])
            start = end = datetime(year, s_month, s_day)
        return start, end
    except (ValueError, TypeError):
        return None


def _guess_country(name: str) -> str:
    for hint, code in COUNTRY_HINTS.items():
        if hint in name:
            return code
    return "DE"


def _parse_track_details(html: str) -> dict[str, Any]:
    """Parse the facts table on a track detail page."""
    soup = BeautifulSoup(html, "html.parser")
    details: dict[str, Any] = {}

    # The facts table uses <tr><td>Label:</td><td>Value</td></tr>
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        key_raw = cells[0].get_text(strip=True).rstrip(":")
        val_raw = cells[1].get_text(strip=True)
        if not key_raw:
            continue
        key = (
            key_raw.lower()
            .replace(" ", "_")
            .replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
        )
        # Try numeric coercion
        numeric = val_raw.replace(",", ".").split()[0] if val_raw else None
        try:
            val: Any = float(numeric) if "." in numeric else int(numeric)
        except (ValueError, TypeError):
            val = val_raw or None
        details[key] = val

    return details


class EuroMotoScraper:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def _get(self, url: str) -> str | None:
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                resp.raise_for_status()
                return await resp.text()
        except Exception as exc:
            _LOGGER.warning("Failed to fetch %s: %s", url, exc)
            return None

    async def fetch_calendar(self) -> list[TrackEvent]:
        """Fetch and parse the race calendar."""
        html = await self._get(CALENDAR_URL)
        if not html:
            return []
        try:
            return _parse_calendar(html)
        except Exception as exc:
            _LOGGER.error("Error parsing calendar: %s", exc)
            return []

    async def fetch_track_details(self, slug: str) -> dict[str, Any]:
        """Fetch and parse a track detail page."""
        url = TRACK_URL_TEMPLATE.format(slug=slug)
        html = await self._get(url)
        if not html:
            return {}
        try:
            return _parse_track_details(html)
        except Exception as exc:
            _LOGGER.warning("Error parsing track details for %s: %s", slug, exc)
            return {}


def _parse_calendar(html: str) -> list[TrackEvent]:
    soup = BeautifulSoup(html, "html.parser")
    events: list[TrackEvent] = []

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            date_raw = cells[0].get_text(strip=True)
            name_raw = cells[1].get_text(strip=True)
            if not date_raw or not name_raw:
                continue

            parsed = _parse_date_range(date_raw)
            if not parsed:
                continue
            date_start, date_end = parsed

            # Extract link from third cell if present
            track_url: str | None = None
            if len(cells) >= 3:
                link = cells[2].find("a", href=True)
                if link:
                    href = link["href"]
                    track_url = href if href.startswith("http") else BASE_URL + href

            country = _guess_country(name_raw)
            # Strip country hints from displayed name
            clean_name = name_raw
            for hint in ("(CZ)", "(NL)", "(DE)"):
                clean_name = clean_name.replace(hint, "").strip()

            events.append(
                TrackEvent(
                    name=clean_name,
                    date_start=date_start,
                    date_end=date_end,
                    track_url=track_url,
                    country=country,
                )
            )

    events.sort(key=lambda e: e.date_start)
    return events
