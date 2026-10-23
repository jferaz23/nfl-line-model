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
STALE_GAMES = 6                   # no appearance in the team's last 6 games = no current role to project
NOW = datetime.now(timezone.utc)


# walk-forward backtest of the green/Top rule (Test P5, assumed -115; see nflmodel/props.py): [won, lost, units]
GREEN_TEST = {"green": {"2025": [382, 305, 27.2], "2026": [224, 180, 14.8]}, "top": {"2025": [97, 69, 15.3], "2026": [75, 56, 9.2]},
              "yardage_green": {"2025": [290, 237, 15.2], "2026": [110, 95, 0.7]}}
LOG_COLS = ["passing_yards", "passing_tds", "rushing_yards", "receiving_yards", "receptions", "targets", "carries"]


def game_logs(st, snaps, players, season, pids, n=12):
    """Each player's last n games (any season): week, opponent, the five prop stats, targets, carries, snap share."""
    pl = players[["gsis_id", "pfr_id"]].dropna()
    sn = snaps.merge(pl.rename(columns={"pfr_id": "pfr_player_id", "gsis_id": "player_id"}), on="pfr_player_id", how="inner")
    snp = dict(zip(zip(sn.player_id, sn.season, sn.week), sn.offense_pct))
    d = st[st.player_id.isin(pids)].sort_values(["season", "week"])
    out = {}
    for pid, g in d.groupby("player_id"):
        rows = []
        for r in g.tail(n).itertuples(index=False):
            sp = snp.get((pid, r.season, r.week))
            rows.append([int(r.season), int(r.week), r.opponent_team] + [float(np.nan_to_num(getattr(r, c))) for c in LOG_COLS]
                        + [round(float(sp), 2) if sp is not None and pd.notna(sp) else None])
        out[pid] = rows
    return {"cols": ["season", "week", "opp"] + LOG_COLS + ["snap"], "players": out}


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
    week_rows, out_ids = [], set()
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
        curves = P.load_curves()
        for r in L.itertuples(index=False):
            u = U[U.player_id == r.player_id]
            if u.empty or r.market not in P.MARKETS:
                continue
            u = u.iloc[0]
            proj, sd = float(u[f"proj_{r.market}"]), float(u[f"sd_{r.market}"])
            z = (proj - r.line) / sd if sd > 0 else 0.0
            side = "over" if proj > r.line else "under"
            stat, vol, _ = P.MARKETS[r.market]
            _, bw, bn = P.band(curves, r.market, side, z)
            num = lambda x, d=1: (round(float(x), d) if pd.notna(x) else None)
            week_rows.append(dict(season=season, week=week, espn_event=r.espn_event, kickoff=r.kickoff, home=r.home, away=r.away,
                                  player_id=r.player_id, player=r.display_name, team=r.team, pos=r.pos, market=r.market, line=r.line,
                                  open_line=r.open_line, proj=round(proj, 1), sd=round(sd, 2), edge=round(proj - r.line, 1), z=round(z, 2),
                                  side=side, chance=round(P.chance(curves, r.market, side, z), 4),
                                  vac=round(float(u.vac_tgt + u.vac_car), 1), category=category(r.market, side, z),
                                  # the "why": recency-weighted average, short-term form, volume, opponent allowed to his
                                  # position (vs average), team implied points, and the backtest band's record
                                  avg=num(u[f"ew_{stat}"]), form=num(u[f"st_{stat}"]), vol=num(u[f"ew_{vol}"]), vol_name=vol,
                                  allow=num(u[f"allow_{stat}"]), imp=num(r.imp_pts), band_w=bw, band_n=bn))
    W = pd.DataFrame(week_rows)
    # ---------------- data-validity guard (Oct 23, after Tank Dell's IR return): a player with no appearance in his
    # team's last STALE_GAMES games, or listed on IR / PUP / out but still on the board, has no current usage to project
    # from; he is shown with a note and never flagged
    if len(W):
        pl2 = players[["gsis_id", "pfr_id"]].dropna()
        sn = snaps.merge(pl2.rename(columns={"pfr_id": "pfr_player_id", "gsis_id": "player_id"}), on="pfr_player_id", how="inner")
        sn["team"] = sn.team.replace(P.FIX)
        tgames = sn[["season", "week", "team"]].drop_duplicates()
        last_app = sn.sort_values(["season", "week"]).groupby("player_id").tail(1).set_index("player_id")[["season", "week"]]
        def missed(pid, team):
            if pid not in last_app.index:
                return 99
            s0, w0 = last_app.loc[pid, "season"], last_app.loc[pid, "week"]
            t = tgames[tgames.team == team]
            return int(((t.season > s0) | ((t.season == s0) & (t.week > w0))).sum())
        W["missed"] = [missed(p, t) for p, t in zip(W.player_id, W.team)]
        W["note"] = ""
        stale = W.missed >= STALE_GAMES
        listed = W.player_id.isin(out_ids)
        W.loc[stale, "note"] = "no games in his team's last " + W.missed.clip(upper=99).astype(str) + " (role unknown)"
        W.loc[listed, "note"] = "returning from the injury list: snap count unknown"
        W.loc[stale | listed, "category"] = ""
        log.info("props: %d lines not flagged (stale or returning from the injury list)", int((stale | listed).sum()))
    # ---------------- last game on the field: snap share, touches, and why it was low (hurt in the game / on the injury
    # report / usage). Games with snaps but no stats count (nflverse's weekly stats leave them out, e.g. benchings).
    st_all = P.add_snap_games(st, snaps, players)
    if len(W):
        inj_in, inj_rep = set(), set()
        try:
            inj_in = P.ingame_injuries([season])
        except Exception as e:
            log.warning("props: in-game injuries unavailable (%s)", e)
        try:
            import nflreadpy as nr
            rp = P._pd(nr.load_injuries(seasons=[season]))
            rp = rp[rp.report_status.isin(["Questionable", "Doubtful"])]
            inj_rep = set(zip(rp.gsis_id, rp.season, rp.week))
        except Exception as e:
            log.warning("props: injury reports unavailable (%s)", e)
        u = P.last_game_usage(st_all, snaps, players, inj_in, inj_rep, set(W.player_id))
        for c in ("season", "week", "opp", "share", "avg6", "touches", "cause"):
            W[f"lg_{c}"] = [(u.get(p) or {}).get(c) for p in W.player_id]
        log.info("props: last games with low usage: %s", W.drop_duplicates("player_id").lg_cause.value_counts().to_dict())
    # ---------------- DraftKings prices (paid; budget-gated) for the props that could be green at a normal price
    if len(W):
        W["price"] = np.nan; W["price_line"] = np.nan
    if args.prices and len(W):
        b = json.loads(BUDGET.read_text()) if BUDGET.exists() else {}
        key = os.environ.get("ODDS_API_KEY")
        if not key or NOW.date().isoformat() < PRICE_TEST_FROM or int(b.get("remaining", 0)) < MIN_CREDITS:
            log.info("props prices skipped (key=%s, remaining=%s, starts %s)", bool(key), b.get("remaining"), PRICE_TEST_FROM)
        else:
            cand = W[(W.note == "") & (W.chance >= P.break_even(-110) + P.GREEN_EDGE)]
            pr, used = P.dk_prices(key, sorted(set(zip(cand.home, cand.away))), sorted(set(cand.market)))
            log.info("props prices: %d outcomes, %d credits", len(pr), used)
            b["remaining"] = int(b.get("remaining", 0)) - used
            BUDGET.write_text(json.dumps(b, indent=1))
            if len(pr):
                pr["nk"] = pr.player_name.map(P.name_key)
                pv = {}
                for q in pr.itertuples(index=False):
                    pv.setdefault((q.home, q.away, q.nk, q.market), {})[q.side] = (q.point, q.price)
                for i, r in W.iterrows():
                    o = pv.get((r.home, r.away, P.name_key(r.player), r.market))
                    if not o or "over" not in o or "under" not in o or o["over"][0] != o["under"][0]:
                        continue
                    pt = float(o["over"][0])          # DraftKings' line at the moment of the price pull (may have moved)
                    z = (r.proj - pt) / r.sd if r.sd > 0 else 0.0
                    sd_ = "over" if r.proj > pt else "under"
                    W.loc[i, ["price_line", "price", "z", "edge"]] = [pt, float(o[sd_][1]), round(z, 2), round(r.proj - pt, 1)]
                    W.loc[i, "side"] = sd_
                    ch, bw, bn = P.band(curves, r.market, sd_, z)
                    W.loc[i, ["chance", "band_w", "band_n"]] = [round(ch, 4), bw, bn]
    # ---------------- green / Top: chance vs the break-even of DraftKings' price (real when fetched, else assumed)
    if len(W):
        W["priced"] = W.price.notna()
        W["tier"] = [P.tier(c, p if pd.notna(p) else ASSUMED) if n == "" else "" for c, p, n in zip(W.chance, W.price, W.note)]
        W["worst_price"] = [P.worst_price(c - P.GREEN_EDGE) if c - P.GREEN_EDGE > 0.5 else None for c in W.chance]
        log.info("props: %d green, %d Top", int((W.tier == "green").sum()), int((W.tier == "top").sum()))
    # ---------------- log flagged props (every run; the last row before kickoff is the one graded)
    logp = OUT / "props_log.csv"
    flagged = W[(W.category != "") | (W.tier != "")].assign(run_at=NOW.isoformat()) if len(W) else W
    if len(W) and logp.exists():
        # props flagged by an earlier run but not any more: log them unflagged so the last pre-kickoff row decides
        prev = pd.read_csv(logp)
        prev = prev[prev.season == season].sort_values("run_at").groupby(["espn_event", "player_id", "market"]).tail(1)
        prev = prev[(prev.category.fillna("") != "") | (prev.get("tier", pd.Series("", index=prev.index)).fillna("") != "")]
        was = set(zip(prev.espn_event.astype(str), prev.player_id, prev.market))
        now_keys = set(zip(flagged.espn_event.astype(str), flagged.player_id, flagged.market)) if len(flagged) else set()
        drop = [k in was and k not in now_keys for k in zip(W.espn_event.astype(str), W.player_id, W.market)]
        unflag = W[drop].assign(category="", tier="", run_at=NOW.isoformat())
        if len(unflag):
            log.info("props: %d earlier flags withdrawn", len(unflag))
            flagged = pd.concat([flagged, unflag], ignore_index=True)
    if len(flagged):                    # rewrite the whole log (columns can grow over time)
        old = pd.read_csv(logp) if logp.exists() else pd.DataFrame()
        pd.concat([old, flagged], ignore_index=True).to_csv(logp, index=False)
    # ---------------- grade finished games
    graded = pd.DataFrame()
    if logp.exists():
        lg = pd.read_csv(logp)
        lg["t"] = pd.to_datetime(lg.run_at, utc=True, format="ISO8601"); lg["ko"] = pd.to_datetime(lg.kickoff, utc=True, format="ISO8601")
        lg = lg[lg.t < lg.ko].sort_values("t").groupby(["espn_event", "player_id", "market"]).tail(1)
        if "tier" not in lg.columns:
            lg["tier"] = ""
        lg["tier"] = lg.tier.fillna(""); lg["category"] = lg.category.fillna("")
        lg = lg[(lg.category != "") | (lg.tier != "")]               # withdrawn before kickoff = not graded
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
                            proj=r.proj, z=r.z, category=r.category, tier=r.tier, actual=act, result=out, price=price,
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
    for t, m in (("green", ("green", "top")), ("top", ("top",))):     # green includes Top, as for spreads
        summary[t] = rec(graded[graded.tier.isin(m)]) if len(graded) and graded.tier.isin(m).any() else None
    curve = json.loads((OUT / "backtest_curve.json").read_text()) if (OUT / "backtest_curve.json").exists() else {}
    glogs = game_logs(st_all, snaps, players, season, set(W.player_id) if len(W) else set())
    (OUT / "week.json").write_text(json.dumps(dict(generated=NOW.isoformat(), season=season, week=week, big_z=P.BIG_Z,
                                                   assumed_price=ASSUMED, props=json.loads(W.to_json(orient="records")) if len(W) else [],
                                                   summary=summary, backtest=curve, green_test=GREEN_TEST, logs=glogs),
                                              separators=(",", ":")), encoding="utf-8")
    log.info("props: %d lines this week, %d flagged, %d graded", len(W), int((W.category != "").sum()) if len(W) else 0, len(graded))
    return 0


if __name__ == "__main__":
    sys.exit(main())
