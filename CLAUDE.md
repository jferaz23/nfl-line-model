# NFL line model

Python pipeline that sets its own NFL spreads/totals each week, prices them, and compares them with
DraftKings (the user's only sportsbook) to flag +EV bets. Full context, research, results and backlog:
`docs/PROJECT_HANDOFF.md` (read it before larger changes). User-facing guide: `README.md`.

## Commands
- Smoke tests (no internet): `python run_week.py --demo`, `python optimize.py --demo --quick`
- Real data: `python optimize.py` (tune + backtest + prune + calibrate), then `python run_week.py`
- Quick backtest: `python backtest.py --no-optimize`; CLV: `python clv_report.py`
- Week 4 site: `python site/week4_2026/site3.py` -> `reports/site/week4_picks.html`
- Syntax check: `python -m py_compile *.py nflmodel/*.py`

## Rules
- DraftKings prices come from The Odds API (`draftkings` key). Never scrape DraftKings or Pro Football
  Reference; PFR data only from files the user saves in `pfr_exports/`.
- Never invent real-week picks or results; keep synthetic output labeled as demo data.
- Features must be as-of kickoff (no information from the game itself or later games).
- New factors: shrink toward zero, put them in a feature group, and let `backtest.py` pruning judge
  them. Never prune the protected groups (team_strength, home_field, quarterback, injuries, weather).
- Pass rule (set Oct 21, 2026; the user asked Claude to choose the best rule and decide). Objective = the bets the site
  recommends: green picks (incl. Top) and the weekly card. A model or pick-rule change goes live only if, vs the current
  live model on the same data: (1) green units AND green win rate are higher overall, and green units are higher in
  2021-26 (settings are always chosen on 2015-20 only); (2) no quality measure gets worse: Top win rate, Top return per
  bet, weekly-card win rate and spread MAE are not worse (total Top units may fall only when Top picks get fewer but
  better; those picks still count as green); (3) not luck: the gain shows up in >= 3 of 4 pure-noise model versions;
  (4) the official production backtest (optimize.py --skip-tune) confirms it. State the rules in the research log before
  each test. Noise reference: a random factor moves spread MAE by -0.005..+0.006 and Top units by up to 36u.
- pandas 2.x/3.x compatible: `.loc` assignments, no chained assignment, avoid `groupby.apply`.
- Run the demo commands after changes; they exercise the whole pipeline on the synthetic league.
- User-facing text: plain language, honest about small edges, "information only, not financial advice".

## Status (Oct 6, 2026)
Backtest 2015-2026 (3121 games; 2015 uses ridge only, too little history for boosting): spread MAE
model 9.89 vs close 9.79, fair-line blend 9.78 (model weight 22%); totals 10.57 vs 10.45 (weight 5%). Boosting weight
spreads 0%, totals 10%. ATS at 4+ pts disagreement 56.9% (n=269), 3+ pts 55.8% (n=548). Widened tuning (tune.py --first 2019 --last 2024) found gains of ~0.005:
kept the validated settings in artifacts/tuned_config.json.
Picks (nflmodel/picks.py, one rule for live and history): model's side of the number; chance = walk-
forward hit rate by disagreement band (0-2, 2-4, 4+), shrunk to 50%, monotone; green = chance >=
break-even + 1pt and chance >= 51%; Top pick = any spread with a 4+ pt edge, always shown green (since Oct 2, 2026;
before, Top also had to pass the green test, which made it jumpy). Track record since 2015 at closing prices (chance rated
on non-QB-caution games, with the market blend and agreement filter below): Top 153-114-10 (57.3%, +29.1u), green incl. Top 465-346-19
(57.3%, +94.2u); weekly card 502-359-14 (58.3%, +97.5u).
Market ratings (features._add_market_ratings, Oct 6, 2026, Test 41): half-life 2.5 weeks, penalty 0.1 (were 6 / 3.0), and
the spread rating shifted by 0.75 x (this week's projected QB value - the QB value the earlier lines priced). Production
spread MAE 9.9649 -> 9.9454 (2015-20 -0.026, 2021-26 -0.013), totals 10.5861 -> 10.5689 (both halves); pick signal
corr(model-close, result-close) 0.032 -> 0.046 (noise runs move it ~-0.001). Rejected the same day: blend weight by week
of season; Top cutoff 3 (failed the perturbation check across model versions); finer chance bands.
Injury-adjusted market ratings (Test 50, Oct 6): missing regular starters valued per player (features.MKT_INJ_PTS, fit
2015-20, capped at 0: OL -0.78, WR -1.48, RB -0.91, LB -1.49, DB -0.77, TE/DL 0); spread rating shifts by the gap vs what
the lines priced. Spread MAE 9.9327 -> 9.9210 (-0.012 both halves), green 294-253 +31.4u -> 428-352 +57.6u, Top +38.0u ->
+28.1u (inside noise); 2021-26 alone (not used for the fit): Top 76-58 -> 81-61, green 105-93 +7.0u -> 212-171 +28.1u,
signal 0.033 -> 0.042. Rejected: blend weight 0.55 (Top -30u), totals QB adjustment (-0.0035), dropping QB caution.
Agreement filter (picks.split_view, Oct 21, Test 70): a spread is green/Top only if the raw model estimate and the
market-ratings forecast (d_mkt_rating) are both on the pick's side of the line (raw = (model - 0.45 m)/0.55). Split green
picks went 20-25 (2015-20) and 6-13 (2021-26); green 491-384 +81.8u -> 465-346 57.3% +94.2u, Top 153-114 +29.1u; won in 4/4
noise versions. backtest_oos.csv and the week payload now carry d_mkt_rating.
Market blend weight raised to 0.45 (Oct 20, Test 59, chosen on 2015-20; 0.35-0.55 all pass): spread MAE 9.9076 -> 9.8887
(2015-20 -0.029, 2021-26 -0.009), green 432-353 +60.2u -> 491-384 +81.8u (2021-26 +31.7u -> +49.0u), Top +28.8u -> +27.1u;
on 4 noise versions green rose 4/4 and Top fell 4/4 (-5..-12u). Rejected Oct 20: Top cutoff 4.5/5, QB_DOWN -3 (2 of 4 noise
versions), health-neutral market ratings.
Market blend (config.mkt_blend_margin, model.LineModel._blend, Oct 2, 2026 at 0.25): spread prediction = 75% model + 25% the
market-implied ratings forecast (d_mkt_rating, earlier weeks' closes). At adoption spread MAE 9.9816 -> 9.9649 (2015-20 -0.022, 2021-26
-0.010); passed the noise-aware rule. Margin cap +/-28 also passed alone but failed combined (units beyond noise).
Questionable starting QB (features.QB_Q_START): last week's starter listed Questionable starts 57% (DNP 37 / limited 53 /
full 85%, 211 cases 2013-2025); his value is blended with the backup's at those odds (live only).
Injury odds (config.status_play_prob, measured 2013-2025): QUESTIONABLE 0.66, DOUBTFUL 0.01; QUESTIONABLE by last practice
on the final report DNP 0.42 / limited 0.68 / full 0.79 (availability.play_prob; midweek practice is not used).
Early-week value (build_site.early_value, Picks tab, information only): the week's first model run, spreads 3+ pts off
DraftKings, graded at that line/price; tracked from 2026 week 4 (backtest vs openers 56-59%, unproven at DK).
Pick log: always read it with picks.read_log (it repairs 288 rows from Sept 30 written one column off).
Live picks logged to artifacts/tracker/picks_log.csv; build_site.build_record merges them.
Picks lock at kickoff (Oct 20, 2026, user request): run_week.py makes no picks, teaser legs or wind calls for games already
started (teaser legs carried over from the previous run); build_site.fill_started replaces any started game's picks with
its last pre-kickoff log row. In-game lines never create picks. Bets tab 2026 week-by-week = picks as shown at kickoff
(weeks the log covers, from week 4) incl. wind; weeks 1-3 backtest at the close (record.by_week[].at_kickoff).
Data audit (audit_data.py) runs weekly; see Info tab.
QB caution (picks.qb_caution): a green pick under the Top line that backs a team with a new (<100 plays) or
2+ pts/game downgraded QB is not green (such picks went ~50% in both halves). QB downgrade *features* were
tested and rejected (no gain). Win totals (nflmodel/wintotals.py, group "win_totals"): read only from pages
the user saves into win_totals/ (Sports Odds History / Genius Sports; no scraping), exported to
win_totals/win_totals.csv; inert until then, and must pass the backtest before it counts.
Alerts: build_site.alerts() -> site Alerts tab (pick green/Top/wind on-off with the reason, DraftKings line moves),
badge + browser notifications while open (polls site.js every 5 min); notify.py pushes pick changes to ntfy only
if the NTFY_TOPIC secret exists (state artifacts/alerts_sent.json); line moves go as one combined low-priority push per run.
Site extras (Oct 6, 2026, display only, no model change): installable app (web/manifest.webmanifest, sw.js network-first,
web/icons), phone bottom tab bar + More sheet, "Bet now" panel on Picks, one-tap "Log bet" (localStorage, auto-graded,
"Export for Claude" -> bet_slips.csv rows), Bets tab stats (by source, CLV vs DK close, running profit), #recap, #tools
(parlay calculator with boost + model EV, fractional-Kelly sizing capped 3%, follow teams), team-color cards, followed
games first, scroll memory per tab, Alerts settings (Top-only / followed teams for browser alerts). notify.py also posts to
<topic>-picks and <topic>-top; overrides/alerts.json holds line-move quiet hours (0-7 ET). build_site fills kickoffs from
the pick log (games no longer in a saved run) and parses timestamps with format="ISO8601".
Personal P&L: overrides/bet_slips.csv (source/game_id/market/side/line per slip) -> build_site.my_pnl (by_source, clv, cum).
Site tabs: How it works (#how, web/app.js renderHow) explains the method with live numbers; game cards show the week's
opening line -> now (the weekly opener = first logged line; ESPN's 'open' is the line first posted months earlier).
Wind tab (#wind, app.js renderWind): rule, this week's outdoor forecasts, 2026 wind unders at kickoff, history.
When to bet (build_site.bet_timing -> site.timing, Picks tab timingPanel): from the pick log, bet-when-first-green vs bet at the
last pre-kickoff update; week 4-6 2026: first-green 15-10, at-kickoff 8-3, dropped-by-kickoff 7-7, early line -0.14 pts.
Rejected Oct 20: green threshold 2-4 pts / chance 52-53% (current best on 2015-20), SHRINK 400 (worse 2021-26), health-neutral
market ratings (Test 55: MAE -0.0045, green -17u).
Suggested parlays (app.js parlayIdeas, Picks + Tools tabs): best 2-/3-leg combos of Top/green/wind picks (one leg per game,
not started), ranked by model value at standard parlay odds, filter spreads/totals, "Open in calculator".
Rejected Oct 20 (evening): totals market blend (2021-26 worse), weather-neutral market totals (-0.001), per-team home field
in the market ratings (MAE -0.007 but green -28.9u).
Rejected Oct 21: Top cutoff 3.5 (2015-20 +35.4u vs +17.9u and 4/4 noise wins, but 2021-26 +6.1u vs +9.1u; re-check later),
ratings-memory ensemble 3/5/9 wk (MAE +0.001, green -13.9u). Diagnostic: green picks by type (dog/fav, home/road, key
numbers, division, primetime, season phase) are positive in both halves; no filter justified.
Rejected Oct 21 (after the agreement filter): key-number cover-probability bands, logistic chance curve, consensus edge,
curve fit without split games (1/4 noise), third-opinion filters (Elo/points/EPA disagreeing greens profitable both halves),
market QB adj 0.5/1.0 and injury x0.75/1.25 inside the full model, teaser/wind filters by model agreement (inconsistent
halves). Calibration: green spreads' shown chance runs 2-4 pts below their actual win rate (53.3% vs 55.6%, 54.6% vs 58.6%).
External-factor research Oct 21 (literature: market broadly efficient; small time-varying biases): ML-vs-spread
inconsistency (Fodor et al. 2012; corr +0.035/+0.038 both halves, but as a pick adjustment green -27.6u, 0/4 noise -> no;
Top improved +9.5u, a lead to re-check), juice skew (flips between halves), week 1-2 holdover bias (flips), DK vs sharp
books (Pinnacle/LowVig/BetOnline/Novig/ProphetX are already in every odds snapshot; 13 differing games 4-7 so far, re-test
at season end).
Rejected Oct 21 (late): ESPN QBR as a second QB rating (corr 0.87 with the QB value; green -15.4u), Top by ML-adjusted
edge (Top +9.5u but green -3.6u, 0/4 noise), salary-weighted missing starters via nflverse contracts (green -38.7u).
College football: separate project at Desktop/cfb-line-model (own repo/site; brief in its CLAUDE.md).
Site design (Oct 22, 2026, user's pick): Spotlight layout on the Glass Field palette (web/theme.css, web/layout.css,
web/layout-kit.js builds the pick-of-the-week card from SITE; only games not yet started). Other designs: web/preview/.
Player props research (Oct 22): ESPN core API has DraftKings prop LINES free (provider 100; 2024-25 ESPN BET = provider 58,
main line = most common opening line per player/market), no prices. Projection model (nflverse weekly stats, walk-forward
GBM) vs lines 2024-26: line MAE beats the projection in nearly every market; green props failed the pre-stated rule (2025
52.2% -61u at -115; yardage markets z>=0.5 2025 51.5%, 2026 49.3%); apparent edges sit in pass TDs/receptions where unseen
juice is skewed. Not recommended; info-only tracker at most. Props v2 (role-change features: vacated targets/carries from snap counts,
share of remaining volume, short-term form) also failed: green 2025 53.3% -4u, 2026 53.0% -6u, noise 1-2/4; yardage z>=0.5
48.8%/48.6%. Leads only: big-edge unders (66%/56%/52% 2024-26) and pass TDs/receptions (need real prices to judge).
Props tab (Oct 23, INFORMATION ONLY, user-approved plan): props_run.py + nflmodel/props.py (v2 role-change projections;
vacated volume live from ESPN's injury list + nflverse; history from snap counts), .github/workflows/props.yml (daily 9 AM
ET, Thu/Mon pre-primetime, Sunday 11 AM ET with --prices). Flag = |z| >= 0.5; categories pass_tds, receptions, under,
over. Real DraftKings prices from The Odds API (event odds, DK only, ~1 credit per market per event) only for flagged
leads, only from 2026-10-31 and while >= 250 credits remain. Outputs artifacts/props/ (week.json -> site.props, props_log.csv,
props_graded.csv, backtest_curve.json). Props become green picks only if the priced live test holds up. Research scripts: scratchpad night/props_*.py (cache in
nfl_data_cache/props).
Kalshi (kalshi_watch.py, every update run): public NFL game/spread/total prices -> artifacts/kalshi/kalshi_nfl.csv;
logging only, not in the model until it passes a backtest (history starts Sept 30, 2026).
Opening-line history: data_cache/line_history.xlsx (user download, personal use, never committed).
Wind unders (nflmodel/wind.py, confirmed by the user Sept 30, 2026): outdoor game, kickoff forecast
(kickoff to +3 h) wind 10+ mph or gusts 20+ mph -> under, if the price leaves 1+ pt of value (same test
as green). Chance = forecast-rule record shrunk (SHRINK 200). History artifacts/wind_history.csv from
Open-Meteo's Historical Forecast API (wind/gust archive from 2018; 2016-17 null); retractable roofs
excluded like live. Record 2018-26 225-166-4 (57.5%, +44.0u); 2018-21 (not used to choose the rule)
103-88-2 (+9.9u); all outdoor unders 52.3%. Live pick is final at the ~80-min pre-kickoff run.
optimize.yml runs `python -m nflmodel.wind --update` weekly.
Missing skill-player value (WR/TE/RB EPA) was tested in the production backtest and rejected (Sept 30,
2026): MAE -0.007 but Top -16.7u and green -23.9u; see docs/PROJECT_HANDOFF.md section 10.
Next Gen Stats team offense (RYOE, separation, YAC over expected; last 8 games) rejected the same day:
MAE +0.007, Top -9.9u, green -16.3u.

Automation (GitHub jferaz23/nfl-line-model, Pages https://jferaz23.github.io/nfl-line-model/):
- `update.yml` every 15 min: scheduler.py picks the mode. api = run_week.py with The Odds API
  (mandatory at injury reports Wed-Fri ~4:30 PM ET and ~80 min before every kickoff; otherwise paced
  from artifacts/odds_budget.json so the credits last until the quota refills, reset date learned);
  espn = run_week.py --espn-lines (free, every 3 h); reprice = reprice.py (DraftKings line from ESPN).
  Then line_watch.py, build_site.py, commit, deploy. `optimize.yml` recalibrates Tuesdays.
- Weekly card = Top picks + 2-team underdog teasers (+1.5..+2.5 teased 6; picks.teaser_*) + wind unders.
- Site: web/ (no build step) + public/data/site.js. Live scores/Gamecast poll ESPN from the browser
  every 15 s during games (display only; never touches the model or credits).
Local: `config.json` (gitignored) keeps the data cache outside OneDrive; use `--config config.json`.
`run_week.py --odds-snapshot latest` re-prices from a saved snapshot without spending credits.
