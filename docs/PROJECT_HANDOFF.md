# NFL Line Model: Project Handoff for Claude Code

Last updated September 29, 2026, the Tuesday before NFL Week 4 (2026 season). Written at the end of
a long Claude.ai chat session that designed, built and iterated on this project, so a Claude Code
session can pick it up without the chat. `CLAUDE.md` in the repo root is the short version; this file
has the full context, decisions, research and backlog.

---

## 0. Read this first

**What it is.** A Python pipeline that sets its own NFL point spreads and totals ("Vegas-style"
lines) for every game each week, turns them into fair prices, compares them with DraftKings, and
flags DraftKings bets with positive expected value. It also prices moneylines, tracks closing-line
value (CLV), learns line movement for bet timing, and self-optimizes via walk-forward backtests.

**State of play.**
- Everything is built and runs end to end, **but only on a synthetic demo league** (`--demo`). The
  chat sandbox had no internet, so the model has **never been run on real NFL data**.
- The first job for Claude Code is to run it on real data: `python optimize.py` (first run downloads
  ~15 seasons of nflverse play-by-play and tunes; slow), then `python run_week.py`.
- A separate, hand-assembled Week 4 website exists (`site/week4_2026/`), built from a manually
  captured multi-book odds snapshot. It is not yet generated from the pipeline.

**Golden rules (keep these).**
1. The user bets **only at DraftKings**. DraftKings prices are the ones to evaluate; other books are
   for consensus/fair value. DraftKings lines come from The Odds API (`draftkings` key), never by
   scraping DraftKings.
2. **No scraping Pro Football Reference** (its terms prohibit automated access without written
   permission). PFR data is only read from pages/CSVs the user saves by hand (`pfr_exports/`).
   Historical line spreadsheets (e.g. Australia Sports Betting) are personal-use downloads.
3. **Never fabricate real-week picks or numbers.** Synthetic/demo output must stay labeled as such.
4. **Every feature must be as-of kickoff** (only information available before the game). No leakage.
5. **Every new factor is shrunk toward zero and must earn its place** in the backtest ablation.
   Core groups (team strength, home field, quarterback, injuries, weather) are protected from pruning.
6. **pandas 2.x and 3.x compatible**: no chained assignment, use `.loc`, avoid `groupby.apply`.
7. Honest framing in anything user-facing: NFL markets are efficient, edges are small, judge by CLV,
   break-even at -110 is 52.4%, "information only, not financial advice", 1-800-GAMBLER line on sites.

**Top next tasks** (details in section 13):
1. Run `python optimize.py` on real data; record the real MAE vs closing line and the pruning log.
2. Sanity-check real-data features (no all-zero columns from missing play-by-play fields).
3. Verify unconfirmed data details (Odds API book keys, 2026 stadium table entries).
4. Generate the weekly website from pipeline output instead of the manual snapshot.
5. Schedule runs (Tue/Fri/Sun) so DraftKings line history accumulates for the movement model.

---

## 1. The user and what they asked for

- Based in Boston, MA. Bets only at DraftKings. Wants the model "as close to Vegas accuracy as
  possible", accounting for "every single possible factor" (weather, opponents, schemes, coaches,
  active/inactive players, location, time of day, historical data, turf vs grass, etc.), with the
  most attractive DraftKings lines each week.
- Asked for historical backing (they mentioned Pro Football Reference, last 5 years); the model
  trains on nflverse data from 2012 on and backtests the last several seasons.
- Asked for a website: organized game by game (sorted by date/time), a spread, total and moneyline
  pick per game with % chance of hitting, fair value vs other books, other relevant info; a condensed
  bottom section with **spreads and totals only** (no moneylines), sorted by % chance of hitting;
  picks should be **whichever side has the higher chance of hitting**; later "cleaner, more
  organized/professional".
- Repeatedly asked to research more factors and "close the gap" to the market. They respond well
  to concrete numbers (model vs market MAE) and plain explanations.

---

## 2. Status and results so far (synthetic league only)

Average absolute miss per game in points (model vs actual result). Each "league" is a regenerated
synthetic dataset, so only compare numbers **within** a row group; the market's own miss changes
between leagues.

**Backtest (walk-forward, 2023-2026 demo seasons)**

| Stage | League | Spread: model / market / gap | Total: model / market / gap |
|---|---|---|---|
| After turnover-luck + special-teams features | v1 | 12.25 / 11.82 / +0.43 | 11.83 / 11.02 / +0.81 |
| After 6 factors (market ratings, WEPA, CPOE, pressure, 3rd-down luck, 2020 flag) | v2 | 11.76 / 11.29 / +0.47 | 11.89 / 11.41 / +0.48 |
| After drive efficiency, calendar, motivation | v3 | 12.01 / 11.46 / +0.55 | 12.35 / 11.87 / +0.48 |
| After full optimization (tuning, pruning, boosting weight), current code | v3 | **11.75 / 11.46 / +0.29** | **12.24 / 11.87 / +0.37** |
| Blended line actually used for picks (current) | v3 | **11.43 vs 11.46** (14% model weight) | 11.87 vs 11.87 (1%) |

**Same-league A/B tests (test seasons 2024-25)**: the six factors cut the spread gap 0.70 -> 0.57
(v2) and 0.80 -> 0.47 (v3), totals 0.51 -> 0.33 (v2) and 0.81 -> 0.69 (v3). Drive efficiency,
calendar and motivation did not help on synthetic data (+0.06 / +0.07). Venue history moved things
by less than 0.03. The fake league does not simulate venue, weather, scheme or drive effects, so
those can only be judged on real data.

**Real-world benchmark to beat**: across 7,276 games since 1999, the closing spread missed the final
margin by 10.3 points on average (SD 13.2) and is essentially unbiased (nflanalytic.com).

---

## 3. Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ODDS_API_KEY=...            # free key at the-odds-api.com

# smoke tests (no internet)
python run_week.py --demo
python optimize.py --demo --quick

# real data
python optimize.py                 # tune -> backtest -> prune -> calibrate (slow first time)
python optimize.py --skip-tune     # recalibrate only
python run_week.py                 # next unplayed week, live DraftKings + other books
python run_week.py --refresh       # re-download current-season data (after Friday injuries, ~90 min pre-kickoff)
python run_week.py --no-odds       # model lines only
python run_week.py --lines-file overrides/manual_lines.csv
python clv_report.py               # CLV and P/L for bets in overrides/my_bets.csv
python pfr_check.py                # cross-check nflverse vs hand-saved PFR tables
python backtest.py --no-optimize   # quick backtest without pruning/boosting selection

# Week 4 website (manual snapshot data)
python site/week4_2026/value.py    # DraftKings vs other books CSV
python site/week4_2026/site3.py    # writes reports/site/week4_picks.html
```

Weekly workflow: Tuesday/Wednesday run (opening look), Friday after injury reports
(`--refresh`, edit `overrides/`), Sunday ~90 minutes before kickoff after inactives.

---

## 4. Repository map

| File | Lines | Purpose |
|---|---|---|
| `run_week.py` | 195 | weekly run: project a week, price DraftKings vs market, write line sheet/CSVs, bet timing |
| `backtest.py` | 302 | walk-forward evaluation; pruning, boosting weight, blend, outcome spread, dynamic blend, movement model -> calibration.json |
| `tune.py` | 93 | coordinate search over rating/QB memory settings -> artifacts/tuned_config.json |
| `optimize.py` | 42 | tune.py then backtest.py in one command |
| `clv_report.py` | 165 | closing-line value and P/L for logged bets |
| `pfr_check.py` | 32 | cross-check nflverse results with hand-saved Pro Football Reference tables |
| `nflmodel/config.py` | 106 | Config dataclass (all settings) and JSON overrides |
| `nflmodel/data.py` | 304 | nflverse loading, caching, cleaning (schedules, pbp, snaps, injuries, rosters) |
| `nflmodel/venues.py` | 213 | team names/aliases, stadium table, travel, time zones, kickoff times |
| `nflmodel/ratings.py` | 262 | team game logs, opponent-adjusted ridge ratings, QB values, Elo |
| `nflmodel/availability.py` | 213 | snap-weighted missing starters by position group |
| `nflmodel/features.py` | 1013 | one row per game with every factor, as-of kickoff; MARGIN_GROUPS/TOTAL_GROUPS |
| `nflmodel/model.py` | 95 | LineModel: ridge + optional gradient boosting, explanations |
| `nflmodel/pricing.py` | 296 | odds math, key-number distributions, consensus, fair lines, EV, Kelly |
| `nflmodel/regress.py` | 127 | error-weighted market regression and outcome-spread exponents |
| `nflmodel/movement.py` | 240 | open->close line movement model, history loaders, bet timing |
| `nflmodel/odds.py` | 153 | The Odds API fetch/parse/match, manual lines, snapshots |
| `nflmodel/weather.py` | 75 | Open-Meteo forecasts for outdoor games |
| `nflmodel/pfr.py` | 174 | PFR export parser and cross-check (no scraping) |
| `nflmodel/report.py` | 339 | weekly HTML line sheet, CSVs, backtest HTML |
| `nflmodel/synthetic.py` | 487 | synthetic demo league in nflverse schema (for --demo tests) |
| `nflmodel/pipeline.py` | 136 | shared helpers: data loading, overrides, calibration, tuned settings, demo |
| `site/week4_2026/board.py` | 85 | Week 4 multi-book odds snapshot (hand-transcribed) |
| `site/week4_2026/common.py` | 193 | site helpers: pricing math, metadata, formatting |
| `site/week4_2026/value.py` | 67 | DraftKings vs other books value CSV |
| `site/week4_2026/site2.py` | 350 | site logic: picks, factor adjustments, weather/news (also writes older layout) |
| `site/week4_2026/site3.py` | 248 | current site layout (v3) -> reports/site/week4_picks.html |

Other: `overrides/` (weekly inputs), `pfr_exports/` (hand-saved PFR tables), `config.example.json`,
`requirements.txt`, `README.md` (user-facing guide), `docs/PROJECT_HANDOFF.md` (this file),
`CLAUDE.md` (short instructions for Claude Code). Generated at runtime: `data_cache/`, `artifacts/`
(calibration, tuned settings, backtest predictions, odds snapshots, coefficients), `reports/`.

---

## 5. Data sources and conventions

**nflverse via `nflreadpy`** (Polars; needs `pyarrow`), with a direct-download fallback and pickle
caches in `data_cache/` (`nflmodel/data.py`, class `DataStore`). Datasets: schedules (required),
play-by-play (required), snap counts, injuries, weekly rosters (optional; missing ones append a note
and the run continues).

- `spread_line` is the **expected home margin** (positive = home favored); `result` = home score -
  away score; `total` = combined points. `clean_schedules` auto-flips the spread sign if its
  correlation with `result` is negative.
- Play-by-play columns requested (`PBP_COLUMNS` in `data.py`) include EPA, success, xpass, no-huddle,
  shotgun, passer/rusher ids, down/distance/yardline, penalty, weather text, game clock, plus the
  newer fields: interception, fumble, fumble_lost, sack, qb_hit, special_teams_play, touchdown, cpoe,
  wp, third_down_converted, third_down_failed, drive. The loader silently keeps only columns that
  exist, so **check on real data that none of the features built from these are all zeros**.
- The current-season injury feed can be late or broken; the pipeline degrades gracefully and the
  user can fill `overrides/player_status.csv`.
- Snap counts (used for "regular starter" availability) start in 2012, which is why
  `first_season = 2012`. nfelo's research found longer training histories predict better; moving
  `first_season` earlier is a tuning option at the cost of no availability features before 2012.

**The Odds API v4** (`nflmodel/odds.py`): `GET https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/`
with `markets=h2h,spreads,totals`, `oddsFormat=american`, `bookmakers=<comma list>`. Cost is
3 credits per group of up to 10 books (default 13 books = 6 credits/call; free plan 500/month).
Usage headers `x-requests-remaining/used/last` are logged. Every raw response is saved to
`artifacts/odds_snapshots/` (feeds CLV and the movement model). Totals outcomes are "Over"/"Under".
Events are matched to the schedule by team names and commence time (36 h window), with home/away
flips for neutral sites. Fallback: `overrides/manual_lines.csv`.
- Book keys: target `draftkings`; sharp consensus `pinnacle, lowvig, betonlineag, novig, prophetx`;
  other US books `fanduel, betmgm, williamhill_us (Caesars), fanatics, espnbet, betrivers,
  hardrockbet`. **The last five keys were not verified against the Odds API docs** in the chat;
  unknown keys just return nothing. Circa is a key US market maker; add it if the API offers it.

**Open-Meteo** (`nflmodel/weather.py`): hourly temperature, precipitation, snowfall, wind, gusts in
F/mph/inch, averaged over kickoff to +3 h, outdoor games only, cached in `artifacts/forecasts/`.
Retractable roofs are assumed closed for upcoming games.

**Pro Football Reference** (`nflmodel/pfr.py`, `pfr_check.py`): reads `pfr_exports/games_<season>.csv`
("Get table as CSV") or `.html` (saved page), cross-checks every nflverse score and adds PFR yards and
turnovers (`pfr_*` columns). Never downloads from PFR.

**Line history** (`nflmodel/movement.py`): an opening/closing spreadsheet the user downloads for
personal use (Australia Sports Betting's NFL file works; save as `data_cache/line_history.xlsx`),
plus DraftKings open/close reconstructed from the saved Odds API snapshots.

**Overrides** (`overrides/`, each with instructions at the top): `starters.csv` (force a QB),
`player_status.csv` (OUT/DOUBTFUL/QUESTIONABLE/IN or 0-1), `manual_lines.csv`, `my_bets.csv`.

**Stadium table** (`nflmodel/venues.py`): coordinates, time zone, altitude, roof, surface per team
and relocation era, plus international/neutral sites. To verify for 2026: Buffalo's new Highmark
Stadium (surface/roof), Carolina's surface, and any other 2026 venue changes.

---

## 6. Pipeline architecture

`data.py` -> `ratings.py` -> `availability.py` -> `features.py` -> `model.py` -> `pricing.py`
(+ `odds.py`, `weather.py`, `regress.py`, `movement.py`) -> `report.py`, orchestrated by
`run_week.py` (weekly), `backtest.py` (evaluation/calibration), `tune.py`, `optimize.py`.

- **Ratings** (`ratings.py`): per completed game, two team rows (points, pass/rush EPA, success rate,
  pace, PROE, no-huddle, weighted EPA with offense- and defense-specific weights, points per drive,
  drives). `RatingEngine.asof(season, week)` fits opponent-adjusted offense/defense ridge ratings for
  each target with recency weights (half-life `rating_half_life_weeks`), offseason decay, and a
  team-specific home-field term. Defense sign convention: positive = allows more. Also an Elo model
  and QB game logs/values (`qb_values_asof`, recency half-life, prior plays, replacement gap).
- **Availability** (`availability.py`): snap-weighted share of regular starters missing by position
  group (OL, WR, TE, RB, DL, LB, DB) from snaps + rosters + injury report + overrides.
- **Features** (`features.py`, `build_games`): one row per game, as-of kickoff. Main parts: rating
  merges; projected starting QBs (override > last starter > roster/injury checks > backup blend by
  play probability); a sequential loop (`_context`) for Elo, rest, streaks, coaches, referees,
  head-to-head, records, ATS/O-U form, turnover/pressure/third-down luck, motivation proxies;
  venue/time/weather (`_venue_time_weather`); market-implied ratings (`_add_market_ratings`, a
  weighted least-squares fit to prior closing lines); QB CPOE (`_add_qb_cpoe`); venue history
  (`_add_venue_history`). Group definitions: `MARGIN_GROUPS`, `TOTAL_GROUPS`.
- **Model** (`model.py`, `LineModel`): ridge (median impute, standardize, `RidgeCV`, sample weights
  0.9^seasons back) plus optional gradient boosting (HistGradientBoosting depth 3, 400 iterations),
  mixed per market by `gbm_weight_margin` / `gbm_weight_total` (chosen by backtest). `explain()`
  gives per-group contributions; `coefficients()` a table. The model never sees the betting line.
- **Pricing** (`pricing.py`): `KeyDist` discretized normal with key-number multipliers fitted from
  history (3, 7, 10...), mean matched by bisection; `game_dists` widens/narrows the distribution with
  the expected total (`sd_total_alpha`, `sd_total_beta`). Consensus = median implied mean of sharp
  books (fallback other books, then DraftKings). **Fair line = w x model + (1 - w) x consensus**,
  with w per game when the error-weighted regression is on. EV = p_win x (decimal - 1) - p_lose;
  Kelly fraction 0.25, capped at 2% of bankroll; "check news" flag when model and market differ by
  more than 4 points.
- **Market regression** (`regress.py`): nfelo-style error-weighted blend (each team's exponential
  average of model vs market squared error sets the game's model weight) and the outcome-spread
  exponents.
- **Movement** (`movement.py`): ridge of (close - open) on the model's disagreement with the opener
  plus key-number flags; `timing()` labels each DraftKings offer "Bet now" / "Can wait" (defaults
  when no history: favorites and overs earlier, underdogs and unders later).
- **Report** (`report.py`): weekly HTML line sheet (highlighter design), CSV board and projections,
  backtest HTML. Demo outputs carry a synthetic-data banner.

---

## 7. Factor groups and features (generated from `features.py`)

Spread model (`MARGIN_GROUPS`, positive = good for the home team):

| Group | What | Features |
|---|---|---|
| home_field | home/neutral, team home-field trend, division, playoff, 2020 empty stadiums | `home_ind`, `hfa_trend`, `div_game`, `playoff`, `home_no_fans` |
| team_strength | opponent-adjusted ratings, weighted EPA, market-implied ratings, special teams, Elo | `d_wepa_net`, `d_mkt_rating`, `d_st_epa`, `d_pts_net`, `d_off_pass`, `d_def_pass`, `d_off_rush`, `d_def_rush`, `d_sr_net`, `elo_diff` |
| scheme_matchup | matchup EPA, pass rate over expected, pace, no-huddle | `matchup_epa_margin`, `d_proe`, `d_pace` |
| quarterback | projected starter value vs league and team baseline, new QB, CPOE | `d_qb_val`, `d_qb_delta`, `d_qb_new`, `d_qb_cpoe` |
| injuries | snap-weighted missing regulars by position group | `d_miss_OL`, `d_miss_WR`, `d_miss_TE`, `d_miss_RB`, `d_miss_DL`, `d_miss_LB`, `d_miss_DB` |
| rest_travel | rest, byes, short weeks, travel miles, time zones, international, road streaks | `rest_diff`, `home_bye`, `away_bye`, `home_short`, `away_short`, `away_travel_kmi`, `d_travel_kmi`, `tz_shift_away`, `intl`, `away_road_streak`, `short_x_travel` |
| time_of_day | body clock, early West Coast kickoffs, prime time, weekday games | `d_body_clock`, `west_early`, `prime_x_clock`, `thu`, `mon`, `sat` |
| weather | wind, cold, heat, rain, snow, dome/warm teams in cold, outdoor teams indoors | `wind_x_passdiff`, `dome_team_cold`, `warm_team_cold`, `outdoor_in_dome` |
| venue_history | team/coach/QB results at the stadium, QB dome/cold splits, stadium scoring | `home_venue_resid`, `away_venue_resid`, `home_coach_venue_resid`, `away_coach_venue_resid`, `d_qb_venue`, `d_qb_env` |
| surface_altitude | turf, surface mismatch, altitude | `away_surface_mismatch`, `home_surface_mismatch`, `alt_adv_kft` |
| coaching | coach vs spread, tenure, new coach, fourth-down aggressiveness | `d_coach_resid`, `d_new_coach`, `d_coach_tenure` |
| officials | referee margin/total tendencies, penalty rate | `ref_margin_resid` |
| history | head-to-head and home/road results vs the spread | `h2h_resid`, `home_ats_resid`, `road_ats_resid` |
| situational | previous game, overtime, look-ahead, records, luck (turnovers, sacks, third downs), pressure | `d_prev_margin`, `prev_ot_h`, `prev_ot_a`, `d_next_opp_elo`, `early_x_strength`, `d_winless`, `d_unbeaten`, `d_record_luck`, `d_ats_form`, `d_post_intl`, `d_fum_luck`, `d_to_margin`, `d_press`, `d_sack_luck`, `d_3rd_luck` |
| drive_efficiency | points per drive, drives per game | `d_ppd_net` |
| motivation | late-season elimination/clinch proxies, Week 18 rest risk | `d_elim`, `d_rest_risk` |

Total model (`TOTAL_GROUPS`):

| Group | What | Features |
|---|---|---|
| scoring_env | league scoring level, early season, playoffs, division, pressure, O/U form | `sum_press`, `sum_3rd_luck`, `sum_ou_form`, `sum_post_intl`, `lg_pts_level`, `early_season`, `playoff`, `div_game` |
| drive_efficiency | points per drive, drives per game | `ppd_total_pred`, `drives_total` |
| calendar | November and December/January scoring | `wk_nov`, `wk_dec` |
| motivation | late-season elimination/clinch proxies, Week 18 rest risk | `sum_elim` |
| team_strength | opponent-adjusted ratings, weighted EPA, market-implied ratings, special teams, Elo | `pts_total_pred`, `sum_wepa`, `mkt_total_pred`, `sum_off_pass`, `sum_def_pass`, `sum_off_rush`, `sum_def_rush` |
| scheme_matchup | matchup EPA, pass rate over expected, pace, no-huddle | `matchup_epa_total`, `pace_total`, `proe_sum`, `nohuddle_sum` |
| quarterback | projected starter value vs league and team baseline, new QB, CPOE | `sum_qb_val`, `sum_qb_delta`, `sum_qb_cpoe` |
| injuries | snap-weighted missing regulars by position group | `off_miss_sum`, `def_miss_sum` |
| rest_travel | rest, byes, short weeks, travel miles, time zones, international, road streaks | `rest_sum_short`, `away_travel_kmi`, `intl` |
| time_of_day | body clock, early West Coast kickoffs, prime time, weekday games | `kickoff_et`, `primetime`, `thu`, `mon`, `sat` |
| weather | wind, cold, heat, rain, snow, dome/warm teams in cold, outdoor teams indoors | `indoor`, `wind_over10`, `wind_over15`, `cold`, `heat`, `precip`, `snow`, `outdoor_in_dome_sum` |
| venue_history | team/coach/QB results at the stadium, QB dome/cold splits, stadium scoring | `venue_total_resid`, `sum_qb_venue`, `sum_qb_env` |
| surface_altitude | turf, surface mismatch, altitude | `turf`, `altitude_kft` |
| coaching | coach vs spread, tenure, new coach, fourth-down aggressiveness | `coach_aggr_sum`, `sum_new_coach` |
| officials | referee margin/total tendencies, penalty rate | `ref_total_resid`, `ref_pen_rate` |
| history | head-to-head and home/road results vs the spread | `h2h_total_resid` |

132 distinct features. Protected from pruning: team_strength, home_field, quarterback, injuries, weather.

### Settings (`nflmodel/config.py` defaults; override with `--config file.json`)

| Setting | Default |
|---|---|
| `first_season` | `2012` |
| `cache_dir` | `'data_cache'` |
| `artifacts_dir` | `'artifacts'` |
| `reports_dir` | `'reports'` |
| `overrides_dir` | `'overrides'` |
| `pfr_dir` | `'pfr_exports'` |
| `current_season_cache_hours` | `6.0` |
| `rating_half_life_weeks` | `8.0` |
| `offseason_decay` | `0.6` |
| `rating_lookback_seasons` | `3` |
| `ridge_lambda` | `4.0` |
| `qb_half_life_weeks` | `26.0` |
| `qb_offseason_decay` | `0.85` |
| `qb_prior_plays` | `200.0` |
| `qb_replacement_gap` | `0.12` |
| `qb_plays_per_game` | `38.0` |
| `regular_window_games` | `4` |
| `regular_min_share` | `0.35` |
| `status_play_prob` | `{'OUT': 0.0, 'DOUBTFUL': 0.12, 'QUESTIONABLE': 0.75, 'PROBABLE': 0.95, 'IR': 0.0, 'PUP': 0.0, 'NFI': 0.0, 'SUSPENDED': 0.0, 'INACTIVE': 0.0, 'ACTIVE': 1.0, 'IN': 1.0, 'PLAYING': 1.0}` |
| `min_train_season` | `2014` |
| `train_recency_decay` | `0.9` |
| `ridge_alphas` | `[1, 3, 10, 30, 100, 300, 1000, 3000, 10000, 30000]` |
| `use_gbm` | `True` |
| `gbm_weight` | `0.35` |
| `target_book` | `'draftkings'` |
| `sharp_books` | `['pinnacle', 'lowvig', 'betonlineag', 'novig', 'prophetx']` |
| `extra_books` | `['fanduel', 'betmgm', 'williamhill_us', 'fanatics', 'espnbet', 'betrivers', 'hardrockbet']` |
| `model_weight_spread` | `0.3` |
| `model_weight_total` | `0.3` |
| `margin_sd` | `13.3` |
| `total_sd` | `13.6` |
| `min_ev` | `0.02` |
| `sd_total_alpha` | `0.0` |
| `sd_total_beta` | `0.0` |
| `sd_ref_total` | `44.0` |
| `dyn_half_life_games` | `0.0` |
| `dyn_scale` | `40.0` |
| `drop_groups_margin` | `[]` |
| `gbm_weight_margin` | `-1.0` |
| `gbm_weight_total` | `-1.0` |
| `drop_groups_total` | `[]` |
| `news_gap_points` | `4.0` |
| `kelly_fraction` | `0.25` |
| `max_stake_pct` | `0.02` |
| `bankroll` | `1000.0` |
| `odds_api_key_env` | `'ODDS_API_KEY'` |
| `line_history_path` | `'data_cache/line_history.xlsx'` |

---

## 8. Optimization and calibration

`optimize.py` = `tune.py` then `backtest.py`:
1. **tune.py**: coordinate search over `rating_half_life_weeks` (5/8/12), `offseason_decay`
   (0.45/0.6/0.75), `qb_half_life_weeks` (16/26/40), `qb_prior_plays` (120/200/320), scored by
   walk-forward MAE (linear model) on the last 3 seasons; writes `artifacts/tuned_config.json`, which
   `backtest.py` and `run_week.py` apply automatically (`pipeline.apply_tuned`).
2. **backtest.py**: selection seasons = all but the last; held-out = last.
   - Pruning (`prune_groups`): drop-one ablation, then greedy drops kept only if the joint miss
     falls by >= 0.005 and the held-out season does not get worse by > 0.005. Protected:
     `team_strength, home_field, quarterback, injuries, weather`.
   - Boosting weight per market (`choose_gbm_weights`) from grid 0-0.7, fallback 0 if held-out disagrees.
   - Blend weight = OLS of (result - market) on (model - market), minus one standard error, clipped 0-1.
   - Outcome-spread exponents, error-weighted blend tuning (grid half-life 4/8/16 games x scale
     20/40/80/160; used only if it lowers held-out squared error), line-movement model if history exists.
   - Writes `artifacts/calibration.json`, `artifacts/backtest_oos.csv`, `reports/backtest.html`.

Current demo `calibration.json` keys: model_weight_spread, model_weight_total, gbm_weight_margin,
gbm_weight_total, margin_sd, total_sd, sd_total_alpha, sd_total_beta, sd_ref_total,
dyn_half_life_games, dyn_scale, drop_groups_margin, drop_groups_total, seasons, n_games, raw_weights.
Demo values after the latest run: spread model weight 14%, totals 1%; boosting 10% spreads, 0% totals;
dropped for spreads: situational, history, rest_travel, drive_efficiency; for totals: coaching,
venue_history. **These are synthetic and will be replaced by the first real run.**

---

## 9. How sportsbooks make and move lines (research summary, and what we copy)

- Market makers (Pinnacle, Circa, Bookmaker/BetCRIS) originate numbers from power ratings plus
  adjustments (home field, injuries, travel, rest, form) and open with low limits so sharp money
  corrects them; retail books (DraftKings, FanDuel, BetMGM) follow with a delay. DraftKings posts
  look-ahead lines and firms them after Sunday.
- Weekly arc: openers Sunday night/Monday move on sharp money; midweek on injury reports, QB news,
  weather; late week recreational money lands on favorites and overs. Favorites tend to be cheapest
  early; underdogs are often best Sunday morning. Limits rise through the week; the closing line is
  the most efficient number, hence CLV as the scorecard.
- Levitt (2004): bookmakers set prices that exploit bettor biases rather than balancing action;
  later tests found a smaller effect. Big favorites, road favorites and overs on high totals draw a
  disproportionate share of bets; betting against lopsided public sentiment was profitable on spreads,
  not totals.
- QB changes are the biggest line movers: oddsmakers value top starters at ~7 points over backups
  (2025 poll: Josh Allen 6.98, Patrick Mahomes 6.94); the market sometimes overcorrects.
- nfelo: blending a model with the market beats both; scaling the blend by recent relative accuracy
  helps further (implemented in `regress.py`).

---

## 10. Factor research log (why each factor exists)

| Factor | Evidence found | Implementation |
|---|---|---|
| Rain at kickoff | Totals under 57.4% with measurable rain at kickoff, 343 games (Sharp Football) | weather `precip` (totals); site adjustment |
| Wind | 15+ mph disrupts passing and kicking | `wind_over10/15`, `wind_x_passdiff` |
| Rest | 4+ day gaps worth ~2 points but mostly priced (~0.45 pts missed, BettorEdge / nflanalytic); rested side vs Monday-night team covered 51.8%; 3-day gaps worth nothing | rest features |
| Body clock | West Coast teams at 1 p.m. ET lost ~3 points historically, books shift lines similarly (Football Outsiders) | `d_body_clock`, `west_early` |
| Winless / unbeaten starts | 0-2 teams covered 55.7% in Week 3 since 2003 (Yahoo) | `d_winless`, `d_unbeaten` |
| Record vs point differential, ATS/O-U streaks | overreaction to records | `d_record_luck`, `d_ats_form`, `sum_ou_form` |
| After an overseas trip | small samples (17 teams since 2016 played the week after Europe) | `d_post_intl` |
| Fumble/turnover luck | recoveries ~coin flips; extreme turnover margins regress (nflanalytic) | `d_fum_luck`, `d_to_margin` |
| Special teams | real but small strength component | `d_st_epa` |
| Weighted EPA | nfelo WEPA beat EPA and DVOA at predicting future margin; separate offense/defense weights | rating targets `wepao`, `wepad`; `d_wepa_net`, `sum_wepa` |
| Market-implied ratings | preseason/market priors improve predictions all season (TeamRankings); ESPN FPI preseason from win totals | `d_mkt_rating`, `mkt_total_pred` |
| QB CPOE | EPA+CPOE composite among the most predictive QB measures; CPOE stable | `d_qb_cpoe`, `sum_qb_cpoe` |
| Pass rush vs protection | pressure stable, sacks lucky (nflanalytic) | `d_press`, `sum_press`, `d_sack_luck` |
| Third-down luck | third-down rates regress heavily; early-down success is the stable signal | `d_3rd_luck`, `sum_3rd_luck` |
| Empty stadiums 2020 | home teams 127-128-1; empty stadiums hurt home teams (arXiv 2104.11595) | `home_no_fans` |
| Drive efficiency | the drive is often the right unit of offense (nflanalytic) | `d_ppd_net`, `ppd_total_pred`, `drives_total` |
| Scoring calendar | November scoring sag | `wk_nov`, `wk_dec` |
| Late-season motivation | mixed: favorites in motivation spots 45-45-2 over 11 seasons; a spoiler system claims 61% ATS for eliminated 7+ dogs; Week 18 rest moves lines massively (use overrides) | `d_elim`, `d_rest_risk`, `sum_elim` |
| Venue history | team-specific home edges tend not to last (nfelo); Denver shows no durable edge; team HFA volatile (Open Source Football); books bake team HFA into spreads | `_add_venue_history`: team/coach/QB at stadium, QB dome/cold splits, stadium scoring |
| Outcome spread vs total | same margin less certain when more scoring (Matter of Stats); distribution width varies game to game | `sd_total_alpha/beta` |
| Error-weighted market regression | nfelo market regression article | `regress.py` |
| Wind unders (Sept 30, 2026) | closing totals under-react to wind: outdoor unders with a kickoff forecast of 10+ mph wind or 20+ mph gusts went 225-166-4 (57.5%, +44.0u) 2018-26 at closing prices; 2018-21, not used to choose the rule, 103-88-2 (+9.9u); all outdoor unders 52.3% | `nflmodel/wind.py`, weekly card (not a model feature) |
| Missing skill-player value (tested and rejected Sept 30, 2026) | regular WR/TE/RB (10%+ of targets+carries over 4 games) missing, weighted by EPA per touch above league x touches per game. Production backtest vs a fresh baseline: spread MAE -0.007 (95% CI -0.018 to +0.004), better in both halves, pruning kept it, but Top picks 170-122-7 +38.7u -> 138-110-7 +21.9u and green +51.3u -> +27.4u, so it failed the pass rule set beforehand (Top and green units not lower) | not in the model |
| Overnight research (Oct 1-2, 2026) | 28 tests against a measured noise floor; see CLAUDE.md "Pass rule". Adopted Oct 2 after the user's OK: Top = any 4+ pt spread edge (241-176 57.8% +49.7u vs 169-123 +36.7u; 55.8-57.0% vs 50.8-56.6% under perturbation); measured injury odds (Questionable 65.7%, Doubtful 0.7%, by final practice 42/68/79%); early-week value tracker (information only; 3+ pt edges vs openers 56.3% nfelo 2015-26, 56.2% ESPN BET 2024-26). Promising, not adopted: nfelo Elo + QB adj (MAE -0.025 but worse 2024-26; no license). No help: ESPN FPI, Prediction Tracker systems (none beats the close in both halves), market-anchored model, own 538 QB rating, preseason DVOA prior (noise level), favorite/total teasers, moneyline value, 32 betting angles | see CLAUDE.md |
| Next Gen Stats team offense (tested and rejected Sept 30, 2026) | rushing yards over expected per carry (2018+), receiver separation, YAC over expected (2016+), team sums over the previous 8 games, shrunk to league. Spread MAE +0.007 (CI -0.012 to +0.024; worse 2015-20, better 2021-26), Top 170-122-7 +38.7u -> 174-136-7 +28.7u, green +51.3u -> +35.0u: failed | not in the model |

---

## 11. The Week 4 2026 website (`site/week4_2026/`)

- Published as a private Claude artifact during the chat: https://claude.ai/artifact/NBqQW51JDXauQLTMS2HSHB
  (regenerate locally with `python site/week4_2026/site3.py`; output `reports/site/week4_picks.html`).
- **Data is a manual snapshot, not pipeline output**: DraftKings, bet365, BetMGM, Caesars, FanDuel,
  Fanatics, BetRivers and Hard Rock full-game prices transcribed from VegasInsider's Week 4 odds table
  (captured Sept 29; page last updated Sept 28) into `board.py`; kickoff forecasts from MySportsWeather
  (Sept 29) and injury news (Sept 29) typed into `site2.py`; openers from VegasInsider/Borgata notes.
  Rams-Eagles is flagged stale (DraftKings moved to Rams -2.5 at -120, total 44.5 after MNF).
- **Chance to hit** = median no-vig probability across the seven other books, converting different
  numbers via push probabilities (3: 9%, 7: 6.5%, others 2-5%; totals 2.8-3.5%).
- **Picks** = side with the higher factor-adjusted chance to hit (spread, total, moneyline).
  Adjustments (probability points, all shrunk): rain = rain chance x (57.4% - 50%) x 0.5 toward the
  under; 0-3 teams +1.4 (a quarter of the 55.7% 0-2 edge); 4+ day rest edge +0.7 (Atlanta).
  Tiers: beats the market (edge >= 0), near fair (>= -2.5%), below fair.
- **"When to bet"** labels come from `movement.timing()` defaults (no line history yet).
- Layout v3 (`site3.py`, `site3.css`): masthead with stamps, sticky section tabs, KPI strip, schedule
  grid with top pick per game, Best bets table, game cards (header with rotation numbers, win-chance
  bar, opener; picks table; context and factors; all-books price table), bottom table of the 32 spread
  and total picks sorted by chance with filters/sorting, method and sources footer. IBM Plex Sans /
  Plex Sans Condensed, tabular numerals, light and dark tokens, mobile card layout below 700px.
- Snapshot results: 5 of 32 spread/total picks beat DraftKings' price after adjustments (best:
  Lions-Panthers under 50.5 -108, +2.1%); only the Chargers ML (+280) beat the market before adjustments.
- **To do**: generate this site from `run_week.py` outputs (live Odds API board, model fair lines,
  pipeline weather/injuries) instead of the hand-typed snapshot, and reuse the v3 design.

---

## 12. Known issues and things to verify

- Never run on real data; expect bugs in real-data paths (column names, dtypes, missing optional
  datasets, team-name matching for odds).
- Unverified Odds API book keys (see section 5); unverified 2026 stadium entries (Buffalo, Carolina).
- The loader drops missing play-by-play columns silently; add a check that warns when a feature is
  constant/zero on real data.
- Pruning, boosting and blend selection use a single held-out season; with real data consider
  rolling multi-season validation. The demo held-out season has only 3 weeks.
- The error-weighted blend is switched on when the **combined** spread+total squared error improves;
  in the last demo run it slightly worsened spreads (15.25 -> 15.27) while improving totals. Consider
  deciding per market.
- `_add_venue_history` iterates rows in Python (fine for ~4k games; profile if slow).
- While writing this handoff, two overlapping venue-history implementations were found in
  `features.py` (one inside `_context` plus `_add_qb_venue`, one in `_add_venue_history`) with
  duplicate `venue_history` dict keys; they were consolidated into `_add_venue_history` only.
- Motivation proxies (elimination/clinch by win% after 11+ games) are crude; real playoff-odds or
  standings logic would be better.
- The Week 4 site is market comparison plus small research adjustments, not model output.
- nflverse snap counts have the two teams' rows swapped in three games (2014_21_NE_SEA, 2015_21_CAR_DEN,
  2018_21_NE_LA: Super Bowls), which mislabeled availability (`miss_*`) for those games. Fixed Oct 1, 2026: `data.fix_snap_teams` detects
  and swaps them at load time (backtest: spread MAE -0.002, totals -0.005; Top -2.0u, green -9.1u).

---

## 13. Backlog (prioritized)

1. **Real-data run**: `python optimize.py`; save the console output and `reports/backtest.html`;
   compare model vs closing MAE; review which groups were pruned.
2. **Data sanity layer**: assertions/warnings for missing columns, constant features, odds matching
   failures, and schedule sign conventions.
3. **Weekly site from the pipeline**: build the v3 page from `projections_*.csv` and
   `dk_board_*.csv` (+ model explanations), publish or write HTML to `reports/`.
4. **Scheduling**: run `run_week.py` Tue/Fri/Sun (cron/Task Scheduler) so odds snapshots accumulate;
   periodically `optimize.py --skip-tune`.
5. **Per-market decisions** for the error-weighted blend; rolling-origin validation for pruning.
6. **Preseason win totals** input (market prior for Week 1-4; not in nflverse).
7. **Opponent-adjusted QB values** (currently raw EPA-based with recency and priors).
8. **Tests** (pytest): leakage checks (features only use t < game), pricing math (push handling,
   no-vig), odds parsing, PFR/line-history parsers, synthetic end-to-end.
9. **Performance**: cache `build_games` outputs per settings hash (tuning rebuilds features each try).
10. Optional data: public betting splits, PFF-style player grades (paid), referee assignments feed.

---

## 14. Sources consulted in the chat

- nflverse / nflreadpy (data); The Odds API v4 (odds); Open-Meteo (forecasts)
- Point-spread accuracy (MAE 10.3, SD 13.2): https://nflanalytic.com/explainer-point-spread-accuracy.html
- Turnover luck: https://nflanalytic.com/explainer-turnovers-luck.html
- Third downs: https://nflanalytic.com/explainer-third-down.html
- Explainer index (pressure vs sacks, drives): https://nflanalytic.com/explainers.html
- Rest and 2026 schedule quirks: https://nflanalytic.com/explainer-2026-schedule-quirks.html
- Bye-week/rest pricing: https://www.bettoredge.com/post/betting-teams-off-a-bye-week
- Rain and weather: https://www.sharpfootballanalysis.com/betting/nfl-weather-betting/
- 0-2 teams ATS: https://sports.yahoo.com/nfl/betting/article/week-3-nfl-odds-picks-predictions-our-best-bets-for-the-weekends-games-163138710.html
- Body clock: https://www.footballoutsiders.com/stat-analysis/2016/east-coast-scheduling-bias
- Weighted EPA: https://www.nfeloapp.com/analysis/weighted-EPA-methodology-and-performance/
- Market regression: https://www.nfeloapp.com/analysis/using-market-regression-to-improve-prediction-accuracy-in-the-nfl/
- HFA exploration: https://www.nfeloapp.com/analysis/an-initial-exploration-of-home-field-advantage-in-the-nfl/
- HFA tracker: https://www.nfeloapp.com/tools/nfl-home-field-advantage-hfa-tracker/
- Team HFA volatility: https://opensourcefootball.com/posts/2021-01-11-hfa-analysis/
- Preseason ratings: https://www.teamrankings.com/blog/nfl/preseason-rankings-ratings-explanation
- CPOE: https://sticktothemodel.com/encyclopedia/cpoe and https://illinoissportsanalytics.com/qb-success-in-recent-history
- 2020 home teams: https://www.nbcsports.com/nfl/profootballtalk/rumor-mill/news/home-field-was-no-advantage-home-teams-went-127-128-1-in-2020-season and https://arxiv.org/pdf/2104.11595
- Outcome spread vs total: http://www.matterofstats.com/mafl-stats-journal/2024/7/8/the-relationship-between-expected-victory-margins-and-estimated-win-probabilities
- Motivation: https://edwithsports.substack.com/p/never-use-playoff-motivation-to-bet and https://www.cbssports.com/nfl/news/nfl-week-18-picks-experts-betting-system-looks-at-eliminated-teams-aiming-to-play-spoiler
- Line making: https://help.outlier.bet/en/articles/9922960-how-sportsbooks-set-odds-soft-vs-sharp-books , https://www.actionnetwork.com/education/how-do-betting-lines-work-vegas , https://bookies.com/news/where-do-betting-lines-come-from , https://unabated.com/articles/who-sets-the-sports-betting-line-market-makers
- Line movement: https://www.deucescracked.com/sports-betting/strategy/line-movement , https://www.sportsbettingdime.com/nfl/public-betting-trends/
- Bettor biases: https://pricetheory.uchicago.edu/levitt/Papers/LevittWhyAreGamblingMarkets2004.pdf , https://www.researchgate.net/publication/227346720_NFL_bettor_biases_and_price_setting_further_tests_of_the_Levitt_hypothesis_of_sportsbook_behaviour
- QB spread values: https://sports.yahoo.com/nfl/betting/article/oddsmakers-rank-all-32-nfl-starting-qbs-by-point-spread-value-how-valuable-is-lamar-jackson-to-the-spread-150837453.html
- PFR data use and bot policy: https://www.sports-reference.com/data_use.html , https://www.sports-reference.com/bot-traffic.html
- Historical lines (personal use): https://www.aussportsbetting.com/data/historical-nfl-results-and-odds-data/
- Week 4 snapshot sources: https://www.vegasinsider.com/nfl/nfl-week-4-odds-2026/ , https://mysportsweather.com/nfl

---

## 15. Glossary

- **MAE**: mean absolute error (average miss in points). **CLV**: closing-line value, how much better
  your number was than the close. **No-vig**: probabilities with the book's margin removed.
- **Key numbers**: common NFL margins (3, 7, 10, 6, 4...) that make half-point moves valuable.
- **Blend weight**: share of the model in the fair line; the rest is the sharp consensus.
- **Ablation/pruning**: dropping a factor group to see whether out-of-sample accuracy improves.
- **As-of**: computed only from information available before kickoff.
