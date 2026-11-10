# Research log (rules are written here BEFORE each test runs)

Earlier entries (Sept 30 - Oct 23, 2026) lived in a scratch folder that was wiped; their results are summarized in
CLAUDE.md and docs/PROJECT_HANDOFF.md. New entries from Nov 10, 2026 are kept here.

## Nov 10, 2026: kicker props (user request). Stated before collecting any data.
Data: ESPN core API prop lines for kickers: Total Kicking Points, Total Field Goals Made, Total Extra Points Made
(2024-25 ESPN BET = provider 58, 2026 DraftKings = provider 100); main line = most common opening line per kicker and
market, last update before kickoff (as the other props). Results from nflverse player stats (fg_made, pat_made).
Projection (as-of kickoff, walk-forward: each season predicted by a model trained on earlier seasons, 2015+ history):
team implied points from the closing spread/total, the kicker's recency-weighted FG attempts / made / XP made and
kicking points (half-life 4 games, last season x0.6), the team's recent FG and TD drive rates, the kicker's FG made
over expected (by distance, prior seasons), indoors / wind / temperature, opponent points allowed (recency-weighted).
Gradient boosting per market (kicking points, FG made, XP made), residual sd for z = (projection - line) / sd.
Pass (same as the other props, P5): chance by market x side x |z| band from earlier seasons (shrunk 200, monotone);
green = chance >= break-even(-115) + 1pt. Kicker props become green picks only if green wins > 53.5% with positive units
at -115 in BOTH 2025 and 2026, Top (break-even + 3pt) beats green's win rate, and the result holds on >= 4 of 5 GBM seeds.
Also reported: the line vs the projection's accuracy (MAE), and over/under hit rates of the lines themselves.
Result (kicker props, 5 seeds): no green or Top kicker prop in 2025 or 2026 on any seed (the model's side never reached
break-even + 1pt in any band) -> NOT adopted. Projection MAE ~ the line's (kicking points 2.83/2.90/3.03 vs line
2.83/2.96/2.99; FG made 1.03/0.96/1.02 vs 1.04/1.01/1.03). Lines: FG made (1.5 almost always) went over 54% / 53% / 54%,
but overs are priced about -120 (needs 54.5%): +5.6u 2024, -18.2u 2025 at real prices -> priced in. Kicking points and
XP lines ~50/50. Data: nfl_data_cache/props/kicker_lines.csv (680 games 2024-26), kicker_backtest.csv.

## Nov 10, 2026: automation. GitHub fired the 15-minute Update schedule only 3-5x/day from Oct 30 (30-40x before), so
pre-kickoff runs after inactives were missed (Nov 8: last update before the 1 PM games at 9:51 AM ET). Added
.github/workflows/keeper.yml + keeper.py (dispatches Update at T-80 min before each kickoff and the Wed-Fri 4:40 PM
injury report; several start times; test dispatch worked) and widened scheduler windows (pre-kick T-88..T-12, injury
report until 6:30 PM ET).
