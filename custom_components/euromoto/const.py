"""Constants for the EURO MOTO / IDM integration."""
from __future__ import annotations

from typing import Any

DOMAIN = "euromoto"
CONF_CLASSES = "classes"
CONF_FAVORITE_RIDERS = "favorite_rider_numbers"  # list of ints

CLASS_SUPERBIKE = "Superbike"
CLASS_SUPERSPORT = "Supersport"
CLASS_SPORTBIKE = "Sportbike"
ALL_CLASSES = [CLASS_SUPERBIKE, CLASS_SUPERSPORT, CLASS_SPORTBIKE]

BASE_URL = "https://euromoto.racing"
CALENDAR_URL = f"{BASE_URL}/termine-strecken/"
TRACK_URL_TEMPLATE = f"{BASE_URL}/strecke/{{slug}}/"

PDF_BASE_URL = "https://results.bike-promotion.com/Results/Championship%20scores"
PDF_URL_TEMPLATE = (
    "{base}/{year}/01%20IDM/IDM%20Punktest%C3%A4nde%20IDM_{cls}.pdf"
)

KNOWN_TRACK_SLUGS = [
    "sachsenring",
    "bruenn",
    "most",
    "oschersleben",
    "assen",
    "nuerburgring",
    "hockenheim",
]

# Country hints embedded in track names
COUNTRY_HINTS: dict[str, str] = {
    "CZ": "CZ",
    "(CZ)": "CZ",
    "NL": "NL",
    "(NL)": "NL",
    "Assen": "NL",
    "Brünn": "CZ",
    "Bruenn": "CZ",
    "Brno": "CZ",
    "Most": "CZ",
}

# Hardcoded 2026 IDM season calendar – used when website is unreachable.
# Source: https://idm.de/2025/09/27/idm-der-terminkalender-fuer-2026-steht-fest/
CALENDAR_FALLBACK_2026: list[dict[str, str]] = [
    {"name": "Sachsenring",       "start": "2026-05-08", "end": "2026-05-10", "country": "DE", "slug": "sachsenring"},
    {"name": "Brünn",             "start": "2026-05-29", "end": "2026-05-31", "country": "CZ", "slug": "bruenn"},
    {"name": "Autodrom Most",     "start": "2026-06-26", "end": "2026-06-28", "country": "CZ", "slug": "most"},
    {"name": "Oschersleben",      "start": "2026-07-31", "end": "2026-08-02", "country": "DE", "slug": "oschersleben"},
    {"name": "TT Circuit Assen",  "start": "2026-08-14", "end": "2026-08-16", "country": "NL", "slug": "assen"},
    {"name": "Nürburgring",       "start": "2026-09-04", "end": "2026-09-06", "country": "DE", "slug": "nuerburgring"},
    {"name": "Hockenheim",        "start": "2026-09-25", "end": "2026-09-27", "country": "DE", "slug": "hockenheim"},
]

TICKETS_URL = "https://tickets.euromoto.racing/"
LIVESTREAM_URL = f"{BASE_URL}/live/"
LIVETIMING_URL = "http://livetiming.bike-promotion.com/#/channel/c1"

UPDATE_INTERVAL_NORMAL_HOURS = 6
UPDATE_INTERVAL_RACE_MINUTES = 30

# Known track GPS coordinates (lat, lon) for weather lookup
TRACK_COORDINATES: dict[str, tuple[float, float]] = {
    "sachsenring":  (50.7914, 12.6872),
    "bruenn":       (49.2019, 16.7292),
    "most":         (50.5233, 13.6369),
    "oschersleben": (52.0278, 11.2858),
    "assen":        (52.9628,  6.5239),
    "nuerburgring": (50.3356,  6.9475),
    "hockenheim":   (49.3278,  8.5656),
}

# Hardcoded track facts – used as fallback when the website cannot be scraped
TRACK_DATA_FALLBACK: dict[str, dict[str, Any]] = {
    "sachsenring": {
        "laenge": 3.671,
        "rechtskurven": 3,
        "linkskurven": 10,
        "laengste_gerade": 780,
        "mindestbreite": 12,
        "adresse": "Hohensteiner Str. 2, 09353 Oberlungwitz",
    },
    "bruenn": {
        "laenge": 5.403,
        "rechtskurven": 9,
        "linkskurven": 5,
        "laengste_gerade": 636,
        "adresse": "Masarykova okruh, Brno, Tschechien",
    },
    "most": {
        "laenge": 4.213,
        "rechtskurven": 10,
        "linkskurven": 11,
        "laengste_gerade": 690,
        "adresse": "Autodrom Most, 434 01 Most, Tschechien",
    },
    "oschersleben": {
        "laenge": 3.696,
        "rechtskurven": 7,
        "linkskurven": 8,
        "laengste_gerade": 725,
        "adresse": "Werner-Heisenberg-Allee 1, 39387 Oschersleben",
    },
    "assen": {
        "laenge": 4.555,
        "rechtskurven": 9,
        "linkskurven": 9,
        "laengste_gerade": 584,
        "adresse": "TT Circuit Assen, Assen, Niederlande",
    },
    "nuerburgring": {
        "laenge": 3.629,
        "rechtskurven": 7,
        "linkskurven": 5,
        "laengste_gerade": 719,
        "adresse": "Otto-Flimm-Str., 53520 Nürburg",
    },
    "hockenheim": {
        "laenge": 4.574,
        "rechtskurven": 5,
        "linkskurven": 2,
        "laengste_gerade": 1047,
        "adresse": "Am Motodrom, 68766 Hockenheim",
    },
}

# Open-Meteo – free, no API key needed
OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}"
    "&current=temperature_2m,relative_humidity_2m,precipitation,"
    "weather_code,wind_speed_10m,wind_direction_10m,surface_pressure"
    "&wind_speed_unit=kmh&timezone=auto"
)

# WMO code → HA weather condition string
WMO_TO_HA_CONDITION: dict[int, str] = {
    0:  "sunny",
    1:  "sunny",
    2:  "partlycloudy",
    3:  "cloudy",
    45: "fog",
    48: "fog",
    51: "rainy",
    53: "rainy",
    55: "rainy",
    56: "rainy",
    57: "rainy",
    61: "rainy",
    63: "rainy",
    65: "pouring",
    66: "snowy-rainy",
    67: "snowy-rainy",
    71: "snowy",
    73: "snowy",
    75: "snowy",
    77: "snowy",
    80: "rainy",
    81: "rainy",
    82: "pouring",
    85: "snowy-rainy",
    86: "snowy-rainy",
    95: "lightning-rainy",
    96: "lightning-rainy",
    99: "lightning-rainy",
}

# Starting grid / qualifying PDF – tried in order until one succeeds
GRID_PDF_URL_TEMPLATES = [
    "{base}/{year}/{round:02d}%20IDM/IDM%20Startaufstellung%20IDM_{cls}.pdf",
    "{base}/{year}/{round:02d}%20IDM/IDM%20Zeittraining%20IDM_{cls}.pdf",
    "{base}/{year}/{round:02d}%20IDM/IDM%20Superpole%20IDM_{cls}.pdf",
]
GRID_PDF_BASE_URL = "https://results.bike-promotion.com/Results"

# ISO 3166-1 alpha-2 → flag emoji
NATION_FLAGS: dict[str, str] = {
    "DE": "🇩🇪",
    "AT": "🇦🇹",
    "CZ": "🇨🇿",
    "NL": "🇳🇱",
    "ES": "🇪🇸",
    "IT": "🇮🇹",
    "FR": "🇫🇷",
    "GB": "🇬🇧",
    "CH": "🇨🇭",
    "BE": "🇧🇪",
    "PT": "🇵🇹",
    "PL": "🇵🇱",
    "HU": "🇭🇺",
    "SK": "🇸🇰",
    "SE": "🇸🇪",
    "FI": "🇫🇮",
    "DK": "🇩🇰",
    "NO": "🇳🇴",
    "RO": "🇷🇴",
    "TR": "🇹🇷",
    "UA": "🇺🇦",
    "SL": "🇸🇮",
    "SI": "🇸🇮",
    "HR": "🇭🇷",
    "GR": "🇬🇷",
    "ZA": "🇿🇦",
    "AU": "🇦🇺",
    "JP": "🇯🇵",
    "US": "🇺🇸",
    "BR": "🇧🇷",
    "AR": "🇦🇷",
}

# How many driver position sensors to create per class (P1 … P_DRIVER_SENSOR_COUNT)
DRIVER_SENSOR_COUNT = 10

# Browser-like headers to avoid 403 on WordPress sites
SCRAPER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}
