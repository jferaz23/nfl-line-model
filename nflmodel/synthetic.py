"""Synthetic league in nflverse format, used by --demo and the test run.

Everything here is invented: random schedules, made-up players ("BUF QB1",
"KC LT"), simulated plays, scores, injuries, referees, weather and odds. It
exists so the whole pipeline can be exercised without internet access. The
simulated world has real (small) effects for rest, travel, weather, injuries,
QB changes and so on, and a sharp synthetic market, so the demo also shows
what happens when a model tries to beat an efficient market.
"""
from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .data import clean_injuries, clean_pbp, clean_rosters, clean_schedules, clean_snaps
from .pricing import prob_to_american
from .venues import ABBR_TO_NAME, HOME, NEUTRAL_VENUES, TEAM_DIVISION, TEAMS, home_venue, kickoff_utc

from scipy.stats import norm

DEMO_SEASONS = list(range(2018, 2027))
TARGET = (2026, 4)
REGULARS = [("OL", "T", "LT"), ("OL", "G", "LG"), ("OL", "C", "C"), ("OL", "G", "RG"), ("OL", "T", "RT"),
            ("WR", "WR", "WR1"), ("WR", "WR", "WR2"), ("WR", "WR", "WR3"), ("TE", "TE", "TE1"), ("RB", "RB", "RB1"),
            ("DL", "DE", "DE1"), ("DL", "DT", "DT1"), ("DL", "DT", "DT2"), ("DL", "DE", "DE2"),
            ("LB", "OLB", "OLB1"), ("LB", "ILB", "ILB1"), ("LB", "OLB", "OLB2"),
            ("DB", "CB", "CB1"), ("DB", "CB", "CB2"), ("DB", "S", "S1"), ("DB", "S", "S2")]
BACKUPS = {"OL": [("G", "OL6"), ("T", "OL7")], "WR": [("WR", "WR4")], "TE": [("TE", "TE2")], "RB": [("RB", "RB2")],
           "DL": [("DE", "DL5"), ("DT", "DL6")], "LB": [("ILB", "LB4")], "DB": [("CB", "CB3"), ("S", "S3")]}
SHARE = {"OL": (0.93, 1.0), "WR": (0.72, 0.93), "TE": (0.65, 0.88), "RB": (0.5, 0.72),
         "DL": (0.58, 0.85), "LB": (0.68, 1.0), "DB": (0.85, 1.0)}
# EPA/play cost of one missing regular (offense groups hurt own offense; defense groups help opponent)
MISS_EFFECT = {"OL": 0.009, "WR": 0.007, "TE": 0.004, "RB": 0.003, "DL": 0.005, "LB": 0.004, "DB": 0.007}
REFS = [f"Referee {c}" for c in "ABCDEFGHIJKLMNOPQ"]
BOOKS = {"pinnacle": 0.025, "lowvig": 0.03, "draftkings": 0.045, "fanduel": 0.045}


def _season_start(season):
    d = date(season, 9, 8)
    while d.weekday() != 6:
        d += timedelta(days=1)
    return d  # week-1 Sunday


class _World:
    def __init__(self, rng):
        self.rng = rng
        self.team = {}
        self.qbs = {}
        self.players = {}
        self.out_until = {}
        self.pid_n = 0
        self.coach = {t: f"{t} Coach 1" for t in TEAMS}
        self.coach_aggr = {c: rng.uniform(0.15, 0.6) for c in self.coach.values()}
        self.ref_eff = {r: (rng.normal(0, 1.2), rng.normal(0, 0.012)) for r in REFS}

    def gsis(self):
        self.pid_n += 1
        return f"00-09{self.pid_n:05d}"

    def new_season(self, season):
        rng = self.rng
        for t in TEAMS:
            if t not in self.team:
                self.team[t] = dict(off_pass=rng.normal(0.06, 0.07), off_rush=rng.normal(-0.06, 0.035),
                                    def_pass=rng.normal(0.06, 0.06), def_rush=rng.normal(-0.06, 0.03),
                                    proe=rng.normal(0, 0.04), pace=rng.normal(0, 2.5), nh=rng.uniform(0.02, 0.2))
                self._new_qb(t, season, first=True)
                for grp, pos, lab in REGULARS:
                    self.players[(t, lab)] = dict(grp=grp, pos=pos, gsis=self.gsis(), pfr=f"SYN{t}{lab}",
                                                  name=f"{t} {lab}", regular=True)
                for grp, bl in BACKUPS.items():
                    for pos, lab in bl:
                        self.players[(t, lab)] = dict(grp=grp, pos=pos, gsis=self.gsis(), pfr=f"SYN{t}{lab}",
                                                      name=f"{t} {lab}", regular=False)
            else:
                s = self.team[t]
                for k, (mu, sd) in dict(off_pass=(0.06, 0.07), off_rush=(-0.06, 0.035), def_pass=(0.06, 0.06),
                                        def_rush=(-0.06, 0.03), proe=(0, 0.04), pace=(0, 2.5)).items():
                    s[k] = mu + 0.6 * (s[k] - mu) + rng.normal(0, sd * 0.8)
                if rng.random() < 0.15:
                    self._new_qb(t, season)
                if rng.random() < 0.2:
                    n = int(self.coach[t].split()[-1]) + 1
                    self.coach[t] = f"{t} Coach {n}"
                    self.coach_aggr[self.coach[t]] = rng.uniform(0.15, 0.6)

    def _new_qb(self, t, season, first=False):
        rng = self.rng
        n = self.qbs.get(t, {}).get("n", 0) + 1
        q1 = rng.normal(0.02, 0.07)
        self.qbs[t] = dict(n=n, qb1=dict(id=self.gsis(), name=f"{t} QB{n}", q=q1, pfr=f"SYN{t}QB{n}"),
                           qb2=dict(id=self.gsis(), name=f"{t} QB{n}b", q=q1 - rng.uniform(0.08, 0.2),
                                    pfr=f"SYN{t}QB{n}b"))

    def starter(self, t, season, week):
        q = self.qbs[t]
        if self.out_until.get(q["qb1"]["id"], (0, 0)) >= (season, week):
            return q["qb2"]
        return q["qb1"]

    def injured(self, key, season, week):
        return self.out_until.get(self.players[key]["gsis"], (0, 0)) >= (season, week)

    def roll_injuries(self, t, season, week):
        rng = self.rng
        for grp, pos, lab in REGULARS:
            p = self.players[(t, lab)]
            if rng.random() < 0.025 and not self.injured((t, lab), season, week + 1):
                self.out_until[p["gsis"]] = (season, week + int(rng.integers(1, 7)))
        q1 = self.qbs[t]["qb1"]
        if rng.random() < 0.03 and self.out_until.get(q1["id"], (0, 0)) < (season, week + 1):
            self.out_until[q1["id"]] = (season, week + int(rng.integers(1, 6)))


def _schedule(season, rng):
    teams = list(TEAMS)
    byes = {}
    order = rng.permutation(teams)
    counts = [4, 4, 2, 4, 2, 4, 2, 4, 4, 2]
    i = 0
    for wk, c in zip(range(5, 15), counts):
        for t in order[i:i + c]:
            byes[t] = wk
        i += c
    sunday1 = _season_start(season)
    intl_weeks = set(rng.choice(range(5, 11), size=2, replace=False).tolist())
    intl_sites = [v for keys, v in NEUTRAL_VENUES if v["name"] in ("Tottenham Hotspur Stadium", "Wembley Stadium",
                                                                   "Allianz Arena", "Estadio Azteca")]
    rows = []
    for wk in range(1, 19):
        active = [t for t in teams if byes.get(t) != wk]
        perm = list(rng.permutation(active))
        pairs = [(perm[j], perm[j + 1]) for j in range(0, len(perm), 2)]
        sunday = sunday1 + timedelta(days=7 * (wk - 1))
        for j, (h, a) in enumerate(pairs):
            if j == 0:
                day, tm = sunday - timedelta(days=3), "20:15"
            elif j == len(pairs) - 1:
                day, tm = sunday + timedelta(days=1), "20:15"
            elif j == len(pairs) - 2:
                day, tm = sunday, "20:20"
            elif j % 3 == 0:
                day, tm = sunday, "16:25" if j % 2 else "16:05"
            else:
                day, tm = sunday, "13:00"
            stadium, location = HOME[h]["name"], "Home"
            if wk in intl_weeks and j == 1:
                site = intl_sites[int(rng.integers(len(intl_sites)))]
                stadium, location, tm = site["name"], "Neutral", "09:30"
            rows.append(dict(season=season, week=wk, gameday=day.isoformat(), gametime=tm,
                             weekday=day.strftime("%A"), home_team=h, away_team=a, stadium=stadium,
                             location=location, game_type="REG",
                             game_id=f"{season}_{wk:02d}_{a}_{h}",
                             div_game=int(TEAM_DIVISION[h] == TEAM_DIVISION[a])))
    df = pd.DataFrame(rows)
    # rest days
    last = {}
    rest_h, rest_a = [], []
    for r in df.sort_values(["week", "gameday"]).itertuples():
        d = date.fromisoformat(r.gameday)
        rest_h.append((r.Index, (d - last[r.home_team]).days if r.home_team in last else 7))
        rest_a.append((r.Index, (d - last[r.away_team]).days if r.away_team in last else 7))
        last[r.home_team] = last[r.away_team] = d
    df.loc[[i for i, _ in rest_h], "home_rest"] = [v for _, v in rest_h]
    df.loc[[i for i, _ in rest_a], "away_rest"] = [v for _, v in rest_a]
    return df


def _climate(lat, gameday, rng):
    m = int(gameday[5:7])
    month_adj = {9: 0, 10: -8, 11: -18, 12: -27, 1: -31}.get(m, 0)
    temp = 80 - (lat - 30) * 1.3 + month_adj + rng.normal(0, 6)
    wind = float(rng.gamma(2.2, 3.5))
    precip = rng.random() < 0.14
    return float(temp), wind, precip


def _exp(w, off, dfn, g, side, ctx):
    """True per-play EPA means, pass rate, plays and expected points for team `off` vs `dfn`."""
    so, sd = w.team[off], w.team[dfn]
    season, week = g["season"], g["week"]
    qb = w.starter(off, season, week)
    miss_off = {grp: sum(w.injured((off, lab), season, week) for gg, _, lab in REGULARS if gg == grp)
                for grp in ("OL", "WR", "TE", "RB")}
    miss_def = {grp: sum(w.injured((dfn, lab), season, week) for gg, _, lab in REGULARS if gg == grp)
                for grp in ("DL", "LB", "DB")}
    mu_p = so["off_pass"] + sd["def_pass"] + qb["q"] - MISS_EFFECT["OL"] * miss_off["OL"] \
        - MISS_EFFECT["WR"] * miss_off["WR"] - MISS_EFFECT["TE"] * miss_off["TE"] \
        + MISS_EFFECT["DL"] * miss_def["DL"] + MISS_EFFECT["DB"] * miss_def["DB"]
    mu_r = so["off_rush"] + sd["def_rush"] - MISS_EFFECT["OL"] * miss_off["OL"] - MISS_EFFECT["RB"] * miss_off["RB"] \
        + MISS_EFFECT["DL"] * miss_def["DL"] + MISS_EFFECT["LB"] * miss_def["LB"]
    home_adj = 0.0 if ctx["neutral"] else (0.011 if side == "home" else -0.011)
    wind_pen = max(ctx["wind"] - 12, 0) * 0.005 + (0.02 if ctx["precip"] else 0.0)
    mu_p += home_adj - wind_pen
    mu_r += home_adj - 0.3 * wind_pen
    pr = float(np.clip(0.58 + so["proe"], 0.4, 0.75))
    plays = 62 + so["pace"] + 0.5 * sd["pace"]
    epa = pr * mu_p + (1 - pr) * mu_r
    pts = 22.0 + plays * (epa - 0.008)
    rest = ctx[f"{side}_rest"]
    pts += 0.6 if rest >= 12 else (-0.5 if rest <= 5 else 0.0)
    if ctx[f"{side}_clock"] <= 10.5:
        pts -= 1.0
    if ctx["alt"] > 4000 and side == "home" and not ctx["neutral"]:
        pts += 0.8
    if ctx[f"{side}_dome"] and ctx["temp"] < 40 and not ctx["indoor"]:
        pts -= 1.0
    pts += w.ref_eff[ctx["ref"]][0] / 2
    return dict(mu_p=mu_p, mu_r=mu_r, pr=pr, plays=plays, pts=pts, qb=qb)


def _score(pts, plays, rng):
    drives = max(int(round(plays / 5.8)), 8)
    p_fg = 0.14
    p_td = float(np.clip((pts / drives - 3 * p_fg) / 6.95, 0.03, 0.6))
    u = rng.random(drives)
    tds = int((u < p_td).sum())
    fgs = int(((u >= p_td) & (u < p_td + p_fg)).sum())
    td_pts = rng.choice([7, 6, 8], size=tds, p=[0.93, 0.045, 0.025]).sum() if tds else 0
    return int(td_pts + 3 * fgs + (2 if rng.random() < 0.012 else 0))


def generate(seed: int = 20260929):
    rng = np.random.default_rng(seed)
    w = _World(rng)
    sched_rows, pbp_parts, snap_rows, roster_rows, inj_rows = [], [], [], [], []
    truth = {}
    tz_team = {t: HOME[t]["tz"] for t in TEAMS}
    for season in DEMO_SEASONS:
        w.new_season(season)
        sch = _schedule(season, rng)
        for g in sch.sort_values(["week", "gameday", "gametime"]).to_dict("records"):
            h, a, wk = g["home_team"], g["away_team"], g["week"]
            played = (season, wk) < TARGET
            neutral = g["location"] == "Neutral"
            ven = next((v for keys, v in NEUTRAL_VENUES if v["name"] == g["stadium"]), None) or home_venue(h, season)
            roof = {"dome": "dome", "retractable": "closed"}.get(ven["roof"], "outdoors")
            surface = "fieldturf" if ven["surface"] == "turf" else "grass"
            temp, wind, precip = _climate(ven["lat"], g["gameday"], rng)
            if roof != "outdoors":
                temp, wind, precip = 70.0, 0.0, False
            ko = kickoff_utc(g["gameday"], g["gametime"])
            clock = {s: ko.astimezone(ZoneInfo(tz_team[t])).hour for s, t in (("home", h), ("away", a))}
            ref = REFS[int(rng.integers(len(REFS)))]
            ctx = dict(neutral=neutral, wind=wind, precip=precip, temp=temp, indoor=roof != "outdoors",
                       alt=ven["alt"], ref=ref, home_rest=g["home_rest"], away_rest=g["away_rest"],
                       home_clock=clock["home"], away_clock=clock["away"],
                       home_dome=HOME[h]["roof"] != "outdoors", away_dome=HOME[a]["roof"] != "outdoors")
            eh, ea = _exp(w, h, a, g, "home", ctx), _exp(w, a, h, g, "away", ctx)
            true_margin, true_total = eh["pts"] - ea["pts"], eh["pts"] + ea["pts"]
            truth[g["game_id"]] = (true_margin, true_total)
            mkt_m = true_margin + rng.normal(0, 2.0)
            mkt_t = true_total + rng.normal(0, 2.3)
            spread = round(mkt_m * 2) / 2
            total = round(mkt_t * 2) / 2
            p_home = float(norm.cdf(mkt_m / 13.3))
            row = dict(g, roof=roof, surface=surface, temp=round(temp) if roof == "outdoors" else np.nan,
                       wind=round(wind) if roof == "outdoors" else np.nan,
                       spread_line=spread, total_line=total, home_spread_odds=-110, away_spread_odds=-110,
                       over_odds=-110, under_odds=-110,
                       home_moneyline=round(prob_to_american(min(p_home * 1.023, 0.97))),
                       away_moneyline=round(prob_to_american(min((1 - p_home) * 1.023, 0.97))),
                       home_coach=w.coach[h], away_coach=w.coach[a],
                       referee=ref if played else np.nan,
                       home_qb_id=np.nan, away_qb_id=np.nan, home_qb_name=np.nan, away_qb_name=np.nan,
                       home_score=np.nan, away_score=np.nan, overtime=np.nan)
            if played:
                zh, za = rng.normal(0, 0.05, 2)
                hs = _score(eh["pts"] + eh["plays"] * zh, eh["plays"], rng)
                as_ = _score(ea["pts"] + ea["plays"] * za, ea["plays"], rng)
                ot = 0
                if hs == as_:
                    ot = 1
                    r_ = rng.random()
                    if r_ < 0.52:
                        hs += 3 if rng.random() < 0.7 else 6
                    elif r_ < 0.97:
                        as_ += 3 if rng.random() < 0.7 else 6
                row.update(home_score=hs, away_score=as_, overtime=ot,
                           home_qb_id=eh["qb"]["id"], away_qb_id=ea["qb"]["id"],
                           home_qb_name=eh["qb"]["name"], away_qb_name=ea["qb"]["name"])
                wx = "Indoors" if roof != "outdoors" else \
                    f"Temp: {round(temp)}° F, Wind: {round(wind)} mph{', Rain' if precip else ''}"
                for side, t, o, e, z in (("home", h, a, eh, zh), ("away", a, h, ea, za)):
                    pbp_parts.append(_plays(w, g, t, o, e, z, wx, rng, ref))
                    snap_rows += _snaps(w, g, t, o, e["plays"], rng)
                for t in (h, a):
                    w.roll_injuries(t, season, wk)
            sched_rows.append(row)
            if (season, wk) == TARGET:
                for t in (h, a):
                    inj_rows += _injury_report(w, t, season, wk, rng)
        if season == TARGET[0]:
            for wk in range(1, TARGET[1] + 1):
                roster_rows += _roster(w, season, wk)

    sched = clean_schedules(pd.DataFrame(sched_rows))
    pbp = pd.concat(pbp_parts, ignore_index=True)
    pbp["play_id"] = pbp.groupby("game_id").cumcount() + 1
    data = dict(schedules=sched, pbp=clean_pbp(pbp), snaps=clean_snaps(pd.DataFrame(snap_rows)),
                injuries=clean_injuries(pd.DataFrame(inj_rows)), rosters=clean_rosters(pd.DataFrame(roster_rows)))
    target = sched[(sched["season"] == TARGET[0]) & (sched["week"] == TARGET[1])]
    events, forecasts = _odds_and_weather(target, truth, w, rng)
    return data, events, forecasts


def _plays(w, g, team, opp, e, z, wx, rng, ref):
    n = int(max(round(e["plays"] + rng.normal(0, 4)), 45))
    qb = e["qb"]
    is_pass = rng.random(n) < e["pr"]
    epa = np.where(is_pass, rng.normal(e["mu_p"] + z, 1.5, n), rng.normal(e["mu_r"] + z, 1.1, n))
    scramble = is_pass & (rng.random(n) < 0.05)
    qb_run = (~is_pass) & (rng.random(n) < 0.12)
    rb = w.players[(team, "RB1")]
    df = pd.DataFrame({
        "game_id": g["game_id"], "season": g["season"], "week": g["week"], "season_type": "REG",
        "posteam": team, "defteam": opp, "home_team": g["home_team"], "away_team": g["away_team"],
        "play_type": np.where(is_pass, "pass", "run"), "pass": is_pass.astype(float),
        "rush": (~is_pass).astype(float), "qb_dropback": is_pass.astype(float),
        "qb_scramble": scramble.astype(float), "epa": epa, "qb_epa": epa, "success": (epa > 0).astype(float),
        "xpass": np.clip(0.58 + rng.normal(0, 0.12, n), 0.05, 0.95),
        "no_huddle": (rng.random(n) < w.team[team]["nh"]).astype(float),
        "shotgun": (rng.random(n) < 0.7).astype(float),
        "passer_id": np.where(is_pass & ~scramble, qb["id"], None),
        "passer": np.where(is_pass & ~scramble, qb["name"], None),
        "rusher_id": np.where(scramble | qb_run, qb["id"], np.where(~is_pass, rb["gsis"], None)),
        "rusher": np.where(scramble | qb_run, qb["name"], np.where(~is_pass, rb["name"], None)),
        "down": rng.integers(1, 4, n).astype(float), "ydstogo": rng.integers(1, 16, n).astype(float),
        "yardline_100": rng.integers(1, 100, n).astype(float),
        "penalty": (rng.random(n) < 0.07 + w.ref_eff[ref][1]).astype(float),
        "weather": wx, "game_seconds_remaining": np.linspace(3600, 0, n),
    })
    # turnovers and pass rush; who recovers a fumble is a coin flip, as in real football
    df["interception"] = (is_pass & (rng.random(n) < 0.024)).astype(float)
    df["fumble"] = (rng.random(n) < 0.012).astype(float)
    df["fumble_lost"] = ((df["fumble"] == 1) & (rng.random(n) < 0.5)).astype(float)
    df["sack"] = (is_pass & (rng.random(n) < 0.065)).astype(float)
    df["qb_hit"] = np.maximum(df["sack"], (is_pass & (rng.random(n) < 0.1)).astype(float))
    df["special_teams_play"] = 0.0
    df["touchdown"] = 0.0
    df["cpoe"] = np.where(is_pass, rng.normal(0, 8, n), np.nan)
    df["wp"] = np.clip(0.5 + np.cumsum(rng.normal(0, 0.03, n)), 0.01, 0.99)
    df["drive"] = (np.arange(n) // max(4, int(rng.integers(5, 8)))).astype(float) + 1
    third = df["down"] == 3
    df["third_down_converted"] = (third & (df["epa"] > 0.3)).astype(float)
    df["third_down_failed"] = (third & (df["epa"] <= 0.3)).astype(float)
    # fourth-down decisions (coach aggressiveness)
    n4 = int(rng.poisson(1.6))
    if n4:
        aggr = w.coach_aggr[w.coach[team]]
        go = rng.random(n4) < aggr
        f4 = pd.DataFrame({
            "game_id": g["game_id"], "season": g["season"], "week": g["week"], "season_type": "REG",
            "posteam": team, "defteam": opp, "home_team": g["home_team"], "away_team": g["away_team"],
            "play_type": np.where(go, "run", "punt"), "pass": 0.0, "rush": go.astype(float), "qb_dropback": 0.0,
            "qb_scramble": 0.0, "epa": np.where(go, rng.normal(0.1, 1.8, n4), rng.normal(-0.1, 0.4, n4)),
            "success": 0.0, "xpass": 0.5, "no_huddle": 0.0, "shotgun": 0.0,
            "rusher_id": np.where(go, rb["gsis"], None), "rusher": np.where(go, rb["name"], None),
            "down": 4.0, "ydstogo": rng.integers(1, 5, n4).astype(float),
            "yardline_100": rng.integers(30, 61, n4).astype(float), "penalty": 0.0, "weather": wx,
            "game_seconds_remaining": 1800.0})
        f4["qb_epa"] = f4["epa"]
        for c in ("interception", "fumble", "fumble_lost", "sack", "qb_hit", "touchdown"):
            f4[c] = 0.0
        f4["special_teams_play"] = np.where(go, 0.0, 1.0)
        f4["wp"] = 0.5
        f4["drive"] = 99.0
        f4["third_down_converted"] = 0.0
        f4["third_down_failed"] = 0.0
        f4["cpoe"] = np.nan
        f4["success"] = (f4["epa"] > 0).astype(float)
        df = pd.concat([df, f4], ignore_index=True)
    return df


def _snaps(w, g, team, opp, plays, rng):
    rows = []
    se, wk = g["season"], g["week"]
    out_groups = {}
    for grp, pos, lab in REGULARS:
        p = w.players[(team, lab)]
        lo, hi = SHARE[grp]
        share = rng.uniform(lo, hi)
        if w.injured((team, lab), se, wk):
            out_groups[grp] = out_groups.get(grp, 0.0) + share
            continue
        rows.append(_snap_row(g, team, opp, p, share, plays, grp))
    for grp, bl in BACKUPS.items():
        extra = out_groups.get(grp, 0.0)
        for i, (pos, lab) in enumerate(bl):
            share = rng.uniform(0.04, 0.3) + (extra if i == 0 else 0.0)
            rows.append(_snap_row(g, team, opp, w.players[(team, lab)], min(share, 1.0), plays, grp))
    return rows


def _snap_row(g, team, opp, p, share, plays, grp):
    off = grp in ("OL", "WR", "TE", "RB")
    return dict(game_id=g["game_id"], season=g["season"], week=g["week"], player=p["name"], pfr_player_id=p["pfr"],
                position=p["pos"], team=team, opponent=opp,
                offense_snaps=round(share * plays) if off else 0, offense_pct=round(share, 2) if off else 0.0,
                defense_snaps=0 if off else round(share * plays), defense_pct=0.0 if off else round(share, 2))


def _injury_report(w, team, season, week, rng):
    rows = []
    for grp, pos, lab in REGULARS:
        p = w.players[(team, lab)]
        if w.injured((team, lab), season, week):
            st = "Out"
        else:
            u = rng.random()
            st = "Questionable" if u < 0.06 else ("Doubtful" if u < 0.07 else None)
        if st:
            rows.append(dict(season=season, week=week, team=team, gsis_id=p["gsis"], full_name=p["name"],
                             position=p["pos"], report_status=st, practice_status="DNP" if st != "Questionable" else "Limited",
                             report_primary_injury=rng.choice(["Knee", "Ankle", "Hamstring", "Shoulder", "Concussion"]),
                             game_type="REG"))
    q1 = w.qbs[team]["qb1"]
    if w.out_until.get(q1["id"], (0, 0)) >= (season, week):
        rows.append(dict(season=season, week=week, team=team, gsis_id=q1["id"], full_name=q1["name"], position="QB",
                         report_status="Out", practice_status="DNP", report_primary_injury="Ankle", game_type="REG"))
    return rows


def _roster(w, season, week):
    rows = []
    for t in TEAMS:
        for (tm, lab), p in w.players.items():
            if tm != t:
                continue
            long_out = w.out_until.get(p["gsis"], (0, 0)) >= (season, week + 3)
            rows.append(dict(season=season, week=week, team=t, gsis_id=p["gsis"], pfr_id=p["pfr"],
                             full_name=p["name"], position=p["pos"], status="RES" if long_out else "ACT"))
        for k in ("qb1", "qb2"):
            q = w.qbs[t][k]
            long_out = w.out_until.get(q["id"], (0, 0)) >= (season, week + 3)
            rows.append(dict(season=season, week=week, team=t, gsis_id=q["id"], pfr_id=q["pfr"], full_name=q["name"],
                             position="QB", status="RES" if long_out else "ACT"))
    return rows


def _prices(p, vig):
    return round(prob_to_american(p * (1 + vig))), round(prob_to_american((1 - p) * (1 + vig)))


def _odds_and_weather(target, truth, w, rng):
    events, forecasts = [], {}
    for g in target.itertuples(index=False):
        tm, tt = truth[g.game_id]
        mkt_m, mkt_t = tm + rng.normal(0, 0.8), tt + rng.normal(0, 1.0)
        stale_m = rng.choice([0.0, 0.0, 0.0, 1.0, -1.0, 1.5, -1.5])
        stale_t = rng.choice([0.0, 0.0, 0.0, 1.5, -1.5, 2.0])
        ko = kickoff_utc(g.gameday, g.gametime)
        books = []
        for book, vig in BOOKS.items():
            m = mkt_m + (stale_m if book == "draftkings" else rng.normal(0, 0.25))
            t = mkt_t + (stale_t if book == "draftkings" else rng.normal(0, 0.3))
            hs = -round(m * 2) / 2
            ts = round(t * 2) / 2
            p_cover = float(norm.cdf((m + hs) / 13.3))
            p_over = float(norm.cdf((t - ts) / 13.6))
            p_win = float(norm.cdf(m / 13.3))
            hp, ap = _prices(p_cover, vig)
            op, up = _prices(p_over, vig)
            hml, aml = _prices(p_win, vig)
            hn, an = ABBR_TO_NAME[g.home_team], ABBR_TO_NAME[g.away_team]
            books.append({"key": book, "title": book.title(), "last_update": ko.isoformat(),
                          "markets": [
                              {"key": "h2h", "outcomes": [{"name": hn, "price": hml}, {"name": an, "price": aml}]},
                              {"key": "spreads", "outcomes": [{"name": hn, "price": hp, "point": hs},
                                                              {"name": an, "price": ap, "point": -hs}]},
                              {"key": "totals", "outcomes": [{"name": "Over", "price": op, "point": ts},
                                                             {"name": "Under", "price": up, "point": ts}]}]})
        events.append({"id": f"demo{g.game_id}", "sport_key": "americanfootball_nfl",
                       "commence_time": ko.strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "home_team": ABBR_TO_NAME[g.home_team], "away_team": ABBR_TO_NAME[g.away_team],
                       "bookmakers": books})
        if g.roof == "outdoors":
            lat = next((v["lat"] for keys, v in NEUTRAL_VENUES if v["name"] == g.stadium), HOME[g.home_team]["lat"])
            temp, wind, precip = _climate(lat, g.gameday, rng)
            forecasts[g.game_id] = {"temp_f": temp, "wind_mph": wind, "gust_mph": wind * 1.5,
                                    "precip_in": 0.12 if precip else 0.0, "snow_in": 0.0}
    return events, forecasts
