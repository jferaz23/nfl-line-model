#!/usr/bin/env python
"""Reprice this week's picks with DraftKings' current line and prices from ESPN's scoreboard.

Runs every 15 minutes (GitHub Actions). No model run and no Odds API credits: the model's numbers
come from the latest weekly run in site_data/, the prices from ESPN (its line provider is
DraftKings). Games that have kicked off keep the last pre-kickoff pick (build_site.py fills them
from the pick log).

- rewrites site_data/week_<s>_<w>.json in the runner (not committed; the next run starts again
  from the committed model run)
- appends to artifacts/tracker/picks_log.csv only when a pick's side, line or price changed

    python reprice.py
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from nflmodel import espn
from nflmodel.picks import pair_teasers, teaser_legs, week_picks

log = logging.getLogger("nflmodel")
ROOT = Path(__file__).resolve().parent
LOG = ROOT / "artifacts" / "tracker" / "picks_log.csv"
FIELDS = {"home_spread": "dk_home_spread", "home_spread_price": "dk_home_spread_price",
          "away_spread_price": "dk_away_spread_price", "total": "dk_total", "over_price": "dk_over_price",
          "under_price": "dk_under_price", "home_ml": "dk_home_ml", "away_ml": "dk_away_ml"}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    weeks = sorted((ROOT / "site_data").glob("week_*.json"))
    if not weeks:
        log.info("No weekly run yet.")
        return 0
    path = weeks[-1]
    p = json.loads(path.read_text(encoding="utf-8"))
    try:
        sb = espn.scoreboard(int(p["season"]), int(p["week"]))
    except Exception as e:
        log.warning("ESPN scoreboard unavailable (%s); keeping the last prices.", e)
        return 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    by = {(r.home_team, r.away_team): r for r in sb.itertuples(index=False)}
    n = 0
    for g in p["games"]:
        r = by.get((g["home_team"], g["away_team"]))
        if r is None or r.state != "pre" or pd.isna(r.home_spread):
            continue
        for src, dst in FIELDS.items():
            v = getattr(r, src)
            g[dst] = None if v is None or pd.isna(v) else float(v)
        g["dk_away_spread"] = -g["dk_home_spread"] if g.get("dk_home_spread") is not None else None
        g["dk_source"], g["dk_updated"] = "ESPN", now
        n += 1
    if not n:
        log.info("No pre-game DraftKings lines on ESPN right now.")
        return 0
    live_ids = {g["game_id"] for g in p["games"] if g.get("dk_source") == "ESPN"}
    picks = [x for x in week_picks(p["games"], p["curves"]) if x["game_id"] in live_ids]
    keep = [x for x in p.get("picks", []) if x["game_id"] not in live_ids]     # started games: model-run pick
    p["picks"] = picks + keep
    legs = teaser_legs([g for g in p["games"] if g["game_id"] in live_ids], p.get("teasers", {}).get("leg_rate", 0.74))
    p["teasers"] = dict(p.get("teasers", {}), legs=legs, pairs=pair_teasers(legs))
    p["priced_at"], p["price_source"] = now, "ESPN scoreboard (DraftKings), repriced every 15 minutes"
    path.write_text(json.dumps(p, separators=(",", ":")), encoding="utf-8")

    # log a pick only when it changed, so the last pre-kickoff pick is graded at its latest price
    rows = pd.DataFrame(picks)
    if len(rows):
        rows.insert(0, "run_at", now)
        if LOG.exists():
            old = pd.read_csv(LOG, on_bad_lines="skip")
            last = old.sort_values("run_at").groupby(["game_id", "market"]).tail(1).set_index(["game_id", "market"])
            keep_rows = []
            for r in rows.itertuples(index=False):
                k = (r.game_id, r.market)
                if k not in last.index:
                    keep_rows.append(True)
                    continue
                o = last.loc[k]
                keep_rows.append(str(o["bet"]) != str(r.bet) or abs(float(o["price"]) - float(r.price)) > 1e-9)
            rows = rows[keep_rows]
            cols = list(old.columns)
            rows = rows.reindex(columns=cols + [c for c in rows.columns if c not in cols])
            if len(rows):
                if list(rows.columns) != cols:
                    pd.concat([old, rows], ignore_index=True).to_csv(LOG, index=False)
                else:
                    rows.to_csv(LOG, mode="a", header=False, index=False)
        else:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            rows.to_csv(LOG, index=False)
    log.info("Repriced %d games from ESPN (DraftKings); %d pick changes logged.", n, len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
