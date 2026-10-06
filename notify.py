#!/usr/bin/env python
"""Phone notifications through ntfy (https://ntfy.sh, free, no account).

Off unless the NTFY_TOPIC secret is set. From the site build's alerts (public/data/site.js):
  pick changes (level "high": green/Top on or off, green side switch, wind under on or off): one push each
  DraftKings line moves (kind "line", pregame spread/total moves): one combined push per run
Channels: <topic> gets everything; <topic>-picks pick changes only; <topic>-top Top-pick changes only.
Settings in overrides/alerts.json: line_moves on/off, quiet_hours_et [start, end) when line moves are held
(recorded, not sent; pick changes always go out).
Each alert is sent once (remembered in artifacts/alerts_sent.json) and only if it is less than FRESH old;
the first run after switching on only records what is already there.

    NTFY_TOPIC=<your topic> python notify.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("nflmodel")
ROOT = Path(__file__).resolve().parent
SITE = ROOT / "public" / "data" / "site.js"
SENT = ROOT / "artifacts" / "alerts_sent.json"
SITE_URL = "https://jferaz23.github.io/nfl-line-model/#alerts"
SETTINGS = ROOT / "overrides" / "alerts.json"


def settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def quiet_now(cfg: dict) -> bool:
    q = cfg.get("quiet_hours_et")
    if not q or len(q) != 2:
        return False
    from zoneinfo import ZoneInfo
    h = datetime.now(ZoneInfo("America/New_York")).hour
    a, b = int(q[0]), int(q[1])
    return a <= h < b if a <= b else (h >= a or h < b)
FRESH = timedelta(hours=3)        # only push changes this recent (older ones, e.g. from a log repair, are just recorded)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    topic = os.environ.get("NTFY_TOPIC", "").replace("﻿", "").strip()      # drop a BOM / whitespace from the secret
    if not topic:
        log.info("Phone notifications off (no NTFY_TOPIC).")
        return 0
    if not SITE.exists():
        return 0
    txt = SITE.read_text(encoding="utf-8")
    allx = json.loads(txt[txt.index("=") + 1:].rstrip().rstrip(";")).get("alerts", [])
    alerts = [a for a in allx if a.get("level") == "high"]
    moves = [a for a in allx if a.get("kind") == "line"]
    first = not SENT.exists()
    sent = set(json.loads(SENT.read_text()) if SENT.exists() else [])
    new = [a for a in alerts if a["id"] not in sent]
    cutoff = datetime.now(timezone.utc) - FRESH
    def fresh(a):
        try:
            return datetime.fromisoformat(a["ts"].replace("Z", "+00:00")) >= cutoff
        except Exception:
            return False
    stale = [a for a in new if not fresh(a)]
    new = [a for a in new if fresh(a)]
    cfg = settings()
    if not first:
        import requests
        for a in sorted(new, key=lambda x: x["ts"])[:10]:
            hdr = {"Title": f"{a['title']}: {a['matchup']}", "Click": SITE_URL, "Tags": "football"}
            try:
                requests.post(f"https://ntfy.sh/{topic}", data=a["text"].encode("utf-8"), timeout=20, headers=hdr).raise_for_status()
            except Exception as e:
                log.warning("ntfy send failed (%s); will retry next run.", e)
                new = [x for x in new if x is not a]
                continue
            extra = [f"{topic}-picks"] + ([f"{topic}-top"] if "Top" in a.get("title", "") else [])
            for t2 in extra:                       # optional channels: best effort, never re-sent
                try:
                    requests.post(f"https://ntfy.sh/{t2}", data=a["text"].encode("utf-8"), timeout=20, headers=hdr)
                except Exception as e:
                    log.warning("ntfy extra channel failed (%s).", e)
    # line moves: one combined push per run (lower priority than pick changes)
    mnew = [a for a in moves if a["id"] not in sent]
    mfresh = [a for a in mnew if fresh(a)] if not first else []
    held = bool(mfresh) and (not cfg.get("line_moves", True) or quiet_now(cfg))
    msent = []
    if held:                                   # quiet hours / switched off: record them, don't push
        msent, mfresh = mfresh, []
    if mfresh:
        import requests
        mfresh = sorted(mfresh, key=lambda x: x["ts"])
        body = "\n".join(f"{a['matchup']}: {a['text']}" for a in mfresh[:12])
        if len(mfresh) > 12:
            body += f"\n+{len(mfresh) - 12} more on the Alerts tab"
        try:
            requests.post(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), timeout=20,
                          headers={"Title": f"DraftKings line move{'s' if len(mfresh) > 1 else ''} ({len(mfresh)})",
                                   "Click": SITE_URL, "Tags": "chart_with_upwards_trend", "Priority": "low"}).raise_for_status()
            msent = mfresh
        except Exception as e:
            log.warning("ntfy line-move send failed (%s); will retry next run.", e)
    mdone = {a["id"] for a in msent} | {a["id"] for a in mnew if not fresh(a)} | ({a["id"] for a in moves} if first else set())
    keep = sorted(sent | {a["id"] for a in new} | {a["id"] for a in stale} | mdone | ({a["id"] for a in alerts} if first else set()))[-4000:]
    SENT.parent.mkdir(parents=True, exist_ok=True)
    SENT.write_text(json.dumps(keep))
    log.info("Phone notifications: %s", "set up (existing alerts recorded, none sent)" if first
             else f"{len(new)} pick changes, {len(msent)} line moves {'held (quiet hours or off)' if held else 'sent'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
