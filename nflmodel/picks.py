"""The page's picks, one rule for the live week and for the 2015-to-now track record.

Spread / total pick
    the model's side of the line: its own number vs the posted spread or total.
Chance
    how often picks with that much disagreement actually won against the closing line (pushes
    excluded), by disagreement band (0-2, 2-4, 4+ points), shrunk toward 50% with a prior of SHRINK games
    and never falling as disagreement grows (adjacent bands pooled), so thin bands cannot overstate. For the track record, each season's bands use only
    earlier seasons (2015, with nothing earlier, is all 50%: no green picks).
Value ("bang for your buck")
    chance minus the break-even rate of the actual price (-110 needs 52.4%, -120 needs 54.5%).
    Picks with value >= HIGHLIGHT are highlighted green and ranked by value.
    A pick only turns green when its band's own hit rate is at least MIN_SKILL, so a plus-money
    price alone never makes a coin flip green.
Top pick
    any spread pick where the model disagrees with the line by TOP_EDGE+ points (always shown green).
    Until Oct 2, 2026 a Top pick also had to pass the green test, which made the record jumpy: tiny model
    changes pushed whole seasons' 4+ band below the green cutoff. Without it the 4+ picks went
    241-176 (57.8%) at closing prices 2015-2026, 57.3% in 2015-20 and 58.3% in 2021-26, and stayed
    55.8-57.0% when the model was perturbed (vs 50.8-56.6% for the old rule). Tracked separately.
Winner pick
    the side the model alone makes more likely to win straight up (shown, not highlighted).
Only needs numpy/pandas, so build_site.py can import it.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

HIGHLIGHT = 0.01          # chance at least 1 point above the price's break-even...
MIN_SKILL = 0.51          # ...and the model's side itself has won at least 51% in that band (not price alone)
TOP_EDGE = 4.0            # Top picks: spread picks where the model disagrees by 4+ points
QB_DOWN = -2.0            # QB caution: the picked team's projected QB is new (<100 plays) or 2+ pts/game worse
                          # than its usual starter. Such 2+ pt spread picks went 49.6% (2015-20) and 50.0%
                          # (2021-26) vs 54-55% with no QB change, so they are not green below the Top line.
BANDS = (0.0, 2.0, 4.0, 99.0)
SHRINK = 200.0            # prior games at 50% in each band


GAME_ID = r"^\d{4}_\d{2}_[A-Z]+_[A-Z]+$"
_SHIFT_SRC = ["game_id", "season", "week", "home_team", "away_team", "kickoff_utc", "highlight", "top", "qb_caution"]
_SHIFT_DST = ["qb_caution", "game_id", "season", "week", "home_team", "away_team", "kickoff_utc", "highlight", "top"]


def read_log(path) -> pd.DataFrame:
    """The live pick log (artifacts/tracker/picks_log.csv), typed. Rows written by the old logger before
    Sept 30, 2026 had qb_caution one column early, which shifts everything from game_id on by one; they
    are put back here (288 rows from the Sept 30 04:21-14:37 UTC runs)."""
    lg = pd.read_csv(path, on_bad_lines="skip", dtype=str, keep_default_na=True)
    if {"game_id", "season"} <= set(lg.columns) and all(c in lg.columns for c in _SHIFT_SRC):
        sh = (~lg["game_id"].astype(str).str.match(GAME_ID) & lg["season"].astype(str).str.match(GAME_ID)).to_numpy()
        if sh.any():
            lg.loc[sh, _SHIFT_DST] = lg.loc[sh, _SHIFT_SRC].to_numpy()
    for c in ("line", "price", "edge", "chance", "breakeven", "value", "season", "week", "wind", "gust"):
        if c in lg.columns:
            lg[c] = pd.to_numeric(lg[c], errors="coerce")
    for c in ("highlight", "top", "qb_caution", "active"):
        if c in lg.columns:
            lg[c] = lg[c].map(lambda v: {"true": True, "false": False}.get(str(v).strip().lower(), np.nan))
            if c in ("highlight", "top"):
                lg[c] = lg[c].fillna(False).astype(bool)     # a blank flag means no (bool(NaN) would be True)
    return lg


def breakeven(price) -> float:
    try:
        a = float(price)
    except (TypeError, ValueError):
        return float("nan")
    if not math.isfinite(a) or abs(a) < 100:
        return float("nan")
    return -a / (-a + 100.0) if a < 0 else 100.0 / (a + 100.0)


def profit(result: str | None, price) -> float | None:
    if result is None:
        return None
    if result == "P":
        return 0.0
    if result == "L":
        return -1.0
    a = float(price)
    return a / 100.0 if a > 0 else 100.0 / -a


def fit_curve(edge, hit) -> list[list[float]]:
    """[[lo, hi, chance, n], ...] per disagreement band, shrunk toward 50%."""
    edge, hit = np.asarray(edge, float), np.asarray(hit, float)
    blocks = []
    for lo, hi in zip(BANDS[:-1], BANDS[1:]):
        m = (edge >= lo) & (edge < hi)
        blocks.append([[(lo, hi)], float(hit[m].sum()) + 0.5 * SHRINK, float(m.sum()) + SHRINK, float(m.sum())])
    # pool adjacent violators: a bigger disagreement is never rated less likely to win
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][1] / blocks[i][2] > blocks[i + 1][1] / blocks[i + 1][2]:
            a, b = blocks[i], blocks.pop(i + 1)
            blocks[i] = [a[0] + b[0], a[1] + b[1], a[2] + b[2], a[3] + b[3]]
            i = max(i - 1, 0)
        else:
            i += 1
    out = []
    for spans, w, n, raw in blocks:
        for lo, hi in spans:
            out.append([lo, hi, w / n, raw])
    return out


def chance(curve, edge: float) -> float:
    e = abs(edge)
    for lo, hi, c, _ in curve:
        if lo <= e < hi:
            return float(c)
    return 0.5


def _lab(team: str, h: float) -> str:
    return f"{team} pk" if abs(h) < 1e-9 else f"{team} {h:+g}".replace("-", "−")


def spread_pick(home, away, model_margin, line_margin, home_price, away_price, b):
    """line_margin = the posted spread as the expected home margin (home -3 -> +3)."""
    if not all(np.isfinite([model_margin, line_margin])):
        return None
    e = model_margin - line_margin
    if abs(e) < 1e-9:
        return None
    home_side = e > 0
    h = -line_margin if home_side else line_margin
    price = home_price if home_side else away_price
    c, be = chance(b, e), breakeven(price)
    return dict(market="spread", side="home" if home_side else "away", team=home if home_side else away,
                bet=_lab(home if home_side else away, h), line=h, price=price, edge=abs(e), chance=c,
                breakeven=be, value=c - be if np.isfinite(be) else float("nan"))


def total_pick(model_total, line, over_price, under_price, b):
    if not all(np.isfinite([model_total, line])):
        return None
    e = model_total - line
    if abs(e) < 1e-9:
        return None
    over = e > 0
    price = over_price if over else under_price
    c, be = chance(b, e), breakeven(price)
    return dict(market="total", side="over" if over else "under", team=None,
                bet=f"{'Over' if over else 'Under'} {line:g}", line=line, price=price, edge=abs(e), chance=c,
                breakeven=be, value=c - be if np.isfinite(be) else float("nan"))


def winner_pick(home, away, p_home, home_ml, away_ml):
    if p_home is None or not np.isfinite(p_home):
        return None
    home_side = p_home >= 0.5
    price = home_ml if home_side else away_ml
    c, be = (p_home if home_side else 1 - p_home), breakeven(price)
    return dict(market="winner", side="home" if home_side else "away", team=home if home_side else away,
                bet=f"{home if home_side else away} to win", line=0.0, price=price, edge=float("nan"), chance=c,
                breakeven=be, value=c - be if np.isfinite(be) else float("nan"))


def qb_caution(side: str, h_new, a_new, h_delta, a_delta) -> bool:
    new, delta = (h_new, h_delta) if side == "home" else (a_new, a_delta)
    try:
        return bool((new is not None and float(new) >= 1) or (delta is not None and float(delta) < QB_DOWN))
    except (TypeError, ValueError):
        return False


def is_green(p: dict) -> bool:
    return bool(p["market"] != "winner" and np.isfinite(p["value"]) and p["value"] >= HIGHLIGHT
                and p["chance"] >= MIN_SKILL and not (p.get("qb_caution") and p["edge"] < TOP_EDGE))


def is_top(p: dict) -> bool:
    e = p.get("edge")
    return bool(p["market"] == "spread" and e is not None and np.isfinite(e) and e >= TOP_EDGE)


def is_highlight(p: dict) -> bool:
    """Shown green: passes the value test, or is a Top pick."""
    return bool(is_green(p) or is_top(p))


def grade(market, side, line, home_score, away_score):
    if home_score is None or away_score is None or not np.isfinite([home_score, away_score]).all():
        return None
    if market == "total":
        d = (home_score + away_score - line) * (1 if side == "over" else -1)
    else:
        m = home_score - away_score if side == "home" else away_score - home_score
        d = m + (line if market == "spread" else 0.0)
    return "W" if d > 1e-9 else ("L" if d < -1e-9 else "P")


def curves_from_oos(oos: pd.DataFrame, before_season: int | None = None) -> dict:
    """Slopes for spreads and totals from backtest rows (seasons < before_season when given)."""
    o = oos if before_season is None else oos[oos["season"] < before_season]
    out = {}
    for mk, pred, line, act in (("spread", "model_margin", "spread_line", "result"),
                                ("total", "model_total", "total_line", "total")):
        d = o.dropna(subset=[pred, line, act])
        e = d[pred] - d[line]
        r = (d[act] - d[line]) * np.sign(e)
        m = ((r != 0) & (e != 0)).to_numpy()
        # rate spread picks from comparable history: leave out QB-caution games (coin flips that would drag
        # the chance of clean picks down). Backtest: green 55.0%, +51.3u vs 55.2%, +43.6u; both halves up.
        if mk == "spread" and len(d) and "h_qb_delta" in d.columns:
            side = np.where(e > 0, "home", "away")
            caut = np.array([qb_caution(s, a, b, c, q) for s, a, b, c, q in
                             zip(side, d["h_qb_new"], d["a_qb_new"], d["h_qb_delta"], d["a_qb_delta"])], dtype=bool)
            m = m & ~caut
        out[mk] = fit_curve(e.abs().to_numpy()[m], (r > 0).to_numpy(float)[m])
    return out


def week_picks(games: list[dict], curves: dict) -> list[dict]:
    """Picks for a weekly payload's games at DraftKings' current prices."""
    out = []
    for g in games:
        base = dict(game_id=g["game_id"], season=g["season"], week=g["week"], home_team=g["home_team"],
                    away_team=g["away_team"], kickoff_utc=g.get("kickoff_utc"))
        hs = g.get("dk_home_spread")
        f = lambda k: float(g[k]) if g.get(k) is not None else float("nan")
        sp = spread_pick(g["home_team"], g["away_team"], f("model_margin"), -float(hs) if hs is not None else float("nan"),
                         f("dk_home_spread_price"), f("dk_away_spread_price"), curves["spread"])
        tt = total_pick(f("model_total"), f("dk_total"), f("dk_over_price"), f("dk_under_price"), curves["total"])
        wn = winner_pick(g["home_team"], g["away_team"], g.get("p_home_win_model"), f("dk_home_ml"), f("dk_away_ml"))
        if sp:
            sp["qb_caution"] = qb_caution(sp["side"], g.get("h_qb_new"), g.get("a_qb_new"), g.get("h_qb_delta"), g.get("a_qb_delta"))
        for p in (sp, tt, wn):
            if p:
                p.update(base)
                p["highlight"], p["top"] = is_highlight(p), is_top(p)
                out.append(p)
    return out


def history(oos: pd.DataFrame) -> dict:
    return rows_summary(history_rows(oos))


def history_rows(oos: pd.DataFrame) -> pd.DataFrame:
    """Every backtest game's picks graded at the closing line and price; curves fit walk-forward."""
    o = oos.dropna(subset=["result", "spread_line", "total_line"]).copy()
    rows = []
    for s in sorted(o["season"].unique()):
        cv = curves_from_oos(o, before_season=int(s))
        for r in o[o["season"] == s].itertuples(index=False):
            ln = float(r.spread_line)
            hsc = (float(r.result) + float(r.total)) / 2.0          # scores from margin and total
            asc = (float(r.total) - float(r.result)) / 2.0
            picks = [spread_pick(r.home_team, r.away_team, float(r.model_margin), ln,
                                 getattr(r, "home_spread_odds", -110.0), getattr(r, "away_spread_odds", -110.0), cv["spread"]),
                     total_pick(float(r.model_total), float(r.total_line), getattr(r, "over_odds", -110.0),
                                getattr(r, "under_odds", -110.0), cv["total"])]
            ph = 1.0 / (1.0 + math.exp(-float(r.model_margin) / 7.0))       # only its side is used
            picks.append(winner_pick(r.home_team, r.away_team, ph, getattr(r, "home_moneyline", np.nan),
                                     getattr(r, "away_moneyline", np.nan)))
            if picks[0]:
                picks[0]["qb_caution"] = qb_caution(picks[0]["side"], getattr(r, "h_qb_new", None), getattr(r, "a_qb_new", None),
                                                    getattr(r, "h_qb_delta", None), getattr(r, "a_qb_delta", None))
            for p in picks:
                if not p:
                    continue
                price = p["price"] if p["price"] is not None and np.isfinite(p["price"]) else -110.0
                res = grade(p["market"], p["side"], p["line"], hsc, asc)
                rows.append(dict(season=int(s), week=int(r.week), game_id=r.game_id, market=p["market"], bet=p["bet"],
                                 edge=p["edge"], chance=p["chance"], price=price, value=p["value"],
                                 highlight=is_highlight(p), top=is_top(p),
                                 result=res, units=profit(res, price) if p["market"] != "winner" or np.isfinite(p["price"]) else None,
                                 source="backtest"))
    return pd.DataFrame(rows)


def _rec(d: pd.DataFrame) -> dict:
    g = d[d["result"].notna()]
    w, l, p = int((g["result"] == "W").sum()), int((g["result"] == "L").sum()), int((g["result"] == "P").sum())
    u = g["units"].dropna()
    return dict(w=w, l=l, p=p, n=w + l + p, pct=(w / (w + l)) if w + l else None,
                units=float(u.sum()) if len(u) else None, roi=float(u.sum() / len(u)) if len(u) else None)


def rows_summary(df: pd.DataFrame) -> dict:
    if df.empty:
        return dict(seasons=[], total={}, cum=[])
    groups = (("spread", df["market"] == "spread"), ("total", df["market"] == "total"),
              ("winner", df["market"] == "winner"), ("green", df["highlight"]),
              ("green_spread", df["highlight"] & (df["market"] == "spread")),
              ("green_total", df["highlight"] & (df["market"] == "total")),
              ("top", df["top"].fillna(False).astype(bool) if "top" in df.columns else df["highlight"] & False))
    seasons = []
    for s, d in df.groupby("season"):
        seasons.append(dict(season=int(s), **{k: _rec(d[m.loc[d.index]]) for k, m in groups}))
    total = {k: _rec(df[m]) for k, m in groups}
    def cumulative(mask):
        g = df[mask & df["result"].notna()].sort_values(["season", "week"])
        out, run = [], 0.0
        for (s, w), d in g.groupby(["season", "week"], sort=True):
            run += float(d["units"].fillna(0).sum())
            out.append([f"{int(s)}-{int(w):02d}", round(run, 2)])
        return out
    cum = cumulative(df["highlight"])
    top_mask = df["top"].fillna(False).astype(bool) if "top" in df.columns else df["highlight"] & False
    cum_top = cumulative(top_mask)
    # by chance band: does a stated chance hold up?
    bands = []
    ats = df[df["market"].isin(["spread", "total"]) & df["result"].isin(["W", "L"])]
    for lo, hi in ((0.50, 0.52), (0.52, 0.54), (0.54, 0.56), (0.56, 0.60), (0.60, 1.0)):
        m = (ats["chance"] >= lo) & (ats["chance"] < hi)
        if m.sum():
            bands.append(dict(lo=lo, hi=hi, n=int(m.sum()), said=float(ats.loc[m, "chance"].mean()),
                              won=float((ats.loc[m, "result"] == "W").mean())))
    return dict(seasons=seasons, total=total, cum=cum, cum_top=cum_top, bands=bands)


# ----------------------------------------------------------------------------- teasers
# 6-point teaser legs on underdogs of +1.5 to +2.5 (teased through 3 and 7 to +7.5 to +8.5). In the
# 2015-2026 backtest these legs won 77.8% (2015-20) and 77.2% (2021-26); a 2-team teaser at -120 needs
# 73.9% per leg. Favorite legs (-7.5 to -8.5) fell to 68% in 2021-26 and are left out.
TEASE_POINTS = 6.0
TEASE_DOG_RANGE = (1.5, 2.5)
TEASER_PRICE = -120.0      # DraftKings' usual 2-team 6-point NFL teaser price; editable on the site
TEASE_PRIOR = 0.74         # leg rate the chance is shrunk toward (about break-even at -120)


def teaser_leg_rate(oos: pd.DataFrame, before_season: int | None = None) -> tuple[float, int]:
    """Historical win rate of qualifying underdog legs (pushes excluded), shrunk toward TEASE_PRIOR."""
    o = oos if before_season is None else oos[oos["season"] < before_season]
    o = o.dropna(subset=["spread_line", "result"])
    w = n = 0
    for sl, res in zip(o["spread_line"], o["result"]):
        for h, m in ((-sl, res), (sl, -res)):            # (handicap, margin) for home then away
            if TEASE_DOG_RANGE[0] <= h <= TEASE_DOG_RANGE[1]:
                d = m + h + TEASE_POINTS
                if d != 0:
                    n += 1
                    w += d > 0
    k = 200.0
    return (w + TEASE_PRIOR * k) / (n + k), n


def teaser_legs(games: list[dict], rate: float) -> list[dict]:
    """Qualifying legs this week at DraftKings' current spreads."""
    out = []
    for g in games:
        hs = g.get("dk_home_spread")
        if hs is None:
            continue
        for team, h in ((g["home_team"], float(hs)), (g["away_team"], -float(hs))):
            if TEASE_DOG_RANGE[0] <= h <= TEASE_DOG_RANGE[1]:
                out.append(dict(game_id=g["game_id"], season=g["season"], week=g["week"], team=team,
                                side="home" if team == g["home_team"] else "away", line=h,
                                teased=h + TEASE_POINTS, bet=_lab(team, h + TEASE_POINTS), chance=rate,
                                kickoff_utc=g.get("kickoff_utc"), home_team=g["home_team"], away_team=g["away_team"]))
    return sorted(out, key=lambda x: (x.get("kickoff_utc") or "", x["game_id"]))


def pair_teasers(legs: list[dict]) -> list[list[dict]]:
    """2-team teasers from the week's legs in kickoff order (legs from the same game are never paired)."""
    pairs, pool = [], list(legs)
    while len(pool) >= 2:
        a = pool.pop(0)
        j = next((i for i, b in enumerate(pool) if b["game_id"] != a["game_id"]), None)
        if j is None:
            break
        pairs.append([a, pool.pop(j)])
    return pairs


def teaser_history(oos: pd.DataFrame) -> dict:
    """Leg and 2-team records since the first season, pairs formed in schedule order each week."""
    o = oos.dropna(subset=["spread_line", "result"]).sort_values(["season", "week", "game_id"])
    legs = []
    for r in o.itertuples(index=False):
        for side, h, m in (("home", -r.spread_line, r.result), ("away", r.spread_line, -r.result)):
            if TEASE_DOG_RANGE[0] <= h <= TEASE_DOG_RANGE[1]:
                d = m + h + TEASE_POINTS
                legs.append(dict(season=int(r.season), week=int(r.week), game_id=r.game_id,
                                 res="W" if d > 0 else ("L" if d < 0 else "P")))
    L = pd.DataFrame(legs)
    if L.empty:
        return {}
    seasons = []
    win = 100.0 / -TEASER_PRICE if TEASER_PRICE < 0 else TEASER_PRICE / 100.0
    all_pairs = []
    for (s, w), g in L.groupby(["season", "week"], sort=True):
        rows = g[g["res"] != "P"].to_dict("records")
        for a, b in pair_teasers(rows):
            r = "W" if a["res"] == "W" and b["res"] == "W" else "L"
            all_pairs.append(dict(season=s, week=w, res=r, units=win if r == "W" else -1.0))
    P = pd.DataFrame(all_pairs)
    for s in sorted(L["season"].unique()):
        l = L[(L["season"] == s) & (L["res"] != "P")]
        p = P[P["season"] == s] if len(P) else P
        seasons.append(dict(season=int(s), legs_w=int((l.res == "W").sum()), legs_l=int((l.res == "L").sum()),
                            w=int((p.res == "W").sum()) if len(p) else 0, l=int((p.res == "L").sum()) if len(p) else 0,
                            units=float(p.units.sum()) if len(p) else 0.0))
    lg = L[L["res"] != "P"]
    cum, run = [], 0.0
    for (s, w), g in (P.groupby(["season", "week"], sort=True) if len(P) else []):
        run += float(g.units.sum())
        cum.append([f"{int(s)}-{int(w):02d}", round(run, 2)])
    return dict(price=TEASER_PRICE, points=TEASE_POINTS, dog_range=list(TEASE_DOG_RANGE),
                legs=dict(w=int((lg.res == "W").sum()), l=int((lg.res == "L").sum()), pct=float((lg.res == "W").mean())),
                teasers=dict(w=int((P.res == "W").sum()), l=int((P.res == "L").sum()),
                             pct=float((P.res == "W").mean()), units=float(P.units.sum()), n=int(len(P))),
                need_leg=float((1.0 / (1.0 + win)) ** 0.5), seasons=seasons, cum=cum)


# ----------------------------------------------------------------------------- rule explorer
def explorer(oos: pd.DataFrame, split: int = 2020) -> list[dict]:
    """Spread and total picks by minimum model disagreement: seasons <= split (where rules were chosen)
    vs later seasons (the check), at closing prices."""
    o = oos.dropna(subset=["model_margin", "spread_line", "result", "model_total", "total_line"])
    rows = []
    for r in o.itertuples(index=False):
        hs, as_ = (r.result + r.total) / 2.0, (r.total - r.result) / 2.0
        e = r.model_margin - r.spread_line
        if e:
            home = e > 0
            line = -r.spread_line if home else r.spread_line
            price = r.home_spread_odds if home else r.away_spread_odds
            res = grade("spread", "home" if home else "away", line, hs, as_)
            rows.append(("spread", r.season, r.week, abs(e), res, profit(res, price)))
        et = r.model_total - r.total_line
        if et:
            over = et > 0
            price = r.over_odds if over else r.under_odds
            res = grade("total", "over" if over else "under", r.total_line, hs, as_)
            rows.append(("total", r.season, r.week, abs(et), res, profit(res, price)))
    d = pd.DataFrame(rows, columns=["market", "season", "week", "edge", "res", "units"])
    n_weeks = {k: d[m].groupby(["season", "week"]).ngroups for k, m in (("a", d.season <= split), ("b", d.season > split))}
    out = []
    for mk in ("spread", "total"):
        for k in (0, 1, 2, 2.5, 3, 3.5, 4, 5):
            row = dict(market=mk, min_edge=k)
            for tag, m in (("a", d.season <= split), ("b", d.season > split)):
                x = d[m & (d.market == mk) & (d.edge >= k)]
                g = x[x.res.isin(["W", "L"])]
                w, l = int((g.res == "W").sum()), int((g.res == "L").sum())
                row[tag] = dict(w=w, l=l, pct=w / max(w + l, 1), units=float(x.units.sum()),
                                per_week=len(x) / max(n_weeks[tag], 1))
            out.append(row)
    return out
