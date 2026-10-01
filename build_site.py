#!/usr/bin/env python
"""Build the website (public/) from the saved run outputs. No model code, no downloads: fast
enough to run after every line watch.

Inputs
    site_data/week_<s>_<w>.json   weekly run payloads (run_week.py)
    site_data/schedule_<s>.json   season results, closing lines, head-to-head
    site_data/season_<s>.json     season simulation
    site_data/live.json           ESPN scoreboard (line_watch.py)
    artifacts/lines/espn_lines.csv            line history (line watch)
    artifacts/tracker/model_picks.csv         every run's picks (graded here)
    artifacts/backtest_oos.csv, calibration.json   backtest (backtest.py)
    overrides/my_bets.csv                     your own bets (optional)
Output
    public/  = web/ (page, script, styles) + public/data/site.js (window.SITE = {...})

    python build_site.py
"""
from __future__ import annotations

import json
import math
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from nflmodel.picks import read_log

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "site_data"
ART = ROOT / "artifacts"
WEB = ROOT / "web"
PUBLIC = ROOT / "public"
NOW = datetime.now(timezone.utc)


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if not math.isfinite(f) else round(f, 4)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.isoformat()
    if not isinstance(o, str) and o is not None and pd.api.types.is_scalar(o) and pd.isna(o):
        return None
    return o


def _load(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _ts(s) -> datetime | None:
    try:
        t = pd.Timestamp(s)
        return (t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")).to_pydatetime()
    except Exception:
        return None


# ----------------------------------------------------------------------------- grading
BET_RE = re.compile(r"^(?P<team>[A-Z]{2,3}) (?P<pts>pk|[+\-−]?\d+(?:\.\d+)?)$")


def parse_bet(label: str, home: str, away: str):
    """-> (market, side, line) where side is home/away/over/under and line is the handicap or total."""
    label = str(label).strip()
    if label.startswith(("Over ", "Under ")):
        side, x = label.split(" ", 1)
        return "total", side.lower(), float(x)
    if label.endswith(" to win"):
        t = label[:-7]
        return "moneyline", "home" if t == home else "away", 0.0
    m = BET_RE.match(label)
    if m:
        t, pts = m.group("team"), m.group("pts")
        x = 0.0 if pts == "pk" else float(pts.replace("−", "-"))
        return "spread", "home" if t == home else "away", x
    return None, None, None


def grade(market, side, line, hs, as_):
    """'W' / 'L' / 'P' for a bet given the final score."""
    if hs is None or as_ is None or any(isinstance(v, float) and math.isnan(v) for v in (hs, as_)):
        return None
    if market == "total":
        d = (hs + as_) - line if side == "over" else line - (hs + as_)
    else:
        margin = hs - as_ if side == "home" else as_ - hs
        d = margin + (line if market == "spread" else 0.0)
    return "W" if d > 1e-9 else ("L" if d < -1e-9 else "P")


def units(result, price):
    if result == "W":
        return (price / 100.0) if price > 0 else (100.0 / -price)
    return -1.0 if result == "L" else 0.0


def closing_lines(lines: pd.DataFrame, games: dict) -> dict:
    """game_id -> last ESPN (DraftKings) line logged before kickoff."""
    out = {}
    if lines is None or lines.empty:
        return out
    lines = lines.copy()
    lines["t"] = pd.to_datetime(lines["ts"], utc=True, errors="coerce")
    lines["ko"] = pd.to_datetime(lines["kickoff_utc"], utc=True, errors="coerce")
    pre = lines[(lines["t"] < lines["ko"]) & lines["home_spread"].notna()]
    last = pre.sort_values("t").groupby(["season", "week", "home_team", "away_team"]).tail(1)
    key = {(g["season"], g["week"], g["home_team"], g["away_team"]): gid for gid, g in games.items()}
    for r in last.itertuples(index=False):
        gid = key.get((int(r.season), int(r.week), r.home_team, r.away_team))
        if gid:
            out[gid] = dict(home_spread=float(r.home_spread), total=float(r.total) if pd.notna(r.total) else None,
                            ts=r.ts)
    return out


def clv(market, side, line, close):
    if not close:
        return None
    if market == "spread":
        c = close["home_spread"] if side == "home" else -close["home_spread"]
        return line - c
    if market == "total" and close.get("total") is not None:
        return (close["total"] - line) if side == "over" else (line - close["total"])
    return None


def _f(x):
    try:
        x = float(x)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _tier(r) -> int:
    """Logged tier. Rows from before tiers existed cannot show the model agreed, so they top out at Value."""
    t = _f(getattr(r, "tier", None))
    if t is not None:
        return int(t)
    return 2 if (bool(r.is_play) or float(r.ev) >= 0.01) else 1


def build_tracker(weeks: list[dict], finals: dict, closes: dict, kickoffs: dict, teams: dict) -> dict:
    p = ART / "tracker" / "model_picks.csv"
    if not p.exists():
        return dict(picks=[], records={})
    df = pd.read_csv(p, on_bad_lines="skip")
    df["t"] = pd.to_datetime(df["run_at"], utc=True, errors="coerce")
    df["ko"] = df["game_id"].map(lambda g: kickoffs.get(g))
    df["ko"] = pd.to_datetime(df["ko"], utc=True, errors="coerce")
    df = df[df["t"] < df["ko"]]                               # only runs before kickoff count
    df = df.sort_values("t").groupby(["game_id", "market"]).tail(1)
    rows = []
    for r in df.itertuples(index=False):
        h, a = teams.get(r.game_id, (None, None))
        market, side, line = parse_bet(r.bet, h, a)
        if market is None:
            continue
        f = finals.get(r.game_id)
        res = grade(market, side, line, *(f if f else (None, None)))
        rows.append(dict(run_at=r.run_at, season=int(r.season), week=int(r.week), game_id=r.game_id,
                         matchup=f"{a} @ {h}", market=market, bet=r.bet, side=side, line=line,
                         price=float(r.price), p_win=float(r.p_win),
                         p_push=float(r.p_push) if pd.notna(r.p_push) else 0.0, ev=float(r.ev),
                         is_play=bool(r.is_play), stake=float(r.stake) if pd.notna(r.stake) else 0.0,
                         tier=_tier(r), model_edge=_f(getattr(r, "model_edge", None)),
                         result=res, units=units(res, float(r.price)) if res else None,
                         clv=clv(market, side, line, closes.get(r.game_id)),
                         final=list(f) if f else None))
    picks = pd.DataFrame(rows)
    recs = {}
    if len(picks):
        def rec(sub):
            g = sub[sub["result"].notna()]
            w, l, pu = (g["result"] == "W").sum(), (g["result"] == "L").sum(), (g["result"] == "P").sum()
            c = sub["clv"].dropna()
            return dict(w=int(w), l=int(l), p=int(pu), units=float(g["units"].sum()),
                        n=int(len(sub)), graded=int(len(g)), clv_avg=float(c.mean()) if len(c) else None,
                        clv_pos=float((c > 0).mean()) if len(c) else None)
        # the page's picks are the likelier side of each market (not every logged flag)
        main = picks.sort_values("p_win", ascending=False).drop_duplicates(["game_id", "market"])
        uniq = picks.drop_duplicates(["game_id", "market", "bet"])
        for label, sub in (("spread", main[main["market"] == "spread"]), ("total", main[main["market"] == "total"]),
                           ("winner", main[main["market"] == "moneyline"]), ("bets", picks[picks["is_play"]]),
                           ("tier3", uniq[uniq["tier"] == 3]), ("tier2", uniq[uniq["tier"] == 2]),
                           ("tier1", uniq[(uniq["tier"] == 1) & uniq["market"].isin(["spread", "total"])])):
            recs[label] = {"season": rec(sub)}
            for wk, s2 in sub.groupby("week"):
                recs[label][f"w{int(wk)}"] = rec(s2)
    return dict(picks=_clean(picks.to_dict("records")) if len(picks) else [], records=recs)



# ----------------------------------------------------------------------------- track record
def build_record(weeks: list[dict], finals: dict, closes: dict, kickoffs: dict) -> dict:
    """One pick rule, graded two ways and combined:
    backtest   every game 2015 on, picks at the closing line and price (walk-forward model and curves)
    live       the weekly runs' logged picks (last run before kickoff) at DraftKings' price, for games
               the backtest has not covered
    """
    from nflmodel.picks import grade as pgrade, history_rows, profit, rows_summary
    frames = []
    oos_p = ART / "backtest_oos.csv"
    covered = set()
    if oos_p.exists():
        oos = pd.read_csv(oos_p)
        if "home_spread_odds" in oos.columns:
            h = history_rows(oos)
            frames.append(h)
            covered = set(oos["game_id"])
    live_rows = []
    lp = ART / "tracker" / "picks_log.csv"
    if lp.exists():
        lg = read_log(lp)
        lg["t"] = pd.to_datetime(lg["run_at"], utc=True, errors="coerce")
        lg["ko"] = pd.to_datetime(lg["game_id"].map(kickoffs), utc=True, errors="coerce")
        lg = lg[lg["t"] < lg["ko"]].sort_values("t").groupby(["game_id", "market"]).tail(1)
        wind_log = lg[lg["market"] == "wind"]
        lg = lg[lg["market"] != "wind"]
        for r in lg.itertuples(index=False):
            f = finals.get(r.game_id)
            res = pgrade(r.market, r.side, float(r.line), *(f if f else (None, None))) if f else None
            c = clv(r.market, r.side, float(r.line), closes.get(r.game_id)) if r.market in ("spread", "total") else None
            live_rows.append(dict(season=int(r.season), week=int(r.week), game_id=r.game_id, market=r.market,
                                  bet=r.bet, edge=_f(r.edge), chance=_f(r.chance), price=_f(r.price), value=_f(r.value),
                                  breakeven=_f(r.breakeven), highlight=bool(r.highlight),
                                  top=bool(getattr(r, "top", False)) if str(getattr(r, "top", "")) not in ("", "nan") else False, result=res,
                                  units=profit(res, r.price) if res and _f(r.price) else None, clv=c,
                                  matchup=f"{r.away_team} @ {r.home_team}", run_at=r.run_at,
                                  source="backtest-covered" if r.game_id in covered else "live"))
    # wind unders: the last model run before kickoff decides (graded only if the rule was on then)
    from nflmodel.wind import summary as wind_summary
    wh = ART / "wind_history.csv"
    wind_hist = pd.read_csv(wh) if wh.exists() else pd.DataFrame()
    in_hist = set(wind_hist["game_id"]) if len(wind_hist) else set()
    wind_live = []
    if lp.exists() and len(wind_log):
        for r in wind_log.itertuples(index=False):
            on = str(getattr(r, "highlight", "")).lower() == "true" and _f(getattr(r, "line", None)) is not None
            if not on:
                continue
            f = finals.get(r.game_id)
            res = pgrade("total", "under", float(r.line), *f) if f else None
            c = clv("total", "under", float(r.line), closes.get(r.game_id))
            wind_live.append(dict(season=int(r.season), week=int(r.week), game_id=r.game_id, market="wind", bet=r.bet,
                                  chance=_f(r.chance), price=_f(r.price), value=_f(r.value), breakeven=_f(r.breakeven),
                                  wind=_f(getattr(r, "wind", None)), gust=_f(getattr(r, "gust", None)), highlight=True,
                                  top=False, result=res, units=profit(res, r.price) if res and _f(r.price) else None, clv=c,
                                  matchup=f"{r.away_team} @ {r.home_team}", run_at=r.run_at,
                                  source="history-covered" if r.game_id in in_hist else "live"))
    live_rows += wind_live
    live = pd.DataFrame(live_rows)
    if len(live):
        frames.append(live[(live["source"] == "live") & (live["market"] != "wind")])
    allr = pd.concat([f for f in frames if len(f)], ignore_index=True) if frames else pd.DataFrame()
    cur = weeks[-1]["season"]
    teas, expl = {}, []
    if oos_p.exists():
        from nflmodel.picks import explorer, teaser_history
        o2 = pd.read_csv(oos_p)
        if "home_spread_odds" in o2.columns:
            teas, expl = teaser_history(o2), explorer(o2)
    out = dict(teasers=teas, explorer=expl)
    out.update(all=rows_summary(allr) if len(allr) else {}, since=int(allr["season"].min()) if len(allr) else None,
               current_season=cur,
               season=rows_summary(allr[allr["season"] == cur]) if len(allr) else {},
               live=_clean(live.to_dict("records")) if len(live) else [])
    # this season, week by week
    by_week = []
    if len(allr):
        s = allr[allr["season"] == cur]
        for wk, d in s.groupby("week"):
            by_week.append(dict(week=int(wk), **rows_summary(d)["total"]))
    out["by_week"] = by_week
    # wind unders record: archived-forecast history (2018 on) + live picks for games not in it yet
    ws = wind_summary(wind_hist) if len(wind_hist) else {}
    wl = pd.DataFrame([x for x in wind_live if x["source"] == "live"])
    wf = dict((ws.get("forecast") or {}))
    if len(wl):
        g_ = wl[wl["result"].isin(["W", "L", "P"])]
        for k, v in (("w", (g_.result == "W").sum()), ("l", (g_.result == "L").sum()), ("p", (g_.result == "P").sum())):
            wf[k] = int(wf.get(k) or 0) + int(v)
        wf["units"] = float(wf.get("units") or 0) + float(pd.to_numeric(g_["units"], errors="coerce").fillna(0).sum())
        wf["n"] = wf["w"] + wf["l"] + wf["p"]
        wf["pct"] = wf["w"] / max(wf["w"] + wf["l"], 1)
    ws["with_live"] = wf
    out["wind"] = ws
    # the weekly card = Top picks + 2-team underdog teasers + wind unders
    top = ((out.get("all") or {}).get("total") or {}).get("top") or {}
    tz = (teas or {}).get("teasers") or {}
    w = int(top.get("w") or 0) + int(tz.get("w") or 0) + int(wf.get("w") or 0)
    l = int(top.get("l") or 0) + int(tz.get("l") or 0) + int(wf.get("l") or 0)
    pu = int(top.get("p") or 0) + int(wf.get("p") or 0)
    out["card"] = dict(w=w, l=l, p=pu, n=w + l + pu, pct=w / max(w + l, 1),
                       units=float(top.get("units") or 0) + float(tz.get("units") or 0) + float(wf.get("units") or 0),
                       parts=dict(top=top, teasers=tz, wind=wf))
    return _clean(out)


def fill_started(weeks: list[dict], kickoffs: dict):
    """Games already under way drop out of the odds feed; show their last pre-kickoff pick instead."""
    lp = ART / "tracker" / "picks_log.csv"
    if not lp.exists():
        return
    lg = read_log(lp)
    lg["t"] = pd.to_datetime(lg["run_at"], utc=True, errors="coerce")
    lg["ko"] = pd.to_datetime(lg["game_id"].map(kickoffs), utc=True, errors="coerce")
    lg = lg[lg["t"] < lg["ko"]].sort_values("t").groupby(["game_id", "market"]).tail(1)
    for w in weeks:
        have = {(p["game_id"], p["market"]) for p in w.get("picks", [])}
        ids = {g["game_id"] for g in w["games"]}
        add = lg[lg["game_id"].isin(ids)]
        extra = [r for r in _clean(add.drop(columns=["t", "ko"]).to_dict("records")) if (r["game_id"], r["market"]) not in have]
        for r in extra:
            r["from_log"] = True
        w["picks"] = w.get("picks", []) + [r for r in extra if r["market"] != "wind"]
        # wind rows: once a game kicks off, show the last pre-kickoff decision (the odds feed drops the game)
        wu = {x["game_id"]: x for x in w.get("wind_unders", [])}
        for r in _clean(add[add["market"] == "wind"].drop(columns=["t", "ko"]).to_dict("records")):
            cur_ = wu.get(r["game_id"])
            if cur_ is None or (not cur_.get("active") and r.get("highlight") in (True, "True", "true")):
                r["active"] = r.get("highlight") in (True, "True", "true")
                r["highlight"] = r["active"]
                r["from_log"] = True
                wu[r["game_id"]] = r
        w["wind_unders"] = list(wu.values())

# ----------------------------------------------------------------------------- backtest
def backtest_summary() -> dict:
    p = ART / "backtest_oos.csv"
    cal = _load(ART / "calibration.json", {}) or {}
    if not p.exists():
        return dict(available=False)
    b = pd.read_csv(p)
    b = b[b["spread_line"].notna() & b["result"].notna()]
    b["edge_s"] = b["model_margin"] - b["spread_line"]
    b["cov"] = np.sign(b["result"] - b["spread_line"]) * np.sign(b["edge_s"])
    b["edge_t"] = b["model_total"] - b["total_line"]
    b["ou"] = np.sign(b["total"] - b["total_line"]) * np.sign(b["edge_t"])
    by_season = []
    for s, g in b.groupby("season"):
        by_season.append(dict(season=int(s), games=len(g),
                              spread_model=float((g["model_margin"] - g["result"]).abs().mean()),
                              spread_market=float((g["spread_line"] - g["result"]).abs().mean()),
                              total_model=float((g["model_total"] - g["total"]).abs().mean()),
                              total_market=float((g["total_line"] - g["total"]).abs().mean())))
    thresholds = []
    for k in (0, 1, 2, 3, 4, 5, 6):
        s = b[(b["edge_s"].abs() >= k) & (b["cov"] != 0)]
        t = b[(b["edge_t"].abs() >= k) & (b["ou"] != 0)]
        thresholds.append(dict(edge=k, ats_n=len(s), ats_pct=float((s["cov"] > 0).mean()) if len(s) else None,
                               ou_n=len(t), ou_pct=float((t["ou"] > 0).mean()) if len(t) else None))
    # "history": hit rate as a function of the model's disagreement, p = 1 / (1 + exp(-b * |edge|))
    hist = {}
    for mk, e, y in (("spread", "edge_s", "cov"), ("total", "edge_t", "ou")):
        s = b[b[y] != 0]
        x, hit = s[e].abs().to_numpy(), (s[y] > 0).to_numpy(float)
        grid = np.linspace(0.0, 0.2, 401)
        ll = [np.sum(hit * np.log(1 / (1 + np.exp(-g * x))) + (1 - hit) * np.log(1 - 1 / (1 + np.exp(-g * x))))
              for g in grid]
        bh = float(grid[int(np.argmax(ll))])
        bins = []
        for lo, hi in ((0, 1), (1, 2), (2, 3), (3, 4), (4, 6), (6, 99)):
            m = (x >= lo) & (x < hi)
            if m.sum():
                bins.append(dict(lo=lo, hi=hi if hi < 99 else None, n=int(m.sum()), hit=float(hit[m].mean()),
                                 fit=float(np.mean(1 / (1 + np.exp(-bh * x[m]))))))
        hist[mk] = dict(b=bh, bins=bins, n=int(len(s)))
    # flat 1-unit record at -110 of the rule "bet when the model disagrees by 3+ points"
    cum = []
    s = b[(b["edge_s"].abs() >= 3) & (b["cov"] != 0)].sort_values(["season", "week"])
    tot = 0.0
    for r in s.itertuples(index=False):
        tot += (100 / 110) if r.cov > 0 else -1.0
        cum.append([f"{int(r.season)}-{int(r.week):02d}", round(tot, 2)])
    overall = dict(
        games=int(len(b)), seasons=f"{int(b['season'].min())}-{int(b['season'].max())}",
        spread_model=float((b["model_margin"] - b["result"]).abs().mean()),
        spread_market=float((b["spread_line"] - b["result"]).abs().mean()),
        total_model=float((b["model_total"] - b["total"]).abs().mean()),
        total_market=float((b["total_line"] - b["total"]).abs().mean()))
    keep = {k: cal.get(k) for k in ("model_weight_spread", "model_weight_total", "gbm_weight_margin",
                                    "gbm_weight_total", "drop_groups_margin", "drop_groups_total", "seasons")}
    return _clean(dict(available=True, overall=overall, by_season=by_season, thresholds=thresholds,
                       history=hist, cum_units=cum, calibration=keep))


# ----------------------------------------------------------------------------- line history
def line_history(lines: pd.DataFrame, week: dict) -> dict:
    out = {}
    if lines is None or lines.empty or not week:
        return out
    g = lines[(lines["season"] == week["season"]) & (lines["week"] == week["week"])]
    for (h, a), sub in g.groupby(["home_team", "away_team"]):
        gid = next((x["game_id"] for x in week["games"] if x["home_team"] == h and x["away_team"] == a), None)
        if not gid:
            continue
        sub = sub.sort_values("ts")
        pts = [[r.ts, r.home_spread, r.total] for r in sub.itertuples(index=False) if pd.notna(r.home_spread)]
        first = sub.iloc[0]
        out[gid] = dict(points=_clean(pts), open_spread=_clean(first.get("home_spread_open")),
                        open_total=_clean(first.get("total_open")))
    return out


# ----------------------------------------------------------------------------- early-week value
EARLY_EDGE = 3.0


def early_value(week: dict, sched: dict, lines: pd.DataFrame | None, finals: dict) -> dict:
    """Information only: each week's FIRST model run vs DraftKings, spreads EARLY_EDGE+ points off, graded at the
    line and price of that run. Backtest (opening-time model vs openers, 2015-2026): 3+ point gaps won 56.3%
    against nfelo's openers and 56.2% against ESPN BET's (2024-26), vs ~54% for the same bets at the close.
    Unproven at DraftKings, so it is tracked here from 2026 week 4 (when the pick log starts)."""
    from nflmodel.picks import grade as pgrade, profit
    from nflmodel.venues import kickoff_utc
    out = dict(edge=EARLY_EDGE, week=[], record={})
    lp = ART / "tracker" / "picks_log.csv"
    if not lp.exists():
        return out
    sg = {g["game_id"]: g for g in sched.get("games", [])}
    for g in (week or {}).get("games", []):
        sg.setdefault(g["game_id"], g)
    ko = {gid: (kickoff_utc(g.get("gameday"), g.get("gametime")) if g.get("gameday") else None) for gid, g in sg.items()}
    for g in (week or {}).get("games", []):
        if g.get("kickoff_utc"):
            ko[g["game_id"]] = pd.Timestamp(g["kickoff_utc"]).to_pydatetime()
    closes = closing_lines(lines, sg)
    lg = read_log(lp)
    lg = lg[(lg["market"] == "spread") & lg["game_id"].isin(set(sg))].copy()
    lg["t"] = pd.to_datetime(lg["run_at"], utc=True, errors="coerce", format="ISO8601")
    lg["ko"] = pd.to_datetime(lg["game_id"].map(lambda x: ko.get(x)), utc=True, errors="coerce")
    lg = lg[lg["t"] < lg["ko"]].sort_values("t")
    first = lg.groupby("game_id").head(1)
    cur = {g["game_id"]: g for g in (week or {}).get("games", [])}
    rows = []
    for r in first.itertuples(index=False):
        if not (_f(r.edge) is not None and r.edge >= EARLY_EDGE and _f(r.line) is not None):
            continue
        f = finals.get(r.game_id)
        res = pgrade("spread", r.side, float(r.line), *f) if f else None
        kicked = ko.get(r.game_id) is not None and pd.Timestamp(ko[r.game_id]).tz_convert("UTC") <= pd.Timestamp(NOW)
        c = clv("spread", r.side, float(r.line), closes.get(r.game_id)) if kicked else None   # vs the close, once known
        g = cur.get(r.game_id)
        now = None
        if g and g.get("dk_home_spread") is not None:
            now = float(g["dk_home_spread"]) if r.side == "home" else -float(g["dk_home_spread"])
        rows.append(dict(game_id=r.game_id, season=int(r.season), week=int(r.week), matchup=f"{r.away_team} @ {r.home_team}",
                         bet=r.bet, side=r.side, team=r.team, line=float(r.line), price=_f(r.price), edge=_f(r.edge),
                         chance=_f(r.chance), run_at=r.run_at, line_now=now,
                         moved=(float(r.line) - now) if now is not None else None, clv=c, result=res,
                         units=profit(res, r.price) if res and _f(r.price) else None))
    graded = [x for x in rows if x["result"] in ("W", "L", "P")]
    w = sum(x["result"] == "W" for x in graded); l = sum(x["result"] == "L" for x in graded); pu = sum(x["result"] == "P" for x in graded)
    cl = [x["clv"] for x in rows if x["clv"] is not None]
    out["record"] = dict(w=w, l=l, p=pu, n=w + l + pu, pct=w / max(w + l, 1),
                         units=float(sum(x["units"] or 0 for x in graded)), clv=float(np.mean(cl)) if cl else None,
                         clv_n=len(cl), since="2026 week 4")
    out["week"] = [x for x in rows if week and x["season"] == week["season"] and x["week"] == week["week"]]
    out["all"] = rows
    return out


# ----------------------------------------------------------------------------- alerts
def _am(x) -> str:
    x = _f(x)
    return "" if x is None else (f"+{x:.0f}" if x > 0 else f"−{abs(x):.0f}")


def _num(x) -> str:
    x = _f(x)
    return "" if x is None else (f"{x:+g}".replace("-", "−") if x != 0 else "PK")


def alerts(week: dict, lines: pd.DataFrame | None, kickoffs: dict) -> list:
    """What changed this week, newest first.
    pick: a spread/total turning green or Top (or losing it), a green pick switching sides, a wind under
          turning on or off, each with what moved (DraftKings line, price, the model's number, the forecast)
    line: DraftKings' spread or total moving (points, not price-only moves)"""
    out = []
    if not week:
        return out
    ids = {g["game_id"]: g for g in week["games"]}
    mu = lambda gid: f"{ids[gid]['away_team']} @ {ids[gid]['home_team']}"
    tb = lambda v: str(v).strip().lower() == "true"
    lp = ART / "tracker" / "picks_log.csv"
    if lp.exists():
        lg = read_log(lp)
        lg = lg[lg["game_id"].isin(set(ids)) & lg["market"].isin(["spread", "total", "wind"])].copy()
        lg["t"] = pd.to_datetime(lg["run_at"], utc=True, errors="coerce", format="ISO8601")
        lg["ko"] = pd.to_datetime(lg["game_id"].map(kickoffs), utc=True, errors="coerce", format="ISO8601")
        lg = lg[lg["t"] < lg["ko"]].sort_values("t")
        for (gid, mkt), d in lg.groupby(["game_id", "market"], sort=False):
            prev = None
            for r in d.itertuples(index=False):
                cur = dict(bet=str(r.bet), side=str(r.bet).rsplit(" ", 1)[0], green=tb(r.highlight),
                           top=mkt == "spread" and tb(getattr(r, "top", False)), price=_f(r.price),
                           edge=_f(getattr(r, "edge", None)), wind=_f(getattr(r, "wind", None)), gust=_f(getattr(r, "gust", None)))
                name = "wind under" if mkt == "wind" else ("Top pick" if cur["top"] else "green pick")
                ev = None
                if prev is None:
                    if cur["green"]:
                        ev = ("New " + name, f"{cur['bet']} {_am(cur['price'])}")
                else:
                    why = []
                    if cur["bet"] != prev["bet"]:
                        why.append(f"DraftKings line {prev['bet']} → {cur['bet']}")
                    if cur["price"] != prev["price"] and None not in (cur["price"], prev["price"]):
                        why.append(f"price {_am(prev['price'])} → {_am(cur['price'])}")
                    if mkt != "wind" and None not in (cur["edge"], prev["edge"]) and abs(cur["edge"] - prev["edge"]) >= 0.05                             and cur["side"] == prev["side"]:
                        why.append(f"model gap {prev['edge']:.2f} → {cur['edge']:.2f} pts (model update)")
                    if mkt == "wind" and (cur["wind"], cur["gust"]) != (prev["wind"], prev["gust"]) and None not in (cur["wind"], prev["wind"]):
                        why.append(f"forecast wind {prev['wind']:.0f} → {cur['wind']:.0f} mph, gusts "
                                   f"{(prev['gust'] or 0):.0f} → {(cur['gust'] or 0):.0f}")
                    reason = "; ".join(why) or "update"
                    if cur["top"] and not prev["top"]:
                        ev = ("New Top pick", f"{cur['bet']} {_am(cur['price'])}: {reason}")
                    elif prev["top"] and not cur["top"]:
                        ev = ("No longer a Top pick" + ("" if cur["green"] else " or green"), f"{prev['bet']}: {reason}")
                    elif cur["green"] and not prev["green"]:
                        ev = ("New " + name, f"{cur['bet']} {_am(cur['price'])}: {reason}")
                    elif prev["green"] and not cur["green"]:
                        ev = ("No longer a " + ("wind under" if mkt == "wind" else "green pick"), f"{prev['bet']}: {reason}")
                    elif cur["green"] and prev["green"] and cur["side"] != prev["side"]:
                        ev = ("Green pick switched sides", f"{prev['bet']} → {cur['bet']}: {reason}")
                if ev:
                    out.append(dict(id=f"{gid}|{mkt}|{r.run_at}", ts=pd.Timestamp(r.t).isoformat(), game_id=gid, matchup=mu(gid),
                                    kind="pick", level="high", market=mkt, title=ev[0], text=ev[1]))
                prev = cur
    if lines is not None and len(lines):
        g = lines[(lines["season"] == week["season"]) & (lines["week"] == week["week"])].sort_values("ts")
        for (h, a), sub in g.groupby(["home_team", "away_team"]):
            gid = next((x for x, gg in ids.items() if gg["home_team"] == h and gg["away_team"] == a), None)
            if not gid:
                continue
            ko = pd.to_datetime(kickoffs.get(gid), utc=True, errors="coerce")
            ls, lt = None, None
            for r in sub.itertuples(index=False):
                if pd.notna(ko) and pd.to_datetime(r.ts, utc=True) >= ko:
                    break
                s_, t_ = _f(r.home_spread), _f(r.total)
                parts = []
                if s_ is not None and ls is not None and s_ != ls:
                    parts.append(f"spread {h} {_num(ls)} → {_num(s_)}")
                if t_ is not None and lt is not None and t_ != lt:
                    parts.append(f"total {lt:g} → {t_:g}")
                if parts:
                    out.append(dict(id=f"{gid}|line|{r.ts}", ts=pd.Timestamp(r.ts).isoformat(), game_id=gid, matchup=mu(gid),
                                    kind="line", level="info", market="line", title="DraftKings line moved", text="; ".join(parts)))
                ls, lt = (s_ if s_ is not None else ls), (t_ if t_ is not None else lt)
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out[:300]


# ----------------------------------------------------------------------------- checks
def health(week, live, season, bt, tracker) -> list:
    c = []

    def add(name, ok, detail=""):
        c.append([name, bool(ok), detail])
    if week:
        gen = _ts(week["generated"])
        add("Weekly model run in the last 4 days", gen and NOW - gen < timedelta(days=4),
            gen.strftime("%b %d %H:%M UTC") if gen else "never")
        gs = week["games"]
        add("Every game has a model line", all(g.get("model_margin") is not None for g in gs), f"{len(gs)} games")
        n_dk = sum(1 for g in gs if g.get("dk_home_spread") is not None)
        add("Every game has a DraftKings price", n_dk == len(gs), f"{n_dk} of {len(gs)}")
        cred = [n for n in week.get("notes", []) if "credits remaining" in n]
        if cred:
            m = re.search(r"(\d+)", cred[-1])
            add("Odds API credits above 50", m and int(m.group(1)) > 50, cred[-1])
        add("ESPN injury report loaded", any("ESPN injury page:" in n for n in week.get("notes", [])))
        add("Win chances between 0 and 1", all(g.get("p_home_win") is None or 0 <= g["p_home_win"] <= 1 for g in gs))
    else:
        add("Weekly model run found", False)
    if week and week.get("priced_at"):
        pt = _ts(week["priced_at"])
        add("DraftKings prices updated in the last hour", pt and NOW - pt < timedelta(hours=1),
            f"{week.get('price_source', '')}, {pt:%b %d %H:%M UTC}" if pt else "")
    if live:
        t = _ts(live.get("checked"))
        add("Line watch in the last hour", t and NOW - t < timedelta(hours=1),
            t.strftime("%b %d %H:%M UTC") if t else "never")
    else:
        add("Line watch has run", False)
    if season:
        s = sum(t["p_sb"] for t in season["teams"])
        add("Season simulation: Super Bowl chances sum to 100%", abs(s - 1) < 0.01, f"{s:.3f}")
        add("Season simulation: 14 playoff teams", abs(sum(t["p_playoffs"] for t in season["teams"]) - 14) < 0.05)
    if bt.get("available"):
        o = bt["overall"]
        add("Backtest: model within 0.5 pts of the closing spread", o["spread_model"] - o["spread_market"] < 0.5,
            f"{o['spread_model']:.2f} vs {o['spread_market']:.2f}")
    add("Pick log readable", isinstance(tracker.get("picks"), list), f"{len(tracker.get('picks', []))} graded or pending")
    a = _load(ART / "data_audit.json")
    if a:
        if "scores" in a and a["scores"].get("games"):
            s = a["scores"]
            add("Final scores match ESPN", s.get("ok"), f"{s['matched'] - s['n_mismatch']} of {s['games']} games, {s['seasons']}")
        if "lines" in a:
            l = a["lines"]
            add("Closing lines complete and consistent", l.get("ok"),
                f"{l['games']} games; {l['n_favorite_disagree']} favorite conflicts")
        if "venues" in a:
            add("Stadium roof and surface match ESPN", a["venues"].get("ok"), f"{a['venues'].get('stadiums', 0)} stadiums")
        if "injuries" in a and a["injuries"].get("listings"):
            i = a["injuries"]
            add("Injury listings matched to rostered players", i.get("ok"),
                f"{100 * i['matched_share']:.1f}% of {i['listings']}; starting QBs checked")
        if "books" in a:
            add("DraftKings and sharp books returned prices", a["books"].get("ok"), f"{len(a['books'].get('books_seen', {}))} books")
    return c


# ----------------------------------------------------------------------------- my bets
def my_bets(finals_by_key) -> list:
    p = ROOT / "overrides" / "my_bets.csv"
    if not p.exists():
        return []
    try:
        df = pd.read_csv(p, comment="#")
    except Exception:
        return []
    out = []
    for r in df.itertuples(index=False):
        f = finals_by_key.get((int(r.season), int(r.week), str(r.home_team), str(r.away_team)))
        line = float(r.line) if pd.notna(r.line) else 0.0
        res = grade(str(r.market), str(r.side), line, *(f if f else (None, None)))
        stake = float(r.stake) if pd.notna(r.stake) else 0.0
        out.append(dict(season=int(r.season), week=int(r.week), matchup=f"{r.away_team} @ {r.home_team}",
                        market=r.market, side=r.side, line=line, price=float(r.price), stake=stake, result=res,
                        profit=units(res, float(r.price)) * stake if res else None, book=getattr(r, "book", "")))
    return out


# ----------------------------------------------------------------------------- main
def main() -> int:
    weeks = [w for w in (_load(p) for p in sorted(DATA.glob("week_*.json"))) if w and not w.get("demo")]
    if not weeks:
        print("No weekly payloads in site_data/; run run_week.py first.")
        return 1
    weeks.sort(key=lambda w: (w["season"], w["week"]))
    cur = weeks[-1]
    season = cur["season"]
    live = _load(DATA / "live.json")
    sched = _load(DATA / f"schedule_{season}.json", {"games": [], "h2h": {}})
    sim = _load(DATA / f"season_{season}.json")
    lines = pd.read_csv(ART / "lines" / "espn_lines.csv") if (ART / "lines" / "espn_lines.csv").exists() else None

    games, kickoffs, teams = {}, {}, {}
    for w in weeks:
        for g in w["games"]:
            games[g["game_id"]] = g
            kickoffs[g["game_id"]] = g.get("kickoff_utc")
            teams[g["game_id"]] = (g["home_team"], g["away_team"])
    finals, finals_by_key = {}, {}
    for g in sched.get("games", []):
        if g.get("home_score") is not None and g.get("result") is not None:
            finals[g["game_id"]] = (g["home_score"], g["away_score"])
            finals_by_key[(g["season"], g["week"], g["home_team"], g["away_team"])] = finals[g["game_id"]]
    if live:
        for x in live.get("games", []):
            if x.get("completed"):
                k = (x["season"], x["week"], x["home_team"], x["away_team"])
                finals_by_key[k] = (x["home_score"], x["away_score"])
                gid = next((gid for gid, g in games.items()
                            if (g["season"], g["week"], g["home_team"], g["away_team"]) == k), None)
                if gid:
                    finals[gid] = (x["home_score"], x["away_score"])
    closes = closing_lines(lines, games)
    fill_started(weeks, kickoffs)
    record = build_record(weeks, finals, closes, kickoffs)
    tracker = dict(picks=record.get("live", []))
    bt = backtest_summary()
    checks = health(cur, live, sim, bt, tracker)

    site = dict(
        built=NOW.isoformat(), season=season, week=cur["week"],
        weeks={f"{w['season']}-{w['week']:02d}": w for w in weeks},
        live=live, schedule=sched, season_sim=sim, record=record, backtest=bt,
        lines=line_history(lines, cur), my_bets=my_bets(finals_by_key),
        checks=checks, checks_ok=all(c[1] for c in checks), audit=_load(ART / "data_audit.json"),
        budget=_load(ART / "odds_budget.json"), alerts=alerts(cur, lines, kickoffs),
        early=early_value(cur, sched, lines, finals),
    )
    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    shutil.copytree(WEB, PUBLIC)
    (PUBLIC / "data").mkdir(exist_ok=True)
    (PUBLIC / "data" / "site.js").write_text("window.SITE=" + json.dumps(_clean(site), separators=(",", ":")) + ";",
                                             encoding="utf-8")
    (PUBLIC / ".nojekyll").write_text("")
    # cache-bust: browsers otherwise keep yesterday's script and data
    v = NOW.strftime("%Y%m%d%H%M%S")
    idx = PUBLIC / "index.html"
    html = idx.read_text(encoding="utf-8")
    for f in ("style.css", "app.js", "data/site.js"):
        html = html.replace(f'"{f}"', f'"{f}?v={v}"')
    idx.write_text(html, encoding="utf-8")
    n_ok = sum(c[1] for c in checks)
    rt = (record.get("all") or {}).get("total", {}).get("green", {})
    print(f"record since {record.get('since')}: green picks {rt.get('w')}-{rt.get('l')}-{rt.get('p')}, "
          f"{rt.get('units') or 0:+.1f} units")
    print(f"public/ built: {season} week {cur['week']}, {len(weeks)} week(s), {len(tracker['picks'])} logged picks, "
          f"checks {n_ok}/{len(checks)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
