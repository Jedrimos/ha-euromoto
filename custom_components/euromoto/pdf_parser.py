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
    slug = _CLASS_SLUG_MAP.get(cls, f"IDM_{cls}")
    return PDF_URL_TEMPLATE.format(base=PDF_BASE_URL, year=year, cls=slug.split("_")[1])


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
        """Download a URL and return raw bytes, or None on 404/error."""
        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status == 404:
                    return None
                resp.raise_for_status()
                return await resp.read()
        except aiohttp.ClientResponseError as exc:
            if exc.status == 404:
                return None
            _LOGGER.warning("HTTP error fetching %s: %s", url, exc)
            return None
        except Exception as exc:
            _LOGGER.warning("Error fetching %s: %s", url, exc)
            return None

    async def fetch_standings(self, cls: str, year: int | None = None) -> list[dict[str, Any]]:
        """Download and parse the championship standings PDF."""
        import datetime as dt

        if year is None:
            year = dt.date.today().year

        url = _pdf_url(cls, year)
        _LOGGER.debug("Fetching standings PDF: %s", url)
        data = await self._fetch_bytes(url)
        if data is None:
            _LOGGER.info("Standings PDF for %s %d not yet available", cls, year)
            return []
        try:
            return _parse_standings_pdf(data)
        except Exception as exc:
            _LOGGER.error("Error parsing standings PDF for %s %d: %s", cls, year, exc)
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
            # Try the last 3 rounds (most recent first)
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
