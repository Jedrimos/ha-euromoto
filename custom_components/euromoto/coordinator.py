"""DataUpdateCoordinator for EURO MOTO / IDM."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    TRACK_COORDINATES,
    TRACK_DATA_FALLBACK,
    UPDATE_INTERVAL_NORMAL_HOURS,
    UPDATE_INTERVAL_RACE_MINUTES,
)
from .pdf_parser import EuroMotoPdfParser
from .scraper import EuroMotoScraper, TrackEvent
from .weather_client import fetch_track_weather

_LOGGER = logging.getLogger(__name__)

# TODO: Live-Timing via WebSocket (livetiming.raceresults.de)
# Protokoll muss noch reverse-engineered werden.
# Ziel-Daten: Sektorzeiten S1-S5, Gap, Best Lap, aktuelle Runde, Flag-Status
# Referenz-Analyse: Browser DevTools → Network → WS während Live-Session


@dataclass
class EuroMotoData:
    calendar: list[TrackEvent] = field(default_factory=list)
    standings: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    grid: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    track_weather: dict[str, Any] = field(default_factory=dict)
    season: int = 0


def _is_race_weekend(calendar: list[TrackEvent]) -> bool:
    today = date.today()
    return any(e.date_start.date() <= today <= e.date_end.date() for e in calendar)


def _next_event(calendar: list[TrackEvent]) -> TrackEvent | None:
    today = date.today()
    upcoming = [e for e in calendar if e.date_end.date() >= today]
    return upcoming[0] if upcoming else None


def _track_slug(event: TrackEvent) -> str | None:
    if not event.track_url:
        return None
    return event.track_url.rstrip("/").rsplit("/", 1)[-1]


def _merge_fallback(details: dict[str, Any], slug: str) -> dict[str, Any]:
    """Fill missing keys from hardcoded fallback data."""
    fallback = TRACK_DATA_FALLBACK.get(slug, {})
    merged = {**fallback, **details}  # scraped data wins over fallback
    return merged


class EuroMotoCoordinator(DataUpdateCoordinator[EuroMotoData]):
    def __init__(
        self,
        hass: HomeAssistant,
        enabled_classes: list[str],
        favorite_riders: list[int] | None = None,
    ) -> None:
        self._enabled_classes = enabled_classes
        self._favorite_riders = favorite_riders or []
        self._session: aiohttp.ClientSession | None = None
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=UPDATE_INTERVAL_NORMAL_HOURS),
        )

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # No custom User-Agent here – scraper.py injects browser headers per request
            self._session = aiohttp.ClientSession()
        return self._session

    async def _async_update_data(self) -> EuroMotoData:
        import datetime as dt

        session = self._get_session()
        scraper = EuroMotoScraper(session)
        pdf_parser = EuroMotoPdfParser(session)
        year = dt.date.today().year

        try:
            async with asyncio.TaskGroup() as tg:
                calendar_task = tg.create_task(scraper.fetch_calendar())
                standings_tasks = {
                    cls: tg.create_task(pdf_parser.fetch_standings(cls, year))
                    for cls in self._enabled_classes
                }
                grid_tasks = {
                    cls: tg.create_task(pdf_parser.fetch_starting_grid(cls, year))
                    for cls in self._enabled_classes
                }
        except* Exception as eg:
            for exc in eg.exceptions:
                _LOGGER.error("Error during parallel data fetch: %s", exc)
            raise UpdateFailed(f"Data fetch failed: {eg.exceptions[0]}") from eg.exceptions[0]

        calendar = calendar_task.result()

        # Enrich events with track details; always merge with hardcoded fallback
        for event in calendar:
            slug = _track_slug(event)
            if slug:
                try:
                    scraped = await scraper.fetch_track_details(slug)
                except Exception as exc:
                    _LOGGER.debug("Could not scrape details for %s: %s", slug, exc)
                    scraped = {}
                event.details = _merge_fallback(scraped, slug)
            elif event.name:
                # Try to match fallback by name
                name_slug = event.name.lower().replace(" ", "").replace("ü", "ue")
                for k in TRACK_DATA_FALLBACK:
                    if k in name_slug or name_slug in k:
                        event.details = TRACK_DATA_FALLBACK[k].copy()
                        break

        standings = {cls: task.result() for cls, task in standings_tasks.items()}
        grid = {cls: task.result() for cls, task in grid_tasks.items()}

        # Weather for the next event's track
        track_weather: dict[str, Any] = {}
        next_ev = _next_event(calendar)
        if next_ev:
            slug = _track_slug(next_ev)
            coords = TRACK_COORDINATES.get(slug or "")
            if coords:
                try:
                    track_weather = await fetch_track_weather(
                        session, coords[0], coords[1], next_ev.name
                    )
                except Exception as exc:
                    _LOGGER.debug("Weather fetch failed for %s: %s", next_ev.name, exc)

        self.update_interval = timedelta(
            minutes=UPDATE_INTERVAL_RACE_MINUTES
            if _is_race_weekend(calendar)
            else UPDATE_INTERVAL_NORMAL_HOURS * 60
        )

        return EuroMotoData(
            calendar=calendar,
            standings=standings,
            grid=grid,
            track_weather=track_weather,
            season=year,
        )

    async def async_shutdown(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        await super().async_shutdown()
