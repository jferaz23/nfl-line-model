#!/usr/bin/env python
"""Phone notifications for pick changes, through ntfy (https://ntfy.sh, free, no account).

Off unless the NTFY_TOPIC secret is set. Sends each new pick-change alert from the site build
(public/data/site.js "alerts", level "high": green/Top on or off, green side switch, wind under on
or off) once, then remembers it in artifacts/alerts_sent.json. The first run after switching on only
records what is already there, so it never floods the phone with old alerts.

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
FRESH = timedelta(hours=3)        # only push changes this recent (older ones, e.g. from a log repair, are just recorded)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        log.info("Phone notifications off (no NTFY_TOPIC).")
        return 0
    if not SITE.exists():
        return 0
    txt = SITE.read_text(encoding="utf-8")
    alerts = [a for a in json.loads(txt[txt.index("=") + 1:].rstrip().rstrip(";")).get("alerts", []) if a.get("level") == "high"]
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
    if not first:
        import requests
        for a in sorted(new, key=lambda x: x["ts"])[:10]:
            try:
                requests.post(f"https://ntfy.sh/{topic}", data=a["text"].encode("utf-8"), timeout=20,
                              headers={"Title": f"{a['title']}: {a['matchup']}",
                                       "Click": SITE_URL, "Tags": "football"}).raise_for_status()
            except Exception as e:
                log.warning("ntfy send failed (%s); will retry next run.", e)
                new = [x for x in new if x is not a]
    keep = sorted(sent | {a["id"] for a in new} | {a["id"] for a in stale} | ({a["id"] for a in alerts} if first else set()))[-4000:]
    SENT.parent.mkdir(parents=True, exist_ok=True)
    SENT.write_text(json.dumps(keep))
    log.info("Phone notifications: %s", "set up (existing alerts recorded, none sent)" if first else f"{len(new)} sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
