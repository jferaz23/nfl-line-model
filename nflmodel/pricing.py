"""Turn projected means into prices, and compare them with DraftKings.

NFL margins pile up on key numbers (3, 7, 6, 10, 4, 14 ...), so a plain normal
distribution misprices spreads near 3 and 7. We learn a key-number factor
K(m) = observed / expected frequency from history (closing lines as the mean)
and use pmf(m) proportional to discretized-normal(m) x K(m), re-centred so the
mean is exactly the projection. Same idea for totals (41, 44, 37, 47, 51 ...).

Fair line = w * model + (1 - w) * sharp-market consensus, where w comes from the
backtest (artifacts/calibration.json). If the model adds nothing beyond the
market, the backtest pushes w toward 0 and the report stops showing phantom edges.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.stats import norm


# ----------------------------------------------------------------------------
# odds conversions
# ----------------------------------------------------------------------------
def american_to_decimal(a) -> float:
    a = float(a)
    return 1 + a / 100 if a > 0 else 1 + 100 / abs(a)


def decimal_to_american(d) -> float:
    d = float(d)
    if d <= 1:
        return float("nan")
    return (d - 1) * 100 if d >= 2 else -100 / (d - 1)


def prob_to_american(p) -> float:
    return decimal_to_american(1 / p) if 0 < p < 1 else float("nan")


def implied_prob(a) -> float:
    return 1 / american_to_decimal(a)


def no_vig(price_a, price_b):
    pa, pb = implied_prob(price_a), implied_prob(price_b)
    s = pa + pb
    return pa / s, pb / s


def fmt_american(a) -> str:
    if a is None or not np.isfinite(a):
        return ""
    a = int(round(a))
    return f"+{a}" if a > 0 else str(a)


# ----------------------------------------------------------------------------
# key-number aware distributions
# ----------------------------------------------------------------------------
class KeyDist:
    def __init__(self, lo, hi, sd, K=None):
        self.support = np.arange(lo, hi + 1, dtype=float)
        self.sd = float(sd)
        self.K = np.ones_like(self.support) if K is None else np.asarray(K, dtype=float)
        self._cache: dict = {}

    def with_sd(self, sd):
        """Same key-number shape, different spread (shares K; cached per sd)."""
        sd = round(float(sd), 1)
        if abs(sd - self.sd) < 1e-9:
            return self
        cache = self.__dict__.setdefault("_scaled", {})
        if sd not in cache:
            d = KeyDist.__new__(KeyDist)
            d.support, d.sd, d.K, d._cache = self.support, sd, self.K, {}
            cache[sd] = d
        return cache[sd]

    def _base(self, m):
        s = self.support
        return norm.cdf((s + 0.5 - m) / self.sd) - norm.cdf((s - 0.5 - m) / self.sd)

    @classmethod
    def fit(cls, values, means, sd, lo, hi, smooth=25.0):
        d = cls(lo, hi, sd)
        v = np.asarray(values, dtype=float)
        mu = np.asarray(means, dtype=float)
        ok = np.isfinite(v) & np.isfinite(mu)
        v, mu = v[ok], mu[ok]
        if len(v) < 300:
            return d
        obs = np.bincount((np.clip(np.round(v), lo, hi) - lo).astype(int), minlength=len(d.support)).astype(float)
        exp = np.zeros(len(d.support))
        for chunk in np.array_split(mu, max(1, len(mu) // 2000)):
            exp += (norm.cdf((d.support[None, :] + 0.5 - chunk[:, None]) / sd)
                    - norm.cdf((d.support[None, :] - 0.5 - chunk[:, None]) / sd)).sum(axis=0)
        d.K = (obs + smooth) / (exp + smooth)
        return d

    def pmf(self, mean):
        key = round(float(mean), 2)
        if key in self._cache:
            return self._cache[key]
        lo, hi = mean - 6.0, mean + 6.0
        s = self.support
        for _ in range(40):
            mid = (lo + hi) / 2
            p = self._base(mid) * self.K
            p = p / p.sum()
            if (p * s).sum() < mean:
                lo = mid
            else:
                hi = mid
        p = self._base((lo + hi) / 2) * self.K
        p = p / p.sum()
        self._cache[key] = p
        return p

    def outcome(self, mean, sign, handicap):
        """P(win), P(push), P(lose) for a bet that wins when sign*X + handicap > 0."""
        p = self.pmf(mean)
        val = sign * self.support + handicap
        win = p[val > 1e-9].sum()
        push = p[np.abs(val) <= 1e-9].sum()
        return float(win), float(push), float(1 - win - push)

    def implied_mean(self, sign, handicap, p_side):
        """Mean that makes a bet (sign, handicap) win p_side of non-push outcomes."""
        lo, hi = self.support[0] + 15, self.support[-1] - 15
        for _ in range(40):
            mid = (lo + hi) / 2
            w, _, l = self.outcome(mid, sign, handicap)
            q = w / (w + l) if w + l > 0 else 0.5
            if (q < p_side) == (sign > 0):
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2


def game_dists(dm, dt, cfg, expected_total):
    """Higher-scoring games have wider outcome ranges: scale both distributions with the expected
    total (exponents estimated by backtest.py from how residuals grow with the closing total)."""
    if not np.isfinite(expected_total) or (cfg.sd_total_alpha == 0 and cfg.sd_total_beta == 0):
        return dm, dt
    r = max(float(expected_total), 20.0) / cfg.sd_ref_total
    return dm.with_sd(dm.sd * r ** cfg.sd_total_alpha), dt.with_sd(dt.sd * r ** cfg.sd_total_beta)


def fit_distributions(sched: pd.DataFrame, cfg):
    done = sched.dropna(subset=["result", "spread_line", "total", "total_line"])
    dm = KeyDist.fit(done["result"], done["spread_line"], cfg.margin_sd, -80, 80)
    dt = KeyDist.fit(done["total"], done["total_line"], cfg.total_sd, 0, 130)
    return dm, dt


# ----------------------------------------------------------------------------
# market consensus
# ----------------------------------------------------------------------------
def book_means(row, dm, dt):
    """Implied (margin mean, total mean) from one book's spread/total (or moneyline)."""
    m_mu, t_mu = np.nan, np.nan
    hs, hp, ap = row.get("home_spread"), row.get("home_spread_price"), row.get("away_spread_price")
    if _ok(hs, hp, ap):
        p_home, _ = no_vig(hp, ap)
        m_mu = dm.implied_mean(+1, float(hs), p_home)
    elif _ok(row.get("home_ml"), row.get("away_ml")):
        p_home, _ = no_vig(row["home_ml"], row["away_ml"])
        m_mu = dm.implied_mean(+1, 0.0, p_home)
    tl, op, up = row.get("total"), row.get("over_price"), row.get("under_price")
    if _ok(tl, op, up):
        p_over, _ = no_vig(op, up)
        t_mu = dt.implied_mean(+1, -float(tl), p_over)
    return m_mu, t_mu


def _ok(*xs):
    for x in xs:
        try:
            if x is None or not math.isfinite(float(x)):
                return False
        except (TypeError, ValueError):
            return False
    return True


def consensus(odds_game: pd.DataFrame, cfg, dm, dt):
    """Median implied mean across sharp books; fall back to other books, then DraftKings."""
    res = {}
    rows = odds_game.to_dict("records")
    means = {r["book"]: book_means(r, dm, dt) for r in rows}
    for idx, key in ((0, "margin"), (1, "total")):
        for label, books in (("sharp", cfg.sharp_books), ("other books", cfg.extra_books),
                             ("DraftKings only", [cfg.target_book])):
            vals = [means[b][idx] for b in books if b in means and np.isfinite(means[b][idx])]
            if vals:
                res[key] = float(np.median(vals))
                res[f"{key}_source"] = f"{label} ({', '.join(b for b in books if b in means and np.isfinite(means[b][idx]))})"
                break
        else:
            res[key], res[f"{key}_source"] = np.nan, "no market"
    res["dk_margin"], res["dk_total"] = means.get(cfg.target_book, (np.nan, np.nan))
    return res


# ----------------------------------------------------------------------------
# bets
# ----------------------------------------------------------------------------
def kelly(p_w, p_l, price):
    b = american_to_decimal(price) - 1
    if b <= 0 or p_w + p_l <= 0:
        return 0.0
    return max((p_w * b - p_l) / (b * (p_w + p_l)), 0.0)


def _bet(dist, mean, sign, handicap, price, cfg):
    w, p, l = dist.outcome(mean, sign, handicap)
    dec = american_to_decimal(price)
    ev = w * (dec - 1) - l
    f = kelly(w, l, price) * cfg.kelly_fraction
    stake = min(f, cfg.max_stake_pct) * cfg.bankroll
    fair = prob_to_american(w / (w + l)) if w + l > 0 else np.nan
    return dict(p_win=w, p_push=p, p_lose=l, ev=ev, stake=round(stake, 2) if ev > 0 else 0.0, fair_price=fair)


def _spread_label(team, pts):
    if abs(pts) < 1e-9:
        return f"{team} pk"
    return f"{team} {pts:+g}".replace("-", "\u2212")


def price_games(target: pd.DataFrame, odds: pd.DataFrame, cfg, dm, dt, weights):
    """target: rows with game_id, home_team, away_team, model_margin, model_total.
    odds: wide per (game_id, book). Returns (summary per game, board of DraftKings offers)."""
    w_m, w_t = weights
    summaries, board = [], []
    for g in target.to_dict("records"):
        og = odds[odds["game_id"] == g["game_id"]] if odds is not None and len(odds) else pd.DataFrame()
        cons = consensus(og, cfg, dm, dt) if len(og) else {"margin": np.nan, "total": np.nan,
                                                            "margin_source": "no market", "total_source": "no market",
                                                            "dk_margin": np.nan, "dk_total": np.nan}
        mm, mt = g["model_margin"], g["model_total"]
        wm = float(g.get("w_margin_game", w_m)) if np.isfinite(g.get("w_margin_game", np.nan)) else w_m
        wt = float(g.get("w_total_game", w_t)) if np.isfinite(g.get("w_total_game", np.nan)) else w_t
        fm = wm * mm + (1 - wm) * cons["margin"] if np.isfinite(cons["margin"]) else mm
        ft = wt * mt + (1 - wt) * cons["total"] if np.isfinite(cons["total"]) else mt
        dmg, dtg = game_dists(dm, dt, cfg, ft)
        s = dict(game_id=g["game_id"], model_margin=mm, model_total=mt, market_margin=cons["margin"],
                 market_total=cons["total"], market_margin_source=cons["margin_source"],
                 market_total_source=cons["total_source"], fair_margin=fm, fair_total=ft,
                 dk_margin=cons["dk_margin"], dk_total=cons["dk_total"],
                 margin_gap=mm - cons["margin"], total_gap=mt - cons["total"],
                 no_market=not np.isfinite(cons["margin"]), weight_margin=wm, weight_total=wt,
                 margin_sd_game=dmg.sd, total_sd_game=dtg.sd)
        dk = og[og["book"] == cfg.target_book] if len(og) else og
        if len(dk):
            d = dk.iloc[-1].to_dict()
            s.update({f"dk_{k}": d.get(k) for k in ("home_spread", "home_spread_price", "away_spread",
                                                    "away_spread_price", "total", "over_price", "under_price",
                                                    "home_ml", "away_ml")})
            h, a = g["home_team"], g["away_team"]
            news_m = np.isfinite(s["margin_gap"]) and abs(s["margin_gap"]) > cfg.news_gap_points
            news_t = np.isfinite(s["total_gap"]) and abs(s["total_gap"]) > cfg.news_gap_points
            offers = []
            if _ok(d.get("home_spread"), d.get("home_spread_price")):
                offers.append(("spread", _spread_label(h, float(d["home_spread"])), dmg, fm, +1,
                               float(d["home_spread"]), d["home_spread_price"], news_m))
            if _ok(d.get("away_spread"), d.get("away_spread_price")):
                offers.append(("spread", _spread_label(a, float(d["away_spread"])), dmg, fm, -1,
                               float(d["away_spread"]), d["away_spread_price"], news_m))
            if _ok(d.get("total"), d.get("over_price")):
                offers.append(("total", f"Over {float(d['total']):g}", dtg, ft, +1, -float(d["total"]),
                               d["over_price"], news_t))
            if _ok(d.get("total"), d.get("under_price")):
                offers.append(("total", f"Under {float(d['total']):g}", dtg, ft, -1, float(d["total"]),
                               d["under_price"], news_t))
            if _ok(d.get("home_ml")):
                offers.append(("moneyline", f"{h} to win", dmg, fm, +1, 0.0, d["home_ml"], news_m))
            if _ok(d.get("away_ml")):
                offers.append(("moneyline", f"{a} to win", dmg, fm, -1, 0.0, d["away_ml"], news_m))
            for market, label, dist, mean, sign, hcap, price, news in offers:
                b = _bet(dist, mean, sign, hcap, float(price), cfg)
                # points of value vs the sharp market for this side (positive = DraftKings is generous)
                if market == "total" and _ok(s["dk_total"], cons["total"]):
                    dk_vs = sign * (cons["total"] - s["dk_total"])
                elif market == "spread" and _ok(s["dk_margin"], cons["margin"]):
                    dk_vs = sign * (cons["margin"] - s["dk_margin"])
                else:
                    dk_vs = np.nan
                board.append(dict(game_id=g["game_id"], matchup=f"{a} @ {h}", market=market, bet=label,
                                  price=float(price), **b, check_news=bool(news),
                                  dk_vs_market=dk_vs, no_market=s["no_market"],
                                  is_play=bool(b["ev"] >= cfg.min_ev and not news and not s["no_market"])))
        summaries.append(s)
    return pd.DataFrame(summaries), pd.DataFrame(board)
