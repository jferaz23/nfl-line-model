#!/usr/bin/env python
"""Kickoff keeper (.github/workflows/keeper.yml): GitHub starts scheduled workflows late or not at all when busy (from
Oct 30, 2026 the 15-minute Update schedule fired only 3-5 times a day, so the pre-kickoff run after inactives was
missed). This job starts shortly before a game window, sleeps until each must-run moment in the next few hours and
dispatches the Update workflow then; scheduler.py sees the window and runs the mandatory Odds API update.

Must-run moments: 80 minutes before every kickoff this week (inactives are announced 90 minutes before), and the
Wednesday-Friday injury reports at 4:40 PM Eastern.

    python keeper.py            # wait and dispatch (needs GH_TOKEN with actions: write)
    python keeper.py --dry-run  # only print the moments it would dispatch at
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
ET = ZoneInfo("America/New_York")
HORIZON = timedelta(hours=5, minutes=15)      # stay within the job's time limit
PRE_KICK = timedelta(minutes=80)


def moments(now: datetime) -> list[tuple[datetime, str]]:
    out = []
    weeks = sorted((ROOT / "site_data").glob("week_*.json"))
    if weeks:
        p = json.loads(weeks[-1].read_text(encoding="utf-8"))
        kicks = set()
        for g in p.get("games", []):
            try:
                kicks.add(datetime.fromisoformat(str(g["kickoff_utc"]).replace("Z", "+00:00")).astimezone(timezone.utc))
            except Exception:
                pass
        out += [(k - PRE_KICK, f"inactives before the {k.astimezone(ET):%a %I:%M %p} ET kickoff") for k in sorted(kicks)]
    for d in range(3):
        day = (now.astimezone(ET) + timedelta(days=d)).date()
        if day.weekday() in (2, 3, 4):
            t = datetime(day.year, day.month, day.day, 16, 40, tzinfo=ET).astimezone(timezone.utc)
            out.append((t, f"{day:%A} injury report"))
    return sorted(x for x in out if now - timedelta(minutes=2) <= x[0] <= now + HORIZON)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test", action="store_true", help="dispatch Update once right now (checks the token works)")
    args = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    todo = [(now, "test dispatch")] if args.test else moments(now)
    if not todo:
        print("nothing to dispatch in the next", HORIZON)
        return 0
    for t, why in todo:
        print(f"{t.astimezone(ET):%a %b %d %I:%M %p} ET  {why}", flush=True)
    if args.dry_run:
        return 0
    for t, why in todo:
        wait = (t - datetime.now(timezone.utc)).total_seconds()
        if wait > 0:
            time.sleep(wait)
        r = subprocess.run(["gh", "workflow", "run", "update.yml", "--ref", "main"], capture_output=True, text=True)
        print(f"{datetime.now(ET):%I:%M %p} ET dispatched Update ({why}): {'ok' if r.returncode == 0 else r.stderr.strip()}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
