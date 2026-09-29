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
Built and tested on synthetic data only; never run on real NFL data. First task: run
`python optimize.py` on real data and review model-vs-closing-line MAE and the pruning log.
