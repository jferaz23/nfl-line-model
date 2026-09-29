"""Teams, stadiums, travel distance, time zones, surfaces and roofs.

Roof and surface for past games come from nflverse; the tables here are the
fallback for upcoming games and the source of coordinates / altitude / time zone.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TEAM_FULL_NAMES = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LA", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
    # historical names
    "Washington Football Team": "WAS", "Washington Redskins": "WAS",
    "Oakland Raiders": "LV", "San Diego Chargers": "LAC", "St. Louis Rams": "LA",
    "St Louis Rams": "LA",
}
ABBR_TO_NAME = {v: k for k, v in TEAM_FULL_NAMES.items() if not k.startswith(("Washington F", "Washington R", "Oakland", "San Diego", "St"))}

# Franchise continuity: ratings follow the franchise through relocations.
ALIASES = {
    "STL": "LA", "LAR": "LA", "SD": "LAC", "SDG": "LAC", "OAK": "LV", "LVR": "LV",
    "JAC": "JAX", "WSH": "WAS", "GNB": "GB", "KAN": "KC", "NWE": "NE", "NOR": "NO",
    "SFO": "SF", "TAM": "TB", "HST": "HOU", "BLT": "BAL", "CLV": "CLE", "ARZ": "ARI",
}

DIVISIONS = {
    "AFC East": ["BUF", "MIA", "NE", "NYJ"], "AFC North": ["BAL", "CIN", "CLE", "PIT"],
    "AFC South": ["HOU", "IND", "JAX", "TEN"], "AFC West": ["DEN", "KC", "LV", "LAC"],
    "NFC East": ["DAL", "NYG", "PHI", "WAS"], "NFC North": ["CHI", "DET", "GB", "MIN"],
    "NFC South": ["ATL", "CAR", "NO", "TB"], "NFC West": ["ARI", "LA", "SF", "SEA"],
}
TEAM_DIVISION = {t: d for d, ts in DIVISIONS.items() for t in ts}


def V(lat, lon, tz, alt, roof, surface, name=""):
    return dict(lat=lat, lon=lon, tz=tz, alt=alt, roof=roof, surface=surface, name=name)


# Current home stadiums. roof: outdoors / dome / retractable. surface: grass / turf.
HOME = {
    "ARI": V(33.5276, -112.2626, "America/Phoenix", 1070, "retractable", "grass", "State Farm Stadium"),
    "ATL": V(33.7554, -84.4008, "America/New_York", 1050, "retractable", "turf", "Mercedes-Benz Stadium"),
    "BAL": V(39.2780, -76.6227, "America/New_York", 30, "outdoors", "grass", "M&T Bank Stadium"),
    "BUF": V(42.7738, -78.7870, "America/New_York", 600, "outdoors", "turf", "Highmark Stadium"),
    "CAR": V(35.2258, -80.8528, "America/New_York", 750, "outdoors", "turf", "Bank of America Stadium"),
    "CHI": V(41.8623, -87.6167, "America/Chicago", 600, "outdoors", "grass", "Soldier Field"),
    "CIN": V(39.0955, -84.5161, "America/New_York", 490, "outdoors", "turf", "Paycor Stadium"),
    "CLE": V(41.5061, -81.6995, "America/New_York", 580, "outdoors", "grass", "Huntington Bank Field"),
    "DAL": V(32.7473, -97.0945, "America/Chicago", 600, "retractable", "turf", "AT&T Stadium"),
    "DEN": V(39.7439, -105.0201, "America/Denver", 5280, "outdoors", "grass", "Empower Field at Mile High"),
    "DET": V(42.3400, -83.0456, "America/Detroit", 600, "dome", "turf", "Ford Field"),
    "GB": V(44.5013, -88.0622, "America/Chicago", 640, "outdoors", "grass", "Lambeau Field"),
    "HOU": V(29.6847, -95.4107, "America/Chicago", 50, "retractable", "turf", "NRG Stadium"),
    "IND": V(39.7601, -86.1639, "America/Indiana/Indianapolis", 715, "retractable", "turf", "Lucas Oil Stadium"),
    "JAX": V(30.3239, -81.6373, "America/New_York", 20, "outdoors", "grass", "EverBank Stadium"),
    "KC": V(39.0489, -94.4839, "America/Chicago", 900, "outdoors", "grass", "GEHA Field at Arrowhead"),
    "LV": V(36.0909, -115.1833, "America/Los_Angeles", 2030, "dome", "grass", "Allegiant Stadium"),
    "LAC": V(33.9535, -118.3392, "America/Los_Angeles", 100, "dome", "turf", "SoFi Stadium"),
    "LA": V(33.9535, -118.3392, "America/Los_Angeles", 100, "dome", "turf", "SoFi Stadium"),
    "MIA": V(25.9580, -80.2389, "America/New_York", 10, "outdoors", "grass", "Hard Rock Stadium"),
    "MIN": V(44.9737, -93.2575, "America/Chicago", 830, "dome", "turf", "U.S. Bank Stadium"),
    "NE": V(42.0909, -71.2643, "America/New_York", 250, "outdoors", "turf", "Gillette Stadium"),
    "NO": V(29.9511, -90.0812, "America/Chicago", 10, "dome", "turf", "Caesars Superdome"),
    "NYG": V(40.8135, -74.0745, "America/New_York", 10, "outdoors", "turf", "MetLife Stadium"),
    "NYJ": V(40.8135, -74.0745, "America/New_York", 10, "outdoors", "turf", "MetLife Stadium"),
    "PHI": V(39.9008, -75.1675, "America/New_York", 30, "outdoors", "grass", "Lincoln Financial Field"),
    "PIT": V(40.4468, -80.0158, "America/New_York", 730, "outdoors", "grass", "Acrisure Stadium"),
    "SF": V(37.4030, -121.9700, "America/Los_Angeles", 30, "outdoors", "grass", "Levi's Stadium"),
    "SEA": V(47.5952, -122.3316, "America/Los_Angeles", 20, "outdoors", "turf", "Lumen Field"),
    "TB": V(27.9759, -82.5033, "America/New_York", 30, "outdoors", "grass", "Raymond James Stadium"),
    "TEN": V(36.1665, -86.7713, "America/Chicago", 400, "outdoors", "turf", "Nissan Stadium"),
    "WAS": V(38.9076, -76.8645, "America/New_York", 200, "outdoors", "grass", "Northwest Stadium"),
}
TEAMS = sorted(HOME)

# Relocations: (franchise, last season inclusive) -> venue used through that season.
ERA = {
    "LA": [(2015, V(38.6328, -90.1885, "America/Chicago", 460, "dome", "turf", "Edward Jones Dome")),
           (2019, V(34.0141, -118.2879, "America/Los_Angeles", 200, "outdoors", "grass", "LA Memorial Coliseum"))],
    "LAC": [(2016, V(32.7831, -117.1196, "America/Los_Angeles", 80, "outdoors", "grass", "Qualcomm Stadium")),
            (2019, V(33.8644, -118.2611, "America/Los_Angeles", 60, "outdoors", "grass", "StubHub Center"))],
    "LV": [(2019, V(37.7516, -122.2005, "America/Los_Angeles", 20, "outdoors", "grass", "Oakland Coliseum"))],
}

# International / neutral venues matched by keywords in the nflverse stadium name.
NEUTRAL_VENUES = [
    (("wembley",), V(51.5560, -0.2796, "Europe/London", 150, "outdoors", "grass", "Wembley Stadium")),
    (("tottenham",), V(51.6043, -0.0664, "Europe/London", 100, "outdoors", "turf", "Tottenham Hotspur Stadium")),
    (("twickenham",), V(51.4560, -0.3415, "Europe/London", 30, "outdoors", "grass", "Twickenham")),
    (("allianz arena", "munich"), V(48.2188, 11.6247, "Europe/Berlin", 1700, "outdoors", "grass", "Allianz Arena")),
    (("deutsche bank park", "frankfurt", "waldstadion"), V(50.0686, 8.6455, "Europe/Berlin", 360, "outdoors", "grass", "Deutsche Bank Park")),
    (("olympiastadion", "berlin"), V(52.5147, 13.2395, "Europe/Berlin", 165, "outdoors", "grass", "Olympiastadion")),
    (("azteca", "banorte", "mexico"), V(19.3029, -99.1505, "America/Mexico_City", 7350, "outdoors", "grass", "Estadio Azteca")),
    (("corinthians", "neo qu", "sao paulo", "são paulo", "arena sp"), V(-23.5453, -46.4742, "America/Sao_Paulo", 2500, "outdoors", "grass", "Arena Corinthians")),
    (("maracan", "rio de janeiro"), V(-22.9121, -43.2302, "America/Sao_Paulo", 10, "outdoors", "grass", "Maracana")),
    (("bernab", "madrid"), V(40.4531, -3.6883, "Europe/Madrid", 2150, "retractable", "grass", "Santiago Bernabeu")),
    (("croke", "dublin"), V(53.3607, -6.2512, "Europe/Dublin", 20, "outdoors", "grass", "Croke Park")),
    (("melbourne", "mcg"), V(-37.8200, 144.9834, "Australia/Melbourne", 30, "outdoors", "grass", "Melbourne Cricket Ground")),
    (("stade de france", "paris"), V(48.9245, 2.3602, "Europe/Paris", 110, "outdoors", "grass", "Stade de France")),
    (("rogers centre", "toronto"), V(43.6414, -79.3894, "America/Toronto", 270, "retractable", "turf", "Rogers Centre")),
]
# Domestic neutral-site games (Super Bowls, relocated games): stadium keyword -> team venue.
DOMESTIC_KEYWORDS = [
    (("superdome",), "NO"), (("state farm stadium", "university of phoenix"), "ARI"),
    (("allegiant",), "LV"), (("sofi",), "LA"), (("hard rock", "sun life", "dolphin"), "MIA"),
    (("mercedes-benz stadium",), "ATL"), (("levi",), "SF"), (("raymond james",), "TB"),
    (("nrg",), "HOU"), (("u.s. bank", "us bank"), "MIN"), (("lucas oil",), "IND"),
    (("metlife",), "NYG"), (("at&t",), "DAL"), (("ford field",), "DET"),
]


def norm_team(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return x
    s = str(x).strip().upper()
    return ALIASES.get(s, s)


def team_from_name(name: str) -> str | None:
    if name is None:
        return None
    if name in TEAM_FULL_NAMES:
        return TEAM_FULL_NAMES[name]
    low = name.lower()
    for full, abbr in TEAM_FULL_NAMES.items():
        if full.lower() == low or full.split()[-1].lower() == low.split()[-1]:
            return abbr
    return None


def home_venue(team: str, season: int) -> dict:
    for last_season, venue in ERA.get(team, []):
        if season <= last_season:
            return venue
    return HOME.get(team, V(39.8, -98.6, "America/Chicago", 0, "outdoors", "grass", "unknown"))


def resolve_venue(home_team: str, season: int, stadium, location) -> dict:
    name = str(stadium).lower() if isinstance(stadium, str) else ""
    for keys, venue in NEUTRAL_VENUES:
        if any(k in name for k in keys):
            return {**venue, "intl": True}
    if str(location).lower() == "neutral":
        for keys, team in DOMESTIC_KEYWORDS:
            if any(k in name for k in keys):
                return {**home_venue(team, season), "intl": False}
    return {**home_venue(home_team, season), "intl": False}


def haversine_miles(lat1, lon1, lat2, lon2) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


ET = ZoneInfo("America/New_York")


def kickoff_utc(gameday, gametime) -> datetime | None:
    """nflverse gameday is the US Eastern date and gametime is HH:MM Eastern."""
    try:
        d = str(gameday)[:10]
        t = str(gametime) if isinstance(gametime, str) and ":" in str(gametime) else "13:00"
        local = datetime.strptime(f"{d} {t[:5]}", "%Y-%m-%d %H:%M").replace(tzinfo=ET)
        return local.astimezone(timezone.utc)
    except Exception:
        return None


def utc_offset_hours(tz: str, when_utc: datetime) -> float:
    return when_utc.astimezone(ZoneInfo(tz)).utcoffset().total_seconds() / 3600


def local_hour(tz: str, when_utc: datetime) -> float:
    lt = when_utc.astimezone(ZoneInfo(tz))
    return lt.hour + lt.minute / 60


TURF_WORDS = ("turf", "astro", "a_turf", "sportturf", "fieldturf", "matrix", "artificial", "synthetic")


def is_turf(surface) -> float:
    if not isinstance(surface, str) or not surface.strip():
        return float("nan")
    s = surface.lower()
    if "grass" in s and not any(w in s for w in ("astro", "turf")):
        return 0.0
    return 1.0 if any(w in s for w in TURF_WORDS) else 0.0


def is_indoor(roof) -> float:
    if not isinstance(roof, str) or not roof.strip():
        return float("nan")
    r = roof.lower()
    if r in ("dome", "closed"):
        return 1.0
    if r == "retractable":   # upcoming game with unknown roof status: assume closed
        return 1.0
    return 0.0
