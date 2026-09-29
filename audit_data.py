#!/usr/bin/env python
"""Data audit: cross-check every input against an independent source and write artifacts/data_audit.json
(shown on the site's Info tab).

1. Final scores, 2015 on: nflverse schedules vs ESPN's scoreboard (completed weeks are cached).
2. Closing lines (nflverse): the spread favorite agrees with the moneyline favorite; spreads and
   totals are in plausible ranges; nothing missing for completed games.
3. Venues this season: our roof/surface table vs nflverse's schedule and ESPN's venue (indoor flag).
4. Injuries for the target week: every ESPN listing matches a rostered player on that team; ESPN vs
   the league report where both list a player; no projected starting QB is listed out.
5. Sportsbooks: which configured Odds API books actually returned prices in the latest snapshot.

    python audit_data.py [--config config.json] [--start 2015] [--no-scores]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from nflmodel import espn
from nflmodel.availability import name_key
from nflmodel.config import load_config
from nflmodel.pipeline import load_real, setup_logging
from nflmodel.venues import home_venue, is_indoor, is_turf, norm_team, resolve_venue

log = logging.getLogger("nflmodel")
ROOT = Path(__file__).resolve().parent


# ----------------------------------------------------------------------------- 1. scores
def espn_week(cache: Path, season: int, stype: int, week: int, done: bool) -> list[dict]:
    f = cache / f"{season}_{stype}_{week:02d}.json"
    if done and f.exists():
        return json.loads(f.read_text())
    d = espn._get("scoreboard", {"dates": season, "seasontype": stype, "week": week})
    rows = []
    for ev in d.get("events", []):
        c = (ev.get("competitions") or [{}])[0]
        comp = {x.get("homeAway"): x for x in c.get("competitors", [])}
        st = (ev.get("status") or {}).get("type", {})
        rows.append(dict(date=ev.get("date"), home=norm_team(comp.get("home", {}).get("team", {}).get("abbreviation")),
                         away=norm_team(comp.get("away", {}).get("team", {}).get("abbreviation")),
                         hs=pd.to_numeric(comp.get("home", {}).get("score"), errors="coerce"),
                         as_=pd.to_numeric(comp.get("away", {}).get("score"), errors="coerce"),
                         completed=bool(st.get("completed")), neutral=bool(c.get("neutralSite")),
                         venue=(c.get("venue") or {}).get("fullName"), indoor=(c.get("venue") or {}).get("indoor")))
    if done and rows and all(r["completed"] for r in rows):
        cache.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(rows, default=lambda o: o.item() if hasattr(o, "item") else None))
    time.sleep(0.25)
    return rows


def audit_scores(sched: pd.DataFrame, start: int, cache: Path) -> dict:
    s = sched[(sched["season"] >= start) & sched["result"].notna()].copy()
    s["home"], s["away"] = s["home_team"].map(norm_team), s["away_team"].map(norm_team)
    s["date"] = pd.to_datetime(s["gameday"], errors="coerce")
    esp = []
    for season in sorted(s["season"].unique()):
        n_reg = 18 if season >= 2021 else 17
        weeks = [(2, w) for w in range(1, n_reg + 1)] + [(3, w) for w in (1, 2, 3, 5)]
        for stype, w in weeks:
            try:
                for r in espn_week(cache, int(season), stype, w, done=True):
                    r["season"] = int(season)
                    esp.append(r)
            except Exception as e:
                log.warning("ESPN %s type %s week %s: %s", season, stype, w, e)
    e = pd.DataFrame(esp)
    if e.empty:
        return dict(ok=False, note="ESPN scoreboard unavailable")
    e = e[e["completed"]].copy()
    e["date"] = pd.to_datetime(e["date"], utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    e["pair"] = [frozenset((h, a)) for h, a in zip(e["home"], e["away"])]
    s["pair"] = [frozenset((h, a)) for h, a in zip(s["home"], s["away"])]
    idx = {}
    for r in e.itertuples(index=False):
        idx.setdefault((r.season, r.pair), []).append(r)
    mism, missing, matched = [], [], 0
    for r in s.itertuples(index=False):
        cands = [c for c in idx.get((r.season, r.pair), []) if abs((c.date - r.date).days) <= 1]
        if not cands:
            missing.append(r.game_id)
            continue
        c = cands[0]
        matched += 1
        # ESPN's home/away can differ from nflverse's at neutral sites; compare by team
        esp_pts = {c.home: c.hs, c.away: c.as_}
        if esp_pts.get(r.home) != r.home_score or esp_pts.get(r.away) != r.away_score:
            mism.append(dict(game_id=r.game_id, nflverse=f"{r.away} {int(r.away_score)} @ {r.home} {int(r.home_score)}",
                             espn=f"{c.away} {esp_pts.get(c.away)} @ {c.home} {esp_pts.get(c.home)}"))
    return dict(ok=not mism, games=int(len(s)), matched=matched, mismatches=mism[:50], n_mismatch=len(mism),
                unmatched=missing[:50], n_unmatched=len(missing), seasons=f"{start}-{int(s['season'].max())}")


# ----------------------------------------------------------------------------- 2. lines
def audit_lines(sched: pd.DataFrame, start: int) -> dict:
    s = sched[(sched["season"] >= start) & sched["result"].notna()]
    miss_spread = int(s["spread_line"].isna().sum())
    miss_total = int(s["total_line"].isna().sum())
    bad_range = s[(s["spread_line"].abs() > 25) | (s["total_line"] < 28) | (s["total_line"] > 65)]
    ml = s.dropna(subset=["home_moneyline", "away_moneyline", "spread_line"])
    same = ml[ml["home_moneyline"] == ml["away_moneyline"]]          # both sides equal: a moneyline entry error
    ml = ml[ml["home_moneyline"] != ml["away_moneyline"]]
    ml = ml[ml["spread_line"].abs() >= 1.5]                       # near pick'em both can be favored by a hair
    fav_ml_home = ml["home_moneyline"] < ml["away_moneyline"]
    fav_sp_home = ml["spread_line"] > 0
    disagree = ml[fav_ml_home != fav_sp_home]
    corr = float(np.corrcoef(s["spread_line"].fillna(0), s["result"])[0, 1])
    return dict(ok=miss_spread == 0 and miss_total == 0 and len(disagree) == 0 and len(bad_range) == 0 and corr > 0.3,
                games=int(len(s)), missing_spread=miss_spread, missing_total=miss_total,
                out_of_range=bad_range["game_id"].tolist()[:30], favorite_disagree=disagree["game_id"].tolist()[:30],
                n_favorite_disagree=int(len(disagree)), spread_result_corr=round(corr, 3),
                moneyline_entry_errors=same["game_id"].tolist()[:30],
                n_moneyline_entry_errors=int(len(same)),
                note="nflverse closing lines; spread sign = home favored when positive")


# ----------------------------------------------------------------------------- 3. venues
def audit_venues(sched: pd.DataFrame, season: int) -> dict:
    """Our stadium table (what the model uses) vs ESPN's venue flags (grass, indoor) for every home stadium.
    ESPN's franchise venue can be stale after a move, so a disagreement only counts when ESPN's scoreboard
    shows the team actually playing at that stadium this season. nflverse's surface field is reported for
    reference: it lists several turf stadiums (Carolina, Tennessee) as grass in every season."""
    s = sched[(sched["season"] == season) & (sched["location"] == "Home")]
    try:
        teams = espn._get("teams")["sports"][0]["leagues"][0]["teams"]
    except Exception as e:
        return dict(ok=False, note=f"ESPN teams unavailable ({e})")
    issues, rows = [], []
    for tm in teams:
        ab = norm_team(tm["team"]["abbreviation"])
        try:
            v = espn._get(f"teams/{tm['team']['id']}")["team"].get("franchise", {}).get("venue", {})
        except Exception:
            continue
        ours = home_venue(ab, season)
        played_there = bool(s[(s["home_team"] == ab)]["stadium"].astype(str).str.lower()
                            .str.contains(str(v.get("fullName", "")).lower()[:10], regex=False).any())
        nv = sorted(set(s[s["home_team"] == ab]["surface"].dropna().astype(str).str.strip()))
        row = dict(team=ab, stadium=ours.get("name"), ours_surface=ours["surface"], ours_roof=ours["roof"],
                   espn_venue=v.get("fullName"), espn_grass=v.get("grass"), espn_indoor=v.get("indoor"),
                   nflverse_surface=",".join(nv), espn_current=played_there)
        rows.append(row)
        if not played_there:
            continue
        if v.get("grass") is not None and bool(v["grass"]) == bool(is_turf(ours["surface"])):
            issues.append(dict(team=ab, field="surface", ours=ours["surface"], espn="grass" if v["grass"] else "turf"))
        if v.get("indoor") is not None and "retract" not in str(ours["roof"]) and bool(v["indoor"]) != (is_indoor(ours["roof"]) >= 0.5):
            issues.append(dict(team=ab, field="roof", ours=ours["roof"], espn="indoor" if v["indoor"] else "outdoor"))
        time.sleep(0.1)
    return dict(ok=not issues, stadiums=len(rows), issues=issues, n_issues=len(issues), table=rows)


# ----------------------------------------------------------------------------- 4. injuries
def audit_injuries(payload: dict, rosters: pd.DataFrame, nflv_inj: pd.DataFrame) -> dict:
    season, week = payload["season"], payload["week"]
    einj, notes = espn.injuries(season, week)
    einj = espn.align_names(einj, rosters[rosters["season"] == season] if rosters is not None and len(rosters) else rosters)
    if einj.empty:
        return dict(ok=False, note=notes[0] if notes else "ESPN injuries unavailable")
    teams = {g["home_team"] for g in payload["games"]} | {g["away_team"] for g in payload["games"]}
    r = rosters[(rosters["season"] == season)]
    r = r[r["week"] == r["week"].max()] if len(r) else r
    roster_keys = set(zip(r["team"], r["full_name"].map(name_key)))
    e = einj[einj["team"].isin(teams)].copy()
    e["nk"] = e["full_name"].map(name_key)
    e["on_roster"] = [(t, k) in roster_keys for t, k in zip(e["team"], e["nk"])]
    # players ESPN lists with a different team, or not on any roster (a trade or a name spelled differently)
    unmatched = e[~e["on_roster"]][["team", "full_name", "position", "report_status"]].to_dict("records")
    # ESPN vs league report where both list the player this week
    disagree = []
    if nflv_inj is not None and len(nflv_inj):
        n = nflv_inj[(nflv_inj["season"] == season) & (nflv_inj["week"] == week) & nflv_inj["report_status"].notna()]
        nmap = {(t, name_key(x)): st for t, x, st in zip(n["team"], n["full_name"], n["report_status"])}
        for row in e.itertuples(index=False):
            st = nmap.get((row.team, row.nk))
            if st and st != row.report_status and row.report_status != "ACTIVE":
                disagree.append(dict(team=row.team, player=row.full_name, espn=row.report_status, league=st))
    # projected starting QBs listed out
    out = set(zip(e.loc[e["report_status"].isin(["OUT", "DOUBTFUL", "IR", "PUP", "SUSPENDED"]), "team"],
                  e.loc[e["report_status"].isin(["OUT", "DOUBTFUL", "IR", "PUP", "SUSPENDED"]), "nk"]))
    qb_flags = []
    for g in payload["games"]:
        for side, t in (("h", g["home_team"]), ("a", g["away_team"])):
            qb = g.get(f"{side}_qb_name_used") or ""
            qk = name_key(qb.replace(".", ". ")).split() if qb else []
            ini, last = (qk[0][:1], qk[-1]) if len(qk) >= 2 else ("", "")
            hit = [k for (tt, k) in out if tt == t and last and k.split()[-1] == last and k.split()[0][:1] == ini]
            if hit:
                qb_flags.append(dict(team=t, qb=qb, espn_status="out/doubtful"))
    share = float(e["on_roster"].mean()) if len(e) else 1.0
    return dict(ok=share >= 0.9 and not qb_flags, listings=int(len(e)), not_active=int((e["report_status"] != "ACTIVE").sum()),
                matched_share=round(share, 3), unmatched=unmatched[:40], n_unmatched=len(unmatched),
                status_disagreements=disagree[:40], n_status_disagree=len(disagree), qb_flags=qb_flags,
                checked=datetime.now(timezone.utc).isoformat(timespec="seconds"))


# ----------------------------------------------------------------------------- 5. books
def audit_books(cfg) -> dict:
    snaps = sorted((ROOT / cfg.artifacts_dir / "odds_snapshots").glob("odds_*.json"))
    if not snaps:
        return dict(ok=False, note="no odds snapshot yet")
    ev = json.loads(snaps[-1].read_text())
    seen = {}
    for e in ev:
        for b in e.get("bookmakers", []):
            seen[b["key"]] = seen.get(b["key"], 0) + 1
    wanted = [cfg.target_book] + list(cfg.sharp_books) + list(cfg.extra_books)
    missing = [b for b in wanted if b not in seen]
    return dict(ok=cfg.target_book in seen and any(b in seen for b in cfg.sharp_books), snapshot=snaps[-1].name,
                games=len(ev), books_seen=seen, configured_missing=missing)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--start", type=int, default=2015)
    ap.add_argument("--no-scores", action="store_true", help="skip the ESPN score cross-check")
    args = ap.parse_args(argv)
    setup_logging()
    cfg = load_config(args.config)
    data, ds = load_real(cfg)
    sched = data["schedules"]
    weeks = sorted((ROOT / "site_data").glob("week_*.json"))
    payload = json.loads(weeks[-1].read_text()) if weeks else None
    season = payload["season"] if payload else int(sched["season"].max())
    res = dict(built=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    prev_path = ROOT / "artifacts" / "data_audit.json"
    prev = json.loads(prev_path.read_text()) if prev_path.exists() else {}
    if not args.no_scores:
        res["scores"] = audit_scores(sched, args.start, Path(cfg.cache_dir) / "espn_scores")
    elif "scores" in prev:
        res["scores"] = prev["scores"]                     # keep the last full score check
    res["lines"] = audit_lines(sched, args.start)
    res["venues"] = audit_venues(sched, season)
    if payload:
        inj = data.get("injuries")
        res["injuries"] = audit_injuries(payload, data.get("rosters_all", data.get("rosters")), inj)
    res["books"] = audit_books(cfg)
    out = ROOT / "artifacts" / "data_audit.json"
    out.write_text(json.dumps(res, indent=1, default=str))
    for k, v in res.items():
        if isinstance(v, dict):
            summary = {kk: vv for kk, vv in v.items() if not isinstance(vv, (list, dict))}
            print(f"{k:9} {'OK ' if v.get('ok') else 'CHECK'} {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
