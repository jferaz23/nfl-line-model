"""Week 4 picks page, v2: picks = side with the higher (factor-adjusted) chance of hitting."""
from pathlib import Path as _P
HERE = _P(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "reports" / "site"
OUT.mkdir(parents=True, exist_ok=True)
import html, sys
from datetime import datetime
sys.path.insert(0, str(ROOT))
from nflmodel.movement import timing
from common import (G, META, STALE, BOOKS, NAMES, REC, side_offer, fair_at, ev, breakeven, fair_price,
                    fl, fp, fpct, fedge, label, cell_text)

# ---- Week 4 conditions (MySportsWeather forecast at kickoff, Sept 29) and news -------------------
WX = {  # temp F, wind mph, gust mph, rain chance at kickoff, indoor
 ("PIT", "CLE"): (75, 8, 15, .15, False), ("IND", "WAS"): (70, 2, None, .11, False),
 ("NE", "BUF"): (66, 6, 10, .33, False), ("NYJ", "CHI"): (61, 5, 10, .04, False),
 ("ARI", "NYG"): (65, 9, 17, .60, False), ("DAL", "HOU"): (None, None, None, 0, True),
 ("JAX", "CIN"): (66, 7, 12, .35, False), ("GB", "TB"): (87, 7, 12, .39, False),
 ("LAR", "PHI"): (65, 5, 15, .59, False), ("TEN", "BAL"): (66, 8, 14, .61, False),
 ("MIA", "MIN"): (None, None, None, 0, True), ("DEN", "SF"): (81, 1, 5, 0, False),
 ("KC", "LV"): (None, None, None, 0, True), ("LAC", "SEA"): (66, 3, 5, 0, False),
 ("DET", "CAR"): (70, 5, 12, .56, False), ("ATL", "NO"): (None, None, None, 0, True),
}
NEWS = {  # QB and injury news as of Sept 29
 ("PIT", "CLE"): ["Cleveland has won two straight with Deshaun Watson at quarterback."],
 ("IND", "WAS"): ["Washington is without QB Jayden Daniels; Marcus Mariota starts. Colts WR Alec Pierce is on injured reserve."],
 ("NE", "BUF"): [],
 ("NYJ", "CHI"): ["Caleb Williams has a Grade 2 hamstring strain (3 to 4 weeks); Case Keenum starts.",
                  "Jets RB Breece Hall was hurt in Week 3."],
 ("ARI", "NYG"): ["Jaxson Dart is out for the regular season. Jameis Winston is expected to start; the Giants have also agreed a trade for J.J. McCarthy.",
                  "Giants pass rusher Brian Burns tore an ACL."],
 ("DAL", "HOU"): ["Houston is 0-3 against the spread with a −7 point differential per game; Dallas is +2."],
 ("JAX", "CIN"): [],
 ("GB", "TB"): ["Baker Mayfield (dislocated throwing thumb) is out at least three weeks; undrafted rookie Jalon Daniels starts.",
                "Green Bay's Micah Parsons is on PUP and Josh Jacobs is on the exempt list."],
 ("LAR", "PHI"): ["Rams WR Puka Nacua has missed two of three games (hip/groin).",
                  "74% of DraftKings tickets and nearly all the money were on the Rams after Monday night."],
 ("TEN", "BAL"): ["Ravens WR Zay Flowers (hamstring) and Titans RB Tyjae Spears (ankle) are uncertain."],
 ("MIA", "MIN"): ["Miami lost RB De'Von Achane to a knee injury; Malik Willis is at quarterback. Justin Jefferson left Minnesota's Week 3 win early."],
 ("DEN", "SF"): [],
 ("KC", "LV"): [],
 ("LAC", "SEA"): ["The Chargers are 0-3 against the spread, with a −4 turnover margin and all three games under the total."],
 ("DET", "CAR"): ["Detroit is 13-4 against the spread as a road favorite under Dan Campbell; Carolina is 6-3 as a home underdog since last season."],
 ("ATL", "NO"): [],
}
WINLESS = {"TEN", "MIA", "LAC", "HOU", "TB"}
REST_EDGE = {("ATL", "NO"): ("ATL", 11, 7)}          # team with a 4+ day rest edge

# ---- research-based adjustments (probability points on one side; each already shrunk) ------------
RAIN_UNDER = 0.574      # under rate with measurable rain at kickoff (Sharp Football, 343 games)
WINLESS_BUMP = 0.014    # a quarter of the 55.7% ATS rate of 0-2 teams in Week 3 since 2003
REST_BUMP = 0.007       # half of the ~0.45 points of bye-sized rest the closing line misses


def factors(g):
    """List of (title, text, effect) where effect = dict(kind -> prob delta) or None if priced in."""
    aw, hm = g["aw"], g["hm"]
    out = []
    t, w, gu, rain, indoor = WX[(aw, hm)]
    if indoor:
        out.append(("Weather", "Played indoors, so weather is not a factor.", None))
    else:
        wind = f"{w} mph wind" + (f", gusts to {gu}" if gu else "")
        txt = f"{t}°F, {wind}, {round(rain * 100)}% chance of rain at kickoff."
        if rain >= 0.1:
            d = rain * (RAIN_UNDER - 0.5) * 0.5
            out.append(("Weather", txt + " Totals have stayed under 57% of the time when rain is falling at kickoff; "
                        "that edge is weighted by the rain chance and halved.", {"under": d, "over": -d}))
        else:
            out.append(("Weather", txt + " Wind under 15 mph and little rain: no weather edge.", None))
        if t and t >= 85:
            out.append(("Heat", f"{t}°F at kickoff. No reliable scoring effect found for heat alone.", None))
    for tm in (aw, hm):
        if tm in WINLESS:
            side = "away" if tm == aw else "home"
            other = "home" if side == "away" else "away"
            out.append(("Winless start", f"{NAMES[tm]} are 0-3. Since 2003, 0-2 teams have covered 55.7% in Week 3 as the "
                        "market overreacts to bad starts; a quarter of that edge is applied.", {side: WINLESS_BUMP, other: -WINLESS_BUMP}))
    if (aw, hm) in REST_EDGE:
        tm, r1, r2 = REST_EDGE[(aw, hm)]
        side = "away" if tm == aw else "home"
        other = "home" if side == "away" else "away"
        out.append(("Rest", f"{NAMES[tm]} have {r1} days of rest to {r2}. Gaps of four days or more have been worth about "
                    "two points, but closing lines already price most of it; half the missing part is applied.",
                    {side: REST_BUMP, other: -REST_BUMP}))
    if (aw, hm) == ("GB", "TB"):
        out.append(("Rest", "Green Bay has 10 days of rest to Tampa Bay's 7. Three-day gaps have been worth nothing historically.", None))
    if (aw, hm) in (("LAR", "PHI"), ("NYJ", "CHI")):
        out.append(("Short week", f"{NAMES[hm]} played Monday night. Rested teams have covered 51.8% in this spot, below break-even, "
                    "and the short-rest side has covered more often since 2016.", None))
    if (aw, hm) == ("LAR", "PHI"):
        out.append(("Body clock", "A 1 p.m. ET kickoff is 10 a.m. for the Rams. That has cost West Coast teams about 3 points "
                    "historically, but books move the spread by about the same amount.", None))
    if (aw, hm) == ("IND", "WAS"):
        out.append(("Travel", "Both teams fly to London, so the trip is shared.", None))
    if (aw, hm) in (("DAL", "HOU"), ("TEN", "BAL")):
        tm = "DAL" if aw == "DAL" else "BAL"
        out.append(("Travel", f"{NAMES[tm]} played in Rio de Janeiro last week. Samples of teams playing right after an "
                    "overseas game are too small to rely on, and Rio is only an hour off Eastern time.", None))
    if NEWS[(aw, hm)]:
        out.append(("Injuries and QBs", " ".join(NEWS[(aw, hm)]) + " The line has already moved for these.", None))
    return out


games = []
for (aw, hm, _), bk in G.items():
    rot, ko, tv, venue, roof, opener, notes = META[(aw, hm)]
    dk = bk["draftkings"]; others = {b: v for b, v in bk.items() if b != "draftkings"}
    g = dict(aw=aw, hm=hm, rot=rot, ko=datetime.strptime(ko, "%Y-%m-%d %H:%M"), tv=tv, venue=venue, roof=roof,
             opener=opener, notes=notes, dk=dk, bk=bk, stale=(aw, hm) in STALE)
    g["factors"] = factors(g)
    adj = {}
    for _, _, eff in g["factors"]:
        for k, d in (eff or {}).items():
            adj[k] = adj.get(k, 0.0) + d
    sides = {}
    for kind in ("away", "home", "over", "under", "away_ml", "home_ml"):
        t, price = side_offer(dk, kind)
        w0, p = fair_at(others, kind, t)
        w = max(0.01, min(0.99, w0 + adj.get(kind, 0.0)))
        best = None
        for b, v in others.items():
            tb, pb = side_offer(v, kind)
            wb, pbp = fair_at(others, kind, tb)
            eb = ev(wb + adj.get(kind, 0.0), pbp, pb)
            if best is None or eb > best[2]:
                best = (b, label(aw, hm, kind, v), eb, pb)
        sides[kind] = dict(kind=kind, label=label(aw, hm, kind, dk), price=price, w0=w0, w=w, adj=adj.get(kind, 0.0), p=p,
                           ev=ev(w, p, price), be=breakeven(p, price), fair=fair_price(w, p), best=best)
    picks = []
    for mk, pair in (("Spread", ("away", "home")), ("Total", ("over", "under")), ("Moneyline", ("away_ml", "home_ml"))):
        a, b = sides[pair[0]], sides[pair[1]]
        picks.append(dict(a if a["w"] >= b["w"] else b, market=mk, stale=(aw, hm) in STALE))
    for pk in picks[:2]:
        side = pk["kind"]
        now = dk[0] if pk["market"] == "Spread" else dk[3]          # expected home margin, or the total
        lab, det, _ = timing("spread" if pk["market"] == "Spread" else "total", side, now, float("nan"), None)
        pk["when"] = (lab, det)
    sp, to = picks[0], picks[1]
    (sp if sp["w"] >= to["w"] else to)["top"] = True
    g.update(sides=sides, picks=picks, win_a=sides["away_ml"]["w0"])
    games.append(g)
games.sort(key=lambda g: (g["ko"], g["rot"]))
listed = [dict(p, g=g) for g in games for p in g["picks"] if p["market"] != "Moneyline"]
n_pos = sum(round(p["ev"], 3) >= 0 and not p["g"]["stale"] for p in listed)
n_adj = sum(abs(p["adj"]) > 1e-9 for p in listed)


def e(s): return html.escape(str(s))
def slug(g): return f"g-{g['aw'].lower()}-{g['hm'].lower()}"
def day(d): return d.strftime("%A, %B ") + str(d.day)
def tm(d): return d.strftime("%I:%M").lstrip("0") + (" a.m." if d.hour < 12 else " p.m.")
def tier(x):
    x = round(x, 3)
    return ("value", "Beats the market") if x >= 0 else (("near", "Near fair") if x >= -0.025 else ("below", "Below fair"))
def pp(x): return ("+" if x >= 0 else "\u2212") + f"{abs(100 * x):.1f}"


def pbar(p):
    return (f'<div class="pbar" role="img" aria-label="Hits {fpct(p["w"])}, needs {fpct(p["be"])}">'
            f'<span class="fill" style="width:{100 * p["w"]:.1f}%"></span>'
            f'<span class="be" style="left:{100 * p["be"]:.1f}%"></span></div>')


def best_text(p):
    b = p["best"]; book = dict(BOOKS)[b[0]]
    if p["market"] == "Moneyline": return f"{book} {fp(b[3])}"
    if p["market"] == "Total": return f'{book} {"o" if b[1].startswith("Over") else "u"}{b[1].split(" ")[1]} {fp(b[3])}'
    return f'{book} {b[1].split(" ")[1]} {fp(b[3])}'


def pick_tile(p):
    cls, tname = tier(p["ev"])
    push = f' <span class="push">push {fpct(p["p"])}</span>' if p["p"] > 0 else ""
    adjline = (f'<p class="adj">Market {fpct(p["w0"])}, {pp(p["adj"])} from factors below</p>' if abs(p["adj"]) > 1e-9
               else '<p class="adj">Market price; no factor adjustment</p>')
    if p.get("stale"):
        adjline += '<p class="adj">Line has moved since; re-check</p>'
    top = '<p class="toppick">Stronger of this game\'s spread and total</p>' if p.get("top") else ""
    tline = f'<p class="timing"><strong>{e(p["when"][0])}.</strong> {e(p["when"][1])}</p>' if p.get("when") else ""
    return f'''<article class="pick {cls}">
  <h4>{p["market"]}</h4>
  <p class="bet"><mark>{e(p["label"])}</mark> <span class="price">{fp(p["price"])}</span></p>
  <p class="hit"><strong>{fpct(p["w"])}</strong> to hit{push}</p>
  {adjline}
  {pbar(p)}
  <dl>
    <div><dt>Needs to break even</dt><dd>{fpct(p["be"])}</dd></div>
    <div><dt>Fair price</dt><dd>{fp(p["fair"])}</dd></div>
    <div><dt>Edge at DraftKings</dt><dd class="edge">{fedge(p["ev"])}</dd></div>
    <div><dt>Best other app</dt><dd>{e(best_text(p))}</dd></div>
  </dl>
  <p class="tier">{tname}</p>{top}{tline}
</article>'''


ROWS = [("away", "spread"), ("home", "spread"), ("over", "total"), ("under", "total"), ("away_ml", "ml"), ("home_ml", "ml")]


def market_table(g):
    books = [(k, n) for k, n in BOOKS if k in g["bk"]]
    pick_kinds = {p["kind"] for p in g["picks"]}
    others = {b: x for b, x in g["bk"].items() if b != "draftkings"}
    head = "".join(f"<th scope='col'>{e(n)}</th>" for _, n in books)
    body = []
    for kind, grp in ROWS:
        s = g["sides"][kind]
        rowname = {"away": g["aw"], "home": g["hm"], "over": "Over", "under": "Under",
                   "away_ml": f'{g["aw"]} ML', "home_ml": f'{g["hm"]} ML'}[kind]
        ln, pr = cell_text(g["dk"], kind)
        cells = [f'<td class="{"dk picked" if kind in pick_kinds else "dk"}"><span class="l">{ln}</span> <span class="p">{pr}</span></td>']
        for k, _ in books:
            v = g["bk"][k]; ln2, pr2 = cell_text(v, kind); tb, pb = side_offer(v, kind)
            w, pq = fair_at(others, kind, tb)
            better = ev(w + s["adj"], pq, pb) > s["ev"] + 1e-9
            cells.append(f'<td class="{"better" if better else ""}"><span class="l">{ln2}</span> <span class="p">{pr2}</span></td>')
        sep = " grp" if kind in ("over", "away_ml") else ""
        body.append(f'<tr class="{grp}{sep}"><th scope="row">{e(rowname)}</th>{"".join(cells)}<td class="fair">{fpct(s["w"], 0)}</td></tr>')
    return f'''<div class="scroll"><table class="board">
<thead><tr><th scope="col"><span class="sr">Side</span></th><th scope="col" class="dkh">DraftKings</th>{head}<th scope="col">Chance</th></tr></thead>
<tbody>{"".join(body)}</tbody></table></div>'''


def factor_list(g):
    items = []
    for title, text, eff in g["factors"]:
        if eff:
            k, d = max(eff.items(), key=lambda kv: kv[1])
            who = {"away": g["aw"], "home": g["hm"], "over": "Over", "under": "Under"}[k]
            tag = f'<span class="ftag on">{pp(d)}% to {e(who)}</span>'
        else:
            tag = '<span class="ftag">No adjustment</span>'
        items.append(f'<li><span class="ft">{e(title)}</span>{tag}<span class="fx">{e(text)}</span></li>')
    return f'<ul class="factors">{"".join(items)}</ul>'


def game_block(g):
    aw, hm = g["aw"], g["hm"]
    stale = '<p class="stale">Line moved after Monday night. Re-check these prices before betting.</p>' if g["stale"] else ""
    notes = "".join(f"<li>{e(n)}</li>" for n in g["notes"])
    return f'''<section class="game" id="{slug(g)}" aria-labelledby="{slug(g)}-h">
<header class="ghead">
  <div class="rot" aria-hidden="true"><span>{g["rot"]}</span><span>{g["rot"] + 1}</span></div>
  <div class="teams">
    <h3 id="{slug(g)}-h"><span class="t">{e(NAMES[aw])}</span> <span class="rec">{REC[aw]}</span> <span class="at">at</span> <span class="t">{e(NAMES[hm])}</span> <span class="rec">{REC[hm]}</span></h3>
    <p class="when">{day(g["ko"])}, {tm(g["ko"])} ET on {e(g["tv"])}</p>
    <p class="where">{e(g["venue"])}. {e(g["roof"])}.</p>
  </div>
  <div class="winp" aria-label="Market chance to win">
    <div class="wbar"><span style="width:{100 * g["win_a"]:.1f}%"></span></div>
    <p><span>{aw} {fpct(g["win_a"], 0)}</span><span>{hm} {fpct(1 - g["win_a"], 0)}</span></p>
    <p class="open">Opened {e(g["opener"])}</p>
  </div>
</header>
{stale}
<ul class="notes">{notes}</ul>
<div class="picks">{"".join(pick_tile(p) for p in g["picks"])}</div>
<details class="fd" open><summary>Factors checked for this game</summary>{factor_list(g)}</details>
<details class="bd"><summary>Every app's price for this game</summary>{market_table(g)}</details>
</section>'''


def index_html():
    out, cur = [], None
    for g in games:
        d = day(g["ko"])
        if d != cur:
            if cur: out.append("</ol></div>")
            out.append(f'<div class="iday"><h3>{d}</h3><ol>'); cur = d
        out.append(f'<li><a href="#{slug(g)}"><span class="it">{tm(g["ko"])}</span> {g["aw"]} at {g["hm"]}</a></li>')
    out.append("</ol></div>")
    return "".join(out)


def rows_html():
    out = []
    for i, p in enumerate(sorted(listed, key=lambda p: -p["w"]), 1):
        g = p["g"]; cls, tname = tier(p["ev"])
        top = ' <span class="flag top">top</span>' if p.get("top") else ""
        adj = f'{pp(p["adj"])}' if abs(p["adj"]) > 1e-9 else "0.0"
        out.append(f'''<tr class="{cls}" data-market="{p["market"]}" data-top="{1 if p.get("top") else 0}" data-hit="{p["w"]:.5f}" data-edge="{p["ev"]:.5f}" data-ko="{g["ko"].isoformat()}{g["rot"]:04d}">
<td class="n">{i}</td><td class="pk"><mark>{e(p["label"])}</mark>{top}</td><td><a href="#{slug(g)}">{g["aw"]} at {g["hm"]}</a>{' <span class="flag">moved</span>' if g["stale"] else ""}</td>
<td class="ko">{g["ko"].strftime("%a")} {tm(g["ko"])}</td><td>{p["market"]}</td><td class="num">{fp(p["price"])}</td>
<td class="num hitc"><strong>{fpct(p["w"])}</strong>{f' <span class="push">+{fpct(p["p"], 0)} push</span>' if p["p"] else ""}</td>
<td class="num mk">{fpct(p["w0"])}</td><td class="num">{adj}</td><td class="num">{fpct(p["be"])}</td><td class="num edge">{fedge(p["ev"])}</td><td class="tiercell">{tname}</td><td class="wh">{e(p["when"][0])}</td></tr>''')
    return "".join(out)


best = sorted([p for p in listed if not p["g"]["stale"]], key=lambda p: -p["ev"])[:4]
lead = ", ".join(f'{e(p["label"])} {fp(p["price"])} ({fedge(p["ev"])})' for p in best)
CSS = open(HERE / "site.css").read() + open(HERE / "site2.css").read()
JS = open(HERE / "site2.js").read()
page = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Week 4 NFL picks at DraftKings, priced against the market</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Condensed:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style></head>
<body>
<a class="skip" href="#games">Skip to games</a>
<header class="top">
  <p class="kicker">NFL 2026, Week 4</p>
  <h1>Every DraftKings line this week, checked against seven other apps</h1>
  <p class="dek">Each pick is the side with the better chance of hitting, after adjusting the market's odds for weather, rest and early-season records where the history says the market leaves something on the table.</p>
  <div class="facts">
    <p><strong>{n_pos}</strong> of {len(listed)} spread and total picks beat DraftKings' price after adjustments.</p>
    <p><strong>{n_adj}</strong> picks moved by a researched factor, most by rain forecasts and 0-3 teams.</p>
    <p>Best edges: {lead}.</p>
  </div>
  <p class="snap">Prices: VegasInsider's multi-book table, captured September 29, 2026 (page last updated Sept. 28). Weather: MySportsWeather kickoff forecasts, Sept. 29. Injury news as of Sept. 29. Confirm every number in the DraftKings app before betting.</p>
</header>
<nav class="index" aria-label="Games by kickoff">{index_html()}</nav>
<aside class="legend" aria-label="How to read a pick">
  <p><mark>Highlighted</mark> is the side more likely to hit.</p>
  <p><span class="lg-bar"></span> Bar is the chance it hits; the tick is the break-even at DraftKings' price.</p>
  <p><span class="dot value"></span> Beats the market <span class="dot near"></span> Near fair (within 2.5%) <span class="dot below"></span> Below fair</p>
</aside>
<main id="games">
{"".join(game_block(g) for g in games)}
</main>
<section class="all" id="all" aria-labelledby="all-h">
  <h2 id="all-h">Every spread and total pick, by chance of hitting</h2>
  <div class="filters" role="group" aria-label="Filter picks">
    <button type="button" aria-pressed="true" data-f="all">Spreads and totals</button>
    <button type="button" aria-pressed="false" data-f="Spread">Spreads</button>
    <button type="button" aria-pressed="false" data-f="Total">Totals</button>
    <button type="button" aria-pressed="false" data-f="top">Top pick per game</button>
  </div>
  <div class="scroll"><table class="list" id="list">
  <thead><tr><th scope="col" class="n">#</th><th scope="col">Pick</th><th scope="col">Game</th><th scope="col" data-sort="ko"><button type="button">Kickoff</button></th><th scope="col">Market</th>
  <th scope="col" class="num">DK price</th><th scope="col" class="num" data-sort="hit" aria-sort="descending"><button type="button">Hits</button></th>
  <th scope="col" class="num">Market</th><th scope="col" class="num">Factors (%)</th><th scope="col" class="num">Needs</th>
  <th scope="col" class="num" data-sort="edge"><button type="button">Edge</button></th><th scope="col">Rating</th><th scope="col">When to bet</th></tr></thead>
  <tbody>{rows_html()}</tbody></table></div>
  <p class="tablenote">"Top" marks the stronger of each game's spread and total. Market is the other apps' no-vig chance; Factors is the adjustment in percentage points. "When to bet" follows how NFL lines usually move: late public money pushes favorites and overs up, so those are usually cheapest early, while underdogs and unders are often best close to kickoff.</p>
</section>
<footer class="method">
  <h2>How these numbers are made</h2>
  <p>The market chance comes from the other seven apps' prices with their margin removed, taking the middle value. When an app hangs a different number, its price is converted using how often games land exactly on that number (about 9% on 3 and 6.5% on 7).</p>
  <p>Factor adjustments only use situations where published records show the closing line missed something, and each is cut to a fraction of the historical edge because trends fade once they are known: rain at kickoff (unders 57.4% over 343 games), 0-2 teams in Week 3 (55.7% against the spread since 2003) and rest gaps of four days or more. Travel, body clock, short weeks, heat and injury news are shown but not adjusted, because the line already moves for them.</p>
  <p>The chance to hit is not the same as a good bet. A 51% side at −110 still loses money over time; the edge column is what matters. For information only, not financial advice. If betting stops being fun, call 1-800-GAMBLER.</p>
</footer>
<script>{JS}</script>
</body></html>'''
open(OUT / "week4_picks.html", "w").write(page)
print(len(listed), "listed;", n_pos, "positive;", n_adj, "adjusted")
for p in sorted(listed, key=lambda p: -p["ev"])[:8]:
    print(f'{p["g"]["aw"]}@{p["g"]["hm"]} {p["market"]:7} {p["label"]:12} {fp(p["price"])} hit {fpct(p["w"])} mkt {fpct(p["w0"])} edge {fedge(p["ev"])}{" TOP" if p.get("top") else ""}')
