"""HTML scraper for euromoto.racing."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import aiohttp
from bs4 import BeautifulSoup

from .const import (
    BASE_URL,
    CALENDAR_FALLBACK_2026,
    CALENDAR_URL,
    COUNTRY_HINTS,
    RIDERS_CLASS_URLS,
    RIDERS_URL_CANDIDATES,
    SCRAPER_HEADERS,
    TRACK_URL_TEMPLATE,
)

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


def _detect_class(text: str) -> str | None:
    """Return IDM class name if the text contains a class keyword."""
    t = text.lower()
    if "superbike" in t:
        return "Superbike"
    if "supersport" in t:
        return "Supersport"
    if "sportbike" in t or "sport bike" in t:
        return "Sportbike"
    return None


_RIDER_NUM_RE = re.compile(r"(?<!\d)(\d{1,3})(?!\d)")
_BIKE_BRANDS = ("Yamaha", "Honda", "Kawasaki", "BMW", "Ducati", "Aprilia", "Suzuki", "Triumph", "KTM", "MV Agusta")


def _parse_rider_entries(html: str) -> list[dict[str, Any]]:
    """Extract rider list from euromoto.racing HTML.

    Returns a list of dicts with keys: number, name, class, bike (opt), team (opt), nation (opt).
    Uses multiple strategies; returns [] if nothing useful found.
    """
    soup = BeautifulSoup(html, "html.parser")
    entries: list[dict[str, Any]] = []
    seen: set[int] = set()
    current_class = "Superbike"

    def _add(number: int, name: str, bike: str = "", team: str = "", nation: str = "", cls: str = "") -> None:
        if number in seen or number < 1 or number > 999 or len(name) < 2:
            return
        seen.add(number)
        entry: dict[str, Any] = {"number": number, "name": name[:60], "class": cls or current_class}
        if bike:
            entry["bike"] = bike[:40]
        if team:
            entry["team"] = team[:60]
        if nation:
            entry["nation"] = nation[:3].upper()
        entries.append(entry)

    def _find_brand(text: str) -> str:
        for b in _BIKE_BRANDS:
            if b.lower() in text.lower():
                return b
        return ""

    # ── Strategy 1: <table> rows ──────────────────────────────────────────────
    for table in soup.find_all("table"):
        # Check for a class heading above the table
        for prev in table.find_all_previous(["h1", "h2", "h3", "h4"], limit=3):
            cls = _detect_class(prev.get_text())
            if cls:
                current_class = cls
                break

        header_cells = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        rows = table.find_all("tr")
        data_rows = rows[1:] if header_cells else rows

        for row in data_rows:
            cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
            if len(cells) < 2:
                continue
            number = None
            for c in cells[:3]:
                stripped = c.strip("#").strip()
                if stripped.isdigit():
                    n = int(stripped)
                    if 1 <= n <= 999:
                        number = n
                        break
            if number is None:
                continue
            non_num = [c for c in cells if not c.strip("#").strip().isdigit() and len(c) > 1]
            name = non_num[0] if non_num else ""
            bike = _find_brand(" ".join(cells))
            team = non_num[1] if len(non_num) > 1 and non_num[1] != name else ""
            _add(number, name, bike=bike, team=team)

    # ── Strategy 2: headings followed by structured divs/cards ───────────────
    for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
        cls = _detect_class(heading.get_text())
        if cls:
            current_class = cls
        # Walk siblings to find rider cards
        for sib in heading.find_next_siblings(["div", "ul", "section", "article"], limit=5):
            for card in sib.find_all(["div", "article", "li"]):
                text = card.get_text(" ", strip=True)
                if len(text) < 3:
                    continue
                m = _RIDER_NUM_RE.search(text[:30])
                if not m:
                    continue
                number = int(m.group(1))
                rest = text[m.end():].strip()
                name = rest.split("\n")[0].strip()[:60]
                bike = _find_brand(text)
                _add(number, name, bike=bike)

    # ── Strategy 3: broad scan for number + name patterns ────────────────────
    if not entries:
        for el in soup.find_all(["p", "li", "div", "td"]):
            text = el.get_text(" ", strip=True)
            # Update class context
            cls = _detect_class(text)
            if cls and len(text) < 50:
                current_class = cls
                continue
            m = _RIDER_NUM_RE.match(text)
            if not m:
                continue
            number = int(m.group(1))
            rest = text[m.end():].strip()
            name = rest.split()[0] if rest.split() else ""
            # name should look like a person (capitalised first letter)
            if name and name[0].isupper() and len(name) > 2:
                _add(number, rest[:60], bike=_find_brand(text))

    return entries


_SCHEDULE_PDF_KEYWORDS = ("zeitplan", "timetable", "programm", "schedule", "fahrplan")


def _find_schedule_pdf_link(html: str, base_url: str) -> str | None:
    """Return the first PDF link whose text or href contains schedule keywords."""
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        label = (a.get_text(strip=True) + " " + href).lower()
        if href.lower().endswith(".pdf") and any(kw in label for kw in _SCHEDULE_PDF_KEYWORDS):
            return href if href.startswith("http") else BASE_URL + href
    return None


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
        except aiohttp.ClientResponseError as exc:
            if exc.status == 404:
                _LOGGER.debug("Not found (404): %s", url)
            else:
                _LOGGER.warning("Failed to fetch %s: %s", url, exc)
            return None
        except Exception as exc:
            _LOGGER.warning("Failed to fetch %s: %s", url, exc)
            return None

    async def fetch_calendar(self) -> list[TrackEvent]:
        html = await self._get(CALENDAR_URL)
        events: list[TrackEvent] = []
        if html:
            try:
                events = _parse_calendar(html)
            except Exception as exc:
                _LOGGER.error("Error parsing calendar: %s", exc)
        if not events:
            _LOGGER.info("Calendar scrape returned no events – using hardcoded 2026 fallback")
            events = _calendar_fallback()
        return events

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

    async def fetch_schedule(self, event: TrackEvent) -> list[dict[str, Any]]:
        """Try to scrape the race weekend timetable from multiple URL candidates.

        The euromoto.racing site often embeds the schedule as an image, so HTML
        scraping usually yields nothing.  We therefore also look for PDF
        download links that the track page may contain.
        """
        slug = None
        if event.track_url:
            slug = event.track_url.rstrip("/").rsplit("/", 1)[-1]

        candidates: list[str] = []
        if slug:
            candidates += [
                f"{BASE_URL}/veranstaltung/{slug}/",
                f"{BASE_URL}/event/{slug}/",
                f"{BASE_URL}/rennen/{slug}/",
            ]
        candidates.append(BASE_URL + "/")
        if slug:
            candidates += [
                f"{BASE_URL}/strecke/{slug}/programm/",
                f"{BASE_URL}/strecke/{slug}/zeitplan/",
                f"{BASE_URL}/strecke/{slug}/",
            ]
        elif event.track_url:
            candidates.append(event.track_url)

        for url in candidates:
            html = await self._get(url)
            if not html:
                continue
            try:
                # First try plain HTML schedule
                sessions = _parse_schedule(html)
                if sessions:
                    _LOGGER.debug("Schedule found at %s (%d sessions)", url, len(sessions))
                    return sessions
                # Fall back: look for PDF links containing "zeitplan"/"timetable"
                pdf_url = _find_schedule_pdf_link(html, url)
                if pdf_url:
                    sessions = await self._fetch_schedule_pdf(pdf_url)
                    if sessions:
                        _LOGGER.debug("Schedule from PDF %s (%d sessions)", pdf_url, len(sessions))
                        return sessions
            except Exception as exc:
                _LOGGER.debug("Schedule parse failed for %s at %s: %s", event.name, url, exc)
        return []

    async def _fetch_schedule_pdf(self, url: str) -> list[dict[str, Any]]:
        """Download a PDF and try to extract schedule sessions from its text."""
        try:
            async with self._session.get(
                url,
                headers=SCRAPER_HEADERS,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                data = await resp.read()
            import io
            import pdfplumber
            text_lines: list[str] = []
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    text_lines.extend(text.splitlines())
            # Build fake HTML from the extracted text so _parse_schedule can reuse its logic
            joined = "\n".join(f"<p>{ln}</p>" for ln in text_lines)
            return _parse_schedule(joined)
        except ImportError:
            _LOGGER.debug("pdfplumber not available – cannot parse schedule PDF")
            return []
        except Exception as exc:
            _LOGGER.debug("Schedule PDF fetch failed for %s: %s", url, exc)
            return []

    async def fetch_rider_entries(self) -> list[dict[str, Any]]:
        """Fetch rider/team data from per-class pages in parallel, fall back to generic URLs."""
        # --- Try class-specific pages first (parallel) ---
        import asyncio as _asyncio
        results: list[dict[str, Any]] = []
        tasks = {cls: _asyncio.create_task(self._get(url)) for cls, url in RIDERS_CLASS_URLS.items()}
        for cls, task in tasks.items():
            html = await task
            if not html:
                continue
            try:
                entries = _parse_rider_entries(html)
                for e in entries:
                    e["class"] = cls  # enforce class from URL
                results.extend(entries)
                _LOGGER.debug("Fetched %d entries for %s", len(entries), cls)
            except Exception as exc:
                _LOGGER.debug("Rider parse failed for %s: %s", cls, exc)

        if results:
            return results

        # --- Fallback: generic single-page candidates ---
        for url in RIDERS_URL_CANDIDATES:
            if url in RIDERS_CLASS_URLS.values():
                continue  # already tried above
            html = await self._get(url)
            if not html:
                continue
            try:
                entries = _parse_rider_entries(html)
                if entries:
                    _LOGGER.debug("Fetched %d rider entries from %s", len(entries), url)
                    return entries
            except Exception as exc:
                _LOGGER.debug("Rider parse failed for %s: %s", url, exc)
        return []


_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
# More-specific patterns must come before shorter ones (first match wins).
_SESSION_KEYWORDS = {
    "freies training 1": "FP1", "freies training 2": "FP2", "freies training 3": "FP3",
    "freies training": "FP1",
    "fp1": "FP1", "fp2": "FP2", "fp3": "FP3",
    "fp4": "FP4",
    "training": "Training",
    "superpole pre-practice": "PreP",
    "pre-practice": "PreP",
    "pre practice": "PreP",
    "prep": "PreP",
    "qualifying 1": "Q1", "qualifying 2": "Q2",
    "qualifying": "Q1",
    "superpole 1": "Superpole 1", "superpole 2": "Superpole 2",
    "superpole": "Superpole",
    "warm-up": "Warm-up",
    "warmup": "Warm-up",
    "rennen 1": "Race 1", "race 1": "Race 1",
    "rennen 2": "Race 2", "race 2": "Race 2",
    " r1": "Race 1", " r2": "Race 2",
    "q1": "Q1", "q2": "Q2",
}
_CLASS_KEYWORDS = {
    "zx-4rr": "ZX-4RR Cup",
    "zx4rr": "ZX-4RR Cup",
    "zx-6r": "ZX-6R Cup",
    "zx6r": "ZX-6R Cup",
    "adac junior": "ADAC Cup",
    "adac": "ADAC Cup",
    "moto4 northern": "Moto4 Cup",
    "moto4": "Moto4 Cup",
    "northern cup": "Moto4 Cup",
    "sbk": "Superbike",
    "superbike": "Superbike",
    "supersport": "Supersport",
    "sportbike": "Sportbike",
}
_DAY_KEYWORDS = {
    "freitag": "friday", "friday": "friday",
    "samstag": "saturday", "saturday": "saturday",
    "sonntag": "sunday", "sunday": "sunday",
}


def _parse_schedule(html: str) -> list[dict[str, Any]]:
    """Extract session timetable from an event page HTML.

    Looks for time patterns (HH:MM) near session-type and class keywords.
    Returns [] if nothing useful is found – caller falls back to hardcoded schedule.
    """
    soup = BeautifulSoup(html, "html.parser")
    sessions: list[dict[str, Any]] = []
    current_day = "friday"

    for el in soup.find_all(["tr", "li", "div", "p", "td"]):
        text = el.get_text(" ", strip=True).lower()

        # Detect day heading
        for kw, day in _DAY_KEYWORDS.items():
            if kw in text and len(text) < 40:
                current_day = day
                break

        # Find time(s) in this element
        times = _TIME_RE.findall(text)
        if not times:
            continue

        time_start = f"{int(times[0][0]):02d}:{times[0][1]}"
        time_end = f"{int(times[1][0]):02d}:{times[1][1]}" if len(times) >= 2 else ""

        # Detect session type
        session = ""
        for kw, label in _SESSION_KEYWORDS.items():
            if kw in text:
                session = label
                break
        if not session:
            continue

        # Detect class
        cls = "Support"
        for kw, label in _CLASS_KEYWORDS.items():
            if kw in text:
                cls = label
                break

        is_race = session.startswith("Race") or session in ("Race 1", "Race 2")
        sessions.append({
            "day": current_day,
            "time_start": time_start,
            "time_end": time_end,
            "session": session,
            "cls": cls,
            "race": is_race,
        })

    # Need at least a handful of sessions to be meaningful
    return sessions if len(sessions) >= 4 else []


def _make_event(date_raw: str, name_raw: str, track_url: str | None) -> TrackEvent | None:
    """Build a TrackEvent from raw date and name strings, or None if date unparseable."""
    parsed = _parse_date_range(date_raw)
    if not parsed:
        return None
    date_start, date_end = parsed
    clean_name = name_raw
    for hint in ("(CZ)", "(NL)", "(DE)"):
        clean_name = clean_name.replace(hint, "").strip()
    country = _guess_country(clean_name)
    return TrackEvent(
        name=clean_name,
        date_start=date_start,
        date_end=date_end,
        track_url=track_url,
        country=country,
    )


def _extract_link(element, base: str = BASE_URL) -> str | None:
    link = element.find("a", href=True) if hasattr(element, "find") else None
    if not link:
        return None
    href = link["href"]
    return href if href.startswith("http") else base + href


def _parse_calendar(html: str) -> list[TrackEvent]:
    """Parse calendar HTML – tries multiple common WordPress layout patterns."""
    soup = BeautifulSoup(html, "html.parser")
    events: list[TrackEvent] = []

    # ── Strategy 1: <table> with rows ────────────────────────────────────────
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            date_raw = cells[0].get_text(strip=True)
            name_raw = cells[1].get_text(strip=True)
            link_cell = cells[2] if len(cells) >= 3 else cells[1]
            ev = _make_event(date_raw, name_raw, _extract_link(link_cell))
            if ev:
                events.append(ev)

    # ── Strategy 2: <li> or <article> elements containing a date pattern ────
    if not events:
        for el in soup.find_all(["li", "article", "div"], class_=True):
            text = el.get_text(" ", strip=True)
            m = _DATE_RANGE_RE.search(text)
            if not m:
                continue
            date_raw = m.group(0)
            # Name = text after the date match, trimmed
            name_raw = text[m.end():].strip().split("\n")[0].strip()
            if not name_raw:
                name_raw = text[:m.start()].strip().split("\n")[-1].strip()
            if not name_raw:
                continue
            ev = _make_event(date_raw, name_raw, _extract_link(el))
            if ev:
                events.append(ev)

    # ── Strategy 3: scan ALL text for date+name pairs ────────────────────────
    if not events:
        for m in _DATE_RANGE_RE.finditer(soup.get_text(" ", strip=True)):
            date_raw = m.group(0)
            after = soup.get_text(" ", strip=True)[m.end():m.end() + 80].strip()
            name_raw = after.split("\n")[0].split("|")[0].strip()
            if len(name_raw) > 3:
                ev = _make_event(date_raw, name_raw, None)
                if ev:
                    events.append(ev)

    # Deduplicate by (date_start, name) and sort
    seen: set[tuple] = set()
    unique: list[TrackEvent] = []
    for ev in events:
        key = (ev.date_start, ev.name)
        if key not in seen:
            seen.add(key)
            unique.append(ev)
    unique.sort(key=lambda e: e.date_start)
    return unique


def _calendar_fallback() -> list[TrackEvent]:
    """Return hardcoded 2026 calendar as TrackEvent list."""
    events: list[TrackEvent] = []
    for entry in CALENDAR_FALLBACK_2026:
        start = datetime.strptime(entry["start"], "%Y-%m-%d")
        end = datetime.strptime(entry["end"], "%Y-%m-%d")
        slug = entry["slug"]
        events.append(TrackEvent(
            name=entry["name"],
            date_start=start,
            date_end=end,
            track_url=f"{BASE_URL}/strecke/{slug}/",
            country=entry["country"],
        ))
    return events
