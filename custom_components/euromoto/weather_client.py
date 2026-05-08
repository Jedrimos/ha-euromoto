"""Open-Meteo weather client for track conditions."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import OPEN_METEO_URL, WMO_TO_HA_CONDITION

_LOGGER = logging.getLogger(__name__)


async def fetch_track_weather(
    session: aiohttp.ClientSession,
    lat: float,
    lon: float,
    track_name: str = "",
) -> dict[str, Any]:
    """Fetch current weather at given coordinates from Open-Meteo."""
    url = OPEN_METEO_URL.format(lat=lat, lon=lon)
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            resp.raise_for_status()
            data = await resp.json()
    except Exception as exc:
        _LOGGER.warning("Failed to fetch weather for %s (%s, %s): %s", track_name, lat, lon, exc)
        return {}

    try:
        cur = data.get("current", {})
        wmo_code = int(cur.get("weather_code", -1))
        condition = WMO_TO_HA_CONDITION.get(wmo_code, "exceptional")
        return {
            "condition": condition,
            "wmo_code": wmo_code,
            "temperature": cur.get("temperature_2m"),
            "humidity": cur.get("relative_humidity_2m"),
            "precipitation": cur.get("precipitation"),
            "wind_speed": cur.get("wind_speed_10m"),
            "wind_bearing": cur.get("wind_direction_10m"),
            "pressure": cur.get("surface_pressure"),
            "track_name": track_name,
            "latitude": lat,
            "longitude": lon,
        }
    except Exception as exc:
        _LOGGER.warning("Error parsing weather response for %s: %s", track_name, exc)
        return {}
