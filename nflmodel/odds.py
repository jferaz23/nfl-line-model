"""Live odds from The Odds API (v4), or a manual CSV if you don't use the API.

One call costs 3 credits per group of up to 10 bookmakers (spreads, totals and
moneylines). The default list (DraftKings, five sharp books and seven other US
apps) is 13 books = 6 credits a call; the free plan's 500 covers ~80 runs a month. Every raw response is saved
to artifacts/odds_snapshots/ so you can later measure closing-line value.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .venues import norm_team, team_from_name

log = logging.getLogger("nflmodel")

API_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"
WIDE_COLS = ["home_spread", "home_spread_price", "away_spread", "away_spread_price", "total",
             "over_price", "under_price", "home_ml", "away_ml"]


def fetch_odds(cfg, api_key: str | None = None):
    import requests
    key = api_key or os.environ.get(cfg.odds_api_key_env)
    if not key:
        raise RuntimeError(f"No Odds API key. Set the {cfg.odds_api_key_env} environment variable "
                           "(free key at the-odds-api.com), or pass --lines-file / --no-odds.")
    books = list(dict.fromkeys([cfg.target_book] + list(cfg.sharp_books) + list(cfg.extra_books)))[:20]
    params = {"apiKey": key, "markets": "h2h,spreads,totals", "oddsFormat": "american",
              "bookmakers": ",".join(books)}
    r = requests.get(API_URL, params=params, timeout=30)
    if r.status_code == 401:
        raise RuntimeError("The Odds API rejected the key (401). Check ODDS_API_KEY.")
    if r.status_code == 429:
        raise RuntimeError("The Odds API quota exhausted or rate-limited (429).")
    r.raise_for_status()
    meta = {h: r.headers.get(h) for h in ("x-requests-remaining", "x-requests-used", "x-requests-last")}
    return r.json(), meta


def save_snapshot(events, cfg, tag="") -> Path:
    d = cfg.path("artifacts_dir") / "odds_snapshots"
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    p = d / f"odds_{ts}{('_' + tag) if tag else ''}.json"
    p.write_text(json.dumps(events))
    return p


def parse_events(events) -> pd.DataFrame:
    """Odds API JSON -> one row per (event, book) with home/away spread, total and moneyline."""
    rows = []
    for ev in events or []:
        home, away = team_from_name(ev.get("home_team")), team_from_name(ev.get("away_team"))
        if not home or not away:
            log.warning("Unrecognised team names in odds feed: %s vs %s", ev.get("away_team"), ev.get("home_team"))
            continue
        for bk in ev.get("bookmakers", []):
            row = {"event_id": ev.get("id"), "commence_time": ev.get("commence_time"), "home_team": home,
                   "away_team": away, "book": bk.get("key"), "last_update": bk.get("last_update")}
            for mk in bk.get("markets", []):
                key = mk.get("key")
                for o in mk.get("outcomes", []):
                    name, price, point = o.get("name"), o.get("price"), o.get("point")
                    tm = team_from_name(name) if name not in ("Over", "Under") else None
                    if key == "spreads" and tm in (home, away):
                        side = "home" if tm == home else "away"
                        row[f"{side}_spread"], row[f"{side}_spread_price"] = point, price
                    elif key == "totals" and name in ("Over", "Under"):
                        row["total"] = point
                        row["over_price" if name == "Over" else "under_price"] = price
                    elif key == "h2h" and tm in (home, away):
                        row["home_ml" if tm == home else "away_ml"] = price
            rows.append(row)
    df = pd.DataFrame(rows)
    for c in WIDE_COLS:
        if c not in df.columns:
            df[c] = np.nan
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def load_manual_lines(path) -> pd.DataFrame:
    """CSV with columns: home_team, away_team, book, home_spread, home_spread_price,
    away_spread_price, total, over_price, under_price, home_ml, away_ml
    (away_spread is optional; it defaults to -home_spread)."""
    df = pd.read_csv(path, comment="#")
    df.columns = [c.strip().lower() for c in df.columns]
    for c in WIDE_COLS:
        if c not in df.columns:
            df[c] = np.nan
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["away_spread"] = df["away_spread"].where(df["away_spread"].notna(), -df["home_spread"])
    df["home_team"] = df["home_team"].map(lambda x: team_from_name(x) or norm_team(x))
    df["away_team"] = df["away_team"].map(lambda x: team_from_name(x) or norm_team(x))
    df["book"] = df["book"].astype(str).str.strip().str.lower()
    df["commence_time"] = None
    return df


def match_games(odds: pd.DataFrame, target: pd.DataFrame) -> pd.DataFrame:
    """Attach game_id by teams (either orientation for neutral sites) and kickoff within 36h."""
    if odds is None or odds.empty or target.empty:
        return pd.DataFrame(columns=["game_id", "book"] + WIDE_COLS)
    out = []
    for g in target.itertuples(index=False):
        ko = pd.to_datetime(g.kickoff_utc, utc=True) if isinstance(g.kickoff_utc, str) and g.kickoff_utc else None
        same = odds[(odds["home_team"] == g.home_team) & (odds["away_team"] == g.away_team)].copy()
        flipped = odds[(odds["home_team"] == g.away_team) & (odds["away_team"] == g.home_team)].copy()
        if not flipped.empty:  # feed lists the teams the other way round (neutral site)
            f = flipped.copy()
            f["home_team"], f["away_team"] = g.home_team, g.away_team
            f["home_spread"], f["away_spread"] = flipped["away_spread"], flipped["home_spread"]
            f["home_spread_price"], f["away_spread_price"] = flipped["away_spread_price"], flipped["home_spread_price"]
            f["home_ml"], f["away_ml"] = flipped["away_ml"], flipped["home_ml"]
            same = pd.concat([same, f], ignore_index=True)
        if ko is not None and "commence_time" in same and same["commence_time"].notna().any():
            ct = pd.to_datetime(same["commence_time"], utc=True, errors="coerce")
            same = same[ct.isna() | ((ct - ko).abs() <= timedelta(hours=36))]
        if len(same):
            same = same.copy()
            same["game_id"] = g.game_id
            out.append(same)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["game_id", "book"] + WIDE_COLS)


def get_week_odds(cfg, target: pd.DataFrame, lines_file=None, no_odds=False, events=None):
    """Returns (odds matched to target games, notes)."""
    notes = []
    if no_odds:
        return match_games(pd.DataFrame(), target), ["Odds skipped (--no-odds): model lines only."]
    if lines_file:
        odds = load_manual_lines(lines_file)
        notes.append(f"Lines from {lines_file}.")
    else:
        if events is None:
            events, meta = fetch_odds(cfg)
            notes.append(f"Odds API credits remaining: {meta.get('x-requests-remaining')}.")
            save_snapshot(events, cfg)
        odds = parse_events(events)
    m = match_games(odds, target)
    missing = sorted(set(target["game_id"]) - set(m["game_id"]))
    if missing:
        notes.append(f"No odds found for {len(missing)} game(s): {', '.join(missing)}.")
    if len(m) and cfg.target_book not in set(m["book"]):
        notes.append(f"No {cfg.target_book} prices in the feed this run.")
    return m, notes
