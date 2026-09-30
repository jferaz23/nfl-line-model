"""Preseason win totals: the betting market's season-long projection for every team.

Read ONLY from pages you save by hand into win_totals/ (no automated downloads: the usual source,
Sports Odds History, belongs to Genius Sports and its terms do not clearly allow scraping). Save each
season's NFL win totals page ("Save page as", HTML) as win_totals/<season>.html, e.g. win_totals/2024.html.
A CSV with columns season,team,win_total,over_odds,under_odds also works (win_totals/*.csv).

Each total becomes a preseason rating in points per game vs an average team:
    expected wins = total + (P(over, no margin) - 0.5) * 2.5
    rating        = (expected wins - games / 2) * points_per_win,  points_per_win = 36 / games
(an extra win is worth about 36 points of season point differential). features.py uses it in weeks
1-8 only, fading out as the season's own games take over the ratings.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

import pandas as pd

from .venues import norm_team, team_from_name


def _implied(a) -> float:
    a = float(str(a).replace("+", ""))
    return -a / (-a + 100.0) if a < 0 else 100.0 / (a + 100.0)


def _parse_html(path: Path, season: int) -> list[dict]:
    t = path.read_text(encoding="utf-8", errors="ignore")
    rows = []
    for tb in re.findall(r"<table.*?</table>", t, flags=re.S | re.I):
        for tr in re.findall(r"<tr.*?</tr>", tb, flags=re.S | re.I):
            cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                     for c in re.findall(r"<t[hd].*?</t[hd]>", tr, flags=re.S | re.I)]
            if len(cells) < 4 or cells[0].lower() == "team":
                continue
            team = team_from_name(cells[0]) or norm_team(cells[0])
            try:
                rows.append(dict(season=season, team=team, win_total=float(cells[1]),
                                 over_odds=cells[2], under_odds=cells[3]))
            except ValueError:
                continue
    return rows


def load_win_totals(folder: str | Path = "win_totals") -> tuple[pd.DataFrame, list[str]]:
    d = Path(folder)
    if not d.exists():
        return pd.DataFrame(), []
    rows, notes = [], []
    pages = [] if (d / "win_totals.csv").exists() else sorted(d.glob("*.html")) + sorted(d.glob("*.htm"))
    for f in pages:
        m = re.search(r"(20\d\d)", f.stem)
        if not m:
            notes.append(f"win_totals/{f.name}: name it by season, e.g. 2024.html")
            continue
        got = _parse_html(f, int(m.group(1)))
        rows += got
        notes.append(f"win_totals/{f.name}: {len(got)} teams")
    for f in sorted(d.glob("*.csv")):
        c = pd.read_csv(f)
        rows += c.to_dict("records")
        notes.append(f"win_totals/{f.name}: {len(c)} rows")
    w = pd.DataFrame(rows)
    if w.empty:
        return w, notes
    w["team"] = w["team"].map(lambda x: team_from_name(str(x)) or norm_team(x))
    games = w["season"].map(lambda s: 17 if int(s) >= 2021 else 16)
    p_over = []
    for o, u in zip(w["over_odds"], w["under_odds"]):
        try:
            po, pu = _implied(o), _implied(u)
            p_over.append(po / (po + pu))
        except (TypeError, ValueError):
            p_over.append(0.5)
    w["exp_wins"] = w["win_total"].astype(float) + (pd.Series(p_over, index=w.index) - 0.5) * 2.5
    w["wt_rating"] = (w["exp_wins"] - games / 2.0) * (36.0 / games)
    w = w.drop_duplicates(["season", "team"], keep="last")
    return w[["season", "team", "win_total", "exp_wins", "wt_rating"]], notes


def export_csv(folder: str | Path = "win_totals") -> Path:
    """Turn the saved pages into win_totals/win_totals.csv (numbers only: season, team, total, prices).
    The HTML pages stay on your computer (git ignores them); the CSV is what the automated runs use."""
    d = Path(folder)
    rows = []
    for f in sorted(d.glob("*.htm*")):
        m = re.search(r"(20\d\d)", f.stem)
        if m:
            rows += _parse_html(f, int(m.group(1)))
    out = d / "win_totals.csv"
    old = pd.read_csv(out) if out.exists() else pd.DataFrame()
    new = pd.concat([old, pd.DataFrame(rows)], ignore_index=True).drop_duplicates(["season", "team"], keep="last")
    new.sort_values(["season", "team"]).to_csv(out, index=False)
    return out


if __name__ == "__main__":
    p = export_csv()
    c = pd.read_csv(p)
    print(f"{p}: {len(c)} rows, seasons {sorted(c['season'].unique().tolist())}")
