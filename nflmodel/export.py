"""Weekly run -> JSON payload for the website, plus the model-pick log that grades it.

site_data/week_<season>_<week>.json holds everything the site shows for a week: projections, the
DraftKings board with probabilities for both sides of every market, every book's line, per-factor
contributions, injuries, weather and power ratings. The latest run of a week overwrites it.

artifacts/tracker/model_picks.csv appends one row per pick per run. The site grades the last
run before each kickoff (see build_site.py), so the record reflects what the page showed.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .pricing import game_dists

GAME_COLS = ["game_id", "season", "week", "game_type", "home_team", "away_team", "kickoff_utc", "gameday",
             "gametime", "location", "roof", "surface", "stadium", "temp_used", "wind_used", "indoor", "precip",
             "h_qb_name_used", "a_qb_name_used", "h_qb_source", "a_qb_source", "home_rest", "away_rest",
             "away_travel_kmi", "h_miss_names", "a_miss_names", "h_off_cont", "h_def_cont", "a_off_cont",
             "a_def_cont", "spread_line", "total_line", "div_game", "model_margin", "model_total",
             "home_coach", "away_coach", "referee", "h_qb_new", "a_qb_new", "h_qb_delta", "a_qb_delta",
             "gust_used", "wx_source"]


def _clean(o):
    """JSON-safe: NaN/inf -> None, numpy -> python, timestamps -> ISO."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if not math.isfinite(f) else round(f, 4)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.isoformat()
    if o is pd.NaT or (not isinstance(o, str) and pd.api.types.is_scalar(o) and pd.isna(o)):
        return None
    return o


def _records(df: pd.DataFrame | None, cols=None) -> list[dict]:
    if df is None or len(df) == 0:
        return []
    d = df if cols is None else df[[c for c in cols if c in df.columns]]
    return _clean(d.to_dict("records"))


TIERS = {3: "Best bet", 2: "Value", 1: "Lean"}


def _side(bet: str, home: str, away: str):
    bet = str(bet)
    if bet.startswith("Over "):
        return "over"
    if bet.startswith("Under "):
        return "under"
    return "home" if bet.startswith(home + " ") else "away"


def add_tiers(board: pd.DataFrame, target: pd.DataFrame, min_ev: float) -> pd.DataFrame:
    """Confidence tier for every DraftKings offer:
      3 Best bet  expected value >= min_ev at DraftKings AND the model's own number agrees with the side
      2 Value     expected value >= min_ev / 2 (1% by default), or >= min_ev with the model alone disagreeing
      1 Lean      everything else: the likelier side at a price near or worse than fair; not a bet
    model_edge = points by which the model alone favors the side (for moneylines, its projected margin)."""
    if board is None or board.empty:
        return board
    tg = target.set_index("game_id")
    edges, tiers = [], []
    for b in board.to_dict("records"):
        g = tg.loc[b["game_id"]]
        side = _side(b["bet"], g["home_team"], g["away_team"])
        e = np.nan
        if b["market"] == "spread":
            hc = float(str(b["bet"]).split(" ")[-1].replace("−", "-").replace("pk", "0"))
            margin = g["model_margin"] if side == "home" else -g["model_margin"]
            e = margin + hc
        elif b["market"] == "total":
            line = float(str(b["bet"]).split(" ")[-1])
            e = (g["model_total"] - line) * (1 if side == "over" else -1)
        elif b["market"] == "moneyline":
            e = g["model_margin"] if side == "home" else -g["model_margin"]
        ev = b.get("ev", np.nan)
        agree = (not np.isfinite(e)) or e > 0
        tier = 3 if (ev >= min_ev and agree and not b.get("check_news")) else (2 if ev >= min_ev / 2 else 1)
        edges.append(e)
        tiers.append(tier)
    out = board.copy()
    out["model_edge"], out["tier"] = edges, tiers
    out["tier_label"] = out["tier"].map(TIERS)
    return out


def week_payload(season, week, target, summary, board, odds, exp_m, exp_t, info, cfg, weights, notes,
                 dm, dt, demo=False, generated=None) -> dict:
    sm = summary.set_index("game_id")
    games = []
    for g in _records(target.sort_values("kickoff_utc"), GAME_COLS):
        gid = g["game_id"]
        s = sm.loc[gid].to_dict() if gid in sm.index else {}
        fm, ft = s.get("fair_margin", g["model_margin"]), s.get("fair_total", g["model_total"])
        dmg, dtg = game_dists(dm, dt, cfg, ft if ft is not None and np.isfinite(ft) else np.nan)
        win_h = dmg.outcome(fm, +1, 0.0) if fm is not None and np.isfinite(fm) else (np.nan, 0.0, np.nan)
        win_m = dmg.outcome(g["model_margin"], +1, 0.0)
        mkt = s.get("market_margin")
        win_v = dmg.outcome(mkt, +1, 0.0) if mkt is not None and np.isfinite(mkt) else (np.nan, 0.0, np.nan)
        g.update(_clean({k: v for k, v in s.items() if k != "game_id"}))
        g["p_home_win"] = _clean(win_h[0] / max(win_h[0] + win_h[2], 1e-9)) if np.isfinite(win_h[0]) else None
        g["p_home_win_model"] = _clean(win_m[0] / max(win_m[0] + win_m[2], 1e-9))
        g["p_home_win_market"] = _clean(win_v[0] / max(win_v[0] + win_v[2], 1e-9)) if np.isfinite(win_v[0]) else None
        # 6-point teaser legs at DraftKings' numbers (probabilities from the same key-number distributions)
        hs, tl = s.get("dk_home_spread"), s.get("dk_total")
        tease = {}
        if hs is not None and np.isfinite(hs) and fm is not None and np.isfinite(fm):
            for side, sign, hc in (("home", +1, hs + 6), ("away", -1, -hs + 6)):
                w_, p_, l_ = dmg.outcome(fm, sign, hc)
                tease[side] = dict(line=hc, p=w_ / max(w_ + l_, 1e-9))
        if tl is not None and np.isfinite(tl) and ft is not None and np.isfinite(ft):
            for side, sign, hc in (("over", +1, -(tl - 6)), ("under", -1, tl + 6)):
                w_, p_, l_ = dtg.outcome(ft, sign, hc)
                tease[side] = dict(line=tl - 6 if side == "over" else tl + 6, p=w_ / max(w_ + l_, 1e-9))
        g["tease"] = _clean(tease)
        g["contrib_margin"] = _clean(exp_m.loc[gid].to_dict()) if gid in exp_m.index else {}
        g["contrib_total"] = _clean(exp_t.loc[gid].to_dict()) if gid in exp_t.index else {}
        games.append(g)
    books = []
    if odds is not None and len(odds):
        books = _records(odds, ["game_id", "book", "home_spread", "home_spread_price", "away_spread",
                                "away_spread_price", "total", "over_price", "under_price", "home_ml", "away_ml"])
    power = info.get("power")
    return _clean(dict(
        season=season, week=week, demo=demo, target_book=cfg.target_book,
        generated=(generated or datetime.now(timezone.utc)).isoformat(),
        weights=dict(spread=weights[0], total=weights[1]), min_ev=cfg.min_ev, bankroll=cfg.bankroll,
        notes=list(dict.fromkeys(n for n in notes if n)), games=games,
        board=_records(add_tiers(board, target, cfg.min_ev)), books=books,
        power=_records(power) if power is not None else [],
        qbs=_records(info.get("qbs")),
    ))


def picks_from_payload(p: dict) -> list[dict]:
    """The page's picks: for each game, the likelier side of the DraftKings spread, total and
    moneyline, flagged `bet` when it clears the edge threshold."""
    out = []
    by_game: dict[str, list[dict]] = {}
    for b in p.get("board", []):
        by_game.setdefault(b["game_id"], []).append(b)
    for gid, offers in by_game.items():
        for market in ("spread", "total", "moneyline"):
            opts = [o for o in offers if o["market"] == market and o.get("p_win") is not None]
            if len(opts) < 2:
                continue
            best = max(opts, key=lambda o: (o["p_win"] / max(o["p_win"] + o["p_lose"], 1e-9)))
            out.append(dict(game_id=gid, market=market, bet=best["bet"], price=best["price"],
                            p_win=best["p_win"], p_push=best["p_push"], ev=best["ev"],
                            is_play=bool(best.get("is_play")), stake=best.get("stake", 0.0),
                            tier=best.get("tier"), model_edge=best.get("model_edge")))
        for o in offers:   # a flagged bet on the less likely side (e.g. a plus-money underdog) is still logged
            if o.get("is_play") and not any(x["bet"] == o["bet"] for x in out if x["game_id"] == gid):
                out.append(dict(game_id=gid, market=o["market"], bet=o["bet"], price=o["price"], p_win=o["p_win"],
                                p_push=o["p_push"], ev=o["ev"], is_play=True, stake=o.get("stake", 0.0),
                                tier=o.get("tier"), model_edge=o.get("model_edge")))
    return out


def append_pick_log(p: dict, path: Path):
    rows = picks_from_payload(p)
    if not rows:
        return 0
    df = pd.DataFrame(rows)
    df.insert(0, "run_at", p["generated"])
    df.insert(1, "season", p["season"])
    df.insert(2, "week", p["week"])
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = pd.read_csv(path, on_bad_lines="skip")
        if list(old.columns) != list(df.columns):          # columns added since the log started: rewrite once
            pd.concat([old, df], ignore_index=True).to_csv(path, index=False)
            return len(df)
    df.to_csv(path, mode="a", header=not path.exists(), index=False)
    return len(df)


def write_payload(p: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    f = out_dir / f"week_{p['season']}_{int(p['week']):02d}.json"
    f.write_text(json.dumps(p, separators=(",", ":")), encoding="utf-8")
    return f


SCHED_COLS = ["game_id", "season", "week", "game_type", "gameday", "gametime", "home_team", "away_team",
              "home_score", "away_score", "result", "total", "spread_line", "total_line", "location",
              "home_qb_name", "away_qb_name", "home_coach", "away_coach", "stadium", "roof", "surface"]


def schedule_payload(sched: pd.DataFrame, season: int, target: pd.DataFrame, meetings: int = 8) -> dict:
    """This season's games (results, closing lines) and each target game's recent meetings."""
    cur = sched[sched["season"] == season].sort_values(["week", "gameday", "gametime"])
    h2h = {}
    done = sched[sched["result"].notna()].sort_values(["season", "week"])
    for r in target.itertuples(index=False):
        pair = {r.home_team, r.away_team}
        m = done[done["home_team"].isin(pair) & done["away_team"].isin(pair)
                 & (done["home_team"] != done["away_team"])].tail(meetings)
        h2h[r.game_id] = _records(m.iloc[::-1], SCHED_COLS)
    return _clean(dict(season=season, games=_records(cur, SCHED_COLS), h2h=h2h))


def append_log(path: Path, rows: pd.DataFrame) -> int:
    """Append rows to a CSV log; when the columns differ from the file's, rewrite it once with the union
    (appending mismatched rows would corrupt the file)."""
    if rows is None or not len(rows):
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = pd.read_csv(path, on_bad_lines="skip")
        if list(rows.columns) != list(old.columns):
            cols = list(old.columns) + [c for c in rows.columns if c not in old.columns]
            pd.concat([old, rows], ignore_index=True).reindex(columns=cols).to_csv(path, index=False)
            return len(rows)
    rows.to_csv(path, mode="a", header=not path.exists(), index=False)
    return len(rows)
