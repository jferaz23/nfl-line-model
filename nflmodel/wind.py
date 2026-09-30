"""Wind unders: bet the under in outdoor games when the kickoff forecast shows wind of 10+ mph or gusts
of 20+ mph (averaged over kickoff to +3 hours, the same window weather.py uses).

Research (docs, 2026-09-30): closing totals under-react to wind. Unders at the closing total and price,
outdoor games: wind 10+ mph recorded at kickoff 401-285 (58.5%) 2015-2026; using only archived
short-range forecasts, 2022-26 wind 10+ 95-61 (60.9%) and gusts 20+ 103-60 (63.2%), vs 52.0% for all
outdoor games. The 2018-21 archived forecasts were not looked at when the rule was chosen, so they are
an independent check (reported by build_history).

Live: run_week.py makes the pick from Open-Meteo's forecast; it is final at the run ~80 minutes before
kickoff (forecasts days ahead are much noisier than the short-range ones the record is built on).
History: `python -m nflmodel.wind` writes artifacts/wind_history.csv from nflverse schedules (recorded
wind, closing total and under price) and Open-Meteo's Historical Forecast API (archived forecasts,
usable from 2018). `--update` only adds games not in the file yet (and retries games whose archived
forecast was missing).
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import time
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .picks import HIGHLIGHT
from .venues import is_indoor, kickoff_utc, resolve_venue

log = logging.getLogger("nflmodel")
WIND_MPH = 10.0
GUST_MPH = 20.0
SHRINK = 200.0                    # prior games at 50% when turning the record into a chance
FORECAST_FROM = 2018              # archived forecasts have wind and gust data from 2018 on
ARCHIVE = "https://historical-forecast-api.open-meteo.com/v1/forecast"


def triggers(wind, gust) -> bool:
    w = float(wind) if wind is not None and np.isfinite(wind) else float("nan")
    g = float(gust) if gust is not None and np.isfinite(gust) else float("nan")
    return bool((np.isfinite(w) and w >= WIND_MPH) or (np.isfinite(g) and g >= GUST_MPH))


def breakeven(price) -> float:
    try:
        a = float(price)
    except (TypeError, ValueError):
        return float("nan")
    if not math.isfinite(a) or abs(a) < 100:
        return float("nan")
    return -a / (-a + 100.0) if a < 0 else 100.0 / (a + 100.0)


def is_bet(chance: float, price) -> bool:
    """The green-pick price test: at least 1 point of value over the under price's break-even. Live games
    need a DraftKings price; a missing historical price counts as -110, as in grading."""
    be = breakeven(price)
    return bool(chance - (be if np.isfinite(be) else breakeven(-110)) >= HIGHLIGHT)


def rule_rate(hist: pd.DataFrame | None) -> tuple[float, int, int]:
    """Chance a wind under wins, from the forecast-based record (pushes excluded), shrunk toward 50%."""
    if hist is None or hist.empty:
        return 0.5, 0, 0
    h = hist[hist["fc_rule"].astype(bool) & hist["result"].isin(["W", "L"])]
    w, n = int((h["result"] == "W").sum()), len(h)
    return (w + 0.5 * SHRINK) / (n + SHRINK), w, n - w


def week_wind_unders(games: list[dict], chance: float) -> list[dict]:
    """Wind unders for a weekly payload: outdoor games with a real forecast that triggers the rule."""
    out = []
    for g in games:
        if g.get("wx_source") != "forecast":
            continue
        wind, gust = g.get("wind_used"), g.get("gust_used")
        wind = float(wind) if wind is not None else float("nan")
        gust = float(gust) if gust is not None else float("nan")
        active = triggers(wind, gust)
        tl, price = g.get("dk_total"), g.get("dk_under_price")
        be = breakeven(price)
        on = bool(active and tl is not None and np.isfinite(be))
        out.append(dict(game_id=g["game_id"], season=g["season"], week=g["week"], home_team=g["home_team"],
                        away_team=g["away_team"], kickoff_utc=g.get("kickoff_utc"), market="wind", side="under",
                        wind=wind, gust=gust, active=on, highlight=bool(on and is_bet(chance, price)),
                        bet=f"Under {float(tl):g}" if tl is not None else None, line=float(tl) if tl is not None else None,
                        price=float(price) if price is not None else None, chance=chance, breakeven=be,
                        value=chance - be if np.isfinite(be) else float("nan")))
    return out


# ----------------------------------------------------------------------------- history
def _grade_under(total, line) -> str | None:
    if not (np.isfinite(total) and np.isfinite(line)):
        return None
    d = line - total
    return "W" if d > 1e-9 else ("L" if d < -1e-9 else "P")


def _profit(res, price) -> float | None:
    if res is None:
        return None
    p = float(price) if price is not None and np.isfinite(price) and abs(price) >= 100 else -110.0
    return 0.0 if res == "P" else (-1.0 if res == "L" else (p / 100.0 if p > 0 else 100.0 / -p))


def _fetch_archive(lat, lon, start, end) -> dict:
    import requests
    p = dict(latitude=lat, longitude=lon, start_date=start, end_date=end,
             hourly="temperature_2m,precipitation,snowfall,wind_speed_10m,wind_gusts_10m",
             temperature_unit="fahrenheit", wind_speed_unit="mph", precipitation_unit="inch", timezone="UTC")
    for attempt in range(3):
        try:
            r = requests.get(ARCHIVE, params=p, timeout=90)
            r.raise_for_status()
            return r.json().get("hourly", {})
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
    return {}


def build_history(sched: pd.DataFrame, out: Path, start: int = 2015, update: bool = False) -> pd.DataFrame:
    from .weather import summarize
    s = sched[(sched["season"] >= start) & sched["result"].notna() & sched["total_line"].notna()].copy()
    old = pd.read_csv(out) if (update and out.exists()) else pd.DataFrame()
    if len(old):
        # retry forecast-era games whose archived forecast was not published yet at the last update
        old = old[~((old["season"] >= FORECAST_FROM) & ~old["fc_known"].astype(bool))]
        s = s[~s["game_id"].isin(set(old["game_id"]))]
    rows = []
    for r in s.itertuples(index=False):
        ven = resolve_venue(r.home_team, r.season, r.stadium, r.location)
        roof = r.roof if isinstance(r.roof, str) and r.roof else ven["roof"]
        # the live pipeline only forecasts open-air venues (retractable roofs are assumed closed)
        if is_indoor(ven["roof"]) >= 0.5 or is_indoor(roof) >= 0.5:
            continue
        ko = kickoff_utc(r.gameday, r.gametime)
        if ko is None:
            continue
        rows.append(dict(game_id=r.game_id, season=int(r.season), week=int(r.week), game_type=r.game_type,
                         home_team=r.home_team, away_team=r.away_team, kickoff_utc=ko.isoformat(),
                         lat=round(float(ven["lat"]), 3), lon=round(float(ven["lon"]), 3),
                         rec_wind=pd.to_numeric(r.wind, errors="coerce"), total_line=float(r.total_line),
                         total=float(r.total), under_odds=pd.to_numeric(r.under_odds, errors="coerce")))
    new = pd.DataFrame(rows)
    if len(new):
        new["fc_wind"], new["fc_gust"] = np.nan, np.nan
        new["ko"] = pd.to_datetime(new["kickoff_utc"], utc=True)
        for (lat, lon, season), grp in new[new["season"] >= FORECAST_FROM].groupby(["lat", "lon", "season"]):
            a = grp["ko"].min().strftime("%Y-%m-%d")
            b = (grp["ko"].max() + timedelta(days=1)).strftime("%Y-%m-%d")
            try:
                hourly = _fetch_archive(lat, lon, a, b)
            except Exception as e:
                log.warning("archive forecast failed for %s,%s %s: %s", lat, lon, season, e)
                continue
            for i, r in grp.iterrows():
                fc = summarize(hourly, r["ko"].to_pydatetime()) if hourly else None
                if fc:
                    new.loc[i, "fc_wind"], new.loc[i, "fc_gust"] = fc["wind_mph"], fc["gust_mph"]
            time.sleep(0.3)
        new = new.drop(columns=["ko"])
        new["fc_rule"] = [triggers(w, g) for w, g in zip(new["fc_wind"], new["fc_gust"])]
        new["fc_known"] = new["fc_wind"].notna() | new["fc_gust"].notna()
        new["rec_rule"] = new["rec_wind"] >= WIND_MPH
        new["result"] = [_grade_under(t, l) for t, l in zip(new["total"], new["total_line"])]
        new["units"] = [_profit(x, p) for x, p in zip(new["result"], new["under_odds"])]
    allh = pd.concat([old, new], ignore_index=True) if len(old) else new
    allh = allh.sort_values(["season", "week", "game_id"]).reset_index(drop=True)
    allh["units"] = pd.to_numeric(allh["units"], errors="coerce").round(6)   # stable text across updates
    out.parent.mkdir(parents=True, exist_ok=True)
    allh.to_csv(out, index=False)
    return allh


def summary(hist: pd.DataFrame) -> dict:
    """Records for the site: the rule as used (forecast, 2018 on) and the recorded-wind version (2015 on)."""
    def rec(d):
        g = d[d["result"].isin(["W", "L", "P"])]
        w, l, p = int((g["result"] == "W").sum()), int((g["result"] == "L").sum()), int((g["result"] == "P").sum())
        u = pd.to_numeric(g["units"], errors="coerce").dropna()
        return dict(w=w, l=l, p=p, n=w + l + p, pct=w / max(w + l, 1), units=float(u.sum()),
                    roi=float(u.sum() / len(u)) if len(u) else None)
    if hist is None or hist.empty:
        return {}
    h = hist.copy()
    # same rule as live: the wind trigger, then the price must leave 1+ point of value at the rule's chance
    chance = rule_rate(h)[0]
    ok = np.array([is_bet(chance, p) for p in h["under_odds"]], dtype=bool)
    h["fc_rule"], h["rec_rule"] = h["fc_rule"].astype(bool) & ok, h["rec_rule"].astype(bool) & ok
    fc = h[h["fc_rule"]]
    known = h[h["fc_known"].astype(bool)] if "fc_known" in h.columns else h[h["season"] >= FORECAST_FROM]
    seasons = []
    for s in sorted(h["season"].unique()):
        x = h[h["season"] == s]
        seasons.append(dict(season=int(s), forecast=rec(x[x["fc_rule"]]) if s >= FORECAST_FROM else None,
                            recorded=rec(x[x["rec_rule"]]), all_outdoor=rec(x)))
    cum, run = [], 0.0
    for (s, w), d in fc.sort_values(["season", "week"]).groupby(["season", "week"], sort=True):
        run += float(pd.to_numeric(d["units"], errors="coerce").fillna(0).sum())
        cum.append([f"{int(s)}-{int(w):02d}", round(run, 2)])
    return dict(rule=f"outdoor games with a kickoff forecast of {WIND_MPH:g}+ mph wind or {GUST_MPH:g}+ mph gusts: under, "
                     f"when the price leaves at least 1 point of value (like green picks)", chance=chance,
                forecast=rec(fc), forecast_since=FORECAST_FROM,
                forecast_2018_21=rec(fc[fc["season"].between(2018, 2021)]), forecast_2022_on=rec(fc[fc["season"] >= 2022]),
                recorded=rec(h[h["rec_rule"]]), recorded_since=int(h["season"].min()),
                all_outdoor_forecast_era=rec(known), seasons=seasons, cum=cum,
                corr=float(np.corrcoef(known.dropna(subset=["rec_wind", "fc_wind"])["rec_wind"],
                                       known.dropna(subset=["rec_wind", "fc_wind"])["fc_wind"])[0, 1])
                if known[["rec_wind", "fc_wind"]].dropna().shape[0] > 10 else None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--update", action="store_true", help="only add games not in the file yet")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    from .config import load_config
    from .data import DataStore
    cfg = load_config(args.config)
    sched = DataStore(cfg).schedules()
    out = cfg.path("artifacts_dir") / "wind_history.csv"
    h = build_history(sched, out, update=args.update)
    s = summary(h)
    print(json.dumps({k: s[k] for k in ("forecast", "forecast_2018_21", "forecast_2022_on", "recorded", "all_outdoor_forecast_era", "corr")},
                     indent=1, default=float))
    print(f"wrote {out} ({len(h)} outdoor games)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
