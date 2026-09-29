"""Line movement: learn how NFL lines move from open to close, and use it to time bets.

How lines are made and move (sources in the README):
  * Market-making books (Pinnacle, Circa, Bookmaker) open the number from power ratings with low
    limits; retail books such as DraftKings follow them with a delay.
  * Sharp money hits the opener first (Sunday night to Tuesday); injury reports, QB decisions and
    weather move lines midweek; recreational money lands on favorites and overs late in the week.
  * The closing line is the most efficient number in the market, so getting a better number than the
    close (closing-line value) is the realistic goal.

This module learns, from history, how far a line moves between open and close given how far the
model disagreed with the opener. Two history sources work:
  1. a spreadsheet of opening and closing lines you download yourself, e.g. Australia Sports
     Betting's free NFL file (personal use; https://www.aussportsbetting.com/data/), saved as
     data_cache/line_history.xlsx (or .csv), and
  2. the Odds API snapshots this pipeline saves on every run (artifacts/odds_snapshots/): after a
     season of Tuesday/Friday/Sunday runs you have DraftKings' own opens and closes.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .venues import ET, norm_team, team_from_name

log = logging.getLogger("nflmodel")
KEYS = (3, 7)


def _num(x):
    return pd.to_numeric(pd.Series(x).astype(str).str.replace("\u2212", "-", regex=False), errors="coerce").values


def _team(x):
    x = str(x or "").strip()
    return team_from_name(x) or norm_team(x) if x else None


# ------------------------------------------------------------------ history loaders
def load_history(path) -> pd.DataFrame:
    """Opening/closing lines from a spreadsheet. Needs date, home and away team, home line open/close
    and total open/close columns (names matched loosely, e.g. 'Home Line Open', 'Total Score Close')."""
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xls"):
        raw = pd.read_excel(path, header=None)
    else:
        raw = pd.read_csv(path, header=None)
    hdr = next((i for i in range(min(10, len(raw)))
                if raw.iloc[i].astype(str).str.contains("home team", case=False).any()), None)
    if hdr is None:
        raise ValueError(f"{path}: no header row with a 'Home Team' column")
    df = raw.iloc[hdr + 1:].copy()
    df.columns = [str(c).strip() for c in raw.iloc[hdr]]
    low = {c.lower(): c for c in df.columns}

    def col(*pats, avoid=("odds", "over", "under", "min", "max")):
        for lc, c in low.items():
            if all(re.search(p, lc) for p in pats) and not any(a in lc for a in avoid):
                return c
        return None

    c_date, c_home, c_away = col(r"^date"), col(r"home team"), col(r"away team")
    c_lo, c_lc = col(r"home line", r"open"), col(r"home line", r"close")
    c_to, c_tc = col(r"total", r"open"), col(r"total", r"close")
    missing = [n for n, c in (("date", c_date), ("home team", c_home), ("away team", c_away),
                              ("home line open", c_lo), ("home line close", c_lc)) if c is None]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    out = pd.DataFrame({
        "gameday": pd.to_datetime(df[c_date], errors="coerce").dt.normalize(),
        "home_team": df[c_home].map(_team), "away_team": df[c_away].map(_team),
        "open_margin": -_num(df[c_lo]), "close_margin": -_num(df[c_lc]),   # home line -> expected home margin
        "open_total": _num(df[c_to]) if c_to else np.nan, "close_total": _num(df[c_tc]) if c_tc else np.nan,
    })
    out["source"] = path.name
    return out.dropna(subset=["gameday", "home_team", "away_team", "open_margin", "close_margin"])


def from_snapshots(snap_dir, book="draftkings") -> pd.DataFrame:
    """First and last saved price per game for one book, from the Odds API snapshots."""
    snap_dir = Path(snap_dir)
    first, last = {}, {}
    for p in sorted(snap_dir.glob("odds_*.json")):
        try:
            events = json.loads(p.read_text())
        except Exception:
            continue
        for ev in events or []:
            start = pd.to_datetime(ev.get("commence_time"), utc=True, errors="coerce")
            for bk in ev.get("bookmakers", []):
                if bk.get("key") != book:
                    continue
                row = {"id": ev.get("id"), "home_team": _team(ev.get("home_team")),
                       "away_team": _team(ev.get("away_team")),
                       "gameday": start.tz_convert(ET).normalize().tz_localize(None) if pd.notna(start) else pd.NaT}
                for mk in bk.get("markets", []):
                    for o in mk.get("outcomes", []):
                        if mk["key"] == "spreads" and _team(o.get("name")) == row["home_team"]:
                            row["margin"] = -float(o.get("point"))
                        if mk["key"] == "totals" and str(o.get("name")).lower() == "over":
                            row["total"] = float(o.get("point"))
                first.setdefault(row["id"], row)
                last[row["id"]] = row
    rows = []
    for k, a in first.items():
        b = last[k]
        rows.append(dict(gameday=a["gameday"], home_team=a["home_team"], away_team=a["away_team"],
                         open_margin=a.get("margin", np.nan), close_margin=b.get("margin", np.nan),
                         open_total=a.get("total", np.nan), close_total=b.get("total", np.nan),
                         source=f"snapshots:{book}"))
    return pd.DataFrame(rows)


def attach(hist: pd.DataFrame, sched: pd.DataFrame) -> pd.DataFrame:
    """Match history rows to schedule games (same teams within two days; home/away swaps allowed)."""
    if hist is None or hist.empty:
        return pd.DataFrame()
    s = sched[["game_id", "season", "week", "gameday", "home_team", "away_team"]].copy()
    s["gd"] = pd.to_datetime(s["gameday"], errors="coerce")
    out = []
    by_pair = {}
    for r in s.itertuples(index=False):
        by_pair.setdefault(frozenset((r.home_team, r.away_team)), []).append(r)
    for h in hist.itertuples(index=False):
        for r in by_pair.get(frozenset((h.home_team, h.away_team)), []):
            if pd.notna(r.gd) and abs((r.gd - h.gameday).days) <= 2:
                flip = -1.0 if r.home_team != h.home_team else 1.0
                out.append(dict(game_id=r.game_id, season=r.season, week=r.week,
                                open_margin=flip * h.open_margin, close_margin=flip * h.close_margin,
                                open_total=h.open_total, close_total=h.close_total, source=h.source))
                break
    return pd.DataFrame(out).drop_duplicates("game_id", keep="last")


# ------------------------------------------------------------------ model
def _design(line, model_value, kind):
    line, mv = np.asarray(line, float), np.asarray(model_value, float)
    gap = np.clip(mv - line, -10, 10)
    cols = [gap, np.sign(gap) * np.minimum(np.abs(gap), 3.0)]          # small disagreements move more per point
    if kind == "margin":
        a = np.abs(line)
        cols += [np.sign(line) * (np.abs(a - 3) <= 0.5), np.sign(line) * (np.abs(a - 7) <= 0.5), np.sign(line)]
    else:
        cols += [line - 44.0]
    return np.column_stack(cols)


class MoveModel:
    """Ridge fit of (close - open) on the model's disagreement with the opener."""

    def __init__(self, coef=None, stats=None):
        self.coef = coef or {}
        self.stats = stats or {}

    def fit(self, df: pd.DataFrame, lam=5.0):
        for kind, o, c, m in (("margin", "open_margin", "close_margin", "model_margin"),
                              ("total", "open_total", "close_total", "model_total")):
            d = df.dropna(subset=[o, c, m])
            if len(d) < 60:
                continue
            X = _design(d[o], d[m], kind)
            y = (d[c] - d[o]).values
            X1 = np.column_stack([np.ones(len(X)), X])
            pen = lam * np.eye(X1.shape[1]); pen[0, 0] = 0
            b = np.linalg.solve(X1.T @ X1 + pen, X1.T @ y)
            pred = X1 @ b
            side = np.sign(d[m].values - d[o].values)
            big = np.abs(pred) >= 0.5
            self.coef[kind] = b.tolist()
            self.stats[kind] = dict(
                games=int(len(d)), mean_abs_move=float(np.mean(np.abs(y))),
                corr_pred_actual=float(np.corrcoef(pred, y)[0, 1]) if np.std(pred) > 0 else 0.0,
                direction_hit=float(np.mean(np.sign(pred[big]) == np.sign(y[big]))) if big.any() else float("nan"),
                clv_model_side_at_open=float(np.mean(side * y)),       # points gained by betting the model's side at open
            )
        return self

    def predict_move(self, kind, line, model_value):
        if kind not in self.coef:
            return None
        X = _design([line], [model_value], kind)
        return float(np.r_[1.0, X[0]] @ np.asarray(self.coef[kind]))

    def save(self, path):
        Path(path).write_text(json.dumps({"coef": self.coef, "stats": self.stats}, indent=1))

    @classmethod
    def load(cls, path):
        p = Path(path)
        if not p.exists():
            return None
        d = json.loads(p.read_text())
        return cls(d.get("coef"), d.get("stats"))


# ------------------------------------------------------------------ timing advice
def timing(market, side, line_now, model_value, mm: MoveModel | None):
    """Advice for one DraftKings bet. market 'spread'|'total'; side 'home'|'away'|'over'|'under';
    line_now = expected home margin (spread) or the total. Returns (label, detail, predicted move)."""
    kind = "margin" if market == "spread" else "total"
    move = mm.predict_move(kind, line_now, model_value) if mm is not None and np.isfinite(model_value) else None
    worse_if_up = side in ("home", "over")          # home margin or total rising makes these bets pricier
    on_key = market == "spread" and round(abs(line_now) * 2) / 2 in KEYS
    if move is not None and abs(move) >= 0.25:
        against = (move > 0) == worse_if_up
        lab = "Bet now" if against else "Can wait"
        det = (f"History says this line moves about {abs(move):.1f} points {'against' if against else 'toward'} "
               f"this side by kickoff.")
    else:
        fav_or_over = (market == "total" and side == "over") or (
            market == "spread" and ((side == "home" and line_now > 0) or (side == "away" and line_now < 0)))
        if fav_or_over:
            lab, det = "Earlier is better", "Late public money usually pushes favorites and overs higher."
        else:
            lab, det = "Can wait", "Underdogs and unders are often best close to kickoff, after public money lands."
    if on_key:
        det += " The line sits on a key number, so a half-point move matters more than usual."
    return lab, det, move


def parse_bet(bet: str, home: str, away: str):
    """Board bet text ('MIA \u22122', 'Over 44.5') -> (side, point) for spread/total rows."""
    t = str(bet).replace("\u2212", "-").strip()
    if t.lower().startswith(("over", "under")):
        return t.split()[0].lower(), float(t.split()[1])
    parts = t.split()
    if len(parts) >= 2:
        team = norm_team(parts[0])
        try:
            pt = 0.0 if parts[1].upper() in ("PK", "PICK") else float(parts[1])
        except ValueError:
            return None, None
        return ("home" if team == home else "away"), pt
    return None, None
