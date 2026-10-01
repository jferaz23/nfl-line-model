#!/usr/bin/env python
"""Log Kalshi's NFL game prices (public market data, no account or key) to build a history.

Information only: nothing here feeds the model or the picks. Once there is enough history, a
Kalshi-based factor can be tested with backtest.py like any other.

For each upcoming game, from the mid of the best bid and ask on each market:
    p_home_win     "NFL Game" market (KXNFLGAME), home team's chance to win
    home_margin    the spread ladder (KXNFLSPREAD, "wins by over X") read as P(home margin > s); the
                   point where it crosses 50% (positive = home favored, like spread_line)
    total          the total ladder (KXNFLTOTAL, "over X"): where P(over) crosses 50%
A game is logged when a value changed and its last row is 60+ minutes old, and on every run in the
2 hours before kickoff (to catch the close). -> artifacts/kalshi/kalshi_nfl.csv

    python kalshi_watch.py
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger("nflmodel")
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "artifacts" / "kalshi" / "kalshi_nfl.csv"
API = "https://external-api.kalshi.com/trade-api/v2/markets"
SERIES = ("KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL")
CODES = {"JAC": "JAX", "LAR": "LA"}        # Kalshi team codes that differ from nflverse
COLS = ["ts", "game_id", "kickoff_utc", "home_team", "away_team", "p_home_win", "home_margin", "total",
        "n_spread", "n_total", "volume"]


def _markets(series: str) -> list[dict]:
    import requests
    out, cursor = [], None
    for _ in range(20):
        params = dict(series_ticker=series, status="open", limit=1000)
        if cursor:
            params["cursor"] = cursor
        r = requests.get(API, params=params, timeout=30)
        r.raise_for_status()
        d = r.json()
        out += d.get("markets", [])
        cursor = d.get("cursor")
        if not cursor:
            break
    return out


def _mid(m: dict) -> float:
    try:
        b, a = float(m.get("yes_bid_dollars") or 0), float(m.get("yes_ask_dollars") or 0)
    except (TypeError, ValueError):
        return float("nan")
    return (b + a) / 2 if b > 0 and a > 0 and a >= b else float("nan")


def _cross(points: list[tuple[float, float]]) -> float:
    """Strike where P(value > strike) crosses 50%, by linear interpolation of the sorted ladder."""
    pts = sorted((s, p) for s, p in points if np.isfinite(p))
    if len(pts) < 2:
        return float("nan")
    s = np.array([x[0] for x in pts])
    p = np.minimum.accumulate(np.array([x[1] for x in pts]))          # P(>s) must not rise with s
    for i in range(len(s) - 1):
        if p[i] >= 0.5 >= p[i + 1] and p[i] > p[i + 1]:
            return float(s[i] + (p[i] - 0.5) / (p[i] - p[i + 1]) * (s[i + 1] - s[i]))
    return float("nan")


def _code(ticker: str) -> str:
    suf = ticker.rsplit("-", 1)[1]
    t = "".join(ch for ch in suf if ch.isalpha())
    return CODES.get(t, t)


def snapshot(schedule: list[dict]) -> pd.DataFrame:
    mk = {s: _markets(s) for s in SERIES}
    games = {}                                   # event suffix -> {team: p_win}
    for m in mk["KXNFLGAME"]:
        key = m["event_ticker"].split("-", 1)[1]
        games.setdefault(key, {"vol": 0.0})[_code(m["ticker"])] = _mid(m)
        games[key]["vol"] += float(m.get("volume_fp") or 0)
    sched = [g for g in schedule if g.get("result") is None]
    rows, now = [], datetime.now(timezone.utc)
    for key, d in games.items():
        teams = [t for t in d if t != "vol"]
        if len(teams) != 2:
            continue
        try:
            day = datetime.strptime(key[:7], "%y%b%d").date()            # e.g. 26OCT12
        except ValueError:
            continue
        g = next((x for x in sched if {x["home_team"], x["away_team"]} == set(teams)
                  and abs((datetime.strptime(str(x["gameday"])[:10], "%Y-%m-%d").date() - day).days) <= 1), None)
        if g is None:
            continue
        h, a = g["home_team"], g["away_team"]
        ph = d.get(h, np.nan)
        if not np.isfinite(ph) and np.isfinite(d.get(a, np.nan)):
            ph = 1 - d[a]
        sp = []
        for m in mk["KXNFLSPREAD"]:
            if m["event_ticker"].split("-", 1)[1] != key or m.get("floor_strike") is None:
                continue
            x, p = float(m["floor_strike"]), _mid(m)
            sp.append((x, p) if _code(m["ticker"]) == h else (-x, 1 - p))     # away by > x  <=>  home margin < -x
        if np.isfinite(ph):
            sp.append((0.0, ph))
        tt = [(float(m["floor_strike"]), _mid(m)) for m in mk["KXNFLTOTAL"]
              if m["event_ticker"].split("-", 1)[1] == key and m.get("floor_strike") is not None]
        rows.append(dict(ts=now.isoformat(timespec="seconds"), game_id=g["game_id"], kickoff_utc=_kick(g),
                         home_team=h, away_team=a, p_home_win=round(ph, 4) if np.isfinite(ph) else None,
                         home_margin=round(_cross(sp), 2), total=round(_cross(tt), 2),
                         n_spread=sum(np.isfinite(p) for _, p in sp), n_total=sum(np.isfinite(p) for _, p in tt),
                         volume=round(d["vol"])))
    return pd.DataFrame(rows, columns=COLS)


def _kick(g) -> str | None:
    from nflmodel.venues import kickoff_utc
    k = kickoff_utc(g.get("gameday"), g.get("gametime"))
    return k.isoformat() if k else None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    sp = sorted((ROOT / "site_data").glob("schedule_*.json"))
    if not sp:
        log.info("No schedule yet.")
        return 0
    try:
        snap = snapshot(json.loads(sp[-1].read_text(encoding="utf-8"))["games"])
    except Exception as e:
        log.warning("Kalshi unavailable (%s); nothing logged.", e)
        return 0
    if snap.empty:
        log.info("No open Kalshi NFL game markets matched the schedule.")
        return 0
    now = datetime.now(timezone.utc)
    ko = pd.to_datetime(snap["kickoff_utc"], utc=True, errors="coerce")
    snap = snap[ko > now]                                         # pregame only
    old = pd.read_csv(OUT) if OUT.exists() else pd.DataFrame(columns=COLS)
    last = old.sort_values("ts").groupby("game_id").tail(1).set_index("game_id") if len(old) else None
    keep = []
    for r in snap.itertuples(index=False):
        near = pd.Timestamp(r.kickoff_utc) - now <= timedelta(hours=2)
        if last is None or r.game_id not in last.index:
            keep.append(True)
            continue
        o = last.loc[r.game_id]
        changed = any(not np.isclose(float(getattr(r, c) if getattr(r, c) is not None else np.nan), float(o[c]),
                                     atol=1e-9, equal_nan=True) for c in ("p_home_win", "home_margin", "total"))
        old_enough = now - pd.Timestamp(o["ts"]) >= timedelta(minutes=60)
        keep.append(near or (changed and old_enough))
    new = snap[keep]
    if len(new):
        OUT.parent.mkdir(parents=True, exist_ok=True)
        new.to_csv(OUT, mode="a", header=not OUT.exists(), index=False)
    log.info("Kalshi: %d games priced, %d rows logged.", len(snap), len(new))
    return 0


if __name__ == "__main__":
    sys.exit(main())
