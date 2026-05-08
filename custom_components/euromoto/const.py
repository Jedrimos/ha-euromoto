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
