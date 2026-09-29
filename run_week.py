#!/usr/bin/env python
"""Project every game in an NFL week and compare the prices with DraftKings.

Examples
    python run_week.py                      # next unplayed week, live odds
    python run_week.py --no-odds            # model lines only
    python run_week.py --lines-file overrides/manual_lines.csv
    python run_week.py --demo               # synthetic data, no internet needed
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from nflmodel.config import load_config
from nflmodel.data import DataUnavailable
from nflmodel.features import build_games
from nflmodel.model import LineModel
from nflmodel.odds import get_week_odds
from nflmodel.pipeline import (apply_demo, apply_tuned, demo_data, load_calibration, load_real, next_unplayed_week,
                               read_override, setup_logging)
from nflmodel.pricing import fit_distributions, fmt_american, price_games
from nflmodel.report import ET, spread_text, weekly_html

log = logging.getLogger("nflmodel")


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, help="season (default: current)")
    ap.add_argument("--week", type=int, help="week (default: next week with unplayed games)")
    ap.add_argument("--demo", action="store_true", help="run on synthetic data (no internet)")
    ap.add_argument("--refresh", action="store_true", help="force re-download of current-season data")
    ap.add_argument("--no-odds", action="store_true", help="skip odds; report model lines only")
    ap.add_argument("--lines-file", help="CSV of lines instead of The Odds API (see overrides/manual_lines.csv)")
    ap.add_argument("--odds-snapshot", help="re-price from a saved Odds API snapshot (artifacts/odds_snapshots/*.json); "
                                            "'latest' = newest one. Spends no credits and logs no picks")
    ap.add_argument("--config", help="JSON file of setting overrides")
    ap.add_argument("--bankroll", type=float)
    ap.add_argument("--min-ev", type=float, help="minimum edge to flag, e.g. 0.02 for +2%%")
    ap.add_argument("--verbose", action="store_true")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    setup_logging(args.verbose)
    cfg = load_config(args.config)
    if args.bankroll is not None:
        cfg.bankroll = args.bankroll
    if args.min_ev is not None:
        cfg.min_ev = args.min_ev
    notes, events, forecasts = [], None, None

    if args.demo:
        apply_demo(cfg)
    tuned_note = apply_tuned(cfg)
    if tuned_note:
        notes.append(tuned_note)
    if args.demo:
        data, events, demo_fc = demo_data(cfg)
    else:
        try:
            data, ds = load_real(cfg, refresh=args.refresh, target_season=args.season)
        except DataUnavailable as e:
            sys.exit(f"Could not load nflverse data: {e}\nCheck your internet connection, or try "
                     f"`pip install -U nflreadpy`. Cached files in {cfg.cache_dir}/ are used when present.")
        notes += ds.notes
    sched = data["schedules"]

    season, week = args.season, args.week
    if season is None or week is None:
        s2, w2 = next_unplayed_week(sched if season is None else sched[sched["season"] == season])
        season, week = season or s2, week or w2
    if season is None:
        sys.exit("No unplayed games in the schedule. Use backtest.py to evaluate past seasons.")
    target_sched = sched[(sched["season"] == season) & (sched["week"] == week) & sched["result"].isna()]
    if target_sched.empty:
        sys.exit(f"No unplayed games in {season} week {week}. Use backtest.py for past weeks.")
    log.info("Target: %s week %s (%d unplayed games)", season, week, len(target_sched))

    # same-day injury news: ESPN's page, laid over nflverse's (lagging) report for the target week
    if not args.demo and cfg.use_espn:
        from nflmodel import espn
        einj, enotes = espn.injuries(season, week)
        notes += enotes
        data["injuries"] = espn.merge_injuries(data.get("injuries"), einj, season, week)

    # weather
    if args.demo:
        forecasts = demo_fc
    else:
        from nflmodel.weather import forecasts_for_games
        try:
            forecasts, wnotes = forecasts_for_games(target_sched, cfg)
            notes += wnotes
        except Exception as e:
            notes.append(f"Weather forecasts unavailable ({e}); typical conditions assumed.")
            forecasts = {}

    qb_ov = read_override(cfg, "starters.csv", ["season", "week", "team", "qb_name"])
    pl_ov = read_override(cfg, "player_status.csv", ["season", "week", "team", "player", "status"])
    weights, cal_note = load_calibration(cfg)
    notes.append(cal_note)

    games, info = build_games(data, cfg, season, week, forecasts=forecasts,
                              player_overrides=pl_ov, qb_overrides=qb_ov)
    notes += info["notes"]
    train = games[~games["is_target"]]
    target = games[games["is_target"]].copy()
    log.info("Training on %d games (%d-%d)", len(train), train["season"].min(), train["season"].max())
    mm = LineModel(cfg, "margin", drop_groups=cfg.drop_groups_margin).fit(train)
    mt = LineModel(cfg, "total", drop_groups=cfg.drop_groups_total).fit(train)
    if cfg.drop_groups_margin or cfg.drop_groups_total:
        notes.append("Factor groups left out because the backtest found they hurt: "
                     + ", ".join(sorted(set(cfg.drop_groups_margin) | set(cfg.drop_groups_total))) + ".")
    target["model_margin"] = mm.predict(target)
    target["model_total"] = mt.predict(target)
    exp_m = mm.explain(target).set_index(target["game_id"])
    exp_t = mt.explain(target).set_index(target["game_id"])
    if cfg.dyn_half_life_games > 0:
        oos_path = cfg.path("artifacts_dir") / "backtest_oos.csv"
        if oos_path.exists():
            from nflmodel.regress import target_weights
            target["w_margin_game"], target["w_total_game"] = target_weights(
                pd.read_csv(oos_path), target, weights[0], weights[1], cfg.dyn_half_life_games, cfg.dyn_scale)
            notes.append("Model weight varies by game with each team's recent model-vs-market accuracy (nfelo-style).")

    dm, dt = fit_distributions(sched[sched["season"] >= cfg.first_season], cfg)
    if args.odds_snapshot and not args.demo:
        import json as _json
        snap = (max((cfg.path("artifacts_dir") / "odds_snapshots").glob("odds_*.json"))
                if args.odds_snapshot == "latest" else Path(args.odds_snapshot))
        events = _json.loads(Path(snap).read_text())
        notes.append(f"Odds re-priced from saved snapshot {Path(snap).name}.")
    try:
        odds, onotes = get_week_odds(cfg, target, lines_file=args.lines_file, no_odds=args.no_odds, events=events)
    except Exception as e:
        log.warning("Odds unavailable: %s", e)
        odds, onotes = get_week_odds(cfg, target, no_odds=True)
        onotes = [f"Odds unavailable ({e}); model lines only."]
    notes += onotes
    summary, board = price_games(target, odds, cfg, dm, dt, weights)
    if board.empty:
        board = pd.DataFrame(columns=["game_id", "matchup", "market", "bet", "price", "p_win", "p_push", "p_lose",
                                      "ev", "stake", "fair_price", "check_news", "dk_vs_market", "no_market", "is_play"])

    # ---------------- bet timing (line-movement model or research-based defaults) ----------------
    from nflmodel.movement import MoveModel, parse_bet, timing
    mv = MoveModel.load(cfg.path("artifacts_dir") / "movement.json")
    if len(board):
        sm = summary.set_index("game_id")
        tg = target.set_index("game_id")
        labs, dets = [], []
        for b in board.to_dict("records"):
            lab = det = ""
            if b["market"] in ("spread", "total") and b["game_id"] in sm.index:
                g = tg.loc[b["game_id"]]
                side, _ = parse_bet(b["bet"], g["home_team"], g["away_team"])
                if b["market"] == "spread":
                    now, mval = -float(sm.loc[b["game_id"], "dk_home_spread"]), float(g["model_margin"])
                else:
                    now, mval = float(sm.loc[b["game_id"], "dk_total"]), float(g["model_total"])
                if side and np.isfinite(now):
                    lab, det, _ = timing(b["market"], side, now, mval, mv)
            labs.append(lab); dets.append(det)
        board["timing"], board["timing_detail"] = labs, dets
    notes.append("Bet timing from the line-movement model." if mv else
                 "Bet timing uses research defaults until backtest.py has opening-line history to learn from.")

    # ---------------- outputs ----------------
    out_dir = cfg.path("reports_dir")
    stem = f"{season}_week{week:02d}"
    html = weekly_html(season, week, target, summary, board, exp_m, exp_t, info.get("power"), cfg, weights,
                       notes, demo=args.demo, generated=datetime.now(ET))
    (out_dir / f"line_sheet_{stem}.html").write_text(html, encoding="utf-8")
    board.to_csv(out_dir / f"dk_board_{stem}.csv", index=False)
    cols = ["game_id", "away_team", "home_team", "kickoff_utc", "model_margin", "model_total", "h_qb_name_used",
            "a_qb_name_used", "temp_used", "wind_used", "indoor"]
    target[cols].merge(summary, on="game_id", how="left", suffixes=("", "_s")).to_csv(
        out_dir / f"projections_{stem}.csv", index=False)
    from nflmodel.export import append_pick_log, week_payload, write_payload
    payload = week_payload(season, week, target, summary, board, odds, exp_m, exp_t, info, cfg, weights, notes,
                           dm, dt, demo=args.demo)
    site_dir = (out_dir / "site_data") if args.demo else Path("site_data")
    write_payload(payload, site_dir)
    from nflmodel.export import schedule_payload
    (site_dir / f"schedule_{season}.json").write_text(
        __import__("json").dumps(schedule_payload(sched, season, target), separators=(",", ":")), encoding="utf-8")
    power = info.get("power")
    if power is not None and len(power):
        import json as _json
        from nflmodel.export import _clean
        from nflmodel.season import market_ratings, simulate_season
        fair = dict(zip(summary["game_id"], summary["fair_margin"]))
        mkt, mkt_hfa = market_ratings(sched, season, week, fair)
        # season ratings: the market-implied rating, nudged by the model by its spread blend weight
        model_net = dict(zip(power["team"], power["net_pts"]))
        rat = {t: (1 - weights[0]) * mkt[t] + weights[0] * model_net.get(t, mkt[t]) for t in mkt}
        sim = simulate_season(sched, season, rat, fair, hfa=mkt_hfa)
        for r in sim["teams"]:
            r["market_rating"], r["model_rating"] = mkt[r["team"]], model_net.get(r["team"])
        sim.update(week=week, generated=payload["generated"], demo=args.demo)
        (site_dir / f"season_{season}.json").write_text(_json.dumps(_clean(sim), separators=(",", ":")), encoding="utf-8")
    if not args.demo and not args.no_odds and not args.odds_snapshot and not args.lines_file:
        append_pick_log(payload, cfg.path("artifacts_dir") / "tracker" / "model_picks.csv")
    mm.coefficients().to_csv(cfg.path("artifacts_dir") / "margin_coefficients.csv", index=False)
    mt.coefficients().to_csv(cfg.path("artifacts_dir") / "total_coefficients.csv", index=False)

    # ---------------- console ----------------
    print(f"\n{season} week {week}: {len(target)} games" + ("  [SYNTHETIC DEMO DATA]" if args.demo else ""))
    for g in target.sort_values("kickoff_utc").itertuples():
        s = summary.set_index("game_id").loc[g.game_id]
        print(f"  {g.away_team:>3} @ {g.home_team:<3}  model {spread_text(g.home_team, g.away_team, g.model_margin):>10}"
              f"  total {g.model_total:5.1f}   market {spread_text(g.home_team, g.away_team, s['market_margin']):>10}"
              f"  total {s['market_total']:5.1f}")
    plays = board[board["is_play"]].sort_values("ev", ascending=False) if len(board) else board
    print(f"\nPlays at {cfg.target_book} with edge >= {cfg.min_ev:.1%}: {len(plays)}")
    for b in plays.itertuples():
        print(f"  {b.matchup:<11} {b.bet:<16} {fmt_american(b.price):>5}  fair {fmt_american(b.fair_price):>5}"
              f"  edge {b.ev:+.1%}  stake ${b.stake:,.0f}  {getattr(b, 'timing', '')}")
    for n in notes:
        print(f"  note: {n}")
    print(f"\nReport: {out_dir / f'line_sheet_{stem}.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
