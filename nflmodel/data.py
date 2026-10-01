"""Load and cache nflverse data.

Order of attempts for each dataset: local cache -> nflreadpy -> direct download
from the nflverse GitHub releases. Past seasons are cached permanently; the
current season is refreshed when the cache is older than
cfg.current_season_cache_hours (or when --refresh is passed).
"""
from __future__ import annotations

import io
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .venues import norm_team

log = logging.getLogger("nflmodel")

URLS = {
    "schedules": [
        "https://github.com/nflverse/nfldata/raw/master/data/games.csv",
        "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv",
    ],
    "pbp": "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.parquet",
    "snap_counts": "https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{season}.parquet",
    "injuries": "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.parquet",
    "rosters_weekly": "https://github.com/nflverse/nflverse-data/releases/download/weekly_rosters/roster_weekly_{season}.parquet",
}

NFLREADPY_FUNCS = {
    "pbp": "load_pbp", "snap_counts": "load_snap_counts",
    "injuries": "load_injuries", "rosters_weekly": "load_rosters_weekly",
}

PBP_COLUMNS = [
    "play_id", "game_id", "season", "week", "season_type", "posteam", "defteam", "home_team",
    "away_team", "play_type", "pass", "rush", "qb_dropback", "qb_scramble", "epa", "qb_epa",
    "success", "xpass", "no_huddle", "shotgun", "passer_id", "passer", "passer_player_id",
    "passer_player_name", "rusher_id", "rusher", "rusher_player_id", "rusher_player_name",
    "down", "ydstogo", "yardline_100", "penalty", "weather", "game_seconds_remaining",
    # turnovers, pass-rush and special teams (luck-regression and special-teams features)
    "interception", "fumble", "fumble_lost", "sack", "qb_hit", "special_teams_play", "touchdown", "cpoe",
    # win probability (for weighted EPA) and third-down outcomes (for third-down luck)
    "wp", "third_down_converted", "third_down_failed",
    "drive",                          # drive number (points per drive, drives per game)
]

SCHEDULE_COLUMNS = [
    "game_id", "season", "game_type", "week", "gameday", "weekday", "gametime", "away_team",
    "away_score", "home_team", "home_score", "location", "result", "total", "overtime",
    "away_rest", "home_rest", "away_moneyline", "home_moneyline", "spread_line",
    "away_spread_odds", "home_spread_odds", "total_line", "under_odds", "over_odds", "div_game",
    "roof", "surface", "temp", "wind", "away_qb_id", "home_qb_id", "away_qb_name", "home_qb_name",
    "away_coach", "home_coach", "referee", "stadium_id", "stadium",
]


class DataUnavailable(RuntimeError):
    pass


def _nflreadpy():
    try:
        import nflreadpy  # noqa: F401
        return nflreadpy
    except Exception:
        return None


def _to_pandas(obj):
    if obj is None:
        return None
    if hasattr(obj, "to_pandas"):
        return obj.to_pandas()
    return pd.DataFrame(obj)


def _download(url: str, timeout: int = 180) -> bytes:
    import requests
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.content


class DataStore:
    def __init__(self, cfg, refresh: bool = False, current_season: int | None = None):
        self.cfg = cfg
        self.refresh = refresh
        self.cache = Path(cfg.cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.current_season = current_season
        self.notes: list[str] = []

    # ---------------- caching ----------------
    def _fresh(self, path: Path, season: int | None) -> bool:
        if not path.exists():
            return False
        is_current = season is None or self.current_season is None or season >= self.current_season
        if not is_current:
            return True
        if self.refresh:
            return False
        age_h = (time.time() - path.stat().st_mtime) / 3600
        return age_h < self.cfg.current_season_cache_hours

    def _cached(self, name: str, season: int | None, loader, required: bool = True) -> pd.DataFrame:
        path = self.cache / (f"{name}_{season}.pkl" if season is not None else f"{name}.pkl")
        if self._fresh(path, season):
            return pd.read_pickle(path)
        try:
            df = loader()
        except Exception as e:  # network or source problem
            if path.exists():
                log.warning("Could not refresh %s (%s); using cached copy.", path.name, e)
                return pd.read_pickle(path)
            msg = f"{name}{f' {season}' if season is not None else ''} unavailable: {e}"
            if required:
                raise DataUnavailable(msg) from e
            log.warning("%s -- continuing without it.", msg)
            self.notes.append(msg)
            return pd.DataFrame()
        if df is None:
            df = pd.DataFrame()
        df.to_pickle(path)
        return df

    def _season_loader(self, name: str, season: int, columns=None):
        def load():
            nfl = _nflreadpy()
            df = None
            if nfl is not None and name in NFLREADPY_FUNCS:
                try:
                    df = _to_pandas(getattr(nfl, NFLREADPY_FUNCS[name])(seasons=[season]))
                except Exception as e:
                    log.info("nflreadpy %s(%s) failed (%s); trying direct download.",
                             NFLREADPY_FUNCS[name], season, e)
                    df = None
            if df is None or df.empty:
                df = pd.read_parquet(io.BytesIO(_download(URLS[name].format(season=season))))
            if columns is not None:
                df = df[[c for c in columns if c in df.columns]].copy()
            return df
        return load

    # ---------------- datasets ----------------
    def schedules(self) -> pd.DataFrame:
        def load():
            nfl = _nflreadpy()
            if nfl is not None:
                try:
                    return _to_pandas(nfl.load_schedules())
                except Exception as e:
                    log.info("nflreadpy load_schedules failed (%s); trying direct download.", e)
            last = None
            for url in URLS["schedules"]:
                try:
                    return pd.read_csv(io.BytesIO(_download(url)), low_memory=False)
                except Exception as e:
                    last = e
            raise last
        return clean_schedules(self._cached("schedules", None, load))

    def pbp(self, seasons) -> pd.DataFrame:
        frames = []
        for s in seasons:
            required = self.current_season is None or s < self.current_season
            frames.append(self._cached("pbp", s, self._season_loader("pbp", s, PBP_COLUMNS), required))
        return clean_pbp(_concat(frames))

    def snap_counts(self, seasons) -> pd.DataFrame:
        frames = [self._cached("snap_counts", s, self._season_loader("snap_counts", s), False) for s in seasons]
        return clean_snaps(_concat(frames))

    def injuries(self, seasons) -> pd.DataFrame:
        frames = [self._cached("injuries", s, self._season_loader("injuries", s), False) for s in seasons]
        return clean_injuries(_concat(frames))

    def rosters_weekly(self, seasons) -> pd.DataFrame:
        cols = ["season", "week", "team", "gsis_id", "pfr_id", "full_name", "position", "status",
                "status_description_abbr"]
        frames = [self._cached("rosters_weekly", s, self._season_loader("rosters_weekly", s, cols), False)
                  for s in seasons]
        return clean_rosters(_concat(frames))


def _concat(frames) -> pd.DataFrame:
    frames = [f for f in frames if f is not None and len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _num(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _obj(df, cols):
    for c in cols:
        if c not in df.columns:
            df[c] = np.nan
        df[c] = df[c].astype("object")
    return df


# ---------------- cleaning ----------------
def clean_schedules(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in SCHEDULE_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    _num(df, ["season", "week", "away_score", "home_score", "result", "total", "overtime",
              "away_rest", "home_rest", "away_moneyline", "home_moneyline", "spread_line",
              "away_spread_odds", "home_spread_odds", "total_line", "under_odds", "over_odds",
              "div_game", "temp", "wind"])
    _obj(df, ["game_id", "game_type", "gameday", "weekday", "gametime", "location", "roof", "surface",
              "away_qb_id", "home_qb_id", "away_qb_name", "home_qb_name", "away_coach", "home_coach",
              "referee", "stadium_id", "stadium"])
    df["home_team"] = df["home_team"].map(norm_team)
    df["away_team"] = df["away_team"].map(norm_team)
    scored = df["home_score"].notna() & df["away_score"].notna()
    df.loc[scored & df["result"].isna(), "result"] = df["home_score"] - df["away_score"]
    df.loc[scored & df["total"].isna(), "total"] = df["home_score"] + df["away_score"]
    df.loc[~scored, ["result", "total"]] = np.nan
    df["roof"] = df["roof"].map(lambda x: x.lower() if isinstance(x, str) else x)
    df["surface"] = df["surface"].map(lambda x: x.lower() if isinstance(x, str) else x)
    df["location"] = df["location"].map(lambda x: x if isinstance(x, str) else "Home")
    df["game_type"] = df["game_type"].map(lambda x: x if isinstance(x, str) else "REG")
    df = df[df["season"].notna() & df["week"].notna()].copy()
    df["season"] = df["season"].astype(int)
    df["week"] = df["week"].astype(int)
    # Safety check on the spread sign convention (positive = home favored).
    done = df.dropna(subset=["result", "spread_line"])
    if len(done) > 200 and np.corrcoef(done["result"], done["spread_line"])[0, 1] < 0:
        log.warning("spread_line looks away-perspective; flipping sign to home-perspective.")
        df["spread_line"] = -df["spread_line"]
    return df.sort_values(["season", "week", "gameday", "gametime", "game_id"]).reset_index(drop=True)


def clean_pbp(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    for c in PBP_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    for c in ["posteam", "defteam", "home_team", "away_team"]:
        df[c] = df[c].map(norm_team)
    _num(df, ["season", "week", "pass", "rush", "qb_dropback", "qb_scramble", "epa", "qb_epa",
              "success", "xpass", "no_huddle", "shotgun", "down", "ydstogo", "yardline_100",
              "penalty", "game_seconds_remaining", "play_id"])
    _obj(df, ["play_type", "passer_id", "passer", "passer_player_id", "passer_player_name",
              "rusher_id", "rusher", "rusher_player_id", "rusher_player_name", "weather", "game_id"])
    return df


def fix_snap_teams(snaps: pd.DataFrame, pbp: pd.DataFrame, rosters: pd.DataFrame) -> pd.DataFrame:
    """Swap the team labels in games where the source lists each side's snap rows under the other team.

    Seen in nflverse snap counts for the 2014, 2015 and 2018 Super Bowls. A game is swapped when, of the
    passers and rushers in its play-by-play (gsis ids linked to snap-count pfr ids through weekly rosters),
    at least 5 are found in the snap rows and more than 80% of them sit under the opponent."""
    if snaps is None or snaps.empty or pbp is None or pbp.empty or rosters is None or rosters.empty:
        return snaps
    g2p = rosters.dropna(subset=["gsis_id", "pfr_id"]).drop_duplicates("gsis_id").set_index("gsis_id")["pfr_id"]
    parts = [pbp[["game_id", "posteam", c]].rename(columns={c: "gsis"}) for c in ("passer_player_id", "rusher_player_id")
             if c in pbp.columns]
    pl = pd.concat(parts, ignore_index=True).dropna().drop_duplicates()
    pl["pfr"] = pl["gsis"].map(g2p)
    pl = pl.dropna(subset=["pfr"])
    st = snaps[["game_id", "pfr_player_id", "team"]].dropna().drop_duplicates(["game_id", "pfr_player_id"])
    m = pl.merge(st, left_on=["game_id", "pfr"], right_on=["game_id", "pfr_player_id"], how="inner")
    if m.empty:
        return snaps
    m["other"] = m["team"] != m["posteam"]
    s = m.groupby("game_id")["other"].agg(["mean", "size"])
    bad = set(s.index[(s["size"] >= 5) & (s["mean"] > 0.8)])
    if not bad:
        return snaps
    out = snaps.copy()
    rows = out["game_id"].isin(bad)
    out.loc[rows, ["team", "opponent"]] = out.loc[rows, ["opponent", "team"]].to_numpy()
    log.info("Snap counts: swapped team labels in %s (source lists each side under the other team).", sorted(bad))
    return out


def clean_snaps(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    for c in ["game_id", "season", "week", "player", "pfr_player_id", "position", "team", "opponent",
              "offense_snaps", "offense_pct", "defense_snaps", "defense_pct"]:
        if c not in df.columns:
            df[c] = np.nan
    df["team"] = df["team"].map(norm_team)
    df["opponent"] = df["opponent"].map(norm_team)
    _num(df, ["season", "week", "offense_snaps", "offense_pct", "defense_snaps", "defense_pct"])
    for c in ["offense_pct", "defense_pct"]:
        if df[c].max(skipna=True) > 1.5:  # stored as 0-100
            df[c] = df[c] / 100.0
    _obj(df, ["game_id", "player", "pfr_player_id", "position"])
    return df


def clean_injuries(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    for c in ["season", "week", "team", "gsis_id", "full_name", "position", "report_status",
              "practice_status", "report_primary_injury", "game_type"]:
        if c not in df.columns:
            df[c] = np.nan
    df["team"] = df["team"].map(norm_team)
    _num(df, ["season", "week"])
    df["report_status"] = df["report_status"].map(lambda x: x.strip().upper() if isinstance(x, str) else np.nan)
    _obj(df, ["gsis_id", "full_name", "position", "practice_status", "report_primary_injury"])
    return df


def clean_rosters(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    for c in ["season", "week", "team", "gsis_id", "pfr_id", "full_name", "position", "status"]:
        if c not in df.columns:
            df[c] = np.nan
    df["team"] = df["team"].map(norm_team)
    _num(df, ["season", "week"])
    df["status"] = df["status"].map(lambda x: x.strip().upper() if isinstance(x, str) else np.nan)
    _obj(df, ["gsis_id", "pfr_id", "full_name", "position"])
    return df
