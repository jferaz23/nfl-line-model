#!/usr/bin/env python
"""Walk-forward backtest and calibration.

Each test season is predicted by models trained only on earlier seasons, using
features computed only from earlier games. Results:
  * accuracy vs the closing line (the bar any betting model has to clear)
  * how much weight the model deserves next to the market (-> artifacts/calibration.json)
  * ATS / over-under records by how far the model disagreed with the close
  * --ablation: which factor groups actually help out of sample

Examples
    python backtest.py                    # last 5 seasons
    python backtest.py --start 2018 --end 2025 --ablation
    python backtest.py --demo --ablation
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from nflmodel.config import load_config
from nflmodel.features import MARGIN_GROUPS, TOTAL_GROUPS, build_games
from nflmodel.model import LineModel
from nflmodel.data import DataUnavailable
from nflmodel.pipeline import apply_demo, apply_tuned, demo_data, load_real, setup_logging
from nflmodel.report import backtest_html

log = logging.getLogger("nflmodel")
THRESHOLDS = [0, 1, 2, 3, 4, 5]


def walk_forward(games, cfg, seasons, drop_groups=(), use_gbm=None, drop_m=None, drop_t=None):
    """Train on seasons before each test season, predict it. drop_m/drop_t drop groups per market."""
    dm_ = list(drop_m) if drop_m is not None else [g for g in drop_groups if g in MARGIN_GROUPS]
    dt_ = list(drop_t) if drop_t is not None else [g for g in drop_groups if g in TOTAL_GROUPS]
    parts, last = [], None
    for s in seasons:
        train, test = games[games["season"] < s], games[games["season"] == s]
        if test.empty or train["season"].nunique() < 1:
            continue
        mm = LineModel(cfg, "margin", drop_groups=dm_, use_gbm=use_gbm).fit(train)
        mt = LineModel(cfg, "total", drop_groups=dt_, use_gbm=use_gbm).fit(train)
        keep = ["game_id", "season", "week", "home_team", "away_team", "result", "total", "spread_line", "total_line",
                "home_spread_odds", "away_spread_odds", "over_odds", "under_odds", "home_moneyline", "away_moneyline",
                "h_qb_new", "a_qb_new", "h_qb_delta", "a_qb_delta"]
        t = test[[c for c in keep if c in test.columns]].copy()     # closing prices grade the track record
        t["model_margin"], t["model_total"] = mm.predict(test), mt.predict(test)
        t["ridge_margin"], t["gbm_margin"] = mm.predict_parts(test)
        t["ridge_total"], t["gbm_total"] = mt.predict_parts(test)
        parts.append(t)
        last = mm
    oos = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    return oos, last


PROTECTED = {"team_strength", "home_field", "quarterback", "injuries", "weather"}


def _mae(o, y, col):
    return float(np.abs(o[y] - o[col]).mean())


def prune_groups(games, cfg, sel, hold):
    """Drop factor groups that hurt: rank by drop-one ablation on the selection seasons, add drops one at a
    time only if the joint miss falls by 0.005+, then confirm on the held-out season. Core groups with
    overwhelming outside evidence are never dropped."""
    base, _ = walk_forward(games, cfg, sel, use_gbm=False)
    b = {"margin": _mae(base, "result", "model_margin"), "total": _mae(base, "total", "model_total")}
    rows = []
    for grp in dict.fromkeys(list(MARGIN_GROUPS) + list(TOTAL_GROUPS)):
        o, _ = walk_forward(games, cfg, sel, drop_groups=[grp], use_gbm=False)
        r = {"group": grp}
        if grp in MARGIN_GROUPS:
            r["margin"] = _mae(o, "result", "model_margin") - b["margin"]
        if grp in TOTAL_GROUPS:
            r["total"] = _mae(o, "total", "model_total") - b["total"]
        rows.append(r)
        log.info("  without %-16s margin %+.3f  total %+.3f", grp, r.get("margin", np.nan), r.get("total", np.nan))
    drops = {}
    for kind, y, col in (("margin", "result", "model_margin"), ("total", "total", "model_total")):
        cands = sorted((r[kind], r["group"]) for r in rows
                       if r.get(kind, 0.0) <= -0.01 and r["group"] not in PROTECTED)
        drop, best = [], b[kind]
        for _, grp in cands:
            kw = dict(drop_m=drop + [grp], drop_t=[]) if kind == "margin" else dict(drop_m=[], drop_t=drop + [grp])
            o, _ = walk_forward(games, cfg, sel, use_gbm=False, **kw)
            m = _mae(o, y, col)
            if m <= best - 0.005:
                drop.append(grp)
                best = m
        if drop and hold:
            kw1 = dict(drop_m=drop, drop_t=[]) if kind == "margin" else dict(drop_m=[], drop_t=drop)
            o0, _ = walk_forward(games, cfg, hold, use_gbm=False)
            o1, _ = walk_forward(games, cfg, hold, use_gbm=False, **kw1)
            m0, m1 = _mae(o0, y, col), _mae(o1, y, col)
            log.info("Pruning %s: %s; selection seasons %.3f -> %.3f, held-out season %.3f -> %.3f",
                     kind, drop, b[kind], best, m0, m1)
            if m1 > m0 + 0.005:
                log.info("  held-out season disagrees; keeping every group for %s", kind)
                drop = []
        drops[kind] = drop
    return drops["margin"], drops["total"], rows


def choose_gbm_weights(oos, sel, hold, grid=(0.0, 0.1, 0.2, 0.35, 0.5, 0.7)):
    """Pick each market's boosting weight on the selection seasons; fall back to 0 if the held-out season disagrees."""
    out = {}
    for kind, y in (("margin", "result"), ("total", "total")):
        r, g = oos[f"ridge_{kind}"], oos[f"gbm_{kind}"]
        g = g.fillna(r)          # seasons with too little history for boosting (2015) use the linear model alone
        if (g == r).all():
            out[kind] = 0.0
            continue
        ms, mh = oos["season"].isin(sel), oos["season"].isin(hold)
        err = lambda w, m: float(np.abs(oos.loc[m, y] - (r[m] + w * (g[m] - r[m]))).mean())
        w = min(grid, key=lambda w: err(w, ms))
        if hold and w > 0 and err(w, mh) > err(0.0, mh) + 0.005:
            w = 0.0
        out[kind] = float(w)
        oos[f"model_{kind}"] = r + w * (g - r)
    return out


def blend_weight(y, model, market):
    """OLS of (actual - market) on (model - market), no intercept. Returns (w_hat, se)."""
    x, r = model - market, y - market
    ok = np.isfinite(x) & np.isfinite(r)
    x, r = x[ok], r[ok]
    if len(x) < 50 or (x ** 2).sum() == 0:
        return 0.0, 1.0
    w = float((x * r).sum() / (x ** 2).sum())
    resid = r - w * x
    se = float(np.sqrt((resid ** 2).sum() / (len(x) - 1) / (x ** 2).sum()))
    return w, se


def record(oos, pred, actual, line):
    rows = []
    d = oos.dropna(subset=[pred, actual, line])
    gap = d[pred] - d[line]
    res = (d[actual] - d[line]) * np.sign(gap)
    for th in THRESHOLDS:
        m = gap.abs() >= max(th, 1e-9)
        wins, losses = int((res[m] > 0).sum()), int((res[m] < 0).sum())
        n = wins + losses
        rows.append(dict(threshold=th, n=n, win_rate=wins / n if n else float("nan"),
                         roi=(wins * 100 / 110 - losses) / n if n else float("nan")))
    return rows


def summarize(oos):
    out = {}
    for key, pred, actual, line in (("spread", "model_margin", "result", "spread_line"),
                                    ("total", "model_total", "total", "total_line")):
        d = oos.dropna(subset=[pred, actual, line])
        y, m, k = d[actual].to_numpy(float), d[pred].to_numpy(float), d[line].to_numpy(float)
        w_hat, se = blend_weight(y, m, k)
        w = float(np.clip(w_hat - se, 0.0, 1.0))  # one standard error down: don't let a lucky sample inflate edges
        blend = w * m + (1 - w) * k
        out[key] = dict(n=len(d), mae_model=float(np.abs(y - m).mean()), mae_market=float(np.abs(y - k).mean()),
                        mae_blend=float(np.abs(y - blend).mean()), weight=w, weight_raw=w_hat, weight_se=se,
                        sd=float(np.std(y - blend, ddof=1)), bias_model=float((y - m).mean()))
    return out


def fit_movement(cfg, oos, sched, art, path=None):
    """Learn open->close line movement from history + the model's out-of-sample numbers (for bet timing)."""
    from nflmodel.movement import MoveModel, attach, from_snapshots, load_history
    frames = []
    p = Path(path or cfg.line_history_path)
    if p.exists():
        try:
            frames.append(load_history(p))
        except Exception as e:
            log.warning("Line history %s unreadable: %s", p, e)
    snaps = Path(cfg.artifacts_dir) / "odds_snapshots"
    if snaps.exists():
        frames.append(from_snapshots(snaps, cfg.target_book))
    frames = [f for f in frames if f is not None and len(f)]
    if not frames or oos is None or oos.empty:
        print("\nLine movement: no opening-line history yet (see README, 'Line movement and timing').")
        return None
    hist = attach(pd.concat(frames, ignore_index=True), sched)
    d = hist.merge(oos[["game_id", "model_margin", "model_total"]], on="game_id", how="inner")
    mm = MoveModel().fit(d)
    if not mm.coef:
        print(f"\nLine movement: only {len(d)} games with openers matched; need 60+.")
        return None
    mm.save(art / "movement.json")
    print("\nLine movement (open -> close), out of sample model numbers:")
    for k, st in mm.stats.items():
        print(f"  {k:6}: {st['games']} games, average move {st['mean_abs_move']:.2f} pts, "
              f"prediction corr {st['corr_pred_actual']:+.2f}, direction right {st['direction_hit']:.0%}, "
              f"betting the model's side at open gained {st['clv_model_side_at_open']:+.2f} pts of CLV")
    return mm


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=int)
    ap.add_argument("--end", type=int)
    ap.add_argument("--ablation", action="store_true", help="(kept for compatibility; pruning now runs by default)")
    ap.add_argument("--no-optimize", action="store_true", help="skip pruning and boosting-weight selection (faster)")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--config")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--line-history", help="spreadsheet of opening/closing lines (default: config line_history_path)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    setup_logging(args.verbose)
    cfg = load_config(args.config)
    if args.demo:
        apply_demo(cfg)
    tuned_note = apply_tuned(cfg)
    if tuned_note:
        log.info(tuned_note)
    if args.demo:
        data, _, _ = demo_data(cfg)
    else:
        try:
            data, _ = load_real(cfg, refresh=args.refresh, need_current=False)
        except DataUnavailable as e:
            sys.exit(f"Could not load nflverse data: {e}\nCheck your internet connection, or try "
                     f"`pip install -U nflreadpy`.")

    games, info = build_games(data, cfg)
    games = games[games["has_ratings"] & games["result"].notna()]
    seasons_all = sorted(games["season"].unique())
    end = args.end or int(seasons_all[-1])
    start = args.start or (max(int(seasons_all[0]) + 1, cfg.backtest_start) if not args.demo
                           else max(int(seasons_all[0]) + 3, end - 4))
    seasons = [s for s in seasons_all if start <= s <= end]
    if not seasons or games[games["season"] < seasons[0]].empty:
        sys.exit("Not enough seasons before --start to train on. Lower cfg.min_train_season or raise --start.")
    log.info("Walk-forward over %s-%s (%d games)", seasons[0], seasons[-1], int(games["season"].isin(seasons).sum()))

    # ---------------- optimization: prune groups -> choose boosting weights -> final walk-forward -------------
    # choose settings on the earlier seasons and confirm them on the most recent ones (the last two when
    # there are enough seasons, so the check is not just the current season's few weeks)
    n_hold = 2 if len(seasons) >= 6 else (1 if len(seasons) >= 3 else 0)
    sel = seasons[:-n_hold] if n_hold else seasons
    hold = seasons[-n_hold:] if n_hold else []
    res = dict(start=seasons[0], end=seasons[-1])
    drop_m, drop_t = [], []
    if not args.no_optimize:
        log.info("Pruning factor groups (linear model, selection seasons %s-%s)...", sel[0], sel[-1])
        drop_m, drop_t, rows = prune_groups(games, cfg, sel, hold)
        res["ablation"] = sorted(rows, key=lambda r: -max(r.get("margin", -9), r.get("total", -9)))
        res["prune"] = dict(margin=drop_m, total=drop_t)
    oos, last_model = walk_forward(games, cfg, seasons, drop_m=drop_m, drop_t=drop_t,
                                   use_gbm=bool(cfg.use_gbm) or None)
    gbm_w = {"margin": cfg.gbm_weight_margin, "total": cfg.gbm_weight_total}
    if cfg.use_gbm and not args.no_optimize:
        gbm_w = choose_gbm_weights(oos, sel, hold)
        print(f"Boosting weight chosen out of sample: spreads {gbm_w['margin']:.0%}, totals {gbm_w['total']:.0%}")
    summ = summarize(oos)
    res.update(n_games=len(oos), summary=summ,
               ats=record(oos, "model_margin", "result", "spread_line"),
               ou=record(oos, "model_total", "total", "total_line"),
               coefs=last_model.coefficients() if last_model is not None else None)

    cal = dict(model_weight_spread=summ["spread"]["weight"], model_weight_total=summ["total"]["weight"],
               gbm_weight_margin=gbm_w["margin"], gbm_weight_total=gbm_w["total"],
               margin_sd=summ["spread"]["sd"], total_sd=summ["total"]["sd"],
               seasons=f"{seasons[0]}-{seasons[-1]}", n_games=len(oos),
               created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
               raw_weights=dict(spread=summ["spread"]["weight_raw"], total=summ["total"]["weight_raw"]))
    # game-specific outcome spread and error-weighted market regression
    from nflmodel.regress import fit_sd_exponents, tune
    cal.update(fit_sd_exponents(oos))
    dyn = tune(oos, summ["spread"]["weight"], summ["total"]["weight"])
    cal["dyn_half_life_games"], cal["dyn_scale"] = (dyn["half_life"], dyn["scale"]) if dyn and dyn["improves"] else (0.0, 40.0)
    if res.get("prune") is not None:
        cal["drop_groups_margin"], cal["drop_groups_total"] = res["prune"]["margin"], res["prune"]["total"]
        print("Groups dropped for weekly runs (they hurt out of sample): "
              f"spreads {res['prune']['margin'] or 'none'}, totals {res['prune']['total'] or 'none'}")
    art = cfg.path("artifacts_dir")
    (art / "calibration.json").write_text(json.dumps(cal, indent=2))
    oos.to_csv(art / "backtest_oos.csv", index=False)
    fit_movement(cfg, oos, data["schedules"], art, args.line_history)
    rep = cfg.path("reports_dir") / "backtest.html"
    rep.write_text(backtest_html(res, cfg, demo=args.demo), encoding="utf-8")

    print(f"\nOutcome spread grows with the total: margin exponent {cal['sd_total_alpha']:.2f}, "
          f"total exponent {cal['sd_total_beta']:.2f}")
    if dyn:
        print(f"Error-weighted market regression (half-life {dyn['half_life']:.0f} games, scale {dyn['scale']:.0f}), "
              f"tested on {dyn['test_season']}: RMSE spread {dyn['rmse_flat'][0]:.2f} flat -> {dyn['rmse_dynamic'][0]:.2f}, "
              f"total {dyn['rmse_flat'][1]:.2f} -> {dyn['rmse_dynamic'][1]:.2f}; "
              + ("using it." if dyn["improves"] else "no improvement, keeping flat weights."))
    print(f"\nBacktest {seasons[0]}-{seasons[-1]}, {len(oos)} games" + ("  [SYNTHETIC DEMO DATA]" if args.demo else ""))
    for k, v in summ.items():
        print(f"  {k:<6} MAE model {v['mae_model']:.2f}  closing line {v['mae_market']:.2f}  blend {v['mae_blend']:.2f}"
              f"  weight {v['weight']:.0%} (raw {v['weight_raw']:.2f} \u00b1 {v['weight_se']:.2f})  SD {v['sd']:.1f}")
    for key, lab in (("ats", "ATS"), ("ou", "O/U")):
        print(f"  {lab}: " + ", ".join(f">={r['threshold']}pt {r['win_rate']:.1%} (n={r['n']})" for r in res[key]))
    print(f"\nCalibration: {art / 'calibration.json'}\nReport: {rep}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
