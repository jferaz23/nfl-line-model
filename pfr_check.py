#!/usr/bin/env python
"""Check nflverse results against Pro Football Reference tables you saved in pfr_exports/.

Save each season's https://www.pro-football-reference.com/years/<season>/games.htm as
pfr_exports/games_<season>.html (File > Save Page As) or paste "Get table as CSV" into
pfr_exports/games_<season>.csv. Then:   python pfr_check.py
"""
import sys
from nflmodel.config import load_config
from nflmodel.data import DataStore, DataUnavailable
from nflmodel.pfr import cross_check, load_pfr_exports
from nflmodel.pipeline import setup_logging

def main():
    setup_logging()
    cfg = load_config(sys.argv[1] if len(sys.argv) > 1 else None)
    pfr, notes = load_pfr_exports(cfg.pfr_dir)
    for n in notes:
        print("note:", n)
    if pfr.empty:
        sys.exit(f"No PFR files found in {cfg.pfr_dir}/ (expected games_<season>.csv or .html).")
    print(f"Read {len(pfr)} PFR games, seasons {sorted(pfr.season.unique())}")
    try:
        sched = DataStore(cfg).schedules()
    except DataUnavailable as e:
        sys.exit(f"Could not load nflverse schedules: {e}")
    _, notes = cross_check(pfr, sched)
    for n in notes:
        print(n)

if __name__ == "__main__":
    main()
