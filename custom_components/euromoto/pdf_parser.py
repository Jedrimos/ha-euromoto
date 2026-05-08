"""PDF parser for EURO MOTO / IDM championship standings."""
from __future__ import annotations

import io
import logging
from typing import Any

import aiohttp

from .const import PDF_BASE_URL, PDF_URL_TEMPLATE

_LOGGER = logging.getLogger(__name__)

_CLASS_SLUG_MAP = {
    "Superbike": "IDM_Superbike",
    "Supersport": "IDM_Supersport",
    "Sportbike": "IDM_Sportbike",
}


def _pdf_url(cls: str, year: int) -> str:
    slug = _CLASS_SLUG_MAP.get(cls, f"IDM_{cls}")
    return PDF_URL_TEMPLATE.format(base=PDF_BASE_URL, year=year, cls=slug.split("_")[1])


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
                        # Last column is typically Total points
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
                                "bike": bike,
                                "points": points,
                            }
                        )
                    except (ValueError, IndexError) as exc:
                        _LOGGER.debug("Skipping standings row %s: %s", row, exc)
    return results


class EuroMotoPdfParser:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def fetch_standings(self, cls: str, year: int | None = None) -> list[dict[str, Any]]:
        """Download and parse the standings PDF for the given class and year."""
        import datetime as dt

        if year is None:
            year = dt.date.today().year

        url = _pdf_url(cls, year)
        _LOGGER.debug("Fetching standings PDF: %s", url)

        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status == 404:
                    # PDF not yet published for this season – graceful degradation
                    _LOGGER.info(
                        "Standings PDF for %s %d not yet available (404)", cls, year
                    )
                    return []
                resp.raise_for_status()
                data = await resp.read()
        except aiohttp.ClientResponseError as exc:
            if exc.status == 404:
                _LOGGER.info(
                    "Standings PDF for %s %d not yet available (404)", cls, year
                )
                return []
            _LOGGER.warning("Error fetching standings for %s %d: %s", cls, year, exc)
            return []
        except Exception as exc:
            _LOGGER.warning("Error fetching standings for %s %d: %s", cls, year, exc)
            return []

        try:
            return _parse_standings_pdf(data)
        except Exception as exc:
            _LOGGER.error("Error parsing standings PDF for %s %d: %s", cls, year, exc)
            return []
