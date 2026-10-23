#!/usr/bin/env python
"""Player props, INFORMATION ONLY (no proven edge in the 2024-26 backtest): DraftKings prop lines from ESPN (free),
role-aware projections, the biggest disagreements flagged and logged, graded after the games.

    python props_run.py            # this week's props + grade finished games
    python props_run.py --prices   # also fetch DraftKings prices from The Odds API for the two leads being tested
                                   # (passing TDs / receptions, and big-edge yardage unders); budget-gated

Outputs (artifacts/props/): week.json (the Props tab), props_log.csv (flagged props, every run), props_graded.csv,
summary.json (record by lead). Prices are only fetched once credits have reset and >= MIN_CREDITS remain.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from nflmodel import props as P

log = logging.getLogger("nflmodel")
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "artifacts" / "props"
BUDGET = ROOT / "artifacts" / "odds_budget.json"
MIN_CREDITS = 250                 # never let the props price test eat into the credits the spread/total updates need
PRICE_TEST_FROM = "2026-10-31"    # the free quota resets around Oct 30; the test starts after that
ASSUMED = -115                    # grading price when DraftKings' real price was not fetched
NOW = datetime.now(timezone.utc)


def current_week():
    weeks = sorted((ROOT / "site_data").glob("week_*_*.json"))
    p = json.loads(weeks[-1].read_text(encoding="utf-8"))
    return int(p["season"]), int(p["week"]), p


def category(market, side, z):
    if abs(z) < P.BIG_Z:
        return ""
    if market in ("pass_tds", "receptions"):
        return market
    return "under" if side == "under" else "over"


def profit(res, price):
    if res == "W":
        return 100 / -price if price < 0 else price / 100
    return -1.0 if res == "L" else 0.0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(); ap.add_argument("--prices", action="store_true"); args = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    season, week, payload = current_week()
    st, sch, snaps, players = P.load_history(range(2013, season + 1))
    imp = P.implied(sch)
    pl = players[["gsis_id", "espn_id", "display_name", "position"]].dropna(subset=["espn_id"]).copy()
    pl["espn_id"] = pl.espn_id.astype(str).str.replace(r"\.0$", "", regex=True)
    last_team = st.sort_values(["season", "week"]).groupby("player_id").tail(1).set_index("player_id")[["team", "pos"]]
    # ---------------- this week's DraftKings lines (games not started)
    games = {g["game_id"]: g for g in payload.get("games", [])}
    lines = []
    for e in P.week_events(season, week):
        if e["state"] != "pre":
            continue
        d = P.dk_lines(e["espn_event"])
        if d.empty:
            continue
        lines.append(d.assign(espn_event=e["espn_event"], kickoff=e["kickoff"], home=e["home"], away=e["away"]))
    L = pd.concat(lines, ignore_index=True) if lines else pd.DataFrame()
    week_rows = []
    if len(L):
        L = L.merge(pl.rename(columns={"espn_id": "espn_athlete", "gsis_id": "player_id"}), on="espn_athlete", how="left")
        L = L.dropna(subset=["player_id"])
        L["team"] = L.player_id.map(last_team.team); L["pos"] = L.player_id.map(last_team.pos)
        L = L[(L.team == L.home) | (L.team == L.away)]
        L["opponent_team"] = np.where(L.team == L.home, L.away, L.home); L["home_flag"] = (L.team == L.home).astype(int)
        # implied points from DraftKings' current spread/total in the latest model run
        gi = {(g["home_team"], g["away_team"]): g for g in games.values()}
        def imp_pts(r):
            g = gi.get((r.home, r.away), {})
            hs, tot = g.get("dk_home_spread"), g.get("dk_total")
            if hs is None or tot is None:
                return np.nan, np.nan
            sp = -float(hs)                                          # home expected margin
            return ((tot + sp) / 2 if r.home_flag else (tot - sp) / 2), float(tot)
        ip = L.apply(imp_pts, axis=1, result_type="expand"); L["imp_pts"], L["total_line"] = ip[0], ip[1]
        up = L.drop_duplicates("player_id")[["player_id", "team", "opponent_team", "pos", "imp_pts", "total_line"]].assign(
            season=season, week=week, home=L.drop_duplicates("player_id").home_flag.to_numpy())
        # injury report: regulars ruled out (Out / Doubtful) this week vacate their volume
        # (ESPN's current list first: nflverse's file lags the Wednesday-Friday reports for Sunday's teams)
        out_ids = set()
        try:
            from nflmodel.espn import injuries as espn_injuries
            ei, _ = espn_injuries(season, week)
            ei = ei[ei.report_status.isin(["OUT", "DOUBTFUL", "IR", "PUP", "SUSPENDED"])]
            # ESPN's list carries no player ids: match by name + current team
            nm = players[["gsis_id", "display_name"]].dropna().assign(team=lambda d: d.gsis_id.map(last_team.team))
            nm["nk"] = nm.display_name.map(P.name_key)
            nmap = {(k, t): g for k, t, g in zip(nm.nk, nm.team, nm.gsis_id) if isinstance(t, str)}
            out_ids |= {nmap[(P.name_key(n), t)] for n, t in zip(ei.full_name, ei.team) if (P.name_key(n), t) in nmap}
        except Exception as e:
            log.warning("props: ESPN injury list unavailable (%s)", e)
        try:
            import nflreadpy as nr
            inj = P._pd(nr.load_injuries(seasons=[season]))
            inj = inj[(inj.week == week) & inj.report_status.isin(["Out", "Doubtful"])]
            out_ids |= set(inj.gsis_id.dropna())
        except Exception as e:
            log.warning("props: nflverse injury report unavailable (%s)", e)
        log.info("props: %d players ruled out this week", len(out_ids))
        F = P.features(st, imp, snaps, players, upcoming=up, out_ids=frozenset(out_ids))
        U = P.project(F)
        for r in L.itertuples(index=False):
            u = U[U.player_id == r.player_id]
            if u.empty or r.market not in P.MARKETS:
                continue
            u = u.iloc[0]
            proj, sd = float(u[f"proj_{r.market}"]), float(u[f"sd_{r.market}"])
            z = (proj - r.line) / sd if sd > 0 else 0.0
            side = "over" if proj > r.line else "under"
            week_rows.append(dict(season=season, week=week, espn_event=r.espn_event, kickoff=r.kickoff, home=r.home, away=r.away,
                                  player_id=r.player_id, player=r.display_name, team=r.team, pos=r.pos, market=r.market, line=r.line,
                                  open_line=r.open_line, proj=round(proj, 1), edge=round(proj - r.line, 1), z=round(z, 2), side=side,
                                  vac=round(float(u.vac_tgt + u.vac_car), 1), category=category(r.market, side, z)))
    W = pd.DataFrame(week_rows)
    # ---------------- DraftKings prices for the leads (paid; budget-gated)
    if args.prices and len(W):
        b = json.loads(BUDGET.read_text()) if BUDGET.exists() else {}
        key = os.environ.get("ODDS_API_KEY")
        if not key or NOW.date().isoformat() < PRICE_TEST_FROM or int(b.get("remaining", 0)) < MIN_CREDITS:
            log.info("props prices skipped (key=%s, remaining=%s, starts %s)", bool(key), b.get("remaining"), PRICE_TEST_FROM)
        else:
            lead = W[W.category != ""]
            mk = sorted(set(lead.market))
            need = sorted(set(zip(lead.home, lead.away)))
            pr, used = P.dk_prices(key, need, mk)
            log.info("props prices: %d outcomes, %d credits", len(pr), used)
            if len(pr):
                pr["nk"] = pr.player_name.map(P.name_key)
                W["nk"] = W.player.map(P.name_key)
                W = W.merge(pr.rename(columns={"point": "price_line"})[["home", "away", "nk", "market", "side", "price_line", "price"]],
                            on=["home", "away", "nk", "market", "side"], how="left").drop(columns=["nk"])
                b["remaining"] = int(b.get("remaining", 0)) - used
                BUDGET.write_text(json.dumps(b, indent=1))
    if "price" not in W.columns:
        W["price"] = np.nan; W["price_line"] = np.nan
    # ---------------- log flagged props (every run; the last row before kickoff is the one graded)
    logp = OUT / "props_log.csv"
    flagged = W[W.category != ""].assign(run_at=NOW.isoformat()) if len(W) else W
    if len(flagged):
        flagged.to_csv(logp, mode="a", header=not logp.exists(), index=False)
    # ---------------- grade finished games
    graded = pd.DataFrame()
    if logp.exists():
        lg = pd.read_csv(logp)
        lg["t"] = pd.to_datetime(lg.run_at, utc=True, format="ISO8601"); lg["ko"] = pd.to_datetime(lg.kickoff, utc=True, format="ISO8601")
        lg = lg[lg.t < lg.ko].sort_values("t").groupby(["espn_event", "player_id", "market"]).tail(1)
        stats = st.set_index(["player_id", "season", "week"])
        res = []
        for r in lg.itertuples(index=False):
            stat = P.MARKETS[r.market][0]
            key = (r.player_id, int(r.season), int(r.week))
            if r.ko > NOW or key not in stats.index:
                continue                                              # not played yet, or did not play (void)
            act = float(np.nan_to_num(stats.loc[key, stat] if not isinstance(stats.loc[key], pd.DataFrame) else stats.loc[key].iloc[0][stat]))
            line = float(r.price_line) if pd.notna(getattr(r, "price_line", np.nan)) else float(r.line)
            out = "P" if act == line else ("W" if (act > line) == (r.side == "over") else "L")
            price = float(r.price) if pd.notna(getattr(r, "price", np.nan)) else np.nan
            res.append(dict(season=r.season, week=r.week, player=r.player, team=r.team, market=r.market, side=r.side, line=line,
                            proj=r.proj, z=r.z, category=r.category, actual=act, result=out, price=price,
                            units_assumed=profit(out, ASSUMED), units_real=(profit(out, price) if pd.notna(price) else np.nan)))
        graded = pd.DataFrame(res)
        graded.to_csv(OUT / "props_graded.csv", index=False)
    def rec(d):
        w, l, p = int((d.result == "W").sum()), int((d.result == "L").sum()), int((d.result == "P").sum())
        pr = d.dropna(subset=["units_real"])
        return dict(w=w, l=l, p=p, n=w + l + p, pct=(w / (w + l) if w + l else None), units_assumed=float(d.units_assumed.sum()),
                    priced=int(len(pr)), units_real=(float(pr.units_real.sum()) if len(pr) else None))
    summary = {"all": rec(graded) if len(graded) else None}
    for c in ("under", "over", "pass_tds", "receptions"):
        summary[c] = rec(graded[graded.category == c]) if len(graded) and (graded.category == c).any() else None
    curve = json.loads((OUT / "backtest_curve.json").read_text()) if (OUT / "backtest_curve.json").exists() else {}
    (OUT / "week.json").write_text(json.dumps(dict(generated=NOW.isoformat(), season=season, week=week, big_z=P.BIG_Z,
                                                   assumed_price=ASSUMED, props=json.loads(W.to_json(orient="records")) if len(W) else [],
                                                   summary=summary, backtest=curve), separators=(",", ":")), encoding="utf-8")
    log.info("props: %d lines this week, %d flagged, %d graded", len(W), int((W.category != "").sum()) if len(W) else 0, len(graded))
    return 0


if __name__ == "__main__":
    sys.exit(main())
