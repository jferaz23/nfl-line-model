"""Pro Football Reference (PFR) season results, read from files you save yourself.

PFR's terms of use don't allow automated downloading without written permission, so
this module never contacts the site. Instead, for each season you want:

  1. open https://www.pro-football-reference.com/years/2025/games.htm in a browser
  2. either  "Share & Export" -> "Get table as CSV (for Excel)" and paste the text into
             pfr_exports/games_2025.csv
     or      File -> Save Page As... -> pfr_exports/games_2025.html

Five seasons is five files. The pipeline then cross-checks every game's date, teams and
score against nflverse and adds PFR's yards and turnovers for each team (columns pfr_*).
"""
from __future__ import annotations

import html as htmllib
import io
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .venues import norm_team, team_from_name

log = logging.getLogger("nflmodel")

PLAYOFF_WEEKS = {"wildcard": 19, "division": 20, "divisional": 20, "confchamp": 21, "conference": 21,
                 "superbowl": 22}
STAT_ORDER = ["week_num", "game_day_of_week", "game_date", "gametime", "winner", "game_location",
              "loser", "boxscore_word", "pts_win", "pts_lose", "yards_win", "to_win", "yards_lose",
              "to_lose"]


def _team(x) -> str | None:
    x = str(x or "").strip().replace("\xa0", " ")
    if not x:
        return None
    return team_from_name(x) or norm_team(x)


def _week(x, season: int, reg_weeks: int) -> int | None:
    s = re.sub(r"[^a-z0-9]", "", str(x).lower())
    if s.isdigit():
        return int(s)
    if s in PLAYOFF_WEEKS:          # nflverse numbers playoff rounds after the last regular week
        return reg_weeks + PLAYOFF_WEEKS[s] - 18
    return None


def _date(x, season: int):
    s = str(x).strip()
    d = pd.to_datetime(s, errors="coerce")
    if pd.notna(d) and re.search(r"\d{4}", s):
        return d.normalize()
    d = pd.to_datetime(f"{s} {season}", errors="coerce")        # "September 7" style
    if pd.isna(d):
        return pd.NaT
    return (d + pd.DateOffset(years=1)) if d.month <= 3 else d


def _rows_from_html(text: str) -> list[dict]:
    m = re.search(r'<table[^>]*id="games".*?</table>', text, re.S)
    if not m:
        raise ValueError("no table with id='games' found (save the season's games.htm page)")
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(0), re.S):
        cells = dict(re.findall(r'<t[hd][^>]*data-stat="([^"]+)"[^>]*>(.*?)</t[hd]>', tr, re.S))
        if not cells:
            continue
        rows.append({k: htmllib.unescape(re.sub(r"<[^>]+>", "", v)).strip() for k, v in cells.items()})
    return rows


def _rows_from_csv(text: str) -> list[dict]:
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    start = next((i for i, ln in enumerate(lines) if ln.lower().startswith("week,")), None)
    if start is None:
        raise ValueError("no header row starting with 'Week,' (use PFR's 'Get table as CSV')")
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])), header=None, dtype=str, keep_default_na=False)
    rows = []
    for vals in df.itertuples(index=False):
        vals = list(vals)
        if str(vals[0]).lower().startswith("week"):
            continue                                       # repeated header rows
        rows.append(dict(zip(STAT_ORDER, vals + [""] * (len(STAT_ORDER) - len(vals)))))
    return rows


def parse_games_file(path: Path, season: int, reg_weeks: int = 18) -> pd.DataFrame:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    rows = _rows_from_html(text) if "<table" in text.lower() else _rows_from_csv(text)
    out = []
    for r in rows:
        wk = _week(r.get("week_num", ""), season, reg_weeks)
        win, lose = _team(r.get("winner")), _team(r.get("loser"))
        if wk is None or not win or not lose:
            continue
        pw, pl = pd.to_numeric(r.get("pts_win"), errors="coerce"), pd.to_numeric(r.get("pts_lose"), errors="coerce")
        if pd.isna(pw) or pd.isna(pl):
            continue                                       # not played yet
        loc = str(r.get("game_location", "")).strip()
        winner_away = loc == "@"
        home, away = (lose, win) if winner_away else (win, lose)
        g = dict(season=season, week=wk, gameday=_date(r.get("game_date", ""), season),
                 home_team=home, away_team=away, pfr_neutral=int(loc.upper() == "N"))
        stats = {"score": ("pts_win", "pts_lose"), "yds": ("yards_win", "yards_lose"), "to": ("to_win", "to_lose")}
        for name, (w, lo) in stats.items():
            vw, vl = pd.to_numeric(r.get(w), errors="coerce"), pd.to_numeric(r.get(lo), errors="coerce")
            g[f"pfr_home_{name}"], g[f"pfr_away_{name}"] = (vl, vw) if winner_away else (vw, vl)
        out.append(g)
    return pd.DataFrame(out)


def load_pfr_exports(folder, seasons=None, reg_weeks_by_season=None) -> tuple[pd.DataFrame, list[str]]:
    """Read every pfr_exports/games_<season>.csv|html. Returns (games, notes)."""
    folder = Path(folder)
    notes, frames = [], []
    if not folder.exists():
        return pd.DataFrame(), notes
    for p in sorted(folder.glob("games_*.*")):
        m = re.match(r"games_(\d{4})\.(csv|txt|html?|htm)$", p.name, re.I)
        if not m:
            continue
        season = int(m.group(1))
        if seasons is not None and season not in seasons:
            continue
        reg = (reg_weeks_by_season or {}).get(season, 18 if season >= 2021 else 17)
        try:
            df = parse_games_file(p, season, reg)
        except Exception as e:
            notes.append(f"PFR file {p.name} could not be read: {e}")
            continue
        if df.empty:
            notes.append(f"PFR file {p.name} had no completed games.")
            continue
        frames.append(df)
    games = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return games, notes


def cross_check(pfr: pd.DataFrame, sched: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Match PFR games to nflverse (season, week, teams; home/away swap tolerated for neutral sites).
    Returns (schedule with pfr_* columns added, notes)."""
    if pfr is None or pfr.empty:
        return sched, []
    s = sched.copy()
    key = ["season", "week", "home_team", "away_team"]
    swapped = pfr.rename(columns={"home_team": "away_team", "away_team": "home_team",
                                  "pfr_home_score": "pfr_away_score", "pfr_away_score": "pfr_home_score",
                                  "pfr_home_yds": "pfr_away_yds", "pfr_away_yds": "pfr_home_yds",
                                  "pfr_home_to": "pfr_away_to", "pfr_away_to": "pfr_home_to"})
    both = pd.concat([pfr.assign(_sw=0), swapped.assign(_sw=1)], ignore_index=True)
    both = both.drop_duplicates(subset=key, keep="first")
    cols = key + [c for c in both.columns if c.startswith("pfr_") and c != "pfr_neutral"] + ["_sw"]
    s = s.drop(columns=[c for c in s.columns if c.startswith("pfr_") and c != "pfr"], errors="ignore")
    m = s.merge(both[cols], on=key, how="left")
    seasons = sorted(pfr["season"].unique())
    in_scope = m["season"].isin(seasons) & m["result"].notna()
    matched = in_scope & m["pfr_home_score"].notna()
    bad = matched & ((m["pfr_home_score"] != m["home_score"]) | (m["pfr_away_score"] != m["away_score"]))
    notes = [f"PFR cross-check {seasons[0]}-{seasons[-1]}: {int(matched.sum())} of {int(in_scope.sum())} "
             f"completed nflverse games matched; {int(bad.sum())} score disagreements."]
    if bad.any():
        ex = m.loc[bad, ["season", "week", "away_team", "home_team", "away_score", "home_score",
                         "pfr_away_score", "pfr_home_score"]].head(5)
        notes.append("First disagreements: " + "; ".join(
            f"{r.season} wk{r.week} {r.away_team}@{r.home_team} nflverse {r.away_score:.0f}-{r.home_score:.0f} "
            f"vs PFR {r.pfr_away_score:.0f}-{r.pfr_home_score:.0f}" for r in ex.itertuples()))
    unmatched = len(pfr) - int(matched.sum())
    if unmatched > 0:
        notes.append(f"{unmatched} PFR games had no nflverse match (check team names/weeks).")
    return m.drop(columns=["_sw"]), notes
