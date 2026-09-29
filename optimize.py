#!/usr/bin/env python
"""One command to re-optimize the model: tune memory settings, then backtest, prune and calibrate.

    python optimize.py                 # full run on real data (slow the first time: downloads + tuning)
    python optimize.py --skip-tune     # keep the current tuned settings, just re-backtest and recalibrate
    python optimize.py --demo --quick  # smoke test on the synthetic league

What it does, in order:
  1. tune.py      - picks rating/QB memory settings walk-forward  -> artifacts/tuned_config.json
  2. backtest.py  - with those settings: drops factor groups that hurt (chosen on earlier seasons,
                    confirmed on the last one), picks the boosting weight for spreads and totals,
                    the model-vs-market blend, the game-by-game (error-weighted) blend, how outcome
                    spread grows with the total, and the line-movement model -> artifacts/calibration.json
run_week.py picks all of this up automatically.
"""
import argparse
import sys

import backtest
import tune


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--quick", action="store_true", help="small tuning grid")
    ap.add_argument("--skip-tune", action="store_true")
    ap.add_argument("--start", type=int)
    ap.add_argument("--end", type=int)
    ap.add_argument("--config")
    args = ap.parse_args(argv)
    common = (["--demo"] if args.demo else []) + (["--config", args.config] if args.config else [])
    if not args.skip_tune:
        print("== Step 1: tuning memory settings ==")
        tune.main(common + (["--quick"] if args.quick else []))
    print("\n== Step 2: backtest, pruning and calibration ==")
    bt = common + (["--start", str(args.start)] if args.start else []) + (["--end", str(args.end)] if args.end else [])
    return backtest.main(bt)


if __name__ == "__main__":
    sys.exit(main())
