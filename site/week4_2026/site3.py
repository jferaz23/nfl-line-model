"""Week 4 line sheet, v3 layout: same numbers as site2.py, cleaner and more structured presentation."""
from pathlib import Path as _P
HERE = _P(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "reports" / "site"
OUT.mkdir(parents=True, exist_ok=True)
import contextlib, html, io
with contextlib.redirect_stdout(io.StringIO()):
    import site2 as d                     # computes games, picks, factors (and writes the old page)
from common import BOOKS, NAMES, REC, fp, fpct, fedge

games, listed = d.games, d.listed
e, slug, day, tm, tier, pp, best_text = d.e, d.slug, d.day, d.tm, d.tier, d.pp, d.best_text


def chance_cell(p):
    push = f'<span class="small">+{fpct(p["p"], 0)} push</span>' if p["p"] > 0 else ""
    adj = (f'<span class="small">Market {fpct(p["w0"])}, factors {pp(p["adj"])}</span>' if abs(p["adj"]) > 1e-9 else "")
    return (f'<div class="chance"><strong>{fpct(p["w"])}</strong>{push}</div>'
            f'<div class="meter" role="img" aria-label="Chance {fpct(p["w"])}, break-even {fpct(p["be"])}">'
            f'<span class="fill {tier(p["ev"])[0]}" style="width:{100 * p["w"]:.1f}%"></span>'
            f'<span class="tick" style="left:{100 * p["be"]:.1f}%"></span></div>{adj}')


def rating(p):
    cls, name = tier(p["ev"])
    return f'<span class="pill {cls}">{name}</span>'


def picks_table(g):
    rows = []
    for p in g["picks"]:
        top = ' <span class="tag">Top pick</span>' if p.get("top") else ""
        when = e(p["when"][0]) if p.get("when") else '<span class="muted">Any time</span>'
        when_title = f' title="{e(p["when"][1])}"' if p.get("when") else ""
        rows.append(f'''<tr>
<td data-label="Market" class="mkt">{p["market"]}</td>
<td data-label="Pick" class="pick"><strong>{e(p["label"])}</strong>{top}</td>
<td data-label="DK price" class="num">{fp(p["price"])}</td>
<td data-label="Chance to hit" class="chance-td">{chance_cell(p)}</td>
<td data-label="Break-even" class="num">{fpct(p["be"])}</td>
<td data-label="Fair price" class="num">{fp(p["fair"])}</td>
<td data-label="Edge" class="num edge {tier(p["ev"])[0]}">{fedge(p["ev"])}</td>
<td data-label="Best other book" class="best">{e(best_text(p))}</td>
<td data-label="Rating">{rating(p)}</td>
<td data-label="When to bet"{when_title}>{when}</td></tr>''')
    return f'''<div class="tablewrap"><table class="gt">
<thead><tr><th scope="col">Market</th><th scope="col">Pick</th><th scope="col" class="num">DK price</th><th scope="col">Chance to hit</th>
<th scope="col" class="num">Break-even</th><th scope="col" class="num">Fair price</th><th scope="col" class="num">Edge</th>
<th scope="col">Best other book</th><th scope="col">Rating</th><th scope="col">When to bet</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>'''


def factors_html(g):
    out = []
    for title, text, eff in g["factors"]:
        if eff:
            k, dlt = max(eff.items(), key=lambda kv: kv[1])
            who = {"away": g["aw"], "home": g["hm"], "over": "Over", "under": "Under"}[k]
            badge = f'<span class="fx on">{pp(dlt)}% to {e(who)}</span>'
        else:
            badge = '<span class="fx">No adjustment</span>'
        out.append(f'<li><div class="fh"><span class="fn">{e(title)}</span>{badge}</div><p>{e(text)}</p></li>')
    return "".join(out)


def game_card(g):
    aw, hm = g["aw"], g["hm"]
    stale = ('<p class="notice">DraftKings moved this line after Monday night (Rams −2.5 at −120, total 44.5). '
             'The prices below are from before the move, so re-check them.</p>') if g["stale"] else ""
    ctx = "".join(f"<li>{e(n)}</li>" for n in g["notes"])
    return f'''<article class="game" id="{slug(g)}" aria-labelledby="{slug(g)}-h">
<header class="gh">
  <div class="gh-main">
    <p class="gtime"><span>{tm(g["ko"])} ET</span><span>{e(g["tv"])}</span><span class="rotn">Rotation {g["rot"]}/{g["rot"] + 1}</span></p>
    <h3 id="{slug(g)}-h">{e(NAMES[aw])} <span class="rec">{REC[aw]}</span> <span class="at">at</span> {e(NAMES[hm])} <span class="rec">{REC[hm]}</span></h3>
    <p class="venue">{e(g["venue"])}. {e(g["roof"])}.</p>
  </div>
  <div class="gh-side">
    <p class="wlabel">Chance to win</p>
    <div class="wbar"><span style="width:{100 * g["win_a"]:.1f}%"></span></div>
    <p class="wvals"><span>{aw} {fpct(g["win_a"], 0)}</span><span>{hm} {fpct(1 - g["win_a"], 0)}</span></p>
    <p class="open">Opened {e(g["opener"])}</p>
  </div>
</header>
{stale}
{picks_table(g)}
<div class="gb">
  <section><h4>Context</h4><ul class="ctx">{ctx}</ul></section>
  <section><h4>Factors checked</h4><ul class="factors">{factors_html(g)}</ul></section>
</div>
<details class="prices"><summary>Prices at all eight sportsbooks</summary>{d.market_table(g)}</details>
</article>'''


def schedule_html():
    out, cur = [], None
    for g in games:
        dd = day(g["ko"])
        if dd != cur:
            if cur:
                out.append("</ul></div>")
            out.append(f'<div class="sday"><h3>{dd}</h3><ul>'); cur = dd
        tp = next(p for p in g["picks"][:2] if p.get("top"))
        out.append(f'<li><a href="#{slug(g)}"><span class="st">{tm(g["ko"])}</span><span class="sm">{g["aw"]} at {g["hm"]}</span>'
                   f'<span class="sp">{e(tp["label"])}</span></a></li>')
    out.append("</ul></div>")
    return "".join(out)


def best_rows():
    b = sorted([p for p in listed if tier(p["ev"])[0] == "value" and not p["g"]["stale"]], key=lambda p: -p["ev"])
    rows = []
    for p in b:
        g = p["g"]
        rows.append(f'''<tr><td data-label="Pick" class="pick"><strong>{e(p["label"])}</strong></td>
<td data-label="Game"><a href="#{slug(g)}">{e(NAMES[g["aw"]])} at {e(NAMES[g["hm"]])}</a></td>
<td data-label="Kickoff">{g["ko"].strftime("%a")} {tm(g["ko"])}</td><td data-label="DK price" class="num">{fp(p["price"])}</td>
<td data-label="Chance" class="num">{fpct(p["w"])}</td><td data-label="Break-even" class="num">{fpct(p["be"])}</td>
<td data-label="Edge" class="num edge value">{fedge(p["ev"])}</td><td data-label="When to bet">{e(p["when"][0])}</td></tr>''')
    return "".join(rows), b


def all_rows():
    out = []
    for i, p in enumerate(sorted(listed, key=lambda p: -p["w"]), 1):
        g = p["g"]; cls, name = tier(p["ev"])
        top = ' <span class="tag">Top</span>' if p.get("top") else ""
        moved = ' <span class="tag warn">Moved</span>' if g["stale"] else ""
        adj = pp(p["adj"]) if abs(p["adj"]) > 1e-9 else "0.0"
        out.append(f'''<tr data-market="{p["market"]}" data-top="{1 if p.get("top") else 0}" data-hit="{p["w"]:.5f}" data-edge="{p["ev"]:.5f}" data-ko="{g["ko"].isoformat()}{g["rot"]:04d}">
<td class="n" data-label="#">{i}</td><td data-label="Pick" class="pick"><strong>{e(p["label"])}</strong>{top}{moved}</td>
<td data-label="Game"><a href="#{slug(g)}">{g["aw"]} at {g["hm"]}</a></td><td data-label="Kickoff" class="muted">{g["ko"].strftime("%a")} {tm(g["ko"])}</td>
<td data-label="Market">{p["market"]}</td><td data-label="DK price" class="num">{fp(p["price"])}</td>
<td data-label="Chance" class="num"><strong>{fpct(p["w"])}</strong>{f' <span class="small">+{fpct(p["p"], 0)} push</span>' if p["p"] else ""}</td>
<td data-label="Market chance" class="num muted">{fpct(p["w0"])}</td><td data-label="Factors" class="num">{adj}</td>
<td data-label="Break-even" class="num">{fpct(p["be"])}</td><td data-label="Edge" class="num edge {cls}">{fedge(p["ev"])}</td>
<td data-label="Rating"><span class="pill {cls}">{name}</span></td><td data-label="When to bet">{e(p["when"][0])}</td></tr>''')
    return "".join(out)


n_games = len(games)
by_day = {}
for g in games:
    by_day[g["ko"].strftime("%A")] = by_day.get(g["ko"].strftime("%A"), 0) + 1
best_html, best_list = best_rows()
n_value = len(best_list)
n_near = sum(tier(p["ev"])[0] == "near" and not p["g"]["stale"] for p in listed)
top_best = best_list[0] if best_list else None
days = []
cur = None
for g in games:
    dd = day(g["ko"])
    if dd != cur:
        days.append((dd, []))
        cur = dd
    days[-1][1].append(g)
games_html = "".join(f'<section class="daygroup" aria-labelledby="d{i}"><h2 id="d{i}">{dd}</h2>{"".join(game_card(g) for g in gs)}</section>'
                     for i, (dd, gs) in enumerate(days))

CSS = open(HERE / "site3.css").read()
JS = open(HERE / "site3.js").read()
page = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Week 4 NFL line sheet: DraftKings vs the market</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Sans+Condensed:wght@500;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style></head>
<body>
<a class="skip" href="#games">Skip to games</a>
<header class="mast">
  <div class="wrap mast-in">
    <div>
      <p class="kicker">NFL 2026, Week 4</p>
      <h1>Week 4 line sheet</h1>
      <p class="sub">Every DraftKings spread, total and moneyline, priced against seven other sportsbooks and adjusted for weather, rest and early-season records.</p>
    </div>
    <dl class="stamp">
      <div><dt>Prices</dt><dd>Sept. 29, 2026</dd></div>
      <div><dt>Weather and injuries</dt><dd>Sept. 29, 2026</dd></div>
    </dl>
  </div>
  <nav class="tabs" aria-label="Sections"><div class="wrap">
    <a href="#summary">Summary</a><a href="#best">Best bets</a><a href="#games">Games</a><a href="#all">All picks</a><a href="#method">Method</a>
  </div></nav>
</header>

<main>
<section class="wrap" id="summary" aria-label="Summary">
  <div class="kpis">
    <div class="kpi"><p class="kl">Games</p><p class="kv">{n_games}</p><p class="ks">{", ".join(f"{v} {k}" for k, v in by_day.items())}</p></div>
    <div class="kpi"><p class="kl">Spread and total picks beating DraftKings' price</p><p class="kv">{n_value}<span> of {len(listed)}</span></p><p class="ks">After factor adjustments</p></div>
    <div class="kpi"><p class="kl">Picks within 2.5% of fair</p><p class="kv">{n_near}</p><p class="ks">Close to break-even at DraftKings</p></div>
    <div class="kpi"><p class="kl">Best edge</p><p class="kv sm">{e(top_best["label"]) if top_best else "None"}</p><p class="ks">{(e(NAMES[top_best["g"]["aw"]]) + " at " + e(NAMES[top_best["g"]["hm"]]) + ", " + fedge(top_best["ev"])) if top_best else ""}</p></div>
  </div>
  <div class="panel sched" aria-label="Schedule"><h2 class="ph">Schedule and top pick per game</h2><div class="sgrid">{schedule_html()}</div></div>
</section>

<section class="wrap" id="best" aria-labelledby="best-h">
  <div class="panel">
    <div class="ph-row"><h2 class="ph" id="best-h">Best bets</h2><p class="ph-note">Picks with a positive edge at DraftKings after adjustments, largest edge first.</p></div>
    <div class="tablewrap"><table class="bt"><thead><tr><th scope="col">Pick</th><th scope="col">Game</th><th scope="col">Kickoff</th><th scope="col" class="num">DK price</th>
    <th scope="col" class="num">Chance</th><th scope="col" class="num">Break-even</th><th scope="col" class="num">Edge</th><th scope="col">When to bet</th></tr></thead>
    <tbody>{best_html}</tbody></table></div>
    <p class="fine">Edges this small are close to noise. Treat them as the best prices on the board, not locks.</p>
  </div>
</section>

<section class="wrap" id="games" aria-label="Games">
  <div class="legend"><span><i class="lg-meter"></i>Bar: chance to hit. Tick: break-even at DraftKings' price.</span>
  <span><span class="pill value">Beats the market</span><span class="pill near">Near fair</span><span class="pill below">Below fair</span></span></div>
  {games_html}
</section>

<section class="wrap" id="all" aria-labelledby="all-h">
  <div class="panel">
    <div class="ph-row"><h2 class="ph" id="all-h">All spread and total picks, by chance of hitting</h2></div>
    <div class="filters" role="group" aria-label="Filter picks">
      <button type="button" aria-pressed="true" data-f="all">All</button>
      <button type="button" aria-pressed="false" data-f="Spread">Spreads</button>
      <button type="button" aria-pressed="false" data-f="Total">Totals</button>
      <button type="button" aria-pressed="false" data-f="top">Top pick per game</button>
    </div>
    <div class="tablewrap"><table class="at" id="list"><thead><tr><th scope="col" class="n">#</th><th scope="col">Pick</th><th scope="col">Game</th>
    <th scope="col" data-sort="ko"><button type="button">Kickoff</button></th><th scope="col">Market</th><th scope="col" class="num">DK price</th>
    <th scope="col" class="num" data-sort="hit" aria-sort="descending"><button type="button">Chance</button></th><th scope="col" class="num">Market</th>
    <th scope="col" class="num">Factors (%)</th><th scope="col" class="num">Break-even</th><th scope="col" class="num" data-sort="edge"><button type="button">Edge</button></th>
    <th scope="col">Rating</th><th scope="col">When to bet</th></tr></thead><tbody>{all_rows()}</tbody></table></div>
    <p class="fine">Top marks the stronger of each game's spread and total. Market is the other books' chance with their margin removed; Factors is the adjustment in percentage points.</p>
  </div>
</section>
</main>

<footer class="wrap method" id="method">
  <h2>Method and sources</h2>
  <div class="mgrid">
    <div><h3>Chance to hit</h3><p>Prices from bet365, BetMGM, Caesars, FanDuel, Fanatics, BetRivers and Hard Rock are stripped of their margin and the middle value is used. When a book hangs a different number, its price is converted using how often games land exactly on that number (about 9% on 3 and 6.5% on 7).</p></div>
    <div><h3>Factor adjustments</h3><p>Only situations where published records show the closing line missing something are adjusted, and each at a fraction of the historical edge: rain at kickoff (unders 57.4% over 343 games), 0-2 teams in Week 3 (55.7% against the spread since 2003) and rest gaps of four days or more. Travel, body clock, short weeks, heat and injury news are listed but not adjusted, because lines already move for them.</p></div>
    <div><h3>When to bet</h3><p>Late public money tends to push favorites and overs higher, so those are usually cheapest early in the week; underdogs and unders are often best close to kickoff. A key number (3 or 7) makes any half-point move matter more.</p></div>
    <div><h3>Sources</h3><p>Odds: VegasInsider multi-book table (captured Sept. 29; page last updated Sept. 28). Weather: MySportsWeather kickoff forecasts. Injuries: team and league reports as of Sept. 29. Research: Sharp Football, Yahoo Sports, NFL Analytics, BettorEdge and Football Outsiders.</p></div>
  </div>
  <p class="disclaimer">For information only, not financial advice. Confirm every price in the DraftKings app before betting. If betting stops being fun, call 1-800-GAMBLER.</p>
</footer>
<script>{JS}</script>
</body></html>'''
open(OUT / "week4_picks.html", "w").write(page)
print("written", len(page), "bytes;", n_value, "best bets;", n_near, "near fair")
