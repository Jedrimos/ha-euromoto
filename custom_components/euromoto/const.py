"""Constants for the EURO MOTO / IDM integration."""

DOMAIN = "euromoto"
CONF_CLASSES = "classes"

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
    "Most": "CZ",
}

TICKETS_URL = "https://tickets.euromoto.racing/"
LIVESTREAM_URL = f"{BASE_URL}/live/"
LIVETIMING_URL = "http://livetiming.bike-promotion.com/#/channel/c1"

UPDATE_INTERVAL_NORMAL_HOURS = 6
UPDATE_INTERVAL_RACE_MINUTES = 30

# Favorite rider config key
CONF_FAVORITE_RIDER = "favorite_rider_number"

# Known track GPS coordinates (lat, lon) for weather lookup
TRACK_COORDINATES: dict[str, tuple[float, float]] = {
    "sachsenring":   (50.7914, 12.6872),
    "bruenn":        (49.2019, 16.7292),
    "most":          (50.5233, 13.6369),
    "oschersleben":  (52.0278, 11.2858),
    "assen":         (52.9628,  6.5239),
    "nuerburgring":  (50.3356,  6.9475),
    "hockenheim":    (49.3278,  8.5656),
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
