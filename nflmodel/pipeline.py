"""Shared plumbing for the command-line scripts."""
from __future__ import annotations

import json
import logging
import pickle
from pathlib import Path

import pandas as pd

from .data import DataStore

log = logging.getLogger("nflmodel")

DEMO_SETTINGS = dict(first_season=2018, min_train_season=2020, rating_lookback_seasons=2)


def setup_logging(verbose=False):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")


def apply_demo(cfg):
    for k, v in DEMO_SETTINGS.items():
        setattr(cfg, k, v)
    cfg.artifacts_dir = str(Path(cfg.artifacts_dir) / "demo")
    cfg.reports_dir = str(Path(cfg.reports_dir) / "demo")
    return cfg


def demo_data(cfg):
    """Synthetic league, cached so repeated demo runs are fast."""
    from .synthetic import generate
    p = Path(cfg.cache_dir) / "synthetic_demo.pkl"
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        try:
            return pickle.loads(p.read_bytes())
        except Exception:
            pass
    log.info("Generating synthetic demo league (about 20 seconds, cached afterwards)...")
    out = generate()
    p.write_bytes(pickle.dumps(out))
    return out


def next_unplayed_week(sched: pd.DataFrame):
    todo = sched[sched["result"].isna()]
    if todo.empty:
        return None, None
    season = int(todo["season"].max())
    s = todo[todo["season"] == season]
    wk = int(s["week"].min())
    return season, wk


def load_real(cfg, refresh=False, target_season=None, need_current=True):
    """Download/cache everything needed. Returns (data dict, DataStore)."""
    ds = DataStore(cfg, refresh=refresh)
    sched = ds.schedules()
    sched = attach_pfr(cfg, sched, ds.notes)
    latest = int(sched["season"].max())
    current = target_season or latest
    ds.current_season = current
    seasons = list(range(cfg.first_season, current + 1))
    log.info("Loading play-by-play %s-%s (first run downloads ~%d files; later runs use the cache)...",
             seasons[0], seasons[-1], len(seasons))
    pbp = ds.pbp(seasons)
    snaps = ds.snap_counts(seasons)
    inj = ds.injuries([current]) if need_current else pd.DataFrame()
    # weekly rosters for every season (roster continuity); the current season's also drive availability
    rost_all = ds.rosters_weekly(seasons)
    from .data import fix_snap_teams
    snaps = fix_snap_teams(snaps, pbp, rost_all)
    rost = rost_all[rost_all["season"] == current].copy() if need_current and len(rost_all) else pd.DataFrame()
    return dict(schedules=sched, pbp=pbp, snaps=snaps, injuries=inj, rosters=rost, rosters_all=rost_all), ds


def attach_pfr(cfg, sched, notes):
    """Cross-check against any Pro Football Reference tables saved in pfr_exports/ (see nflmodel/pfr.py)."""
    from .pfr import cross_check, load_pfr_exports
    pfr, pn = load_pfr_exports(cfg.pfr_dir)
    notes += pn
    if pfr.empty:
        return sched
    sched, cn = cross_check(pfr, sched)
    notes += cn
    for n in pn + cn:
        log.info(n)
    return sched


TUNED_KEYS = ("rating_half_life_weeks", "offseason_decay", "qb_half_life_weeks", "qb_prior_plays",
              "ridge_lambda", "rating_lookback_seasons", "train_recency_decay")


def apply_tuned(cfg):
    """Use artifacts/tuned_config.json (written by tune.py) if it exists. Returns a note or ''."""
    p = Path(cfg.artifacts_dir) / "tuned_config.json"
    if not p.exists():
        return ""
    t = json.loads(p.read_text())
    used = {k: t[k] for k in TUNED_KEYS if k in t}
    for k, v in used.items():
        setattr(cfg, k, v)
    return "Tuned settings from tune.py: " + ", ".join(f"{k}={v}" for k, v in used.items()) + "."


def read_override(cfg, name, required_cols) -> pd.DataFrame:
    p = Path(cfg.overrides_dir) / name
    if not p.exists():
        return pd.DataFrame(columns=required_cols)
    df = pd.read_csv(p, comment="#", skip_blank_lines=True)
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"{p} is missing columns {missing}; expected {required_cols}")
    return df.dropna(subset=required_cols[:3])


def load_calibration(cfg):
    """Apply artifacts/calibration.json (written by backtest.py) to cfg; returns (weights, note)."""
    p = Path(cfg.artifacts_dir) / "calibration.json"
    if not p.exists():
        return (cfg.model_weight_spread, cfg.model_weight_total), (
            f"No backtest calibration found; using default model weights "
            f"({cfg.model_weight_spread:.0%} / {cfg.model_weight_total:.0%}). Run backtest.py to estimate them.")
    c = json.loads(p.read_text())
    cfg.model_weight_spread = float(c.get("model_weight_spread", cfg.model_weight_spread))
    cfg.model_weight_total = float(c.get("model_weight_total", cfg.model_weight_total))
    cfg.margin_sd = float(c.get("margin_sd", cfg.margin_sd))
    cfg.total_sd = float(c.get("total_sd", cfg.total_sd))
    cfg.drop_groups_margin = list(c.get("drop_groups_margin", cfg.drop_groups_margin))
    cfg.drop_groups_total = list(c.get("drop_groups_total", cfg.drop_groups_total))
    for k in ("sd_total_alpha", "sd_total_beta", "sd_ref_total", "dyn_half_life_games", "dyn_scale",
              "gbm_weight_margin", "gbm_weight_total"):
        if k in c:
            setattr(cfg, k, float(c[k]))
    return (cfg.model_weight_spread, cfg.model_weight_total), (
        f"Model weights from backtest {c.get('seasons', '')}: {cfg.model_weight_spread:.0%} spreads, "
        f"{cfg.model_weight_total:.0%} totals.")
