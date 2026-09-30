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
- pandas 2.x/3.x compatible: `.loc` assignments, no chained assignment, avoid `groupby.apply`.
- Run the demo commands after changes; they exercise the whole pipeline on the synthetic league.
- User-facing text: plain language, honest about small edges, "information only, not financial advice".

## Status (Sept 29, 2026)
Backtest 2015-2026 (3076 games; 2015 uses ridge only, too little history for boosting): spread MAE
model 9.98 vs close 9.82, blend 9.81 (weight 10%); totals 10.59 vs 10.45 (weight 2%). ATS at 4+ pts
disagreement 57.6% (n=415). Widened tuning (tune.py --first 2019 --last 2024) found gains of ~0.005:
kept the validated settings in artifacts/tuned_config.json.
Picks (nflmodel/picks.py, one rule for live and history): model's side of the number; chance = walk-
forward hit rate by disagreement band (0-2, 2-4, 4+), shrunk to 50%, monotone; green = chance >=
break-even + 1pt and chance >= 51%; Top pick = green spread with 4+ pt edge. Track record since 2015
at closing prices (chance rated on non-QB-caution games): Top 170-122-7 (58.2%), green 326-267-16 (55.0%, +51.3u), all spreads 51.8%.
Live picks logged to artifacts/tracker/picks_log.csv; build_site.build_record merges them.
Data audit (audit_data.py) runs weekly; see Info tab.
QB caution (picks.qb_caution): a green pick under the Top line that backs a team with a new (<100 plays) or
2+ pts/game downgraded QB is not green (such picks went ~50% in both halves). QB downgrade *features* were
tested and rejected (no gain). Win totals (nflmodel/wintotals.py, group "win_totals"): read only from pages
the user saves into win_totals/ (Sports Odds History / Genius Sports; no scraping), exported to
win_totals/win_totals.csv; inert until then, and must pass the backtest before it counts.
Opening-line history: data_cache/line_history.xlsx (user download, personal use, never committed).
Wind unders (nflmodel/wind.py, confirmed by the user Sept 30, 2026): outdoor game, kickoff forecast
(kickoff to +3 h) wind 10+ mph or gusts 20+ mph -> under, if the price leaves 1+ pt of value (same test
as green). Chance = forecast-rule record shrunk (SHRINK 200). History artifacts/wind_history.csv from
Open-Meteo's Historical Forecast API (wind/gust archive from 2018; 2016-17 null); retractable roofs
excluded like live. Record 2018-26 225-166-4 (57.5%, +44.0u); 2018-21 (not used to choose the rule)
103-88-2 (+9.9u); all outdoor unders 52.3%. Live pick is final at the ~80-min pre-kickoff run.
optimize.yml runs `python -m nflmodel.wind --update` weekly.

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
