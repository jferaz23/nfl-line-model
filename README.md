# NFL line model

Builds its own point spread and total for every NFL game each week, turns them into
fair prices, and compares those with DraftKings to flag the bets with positive
expected value (EV). Everything is computed "as of kickoff": a game's features only
use information available before it was played, so the backtest is honest.

## Setup (once)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Get a free key at <https://the-odds-api.com> (500 credits/month; one pull
costs 6 with the default 13 books), then:

```bash
export ODDS_API_KEY=your_key_here                       # Windows: set ODDS_API_KEY=your_key_here
```

Check the install without internet or a key:

```bash
python run_week.py --demo          # synthetic league: exercises the whole pipeline
python backtest.py --demo
```

Demo output is fake data and says so on every page. It is only a smoke test.

## Where the lines come from

The `--demo` report uses invented games and lines, so its numbers will never match
DraftKings. A real run pulls DraftKings' own posted prices through The Odds API
(bookmaker key `draftkings`), which is the line you bet into. It also pulls the same
games from five sharp books (Pinnacle, LowVig, BetOnline, Novig, ProphetX) and seven
other US apps (FanDuel, BetMGM, Caesars, Fanatics, ESPN BET, BetRivers, Hard Rock).
The report shows each DraftKings price next to that market, and flags DraftKings numbers
that are better than the rest of the market for you. Lines move, so re-run before
betting and confirm the number in the DraftKings app.

## Pro Football Reference (optional cross-check)

Pro Football Reference's terms don't allow automated downloading without written
permission, so the pipeline never scrapes it. For the last five seasons you can save
each `/years/<season>/games.htm` page yourself into `pfr_exports/` (see the README
there). Every run then checks each nflverse result against PFR, lists any
disagreements in the report notes, and adds PFR's yards and turnovers per team
(columns `pfr_*`). Run `python pfr_check.py` to check the files on their own.

The model itself already trains on every season since 2012 from nflverse (play-by-play,
schedules, rosters and injuries; its snap counts come from PFR), and `backtest.py`
scores it on the last five seasons by default.

## First real run

```bash
python optimize.py
```

The first run downloads nflverse play-by-play since 2012 (a few hundred MB, cached in
`data_cache/`). It writes:

* `artifacts/calibration.json` — how much weight the model earns next to the sharp
  market, plus the margin/total spread of outcomes. `run_week.py` uses it automatically.
* `reports/backtest.html` — accuracy vs the closing line, ATS/over-under records by
  disagreement size, and which factor groups help out of sample (`--ablation`).

Re-run the backtest every few weeks or after changing settings.

## Weekly workflow

| When | Command | Why |
|---|---|---|
| Tuesday/Wednesday | `python run_week.py` | Opening look after lines settle |
| Friday, after injury reports | edit `overrides/`, then `python run_week.py --refresh` | Game statuses are known |
| Sunday, ~90 min before kickoff | update `overrides/player_status.csv`, then `python run_week.py --refresh` | Inactives are out; last chance before the close |

Each run writes `reports/line_sheet_<season>_week<NN>.html` (open it in a browser),
`dk_board_*.csv` (every DraftKings price with fair price, edge and stake) and
`projections_*.csv`. The week defaults to the next one with unplayed games; use
`--season 2026 --week 5` to choose.

Useful flags: `--no-odds` (model lines only), `--lines-file overrides/manual_lines.csv`
(type lines in yourself), `--bankroll 2500`, `--min-ev 0.03`, `--config my.json`
(see `config.example.json`).

### Overrides (the part that matters most)

The model is only as good as what it knows about who is playing. The files in `overrides/`
have instructions at the top:

* `starters.csv` — force the starting QB. Use it for benchings, rookies and anything the
  injury report doesn't capture. A QB with no NFL history gets a replacement-level value.
* `player_status.csv` — OUT/DOUBTFUL/QUESTIONABLE/IN or a 0–1 probability for any player.
* `manual_lines.csv` — prices typed in by hand if you don't use The Odds API.
* `my_bets.csv` — log each bet; `python clv_report.py` scores it.

## How a line is made

1. **Features.** 59 for the spread model and 39 for the total model, in 14 factor groups (table below).
2. **Model.** Ridge regression (heavily regularized, recent seasons weighted more) blended
   with a small gradient-boosted tree model for interactions. Every factor stays in; the
   data decides how much each one counts. The line sheet shows each group's contribution.
3. **Fair line.** `fair = w × model + (1 − w) × sharp consensus`, where the consensus is
   the median of Pinnacle, LowVig, BetOnline, Novig and ProphetX, and `w` comes from the
   backtest. Starting values are 30% model weight until you calibrate.
4. **Prices.** The fair line is converted to win/push/lose probabilities with a
   distribution that respects key numbers (3, 7, 6, 10, 4 for spreads; 41, 43, 44, 37,
   47 for totals).
5. **Edge and stake.** `EV = p_win × (decimal − 1) − p_lose`. Plays are flagged at
   ≥ `min_ev` (default +2%), staked at quarter Kelly, capped at 2% of bankroll.
   A "check news" flag appears when the model and market disagree by 4+ points —
   that is usually information the model lacks, not an edge.

### Factors

| Group | What's in it | Source |
|---|---|---|
| Home field | Home/neutral, team-specific and time-varying home edge, division games, playoffs | nflverse schedules |
| Team strength | Opponent-adjusted offense/defense ratings (points, pass/rush EPA, success rate), decayed by recency, regressed each offseason; Elo | play-by-play |
| Scheme matchup | Pass rate over expected, pace, no-huddle, shotgun; offense-vs-defense matchup EPA | play-by-play |
| Quarterback | Projected starter's value vs league and vs the team's baseline; backup value weighted by play probability; new-QB flag | play-by-play, rosters, injury report |
| Injuries | Snap-weighted share of regular OL, WR, TE, RB, DL, LB, DB missing | snap counts, injury report, overrides |
| Rest & travel | Rest days, byes, short weeks, miles traveled, time-zone shift, international games, road streaks | schedules, stadium table |
| Time of day | Kickoff in each team's body-clock hours, early West Coast kickoffs, prime time, Thu/Mon/Sat | schedules |
| Weather | Temperature, wind, rain, snow; dome and warm-weather teams in cold | Open-Meteo forecast / historical records |
| Surface & altitude | Turf vs grass, surface mismatch vs home field, altitude | stadium table, schedules |
| Coaching | Coach record vs the spread (shrunk), tenure, first-year coaches, 4th-down aggressiveness | schedules, play-by-play |
| Officials | Referee crew margin/total tendencies and penalty rate (shrunk hard) | schedules, play-by-play |
| History | Head-to-head and home/road results vs the line (shrunk hard) | schedules |
| Situational | Previous margin, overtime last week, look-ahead to next opponent, early season | schedules |
| Scoring environment | League scoring level, early-season and playoff effects on totals | schedules |

"Shrunk" means small samples are pulled heavily toward zero, so a referee with a few
odd games doesn't move a line. Many of these groups (officials, history, coaching
ATS) will show close to zero value in the backtest — the market already prices them.
That's expected, not a bug.

### Situational factors: what the research says (checked September 2026)

| Factor | What history shows | How the model uses it |
|---|---|---|
| Rain at kickoff | Totals went under 57.4% of the time with measurable rain at kickoff (Sharp Football, 343 games) | Forecast rain and snow features in the total model |
| Wind | 15+ mph disrupts passing and kicking | Wind above 10 and 15 mph, wind × passing matchup |
| Rest gaps | 4+ day gaps have been worth about 2 points, but closing lines price most of it (about 0.45 points missed); rested teams facing a Monday-night team covered only 51.8% | Rest difference, bye and short-week flags |
| Body clock | West Coast teams at 1 p.m. ET lost about 3 points historically, and books move lines by about the same | Local-hour body-clock features |
| Winless and unbeaten starts | 0-2 teams covered 55.7% in Week 3 since 2003: the market overreacts to early records | New: `d_winless`, `d_unbeaten` |
| Record vs point differential, ATS and O/U streaks | The same overreaction story: records that outrun scoring margin, and hot ATS or over teams, get overpriced | New: `d_record_luck` (Pythagorean), `d_ats_form`, `sum_ou_form` |
| Games after an overseas trip | Samples are small (17 teams since 2016 played the week after Europe) | New: `d_post_intl`, `sum_post_intl` (neutral-site proxy) |
| QB changes and injuries | By far the biggest line movers | Starter projection and snap-weighted absences |

Every new feature is regularized and must earn its weight in `backtest.py --ablation`; most situational
angles will come back close to zero because the closing line already prices them.

### Round 3 factors (added after another research pass)

| New factor | What the research says | Features |
|---|---|---|
| Weighted EPA | nfelo's WEPA discounts plays that swing games randomly (lost fumbles) and weights close-game plays more; it beat raw EPA and DVOA at predicting future margin, and works best with separate offense and defense weights (an interception says more about the passer than the coverage) | `d_wepa_net`, `sum_wepa` (new rating targets `wepao`, `wepad`) |
| Market-implied team ratings | Preseason priors from the betting market improve predictions all season, not just early (TeamRankings; ESPN's FPI builds its preseason ratings mainly from win totals). The same prior is rebuilt here from every team's previous closing spreads and totals | `d_mkt_rating`, `mkt_total_pred` |
| QB accuracy (CPOE) | The EPA + CPOE composite is among the most predictive public QB measures, and CPOE is very stable year to year | `d_qb_cpoe`, `sum_qb_cpoe` |
| Pass-rush matchup and sack luck | Pressure is frequent and stable; sacks are rare and lucky. Pass rush (sacks + QB hits per dropback) is matched against the opponent's protection, and sacks above what the pressure implies are treated as luck | `d_press`, `sum_press`, `d_sack_luck` |
| Third-down luck | Third-down conversion rate regresses heavily; early-down success is the stable signal, so third-down rates above what early downs imply are faded | `d_3rd_luck`, `sum_3rd_luck` |
| Empty stadiums (2020) | Home teams went 127-128-1 in 2020, the first losing home record in NFL history; a flag keeps that season from teaching the model a permanent home-field collapse | `home_no_fans` |

These need the extra play-by-play columns `wp`, `third_down_converted` and `third_down_failed`,
which are now downloaded with the rest. On the synthetic demo league, adding them cut the model's
out-of-sample miss from 11.82 to 11.69 points on spreads and from 12.07 to 11.89 on totals
(closing lines: 11.12 and 11.56). That is only a smoke test; run
`python backtest.py --ablation` on real data to see which groups earn their weight.

### Round 4: closing the gap to the market

| Change | Why | Where |
|---|---|---|
| Error-weighted market regression | nfelo showed a model blended with the market beats both, and that scaling the blend by how accurate the model has recently been *for these two teams* (vs the market) improves it again | `nflmodel/regress.py`; `backtest.py` tunes the half-life and scale on earlier seasons, tests them on the last one, and only turns it on if it helps; `run_week.py` then gives every game its own model weight (`weight_margin`, `weight_total` in the projections CSV) |
| Game-specific outcome spread | The same expected margin is less certain in a higher-scoring game, and the spread of outcomes varies game to game; cover probabilities now come from a distribution whose width scales with the expected total | exponents `sd_total_alpha` / `sd_total_beta` fitted in `backtest.py`, applied in `pricing.py` |
| Automatic factor pruning | Extra factors that carry no signal add noise; `backtest.py --ablation` now drops the most harmful groups one at a time, keeps a drop only if the combined miss falls, and never prunes the core groups (team strength, home field, QB, injuries, weather) | `drop_groups_margin` / `drop_groups_total` in `artifacts/calibration.json`, used by `run_week.py` |
| Drive efficiency | Per-game points reward pace and per-play stats hide finishing; the drive is often the right unit of offense | new rating targets `ppd`, `drv`; features `d_ppd_net`, `ppd_total_pred`, `drives_total` |
| Scoring calendar | Scoring sags in November and in December/January weather | `wk_nov`, `wk_dec` |
| Late-season motivation | Evidence is mixed (favorites in "motivation" spots went 45-45-2 over 11 seasons; a published spoiler system claims 61% for eliminated underdogs of 7+), so these are proxies for the backtest to judge; known rest decisions still belong in the overrides | `d_elim`, `d_rest_risk`, `sum_elim` |

On the synthetic demo league: error-weighted regression lowered the blended forecast's RMSE on the
held-out season from 15.32 to 15.27 (spreads) and 15.29 to 15.26 (totals); pruning cut the linear
model's spread miss from 12.01 to 11.67 against a closing line of 11.46 (optimistic, because the
groups were chosen on the same seasons). The new drive, calendar and motivation groups did not help
there, which is expected because the fake league doesn't simulate those effects; on real data the
ablation decides whether they stay.

### Round 5: venue history and tuning

**Venue history** (group `venue_history`, judged and pruned by `backtest.py --ablation` like every
other non-core group): the home team's record against the spread at its own stadium over up to six
seasons (`venue_hfa_resid`), the visiting team's and visiting head coach's past results at this
stadium (`venue_away_resid`, `venue_away_coach_resid`), each projected QB's EPA per play at this
stadium compared with his EPA everywhere else (`d_qb_venue`, `sum_qb_venue`), and the stadium's own
scoring against the closing total (`venue_total_resid`, a football "park factor"). All are shrunk
hard toward zero because the samples are tiny: outside the division a team visits a given stadium
only every few years, so one QB may have two or three games there in a career. Published work
points the same way. Team-specific home-field edges have tended not to last (Seattle, Baltimore and
New Orleans all fell back to average), Denver shows no durable edge despite the altitude, and books
already bake team-specific home field into their spreads. On the synthetic league the group
changed the out-of-sample miss by less than 0.03 points.

**Tuning** (`python tune.py`): tries a few values of the settings that control how fast team ratings
and QB values react and how much carries over between seasons, one at a time, and saves the best
to `artifacts/tuned_config.json` (use it with `--config`). Each try rebuilds every feature, so on
real data expect it to take a while; run it once in the offseason or on a quiet weekday.

### Round 6: one-command optimization

`python optimize.py` now re-optimizes everything in order, and `run_week.py` picks up the results:

1. **Tuning** (`tune.py`): the rating and QB memory settings, walk-forward, saved to
   `artifacts/tuned_config.json` and used automatically by `backtest.py` and `run_week.py`.
2. **Pruning, now on by default and checked on unseen data**: factor groups are ranked and dropped
   on all backtest seasons except the last, then the drop is kept only if the last season agrees.
   Core groups (team strength, home field, QB, injuries, weather) are never dropped.
3. **Boosting weight per market**: the backtest keeps the ridge and gradient-boosting predictions
   separately and picks the mix for spreads and totals on earlier seasons, falling back to pure
   ridge if the last season disagrees (`gbm_weight_margin`, `gbm_weight_total`).
4. **Blend, game-by-game blend, outcome spread and line movement**, as before, on the final
   out-of-sample predictions.

`python backtest.py --no-optimize` skips steps 2-3 when you only want a quick check.

On the synthetic league (same league as rounds 4-5, 2023-2026 backtest), this took the spread
model's miss from 12.01 to 11.75 against a closing line of 11.46, and totals from 12.35 to 12.24
against 11.87. The blended spread line (11.43, with 14% model weight) came in slightly under the
closing line for the first time; totals blended to the market (11.87). The last backtest season in the demo league has only
three weeks, so treat the held-out checks there as thin; on real data every season is complete.

### What's left between the model and the market

After five rounds, the remaining gap is mostly things a public-data model can't see or can't
measure well: injury and lineup news before it's public, how sharp money is positioned, player-level
grades behind paywalls, and plain randomness (a closing line still misses by about 10 points on
average). The practical levers from here are timing (re-run after Friday injury reports and ~90
minutes before kickoff when inactives post), keeping your own DraftKings line history so the
movement model can learn, and letting the backtest keep only what earns its place.

### How close to Vegas is "close"

Across 7,276 games since 1999 the closing spread missed the final margin by 10.3 points on average
(standard deviation 13.2) and was almost exactly unbiased. That is the bar: `backtest.py` reports the
model's MAE next to the closing line's. A model within a few tenths of a point of the close is doing
very well; beating it consistently is what professional bettors spend careers chasing, and the blend
weight in `artifacts/calibration.json` is how the pipeline decides how much to trust the model.

## How sportsbooks make and move lines (and what the model copies)

* **Who sets the number.** A few market-making books (Pinnacle, Circa, Bookmaker) build openers from
  power ratings plus home field, injuries, travel, rest and form, and post them with low limits so
  sharp bettors can correct them. Retail books such as DraftKings mostly follow those prices with a
  delay. The model does the same thing: team power ratings plus adjustments, blended with the sharp
  consensus by a backtest-estimated weight.
* **How lines move.** NFL numbers usually open Sunday night or Monday and react first to sharp money;
  midweek moves come from injury reports, QB decisions and weather; late-week money from the public
  lands on favorites and overs. Limits rise through the week, and the closing line is the most
  efficient number, which is why CLV is the scorecard.
* **Where soft books lean.** Bookmakers have long shaded prices toward what the public likes: big
  favorites, road favorites and overs on high totals draw a disproportionate share of bets, and
  betting against lopsided public sentiment has been profitable on spreads (not totals).
* **What moves a line most.** A starting QB: oddsmakers value the best starters at close to 7 points
  over their backups, and the market sometimes overreacts to QB changes.

### Line movement and timing

`nflmodel/movement.py` learns how far lines move from open to close given how far the model
disagreed with the opener, then labels each DraftKings offer **Bet now** (the line is likely to move
against you) or **Can wait**. It needs opening lines:

1. download a historical opening/closing line spreadsheet for personal use (Australia Sports
   Betting's free NFL file has open, min, max and close for spreads and totals) and save it as
   `data_cache/line_history.xlsx`, and/or
2. keep running `run_week.py` a few times a week: every run saves DraftKings' prices to
   `artifacts/odds_snapshots/`, which becomes your own DraftKings open/close history.

`backtest.py` fits the movement model automatically when history exists, reports how often it
predicts the direction of the move and how much CLV betting the model's side at the open would have
captured, and saves `artifacts/movement.json`. Until then, timing falls back to the research
defaults: favorites and overs earlier, underdogs and unders later.

### New luck and special-teams features

Fumble recoveries are close to coin flips and turnover margins regress hard, while pressure is more
stable than sacks. The model now tracks, season to date and shrunk toward zero: fumble-recovery luck
(`d_fum_luck`), turnover margin (`d_to_margin`) and net special-teams EPA (`d_st_epa`). They come
from extra play-by-play columns (interception, fumble, fumble_lost, sack, qb_hit, special_teams_play,
cpoe) that are now downloaded with the rest.

## Judging it honestly

* **The closing line is the benchmark.** A model that doesn't beat the close in the
  backtest has no edge, however clever it looks. Expect it to be close to the market,
  not better by much — NFL lines are very efficient, and DraftKings follows the sharp books.
* **Track closing-line value (CLV), not win rate.** `python clv_report.py` compares every
  logged bet with the close. Consistently getting better numbers than the close is the
  best evidence of an edge; profit over 100–200 bets is mostly luck.
* **Break-even at −110 is 52.4%.** Edges in this market are small, so bet small.
* Most real edges come from being early to news (injuries, QB changes, weather) — which
  is why the Friday and Sunday re-runs matter.

This is a tool for your own analysis, not financial advice. Bet only what you can afford
to lose, and check that sports betting is legal where you are.

## Known limitations

* nflverse's current-season injury feed is sometimes late or broken. The pipeline
  notes this in the report and keeps going; fill `overrides/player_status.csv` yourself.
* Week 1 has no current-season snaps, so "regular starter" is taken from last season.
* The model can't see motivation, resting starters in late-season games, or a coordinator
  change mid-season. Use the overrides or skip those games.
* Retractable roofs are assumed closed for upcoming games.
* Backup-QB quality relies on limited snaps; rookies and journeymen get a replacement-level prior.

## Troubleshooting

* **"Could not load nflverse data"** — no internet or a source change. Try
  `pip install -U nflreadpy`; the cached copy in `data_cache/` is used when present.
* **"The Odds API rejected the key"** — check `ODDS_API_KEY`. Each pull uses 6 credits with the default 13 books.
* **A game has "no market"** — the book hasn't posted it yet, or team names didn't match;
  try again later or add it to `manual_lines.csv`.
* **Slow first run** — the play-by-play download; later runs use the cache.

## Files

```
run_week.py      weekly projections + DraftKings comparison
backtest.py      walk-forward test, calibration, factor ablation
clv_report.py    closing-line value and P/L for your logged bets
pfr_check.py     check nflverse results against Pro Football Reference files you saved
tune.py          walk-forward tuning of rating and QB memory settings
optimize.py      tune + backtest + prune + calibrate in one command
CLAUDE.md        short instructions for Claude Code; full context in docs/PROJECT_HANDOFF.md
site/week4_2026/ the Week 4 picks website generator (hand-captured odds snapshot)
nflmodel/        config, data, venues, ratings, availability, features, model,
                 pricing, odds, weather, report, synthetic (demo), pipeline
overrides/       your weekly inputs
pfr_exports/     optional Pro Football Reference season tables
config.example.json
```
