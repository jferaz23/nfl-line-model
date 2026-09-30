#!/usr/bin/env python
"""Decide what the 15-minute job does this time. Prints `mode=` and `reason=` for GitHub Actions.

mode=api      full model run priced with The Odds API (DraftKings + sharp books; 3 credits)
mode=espn     full model run priced with DraftKings' line from ESPN (free): fresh injuries and weather
mode=reprice  no model run: reprice picks with ESPN's DraftKings line (free), rebuild the site

Mandatory Odds API runs (never skipped while credits last):
  - injury reports: Wednesday, Thursday and Friday at about 4:30 PM ET (the league posts ~4 PM ET)
  - before every kickoff time this week: about 80 minutes before kickoff, just after teams announce
    inactives (90 minutes before)
Paced Odds API runs: the credits left after reserving the mandatory runs until the quota refills are
spread evenly until then (the refill date is learned from the balance; see next_reset). Model refresh from ESPN every 3 hours otherwise.

State (committed): artifacts/odds_budget.json. run_week.py records the credits left after each API run.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "artifacts" / "odds_budget.json"
ET = ZoneInfo("America/New_York")
CREDITS_PER_RUN = 3
RESERVE = 12                      # never spend the last few credits
MANDATORY_PER_WEEK = 9            # injury reports (3) + kickoff windows (~6)
ESPN_REFRESH_HOURS = 3.0
PRE_KICK = (timedelta(minutes=88), timedelta(minutes=70))   # window before kickoff: after inactives (T-90)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(s: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1))


def kickoffs() -> list[datetime]:
    weeks = sorted((ROOT / "site_data").glob("week_*.json"))
    if not weeks:
        return []
    p = json.loads(weeks[-1].read_text(encoding="utf-8"))
    out = set()
    for g in p.get("games", []):
        try:
            out.add(datetime.fromisoformat(str(g["kickoff_utc"]).replace("Z", "+00:00")).astimezone(timezone.utc))
        except Exception:
            pass
    return sorted(out)


def next_reset(now: datetime, s: dict) -> datetime:
    """When the Odds API quota next refills. Unknown until a refill has been seen (run_week.py records
    reset_at when the balance jumps up); until then assume 30 days after the balance was first seen,
    so an early refill only means credits were saved, never that they ran out."""
    def parse(x):
        return datetime.fromisoformat(x).astimezone(timezone.utc)
    if s.get("reset_at"):
        r = parse(s["reset_at"])
        while r <= now:
            m = r.month % 12 + 1
            y = r.year + (r.month == 12)
            try:
                r = r.replace(year=y, month=m)
            except ValueError:                       # e.g. the 31st in a 30-day month
                r = r.replace(year=y, month=m, day=28)
        return r
    first = parse(s.get("first_seen") or s.get("remaining_at") or now.isoformat())
    r = first + timedelta(days=30)
    while r <= now:
        r += timedelta(days=30)
    return r


def decide(now: datetime, s: dict) -> tuple[str, str, str | None]:
    """Returns (mode, reason, tag). tag marks a mandatory run so it happens once."""
    done = set(s.get("done", []))
    remaining = s.get("remaining")
    can_api = remaining is None or remaining - CREDITS_PER_RUN >= RESERVE
    et = now.astimezone(ET)
    # 1) injury reports (Wed/Thu/Fri ~4:30 PM ET)
    if et.weekday() in (2, 3, 4) and 16 * 60 + 20 <= et.hour * 60 + et.minute <= 17 * 60 + 5:
        tag = f"injury-{et.date()}"
        if tag not in done:
            return ("api" if can_api else "espn"), f"mandatory: {et:%A} injury report", tag
    # 2) before each kickoff time
    for k in kickoffs():
        if k - PRE_KICK[0] <= now <= k - PRE_KICK[1]:
            tag = f"pregame-{k:%Y%m%dT%H%M}"
            if tag not in done:
                return ("api" if can_api else "espn"), f"mandatory: inactives, {k.astimezone(ET):%a %I:%M %p} ET kickoff", tag
    # 3) paced Odds API runs with what is left after reserving mandatory runs
    last_api = s.get("last_api_run")
    if can_api and remaining is not None:
        hours_left = max((next_reset(now, s) - now).total_seconds() / 3600, 1.0)
        mand_left = MANDATORY_PER_WEEK * hours_left / 168.0
        spare = (remaining - RESERVE) / CREDITS_PER_RUN - mand_left
        if spare >= 1:
            interval = hours_left / spare
            since = (now - datetime.fromisoformat(last_api)).total_seconds() / 3600 if last_api else 1e9
            if since >= interval:
                return "api", f"paced: every {interval:.1f} h to last the month ({remaining} credits left)", None
    elif remaining is None:
        return "api", "first run: learning the credit balance", None
    # 4) free model refresh from ESPN lines
    last_model = s.get("last_model_run")
    since_m = (now - datetime.fromisoformat(last_model)).total_seconds() / 3600 if last_model else 1e9
    if since_m >= ESPN_REFRESH_HOURS:
        return "espn", f"model refresh (every {ESPN_REFRESH_HOURS:.0f} h, free)", None
    return "reprice", "reprice with DraftKings' current line (every 15 min, free)", None


def main() -> int:
    now = datetime.now(timezone.utc)
    s = load_state()
    force = os.environ.get("FORCE_MODE", "").strip()
    mode, reason, tag = (force, "manual run", None) if force in ("api", "espn", "reprice") else decide(now, s)
    if mode in ("api", "espn"):
        s["last_model_run"] = now.isoformat(timespec="seconds")
    if mode == "api":
        s["last_api_run"] = now.isoformat(timespec="seconds")
    if tag:
        s["done"] = (s.get("done", []) + [tag])[-60:]
    if mode != "reprice":              # only real runs touch the committed state (no commit every 15 min)
        s["last_decision"] = dict(at=now.isoformat(timespec="seconds"), mode=mode, reason=reason)
        save_state(s)
    out = os.environ.get("GITHUB_OUTPUT")
    line = f"mode={mode}\nreason={reason}\n"
    if out:
        with open(out, "a") as f:
            f.write(line)
    print(line.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
