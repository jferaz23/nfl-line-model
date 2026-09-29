"""How much to trust the model vs the market, game by game.

Two ideas from published NFL modeling work:

1. Error-weighted market regression (nfelo). Blending a model with the market beats either one alone,
   and scaling the blend by how accurate the model has recently been *for these two teams*,
   relative to the market, improves it further. Each team keeps an exponential average of the
   model's and the market's squared errors in its recent games; when the model has been beating
   the market on those teams, it gets more weight in the next game, and less when it hasn't.

2. Game-specific outcome spread. In higher-scoring games the same expected margin is less certain,
   so cover probabilities should come from a wider distribution. The exponent linking the spread of
   results to the closing total is estimated from history.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

KEY = ["season", "week"]


def fit_sd_exponents(oos: pd.DataFrame, ref_total=44.0):
    """Slopes of log|residual| on log(total line): how outcome spread scales with expected scoring."""
    out = {}
    d = oos.dropna(subset=["result", "spread_line", "total", "total_line"])
    d = d[d["total_line"] > 20]
    if len(d) < 300:
        return dict(sd_total_alpha=0.0, sd_total_beta=0.0, sd_ref_total=ref_total)
    x = np.log(d["total_line"].to_numpy(float) / ref_total)
    for name, resid in (("sd_total_alpha", d["result"] - d["spread_line"]), ("sd_total_beta", d["total"] - d["total_line"])):
        y = np.log(np.abs(resid.to_numpy(float)) + 1.0)
        b = np.polyfit(x, y, 1)[0]
        out[name] = float(np.clip(b, 0.0, 1.0))
    out["sd_ref_total"] = float(ref_total)
    return out


def _ema_state(rows, half_life):
    """Walk games in time order; yield (index, rel_margin, rel_total) using only earlier games, then update."""
    a = 1.0 - 0.5 ** (1.0 / half_life)
    st = {}
    for r in rows.itertuples():
        vals = []
        for kind in ("m", "t"):
            em = [st.get((tm, kind), (np.nan, np.nan)) for tm in (r.home_team, r.away_team)]
            mod = [e[0] for e in em if np.isfinite(e[0])]
            mkt = [e[1] for e in em if np.isfinite(e[1])]
            vals.append(np.mean(mod) - np.mean(mkt) if mod and mkt else 0.0)
        yield r.Index, vals[0], vals[1]
        for kind, y, mdl, mk in (("m", r.result, r.model_margin, r.spread_line), ("t", r.total, r.model_total, r.total_line)):
            if not (np.isfinite(y) and np.isfinite(mdl) and np.isfinite(mk)):
                continue
            for tm in (r.home_team, r.away_team):
                em, ek = st.get((tm, kind), (np.nan, np.nan))
                se_m, se_k = (y - mdl) ** 2, (y - mk) ** 2
                st[(tm, kind)] = (se_m if not np.isfinite(em) else (1 - a) * em + a * se_m,
                                  se_k if not np.isfinite(ek) else (1 - a) * ek + a * se_k)
    rows.attrs["state"] = st


def relative_errors(oos: pd.DataFrame, half_life):
    d = oos.sort_values(KEY).copy()
    rel_m, rel_t = pd.Series(0.0, index=d.index), pd.Series(0.0, index=d.index)
    gen = _ema_state(d, half_life)
    for idx, rm, rt in gen:
        rel_m[idx], rel_t[idx] = rm, rt
    return rel_m.reindex(oos.index), rel_t.reindex(oos.index), d.attrs.get("state", {})


def dyn_weight(base_w, rel, scale):
    """Model weight: market weight grows when the model has been worse than the market (rel > 0)."""
    r_base = 1.0 - base_w
    r = np.clip(r_base * (1.0 + np.asarray(rel, float) / scale), 0.0, 1.0)
    return 1.0 - r


def tune(oos: pd.DataFrame, base_w_m, base_w_t, grid_hl=(4, 8, 16), grid_scale=(20, 40, 80, 160)):
    """Pick the half-life and scale on all but the last season; report the last season out of sample."""
    d = oos.dropna(subset=["result", "total", "spread_line", "total_line", "model_margin", "model_total"])
    if d["season"].nunique() < 3:
        return None
    last = d["season"].max()
    fit, test = d["season"] < last, d["season"] == last

    def mse(mask, w, kind):
        y = d["result"] if kind == "m" else d["total"]
        m = d["model_margin"] if kind == "m" else d["model_total"]
        k = d["spread_line"] if kind == "m" else d["total_line"]
        p = w * m + (1 - w) * k
        return float(((y - p)[mask] ** 2).mean())

    best = None
    for hl in grid_hl:
        rm, rt, _ = relative_errors(d, hl)
        for sc in grid_scale:
            wm, wt = dyn_weight(base_w_m, rm, sc), dyn_weight(base_w_t, rt, sc)
            score = mse(fit, wm, "m") + mse(fit, wt, "t")
            if best is None or score < best[0]:
                best = (score, hl, sc, wm, wt)
    _, hl, sc, wm, wt = best
    flat = mse(test, np.full(len(d), base_w_m), "m"), mse(test, np.full(len(d), base_w_t), "t")
    dyn = mse(test, wm, "m"), mse(test, wt, "t")
    y_m, y_t = d.loc[test, "result"], d.loc[test, "total"]
    mae = lambda y, p: float(np.abs(y - p).mean())
    return dict(half_life=float(hl), scale=float(sc), test_season=int(last),
                rmse_flat=(flat[0] ** 0.5, flat[1] ** 0.5), rmse_dynamic=(dyn[0] ** 0.5, dyn[1] ** 0.5),
                mae_dynamic=(mae(y_m, (wm * d["model_margin"] + (1 - wm) * d["spread_line"])[test]),
                             mae(y_t, (wt * d["model_total"] + (1 - wt) * d["total_line"])[test])),
                mae_market=(mae(y_m, d.loc[test, "spread_line"]), mae(y_t, d.loc[test, "total_line"])),
                improves=bool(dyn[0] + dyn[1] < flat[0] + flat[1]))


def target_weights(oos: pd.DataFrame, target: pd.DataFrame, base_w_m, base_w_t, half_life, scale):
    """Per-game model weights for upcoming games, from the teams' recent model-vs-market errors."""
    _, _, st = relative_errors(oos.dropna(subset=["result"]), half_life)
    wm, wt = [], []
    for r in target.itertuples(index=False):
        rel = []
        for kind in ("m", "t"):
            em = [st.get((tm, kind), (np.nan, np.nan)) for tm in (r.home_team, r.away_team)]
            mod = [e[0] for e in em if np.isfinite(e[0])]
            mkt = [e[1] for e in em if np.isfinite(e[1])]
            rel.append(np.mean(mod) - np.mean(mkt) if mod and mkt else 0.0)
        wm.append(float(dyn_weight(base_w_m, rel[0], scale)))
        wt.append(float(dyn_weight(base_w_t, rel[1], scale)))
    return np.array(wm), np.array(wt)
