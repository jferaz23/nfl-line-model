"""One row per game with every factor the model uses, computed "as of" kickoff.

Nothing in a row uses information from that game or later games, so the same
table serves both the weekly projection (target games) and honest backtests.

Factors are organised in groups (see MARGIN_GROUPS / TOTAL_GROUPS). The
backtest's ablation drops one group at a time, which is how you find out which
of these "every possible factor" ideas actually carry signal.
"""
from __future__ import annotations

import logging
import re
import warnings
from collections import defaultdict, deque
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .availability import DEF_GROUPS, GROUPS, OFF_GROUPS, compute_availability
from .continuity import compute_continuity
from .ratings import Elo, RatingEngine, build_qb_games, build_team_games, qb_values_asof, time_index
from .venues import (home_venue, haversine_miles, is_indoor, is_turf, kickoff_utc, local_hour,
                     resolve_venue, utc_offset_hours)

log = logging.getLogger("nflmodel")

MARGIN_GROUPS = {
    "home_field": ["home_ind", "hfa_trend", "div_game", "playoff", "home_no_fans"],
    "team_strength": ["d_wepa_net", "d_mkt_rating", "d_st_epa", "d_pts_net", "d_off_pass", "d_def_pass", "d_off_rush", "d_def_rush",
                      "d_sr_net", "elo_diff"],
    "scheme_matchup": ["matchup_epa_margin", "d_proe", "d_pace"],
    "quarterback": ["d_qb_val", "d_qb_delta", "d_qb_new", "d_qb_cpoe"],
    "injuries": [f"d_miss_{g}" for g in GROUPS],
    "rest_travel": ["rest_diff", "home_bye", "away_bye", "home_short", "away_short",
                    "away_travel_kmi", "d_travel_kmi", "tz_shift_away", "intl",
                    "away_road_streak", "short_x_travel"],
    "time_of_day": ["d_body_clock", "west_early", "prime_x_clock", "thu", "mon", "sat"],
    "weather": ["wind_x_passdiff", "dome_team_cold", "warm_team_cold", "outdoor_in_dome"],
    "venue_history": ["home_venue_resid", "away_venue_resid", "home_coach_venue_resid", "away_coach_venue_resid",
                      "d_qb_venue", "d_qb_env"],
    "surface_altitude": ["away_surface_mismatch", "home_surface_mismatch", "alt_adv_kft"],
    "coaching": ["d_coach_resid", "d_new_coach", "d_coach_tenure"],
    "officials": ["ref_margin_resid"],
    "history": ["h2h_resid", "home_ats_resid", "road_ats_resid"],
    "situational": ["d_prev_margin", "prev_ot_h", "prev_ot_a", "d_next_opp_elo", "early_x_strength",
                    "d_winless", "d_unbeaten", "d_record_luck", "d_ats_form", "d_post_intl",
                    "d_fum_luck", "d_to_margin", "d_press", "d_sack_luck", "d_3rd_luck"],
    "drive_efficiency": ["d_ppd_net"],
    "motivation": ["d_elim", "d_rest_risk"],
    "early_down": ["d_early_net"],
    "big_plays": ["d_big_net"],
    "roster_continuity": ["d_cont_early"],
    "win_totals": ["d_wt_early"],
}
TOTAL_GROUPS = {
    "scoring_env": ["sum_press", "sum_3rd_luck", "sum_ou_form", "sum_post_intl", "lg_pts_level", "early_season", "playoff", "div_game"],
    "drive_efficiency": ["ppd_total_pred", "drives_total"],
    "calendar": ["wk_nov", "wk_dec"],
    "motivation": ["sum_elim"],
    "team_strength": ["pts_total_pred", "sum_wepa", "mkt_total_pred", "sum_off_pass", "sum_def_pass", "sum_off_rush", "sum_def_rush"],
    "scheme_matchup": ["matchup_epa_total", "pace_total", "proe_sum", "nohuddle_sum"],
    "quarterback": ["sum_qb_val", "sum_qb_delta", "sum_qb_cpoe"],
    "injuries": ["off_miss_sum", "def_miss_sum"],
    "rest_travel": ["rest_sum_short", "away_travel_kmi", "intl"],
    "time_of_day": ["kickoff_et", "primetime", "thu", "mon", "sat"],
    "weather": ["indoor", "wind_over10", "wind_over15", "cold", "heat", "precip", "snow", "outdoor_in_dome_sum"],
    "venue_history": ["venue_total_resid", "sum_qb_venue", "sum_qb_env"],
    "surface_altitude": ["turf", "altitude_kft"],
    "coaching": ["coach_aggr_sum", "sum_new_coach"],
    "officials": ["ref_total_resid", "ref_pen_rate"],
    "history": ["h2h_total_resid"],
    "early_down": ["sum_early"],
    "big_plays": ["sum_big"],
    "roster_continuity": ["sum_offcont_early", "sum_defcont_early"],
    "win_totals": ["sum_wt_early"],
}
MARGIN_FEATURES = [f for fs in MARGIN_GROUPS.values() for f in fs]
TOTAL_FEATURES = list(dict.fromkeys(f for fs in TOTAL_GROUPS.values() for f in fs))

RATING_COLS = ["off_ppd", "def_ppd", "off_drv", "def_drv", "off_wepao", "def_wepao", "off_wepad", "def_wepad", "off_pts", "def_pts", "off_pass", "def_pass", "off_rush", "def_rush", "off_sr", "def_sr",
               "off_pace", "def_pace", "off_proe", "def_proe", "off_nh", "def_nh", "lg_pts", "lg_pass",
               "lg_rush", "lg_pace", "hfa_pts", "rating_weight", "qb_base",
               "off_early", "def_early", "off_big", "def_big"]
MARKET_COLS = ["spread_line", "total_line", "home_moneyline", "away_moneyline", "home_spread_odds",
               "away_spread_odds", "over_odds", "under_odds"]
RAIN_WORDS = re.compile(r"rain|shower|drizzle|storm|thunder|precip", re.I)
SNOW_WORDS = re.compile(r"snow|flurr|sleet|wintry", re.I)


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def qb_key(name) -> str:
    """'P.Mahomes', 'Patrick Mahomes', 'Mahomes, Patrick' -> 'p mahomes'."""
    if not isinstance(name, str) or not name.strip():
        return ""
    s = name.strip()
    if "," in s:
        last, first = [x.strip() for x in s.split(",", 1)]
        s = f"{first} {last}"
    s = re.sub(r"[^a-z0-9 .]", "", s.lower().replace("-", " "))
    toks = [t for t in re.split(r"[ .]+", s) if t and t not in {"jr", "sr", "ii", "iii", "iv", "v"}]
    if not toks:
        return ""
    if len(toks) == 1:
        return toks[0]
    return f"{toks[0][0]} {toks[-1]}"


def _full_key(name) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower()) if isinstance(name, str) else ""


def _shrink(total, n, k):
    return total / (n + k) if n > 0 else 0.0


def _fnum(x, default=np.nan):
    try:
        v = float(x)
        return v if np.isfinite(v) else default
    except (TypeError, ValueError):
        return default


# ----------------------------------------------------------------------------
# quarterbacks for upcoming games
# ----------------------------------------------------------------------------
def _match_qb(name, team, qg):
    """Find a qb_id for a typed name, preferring QBs who played for that team."""
    if qg.empty:
        return None, name
    fk, qk = _full_key(name), qb_key(name)
    cands = qg[["qb_id", "qb_name", "team", "t", "plays"]]
    for pool in (cands[cands["team"] == team], cands):
        if pool.empty:
            continue
        full = pool[pool["qb_name"].map(_full_key) == fk]
        if full.empty:
            full = pool[pool["qb_name"].map(qb_key) == qk]
        if not full.empty:
            best = full.groupby("qb_id").agg(t=("t", "max"), n=("qb_name", "last")).sort_values("t").iloc[-1]
            return best.name, best["n"]
    return None, name


def _qb_unavailable(qid, qname, team, season, week, injuries, rosters):
    """Returns a reason string if the QB is listed Out/Doubtful or off the active roster."""
    if injuries is not None and not injuries.empty:
        inj = injuries[(injuries["season"] == season) & (injuries["week"] == week) & (injuries["team"] == team)]
        if not inj.empty:
            hit = inj[(inj["gsis_id"] == qid) | (inj["full_name"].map(qb_key) == qb_key(qname))]
            st = hit["report_status"].dropna()
            if len(st) and st.iloc[-1] in ("OUT", "DOUBTFUL", "IR", "PUP", "SUSPENDED", "INACTIVE"):
                return st.iloc[-1].title()
    if rosters is not None and not rosters.empty:
        r = rosters[(rosters["season"] == season) & (rosters["week"] <= week)]
        if not r.empty:
            r = r[r["week"] == r["week"].max()]
            me = r[r["gsis_id"] == qid]
            if me.empty:
                me = r[(r["full_name"].map(qb_key) == qb_key(qname)) & (r["position"] == "QB")]
            if me.empty:
                team_r = r[r["team"] == team]
                if not team_r.empty:
                    return "not on roster"
            else:
                if (me["team"] != team).all():
                    return f"now on {me['team'].iloc[-1]}"
                st = me["status"].iloc[-1]
                if isinstance(st, str) and st not in ("ACT", "A01", "ACTIVE"):
                    return f"roster {st}"
    return None


def _backup_qb(team, season, week, exclude, qg, rosters, wplays):
    """Most-used available QB for the team (active roster if we have it)."""
    if rosters is not None and not rosters.empty:
        r = rosters[(rosters["season"] == season) & (rosters["week"] <= week) & (rosters["team"] == team)]
        if not r.empty:
            r = r[(r["week"] == r["week"].max()) & (r["position"] == "QB") & r["status"].isin(["ACT", "A01", "ACTIVE"])]
            r = r[r["gsis_id"] != exclude]
            if not r.empty:
                best = max(r["gsis_id"].dropna(), key=lambda q: wplays.get(q, 0.0), default=None)
                if best is not None:
                    return best, r.loc[r["gsis_id"] == best, "full_name"].iloc[0]
    alt = qg[(qg["team"] == team) & (qg["season"] >= season - 1) & (qg["qb_id"] != exclude)]
    if not alt.empty:
        best = alt.groupby("qb_id").agg(plays=("plays", "sum"), n=("qb_name", "last")).sort_values("plays").iloc[-1]
        return best.name, best["n"]
    return "UNKNOWN", "unknown QB"


def project_starters(target, starters_hist, qg, injuries, rosters, qb_overrides, qmap_wplays):
    """Projected starting QB for each team in the target games.
    Order: your override -> last starter (unless Out/Doubtful/off roster) -> the team's
    most-used other available QB -> unknown (valued at replacement level)."""
    rows = []
    ov = qb_overrides if qb_overrides is not None and not qb_overrides.empty else None
    for g in target.itertuples(index=False):
        for side, team in (("home", g.home_team), ("away", g.away_team)):
            qid, qname, src = None, None, None
            if ov is not None:
                o = ov[(ov["season"].astype(int) == g.season) & (ov["week"].astype(int) == g.week)
                       & (ov["team"].astype(str).str.upper() == team)]
                if len(o):
                    typed = str(o["qb_name"].iloc[-1])
                    qid, qname = _match_qb(typed, team, qg)
                    src = "your override"
                    if qid is None:
                        qid, qname, src = f"UNKNOWN:{typed}", typed, "your override (no NFL history: replacement level)"
            if qid is None:
                h = starters_hist[(starters_hist["team"] == team) & starters_hist["qb_id"].notna()]
                h = h[h["t"] < time_index(g.season, g.week)].sort_values("t")
                last_id = h["qb_id"].iloc[-1] if len(h) else None
                last_name = h["qb_name"].iloc[-1] if len(h) else None
                reason = _qb_unavailable(last_id, last_name, team, g.season, g.week, injuries, rosters) if last_id else "no history"
                if last_id and reason is None:
                    qid, qname, src = last_id, last_name, "last starter"
                else:
                    qid, qname = _backup_qb(team, g.season, g.week, last_id, qg, rosters, qmap_wplays)
                    src = f"backup ({last_name}: {reason})" if last_id else "no recent starter found"
            rows.append({"game_id": g.game_id, "team": team, "side": side, "qb_id": qid,
                         "qb_name": qname, "qb_source": src})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# sequential context: Elo, schedule spots, coaches, referees, history
# ----------------------------------------------------------------------------
def _pbp_game_extras(pbp):
    """Per game: penalties, weather text. Per team-game: 4th-down go/att counts."""
    if pbp is None or pbp.empty:
        return {}, {}, {}
    pen = pbp.groupby("game_id")["penalty"].sum().to_dict()
    wx = pbp.dropna(subset=["weather"]).groupby("game_id")["weather"].first().to_dict()
    d4 = pbp[(pbp["down"] == 4) & (pbp["ydstogo"] <= 4) & pbp["yardline_100"].between(30, 60)
             & pbp["play_type"].isin(["pass", "run", "punt", "field_goal"])].copy()
    d4["go"] = d4["play_type"].isin(["pass", "run"]).astype(float)
    g = d4.groupby(["game_id", "posteam"])["go"].agg(["sum", "size"])
    fourth = {k: (float(v["sum"]), float(v["size"])) for k, v in g.iterrows()}
    return pen, wx, fourth


def _pbp_team_extras(pbp):
    """(game_id, team) -> (own fumbles, own fumbles lost, takeaways, giveaways, net special-teams EPA).
    Fumble recoveries are close to coin flips and turnover margins regress hard, so these feed
    shrunk 'luck' features; special-teams EPA is a small but real strength component."""
    need = {"fumble", "fumble_lost", "interception"}
    if pbp is None or pbp.empty or not need.issubset(pbp.columns):
        return {}
    p = pbp[pbp["posteam"].notna() & pbp["defteam"].notna()]
    num = lambda c: pd.to_numeric(p[c], errors="coerce").fillna(0.0)
    df = pd.DataFrame({"game_id": p["game_id"], "off": p["posteam"], "dfn": p["defteam"],
                       "fum": num("fumble"), "lost": num("fumble_lost"), "int": num("interception")})
    st = p["play_type"].isin(["punt", "kickoff", "field_goal", "extra_point"])
    if "special_teams_play" in p.columns:
        st = st | (pd.to_numeric(p["special_teams_play"], errors="coerce") == 1)
    df["st_epa"] = np.where(st, pd.to_numeric(p["epa"], errors="coerce").fillna(0.0), 0.0)
    df["give"] = df["lost"] + df["int"]
    # pass rush: dropbacks, sacks and pressure (sack or QB hit) -- pressure is stable, sacks are lucky
    db = ((pd.to_numeric(p["qb_dropback"], errors="coerce") == 1) if "qb_dropback" in p.columns
          else (p["play_type"] == "pass")) & p["play_type"].isin(["pass", "run"])
    sk = num("sack") if "sack" in p.columns else 0.0
    hit = num("qb_hit") if "qb_hit" in p.columns else 0.0
    df["db"] = db.astype(float)
    df["sack"] = np.where(db, sk, 0.0)
    df["press"] = np.where(db, np.maximum(sk, hit), 0.0)
    # third downs vs early-down success (third-down rates regress hard toward early-down efficiency)
    down = pd.to_numeric(p["down"], errors="coerce")
    scrim = p["play_type"].isin(["pass", "run"])
    if "third_down_converted" in p.columns:
        df["c3"] = np.where(scrim & (down == 3), num("third_down_converted"), 0.0)
        df["a3"] = np.where(scrim & (down == 3), num("third_down_converted") + num("third_down_failed"), 0.0)
    else:
        df["c3"] = df["a3"] = 0.0
    ed = scrim & down.isin([1, 2])
    df["eds"] = np.where(ed, pd.to_numeric(p["success"], errors="coerce").fillna(0.0), 0.0)
    df["edn"] = ed.astype(float)
    off = df.groupby(["game_id", "off"])[["fum", "lost", "give", "st_epa", "db", "sack", "press", "c3", "a3", "eds", "edn"]].sum()
    dfn = df.groupby(["game_id", "dfn"])[["give", "st_epa", "db", "sack", "press"]].sum()
    off.index.names = dfn.index.names = ["game_id", "team"]
    j = off.join(dfn, rsuffix="_opp", how="outer").fillna(0.0)
    return {k: (r["fum"], r["lost"], r["give_opp"], r["give"], r["st_epa"] - r["st_epa_opp"],
                r["db"], r["sack"], r["press"], r["db_opp"], r["sack_opp"], r["press_opp"],
                r["c3"], r["a3"], r["eds"], r["edn"])
            for k, r in j.iterrows()}


def _next_opponents(sched):
    """(game_id, team) -> next opponent that season (look-ahead / letdown spot)."""
    out = {}
    rows = []
    for r in sched[["game_id", "season", "t", "gameday", "home_team", "away_team"]].itertuples(index=False):
        rows.append((r.home_team, r.season, r.t, str(r.gameday), r.game_id, r.away_team))
        rows.append((r.away_team, r.season, r.t, str(r.gameday), r.game_id, r.home_team))
    rows.sort()
    for i in range(len(rows) - 1):
        a, b = rows[i], rows[i + 1]
        if a[0] == b[0] and a[1] == b[1]:
            out[(a[4], a[0])] = b[5]
    return out


def _context(ctx, pbp):
    pen, _, fourth = _pbp_game_extras(pbp)
    tx = _pbp_team_extras(pbp)
    lk = {}                                # team -> (season, games, fumbles, lost, takeaways, giveaways, st_epa)
    pz = {}                                # team -> season pass-rush and third-down tallies
    lgp = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]  # league: pressures, dropbacks, sacks, 3rd conv, 3rd att, ed succ, ed plays
    nxt = _next_opponents(ctx)
    elo = Elo()
    last = {}                              # team -> (season, margin, ot)
    road = defaultdict(lambda: (None, 0))  # team -> (season, consecutive road games)
    coach_games = defaultdict(int)         # (coach, team) -> games
    coach_ats = defaultdict(lambda: [0.0, 0])
    coach_4th = defaultdict(lambda: [0.0, 0.0])
    lg_4th = [0.0, 0.0]
    ref = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0])  # n, tot_resid, margin_resid, penalties, pen_n
    lg_pen = [0.0, 0]
    h2h = defaultdict(lambda: deque(maxlen=12))
    home_ats = defaultdict(lambda: deque(maxlen=40))
    road_ats = defaultdict(lambda: deque(maxlen=40))
    last_coach = {}
    rec = {}                               # team -> season record, points, ATS and O/U tallies (this season only)
    lg_res = [0.0, 0.0]                    # running league-average residuals (margin, total) vs the line
    feats = []
    for r in ctx.itertuples(index=False):
        elo.new_season(r.season)
        h, a, se = r.home_team, r.away_team, r.season
        hc = r.home_coach if isinstance(r.home_coach, str) and r.home_coach else last_coach.get(h, f"{h} coach")
        ac = r.away_coach if isinstance(r.away_coach, str) and r.away_coach else last_coach.get(a, f"{a} coach")
        neutral = r.location == "Neutral"
        f = {"game_id": r.game_id, "home_coach_used": hc, "away_coach_used": ac}
        f["elo_h"], f["elo_a"] = elo.get(h), elo.get(a)
        f["elo_diff"] = (f["elo_h"] - f["elo_a"] + (0 if neutral else elo.hfa)) / 25.0
        for side, tm in (("h", h), ("a", a)):
            lp = last.get(tm)
            same = lp is not None and lp[0] == se
            f[f"prev_margin_{side}"] = lp[1] if same else 0.0
            f[f"prev_ot_{side}"] = float(lp[2]) if same else 0.0
            no = nxt.get((r.game_id, tm))
            f[f"next_opp_elo_{side}"] = (elo.get(no) - 1500.0) if no else 0.0
        f["away_road_streak"] = float(road[a][1]) if road[a][0] == se else 0.0
        # early-season record effects the market is known to overreact to (winless/unbeaten starts,
        # records that outrun point differential, ATS and over/under streaks) and trips abroad
        for side, tm in (("h", h), ("a", a)):
            s_ = rec.get(tm)
            if s_ is None or s_[0] != se:
                s_ = (se, 0, 0, 0, 0.0, 0.0, 0, 0, 0, 0)
            _, w_, l_, t_, pf_, pa_, cv_, nc_, ov_, un_ = s_
            gp = w_ + l_ + t_
            f[f"winless_{side}"] = float(gp >= 2 and w_ == 0)
            f[f"unbeaten_{side}"] = float(gp >= 2 and l_ == 0)
            # late-season motivation proxies: likely eliminated / likely clinched (Week 18 rest risk)
            wpct = (w_ + 0.5 * t_) / gp if gp else 0.5
            late = _fnum(r.week, 0) >= 13 and str(getattr(r, "game_type", "REG")) == "REG" and gp >= 11
            f[f"elim_{side}"] = float(late and wpct <= 0.35)
            f[f"clinch_{side}"] = float(late and wpct >= 0.80)
            if gp and pf_ + pa_ > 0:
                pyth = pf_ ** 2.37 / (pf_ ** 2.37 + pa_ ** 2.37)
                f[f"record_luck_{side}"] = ((w_ + 0.5 * t_) / gp - pyth) * gp / (gp + 4)
            else:
                f[f"record_luck_{side}"] = 0.0
            f[f"ats_form_{side}"] = (cv_ - nc_) / (cv_ + nc_ + 4)
            f[f"ou_form_{side}"] = (ov_ - un_) / (ov_ + un_ + 4)
            lp = last.get(tm)
            f[f"post_intl_{side}"] = float(lp is not None and lp[0] == se and len(lp) > 3 and lp[3])
            q = lk.get(tm)
            if q is None or q[0] != se:
                q = (se, 0, 0.0, 0.0, 0.0, 0.0, 0.0)
            _, gq, fu, fl_, tk, gv, stv = q
            f[f"fum_luck_{side}"] = ((fu - fl_) - 0.5 * fu) / (fu + 6.0)
            f[f"to_margin_{side}"] = (tk - gv) / (gq + 3.0)
            f[f"st_epa_{side}"] = stv / (gq + 4.0)
            z = pz.get(tm)
            if z is None or z[0] != se:
                z = (se,) + (0.0,) * 10
            _, dbo, sko, pro, dbd, skd, prd, c3, a3, eds, edn = z
            lp_ = lgp[0] / lgp[1] if lgp[1] else 0.13
            ls_ = lgp[2] / lgp[0] if lgp[0] else 0.45
            l3 = lgp[3] / lgp[4] if lgp[4] else 0.39
            le = lgp[5] / lgp[6] if lgp[6] else 0.45
            f[f"press_allow_{side}"] = (pro - lp_ * dbo) / (dbo + 60.0)
            f[f"press_gen_{side}"] = (prd - lp_ * dbd) / (dbd + 60.0)
            f[f"sack_luck_{side}"] = (skd - ls_ * prd) / (prd + 20.0) - (sko - ls_ * pro) / (pro + 20.0)
            f[f"third_luck_{side}"] = (c3 - l3 * a3) / (a3 + 25.0) - 1.2 * (eds - le * edn) / (edn + 80.0)
        # coaches
        for side, c, tm in (("h", hc, h), ("a", ac, a)):
            n = coach_games[(c, tm)]
            f[f"coach_tenure_{side}"] = np.log1p(n)
            f[f"new_coach_{side}"] = float(n < 8)
            s, k = coach_ats[c]
            f[f"coach_resid_{side}"] = _shrink(s, k, 100)
            go, att = coach_4th[c]
            lr = lg_4th[0] / lg_4th[1] if lg_4th[1] else 0.3
            f[f"coach_aggr_{side}"] = (go + 20 * lr) / (att + 20) - lr
        # referee
        rf = r.referee if isinstance(r.referee, str) and r.referee else None
        if rf:
            n, tres, mres, ps, pn = ref[rf]
            f["ref_total_resid"] = _shrink(tres, n, 80)
            f["ref_margin_resid"] = _shrink(mres, n, 80)
            lp_ = lg_pen[0] / lg_pen[1] if lg_pen[1] else 0.0
            f["ref_pen_rate"] = (ps + 80 * lp_) / (pn + 80) - lp_ if lg_pen[1] else 0.0
        else:
            f["ref_total_resid"] = f["ref_margin_resid"] = f["ref_pen_rate"] = 0.0
        # head-to-head and venue-split ATS (almost surely noise; kept so the backtest can prove it)
        pair = tuple(sorted((h, a)))
        sign = 1.0 if pair[0] == h else -1.0
        recent = [x for x in h2h[pair] if x[0] >= se - 4]
        f["h2h_resid"] = sign * _shrink(sum(x[1] for x in recent), len(recent), 6)
        f["h2h_total_resid"] = _shrink(sum(x[2] for x in recent), len(recent), 6)
        ha = [x[1] for x in home_ats[h] if x[0] >= se - 1]
        ra = [x[1] for x in road_ats[a] if x[0] >= se - 1]
        f["home_ats_resid"] = _shrink(sum(ha), len(ha), 40)
        f["road_ats_resid"] = _shrink(sum(ra), len(ra), 40)
        feats.append(f)

        # ---------- update state with the result ----------
        if not np.isfinite(_fnum(r.result)):
            continue
        margin = float(r.result)
        ot = _fnum(r.overtime, 0.0) > 0
        elo.update(h, a, margin, neutral)
        last[h], last[a] = (se, margin, ot, neutral), (se, -margin, ot, neutral)
        tot_ = _fnum(r.total)
        slc, tlc = _fnum(r.spread_line), _fnum(r.total_line)
        for tm, m_ in ((h, margin), (a, -margin)):
            s_ = rec.get(tm)
            if s_ is None or s_[0] != se:
                s_ = (se, 0, 0, 0, 0.0, 0.0, 0, 0, 0, 0)
            _, w_, l_, t_, pf_, pa_, cv_, nc_, ov_, un_ = s_
            w_, l_, t_ = w_ + (m_ > 0), l_ + (m_ < 0), t_ + (m_ == 0)
            if np.isfinite(tot_):
                pf_, pa_ = pf_ + (tot_ + m_) / 2, pa_ + (tot_ - m_) / 2
            if np.isfinite(slc):
                ats = (m_ - slc) if tm == h else (m_ + slc)      # spread_line > 0 means home favored
                cv_, nc_ = cv_ + (ats > 0), nc_ + (ats < 0)
            if np.isfinite(tlc) and np.isfinite(tot_):
                ov_, un_ = ov_ + (tot_ > tlc), un_ + (tot_ < tlc)
            rec[tm] = (se, w_, l_, t_, pf_, pa_, cv_, nc_, ov_, un_)
            x = tx.get((r.game_id, tm))
            if x is not None:
                q = lk.get(tm)
                if q is None or q[0] != se:
                    q = (se, 0, 0.0, 0.0, 0.0, 0.0, 0.0)
                lk[tm] = (se, q[1] + 1, q[2] + x[0], q[3] + x[1], q[4] + x[2], q[5] + x[3], q[6] + x[4])
                if len(x) > 5:
                    z = pz.get(tm)
                    if z is None or z[0] != se:
                        z = (se,) + (0.0,) * 10
                    pz[tm] = (se, z[1] + x[5], z[2] + x[6], z[3] + x[7], z[4] + x[8], z[5] + x[9], z[6] + x[10],
                              z[7] + x[11], z[8] + x[12], z[9] + x[13], z[10] + x[14])
                    for i_, v_ in enumerate((x[7], x[5], x[6], x[11], x[12], x[13], x[14])):
                        lgp[i_] += 0.5 * v_              # each game counted from both teams' rows
        prev = road[a][1] if road[a][0] == se else 0
        road[a] = (se, 0 if neutral else prev + 1)
        road[h] = (se, 0)
        coach_games[(hc, h)] += 1
        coach_games[(ac, a)] += 1
        last_coach[h], last_coach[a] = hc, ac
        sl, tl = _fnum(r.spread_line), _fnum(r.total_line)
        # residuals vs the closing line, net of the league-wide drift (e.g. scoring trends, HFA decline),
        # so these features don't just act as a clock
        mres = margin - sl - lg_res[0] if np.isfinite(sl) else np.nan
        tres = float(r.total) - tl - lg_res[1] if np.isfinite(tl) and np.isfinite(_fnum(r.total)) else np.nan
        if np.isfinite(mres):
            lg_res[0] += 0.01 * mres
        if np.isfinite(tres):
            lg_res[1] += 0.01 * tres
        if np.isfinite(mres):
            coach_ats[hc][0] += mres
            coach_ats[hc][1] += 1
            coach_ats[ac][0] -= mres
            coach_ats[ac][1] += 1
            home_ats[h].append((se, mres))
            road_ats[a].append((se, -mres))
        for c, tm in ((hc, h), (ac, a)):
            go, att = fourth.get((r.game_id, tm), (0.0, 0.0))
            coach_4th[c][0] += go
            coach_4th[c][1] += att
            lg_4th[0] += go
            lg_4th[1] += att
        if rf:
            st = ref[rf]
            if np.isfinite(mres) and np.isfinite(tres):
                st[0] += 1
                st[1] += tres
                st[2] += mres
            if r.game_id in pen:
                st[3] += pen[r.game_id]
                st[4] += 1
                lg_pen[0] += pen[r.game_id]
                lg_pen[1] += 1
        h2h[pair].append((se, sign * mres if np.isfinite(mres) else 0.0, tres if np.isfinite(tres) else 0.0))
    return pd.DataFrame(feats), dict(elo.r)


# ----------------------------------------------------------------------------
# venue, time of day, weather
# ----------------------------------------------------------------------------
def _venue_time_weather(ctx, pbp_wx, forecasts):
    rows = []
    for r in ctx.itertuples(index=False):
        se, h, a = r.season, r.home_team, r.away_team
        ven = resolve_venue(h, se, r.stadium, r.location)
        hv, av = home_venue(h, se), home_venue(a, se)
        ko = kickoff_utc(r.gameday, r.gametime)
        roof = r.roof if isinstance(r.roof, str) and r.roof else ven["roof"]
        surface = r.surface if isinstance(r.surface, str) and r.surface.strip() else ven["surface"]
        indoor = is_indoor(roof)
        if not np.isfinite(indoor):
            indoor = is_indoor(ven["roof"])
        turf = is_turf(surface)
        if not np.isfinite(turf):
            turf = is_turf(ven["surface"])
        f = {"game_id": r.game_id, "venue_name": ven.get("name", ""), "roof_used": roof,
             "surface_used": surface, "indoor": indoor, "turf": turf, "intl": float(ven.get("intl", False)),
             "kickoff_utc": ko.isoformat() if ko else ""}
        # travel and time zones
        f["away_travel_kmi"] = haversine_miles(av["lat"], av["lon"], ven["lat"], ven["lon"]) / 1000
        f["home_travel_kmi"] = haversine_miles(hv["lat"], hv["lon"], ven["lat"], ven["lon"]) / 1000
        if ko is not None:
            v_off = utc_offset_hours(ven["tz"], ko)
            f["tz_shift_away"] = abs(v_off - utc_offset_hours(av["tz"], ko))
            f["body_clock_h"] = local_hour(hv["tz"], ko)
            f["body_clock_a"] = local_hour(av["tz"], ko)
            f["kickoff_et"] = local_hour("America/New_York", ko)
            wd = ko.astimezone(ZoneInfo("America/New_York")).weekday()
        else:
            f["tz_shift_away"], f["body_clock_h"], f["body_clock_a"], f["kickoff_et"] = 0.0, 13.0, 13.0, 13.0
            wd = 6
        f["thu"], f["mon"], f["sat"] = float(wd == 3), float(wd == 0), float(wd == 5)
        f["primetime"] = float(f["kickoff_et"] >= 19.5)
        # altitude
        f["altitude_kft"] = ven["alt"] / 1000
        f["alt_adv_kft"] = (max(ven["alt"] - av["alt"], 0) - max(ven["alt"] - hv["alt"], 0)) / 1000
        f["home_lat"], f["away_lat"] = hv["lat"], av["lat"]
        # weather
        temp, wind, precip, snow, wx_src = np.nan, np.nan, 0.0, 0.0, ""
        if indoor >= 0.5:
            temp, wind, wx_src = 70.0, 0.0, "indoors"
        else:
            fc = (forecasts or {}).get(r.game_id)
            if fc is not None and not np.isfinite(_fnum(r.result)):
                temp, wind = _fnum(fc.get("temp_f")), _fnum(fc.get("wind_mph"))
                precip = float(_fnum(fc.get("precip_in"), 0.0) >= 0.03)
                snow = float(_fnum(fc.get("snow_in"), 0.0) >= 0.05)
                wx_src = "forecast"
            else:
                temp, wind = _fnum(r.temp), _fnum(r.wind)
                txt = pbp_wx.get(r.game_id, "")
                if isinstance(txt, str) and txt:
                    snow = float(bool(SNOW_WORDS.search(txt)))
                    precip = float(bool(RAIN_WORDS.search(txt)) or snow > 0)
                wx_src = "recorded" if np.isfinite(temp) else ""
            if not np.isfinite(temp):
                temp, wx_src = 60.0, (wx_src + " (temp assumed)").strip()
            if not np.isfinite(wind):
                wind = 7.0
        f.update(temp_used=temp, wind_used=wind, precip=precip, snow=snow, wx_source=wx_src)
        rows.append(f)
    out = pd.DataFrame(rows)
    return out


# ----------------------------------------------------------------------------
# main entry
# ----------------------------------------------------------------------------
def build_games(data: dict, cfg, target_season=None, target_week=None, forecasts=None,
                player_overrides=None, qb_overrides=None):
    """Returns (games, info).
    games: one row per completed game (season >= cfg.min_train_season) plus the target
           week's unplayed games, with features, market lines, outcomes and display info.
    info:  notes, projected starters and power ratings for the target week."""
    notes: list[str] = []
    sched = data["schedules"]
    sched = sched[sched["season"] >= cfg.first_season].copy()
    sched["t"] = time_index(sched["season"], sched["week"])
    done = sched["result"].notna()
    if target_season is not None:
        tmask = (sched["season"] == target_season) & (sched["week"] == target_week) & ~done
        t_last = int(time_index(target_season, target_week))
    else:
        tmask = pd.Series(False, index=sched.index)
        t_last = 10 ** 9
    sched["is_target"] = tmask.to_numpy()
    ctx = sched[(done & (sched["t"] <= t_last)) | sched["is_target"]].copy()
    ctx = ctx.sort_values(["t", "gameday", "gametime", "game_id"]).reset_index(drop=True)

    pbp = data.get("pbp")
    if pbp is None or pbp.empty:
        notes.append("Play-by-play unavailable: EPA, pace and QB features fall back to points only.")
        pbp = pd.DataFrame()

    # ---------------- ratings and QBs as of each week ----------------
    tg = build_team_games(sched, pbp if len(pbp) else None)
    engine = RatingEngine(tg, cfg)
    qg, starters = build_qb_games(pbp if len(pbp) else None, sched)
    st_t = starters.merge(sched[["game_id", "t"]], on="game_id", how="left")
    tg_qb = (engine.tg[["game_id", "team"]]
             .merge(starters[["game_id", "team", "qb_id"]].drop_duplicates(["game_id", "team"]),
                    on=["game_id", "team"], how="left")["qb_id"].to_numpy())

    out = ctx[(ctx["season"] >= cfg.min_train_season) | ctx["is_target"]].copy()
    rating_frames, qb_lookup = [], {}
    tg_team = engine.tg["team"].to_numpy()
    for (se, wk), _ in out.groupby(["season", "week"], sort=True):
        R = engine.asof(se, wk)
        if R is None:
            continue
        qv, lg, prior = qb_values_asof(qg, se, wk, cfg)
        qmap = dict(zip(qv["qb_id"], qv["value"]))
        wmap = dict(zip(qv["qb_id"], qv["wplays"]))
        m, w = engine.weights_asof(se, wk)
        vals = pd.Series(tg_qb[m]).map(qmap).fillna(prior).to_numpy(dtype=float)
        agg = pd.DataFrame({"team": tg_team[m], "w": w[m], "wv": w[m] * vals}).groupby("team").sum()
        base = (agg["wv"] / agg["w"].where(agg["w"] > 0)).to_dict()
        R["qb_base"] = R["team"].map(base).fillna(prior)
        R["season"], R["week"] = se, wk
        rating_frames.append(R)
        qb_lookup[(se, wk)] = (qmap, wmap, lg, prior)
    if not rating_frames:
        raise RuntimeError("Not enough completed games to build ratings. Check first_season / data.")
    ratings = pd.concat(rating_frames, ignore_index=True)
    out = out[out.set_index(["season", "week"]).index.isin(list(qb_lookup))].copy()

    # ---------------- starters ----------------
    target = out[out["is_target"]]
    proj = pd.DataFrame(columns=["game_id", "team", "side", "qb_id", "qb_name", "qb_source"])
    if len(target):
        tq = qb_lookup[(target_season, target_week)]
        proj = project_starters(target, st_t, qg, data.get("injuries"), data.get("rosters"), qb_overrides, tq[1])
    hist_st = starters[["game_id", "team", "qb_id", "qb_name"]].drop_duplicates(["game_id", "team"]).copy()
    hist_st["qb_source"] = "actual starter"
    all_st = pd.concat([hist_st, proj.drop(columns=["side"])], ignore_index=True).drop_duplicates(["game_id", "team"], keep="last")

    for side, col in (("h", "home_team"), ("a", "away_team")):
        rr = ratings.rename(columns={c: f"{side}_{c}" for c in RATING_COLS}).rename(columns={"team": col})
        out = out.merge(rr[["season", "week", col] + [f"{side}_{c}" for c in RATING_COLS]],
                        on=["season", "week", col], how="left")
        s2 = all_st.rename(columns={"team": col, "qb_id": f"{side}_qb_id", "qb_name": f"{side}_qb_name_used",
                                    "qb_source": f"{side}_qb_source"})
        out = out.merge(s2, on=["game_id", col], how="left")

    qv_h, qv_a, new_h, new_a, lgs = [], [], [], [], []
    for r in out[["season", "week", "h_qb_id", "a_qb_id"]].itertuples(index=False):
        qmap, wmap, lg, prior = qb_lookup[(r.season, r.week)]
        vh = qmap.get(r.h_qb_id, prior) if isinstance(r.h_qb_id, str) else prior
        va = qmap.get(r.a_qb_id, prior) if isinstance(r.a_qb_id, str) else prior
        qv_h.append(vh)
        qv_a.append(va)
        new_h.append(float(wmap.get(r.h_qb_id, 0.0) < 100))
        new_a.append(float(wmap.get(r.a_qb_id, 0.0) < 100))
        lgs.append(lg)
    out["h_qb_value"], out["a_qb_value"], out["qb_lg"] = qv_h, qv_a, lgs
    out["h_qb_new"], out["a_qb_new"] = new_h, new_a

    # ---------------- availability ----------------
    av, av_notes = compute_availability(data.get("snaps"), ctx, data.get("rosters"), data.get("injuries"),
                                        player_overrides, cfg)
    notes += av_notes
    for side, col in (("h", "home_team"), ("a", "away_team")):
        a2 = av.rename(columns={"team": col, **{f"miss_{g}": f"{side}_miss_{g}" for g in GROUPS},
                                "miss_names": f"{side}_miss_names"})
        out = out.merge(a2, on=["game_id", col], how="left")

    # ---------------- roster continuity (share of last season's snaps still on the roster) ----------------
    cont = compute_continuity(data.get("snaps"), data.get("rosters_all", data.get("rosters")), out)
    for side, col in (("h", "home_team"), ("a", "away_team")):
        c2 = cont.rename(columns={"team": col, "off_cont": f"{side}_off_cont", "def_cont": f"{side}_def_cont"})
        out = out.merge(c2, on=["game_id", col], how="left")

    # ---------------- preseason win totals (pages you saved into win_totals/; inert without them) ----------------
    from .wintotals import load_win_totals
    wt, wt_notes = load_win_totals(getattr(cfg, "win_totals_dir", "win_totals"))
    for side, col in (("h", "home_team"), ("a", "away_team")):
        if len(wt):
            w2 = wt.rename(columns={"team": col, "wt_rating": f"{side}_wt_rating"})[["season", col, f"{side}_wt_rating"]]
            out = out.merge(w2, on=["season", col], how="left")
        else:
            out[f"{side}_wt_rating"] = np.nan
    if len(wt) and target_season is not None and not (wt["season"] == target_season).any():
        notes.append(f"No {target_season} win totals in win_totals/: the preseason prior is off this season.")

    # ---------------- sequential context + venue/weather ----------------
    _, pbp_wx, _ = _pbp_game_extras(pbp) if len(pbp) else ({}, {}, {})
    cx, elo_now = _context(ctx, pbp if len(pbp) else None)
    vw = _venue_time_weather(ctx, pbp_wx, forecasts)
    out = out.merge(cx, on="game_id", how="left").merge(vw, on="game_id", how="left")

    # team home-environment shares (dome team, turf team) per season
    home_rows = vw.merge(ctx[["game_id", "season", "home_team", "location"]], on="game_id")
    home_rows = home_rows[home_rows["location"] != "Neutral"]
    env = home_rows.groupby(["home_team", "season"]).agg(indoor_share=("indoor", "mean"), turf_share=("turf", "mean"))
    env_d = env.to_dict("index")
    for side, col in (("h", "home_team"), ("a", "away_team")):
        keys = list(zip(out[col], out["season"]))
        out[f"{side}_dome_team"] = [float(env_d.get(k, {}).get("indoor_share", 0.0) >= 0.5) for k in keys]
        out[f"{side}_turf_team"] = [env_d.get(k, {}).get("turf_share", 0.5) for k in keys]

    if target_season is not None and len(target) and (out["is_target"] & out["h_off_pts"].isna()).any():
        notes.append("Some target teams have no rating history; they are treated as league average.")

    out = _add_qb_cpoe(out, pbp if len(pbp) else None)
    games = _assemble(out, cfg)
    games = _add_venue_history(games, qg)
    info = {"notes": notes, "starters": proj}
    if len(target):
        info["power"] = _power_table(ratings, target_season, target_week, qb_lookup, proj, elo_now)
        info["qbs"] = _qb_table(qg, target_season, target_week, cfg)
    return games, info


def _assemble(o: pd.DataFrame, cfg) -> pd.DataFrame:
    """Turn raw per-side columns into model features."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", pd.errors.PerformanceWarning)
        return _assemble_inner(o, cfg).copy()


def _assemble_inner(o: pd.DataFrame, cfg) -> pd.DataFrame:
    g = o.copy()
    for side in ("h", "a"):
        for c in RATING_COLS:
            col = f"{side}_{c}"
            if c.startswith(("off_", "def_")):
                g[col] = g[col].fillna(0.0)
        for grp in GROUPS:
            g[f"{side}_miss_{grp}"] = g[f"{side}_miss_{grp}"].fillna(0.0)
    neutral = g["location"].eq("Neutral")
    g["home_ind"] = (~neutral).astype(float)
    g["hfa_trend"] = g["home_ind"] * g["h_hfa_pts"].fillna(0.0)
    # 2020: empty or near-empty stadiums; home teams went 127-128-1, so keep that season from
    # teaching the model a permanent home-field collapse
    g["home_no_fans"] = g["home_ind"] * (g["season"] == 2020).astype(float)
    g["div_game"] = g["div_game"].fillna(0.0).astype(float)
    g["playoff"] = (g["game_type"] != "REG").astype(float)
    g["early_season"] = (g["week"] <= 3).astype(float)

    # team strength (points, EPA/play, success rate)
    g["d_pts_net"] = (g["h_off_pts"] - g["h_def_pts"]) - (g["a_off_pts"] - g["a_def_pts"])
    for k in ("pass", "rush"):
        g[f"d_off_{k}"] = (g[f"h_off_{k}"] - g[f"a_off_{k}"]) * 100
        g[f"d_def_{k}"] = (g[f"h_def_{k}"] - g[f"a_def_{k}"]) * 100
        g[f"sum_off_{k}"] = (g[f"h_off_{k}"] + g[f"a_off_{k}"]) * 100
        g[f"sum_def_{k}"] = (g[f"h_def_{k}"] + g[f"a_def_{k}"]) * 100
    g["d_sr_net"] = ((g["h_off_sr"] - g["h_def_sr"]) - (g["a_off_sr"] - g["a_def_sr"])) * 100
    g["pts_total_pred"] = g["h_off_pts"] + g["a_def_pts"] + g["a_off_pts"] + g["h_def_pts"]
    g["d_wepa_net"] = ((g["h_off_wepao"] - g["h_def_wepad"]) - (g["a_off_wepao"] - g["a_def_wepad"])) * 10
    g["d_ppd_net"] = (g["h_off_ppd"] - g["h_def_ppd"]) - (g["a_off_ppd"] - g["a_def_ppd"])
    g["d_early_net"] = ((g["h_off_early"] - g["h_def_early"]) - (g["a_off_early"] - g["a_def_early"])) * 10
    g["sum_early"] = (g["h_off_early"] + g["a_def_early"] + g["a_off_early"] + g["h_def_early"]) * 10
    g["d_big_net"] = ((g["h_off_big"] - g["h_def_big"]) - (g["a_off_big"] - g["a_def_big"])) * 100
    g["sum_big"] = (g["h_off_big"] + g["a_def_big"] + g["a_off_big"] + g["h_def_big"]) * 100
    # roster continuity, weeks 1-8 only (fades out as this season's games replace last season's in the ratings)
    reg_ = g["game_type"].eq("REG") if "game_type" in g.columns else pd.Series(True, index=g.index)
    ew = ((9 - g["week"]) / 8).clip(0, 1) * reg_.astype(float)
    # unknown continuity (no roster data) -> league average, so the feature is 0 rather than missing
    cont = {c: g[c].fillna(g[c].mean()).fillna(0.6) if c in g.columns else pd.Series(0.6, index=g.index)
            for c in ("h_off_cont", "h_def_cont", "a_off_cont", "a_def_cont")}
    g["d_cont_early"] = ew * ((cont["h_off_cont"] + cont["h_def_cont"]) - (cont["a_off_cont"] + cont["a_def_cont"])) * 10
    lg_o = pd.concat([cont["h_off_cont"], cont["a_off_cont"]]).mean()
    lg_d = pd.concat([cont["h_def_cont"], cont["a_def_cont"]]).mean()
    g["sum_offcont_early"] = ew * (cont["h_off_cont"] + cont["a_off_cont"] - 2 * lg_o) * 10
    g["sum_defcont_early"] = ew * (cont["h_def_cont"] + cont["a_def_cont"] - 2 * lg_d) * 10
    # preseason market prior from win totals, same early-season fade (0 where no total was saved)
    hw = g["h_wt_rating"].fillna(0.0) if "h_wt_rating" in g.columns else 0.0
    aw = g["a_wt_rating"].fillna(0.0) if "a_wt_rating" in g.columns else 0.0
    g["d_wt_early"] = ew * (hw - aw)
    g["sum_wt_early"] = ew * (hw + aw)
    g["ppd_total_pred"] = g["h_off_ppd"] + g["a_def_ppd"] + g["a_off_ppd"] + g["h_def_ppd"]
    g["drives_total"] = g["h_off_drv"] + g["a_def_drv"] + g["a_off_drv"] + g["h_def_drv"]
    # scoring calendar: points sag in November and in cold-weather December/January games
    reg = g["game_type"].eq("REG") if "game_type" in g.columns else True
    g["wk_nov"] = (g["week"].between(9, 13) & reg).astype(float)
    g["wk_dec"] = ((g["week"] >= 14) | ~reg).astype(float)
    g["sum_wepa"] = (g["h_off_wepao"] + g["a_def_wepad"] + g["a_off_wepao"] + g["h_def_wepad"]) * 10
    g["lg_pts_level"] = 2 * g["h_lg_pts"].fillna(g["h_lg_pts"].median())

    # scheme matchup: pass-rate tendencies x pass/rush efficiency x projected plays
    def exp_pts(o_, d_):
        lg_pass, lg_rush = g["h_lg_pass"].fillna(0.0), g["h_lg_rush"].fillna(0.0)
        pr = (0.58 + g[f"{o_}_off_proe"] + g[f"{d_}_def_proe"]).clip(0.3, 0.8)
        epa = pr * (lg_pass + g[f"{o_}_off_pass"] + g[f"{d_}_def_pass"]) + \
            (1 - pr) * (lg_rush + g[f"{o_}_off_rush"] + g[f"{d_}_def_rush"])
        plays = (g["h_lg_pace"].fillna(63.0) + g[f"{o_}_off_pace"] + g[f"{d_}_def_pace"]).clip(45, 85)
        return epa * plays
    eh, ea = exp_pts("h", "a"), exp_pts("a", "h")
    g["matchup_epa_margin"] = eh - ea
    g["matchup_epa_total"] = eh + ea
    g["d_proe"] = (g["h_off_proe"] - g["a_off_proe"]) * 100
    g["d_pace"] = g["h_off_pace"] - g["a_off_pace"]
    g["pace_total"] = g["h_off_pace"] + g["a_def_pace"] + g["a_off_pace"] + g["h_def_pace"]
    g["proe_sum"] = (g["h_off_proe"] + g["a_off_proe"]) * 100
    g["nohuddle_sum"] = (g["h_off_nh"] + g["a_off_nh"]) * 100

    # quarterbacks (points per game relative to league / relative to team baseline)
    ppg = cfg.qb_plays_per_game
    g["h_qb_rel"] = (g["h_qb_value"] - g["qb_lg"]) * ppg
    g["a_qb_rel"] = (g["a_qb_value"] - g["qb_lg"]) * ppg
    g["h_qb_delta"] = (g["h_qb_value"] - g["h_qb_base"].fillna(g["h_qb_value"])) * ppg
    g["a_qb_delta"] = (g["a_qb_value"] - g["a_qb_base"].fillna(g["a_qb_value"])) * ppg
    g["d_qb_val"] = g["h_qb_rel"] - g["a_qb_rel"]
    g["d_qb_delta"] = g["h_qb_delta"] - g["a_qb_delta"]
    g["d_qb_new"] = g["h_qb_new"] - g["a_qb_new"]
    g["sum_qb_val"] = g["h_qb_rel"] + g["a_qb_rel"]
    g["sum_qb_delta"] = g["h_qb_delta"] + g["a_qb_delta"]

    # injuries (missing regulars by position group)
    for grp in GROUPS:
        g[f"d_miss_{grp}"] = g[f"h_miss_{grp}"] - g[f"a_miss_{grp}"]
    g["off_miss_sum"] = sum(g[f"h_miss_{x}"] + g[f"a_miss_{x}"] for x in OFF_GROUPS)
    g["def_miss_sum"] = sum(g[f"h_miss_{x}"] + g[f"a_miss_{x}"] for x in DEF_GROUPS)

    # rest and travel
    hr, ar = g["home_rest"].fillna(7.0), g["away_rest"].fillna(7.0)
    g["rest_diff"] = (hr - ar).clip(-7, 7)
    g["home_bye"], g["away_bye"] = (hr >= 12).astype(float), (ar >= 12).astype(float)
    g["home_short"], g["away_short"] = (hr <= 5).astype(float), (ar <= 5).astype(float)
    g["d_travel_kmi"] = g["away_travel_kmi"] - g["home_travel_kmi"]
    g["short_x_travel"] = g["away_short"] * g["away_travel_kmi"]
    g["rest_sum_short"] = g["home_short"] + g["away_short"]

    # time of day / body clock
    g["d_body_clock"] = g["body_clock_h"] - g["body_clock_a"]
    g["west_early"] = (g["body_clock_a"] <= 10.5).astype(float) - (g["body_clock_h"] <= 10.5).astype(float)
    g["prime_x_clock"] = g["primetime"] * g["d_body_clock"]

    # weather
    wind_x = (g["wind_used"] - 8).clip(lower=0) / 10
    g["wind_x_passdiff"] = wind_x * g["d_off_pass"]
    cold_deg = ((45 - g["temp_used"]).clip(lower=0) / 10) * (1 - g["indoor"])
    g["dome_team_cold"] = (g["a_dome_team"] - g["h_dome_team"]) * cold_deg
    # outdoor teams playing under a roof: passing efficiency tends to tick up (the reverse of dome teams in the cold)
    ind = g["indoor"].fillna(0.0) if "indoor" in g.columns else 0.0
    g["outdoor_in_dome"] = ind * ((1 - g["a_dome_team"]) - (1 - g["h_dome_team"]))
    g["outdoor_in_dome_sum"] = ind * ((1 - g["a_dome_team"]) + (1 - g["h_dome_team"]))
    warm_a = ((g["away_lat"] < 34.5) | (g["a_dome_team"] > 0)).astype(float)
    warm_h = ((g["home_lat"] < 34.5) | (g["h_dome_team"] > 0)).astype(float)
    g["warm_team_cold"] = (warm_a - warm_h) * cold_deg
    g["wind_over10"] = (g["wind_used"] - 10).clip(lower=0)
    g["wind_over15"] = (g["wind_used"] - 15).clip(lower=0)
    g["cold"] = (40 - g["temp_used"]).clip(lower=0)
    g["heat"] = (g["temp_used"] - 85).clip(lower=0)

    # surface
    g["away_surface_mismatch"] = (g["turf"] - g["a_turf_team"]).abs()
    g["home_surface_mismatch"] = (g["turf"] - g["h_turf_team"]).abs()

    # coaching / officials / history / situational
    g["d_coach_resid"] = g["coach_resid_h"] - g["coach_resid_a"]
    g["d_new_coach"] = g["new_coach_h"] - g["new_coach_a"]
    g["d_coach_tenure"] = g["coach_tenure_h"] - g["coach_tenure_a"]
    g["coach_aggr_sum"] = (g["coach_aggr_h"] + g["coach_aggr_a"]) * 10
    g["sum_new_coach"] = g["new_coach_h"] + g["new_coach_a"]
    g["d_prev_margin"] = (g["prev_margin_h"] - g["prev_margin_a"]).clip(-35, 35) / 10
    g["d_next_opp_elo"] = (g["next_opp_elo_h"] - g["next_opp_elo_a"]) / 100
    g["early_x_strength"] = g["early_season"] * g["d_pts_net"]
    # pass-rush matchup: home rush vs away protection, and the reverse
    mh = g["press_gen_h"] + g["press_allow_a"]
    ma = g["press_gen_a"] + g["press_allow_h"]
    g["d_press"], g["sum_press"] = (mh - ma) * 10, (mh + ma) * 10
    g["d_sack_luck"] = g["sack_luck_h"] - g["sack_luck_a"]
    g["d_3rd_luck"] = (g["third_luck_h"] - g["third_luck_a"]) * 10
    g["d_elim"] = g["elim_h"] - g["elim_a"]
    g["sum_elim"] = g["elim_h"] + g["elim_a"]
    w18 = ((g["week"] == 18) & (g.get("game_type", "REG") == "REG")).astype(float)
    g["d_rest_risk"] = (g["clinch_h"] - g["clinch_a"]) * w18
    g["sum_3rd_luck"] = (g["third_luck_h"] + g["third_luck_a"]) * 10
    for k in ("winless", "unbeaten", "record_luck", "ats_form", "post_intl", "fum_luck", "to_margin", "st_epa"):
        g[f"d_{k}"] = g[f"{k}_h"] - g[f"{k}_a"]
    g["sum_ou_form"] = g["ou_form_h"] + g["ou_form_a"]
    g["sum_post_intl"] = g["post_intl_h"] + g["post_intl_a"]
    g["has_ratings"] = g["h_lg_pts"].notna()
    g = _add_market_ratings(g)
    for c in ("h_qb_cpoe", "a_qb_cpoe"):
        if c not in g.columns:
            g[c] = 0.0
    g["d_qb_cpoe"] = (g["h_qb_cpoe"].fillna(0.0) - g["a_qb_cpoe"].fillna(0.0)) / 5
    g["sum_qb_cpoe"] = (g["h_qb_cpoe"].fillna(0.0) + g["a_qb_cpoe"].fillna(0.0)) / 5
    return g.reset_index(drop=True)


def _add_venue_history(g, qg, season_decay=0.85):
    """Stadium-level history, all as-of kickoff and heavily shrunk (most of it is noise, so the
    backtest's pruning is expected to judge it):
      * venue_total_resid: points scored vs the closing total at this stadium (a 'park factor')
      * home/away_venue_resid: each team's results vs the spread at this stadium
      * home/away_coach_venue_resid: the same for each head coach
      * qb venue and environment splits: each starter's EPA per dropback at this stadium, in the
        cold outdoors and under a roof, relative to his overall level."""
    from collections import defaultdict
    g = g.copy()
    order = g.sort_values(["t", "game_id"]).index
    ven = g["venue_name"].fillna("").where(g["venue_name"].fillna("") != "", g["home_team"]) if "venue_name" in g.columns else g["home_team"]
    st = defaultdict(lambda: [0.0, 0.0, None])          # key -> [sum, n, season last touched]

    def get(key, se):
        v = st[key]
        if v[2] is not None and v[2] < se:
            d = season_decay ** (se - v[2])
            v[0] *= d; v[1] *= d; v[2] = se
        return v

    def add(key, se, x, n=1.0):
        v = get(key, se)
        v[0] += x; v[1] += n; v[2] = se

    ql = {}
    if qg is not None and len(qg):
        for r in qg.itertuples(index=False):
            ql.setdefault((r.game_id, r.team), []).append((r.qb_id, float(r.epa_sum), float(r.plays)))
    cols = {c: np.zeros(len(g)) for c in ("venue_total_resid", "home_venue_resid", "away_venue_resid",
                                          "home_coach_venue_resid", "away_coach_venue_resid",
                                          "qbv_h", "qbv_a", "qbe_h", "qbe_a")}
    pos = {ix: i for i, ix in enumerate(g.index)}
    for ix in order:
        r = g.loc[ix]
        i, se, v = pos[ix], int(r["season"]), ven.loc[ix]
        h, a = r["home_team"], r["away_team"]
        hc, ac = r.get("home_coach_used", None), r.get("away_coach_used", None)
        indoor = float(r.get("indoor", 0) or 0) >= 0.5
        temp = r.get("temp_used", np.nan)
        env = "dome" if indoor else ("cold" if np.isfinite(temp) and temp <= 40 else None)
        x = get(("vt", v), se); cols["venue_total_resid"][i] = x[0] / (x[1] + 40.0)
        x = get(("tv", h, v), se); cols["home_venue_resid"][i] = x[0] / (x[1] + 30.0)
        x = get(("tv", a, v), se); cols["away_venue_resid"][i] = x[0] / (x[1] + 12.0)
        x = get(("cv", hc, v), se); cols["home_coach_venue_resid"][i] = x[0] / (x[1] + 30.0)
        x = get(("cv", ac, v), se); cols["away_coach_venue_resid"][i] = x[0] / (x[1] + 10.0)
        for side, qid in (("h", r.get("h_qb_id")), ("a", r.get("a_qb_id"))):
            if not isinstance(qid, str):
                continue
            tot = get(("qa", qid), se)
            mu = tot[0] / tot[1] if tot[1] > 0 else 0.0
            x = get(("qv", qid, v), se)
            cols[f"qbv_{side}"][i] = (x[0] - mu * x[1]) / (x[1] + 150.0)
            if env:
                x = get(("qe", qid, env), se)
                cols[f"qbe_{side}"][i] = (x[0] - mu * x[1]) / (x[1] + 200.0)
        # ---- update with this game's result ----
        res, tl, sl, total = r.get("result"), r.get("total_line"), r.get("spread_line"), r.get("total")
        if not (isinstance(res, (int, float)) and np.isfinite(res)):
            continue
        if np.isfinite(sl):
            m = float(res) - float(sl)
            add(("tv", h, v), se, m); add(("tv", a, v), se, -m)
            add(("cv", hc, v), se, m); add(("cv", ac, v), se, -m)
        if np.isfinite(tl) and np.isfinite(total):
            add(("vt", v), se, float(total) - float(tl))
        for team in (h, a):
            for qid, e_, n_ in ql.get((r["game_id"], team), []):
                if n_ <= 0:
                    continue
                add(("qa", qid), se, e_, n_); add(("qv", qid, v), se, e_, n_)
                if env:
                    add(("qe", qid, env), se, e_, n_)
    for c, arr in cols.items():
        g[c] = arr
    # sign conventions: positive = good for the home team
    g["away_venue_resid"] = -g["away_venue_resid"]
    g["away_coach_venue_resid"] = -g["away_coach_venue_resid"]
    g["d_qb_venue"], g["sum_qb_venue"] = (g["qbv_h"] - g["qbv_a"]) * 10, (g["qbv_h"] + g["qbv_a"]) * 10
    g["d_qb_env"], g["sum_qb_env"] = (g["qbe_h"] - g["qbe_a"]) * 10, (g["qbe_h"] + g["qbe_a"]) * 10
    return g


def _add_market_ratings(g, half_life=6.0, lam=3.0):
    """Market-implied team ratings: the spread and total each team 'deserves' according to the
    closing lines of its previous games (a least-squares fit, recent weeks weighted more, last
    season's games discounted). This is the market's own prior on every team, the same idea as
    preseason win totals, rebuilt from lines nflverse already has."""
    g = g.reset_index(drop=True).copy()
    g["d_mkt_rating"], g["mkt_total_pred"] = 0.0, 0.0
    if not {"spread_line", "total_line"}.issubset(g.columns):
        return g
    teams = sorted(set(g["home_team"]) | set(g["away_team"]))
    ix = {t: i for i, t in enumerate(teams)}
    k = len(teams)
    hist = g[g["spread_line"].notna() & g["total_line"].notna()]
    H = hist["home_team"].map(ix).to_numpy(); A = hist["away_team"].map(ix).to_numpy()
    T = hist["t"].to_numpy(float); S = hist["season"].to_numpy()
    home = (hist["location"] != "Neutral").to_numpy(float)
    ys, yt = hist["spread_line"].to_numpy(float), hist["total_line"].to_numpy(float)
    Xs = np.zeros((len(hist), k + 1)); Xs[np.arange(len(hist)), H] += 1; Xs[np.arange(len(hist)), A] -= 1; Xs[:, k] = home
    Xt = np.zeros((len(hist), k + 1)); Xt[np.arange(len(hist)), H] += 1; Xt[np.arange(len(hist)), A] += 1; Xt[:, k] = 1
    out_s, out_t = np.zeros(len(g)), np.zeros(len(g))
    for (se, t0), idx in g.groupby(["season", "t"]).groups.items():
        m = (T < t0) & (S >= se - 1)
        if m.sum() < 40:
            continue
        w = 0.5 ** ((t0 - T[m]) / half_life) * np.where(S[m] < se, 0.6, 1.0)
        pen = lam * np.eye(k + 1); pen[k, k] = 1e-6
        Xw = Xs[m] * w[:, None]
        bs = np.linalg.solve(Xs[m].T @ Xw + pen, Xw.T @ ys[m])
        Xw2 = Xt[m] * w[:, None]
        mu = np.average(yt[m], weights=w)
        bt = np.linalg.solve(Xt[m].T @ Xw2 + pen, Xw2.T @ (yt[m] - mu))
        rows = g.loc[idx]
        hi, ai = rows["home_team"].map(ix).to_numpy(), rows["away_team"].map(ix).to_numpy()
        hm = (rows["location"] != "Neutral").to_numpy(float)
        out_s[g.index.get_indexer(idx)] = bs[hi] - bs[ai] + bs[k] * hm
        out_t[g.index.get_indexer(idx)] = mu + bt[hi] + bt[ai]
    g["d_mkt_rating"] = out_s
    g["mkt_total_pred"] = np.where(out_t > 0, out_t - np.nanmean(np.where(out_t > 0, out_t, np.nan)), 0.0)
    return g


def _add_qb_cpoe(out, pbp, half_life=26.0, prior_att=150.0):
    """Each projected starter's completion percentage over expected, recency-weighted and shrunk
    toward zero. CPOE is among the most stable QB stats; with EPA it forms the best public QB composite."""
    out = out.copy()
    out["h_qb_cpoe"], out["a_qb_cpoe"] = 0.0, 0.0
    if pbp is None or len(pbp) == 0 or "cpoe" not in pbp.columns or "passer_id" not in pbp.columns:
        return out
    p = pbp[pbp["cpoe"].notna() & pbp["passer_id"].notna()]
    if p.empty:
        return out
    q = p.groupby(["passer_id", "season", "week"])["cpoe"].agg(["sum", "size"]).reset_index()
    q["t"] = time_index(q["season"], q["week"])
    q = q.sort_values(["passer_id", "t"])
    state = {}
    rows = []
    for r in q.itertuples(index=False):
        s_, n_, t_ = state.get(r.passer_id, (0.0, 0.0, r.t))
        d = 0.5 ** ((r.t - t_) / half_life)
        s_, n_ = s_ * d + r[3], n_ * d + r[4]
        state[r.passer_id] = (s_, n_, r.t)
        rows.append((r.passer_id, r.t, s_, n_))
    tl = pd.DataFrame(rows, columns=["qb_id", "t_last", "s", "n"]).sort_values("t_last")
    for side in ("h", "a"):
        col = f"{side}_qb_id"
        if col not in out.columns:
            continue
        qq = out[[col, "t"]].rename(columns={col: "qb_id"}).reset_index()
        qq = qq[qq["qb_id"].notna()].sort_values("t")
        qq["qb_id"] = qq["qb_id"].astype(str)
        qq["t_q"] = qq["t"].astype(float) - 0.5            # strictly before this game
        tl2 = tl.assign(t_last=tl["t_last"].astype(float), qb_id=tl["qb_id"].astype(str))
        mm = pd.merge_asof(qq, tl2, left_on="t_q", right_on="t_last", by="qb_id", direction="backward")
        d = 0.5 ** ((mm["t"] - mm["t_last"]) / half_life)
        val = (mm["s"] * d) / (mm["n"] * d + prior_att)
        out.loc[mm["index"].to_numpy(), f"{side}_qb_cpoe"] = val.fillna(0.0).to_numpy()
    return out


def _qb_table(qg, season, week, cfg):
    """QB values going into the target week, in points per game vs league average, with each QB's latest team."""
    qv, lg, prior = qb_values_asof(qg, season, week, cfg)
    if qv.empty:
        return qv
    last = qg.sort_values("t").groupby("qb_id").agg(team=("team", "last"), last_season=("season", "last"),
                                                    games=("game_id", "nunique"))
    qv = qv.merge(last, left_on="qb_id", right_index=True, how="left")
    qv = qv[(qv["last_season"] >= season - 1) & (qv["wplays"] >= 50)].copy()
    qv["pts_vs_avg"] = (qv["value"] - lg) * cfg.qb_plays_per_game
    return qv.sort_values("pts_vs_avg", ascending=False)[
        ["qb_id", "qb_name", "team", "pts_vs_avg", "value", "wplays", "games", "last_season"]].reset_index(drop=True)


def _power_table(ratings, season, week, qb_lookup, proj, elo_now):
    R = ratings[(ratings["season"] == season) & (ratings["week"] == week)].copy()
    qmap, wmap, lg, prior = qb_lookup[(season, week)]
    R["net_pts"] = R["off_pts"] - R["def_pts"]
    R["off_epa_pass"], R["def_epa_pass"] = R["off_pass"], R["def_pass"]
    tq = proj.set_index("team") if len(proj) else pd.DataFrame()
    R["proj_qb"] = R["team"].map(tq["qb_name"]) if len(tq) else ""
    R["qb_vs_base_pts"] = [((qmap.get(tq.loc[t, "qb_id"], prior) if t in tq.index else np.nan) - b) * 38
                           if t in tq.index else np.nan for t, b in zip(R["team"], R["qb_base"])]
    R["elo"] = R["team"].map(elo_now)
    R = R[R["rating_weight"] > 0].sort_values("net_pts", ascending=False)
    return R[["team", "net_pts", "off_pts", "def_pts", "off_epa_pass", "def_epa_pass", "elo",
              "proj_qb", "qb_vs_base_pts"]].reset_index(drop=True)
