"""Roster continuity: how much of last season's team is still on the roster.

For each team-game, the share of the team's previous-season offensive (and defensive) snaps
taken by players on this week's roster. Teams that lost a lot of snaps over the offseason tend
to be worse than last year's ratings say early in the season; ratings catch up by midseason,
so the model uses these only through the early-season weight in features.py.

As-of kickoff: last season's snaps are fully known, and the weekly roster is set before the
game. Players are matched by name within the team (nflverse rosters often lack pfr ids; every
2026 offensive lineman does), which is why this uses name_key rather than ids.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .availability import name_key

ON_ROSTER = {"ACT", "ACTIVE", "A01", "INA"}   # active or game-day inactive; not IR, PUP or practice squad


def compute_continuity(snaps: pd.DataFrame | None, rosters: pd.DataFrame | None,
                       games: pd.DataFrame) -> pd.DataFrame:
    """games needs game_id, season, week, home_team, away_team.
    Returns one row per (game_id, team) with off_cont and def_cont in 0-1 (NaN when unknown)."""
    base = pd.concat([games[["game_id", "season", "week", "home_team"]].rename(columns={"home_team": "team"}),
                      games[["game_id", "season", "week", "away_team"]].rename(columns={"away_team": "team"})],
                     ignore_index=True)
    base["off_cont"] = np.nan
    base["def_cont"] = np.nan
    need_s, need_r = {"season", "team", "player", "offense_snaps", "defense_snaps"}, {"season", "week", "team", "full_name", "status"}
    if (snaps is None or snaps.empty or rosters is None or rosters.empty
            or not need_s <= set(snaps.columns) or not need_r <= set(rosters.columns)):
        return base[["game_id", "team", "off_cont", "def_cont"]]

    s = snaps[snaps["game_type"].fillna("REG").eq("REG")] if "game_type" in snaps.columns else snaps
    s = s.assign(nk=s["player"].map(name_key))
    prev = (s.groupby(["season", "team", "nk"], as_index=False)
             .agg(off=("offense_snaps", "sum"), dfn=("defense_snaps", "sum")))
    prev["season"] = prev["season"] + 1            # last season's snaps, keyed by the season they inform
    tot = prev.groupby(["season", "team"])[["off", "dfn"]].sum()

    r = rosters[rosters["status"].astype(str).str.upper().isin(ON_ROSTER)]
    r = r.dropna(subset=["season", "week", "team"]).assign(nk=r["full_name"].map(name_key))
    members = {k: set(g["nk"]) for k, g in r.groupby(["season", "week", "team"])}
    weeks_by = {}
    for (se, wk, tm) in members:
        weeks_by.setdefault((se, tm), []).append(wk)
    for k in weeks_by:
        weeks_by[k].sort()
    prev_by = {k: g for k, g in prev.groupby(["season", "team"])}

    off_c, def_c = [], []
    for se, wk, tm in base[["season", "week", "team"]].itertuples(index=False):
        wks = [w for w in weeks_by.get((se, tm), []) if w <= wk]
        pv = prev_by.get((se, tm))
        if not wks or pv is None or (se, tm) not in tot.index:
            off_c.append(np.nan); def_c.append(np.nan)
            continue
        mem = members[(se, max(wks), tm)]
        on = pv["nk"].isin(mem).to_numpy()
        t_off, t_def = tot.loc[(se, tm)]
        off_c.append(float(pv["off"].to_numpy()[on].sum() / t_off) if t_off > 0 else np.nan)
        def_c.append(float(pv["dfn"].to_numpy()[on].sum() / t_def) if t_def > 0 else np.nan)
    base["off_cont"], base["def_cont"] = off_c, def_c
    return base[["game_id", "team", "off_cont", "def_cont"]]
