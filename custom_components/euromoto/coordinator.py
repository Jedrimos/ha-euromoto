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
    SCHEDULE_FALLBACK,
    TRACK_COORDINATES,
    TRACK_DATA_FALLBACK,
    UPDATE_INTERVAL_NORMAL_HOURS,
    UPDATE_INTERVAL_RACE_MINUTES,
)
from .livetiming import EuroMotoLiveTiming, LiveTimingState
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
    schedule: list[dict[str, Any]] = field(default_factory=list)
    season: int = 0
    rider_entries: list[dict[str, Any]] = field(default_factory=list)
    live_timing: LiveTimingState | None = None


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


def _best_fallback_key(slug: str, lookup: dict) -> str | None:
    """Find the best matching key in a dict for a URL slug via partial match."""
    if slug in lookup:
        return slug
    # Try: key is a substring of slug (e.g. "oschersleben" in "motorsport-arena-oschersleben")
    for key in lookup:
        if key in slug:
            return key
    # Try: slug is a substring of key
    for key in lookup:
        if slug in key:
            return key
    return None


def _merge_fallback(details: dict[str, Any], slug: str) -> dict[str, Any]:
    """Fill missing keys from hardcoded fallback data."""
    key = _best_fallback_key(slug, TRACK_DATA_FALLBACK)
    fallback = TRACK_DATA_FALLBACK.get(key, {}) if key else {}
    return {**fallback, **details}  # scraped data wins over fallback


class EuroMotoCoordinator(DataUpdateCoordinator[EuroMotoData]):
    def __init__(
        self,
        hass: HomeAssistant,
        enabled_classes: list[str],
        favorite_riders: list[int] | None = None,
        live_tenant_id: str = "c1",
    ) -> None:
        self._enabled_classes = enabled_classes
        self._favorite_riders = favorite_riders or []
        self._live_tenant_id = live_tenant_id
        self._session: aiohttp.ClientSession | None = None
        self._track_details_cache: dict[str, dict[str, Any]] = {}
        self._rider_entries_cache: list[dict[str, Any]] | None = None
        self._live_timing: EuroMotoLiveTiming | None = None
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

        # Enrich events with track details; cache scraped data to avoid re-fetching
        for event in calendar:
            slug = _track_slug(event)
            if slug:
                if slug not in self._track_details_cache:
                    try:
                        scraped = await scraper.fetch_track_details(slug)
                    except Exception as exc:
                        _LOGGER.debug("Could not scrape details for %s: %s", slug, exc)
                        scraped = {}
                    self._track_details_cache[slug] = _merge_fallback(scraped, slug)
                event.details = self._track_details_cache[slug]
            elif event.name:
                # Try to match fallback by name
                name_slug = event.name.lower().replace(" ", "").replace("ü", "ue")
                for k in TRACK_DATA_FALLBACK:
                    if k in name_slug or name_slug in k:
                        event.details = TRACK_DATA_FALLBACK[k].copy()
                        break

        standings = {cls: task.result() for cls, task in standings_tasks.items()}
        grid = {cls: task.result() for cls, task in grid_tasks.items()}

        # Rider entries (names, teams, bikes from website) – cached to reduce HTTP load
        if self._rider_entries_cache is None:
            try:
                self._rider_entries_cache = await scraper.fetch_rider_entries()
            except Exception as exc:
                _LOGGER.debug("Rider entries fetch failed: %s", exc)
                self._rider_entries_cache = []
        rider_entries = self._rider_entries_cache

        # Weather for the next event's track
        track_weather: dict[str, Any] = {}
        next_ev = _next_event(calendar)
        if next_ev:
            slug = _track_slug(next_ev)
            coord_key = _best_fallback_key(slug or "", TRACK_COORDINATES) if slug else None
            coords = TRACK_COORDINATES.get(coord_key) if coord_key else None
            if coords:
                try:
                    track_weather = await fetch_track_weather(
                        session, coords[0], coords[1], next_ev.name
                    )
                except Exception as exc:
                    _LOGGER.debug("Weather fetch failed for %s: %s", next_ev.name, exc)

        is_race_wknd = _is_race_weekend(calendar)
        self.update_interval = timedelta(
            minutes=UPDATE_INTERVAL_RACE_MINUTES
            if is_race_wknd
            else UPDATE_INTERVAL_NORMAL_HOURS * 60
        )

        # Start/stop live timing WebSocket based on race weekend status
        if is_race_wknd:
            if self._live_timing is None:
                self._live_timing = EuroMotoLiveTiming(
                    self._get_session(), self._live_tenant_id
                )
                self._live_timing.add_update_callback(self._on_live_update)
            await self._live_timing.async_start()
        else:
            if self._live_timing is not None:
                await self._live_timing.async_stop()

        # Schedule for the current/next race weekend
        schedule: list[dict[str, Any]] = []
        current_event = _next_event(calendar)
        if current_event:
            # Round number = position in sorted calendar (1-based)
            round_num = next(
                (i + 1 for i, e in enumerate(calendar) if e is current_event), 1
            )
            try:
                # 1. Try PDF from results.bike-promotion.com
                pdf_lines = await pdf_parser.fetch_schedule(round_num, year)
                if pdf_lines:
                    from .scraper import _parse_schedule as _ps
                    joined = "\n".join(f"<p>{ln}</p>" for ln in pdf_lines)
                    schedule = _ps(joined)
            except Exception as exc:
                _LOGGER.debug("PDF schedule fetch failed: %s", exc)
            if not schedule:
                # 2. Try HTML scraping (incl. PDF links embedded on track pages)
                try:
                    schedule = await scraper.fetch_schedule(current_event)
                except Exception as exc:
                    _LOGGER.debug("Schedule fetch failed: %s", exc)
        if not schedule:
            schedule = list(SCHEDULE_FALLBACK)

        return EuroMotoData(
            calendar=calendar,
            standings=standings,
            grid=grid,
            track_weather=track_weather,
            schedule=schedule,
            season=year,
            rider_entries=rider_entries,
            live_timing=self._live_timing.state if self._live_timing else None,
        )

    def _on_live_update(self, state: LiveTimingState) -> None:
        """Called by EuroMotoLiveTiming whenever new data arrives – push to HA."""
        if self.data:
            self.data.live_timing = state
        self.async_set_updated_data(self.data)

    async def async_shutdown(self) -> None:
        if self._live_timing:
            await self._live_timing.async_stop()
        if self._session and not self._session.closed:
            await self._session.close()
        await super().async_shutdown()
