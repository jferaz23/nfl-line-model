#!/usr/bin/env python
"""Line watch: log DraftKings' line (as shown on ESPN's scoreboard) and live scores.

Runs every 20 minutes from GitHub Actions. Cheap: one ESPN request, no Odds API credits.
- artifacts/lines/espn_lines.csv  one row per game whenever its line, prices or status change
                                  (line history charts, the movement model, closing lines for CLV)
- site_data/live.json             the current week's scoreboard (status, clock, score) for the site

    python line_watch.py
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pandas as pd

from nflmodel import espn
from build_site import _clean

log = logging.getLogger("nflmodel")
ROOT = Path(__file__).resolve().parent
LOG = ROOT / "artifacts" / "lines" / "espn_lines.csv"
LIVE = ROOT / "site_data" / "live.json"
KEY = ["home_spread", "total", "home_spread_price", "away_spread_price", "over_price", "under_price",
       "home_ml", "away_ml", "state"]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    try:
        cur = espn.scoreboard()              # ESPN's current week (last week's games until Wednesday)
        frames = [cur]
        if len(cur) and int(cur["season_type"].iloc[0]) == 2 and int(cur["week"].iloc[0]) < 18:
            frames.append(espn.scoreboard(int(cur["season"].iloc[0]), int(cur["week"].iloc[0]) + 1))
        sb = pd.concat([f for f in frames if len(f)], ignore_index=True)
    except Exception as e:
        log.warning("ESPN scoreboard unavailable: %s", e)
        return 0                      # never fail the workflow over a flaky feed
    if sb.empty:
        log.info("No games on the scoreboard.")
        return 0

    LOG.parent.mkdir(parents=True, exist_ok=True)
    new = sb.copy()
    if LOG.exists():
        old = pd.read_csv(LOG, dtype={"espn_id": str})
        last = old.sort_values("ts").groupby("espn_id").tail(1).set_index("espn_id")
        keep = []
        for r in new.itertuples(index=False):
            if r.espn_id not in last.index:
                keep.append(True)
                continue
            prev = last.loc[r.espn_id]
            changed = False
            for k in KEY:
                a, b = getattr(r, k), prev.get(k)
                if pd.isna(a) and pd.isna(b):
                    continue
                if (pd.isna(a) != pd.isna(b)) or (str(a) != str(b) and not _num_eq(a, b)):
                    changed = True
                    break
            keep.append(changed)
        new = new[keep]
    log_cols = [c for c in sb.columns if c not in ("clock", "period", "detail", "venue", "broadcast")]
    if len(new):
        new[log_cols].to_csv(LOG, mode="a", header=not LOG.exists(), index=False)
    log.info("Scoreboard %s weeks %s: %d games, %d line/status changes logged.",
             sb["season"].iloc[0], sorted(sb["week"].unique().tolist()), len(sb), len(new))

    LIVE.parent.mkdir(parents=True, exist_ok=True)
    LIVE.write_text(json.dumps(_clean(dict(
        checked=sb["ts"].iloc[0], season=int(sb["season"].iloc[0]), week=int(sb["week"].max()),
        season_type=int(sb["season_type"].iloc[0]) if "season_type" in sb else 2,
        games=sb.to_dict("records"))), separators=(",", ":")), encoding="utf-8")
    return 0


def _num_eq(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return False


if __name__ == "__main__":
    sys.exit(main())
