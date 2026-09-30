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
at closing prices: Top 150-112-7 (57.3%), green 277-228-12 (54.9%, +43.7u), all spreads 51.8%.
Live picks logged to artifacts/tracker/picks_log.csv; build_site.build_record merges them.
Data audit (audit_data.py) runs weekly; see Info tab.

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
