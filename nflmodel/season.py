"""Season simulation: playoff, division, bye and Super Bowl chances from the model's ratings.

Each simulated season plays every remaining regular-season game from
    margin = rating_home - rating_away + home field + team shock + game noise
where the ratings are the model's opponent-adjusted net points per game, this week's games use the
priced fair margins, the team shock (one draw per team per season) carries rating uncertainty
through the rest of the year, and the game noise matches the NFL's ~13-point outcome spread.
Seeding follows the 7-team format (4 division winners, then 3 wild cards); ties on record are
broken by point differential, a simplification of the league's tiebreakers. The playoffs are
simulated with reseeding and home field for the higher seed (neutral Super Bowl).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .venues import DIVISIONS, TEAM_DIVISION


def market_ratings(sched: pd.DataFrame, season: int, week: int, current: dict | None = None,
                   half_life: float = 6.0, lam: float = 3.0) -> tuple[dict, float]:
    """Team ratings (points vs average) implied by closing spreads, the same least-squares fit as
    features._add_market_ratings: recent weeks weigh more, last season's games 0.6. `current` adds
    this week's priced margins {game_id: home margin} as the newest observations."""
    from .ratings import time_index
    teams = sorted(TEAM_DIVISION)
    ix = {t: i for i, t in enumerate(teams)}
    k = len(teams)
    s = sched[sched["home_team"].isin(ix) & sched["away_team"].isin(ix)].copy()
    s["t"] = time_index(s["season"], s["week"])
    t_now = float(time_index(season, week))
    hist = s[s["spread_line"].notna() & s["result"].notna() & (s["t"] < t_now) & (s["season"] >= season - 1)]
    rows = [(r.home_team, r.away_team, r.location != "Neutral", float(r.spread_line), float(r.t), int(r.season))
            for r in hist.itertuples(index=False)]
    cur = s[s["game_id"].isin(list((current or {}).keys()))]
    rows += [(r.home_team, r.away_team, r.location != "Neutral", float(current[r.game_id]), t_now, season)
             for r in cur.itertuples(index=False) if np.isfinite(current[r.game_id])]
    if len(rows) < 40:
        return {t: 0.0 for t in teams}, 1.7
    X = np.zeros((len(rows), k + 1)); y = np.zeros(len(rows)); w = np.zeros(len(rows))
    for n, (h, a, home, m, tt, se) in enumerate(rows):
        X[n, ix[h]] += 1; X[n, ix[a]] -= 1; X[n, k] = float(home)
        y[n] = m
        w[n] = 0.5 ** ((t_now - tt) / half_life) * (0.6 if se < season else 1.0)
    pen = lam * np.eye(k + 1); pen[k, k] = 1e-6
    Xw = X * w[:, None]
    b = np.linalg.solve(X.T @ Xw + pen, Xw.T @ y)
    return {t: float(b[ix[t]]) for t in teams}, float(b[k])


def simulate_season(sched: pd.DataFrame, season: int, ratings: dict, fair_margins: dict | None = None,
                    n_sims: int = 10000, game_sd: float = 13.0, rating_sd: float = 2.0, seed: int = 7,
                    hfa: float | None = None) -> dict:
    s = sched[(sched["season"] == season) & (sched["game_type"] == "REG")].copy()
    teams = sorted(TEAM_DIVISION)
    ix = {t: i for i, t in enumerate(teams)}
    T = len(teams)
    done, todo = s[s["result"].notna()], s[s["result"].isna()]
    rec_done = s[s["result"].notna() & s["season"].eq(season)]
    hist = sched[(sched["season"].between(season - 3, season)) & sched["result"].notna()
                 & sched["location"].ne("Neutral")]
    if hfa is None:
        hfa = float(np.clip(hist["result"].mean(), 0.5, 3.0)) if len(hist) else 1.7

    w0, l0, t0, pd0 = (np.zeros(T) for _ in range(4))
    for r in rec_done.itertuples(index=False):
        h, a, m = ix[r.home_team], ix[r.away_team], float(r.result)
        pd0[h] += m
        pd0[a] -= m
        if m > 0:
            w0[h] += 1; l0[a] += 1
        elif m < 0:
            w0[a] += 1; l0[h] += 1
        else:
            t0[h] += 1; t0[a] += 1

    rng = np.random.default_rng(seed)
    rat = np.array([float(ratings.get(t, 0.0)) for t in teams])
    hi = todo["home_team"].map(ix).to_numpy()
    ai = todo["away_team"].map(ix).to_numpy()
    neutral = todo["location"].eq("Neutral").to_numpy()
    fair = fair_margins or {}
    mu = np.array([fair.get(g, np.nan) for g in todo["game_id"]])
    base = rat[hi] - rat[ai] + np.where(neutral, 0.0, hfa)
    mu = np.where(np.isfinite(mu), mu, base)
    shock = rng.normal(0.0, rating_sd, (n_sims, T))
    G = len(todo)
    margin = mu[None, :] + shock[:, hi] - shock[:, ai] + rng.normal(0.0, game_sd, (n_sims, G))
    hw = (margin > 0).astype(float)

    wins = np.tile(w0 + 0.5 * t0, (n_sims, 1))
    pdiff = np.tile(pd0, (n_sims, 1))
    for g in range(G):
        wins[:, hi[g]] += hw[:, g]
        wins[:, ai[g]] += 1 - hw[:, g]
        pdiff[:, hi[g]] += margin[:, g]
        pdiff[:, ai[g]] -= margin[:, g]
    score = wins + 1e-4 * pdiff + 1e-7 * rng.random((n_sims, T))   # record, then point differential

    div_win = np.zeros((n_sims, T), dtype=bool)
    for d, ts in DIVISIONS.items():
        cols = [ix[t] for t in ts]
        best = np.array(cols)[np.argmax(score[:, cols], axis=1)]
        div_win[np.arange(n_sims), best] = True
    seeds = np.zeros((n_sims, T), dtype=int)
    for conf in ("AFC", "NFC"):
        cols = np.array([ix[t] for t in teams if TEAM_DIVISION[t].startswith(conf)])
        sc = score[:, cols]
        dw = div_win[:, cols]
        key_div = np.where(dw, sc + 1000, -np.inf)                   # division winners first
        order_div = np.argsort(-key_div, axis=1)[:, :4]
        key_wc = np.where(dw, -np.inf, sc)
        order_wc = np.argsort(-key_wc, axis=1)[:, :3]
        order = np.concatenate([order_div, order_wc], axis=1)
        for k in range(7):
            seeds[np.arange(n_sims), cols[order[:, k]]] = k + 1

    # playoffs (reseeding; higher seed hosts; neutral Super Bowl)
    conf_champ = np.zeros((n_sims, T), dtype=bool)
    sb_win = np.zeros((n_sims, T), dtype=bool)
    true_rat = rat[None, :] + shock
    for i in range(n_sims):
        champs = []
        for conf in ("AFC", "NFC"):
            seeded = sorted((seeds[i, j], j) for j in range(T) if seeds[i, j] > 0 and TEAM_DIVISION[teams[j]].startswith(conf))
            alive = [j for _, j in seeded]
            seed_of = {j: sd for sd, j in seeded}

            def play(h, a, neutral=False):
                m = true_rat[i, h] - true_rat[i, a] + (0.0 if neutral else hfa) + rng.normal(0.0, game_sd)
                return h if m > 0 else a
            winners = [alive[0]] + [play(alive[1], alive[6]), play(alive[2], alive[5]), play(alive[3], alive[4])]
            winners.sort(key=lambda j: seed_of[j])
            w2 = [play(winners[0], winners[3]), play(winners[1], winners[2])]
            w2.sort(key=lambda j: seed_of[j])
            c = play(w2[0], w2[1])
            conf_champ[i, c] = True
            champs.append(c)
        m = true_rat[i, champs[0]] - true_rat[i, champs[1]] + rng.normal(0.0, game_sd)
        sb_win[i, champs[0] if m > 0 else champs[1]] = True

    rows = []
    for t in teams:
        j = ix[t]
        w = wins[:, j]
        rows.append(dict(team=t, division=TEAM_DIVISION[t], wins_now=int(w0[j]), losses_now=int(l0[j]),
                         ties_now=int(t0[j]), point_diff=float(pd0[j]), rating=float(rat[j]),
                         wins_mean=float(w.mean()), wins_p10=float(np.percentile(w, 10)),
                         wins_p90=float(np.percentile(w, 90)), p_div=float(div_win[:, j].mean()),
                         p_playoffs=float((seeds[:, j] > 0).mean()), p_bye=float((seeds[:, j] == 1).mean()),
                         p_conf=float(conf_champ[:, j].mean()), p_sb=float(sb_win[:, j].mean()),
                         seed_dist=[float((seeds[:, j] == k).mean()) for k in range(1, 8)]))
    return dict(season=season, n_sims=n_sims, games_left=G, hfa=hfa, game_sd=game_sd, rating_sd=rating_sd,
                teams=rows)
