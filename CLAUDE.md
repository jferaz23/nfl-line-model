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
Real-data backtest 2022-2026 (1187 games): spread MAE model 9.75 vs close 9.57 (blend weight 3%),
total 10.29 vs 10.23 (blend 10.21, weight 28%). Roster continuity (nflmodel/continuity.py, weeks 1-8)
earned its place (held-out spread MAE 10.93 -> 10.79); early_down and big_plays groups are marginal.

Automation (GitHub jferaz23/nfl-line-model, Pages https://jferaz23.github.io/nfl-line-model/):
- `weekly.yml`: run_week.py (Tue/Thu/Fri/Sun/Mon) -> line_watch.py -> build_site.py -> deploy.
  run_week writes site_data/week_*.json, schedule_*.json, season_*.json (season sim) and appends
  artifacts/tracker/model_picks.csv. ESPN same-day injuries are merged for the target week.
- `line_watch.yml` (every 20 min): ESPN scoreboard -> artifacts/lines/espn_lines.csv (DraftKings line
  history + opening lines) and site_data/live.json (not committed) -> build_site.py -> deploy.
- `optimize.yml`: recalibrates Tuesdays. `ODDS_API_KEY` is an Actions secret.
- Site: web/ (index.html, app.js, style.css, no build step) + public/data/site.js from build_site.py.
  Tabs: Games, Picks (bet ranking, history %, teasers, PDF), Breakdown, Futures, Teams, Players,
  Backtest, Bets (graded tracker, CLV), Info (health checks).
Local: `config.json` (gitignored) keeps the data cache outside OneDrive; use `--config config.json`.
`run_week.py --odds-snapshot latest` re-prices from a saved snapshot without spending credits.
