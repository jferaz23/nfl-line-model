#!/usr/bin/env python
"""Closing-line value (CLV) and profit/loss for the bets you logged.

Log each bet in overrides/my_bets.csv:
    season,week,home_team,away_team,market,side,line,price,stake,book
    2026,4,MIA,CLE,spread,away,2.5,-110,20,draftkings
    2026,4,MIA,CLE,total,over,44.5,-108,15,draftkings
    2026,4,MIA,CLE,moneyline,away,,+120,10,draftkings
market: spread | total | moneyline.  side: home | away | over | under.
line: your handicap for that side (away +2.5 -> 2.5, home -3 -> -3), or the total.

CLV compares your number with the closing line recorded by nflverse. Beating the
close consistently is the best evidence you have an edge; P/L over a few hundred
bets is mostly noise.

    python clv_report.py
    python clv_report.py --bets path/to/bets.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from nflmodel.config import load_config
from nflmodel.data import DataStore
from nflmodel.pricing import american_to_decimal, fit_distributions, no_vig
from nflmodel.pipeline import setup_logging
from nflmodel.venues import norm_team


def evaluate(bets: pd.DataFrame, sched: pd.DataFrame, cfg) -> pd.DataFrame:
    dm, dt = fit_distributions(sched, cfg)
    b = bets.copy()
    b.columns = [c.strip().lower() for c in b.columns]
    for c in ("home_team", "away_team"):
        b[c] = b[c].map(norm_team)
    b["market"] = b["market"].str.strip().str.lower().replace({"ml": "moneyline", "h2h": "moneyline", "spreads": "spread",
                                                               "totals": "total"})
    b["side"] = b["side"].str.strip().str.lower()
    for c in ("season", "week", "line", "price", "stake"):
        b[c] = pd.to_numeric(b[c], errors="coerce")
    # tolerate home/away entered the wrong way round (common for neutral-site games)
    keys = set(zip(sched["season"], sched["week"], sched["home_team"], sched["away_team"]))
    for i, r in b.iterrows():
        k = (r["season"], r["week"], r["home_team"], r["away_team"])
        swapped = (r["season"], r["week"], r["away_team"], r["home_team"])
        if k not in keys and swapped in keys:
            b.loc[i, ["home_team", "away_team"]] = [r["away_team"], r["home_team"]]
            b.loc[i, "side"] = {"home": "away", "away": "home"}.get(r["side"], r["side"])
    m = b.merge(sched[["season", "week", "home_team", "away_team", "result", "total", "spread_line", "total_line",
                       "home_spread_odds", "away_spread_odds", "over_odds", "under_odds", "home_moneyline",
                       "away_moneyline"]], on=["season", "week", "home_team", "away_team"], how="left",
                indicator="_found")
    rows = []
    for r in m.to_dict("records"):
        out = dict(r)
        mk, side, line, price = r["market"], r["side"], r["line"], r["price"]
        sign = 1 if side in ("home", "over") else -1
        if r.pop("_found", "both") != "both":
            out.pop("_found", None)
            out["status"] = "game not found (check season/week/teams)"
            rows.append(out)
            continue
        out.pop("_found", None)
        if side not in ("home", "away", "over", "under") or not np.isfinite(price):
            out["status"] = "bad side or price"
            rows.append(out)
            continue
        need = "total_line" if mk == "total" else "spread_line"
        if not np.isfinite(r.get(need, np.nan)):
            out["status"] = "no closing line recorded"
            rows.append(out)
            continue
        # ---- closing mean implied by the close ----
        if mk == "spread":
            close_line = -r["spread_line"] if side == "home" else r["spread_line"]
            ph, _ = no_vig(r["home_spread_odds"] if np.isfinite(r["home_spread_odds"]) else -110,
                           r["away_spread_odds"] if np.isfinite(r["away_spread_odds"]) else -110)
            mu = dm.implied_mean(+1, -r["spread_line"], ph)
            dist, hcap = dm, line
            out["clv_pts"] = line - close_line
        elif mk == "total":
            close_line = r["total_line"]
            po, _ = no_vig(r["over_odds"] if np.isfinite(r["over_odds"]) else -110,
                           r["under_odds"] if np.isfinite(r["under_odds"]) else -110)
            mu = dt.implied_mean(+1, -r["total_line"], po)
            dist, hcap = dt, (-line if side == "over" else line)
            out["clv_pts"] = (close_line - line) if side == "over" else (line - close_line)
        elif mk == "moneyline":
            if np.isfinite(r["home_moneyline"]) and np.isfinite(r["away_moneyline"]):
                ph, _ = no_vig(r["home_moneyline"], r["away_moneyline"])
                mu = dm.implied_mean(+1, 0.0, ph)
            else:
                mu = dm.implied_mean(+1, -r["spread_line"], 0.5)
            dist, hcap = dm, 0.0
            out["clv_pts"] = np.nan
        else:
            out["status"] = f"unknown market '{mk}'"
            rows.append(out)
            continue
        w, p, l = dist.outcome(mu, sign, hcap)
        dec = american_to_decimal(price)
        out["win_prob_at_close"] = w / (w + l) if w + l else np.nan
        out["ev_at_close"] = w * (dec - 1) - l      # your ticket's value priced at the closing line
        # ---- result ----
        if mk == "total":
            actual = r["total"]
            val = (actual - line) if side == "over" else (line - actual)
        else:
            actual = r["result"]
            val = sign * actual + (line if mk == "spread" else 0.0)
        if not np.isfinite(actual):
            out["status"], out["pl"] = "pending (CLV vs current line)", 0.0
        else:
            out["status"] = "win" if val > 0 else ("push" if val == 0 else "loss")
            out["pl"] = r["stake"] * (dec - 1) if val > 0 else (0.0 if val == 0 else -r["stake"])
        rows.append(out)
    return pd.DataFrame(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bets", help="CSV of bets (default overrides/my_bets.csv)")
    ap.add_argument("--config")
    ap.add_argument("--demo", action="store_true", help="use synthetic schedule (for testing)")
    args = ap.parse_args(argv)
    setup_logging()
    cfg = load_config(args.config)
    path = Path(args.bets or Path(cfg.overrides_dir) / "my_bets.csv")
    if not path.exists():
        sys.exit(f"No bets file at {path}. See the header of this script for the format.")
    bets = pd.read_csv(path, comment="#")
    if bets.empty:
        sys.exit(f"{path} has no bets yet.")
    if args.demo:
        from nflmodel.pipeline import apply_demo, demo_data
        apply_demo(cfg)
        sched = demo_data(cfg)[0]["schedules"]
    else:
        sched = DataStore(cfg, refresh=True, current_season=int(bets["season"].max())).schedules()
    res = evaluate(bets, sched, cfg)
    done = res[res["status"].isin(["win", "loss", "push"])]
    out = cfg.path("reports_dir") / "clv_report.csv"
    res.to_csv(out, index=False)
    cols = ["season", "week", "away_team", "home_team", "market", "side", "line", "price", "clv_pts",
            "ev_at_close", "status", "pl"]
    with pd.option_context("display.width", 160, "display.max_rows", 200):
        print(res[[c for c in cols if c in res.columns]].to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    staked = done["stake"].sum()
    print(f"\n{len(res)} bets, {len(done)} settled.")
    if len(res.dropna(subset=["ev_at_close"])):
        print(f"Average value at closing prices: {res['ev_at_close'].mean():+.2%} per dollar "
              f"(positive = you beat the close); average points of CLV: {res['clv_pts'].mean():+.2f}.")
    if staked:
        print(f"P/L {done['pl'].sum():+,.2f} on {staked:,.2f} staked (ROI {done['pl'].sum() / staked:+.1%}).")
    print(f"Details: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
