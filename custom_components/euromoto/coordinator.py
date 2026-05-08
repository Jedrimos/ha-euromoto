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
    ALL_CLASSES,
    UPDATE_INTERVAL_NORMAL_HOURS,
    UPDATE_INTERVAL_RACE_MINUTES,
)
from .pdf_parser import EuroMotoPdfParser
from .scraper import EuroMotoScraper, TrackEvent

_LOGGER = logging.getLogger(__name__)

# TODO: Live-Timing via WebSocket (livetiming.raceresults.de)
# Protokoll muss noch reverse-engineered werden.
# Ziel-Daten: Sektorzeiten S1-S5, Gap, Best Lap, aktuelle Runde, Flag-Status
# Referenz-Analyse: Browser DevTools → Network → WS während Live-Session


@dataclass
class EuroMotoData:
    calendar: list[TrackEvent] = field(default_factory=list)
    standings: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    season: int = 0


def _is_race_weekend(calendar: list[TrackEvent]) -> bool:
    today = date.today()
    return any(
        e.date_start.date() <= today <= e.date_end.date() for e in calendar
    )


class EuroMotoCoordinator(DataUpdateCoordinator[EuroMotoData]):
    def __init__(
        self,
        hass: HomeAssistant,
        enabled_classes: list[str],
    ) -> None:
        self._enabled_classes = enabled_classes
        self._session: aiohttp.ClientSession | None = None
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=UPDATE_INTERVAL_NORMAL_HOURS),
        )

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": "ha-euromoto/0.1 HomeAssistant"}
            )
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
        except* Exception as eg:
            for exc in eg.exceptions:
                _LOGGER.error("Error during parallel data fetch: %s", exc)
            raise UpdateFailed(f"Data fetch failed: {eg.exceptions[0]}") from eg.exceptions[0]

        calendar = calendar_task.result()

        # Enrich events with track details (lazy, in sequence to avoid hammering)
        for event in calendar:
            if event.track_url:
                slug = event.track_url.rstrip("/").rsplit("/", 1)[-1]
                try:
                    event.details = await scraper.fetch_track_details(slug)
                except Exception as exc:
                    _LOGGER.debug("Could not load details for %s: %s", slug, exc)

        standings = {cls: task.result() for cls, task in standings_tasks.items()}

        # Adjust update interval based on whether we're in a race weekend
        if _is_race_weekend(calendar):
            self.update_interval = timedelta(minutes=UPDATE_INTERVAL_RACE_MINUTES)
        else:
            self.update_interval = timedelta(hours=UPDATE_INTERVAL_NORMAL_HOURS)

        return EuroMotoData(calendar=calendar, standings=standings, season=year)

    async def async_shutdown(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        await super().async_shutdown()
