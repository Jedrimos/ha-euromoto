"""PDF parser for EURO MOTO / IDM championship standings and starting grids."""
from __future__ import annotations

import io
import logging
from typing import Any

import aiohttp

from .const import (
    PDF_BASE_URL,
    PDF_URL_TEMPLATE,
    GRID_PDF_BASE_URL,
    GRID_PDF_URL_TEMPLATES,
    NATION_FLAGS,
    SCHEDULE_PDF_URL_TEMPLATES,
    SCRAPER_HEADERS,
)

_LOGGER = logging.getLogger(__name__)

_CLASS_SLUG_MAP = {
    "Superbike": "IDM_Superbike",
    "Supersport": "IDM_Supersport",
    "Sportbike": "IDM_Sportbike",
}


def _flag(nation: str | None) -> str:
    if not nation:
        return ""
    return NATION_FLAGS.get(nation.upper(), "")


def _pdf_url(cls: str, year: int) -> str:
    return PDF_URL_TEMPLATE.format(base=PDF_BASE_URL, year=year, cls=cls.upper())


def _grid_urls(cls: str, year: int, round_num: int) -> list[str]:
    cls_short = _CLASS_SLUG_MAP.get(cls, f"IDM_{cls}").split("_")[1]
    return [
        tpl.format(base=GRID_PDF_BASE_URL, year=year, round=round_num, cls=cls_short)
        for tpl in GRID_PDF_URL_TEMPLATES
    ]


def _parse_standings_pdf(data: bytes) -> list[dict[str, Any]]:
    """Extract standings rows from a PDF binary."""
    import pdfplumber  # lazy import – not available until runtime

    results: list[dict[str, Any]] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if not row or len(row) < 3:
                        continue
                    pos_raw = (row[0] or "").strip()
                    if not pos_raw.isdigit():
                        continue
                    try:
                        pos = int(pos_raw)
                        number_raw = (row[1] or "").strip()
                        number = int(number_raw) if number_raw.isdigit() else None
                        name = (row[2] or "").strip() or None
                        nation = (row[3] or "").strip() if len(row) > 3 else None
                        bike = (row[4] or "").strip() if len(row) > 4 else None
                        points_raw = (row[-1] or "").strip() if row[-1] else ""
                        try:
                            points: int | None = int(float(points_raw))
                        except (ValueError, TypeError):
                            points = None
                        results.append(
                            {
                                "pos": pos,
                                "number": number,
                                "name": name,
                                "nation": nation,
                                "flag": _flag(nation),
                                "bike": bike,
                                "points": points,
                            }
                        )
                    except (ValueError, IndexError) as exc:
                        _LOGGER.debug("Skipping standings row %s: %s", row, exc)
    return results


def _parse_grid_pdf(data: bytes) -> list[dict[str, Any]]:
    """Extract starting grid / qualifying rows from a PDF.

    Typical columns: Pos | # | Name | Nation | Bike | Time (or Gap)
    """
    import pdfplumber

    results: list[dict[str, Any]] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if not row or len(row) < 3:
                        continue
                    pos_raw = (row[0] or "").strip()
                    if not pos_raw.isdigit():
                        continue
                    try:
                        pos = int(pos_raw)
                        number_raw = (row[1] or "").strip()
                        number = int(number_raw) if number_raw.isdigit() else None
                        name = (row[2] or "").strip() or None
                        nation = (row[3] or "").strip() if len(row) > 3 else None
                        bike = (row[4] or "").strip() if len(row) > 4 else None
                        time_raw = (row[5] or "").strip() if len(row) > 5 else None
                        results.append(
                            {
                                "grid_pos": pos,
                                "number": number,
                                "name": name,
                                "nation": nation,
                                "flag": _flag(nation),
                                "bike": bike,
                                "best_time": time_raw,
                            }
                        )
                    except (ValueError, IndexError) as exc:
                        _LOGGER.debug("Skipping grid row %s: %s", row, exc)
    return results


class EuroMotoPdfParser:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def _fetch_bytes(self, url: str) -> bytes | None:
        """Download a URL and return raw bytes, or None on 404/error.

        Sends the same browser-like headers as scraper.py - without them,
        results.bike-promotion.com (like euromoto.racing) can reject the
        default aiohttp User-Agent, making every PDF fetch fail regardless
        of whether the URL itself is correct.
        """
        try:
            async with self._session.get(
                url, headers=SCRAPER_HEADERS, timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status == 404:
                    return None
                resp.raise_for_status()
                return await resp.read()
        except aiohttp.ClientResponseError as exc:
            if exc.status == 404:
                return None
            _LOGGER.debug("HTTP error fetching %s: %s", url, exc)
            return None
        except Exception as exc:
            _LOGGER.debug("Error fetching %s: %s", url, exc)
            return None

    async def fetch_standings(self, cls: str, year: int | None = None) -> list[dict[str, Any]]:
        """Download and parse the championship standings PDF.

        Confirmed against the site's own file browser (results.bike-promotion.com
        /#Results/Championship scores/{year}/01 EURO MOTO/): this is a single
        continuously-updated cumulative PDF per class directly under "01 EURO
        MOTO" - not split by round, and not "IDM"-named (that branding was
        dropped season-wide).
        """
        import datetime as dt

        if year is None:
            year = dt.date.today().year

        url = _pdf_url(cls, year)
        data = await self._fetch_bytes(url)
        if data is None:
            _LOGGER.info("Standings PDF for %s %d not yet available at %s", cls, year, url)
            return []
        try:
            return _parse_standings_pdf(data)
        except Exception as exc:
            _LOGGER.error("Error parsing standings PDF %s: %s", url, exc)
            return []

    async def fetch_starting_grid(
        self, cls: str, year: int | None = None, round_num: int | None = None
    ) -> list[dict[str, Any]]:
        """Download and parse the most recent starting grid / qualifying PDF.

        Tries multiple URL patterns and multiple recent round numbers.
        Returns empty list if nothing is found (e.g. before the season starts).
        """
        import datetime as dt

        if year is None:
            year = dt.date.today().year
        if round_num is None:
            # Caller doesn't know the current round number (calendar fetch runs in
            # parallel) – probe every possible round this season, most recent first.
            rounds_to_try = list(range(8, 0, -1))
        else:
            rounds_to_try = [round_num]

        for rnd in rounds_to_try:
            for url in _grid_urls(cls, year, rnd):
                data = await self._fetch_bytes(url)
                if data is not None:
                    _LOGGER.debug("Found grid PDF at %s", url)
                    try:
                        rows = _parse_grid_pdf(data)
                        if rows:
                            return rows
                    except Exception as exc:
                        _LOGGER.warning("Error parsing grid PDF %s: %s", url, exc)

        _LOGGER.info("No starting grid PDF found for %s %d", cls, year)
        return []

    async def fetch_schedule(self, round_num: int, year: int | None = None) -> list[str]:
        """Try to download a schedule PDF from results.bike-promotion.com.

        Returns the extracted text lines (one per line) on success, [] otherwise.
        The caller (scraper) can then run _parse_schedule() on them.
        """
        import datetime as dt

        if year is None:
            year = dt.date.today().year

        for tpl in SCHEDULE_PDF_URL_TEMPLATES:
            url = tpl.format(base=GRID_PDF_BASE_URL, year=year, round=round_num)
            data = await self._fetch_bytes(url)
            if data is None:
                continue
            try:
                import io
                import pdfplumber
                lines: list[str] = []
                with pdfplumber.open(io.BytesIO(data)) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text() or ""
                        lines.extend(text.splitlines())
                if lines:
                    _LOGGER.debug("Schedule PDF found at %s (%d lines)", url, len(lines))
                    return lines
            except ImportError:
                _LOGGER.debug("pdfplumber not available for schedule PDF")
                return []
            except Exception as exc:
                _LOGGER.debug("Error parsing schedule PDF %s: %s", url, exc)

        return []
