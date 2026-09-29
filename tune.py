#!/usr/bin/env python
"""Tune the settings that control how fast the model forgets (walk-forward, out of sample).

How quickly team ratings and QB values react to new games, and how much they carry over between
seasons, matter more than most individual factors. This script tries a few values of each setting
one at a time (coordinate search), rebuilding the features and re-running the walk-forward test for
each, and writes the best combination to artifacts/tuned_config.json. Use it with:

    python tune.py                      # real data: slow (each try rebuilds all features)
    python tune.py --demo --quick       # smoke test on the synthetic league
    python run_week.py --config artifacts/tuned_config.json
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
import time

import numpy as np

from backtest import walk_forward
from nflmodel.config import load_config
from nflmodel.data import DataUnavailable
from nflmodel.features import build_games
from nflmodel.pipeline import apply_demo, demo_data, load_real, setup_logging

log = logging.getLogger("nflmodel")

GRID = {
    "rating_half_life_weeks": [5, 8, 12],
    "offseason_decay": [0.45, 0.6, 0.75],
    "qb_half_life_weeks": [16, 26, 40],
    "qb_prior_plays": [120, 200, 320],
}
QUICK = {"rating_half_life_weeks": [6, 10], "offseason_decay": [0.5, 0.7]}


def score(data, cfg, seasons):
    games, _ = build_games(data, cfg)
    games = games[games["has_ratings"] & games["result"].notna()]
    oos, _ = walk_forward(games, cfg, seasons, use_gbm=False)
    m = float(np.abs(oos["result"] - oos["model_margin"]).mean())
    t = float(np.abs(oos["total"] - oos["model_total"]).mean())
    return m + t, m, t


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--quick", action="store_true", help="small grid (for testing)")
    ap.add_argument("--seasons", type=int, default=3, help="most recent seasons to score on")
    ap.add_argument("--config")
    args = ap.parse_args(argv)
    setup_logging()
    base = load_config(args.config)
    if args.demo:
        apply_demo(base)
        data, _, _ = demo_data(base)
    else:
        try:
            data, _ = load_real(base, need_current=False)
        except DataUnavailable as e:
            sys.exit(f"Could not load nflverse data: {e}")
    done = data["schedules"].dropna(subset=["result"])
    seasons = sorted(done["season"].unique())[-args.seasons:]
    grid = QUICK if args.quick else GRID
    best_cfg = copy.deepcopy(base)
    t0 = time.time()
    best, bm, bt = score(data, best_cfg, seasons)
    print(f"start: spread miss {bm:.3f}, total miss {bt:.3f}")
    for key, values in grid.items():
        for v in values:
            if getattr(best_cfg, key) == v:
                continue
            c = copy.deepcopy(best_cfg)
            setattr(c, key, v)
            s, m, t = score(data, c, seasons)
            print(f"  {key}={v}: spread {m:.3f}, total {t:.3f}" + ("  <- better" if s < best - 1e-4 else ""))
            if s < best - 1e-4:
                best, bm, bt, best_cfg = s, m, t, c
    tuned = {k: getattr(best_cfg, k) for k in grid}
    out = best_cfg.path("artifacts_dir") / "tuned_config.json"
    out.write_text(json.dumps(tuned, indent=2))
    print(f"best: spread miss {bm:.3f}, total miss {bt:.3f} with {tuned} ({time.time() - t0:.0f}s). Saved {out}")
    print("Scores come from the same seasons the settings were chosen on, so expect a little less on new data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
