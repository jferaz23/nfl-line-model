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
