"""Central configuration.

Every number here is a default. Override any of them with a JSON file:
    python run_week.py --config my_settings.json
where my_settings.json looks like {"min_ev": 0.03, "bankroll": 2500}.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class Config:
    # ---------------- data ----------------
    first_season: int = 2012            # snap counts (player availability) start in 2012
    cache_dir: str = "data_cache"
    artifacts_dir: str = "artifacts"
    reports_dir: str = "reports"
    overrides_dir: str = "overrides"
    pfr_dir: str = "pfr_exports"
    current_season_cache_hours: float = 6.0

    # ------------- team power ratings -------------
    # Opponent-adjusted ratings from a recency-weighted ridge regression on
    # points, EPA/play (pass and rush separately), success rate, pace and PROE.
    rating_half_life_weeks: float = 8.0
    offseason_decay: float = 0.6        # extra weight multiplier per season boundary
    rating_lookback_seasons: int = 3
    ridge_lambda: float = 4.0           # shrinkage toward league average, in "games"

    # ------------- quarterbacks -------------
    qb_half_life_weeks: float = 26.0
    qb_offseason_decay: float = 0.85
    qb_prior_plays: float = 200.0       # shrink small samples toward replacement level
    qb_replacement_gap: float = 0.12    # replacement QB = league avg EPA/play minus this
    qb_plays_per_game: float = 38.0     # converts EPA/play into points per game

    # ------------- player availability -------------
    regular_window_games: int = 4       # "regular" = recent snap share over this many team games
    regular_min_share: float = 0.35
    status_play_prob: dict = field(default_factory=lambda: {
        "OUT": 0.0, "DOUBTFUL": 0.12, "QUESTIONABLE": 0.75, "PROBABLE": 0.95,
        "IR": 0.0, "PUP": 0.0, "NFI": 0.0, "SUSPENDED": 0.0, "INACTIVE": 0.0,
        "ACTIVE": 1.0, "IN": 1.0, "PLAYING": 1.0,
    })

    # ------------- game model -------------
    min_train_season: int = 2014        # first season used to fit the game model
    train_recency_decay: float = 0.9    # weight per season back in time when fitting
    ridge_alphas: list = field(default_factory=lambda: [1, 3, 10, 30, 100, 300, 1000, 3000, 10000, 30000])
    use_gbm: bool = True                # add gradient boosting for non-linear effects
    gbm_weight: float = 0.35

    # ------------- pricing / market -------------
    target_book: str = "draftkings"
    sharp_books: list = field(default_factory=lambda: [
        "pinnacle", "lowvig", "betonlineag", "novig", "prophetx"])
    extra_books: list = field(default_factory=lambda: [
        "fanduel", "betmgm", "williamhill_us", "fanatics", "espnbet", "betrivers", "hardrockbet"])
    # How much weight the fair line puts on the model vs the sharp market.
    # backtest.py estimates these from history and writes artifacts/calibration.json,
    # which overrides the defaults below.
    model_weight_spread: float = 0.30
    model_weight_total: float = 0.30
    margin_sd: float = 13.3
    total_sd: float = 13.6
    min_ev: float = 0.02                # flag bets at +2% expected value or better
    # outcome spread grows with the expected total (fit by backtest.py; 0 = constant spread)
    sd_total_alpha: float = 0.0
    sd_total_beta: float = 0.0
    sd_ref_total: float = 44.0
    # error-weighted market regression (nfelo-style; set by backtest.py; 0 = flat weights)
    dyn_half_life_games: float = 0.0
    dyn_scale: float = 40.0
    # factor groups the backtest ablation found to hurt out of sample (set by backtest.py --ablation)
    drop_groups_margin: list = field(default_factory=list)
    # weight of the gradient-boosting component per market (-1 = use gbm_weight); set by backtest.py
    gbm_weight_margin: float = -1.0
    gbm_weight_total: float = -1.0
    drop_groups_total: list = field(default_factory=list)
    news_gap_points: float = 4.0        # model vs market gap that usually means missing news
    kelly_fraction: float = 0.25
    max_stake_pct: float = 0.02
    bankroll: float = 1000.0
    odds_api_key_env: str = "ODDS_API_KEY"
    use_espn: bool = True          # ESPN same-day injuries (weekly run) and scoreboard lines (line watch)
    # opening/closing line history for the line-movement model (see nflmodel/movement.py)
    line_history_path: str = "data_cache/line_history.xlsx"

    def path(self, attr: str) -> Path:
        p = Path(getattr(self, attr))
        p.mkdir(parents=True, exist_ok=True)
        return p


def load_config(path: str | None = None) -> Config:
    cfg = Config()
    if path:
        data = json.loads(Path(path).read_text())
        valid = {f.name for f in fields(Config)}
        for key, value in data.items():
            if key not in valid:
                raise ValueError(f"Unknown config key '{key}'. Valid keys: {sorted(valid)}")
            setattr(cfg, key, value)
    return cfg
