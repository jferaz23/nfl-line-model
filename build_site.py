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
    if live:
        t = _ts(live.get("checked"))
        add("Line watch in the last 3 hours", t and NOW - t < timedelta(hours=3),
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
    tracker = build_tracker(weeks, finals, closes, kickoffs, teams)
    bt = backtest_summary()
    checks = health(cur, live, sim, bt, tracker)

    site = dict(
        built=NOW.isoformat(), season=season, week=cur["week"],
        weeks={f"{w['season']}-{w['week']:02d}": w for w in weeks},
        live=live, schedule=sched, season_sim=sim, tracker=tracker, backtest=bt,
        lines=line_history(lines, cur), my_bets=my_bets(finals_by_key),
        checks=checks, checks_ok=all(c[1] for c in checks), audit=_load(ART / "data_audit.json"),
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
    print(f"public/ built: {season} week {cur['week']}, {len(weeks)} week(s), {len(tracker['picks'])} logged picks, "
          f"checks {n_ok}/{len(checks)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
