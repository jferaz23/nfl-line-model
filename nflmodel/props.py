"""Player props: DraftKings lines (free, ESPN core API provider 100), role-aware projections, logging and grading.

INFORMATION ONLY. The Oct 22, 2026 backtest (2024-26 prop lines) found no proven edge: green props failed the pre-stated
rule (2025 53.3% -4u, 2026 53.0% -6u at an assumed -115). This module powers an info-only Props tab and a live test of
two leads (big-edge unders; passing TDs/receptions, which need real prices) - see props_run.py.

Projection per market (as-of kickoff): the player's recency-weighted stat and volume (half-life 4 games; last season
counts 0.6), short-term form (half-life 1.5), opponent allowed to his position, team implied points from DraftKings'
spread/total, home, and role changes: targets/carries vacated by regular teammates who are out (injury report live,
snap counts in history) and his share of the remaining volume. Gradient boosting per market on 2015-to-date games.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger("nflmodel")
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
SITE_API = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
DK_PROVIDER = "100"
ESPN_TYPES = {"Total Passing Yards (incl. overtime)": "pass_yds", "Total Rushing Yards (incl. overtime)": "rush_yds",
              "Total Receiving Yards (incl. overtime)": "rec_yds", "Total Receptions (incl. overtime)": "receptions",
              "Total Passing Touchdowns (incl. overtime)": "pass_tds"}
MARKETS = {  # market: (stat column, volume column, position or None)
    "pass_yds": ("passing_yards", "attempts", "QB"), "pass_tds": ("passing_tds", "attempts", "QB"),
    "rush_yds": ("rushing_yards", "carries", None), "rec_yds": ("receiving_yards", "targets", None),
    "receptions": ("receptions", "targets", None)}
LABEL = {"pass_yds": "passing yards", "pass_tds": "passing TDs", "rush_yds": "rushing yards", "rec_yds": "receiving yards",
         "receptions": "receptions"}
ODDS_KEYS = {"pass_tds": "player_pass_tds", "receptions": "player_receptions", "rec_yds": "player_reception_yds",
             "rush_yds": "player_rush_yds", "pass_yds": "player_pass_yds"}
BIG_Z = 0.5                       # "big disagreement": |projection - line| >= 0.5 residual sd
FIX = {"LAR": "LA", "OAK": "LV", "SD": "LAC", "STL": "LA", "JAC": "JAX", "WSH": "WAS"}
POS = ["QB", "RB", "WR", "TE"]


def _pd(x):
    return x.to_pandas() if hasattr(x, "to_pandas") else x


def _ew(v, s, hl, season_mult):
    """Recency-weighted mean of PREVIOUS rows (one pass, running sums)."""
    out = np.full(len(v), np.nan); S = W = 0.0; d = 0.5 ** (1.0 / hl); last = None
    for i in range(len(v)):
        if last is not None and s[i] != last:
            f = season_mult ** (s[i] - last); S *= f; W *= f
        if W > 0:
            out[i] = S / W
        x = v[i]
        if not np.isnan(x):                      # upcoming rows (no stats yet) don't update the means
            S = S * d + x; W = W * d + 1.0
        last = s[i]
    return out


# ----------------------------------------------------------------------------- history + upcoming rows -> features
def _retry(fn, *a, tries=4, **k):
    for i in range(tries):
        try:
            return fn(*a, **k)
        except Exception as e:                      # nflverse downloads occasionally drop the connection
            if i == tries - 1:
                raise
            log.warning("download failed (%s); retrying", e); time.sleep(5 * (i + 1))


def load_history(seasons):
    import nflreadpy as nr
    st = _pd(_retry(nr.load_player_stats, seasons=list(seasons)))
    st = st[st.season_type == "REG"].copy()
    st["pos"] = st.position_group.fillna(st.position)
    st = st[st.pos.isin(POS)].copy()
    for c in ("team", "opponent_team"):
        st[c] = st[c].replace(FIX)
    sch = _pd(_retry(nr.load_schedules, seasons=list(seasons)))
    sch = sch[sch.game_type == "REG"]
    snaps = _pd(_retry(nr.load_snap_counts, seasons=[s for s in seasons if s >= 2013]))
    snaps = snaps[(snaps.game_type == "REG") & (snaps.offense_snaps.fillna(0) > 0)]
    players = _pd(_retry(nr.load_players))
    return st, sch, snaps, players


def implied(sch):
    s = sch.dropna(subset=["spread_line", "total_line"])
    a = s.assign(team=s.home_team, opp=s.away_team, home=1, imp_pts=(s.total_line + s.spread_line) / 2)
    b = s.assign(team=s.away_team, opp=s.home_team, home=0, imp_pts=(s.total_line - s.spread_line) / 2)
    out = pd.concat([a, b])[["season", "week", "team", "opp", "home", "imp_pts", "total_line"]]
    out["team"] = out.team.replace(FIX); out["opp"] = out.opp.replace(FIX)
    return out


def features(st, sch_imp, snaps, players, upcoming=None, out_ids=frozenset()):
    """st: weekly player stats. upcoming: rows (player_id, season, week, team, opponent_team, pos) for games to project,
    with home/imp_pts/total_line filled in. out_ids: player_ids ruled out for the upcoming week (injury report)."""
    st = st.merge(sch_imp.rename(columns={"opp": "opponent_team"}), on=["season", "week", "team", "opponent_team"], how="left")
    if upcoming is not None and len(upcoming):
        st = pd.concat([st, upcoming.assign(_upcoming=True)], ignore_index=True)
    st["_upcoming"] = st.get("_upcoming", False)
    st["_upcoming"] = st["_upcoming"].fillna(False).astype(bool)
    st["t"] = st.season * 20 + st.week
    st = st.sort_values(["player_id", "t"]).reset_index(drop=True)
    cols = ["passing_yards", "passing_tds", "attempts", "rushing_yards", "carries", "receiving_yards", "receptions", "targets",
            "target_share"]
    for c in cols:
        st[c] = pd.to_numeric(st.get(c), errors="coerce")
        v = st[c].fillna(0.0).where(~st._upcoming)          # past games: missing stat = 0; upcoming rows: not counted
        st[f"ew_{c}"] = np.concatenate([_ew(v[g.index].to_numpy(float), g.season.to_numpy(), 4.0, 0.6) for _, g in st.groupby("player_id", sort=False)])
        st[f"st_{c}"] = np.concatenate([_ew(v[g.index].to_numpy(float), g.season.to_numpy(), 1.5, 0.3) for _, g in st.groupby("player_id", sort=False)])
    st["n_prev"] = st.groupby("player_id").cumcount()
    # opponent allowed to the position (recency-weighted, minus the season/position average)
    hist = st[~st._upcoming]
    grp = hist.groupby(["season", "week", "opponent_team", "pos"])[[c for c, _, _ in MARKETS.values()]].sum().reset_index()
    nxt = st[st._upcoming][["season", "week", "opponent_team", "pos"]].drop_duplicates()
    grp = pd.concat([grp, nxt], ignore_index=True)
    grp["t"] = grp.season * 20 + grp.week
    grp = grp.sort_values(["opponent_team", "pos", "t"]).reset_index(drop=True)
    for c, _, _ in MARKETS.values():
        grp[f"allow_{c}"] = np.concatenate([_ew(g[c].to_numpy(float), g.season.to_numpy(), 4.0, 0.6) for _, g in grp.groupby(["opponent_team", "pos"], sort=False)])
        grp[f"allow_{c}"] -= grp.groupby(["season", "pos"])[f"allow_{c}"].transform("mean")
    st = st.merge(grp[["season", "week", "opponent_team", "pos"] + [f"allow_{c}" for c, _, _ in MARKETS.values()]],
                  on=["season", "week", "opponent_team", "pos"], how="left")
    # role changes: regular teammates (appeared in one of the team's last 3 games; recency-weighted targets >= 3 or
    # carries >= 6) who are out: no offensive snaps (history) or ruled out on the injury report (upcoming)
    pl = players[["gsis_id", "pfr_id"]].dropna()
    sn = snaps.merge(pl.rename(columns={"pfr_id": "pfr_player_id", "gsis_id": "player_id"}), on="pfr_player_id", how="inner")
    played = set(zip(sn.player_id, sn.season, sn.week)); have = set(zip(sn.season, sn.week))
    tg = st[["team", "season", "week", "_upcoming"]].drop_duplicates(["team", "season", "week"]).sort_values(["team", "season", "week"])
    rows = []
    for team, gg in tg.groupby("team"):
        sub = st[(st.team == team) & ~st._upcoming]
        keys = list(zip(gg.season, gg.week, gg._upcoming))
        for i, (se, wk, up) in enumerate(keys):
            if not up and (se, wk) not in have:
                continue
            prev = {(a, b) for a, b, _ in keys[max(0, i - 3):i]}
            if not prev:
                continue
            rec = sub[[(a, b) in prev for a, b in zip(sub.season, sub.week)]].sort_values("t").groupby("player_id").tail(1)
            rec = rec[(rec.ew_targets.fillna(0) >= 3) | (rec.ew_carries.fillna(0) >= 6)]
            for r in rec.itertuples(index=False):
                out = (r.player_id in out_ids) if up else ((r.player_id, se, wk) not in played)
                if out:
                    rows.append(dict(team=team, season=se, week=wk, mate=r.player_id, pos=r.pos, tgt=r.ew_targets or 0.0,
                                     car=r.ew_carries or 0.0, tsh=r.ew_target_share or 0.0))
    V = pd.DataFrame(rows, columns=["team", "season", "week", "mate", "pos", "tgt", "car", "tsh"])
    tv = V.groupby(["team", "season", "week"])[["tgt", "car", "tsh"]].sum().rename(columns=lambda c: f"vac_{c}").reset_index()
    pv = V.groupby(["team", "season", "week", "pos"])[["tgt", "car"]].sum().rename(columns=lambda c: f"vacpos_{c}").reset_index()
    sv = V.rename(columns={"mate": "player_id", "tgt": "s_tgt", "car": "s_car", "tsh": "s_tsh"})[["team", "season", "week", "player_id", "s_tgt", "s_car", "s_tsh"]]
    st = st.merge(tv, on=["team", "season", "week"], how="left").merge(pv, on=["team", "season", "week", "pos"], how="left")
    st = st.merge(sv, on=["team", "season", "week", "player_id"], how="left")
    for c in ("vac_tgt", "vac_car", "vac_tsh", "vacpos_tgt", "vacpos_car", "s_tgt", "s_car", "s_tsh"):
        st[c] = st[c].fillna(0.0)
    st["vac_tgt"] -= st.s_tgt; st["vac_car"] -= st.s_car; st["vac_tsh"] -= st.s_tsh
    st["vacpos_tgt"] -= st.s_tgt; st["vacpos_car"] -= st.s_car
    st["share_rem"] = st.ew_target_share.fillna(0) / (1 - st.vac_tsh.clip(upper=0.8))
    return st


def feat_cols(market):
    stat, vol, _ = MARKETS[market]
    return list(dict.fromkeys([f"ew_{stat}", f"ew_{vol}", "ew_target_share", "n_prev", f"allow_{stat}", "imp_pts", "total_line", "home",
                               "vac_tgt", "vac_car", "vacpos_tgt", "vacpos_car", "share_rem", f"st_{vol}", f"st_{stat}"]))


def project(st, first_season=2015):
    """Train on completed games, project the upcoming rows. Returns upcoming rows with proj_<market> and sd_<market>."""
    from sklearn.ensemble import HistGradientBoostingRegressor
    up = st[st._upcoming].copy()
    for m, (stat, vol, pos) in MARKETS.items():
        fc = feat_cols(m)
        d = st[~st._upcoming & (st.season >= first_season)].dropna(subset=[f"ew_{stat}"])
        if pos:
            d = d[d.pos == pos]
        d = d[d[f"ew_{vol}"].fillna(0) > 0.5]
        mdl = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=24, min_samples_leaf=60, l2_regularization=1.0)
        mdl.fit(d[fc], d[stat].fillna(0))
        up[f"proj_{m}"] = mdl.predict(up[fc])
        up[f"sd_{m}"] = float(np.std(d[stat].fillna(0) - mdl.predict(d[fc])))
    return up


# ----------------------------------------------------------------------------- DraftKings lines via ESPN
def _get(url, tries=3):
    import requests
    for t in range(tries):
        try:
            r = requests.get(url, timeout=40)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except Exception:
            time.sleep(2 * (t + 1))
    return None


def week_events(season, week):
    d = _get(f"{SITE_API}/scoreboard?dates={season}&seasontype=2&week={week}") or {}
    out = []
    for e in d.get("events", []):
        comp = {c["homeAway"]: c["team"]["abbreviation"] for c in e["competitions"][0]["competitors"]}
        out.append(dict(espn_event=e["id"], kickoff=e["date"], home=FIX.get(comp["home"], comp["home"]),
                        away=FIX.get(comp["away"], comp["away"]), state=e["status"]["type"]["state"]))
    return out


def dk_lines(event_id):
    """Main DraftKings line per player and market (ESPN lists the over and the under; same line)."""
    items, page = [], 1
    while True:
        d = _get(f"{CORE}/events/{event_id}/competitions/{event_id}/odds/{DK_PROVIDER}/propBets?limit=1000&page={page}")
        if not d:
            break
        items += d.get("items", [])
        if page >= d.get("pageCount", 1):
            break
        page += 1
    rows = []
    for i in items:
        m = ESPN_TYPES.get((i.get("type") or {}).get("name"))
        a = re.search(r"/athletes/(\d+)", ((i.get("athlete") or {}).get("$ref") or ""))
        cur = ((i.get("current") or {}).get("target") or {}).get("value")
        if m and a and cur is not None:
            rows.append(dict(espn_athlete=a.group(1), market=m, line=float(cur),
                             open_line=((i.get("open") or {}).get("target") or {}).get("value"), updated=i.get("lastUpdated")))
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("updated").groupby(["espn_athlete", "market"]).tail(1)


# ----------------------------------------------------------------------------- DraftKings prices (The Odds API, paid)
def dk_prices(api_key, events_needed, markets):
    """events_needed: list of (home, away). Returns rows (home, away, player_name, market, side, point, price) and credits used.
    Cost: about one credit per market per event (DraftKings only)."""
    import requests
    base = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl"
    from .venues import team_from_name
    evs = requests.get(f"{base}/events", params={"apiKey": api_key}, timeout=30).json()
    rows, used = [], 0
    want = set(events_needed)
    for ev in evs:
        h, a = team_from_name(ev.get("home_team")), team_from_name(ev.get("away_team"))
        if (h, a) not in want:
            continue
        r = requests.get(f"{base}/events/{ev['id']}/odds", params={"apiKey": api_key, "regions": "us", "bookmakers": "draftkings",
                         "markets": ",".join(ODDS_KEYS[m] for m in markets), "oddsFormat": "american"}, timeout=30)
        if not r.ok:
            log.warning("props prices: %s %s", r.status_code, r.text[:120]); continue
        used += int(r.headers.get("x-requests-last") or 0)
        for b in r.json().get("bookmakers", []):
            for mk in b.get("markets", []):
                m = next((k for k, v in ODDS_KEYS.items() if v == mk["key"]), None)
                for o in mk.get("outcomes", []):
                    rows.append(dict(home=h, away=a, player_name=o.get("description"), market=m, side=str(o.get("name", "")).lower(),
                                     point=o.get("point"), price=o.get("price")))
        remaining = r.headers.get("x-requests-remaining")
    return pd.DataFrame(rows), used


def name_key(s):
    s = re.sub(r"[^a-z ]", "", str(s).lower().replace("-", " ").replace(".", ""))
    toks = [t for t in s.split() if t not in {"jr", "sr", "ii", "iii", "iv", "v"}]
    return " ".join(toks)
