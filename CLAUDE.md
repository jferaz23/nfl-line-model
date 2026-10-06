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
- Pass rule for model changes (user-approved Oct 2, 2026), vs a fresh baseline on the same data: pruning keeps
  the group; spread MAE improves by more than the noise floor (0.006 pts) and in both halves (2015-20, 2021-26);
  Top/green units no worse than the noise range (not "not lower"). Noise floor = 20 runs adding a pure random
  factor: spread MAE change mean +0.002, sd 0.003, range -0.005..+0.006 (2 of 20 improved both halves by chance);
  Top units fell in 19/20 runs (mean -8.6u, min -36u), green in 16/20 (mean -11.4u). Pick-rule changes are judged
  on the pick record itself, with the same perturbation check.
- pandas 2.x/3.x compatible: `.loc` assignments, no chained assignment, avoid `groupby.apply`.
- Run the demo commands after changes; they exercise the whole pipeline on the synthetic league.
- User-facing text: plain language, honest about small edges, "information only, not financial advice".

## Status (Oct 6, 2026)
Backtest 2015-2026 (3092 games; 2015 uses ridge only, too little history for boosting): spread MAE
model 9.92 vs close 9.80, fair-line blend 9.79 (model weight 18%); totals 10.57 vs 10.45 (weight 7%). Boosting weight
spreads 0%, totals 20%. ATS at 4+ pts disagreement 56.5% (n=299), 3+ pts 57.6% (n=621). Widened tuning (tune.py --first 2019 --last 2024) found gains of ~0.005:
kept the validated settings in artifacts/tuned_config.json.
Picks (nflmodel/picks.py, one rule for live and history): model's side of the number; chance = walk-
forward hit rate by disagreement band (0-2, 2-4, 4+), shrunk to 50%, monotone; green = chance >=
break-even + 1pt and chance >= 51%; Top pick = any spread with a 4+ pt edge, always shown green (since Oct 2, 2026;
before, Top also had to pass the green test, which made it jumpy). Track record since 2015 at closing prices (chance rated
on non-QB-caution games, with the market blend below): Top 169-130-12 (56.5%, +28.1u), green incl. Top 428-352-19
(54.9%, +57.6u; totals 10-5-1), all spreads 51.3% (-18.7u); weekly card 514-371-16 (58.1%, +97.0u).
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
Market blend (config.mkt_blend_margin 0.25, model.LineModel._blend, Oct 2, 2026): spread prediction = 75% model + 25% the
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
