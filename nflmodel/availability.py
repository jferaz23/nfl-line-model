"""Who is actually playing.

For every team-game we measure "missing regulars" by position group:
    regular      = player whose snap share over the team's previous N games >= threshold
    missing      = sum of those shares for regulars who did not play
                   (historical games: absent from the snap counts;
                    upcoming games: 1 - probability of playing from the injury
                    report / roster status / your manual overrides)
A value of 1.0 in miss_OL means "one full-time offensive lineman's worth of snaps
is missing". The game model learns how many points each group is worth.
QBs are handled separately (see ratings.qb_values_asof) because they matter far more.
"""
from __future__ import annotations

import logging
import re

import numpy as np
import pandas as pd

log = logging.getLogger("nflmodel")

POS_GROUP = {
    "T": "OL", "G": "OL", "C": "OL", "OL": "OL", "OT": "OL", "OG": "OL", "LT": "OL", "RT": "OL",
    "LG": "OL", "RG": "OL", "WR": "WR", "TE": "TE", "RB": "RB", "FB": "RB", "HB": "RB",
    "DE": "DL", "DT": "DL", "NT": "DL", "DL": "DL", "EDGE": "DL", "OLB": "LB", "ILB": "LB",
    "MLB": "LB", "LB": "LB", "CB": "DB", "S": "DB", "FS": "DB", "SS": "DB", "DB": "DB", "SAF": "DB",
}
OFF_GROUPS = ["OL", "WR", "TE", "RB"]
DEF_GROUPS = ["DL", "LB", "DB"]
GROUPS = OFF_GROUPS + DEF_GROUPS
ACTIVE_ROSTER = {"ACT", "A01", "ACTIVE"}


def name_key(s) -> str:
    if not isinstance(s, str):
        return ""
    s = re.sub(r"[^a-z0-9 ]", "", s.lower().replace("-", " ").replace(".", " "))
    toks = [t for t in s.split() if t not in {"jr", "sr", "ii", "iii", "iv", "v"}]
    return " ".join(toks)


def _team_games(games: pd.DataFrame) -> pd.DataFrame:
    base = ["game_id", "season", "week", "t", "is_target"]
    h = games[base + ["home_team"]].rename(columns={"home_team": "team"})
    a = games[base + ["away_team"]].rename(columns={"away_team": "team"})
    return pd.concat([h, a], ignore_index=True).sort_values(["team", "t", "game_id"])


def _override_probs(overrides: pd.DataFrame | None, cfg) -> dict:
    """(season, week, team, name_key) -> play probability."""
    out = {}
    if overrides is None or overrides.empty:
        return out
    for r in overrides.itertuples(index=False):
        status = str(getattr(r, "status", "")).strip().upper()
        try:
            p = float(status)
        except ValueError:
            p = cfg.status_play_prob.get(status)
        if p is None:
            log.warning("Unknown status '%s' in player_status overrides; use OUT/DOUBTFUL/QUESTIONABLE/IN or 0-1.", status)
            continue
        out[(int(r.season), int(r.week), str(r.team).upper(), name_key(r.player))] = min(max(p, 0.0), 1.0)
    return out


def compute_availability(snaps, games, rosters, injuries, overrides, cfg):
    """games needs game_id, season, week, t, home_team, away_team, is_target."""
    tgames = _team_games(games)
    miss_cols = [f"miss_{g}" for g in GROUPS]
    notes = []
    if snaps is None or snaps.empty:
        out = tgames[["game_id", "team"]].copy()
        for c in miss_cols:
            out[c] = 0.0
        out["miss_names"] = ""
        notes.append("Snap counts unavailable: non-QB injuries not modeled this run.")
        return out, notes

    s = snaps.copy()
    s["group"] = s["position"].map(lambda p: POS_GROUP.get(str(p).upper()))
    s = s[s["group"].notna() & s["team"].notna()].copy()
    off = s["group"].isin(OFF_GROUPS).to_numpy()
    s["share"] = np.where(off, s["offense_pct"].to_numpy(dtype=float), s["defense_pct"].to_numpy(dtype=float))
    s["share"] = s["share"].fillna(0.0)
    s["pid"] = s["pfr_player_id"].where(s["pfr_player_id"].notna(), s["player"].astype(str) + "|" + s["team"].astype(str))
    pinfo = (s.sort_values(["season", "week"]).groupby("pid")
             .agg(group=("group", "last"), name=("player", "last")))

    # ---- roster membership / status (optional data) ----
    roster_members, roster_status_latest, gsis_to_pfr = {}, {}, {}
    have_rosters = rosters is not None and not rosters.empty and rosters["pfr_id"].notna().any()
    if have_rosters:
        r = rosters.dropna(subset=["pfr_id", "team", "season", "week"])
        for (se, wk, tm), grp in r.groupby(["season", "week", "team"]):
            roster_members[(int(se), int(wk), tm)] = set(grp["pfr_id"])
        gsis_to_pfr = dict(zip(rosters["gsis_id"].dropna(), rosters.loc[rosters["gsis_id"].notna(), "pfr_id"]))
    elif rosters is not None and not rosters.empty:
        gsis_to_pfr = {}

    # ---- injury report for target games ----
    target_keys = set(map(tuple, tgames.loc[tgames["is_target"], ["season", "week", "team"]].astype(object).to_numpy()))
    inj_status = {}   # (season, week, team, pid) -> status
    inj_by_name = {}  # (season, week, team, name_key) -> status
    if injuries is not None and not injuries.empty and target_keys:
        inj = injuries[injuries["report_status"].notna()]
        for rr in inj.itertuples(index=False):
            key = (int(rr.season), int(rr.week), rr.team)
            if key not in target_keys:
                continue
            pid = gsis_to_pfr.get(rr.gsis_id)
            if pid:
                inj_status[key + (pid,)] = rr.report_status
            inj_by_name[key + (name_key(rr.full_name),)] = rr.report_status
    elif target_keys:
        notes.append("Injury report data unavailable: add statuses to overrides/player_status.csv.")
    ov = _override_probs(overrides, cfg)
    W, thr = cfg.regular_window_games, cfg.regular_min_share

    out_rows = []
    for team, tg in tgames.groupby("team", sort=False):
        tg = tg.sort_values("t")
        sub = s[s["team"] == team]
        gids = tg["game_id"].to_numpy()
        if sub.empty:
            for gid in gids:
                out_rows.append({"game_id": gid, "team": team, **{c: 0.0 for c in miss_cols}, "miss_names": ""})
            continue
        piv = sub.pivot_table(index="game_id", columns="pid", values="share", aggfunc="max")
        has_data = np.isin(gids, piv.index.to_numpy())
        piv = piv.reindex(gids)
        pids = piv.columns.to_numpy()
        present = np.nan_to_num(piv.to_numpy(dtype=float), nan=0.0)
        filled = present.copy()
        filled[~has_data, :] = np.nan
        seasons, weeks = tg["season"].to_numpy(), tg["week"].to_numpy()

        roll_x = pd.DataFrame(filled).rolling(W, min_periods=1).mean().shift(1).to_numpy()
        roll_s = np.full_like(filled, np.nan)
        for se in np.unique(seasons):
            blk = np.where(seasons == se)[0]
            roll_s[blk] = pd.DataFrame(filled[blk]).rolling(W, min_periods=1).mean().shift(1).to_numpy()
        roll_x, roll_s = np.nan_to_num(roll_x), np.nan_to_num(roll_s)
        roll = roll_s.copy()
        if have_rosters:
            for i in range(len(gids)):
                members = roster_members.get((int(seasons[i]), int(weeks[i]), team))
                if members is None and tg["is_target"].iloc[i]:
                    wk_avail = [w for (se, w, tm) in roster_members if se == seasons[i] and tm == team and w <= weeks[i]]
                    if wk_avail:
                        members = roster_members[(int(seasons[i]), max(wk_avail), team)]
                if members is not None:
                    roll[i] = roll_x[i] * np.isin(pids, list(members))
        regular = roll >= thr
        groups = pinfo.reindex(pids)["group"].to_numpy()
        names = pinfo.reindex(pids)["name"].to_numpy()
        is_target = tg["is_target"].to_numpy()

        for i, gid in enumerate(gids):
            if not is_target[i]:
                if not has_data[i]:
                    miss = np.zeros(len(pids))
                else:
                    miss = roll[i] * regular[i] * (present[i] <= 0)
                label = ""
            else:
                key = (int(seasons[i]), int(weeks[i]), team)
                p_play = np.ones(len(pids))
                status_txt = np.array([""] * len(pids), dtype=object)
                for j in np.where(regular[i])[0]:
                    pid, nk = pids[j], name_key(names[j])
                    st = inj_status.get(key + (pid,)) or inj_by_name.get(key + (nk,))
                    if st:
                        p_play[j] = cfg.status_play_prob.get(st, 1.0)
                        status_txt[j] = st.title()
                    if (key + (nk,)) in ov:
                        p_play[j] = ov[key + (nk,)]
                        status_txt[j] = f"override {p_play[j]:.0%}"
                if have_rosters:
                    latest = _latest_roster_status(rosters, key)
                    for j in np.where(regular[i])[0]:
                        stt = latest.get(pids[j])
                        if stt is not None and stt not in ACTIVE_ROSTER and (key + (name_key(names[j]),)) not in ov:
                            p_play[j] = 0.0
                            status_txt[j] = f"roster: {stt}"
                miss = roll[i] * regular[i] * (1.0 - p_play)
                order = np.argsort(-miss)
                label = "; ".join(f"{names[j]} ({groups[j]}, {status_txt[j] or 'out'})"
                                  for j in order[:6] if miss[j] > 0.05)
            row = {"game_id": gid, "team": team, "miss_names": label}
            for g in GROUPS:
                row[f"miss_{g}"] = float(miss[groups == g].sum())
            out_rows.append(row)
    return pd.DataFrame(out_rows), notes


_ROSTER_CACHE: dict = {}


def _latest_roster_status(rosters: pd.DataFrame, key) -> dict:
    """pfr_id -> status on the most recent roster snapshot at or before the target week."""
    if key in _ROSTER_CACHE:
        return _ROSTER_CACHE[key]
    season, week, team = key
    r = rosters[(rosters["season"] == season) & (rosters["team"] == team) & (rosters["week"] <= week)]
    if r.empty:
        _ROSTER_CACHE[key] = {}
        return {}
    r = r[r["week"] == r["week"].max()]
    res = dict(zip(r["pfr_id"], r["status"]))
    _ROSTER_CACHE[key] = res
    return res
