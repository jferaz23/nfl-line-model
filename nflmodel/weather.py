"""Kickoff-window weather forecasts from Open-Meteo (free, no key).

Averages the hourly forecast over kickoff -> kickoff + 3h. Domes and
retractable roofs are skipped (retractables are assumed closed for upcoming
games; if a roof will be open in bad weather, the market will know before you).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import numpy as np

from .venues import is_indoor, kickoff_utc, resolve_venue

log = logging.getLogger("nflmodel")
URL = "https://api.open-meteo.com/v1/forecast"


def _fetch(lat, lon):
    import requests
    params = {"latitude": lat, "longitude": lon,
              "hourly": "temperature_2m,precipitation,snowfall,wind_speed_10m,wind_gusts_10m",
              "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "precipitation_unit": "inch",
              "timezone": "UTC", "forecast_days": 16}
    r = requests.get(URL, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def summarize(hourly: dict, kickoff: datetime) -> dict | None:
    times = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in hourly.get("time", [])]
    idx = [i for i, t in enumerate(times) if kickoff - timedelta(minutes=30) <= t <= kickoff + timedelta(hours=3)]
    if not idx:
        return None

    def mean(k):
        v = [hourly[k][i] for i in idx if hourly.get(k) and hourly[k][i] is not None]
        return float(np.mean(v)) if v else np.nan

    def total(k):
        v = [hourly[k][i] for i in idx if hourly.get(k) and hourly[k][i] is not None]
        return float(np.sum(v)) if v else 0.0

    return {"temp_f": mean("temperature_2m"), "wind_mph": mean("wind_speed_10m"),
            "gust_mph": mean("wind_gusts_10m"), "precip_in": total("precipitation"),
            "snow_in": total("snowfall")}


def forecasts_for_games(target_sched, cfg, fetch=_fetch):
    """target_sched: schedule rows for the target games. Returns ({game_id: forecast}, notes)."""
    out, notes, failed = {}, [], []
    now = datetime.now(timezone.utc)
    for g in target_sched.itertuples(index=False):
        ven = resolve_venue(g.home_team, g.season, g.stadium, g.location)
        roof = g.roof if isinstance(g.roof, str) and g.roof else ven["roof"]
        if is_indoor(roof) >= 0.5 or is_indoor(ven["roof"]) >= 0.5:
            continue
        ko = kickoff_utc(g.gameday, g.gametime)
        if ko is None or ko - now > timedelta(days=15):
            failed.append(g.game_id)
            continue
        try:
            fc = summarize(fetch(ven["lat"], ven["lon"])["hourly"], ko)
        except Exception as e:  # network, API change
            log.warning("Forecast failed for %s: %s", g.game_id, e)
            fc = None
        if fc is None:
            failed.append(g.game_id)
        else:
            out[g.game_id] = fc
    if failed:
        notes.append(f"No weather forecast for {len(failed)} outdoor game(s) ({', '.join(failed)}); "
                     "typical conditions assumed.")
    return out, notes
