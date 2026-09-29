"""Weekly line sheet (HTML + CSV) and backtest report.

Visual idea: a handicapper's printed line sheet with the playable prices
marked in highlighter. Quiet ink-on-paper everywhere else, so the yellow is
the only thing that shouts.
"""
from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .pricing import fmt_american

ET = ZoneInfo("America/New_York")
BOOK_NAMES = {"draftkings": "DraftKings", "fanduel": "FanDuel", "betmgm": "BetMGM", "pinnacle": "Pinnacle",
              "lowvig": "LowVig", "betonlineag": "BetOnline", "bovada": "Bovada", "novig": "Novig",
              "prophetx": "ProphetX", "caesars": "Caesars", "williamhill_us": "Caesars", "espnbet": "ESPN BET"}


def book_name(key: str) -> str:
    return BOOK_NAMES.get(key, key.title())
GROUP_LABELS = {
    "venue_history": "Stadium history",
    "drive_efficiency": "Drive efficiency", "calendar": "Scoring calendar", "motivation": "Late-season motivation", "venue_history": "Venue history",
    "home_field": "Home field", "team_strength": "Team strength", "scheme_matchup": "Scheme matchup",
    "quarterback": "Quarterbacks", "injuries": "Injuries", "rest_travel": "Rest and travel",
    "time_of_day": "Kickoff time", "weather": "Weather", "surface_altitude": "Surface and altitude",
    "coaching": "Coaching", "officials": "Officials", "history": "Head-to-head and ATS history",
    "situational": "Schedule spot", "scoring_env": "League scoring level",
}

CSS = """
:root{--paper:#F3F5F7;--ink:#1C2733;--rule:#C9D1DA;--muted:#5B6875;--mark:#FFE45C;--mark-ink:#1C2733;
--field:#2F6B4F;--warn:#8A4B12;--card:#FFFFFF}
@media (prefers-color-scheme:dark){:root{--paper:#141A21;--ink:#E4E9EE;--rule:#34404C;--muted:#9AA7B4;
--mark:#E8CF4A;--mark-ink:#141A21;--field:#7FC3A0;--warn:#E3A566;--card:#1A222B}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);
font-family:"IBM Plex Sans Condensed","Arial Narrow","Roboto Condensed",Arial,sans-serif;
font-size:16px;line-height:1.45;font-variant-numeric:tabular-nums}
main{max-width:1080px;margin:0 auto;padding:28px 20px 64px}
h1{font-size:2.1rem;line-height:1.1;margin:0 0 6px;font-weight:600;letter-spacing:-.01em}
h2{font-size:1.25rem;margin:40px 0 10px;font-weight:600;padding-bottom:6px;border-bottom:2px solid var(--ink)}
h3{font-size:1.05rem;margin:0;font-weight:600}
p{max-width:72ch;margin:6px 0}
.sub{color:var(--muted);margin:0}
.settings{display:flex;flex-wrap:wrap;gap:4px 22px;margin:14px 0 0;padding:0;list-style:none;color:var(--muted);font-size:.9rem}
.settings b{color:var(--ink);font-weight:600}
.demo{background:var(--ink);color:var(--paper);padding:10px 14px;margin:0 0 20px;font-weight:600}
.notes{margin:14px 0 0;padding-left:18px;color:var(--muted);font-size:.92rem}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-size:.95rem}
th{text-align:left;font-weight:600;color:var(--muted);border-bottom:1px solid var(--ink);padding:6px 10px 5px;white-space:nowrap}
td{padding:6px 10px;border-bottom:1px solid var(--rule);vertical-align:top}
td.n,th.n{text-align:right;white-space:nowrap}
tr:last-child td{border-bottom:none}
.mark{background:var(--mark);color:var(--mark-ink);box-shadow:inset 0 -2px 0 rgba(0,0,0,.08)}
.pos{color:var(--field)}
.warn{color:var(--warn)}
.muted{color:var(--muted)}
.empty{padding:18px 16px;border:1px dashed var(--rule);color:var(--muted);max-width:72ch}
.game{background:var(--card);border:1px solid var(--rule);padding:16px 18px;margin:14px 0}
.gh{display:flex;flex-wrap:wrap;justify-content:space-between;gap:4px 20px;align-items:baseline}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:4px 24px;margin:10px 0 12px;font-size:.92rem}
.facts div span{color:var(--muted)}
.lines{margin-top:6px}
.why{display:grid;grid-template-columns:minmax(150px,max-content) 1fr 52px;gap:3px 10px;align-items:center;font-size:.88rem;margin-top:12px;max-width:560px}
.bar{height:9px;position:relative;background:linear-gradient(var(--rule),var(--rule)) center/1px 100% no-repeat}
.bar i{position:absolute;top:0;bottom:0;background:var(--ink);opacity:.75}
details{margin-top:10px}
summary{cursor:pointer;color:var(--muted);font-size:.9rem}
summary:focus-visible,a:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
footer{margin-top:48px;color:var(--muted);font-size:.9rem}
@media (max-width:620px){h1{font-size:1.6rem}main{padding:20px 14px 48px}.game{padding:14px 12px}}
@media print{body{background:#fff}.game{break-inside:avoid;border-color:#999}}
"""


def esc(x) -> str:
    return html.escape("" if x is None or (isinstance(x, float) and np.isnan(x)) else str(x))


def _f(x, nd=1, sign=False):
    if x is None or not np.isfinite(x):
        return "\u2013"
    s = f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"
    return s.replace("-", "\u2212")


def spread_text(team_home, team_away, margin, nd=1):
    """Home-perspective mean margin -> favourite and points, e.g. 'KC \u22123.2'."""
    if margin is None or not np.isfinite(margin):
        return "\u2013"
    if abs(margin) < 0.05:
        return "pick'em"
    fav = team_home if margin > 0 else team_away
    return f"{fav} \u2212{abs(margin):.{nd}f}"


def _pretty(src: str) -> str:
    import re
    return re.sub(r"[a-z_]+", lambda m: BOOK_NAMES.get(m.group(0), m.group(0)), str(src))


def _page(title, body, demo=False):
    banner = ('<div class="demo" role="note">Synthetic demo data. These are not real games, lines or '
              'recommendations; they only show what the report looks like.</div>') if demo else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Condensed:wght@400;600&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><main>{banner}{body}</main></body></html>"""


def _clock(t: datetime) -> str:
    """Portable '1:00 pm' (Windows strftime has no %-I)."""
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"


def _kick(iso):
    try:
        t = datetime.fromisoformat(iso).astimezone(ET)
        return f"{t:%a %b} {t.day}, {_clock(t)} ET"
    except Exception:
        return ""


def _weather(g):
    if g.get("indoor", 0) >= 0.5:
        return "Indoors"
    src = g.get("wx_source", "")
    parts = [f"{g.get('temp_used', np.nan):.0f}\u00b0F", f"wind {g.get('wind_used', np.nan):.0f} mph"]
    if g.get("snow", 0) > 0:
        parts.append("snow")
    elif g.get("precip", 0) > 0:
        parts.append("rain")
    txt = ", ".join(parts)
    if "assumed" in str(src):
        txt += " (no forecast yet; typical conditions assumed)"
    return txt


def _why_bars(contrib: dict, limit=6):
    items = sorted(((k, v) for k, v in contrib.items() if k != "baseline"), key=lambda kv: -abs(kv[1]))[:limit]
    if not items:
        return ""
    scale = max(3.0, max(abs(v) for _, v in items))
    rows = []
    for k, v in items:
        w = min(abs(v) / scale * 50, 50)
        left = 50 if v >= 0 else 50 - w
        rows.append(f'<div>{esc(GROUP_LABELS.get(k, k))}</div><div class="bar"><i style="left:{left:.1f}%;width:{w:.1f}%"></i></div>'
                    f'<div class="n" style="text-align:right">{_f(v, 1, True)}</div>')
    return "".join(rows)


def weekly_html(season, week, games: pd.DataFrame, summary: pd.DataFrame, board: pd.DataFrame,
                explain_m: pd.DataFrame, explain_t: pd.DataFrame, power: pd.DataFrame, cfg, weights,
                notes, demo=False, generated=None) -> str:
    generated = generated or datetime.now(ET)
    w_m, w_t = weights
    head = [f"<h1>NFL line sheet: {season} week {week}</h1>",
            f'<p class="sub">Generated {esc(f"{generated:%A %B} {generated.day}, {generated.year} at {_clock(generated)} ET")}. '
            f"Prices compared against {esc(book_name(cfg.target_book))}.</p>",
            '<ul class="settings">',
            f"<li>Minimum edge <b>{cfg.min_ev:+.1%}</b></li>",
            f"<li>Bankroll <b>${cfg.bankroll:,.0f}</b>, {cfg.kelly_fraction:.2g} Kelly, cap {cfg.max_stake_pct:.1%}</li>",
            f"<li>Model weight <b>{w_m:.0%}</b> spreads, <b>{w_t:.0%}</b> totals</li>",
            f"<li>Outcome SD {cfg.margin_sd:.1f} margin, {cfg.total_sd:.1f} total</li></ul>"]
    if notes:
        head.append('<ul class="notes">' + "".join(f"<li>{esc(n)}</li>" for n in notes) + "</ul>")

    # ---------------- best bets ----------------
    parts = ["\n".join(head), "<h2>Best prices this week</h2>"]
    plays = board[board["is_play"]].sort_values("ev", ascending=False) if len(board) else board
    if len(plays):
        rows = []
        for i, b in enumerate(plays.to_dict("records"), 1):
            push = "" if b["p_push"] < 0.005 else f" / {b['p_push']:.0%} push"
            rows.append(
                f"<tr><td class='n'>{i}</td><td>{esc(b['matchup'])}</td><td><span class='mark'>{esc(b['bet'])} "
                f"{esc(fmt_american(b['price']))}</span></td><td class='n'>{esc(fmt_american(b['fair_price']))}</td>"
                f"<td class='n'>{b['p_win']:.1%}{push}</td>"
                f"<td class='n pos'>{b['ev']:+.1%}</td><td class='n'>${b['stake']:,.0f}</td>"
                f"<td class='n'>{_f(b['dk_vs_market'], 1, True)}</td></tr>")
        parts.append("<div class='scroll'><table><thead><tr><th class='n'>Rank</th><th>Game</th>"
                     "<th>Bet at DraftKings</th><th class='n'>Fair price</th><th class='n'>Win chance</th>"
                     "<th class='n'>Edge</th><th class='n'>Stake</th><th class='n'>Pts vs sharp market</th>"
                     "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")
        parts.append("<p class='muted'>Edge is expected profit per dollar at the fair line. Stakes are "
                     f"{cfg.kelly_fraction:.2g} Kelly, capped. \"Pts vs sharp market\" is how many points better "
                     "DraftKings' number is than the sharp consensus; most real edges come from there.</p>")
    else:
        parts.append("<div class='empty'>Nothing clears the minimum edge at DraftKings right now. That's the "
                     "normal result on most runs. Re-run after Friday's final injury report and again about 90 "
                     "minutes before kickoff, once inactives are announced; that is when soft lines usually appear.</div>")
    flagged = board[board["check_news"] & (board["ev"] >= cfg.min_ev)] if len(board) else board
    if len(flagged):
        parts.append("<p class='warn'>Held back because the model disagrees with the market by more than "
                     f"{cfg.news_gap_points:g} points, which usually means news the model doesn't have: "
                     + esc("; ".join(f"{r['matchup']} {r['bet']}" for r in flagged.to_dict("records")))
                     + ". Check injuries, weather and QB status before betting any of these.</p>")

    # ---------------- per game ----------------
    parts.append("<h2>Game by game</h2>")
    s_idx = summary.set_index("game_id") if len(summary) else pd.DataFrame()
    for g in games.sort_values("kickoff_utc").to_dict("records"):
        gid, h, a = g["game_id"], g["home_team"], g["away_team"]
        s = s_idx.loc[gid].to_dict() if gid in s_idx.index else {}
        venue = g.get("venue_name", "")
        site = "neutral site" if g.get("location") == "Neutral" else f"{h} home"
        facts = [
            ("Kickoff", _kick(g.get("kickoff_utc", ""))),
            ("Venue", f"{venue} ({site}), {g.get('roof_used', '')}, {'turf' if g.get('turf', 0) >= 0.5 else 'grass'}"),
            ("Weather", _weather(g)),
            ("Rest", f"{a} {g.get('away_rest', np.nan):.0f} days, {h} {g.get('home_rest', np.nan):.0f} days; "
                     f"{a} travel {g.get('away_travel_kmi', 0) * 1000:,.0f} mi"),
            (f"{a} QB", f"{g.get('a_qb_name_used', '')} ({g.get('a_qb_source', '')})"),
            (f"{h} QB", f"{g.get('h_qb_name_used', '')} ({g.get('h_qb_source', '')})"),
        ]
        if g.get("a_miss_names"):
            facts.append((f"{a} injury list", g["a_miss_names"]))
        if g.get("h_miss_names"):
            facts.append((f"{h} injury list", g["h_miss_names"]))
        fact_html = "".join(f"<div><span>{esc(k)}:</span> {esc(v)}</div>" for k, v in facts)

        mm, mt = s.get("model_margin", g.get("model_margin")), s.get("model_total", g.get("model_total"))
        line_rows = [
            f"<tr><td>Spread</td><td class='n'>{spread_text(h, a, mm)}</td><td class='n'>{spread_text(h, a, s.get('market_margin'))}</td>"
            f"<td class='n'>{spread_text(h, a, s.get('fair_margin'))}</td><td class='n'>{spread_text(h, a, s.get('dk_margin'))}</td></tr>",
            f"<tr><td>Total</td><td class='n'>{_f(mt)}</td><td class='n'>{_f(s.get('market_total'))}</td>"
            f"<td class='n'>{_f(s.get('fair_total'))}</td><td class='n'>{_f(s.get('dk_total'))}</td></tr>",
        ]
        lines = ("<div class='scroll lines'><table><thead><tr><th>Projection</th><th class='n'>Model</th>"
                 "<th class='n'>Sharp market</th><th class='n'>Fair (blend)</th><th class='n'>DraftKings implied</th>"
                 "</tr></thead><tbody>" + "".join(line_rows) + "</tbody></table></div>")
        gb = board[board["game_id"] == gid] if len(board) else board
        offers = ""
        if len(gb):
            rows = []
            for b in gb.to_dict("records"):
                cls = " class='mark'" if b["is_play"] else ""
                flag = " <span class='warn'>(check news)</span>" if b["check_news"] and b["ev"] >= cfg.min_ev else ""
                if b.get("timing"):
                    flag += f" <span class='muted' title='{esc(b.get('timing_detail', ''))}'>{esc(b['timing'])}</span>"
                rows.append(f"<tr><td><span{cls}>{esc(b['bet'])}</span>{flag}</td><td class='n'>{esc(fmt_american(b['price']))}</td>"
                            f"<td class='n'>{esc(fmt_american(b['fair_price']))}</td><td class='n'>{b['p_win']:.1%}</td>"
                            f"<td class='n {'pos' if b['ev'] > 0 else 'muted'}'>{b['ev']:+.1%}</td></tr>")
            offers = ("<div class='scroll lines'><table><thead><tr><th>DraftKings offer</th><th class='n'>Price</th>"
                      "<th class='n'>Fair price</th><th class='n'>Win</th><th class='n'>Edge</th></tr></thead><tbody>"
                      + "".join(rows) + "</tbody></table></div>")
        else:
            offers = "<p class='muted'>No DraftKings prices for this game in this run.</p>"
        src = (f"<p class='muted'>Market consensus: spreads from {esc(_pretty(s.get('market_margin_source', 'n/a')))}; "
               f"totals from {esc(_pretty(s.get('market_total_source', 'n/a')))}.</p>") if s else ""
        em = explain_m.loc[gid].to_dict() if gid in explain_m.index else {}
        et = explain_t.loc[gid].to_dict() if gid in explain_t.index else {}
        why = ""
        if em:
            why = (f"<details><summary>What moves the model's number</summary>"
                   f"<p class='muted'>Points added to {esc(h)}'s margin by each factor group, versus an average matchup "
                   f"(linear part of the model):</p><div class='why'>{_why_bars(em)}</div>"
                   f"<p class='muted' style='margin-top:12px'>Points added to the total:</p><div class='why'>{_why_bars(et)}</div></details>")
        parts.append(f"<section class='game' aria-label='{esc(a)} at {esc(h)}'><div class='gh'><h3>{esc(a)} at {esc(h)}</h3>"
                     f"<span class='muted'>{esc(gid)}</span></div><div class='facts'>{fact_html}</div>{lines}{offers}{src}{why}</section>")

    # ---------------- power ratings ----------------
    if power is not None and len(power):
        rows = "".join(
            f"<tr><td class='n'>{i}</td><td>{esc(r['team'])}</td><td class='n'>{_f(r['net_pts'], 1, True)}</td>"
            f"<td class='n'>{_f(r['off_pts'], 1, True)}</td><td class='n'>{_f(-r['def_pts'], 1, True)}</td>"
            f"<td class='n'>{_f(r['elo'], 0)}</td><td>{esc(r['proj_qb'])}</td><td class='n'>{_f(r['qb_vs_base_pts'], 1, True)}</td></tr>"
            for i, r in enumerate(power.to_dict("records"), 1))
        parts.append("<h2>Power ratings going into the week</h2><p class='muted'>Points versus an average team on a neutral "
                     "field, opponent-adjusted and weighted toward recent games. QB adjustment is how much this week's "
                     "projected starter differs from the QB play baked into the team rating.</p>"
                     "<div class='scroll'><table><thead><tr><th class='n'>Rank</th><th>Team</th><th class='n'>Net</th>"
                     "<th class='n'>Offense</th><th class='n'>Defense</th><th class='n'>Elo</th><th>Projected QB</th>"
                     "<th class='n'>QB adj.</th></tr></thead><tbody>" + rows + "</tbody></table></div>")

    parts.append(
        "<footer><p>How the fair line is built: the model projects the margin and total from opponent-adjusted "
        "team ratings, quarterback value, player availability, rest, travel, kickoff time, weather, surface, "
        "coaching and officials. That projection is blended with the no-vig consensus of sharp books using the "
        "weight your backtest estimated, then priced with a key-number-aware distribution. Beating the closing "
        "line is the test that matters; log your bets in overrides/my_bets.csv and run clv_report.py.</p>"
        "<p>This is a model, not advice. Bet only what you can afford to lose.</p></footer>")
    return _page(f"NFL line sheet {season} week {week}", "\n".join(parts), demo)


def backtest_html(res: dict, cfg, demo=False) -> str:
    p = [f"<h1>Backtest: {res['start']} to {res['end']}</h1>",
         f"<p class='sub'>Walk-forward by season: each season is predicted by a model trained only on earlier "
         f"seasons. {res['n_games']:,} games.</p>"]
    s = res["summary"]
    p.append("<h2>Accuracy against the closing line</h2><div class='scroll'><table><thead><tr><th></th>"
             "<th class='n'>Model MAE</th><th class='n'>Closing line MAE</th><th class='n'>Blend MAE</th>"
             "<th class='n'>Blend weight on model</th><th class='n'>Residual SD</th></tr></thead><tbody>"
             + "".join(f"<tr><td>{esc(k)}</td><td class='n'>{v['mae_model']:.2f}</td><td class='n'>{v['mae_market']:.2f}</td>"
                       f"<td class='n'>{v['mae_blend']:.2f}</td><td class='n'>{v['weight']:.0%}</td><td class='n'>{v['sd']:.1f}</td></tr>"
                       for k, v in s.items()) + "</tbody></table></div>")
    p.append("<p>If the model's error is well above the closing line's, it is not seeing anything the market "
             "misses, and the blend weight will be near zero. That is the honest outcome for most public models; "
             "your edge then comes from line shopping DraftKings against sharper books and from betting before "
             "news is priced in.</p>")
    for key, title in (("ats", "Against the spread, by size of disagreement with the closing line"),
                       ("ou", "Over/under, by size of disagreement with the closing total")):
        t = res[key]
        p.append(f"<h2>{title}</h2><div class='scroll'><table><thead><tr><th class='n'>Model differs by at least</th>"
                 "<th class='n'>Games</th><th class='n'>Win rate</th><th class='n'>ROI at \u2212110</th></tr></thead><tbody>"
                 + "".join(f"<tr><td class='n'>{r['threshold']:g} pts</td><td class='n'>{r['n']}</td>"
                           f"<td class='n{' pos' if r['win_rate'] > 0.524 else ''}'>{r['win_rate']:.1%}</td>"
                           f"<td class='n'>{r['roi']:+.1%}</td></tr>" for r in t) + "</tbody></table></div>")
    p.append("<p class='muted'>Break-even at \u2212110 is 52.4%. Small samples swing a lot: 100 bets at a true "
             "52% win rate will land anywhere from about 42% to 62%.</p>")
    if res.get("ablation"):
        p.append("<h2>Which factor groups earn their place</h2><p>Out-of-sample error change when a group is "
                 "removed (linear model only). Positive means the group helps; near zero means it is noise the "
                 "regularization is already ignoring.</p><div class='scroll'><table><thead><tr><th>Group</th>"
                 "<th class='n'>Margin MAE change</th><th class='n'>Total MAE change</th></tr></thead><tbody>"
                 + "".join(f"<tr><td>{esc(GROUP_LABELS.get(r['group'], r['group']))}</td>"
                           f"<td class='n'>{_f(r.get('margin'), 3, True)}</td><td class='n'>{_f(r.get('total'), 3, True)}</td></tr>"
                           for r in res["ablation"]) + "</tbody></table></div>")
    if res.get("coefs") is not None:
        c = res["coefs"].head(25)
        p.append("<h2>Largest margin-model weights</h2><div class='scroll'><table><thead><tr><th>Feature</th><th>Group</th>"
                 "<th class='n'>Points per SD</th></tr></thead><tbody>"
                 + "".join(f"<tr><td>{esc(r['feature'])}</td><td>{esc(GROUP_LABELS.get(r['group'], r['group']))}</td>"
                           f"<td class='n'>{_f(r['pts_per_sd'], 2, True)}</td></tr>" for r in c.to_dict("records"))
                 + "</tbody></table></div>")
    p.append(f"<footer><p>Calibration written to artifacts/calibration.json (weights {s['spread']['weight']:.0%} spread, "
             f"{s['total']['weight']:.0%} total). run_week.py uses it automatically.</p></footer>")
    return _page(f"Backtest {res['start']}-{res['end']}", "\n".join(p), demo)
