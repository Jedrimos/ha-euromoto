"""HTML scraper for euromoto.racing."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import aiohttp
from bs4 import BeautifulSoup

from .const import BASE_URL, CALENDAR_URL, COUNTRY_HINTS, SCRAPER_HEADERS, TRACK_URL_TEMPLATE

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
        if g[0]:
            s_day = int(g[0])
            e_day = int(g[2])
            e_month = int(g[3])
            year = int(g[4])
            s_month = int(g[1]) if g[1] else e_month
            start = datetime(year, s_month, s_day)
            end = datetime(year, e_month, e_day)
        else:
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


def _normalise_key(raw: str) -> str:
    return (
        raw.lower().strip().rstrip(":")
        .replace(" ", "_")
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )


def _coerce_value(val_raw: str) -> Any:
    """Try to coerce a string to int/float, keep as string otherwise."""
    cleaned = val_raw.replace(",", ".").split()[0] if val_raw else ""
    if cleaned:
        try:
            return float(cleaned) if "." in cleaned else int(cleaned)
        except ValueError:
            pass
    return val_raw or None


def _parse_track_details(html: str) -> dict[str, Any]:
    """Parse facts from a track detail page – tries multiple HTML structures."""
    soup = BeautifulSoup(html, "html.parser")
    details: dict[str, Any] = {}

    # Strategy 1: <table> with two-column rows
    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            key_raw = cells[0].get_text(strip=True)
            val_raw = cells[1].get_text(strip=True)
            if key_raw and val_raw:
                details[_normalise_key(key_raw)] = _coerce_value(val_raw)

    # Strategy 2: <dl>/<dt>/<dd> definition lists
    for dl in soup.find_all("dl"):
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            key_raw = dt.get_text(strip=True)
            val_raw = dd.get_text(strip=True)
            if key_raw and val_raw:
                details[_normalise_key(key_raw)] = _coerce_value(val_raw)

    # Strategy 3: <div> pairs where first child looks like a label
    for div in soup.find_all("div"):
        children = [c for c in div.children if hasattr(c, "get_text")]
        if len(children) == 2:
            key_raw = children[0].get_text(strip=True)
            val_raw = children[1].get_text(strip=True)
            # Only treat as label/value if key ends with ":" or is short
            if key_raw and val_raw and (key_raw.endswith(":") or len(key_raw) < 30):
                k = _normalise_key(key_raw)
                if k and k not in details:
                    details[k] = _coerce_value(val_raw)

    # Strategy 4: regex scan of raw text for known patterns
    text = soup.get_text(" ", strip=True)
    _PATTERNS = [
        (r"[Ll][äa]nge[:\s]+(\d+[,\.]\d+)\s*km", "laenge"),
        (r"Rechtskurven[:\s]+(\d+)", "rechtskurven"),
        (r"Linkskurven[:\s]+(\d+)", "linkskurven"),
        (r"[Ll][äa]ngste\s+Gerade[:\s]+(\d+)\s*m", "laengste_gerade"),
        (r"Mindestbreite[:\s]+(\d+)\s*m", "mindestbreite"),
    ]
    for pattern, key in _PATTERNS:
        if key not in details:
            m = re.search(pattern, text)
            if m:
                raw = m.group(1).replace(",", ".")
                try:
                    details[key] = float(raw) if "." in raw else int(raw)
                except ValueError:
                    pass

    return details


class EuroMotoScraper:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def _get(self, url: str) -> str | None:
        try:
            async with self._session.get(
                url,
                headers=SCRAPER_HEADERS,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                return await resp.text()
        except Exception as exc:
            _LOGGER.warning("Failed to fetch %s: %s", url, exc)
            return None

    async def fetch_calendar(self) -> list[TrackEvent]:
        html = await self._get(CALENDAR_URL)
        if not html:
            return []
        try:
            return _parse_calendar(html)
        except Exception as exc:
            _LOGGER.error("Error parsing calendar: %s", exc)
            return []

    async def fetch_track_details(self, slug: str) -> dict[str, Any]:
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

            track_url: str | None = None
            if len(cells) >= 3:
                link = cells[2].find("a", href=True)
                if link:
                    href = link["href"]
                    track_url = href if href.startswith("http") else BASE_URL + href

            country = _guess_country(name_raw)
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
