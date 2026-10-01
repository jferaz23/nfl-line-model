"""ESPN's public JSON feeds (site.api.espn.com): same-day injury reports and the scoreboard.

- Injuries: nflverse's injury data follows the league's Wednesday-Friday reports with a lag;
  ESPN's page updates through the week (including players cleared to play), so the weekly run
  lays it over nflverse for the target week.
- Scoreboard: kickoff, status, live score, and the DraftKings line ESPN shows (current and open).
  The line watch logs it every run for line history and grading. DraftKings prices used for
  betting decisions still come from The Odds API (odds.py); ESPN's line is a free, frequent
  second source for movement and closing lines.

Every call fails soft: callers get an empty frame plus a note.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import pandas as pd

from .venues import norm_team

log = logging.getLogger("nflmodel")
BASE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
HEADERS = {"Accept": "application/json"}   # requests' default user agent; ESPN blocks browser-like ones
STATUS = {"ACTIVE": "ACTIVE", "QUESTIONABLE": "QUESTIONABLE", "DOUBTFUL": "DOUBTFUL", "OUT": "OUT",
          "INJURED RESERVE": "IR", "PHYSICALLY UNABLE TO PERFORM": "PUP", "SUSPENSION": "SUSPENDED",
          "SUSPENDED": "SUSPENDED", "DAY-TO-DAY": "QUESTIONABLE", "PROBABLE": "PROBABLE"}


def _get(path: str, params: dict | None = None, tries: int = 3) -> dict:
    import requests
    for attempt in range(tries):
        try:
            r = requests.get(f"{BASE}/{path}", params=params or {}, timeout=30, headers=HEADERS)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == tries - 1:
                raise
            time.sleep(4 * (attempt + 1))
    return {}


def injuries(season: int, week: int) -> tuple[pd.DataFrame, list[str]]:
    """ESPN's current injury list, labeled with the target season/week, in nflverse's columns."""
    try:
        d = _get("injuries")
    except Exception as e:
        return pd.DataFrame(), [f"ESPN injury page unavailable ({e}); using nflverse's report only."]
    rows = []
    for team in d.get("injuries", []):
        for i in team.get("injuries", []):
            a = i.get("athlete", {})
            st = STATUS.get(str(i.get("status", "")).strip().upper())
            if not st:
                continue
            rows.append(dict(season=season, week=week, team=norm_team(a.get("team", {}).get("abbreviation")),
                             gsis_id=None, espn_id=str(a.get("id", "")) or None, full_name=a.get("displayName"),
                             position=(a.get("position") or {}).get("abbreviation"), report_status=st,
                             practice_status=None, report_primary_injury=(i.get("details") or {}).get("type"),
                             game_type="REG", espn_date=i.get("date"), espn_comment=i.get("shortComment")))
    df = pd.DataFrame(rows)
    return df, ([f"ESPN injury page: {len(df)} listings ({(df['report_status'] != 'ACTIVE').sum()} not fully active)."]
                if len(df) else ["ESPN injury page returned no listings."])


def align_names(espn: pd.DataFrame, rosters: pd.DataFrame | None) -> pd.DataFrame:
    """ESPN sometimes lists a player by nickname ("Hollywood Brown" for Marquise Brown). Where ESPN's name is
    not on the team's roster but exactly one rostered player on that team shares the last name and position
    group, use the roster's name so the injury status reaches the model."""
    if espn is None or espn.empty or rosters is None or rosters.empty:
        return espn
    from .availability import POS_GROUP, name_key
    r = rosters.dropna(subset=["team", "full_name"])
    r = r[r["season"] == r["season"].max()]
    r = r[r["week"] == r["week"].max()]
    have = set(zip(r["team"], r["full_name"].map(name_key)))
    by_last = {}
    for t_, n, pos in zip(r["team"], r["full_name"], r["position"]):
        k = name_key(n).split()
        if k:
            by_last.setdefault((t_, k[-1]), []).append((n, POS_GROUP.get(str(pos).upper(), str(pos).upper())))
    out = espn.copy()
    for i, row in out.iterrows():
        k = name_key(row["full_name"])
        if (row["team"], k) in have or not k:
            continue
        grp = POS_GROUP.get(str(row["position"]).upper(), str(row["position"]).upper())
        cands = [n for n, g in by_last.get((row["team"], k.split()[-1]), []) if g == grp]
        if len(set(cands)) == 1:
            out.loc[i, "espn_name"] = row["full_name"]
            out.loc[i, "full_name"] = cands[0]
    return out


def merge_injuries(nflverse: pd.DataFrame, espn: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
    """For the target week, ESPN's newer status wins wherever both list the same player."""
    if espn is None or espn.empty:
        return nflverse
    from .availability import name_key
    if nflverse is None or nflverse.empty:
        return espn.copy()
    cur = (nflverse["season"] == season) & (nflverse["week"] == week)
    ek = set(zip(espn["team"], espn["full_name"].map(name_key)))
    nk = list(zip(nflverse["team"], nflverse["full_name"].map(name_key)))
    drop = cur.to_numpy() & pd.Series([k in ek for k in nk], index=nflverse.index).to_numpy()
    # ESPN has no practice participation: keep nflverse's last practice for the same player this week, but only
    # from the final report (official game status set); midweek practice is a weaker signal than the
    # final-report rates in config.questionable_by_practice
    espn = espn.copy()
    if "practice_status" in nflverse.columns:
        rs = nflverse["report_status"] if "report_status" in nflverse.columns else pd.Series([None] * len(nflverse))
        prac = {k: v for k, v, c, s in zip(nk, nflverse["practice_status"], cur, rs)
                if c and isinstance(v, str) and v.strip() and isinstance(s, str) and s.strip()}
        keys = list(zip(espn["team"], espn["full_name"].map(name_key)))
        espn["practice_status"] = [prac.get(k, p) for k, p in zip(keys, espn.get("practice_status", [None] * len(espn)))]
    return pd.concat([nflverse[~drop], espn], ignore_index=True)


def scoreboard(season: int | None = None, week: int | None = None, seasontype: int = 2) -> pd.DataFrame:
    """One row per game: ids, kickoff, status, score, and ESPN's DraftKings line (home view).
    With no season/week, ESPN's current week."""
    d = _get("scoreboard", {"seasontype": seasontype, "week": week, "dates": season} if week else {})
    season = season or (d.get("season") or {}).get("year")
    week = week or (d.get("week") or {}).get("number")
    seasontype = (d.get("season") or {}).get("type", seasontype)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for ev in d.get("events", []):
        c = (ev.get("competitions") or [{}])[0]
        comp = {x.get("homeAway"): x for x in c.get("competitors", [])}
        h, a = comp.get("home", {}), comp.get("away", {})
        st = (ev.get("status") or {}).get("type", {})
        o = (c.get("odds") or [{}])[0]
        spread = o.get("spread")                       # ESPN: points the home team gives (negative = home favored)
        ml = o.get("moneyline") or {}
        pts = o.get("pointSpread") or {}
        tot = o.get("total") or {}

        def odd(block, side, when):
            try:
                v = block[side][when]["odds"]
                return float(str(v).replace("+", "")) if v not in (None, "", "OFF", "EVEN") else (100.0 if v == "EVEN" else None)
            except (KeyError, TypeError, ValueError):
                return None

        def line(block, side, when):
            try:
                v = block[side][when]["line"]
                return float(str(v).replace("+", "").replace("o", "").replace("u", ""))
            except (KeyError, TypeError, ValueError):
                return None

        rows.append(dict(
            ts=now, espn_id=ev.get("id"), kickoff_utc=ev.get("date"), season=season, week=week,
            season_type=seasontype,
            home_team=norm_team(h.get("team", {}).get("abbreviation")),
            away_team=norm_team(a.get("team", {}).get("abbreviation")),
            state=st.get("state"), completed=bool(st.get("completed")), detail=st.get("shortDetail"),
            period=(ev.get("status") or {}).get("period"), clock=(ev.get("status") or {}).get("displayClock"),
            home_score=pd.to_numeric(h.get("score"), errors="coerce"),
            away_score=pd.to_numeric(a.get("score"), errors="coerce"),
            provider=(o.get("provider") or {}).get("name"),
            home_spread=float(spread) if spread is not None else None,
            total=pd.to_numeric(o.get("overUnder"), errors="coerce"),
            home_spread_open=line(pts, "home", "open"), total_open=line(tot, "over", "open"),
            home_spread_price=odd(pts, "home", "close"), away_spread_price=odd(pts, "away", "close"),
            over_price=odd(tot, "over", "close"), under_price=odd(tot, "under", "close"),
            home_ml=odd(ml, "home", "close"), away_ml=odd(ml, "away", "close"),
            home_ml_open=odd(ml, "home", "open"), away_ml_open=odd(ml, "away", "open"),
            broadcast=", ".join(b for x in c.get("broadcasts", []) for b in x.get("names", [])),
            venue=(c.get("venue") or {}).get("fullName"),
        ))
    return pd.DataFrame(rows)
