"""Team strength, quarterback value and Elo -- all computed "as of" a week,
using only games played before that week (no look-ahead leakage)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .venues import TEAMS


def time_index(season, week):
    """Monotone game clock. 23 slots per season covers 18 regular weeks + playoffs."""
    return np.asarray(season) * 23 + np.asarray(week)


# ----------------------------------------------------------------------------
# Team-game table
# ----------------------------------------------------------------------------
def build_team_games(sched: pd.DataFrame, pbp: pd.DataFrame) -> pd.DataFrame:
    done = sched[sched["result"].notna()].copy()
    neutral = done["location"].eq("Neutral").to_numpy()
    base = dict(game_id=done["game_id"].to_numpy(), season=done["season"].to_numpy(),
                week=done["week"].to_numpy())
    home = pd.DataFrame({**base, "team": done["home_team"].to_numpy(), "opp": done["away_team"].to_numpy(),
                         "home": np.where(neutral, 0.0, 0.5), "pf": done["home_score"].to_numpy(),
                         "pa": done["away_score"].to_numpy()})
    away = pd.DataFrame({**base, "team": done["away_team"].to_numpy(), "opp": done["home_team"].to_numpy(),
                         "home": np.where(neutral, 0.0, -0.5), "pf": done["away_score"].to_numpy(),
                         "pa": done["home_score"].to_numpy()})
    tg = pd.concat([home, away], ignore_index=True)
    tg["t"] = time_index(tg["season"], tg["week"])

    stat_cols = ["plays", "pass_plays", "rush_plays", "epa_pass", "epa_rush", "sr", "proe",
                 "nohuddle", "shotgun", "wepa_o", "wepa_d", "drives", "ppd"]
    if pbp is not None and len(pbp):
        p = pbp[pbp["play_type"].isin(["pass", "run"]) & pbp["epa"].notna() & pbp["posteam"].notna()].copy()
        p["is_pass"] = ((p["pass"] == 1) | (p["qb_dropback"] == 1)).astype(float)
        p["oe"] = p["is_pass"] - p["xpass"]
        g = p.groupby(["game_id", "posteam"])
        agg = pd.DataFrame({
            "plays": g["epa"].size(),
            "pass_plays": g["is_pass"].sum(),
            "sr": g["success"].mean(),
            "proe": g["oe"].mean(),
            "nohuddle": g["no_huddle"].mean(),
            "shotgun": g["shotgun"].mean(),
        })
        agg["rush_plays"] = agg["plays"] - agg["pass_plays"]
        agg["epa_pass"] = p[p["is_pass"] == 1].groupby(["game_id", "posteam"])["epa"].mean()
        agg["epa_rush"] = p[p["is_pass"] == 0].groupby(["game_id", "posteam"])["epa"].mean()
        # Weighted EPA (after nfelo's WEPA): close-game plays count more than lopsided ones, lost
        # fumbles (recovery is a coin flip) count less, and interceptions count less for the defense
        # than for the offense, since they say more about the passer than the coverage.
        wp = pd.to_numeric(p["wp"], errors="coerce") if "wp" in p.columns else pd.Series(0.5, index=p.index)
        w = 0.35 + 0.65 * np.exp(-((wp.fillna(0.5) - 0.5) / 0.3) ** 2)
        fl = pd.to_numeric(p["fumble_lost"], errors="coerce").fillna(0) if "fumble_lost" in p.columns else 0.0
        it = pd.to_numeric(p["interception"], errors="coerce").fillna(0) if "interception" in p.columns else 0.0
        e_o = p["epa"] * np.where(fl == 1, 0.35, 1.0) * np.where(it == 1, 0.8, 1.0)
        e_d = p["epa"] * np.where(fl == 1, 0.35, 1.0) * np.where(it == 1, 0.5, 1.0)
        p = p.assign(_w=w, _wo=w * e_o, _wd=w * e_d)
        gw = p.groupby(["game_id", "posteam"])
        agg["wepa_o"] = gw["_wo"].sum() / gw["_w"].sum()
        agg["wepa_d"] = gw["_wd"].sum() / gw["_w"].sum()
        if "drive" in p.columns:
            agg["drives"] = gw["drive"].nunique()
        agg = agg.reset_index().rename(columns={"posteam": "team"})
        tg = tg.merge(agg, on=["game_id", "team"], how="left")
        if "drives" in tg.columns:
            tg["ppd"] = tg["pf"] / tg["drives"].where(tg["drives"] >= 6)
    for c in stat_cols:
        if c not in tg.columns:
            tg[c] = np.nan
    return tg.sort_values(["t", "game_id", "team"]).reset_index(drop=True)


# ----------------------------------------------------------------------------
# Opponent-adjusted, recency-weighted ridge ratings
# ----------------------------------------------------------------------------
RATING_TARGETS = [
    # (column, volume column for weighting, output prefix)
    ("pf", None, "pts"),
    ("epa_pass", "pass_plays", "pass"),
    ("epa_rush", "rush_plays", "rush"),
    ("sr", "plays", "sr"),
    ("plays", None, "pace"),
    ("proe", "plays", "proe"),
    ("nohuddle", "plays", "nh"),
    ("wepa_o", "plays", "wepao"),      # weighted EPA, offense-side weights
    ("wepa_d", "plays", "wepad"),      # weighted EPA, defense-side weights
    ("ppd", "drives", "ppd"),          # points per drive: the drive is the natural unit of offense
    ("drives", None, "drv"),           # possessions per game (pace in drives)
]


def recency_weights(t_games, seasons_games, t_now, season_now, half_life, offseason_decay):
    dt = np.maximum(t_now - np.asarray(t_games), 0)
    boundaries = season_now - np.asarray(seasons_games)
    return (0.5 ** (dt / half_life)) * (offseason_decay ** boundaries)


class RatingEngine:
    def __init__(self, team_games: pd.DataFrame, cfg):
        self.cfg = cfg
        self.tg = team_games.reset_index(drop=True)
        teams = list(TEAMS) + sorted(set(self.tg["team"]).union(self.tg["opp"]) - set(TEAMS))
        self.teams = teams
        self.idx = {t: i for i, t in enumerate(teams)}
        n, k = len(self.tg), len(teams)
        X = np.zeros((n, 2 + 2 * k))
        X[:, 0] = 1.0
        X[:, 1] = self.tg["home"].to_numpy(dtype=float)
        rows = np.arange(n)
        X[rows, 2 + self.tg["team"].map(self.idx).to_numpy()] = 1.0
        X[rows, 2 + k + self.tg["opp"].map(self.idx).to_numpy()] = 1.0
        self.X = X
        self.k = k
        self.t = self.tg["t"].to_numpy()
        self.season = self.tg["season"].to_numpy()
        self.pen = np.r_[1e-6, 1e-3, np.full(2 * k, cfg.ridge_lambda)]

    def weights_asof(self, season, week):
        t_now = int(time_index(season, week))
        m = (self.t < t_now) & (self.season >= season - self.cfg.rating_lookback_seasons)
        w = np.zeros(len(self.t))
        w[m] = recency_weights(self.t[m], self.season[m], t_now, season,
                               self.cfg.rating_half_life_weeks, self.cfg.offseason_decay)
        return m, w

    def asof(self, season, week) -> pd.DataFrame | None:
        m, w = self.weights_asof(season, week)
        if m.sum() < 40:
            return None
        out = pd.DataFrame({"team": self.teams})
        k = self.k
        for col, vol, name in RATING_TARGETS:
            y = self.tg[col].to_numpy(dtype=float)
            valid = m & np.isfinite(y)
            if valid.sum() < 40:
                out[f"off_{name}"] = 0.0
                out[f"def_{name}"] = 0.0
                out[f"lg_{name}"] = np.nan
                continue
            ww = w[valid].copy()
            if vol is not None:
                v = self.tg[vol].to_numpy(dtype=float)[valid]
                v = np.where(np.isfinite(v) & (v > 0), v, np.nanmean(v))
                ww = ww * v / np.mean(v)
            Xv = self.X[valid]
            A = Xv.T @ (Xv * ww[:, None]) + np.diag(self.pen)
            b = Xv.T @ (ww * y[valid])
            beta = np.linalg.solve(A, b)
            out[f"off_{name}"] = beta[2:2 + k]
            out[f"def_{name}"] = beta[2 + k:]
            out[f"lg_{name}"] = beta[0]
            if name == "pts":
                out["hfa_pts"] = beta[1]
        # weighted number of games behind each team's rating (for "confidence")
        tw = pd.Series(w[m]).groupby(self.tg.loc[m, "team"].to_numpy()).sum()
        out["rating_weight"] = out["team"].map(tw).fillna(0.0)
        return out


# ----------------------------------------------------------------------------
# Quarterbacks
# ----------------------------------------------------------------------------
def build_qb_games(pbp: pd.DataFrame, sched: pd.DataFrame):
    """Returns (qb_games, starters).
    qb_games: one row per QB per team-game with plays and EPA.
    starters: one row per team-game with the starting QB id/name."""
    empty_q = pd.DataFrame(columns=["game_id", "season", "week", "t", "team", "qb_id", "qb_name", "plays", "epa_sum"])
    starters = _schedule_starters(sched)
    if pbp is None or not len(pbp):
        return empty_q, starters
    p = pbp[pbp["posteam"].notna() & pbp["epa"].notna()].copy()
    qb_col = "passer_id" if p["passer_id"].notna().any() else "passer_player_id"
    name_col = "passer" if p["passer"].notna().any() else "passer_player_name"
    rush_id = "rusher_id" if p["rusher_id"].notna().any() else "rusher_player_id"
    rush_name = "rusher" if p["rusher"].notna().any() else "rusher_player_name"
    drop = p[(p["qb_dropback"] == 1)].copy()
    drop["qb_id"] = drop[qb_col].where(drop[qb_col].notna(), drop[rush_id])
    drop["qb_name"] = drop[name_col].where(drop[name_col].notna(), drop[rush_name])
    drop["val"] = drop["qb_epa"].where(drop["qb_epa"].notna(), drop["epa"])
    qb_ids = set(drop["qb_id"].dropna())
    runs = p[(p["qb_dropback"] != 1) & (p["play_type"] == "run") & p[rush_id].isin(qb_ids)].copy()
    runs["qb_id"] = runs[rush_id]
    runs["qb_name"] = runs[rush_name]
    runs["val"] = runs["epa"]
    q = pd.concat([drop, runs], ignore_index=True)
    q = q[q["qb_id"].notna()]
    qg = (q.groupby(["game_id", "season", "week", "posteam", "qb_id"])
          .agg(qb_name=("qb_name", "first"), plays=("val", "size"), epa_sum=("val", "sum"))
          .reset_index().rename(columns={"posteam": "team"}))
    qg["t"] = time_index(qg["season"], qg["week"])
    # pbp-based starter = QB on the team's first dropback of the game
    first = (drop.dropna(subset=["qb_id"]).sort_values(["game_id", "play_id"])
             .groupby(["game_id", "posteam"]).agg(qb_id_pbp=("qb_id", "first"), qb_name_pbp=("qb_name", "first"))
             .reset_index().rename(columns={"posteam": "team"}))
    starters = starters.merge(first, on=["game_id", "team"], how="outer")
    starters["qb_id"] = starters["qb_id"].where(starters["qb_id"].notna(), starters["qb_id_pbp"])
    starters["qb_name"] = starters["qb_name"].where(starters["qb_name"].notna(), starters["qb_name_pbp"])
    starters = starters.drop(columns=["qb_id_pbp", "qb_name_pbp"])
    return qg, starters


def _schedule_starters(sched: pd.DataFrame) -> pd.DataFrame:
    s = sched[sched["result"].notna()]
    h = pd.DataFrame({"game_id": s["game_id"], "team": s["home_team"], "qb_id": s["home_qb_id"], "qb_name": s["home_qb_name"]})
    a = pd.DataFrame({"game_id": s["game_id"], "team": s["away_team"], "qb_id": s["away_qb_id"], "qb_name": s["away_qb_name"]})
    out = pd.concat([h, a], ignore_index=True)
    out["qb_id"] = out["qb_id"].where(out["qb_id"].map(lambda x: isinstance(x, str) and len(x) > 0), np.nan)
    return out


def qb_values_asof(qg: pd.DataFrame, season: int, week: int, cfg):
    """Shrunk, recency-weighted EPA per QB play. Returns (DataFrame[qb_id, value, wplays, qb_name], league_avg, prior)."""
    t_now = int(time_index(season, week))
    m = (qg["t"].to_numpy() < t_now) & (qg["season"].to_numpy() >= season - 4)
    sub = qg[m]
    if sub.empty:
        return pd.DataFrame(columns=["qb_id", "value", "wplays", "qb_name"]), 0.0, -cfg.qb_replacement_gap
    w = recency_weights(sub["t"].to_numpy(), sub["season"].to_numpy(), t_now, season,
                        cfg.qb_half_life_weeks, cfg.qb_offseason_decay)
    tmp = pd.DataFrame({"qb_id": sub["qb_id"].to_numpy(), "qb_name": sub["qb_name"].to_numpy(),
                        "wp": w * sub["plays"].to_numpy(), "we": w * sub["epa_sum"].to_numpy()})
    g = tmp.groupby("qb_id").agg(wplays=("wp", "sum"), wepa=("we", "sum"), qb_name=("qb_name", "last"))
    lg = g["wepa"].sum() / max(g["wplays"].sum(), 1e-9)
    prior = lg - cfg.qb_replacement_gap
    g["value"] = (g["wepa"] + prior * cfg.qb_prior_plays) / (g["wplays"] + cfg.qb_prior_plays)
    return g.reset_index()[["qb_id", "value", "wplays", "qb_name"]], float(lg), float(prior)


# ----------------------------------------------------------------------------
# Elo (538-style: margin-of-victory multiplier, home field, season regression)
# ----------------------------------------------------------------------------
class Elo:
    def __init__(self, k=20.0, hfa=48.0, regress=1 / 3):
        self.k, self.hfa, self.regress = k, hfa, regress
        self.r: dict[str, float] = {}
        self.season = None

    def new_season(self, season):
        if self.season is not None and season != self.season:
            for t in self.r:
                self.r[t] = 1505 + (self.r[t] - 1505) * (1 - self.regress)
        self.season = season

    def get(self, team):
        return self.r.get(team, 1500.0)

    def update(self, home, away, margin, neutral):
        rh, ra = self.get(home), self.get(away)
        adv = 0.0 if neutral else self.hfa
        diff = rh + adv - ra
        exp_h = 1 / (1 + 10 ** (-diff / 400))
        res_h = 1.0 if margin > 0 else 0.0 if margin < 0 else 0.5
        winner_diff = diff if margin > 0 else -diff
        mult = math.log(abs(margin) + 1) * (2.2 / (winner_diff * 0.001 + 2.2)) if margin != 0 else 1.0
        delta = self.k * mult * (res_h - exp_h)
        self.r[home] = rh + delta
        self.r[away] = ra - delta
