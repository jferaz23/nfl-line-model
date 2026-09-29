"""Build the Week 4 DraftKings picks page from the multi-book snapshot in board.py."""
import html, json, math, statistics as st
from datetime import datetime
from board import G

BOOKS = [("bet365", "bet365"), ("betmgm", "BetMGM"), ("caesars", "Caesars"), ("fanduel", "FanDuel"),
         ("fanatics", "Fanatics"), ("betrivers", "BetRivers"), ("hardrock", "Hard Rock")]
NAMES = {"PIT": "Steelers", "CLE": "Browns", "IND": "Colts", "WAS": "Commanders", "LAR": "Rams", "PHI": "Eagles",
         "NE": "Patriots", "BUF": "Bills", "DAL": "Cowboys", "HOU": "Texans", "JAX": "Jaguars", "CIN": "Bengals",
         "NYJ": "Jets", "CHI": "Bears", "GB": "Packers", "TB": "Buccaneers", "TEN": "Titans", "BAL": "Ravens",
         "ARI": "Cardinals", "NYG": "Giants", "MIA": "Dolphins", "MIN": "Vikings", "DEN": "Broncos", "SF": "49ers",
         "KC": "Chiefs", "LV": "Raiders", "LAC": "Chargers", "SEA": "Seahawks", "DET": "Lions", "CAR": "Panthers",
         "ATL": "Falcons", "NO": "Saints"}
REC = {"PIT": "2-1", "CLE": "2-1", "IND": "1-2", "WAS": "1-2", "LAR": "1-2", "PHI": "2-1", "NE": "1-2", "BUF": "3-0",
       "DAL": "1-2", "HOU": "0-3", "JAX": "2-1", "CIN": "2-1", "NYJ": "1-2", "CHI": "2-1", "GB": "1-2", "TB": "0-3",
       "TEN": "0-3", "BAL": "2-1", "ARI": "1-2", "NYG": "2-1", "MIA": "0-3", "MIN": "3-0", "DEN": "2-1", "SF": "3-0",
       "KC": "3-0", "LV": "3-0", "LAC": "0-3", "SEA": "2-1", "DET": "2-1", "CAR": "1-2", "ATL": "1-2", "NO": "1-2"}
# rotation numbers, kickoff (ET), TV, venue, opener (BetMGM/Borgata), context
META = {
 ("PIT", "CLE"): (101, "2026-10-01 20:15", "Prime Video", "Huntington Bank Field, Cleveland", "Open air, grass",
   "PIT −2.5, total 38.5", [
   "Both teams are 2-1 after winning as home underdogs in Week 3: Pittsburgh beat Cincinnati 30-27 on two late Chris Boswell field goals, and Cleveland beat Carolina 21-18.",
   "Thursday night, so both teams are on a short week.",
   "Borgata reported the early money on Pittsburgh laying 2.5."]),
 ("IND", "WAS"): (251, "2026-10-04 09:30", "NFL Network", "Tottenham Hotspur Stadium, London", "Open air, artificial turf",
   "IND −3.5, total not posted", [
   "London game; Washington is the designated home team, so neither side has a real home crowd.",
   "Indianapolis got its first win, 19-17 over Houston on a field goal in the final seconds.",
   "Washington beat Seattle 33-31 as an 8.5-point underdog with backup QB Marcus Mariota starting."]),
 ("NE", "BUF"): (253, "2026-10-04 13:00", "CBS", "Highmark Stadium, Orchard Park", "Open air",
   "BUF −7, total 48.5", [
   "Buffalo is 3-0 both straight up and against the spread after beating the Chargers 24-16.",
   "New England was never in it at Jacksonville and lost 35-6.",
   "Books expect this to bounce between 6.5 and 7. DraftKings is on 7 while every other app shows 6.5."]),
 ("NYJ", "CHI"): (255, "2026-10-04 13:00", "FOX", "Soldier Field, Chicago", "Open air, grass",
   "CHI −3, total 43", [
   "Chicago is without QB Caleb Williams (hamstring). Case Keenum started Monday's 27-7 win over Philadelphia.",
   "Chicago played Monday night, so it is on a short week.",
   "The Jets rallied at Detroit but lost 31-24, pushing as 7-point underdogs."]),
 ("ARI", "NYG"): (257, "2026-10-04 13:00", "CBS", "MetLife Stadium, East Rutherford", "Open air, artificial turf",
   "NYG −2.5, total 43.5", [
   "The biggest move of the week: the Giants opened −2.5 and the market is now close to a pick'em.",
   "New York beat Tennessee 12-7 on four field goals without QB Jaxson Dart, who is now out for the regular season.",
   "Arizona lost 36-30 at San Francisco after pulling within two late."]),
 ("DAL", "HOU"): (259, "2026-10-04 13:00", "FOX", "NRG Stadium, Houston", "Retractable roof, artificial turf",
   "HOU −1.5, total 47", [
   "Houston is 0-3 after a 19-17 loss at Indianapolis on a last-second field goal.",
   "Dallas lost 34-31 to Baltimore in Rio de Janeiro on a 56-yard field goal with one second left, and comes back from Brazil.",
   "The spread has moved a point toward Houston since opening."]),
 ("JAX", "CIN"): (261, "2026-10-04 13:00", "CBS", "Paycor Stadium, Cincinnati", "Open air, artificial turf",
   "CIN −2.5, total 50", [
   "Highest total on the board, up from 50 at open.",
   "Jacksonville routed New England 35-6.",
   "Cincinnati lost 30-27 at Pittsburgh as a 3.5-point favorite."]),
 ("GB", "TB"): (263, "2026-10-04 13:00", "FOX", "Raymond James Stadium, Tampa", "Open air, grass",
   "GB −3.5, total 41.5", [
   "Tampa Bay QB Baker Mayfield dislocated his right thumb late in Week 3 and will miss at least three weeks.",
   "Green Bay played last Thursday (a 35-14 loss to Atlanta), so it comes in with 10 days of rest.",
   "Tampa Bay is 0-3 after a 23-16 loss to Minnesota. The total has dropped two points since open."]),
 ("LAR", "PHI"): (265, "2026-10-04 13:00", "FOX", "Lincoln Financial Field, Philadelphia", "Open air, grass",
   "LAR −2.5, total 46", [
   "Philadelphia lost 27-7 at Chicago on Monday night and is on a short week.",
   "The Rams led 16-0 at halftime in Denver on Sunday night and lost 30-26.",
   "After Monday's game DraftKings moved to Rams −2.5 (−120) and cut the total to 44.5 (over −115). The prices below are from before that move."]),
 ("TEN", "BAL"): (267, "2026-10-04 13:00", "CBS", "M&T Bank Stadium, Baltimore", "Open air, grass",
   "BAL −11.5, total 43.5", [
   "Baltimore beat Dallas 34-31 in Rio on a 56-yard Tyler Loop field goal and comes back from Brazil.",
   "Tennessee is 0-3 and didn't score until the final minutes of a 12-7 loss to the Giants.",
   "Biggest spread of the week. The first move was toward Tennessee."]),
 ("MIA", "MIN"): (269, "2026-10-04 16:05", "FOX", "U.S. Bank Stadium, Minneapolis", "Dome, artificial turf",
   "MIN −10.5, total 43", [
   "Minnesota is 3-0 with Kyler Murray back from a concussion; it won 23-16 at Tampa Bay.",
   "Miami is 0-3 after a 24-10 loss to Kansas City.",
   "The total has fallen about four points since open."]),
 ("DEN", "SF"): (271, "2026-10-04 16:25", "CBS", "Levi's Stadium, Santa Clara", "Open air, grass",
   "SF −3, total 45.5", [
   "San Francisco is 3-0 after a 36-30 win over Arizona.",
   "Denver trailed the Rams 16-0 at halftime on Sunday night and won 30-26.",
   "DraftKings hangs 3 where most apps show 2.5, so check which side of the key number you want."]),
 ("KC", "LV"): (273, "2026-10-04 16:25", "CBS", "Allegiant Stadium, Las Vegas", "Dome, grass",
   "KC −5, total not posted", [
   "Both teams are 3-0. Las Vegas and Kirk Cousins came back to beat New Orleans 35-27.",
   "Kansas City beat Miami 24-10 but failed to cover as a 9.5-point favorite.",
   "Opened Kansas City −5 and has settled at −4.5."]),
 ("LAC", "SEA"): (275, "2026-10-04 16:25", "CBS", "Lumen Field, Seattle", "Open air, artificial turf",
   "SEA −7, total 45", [
   "Seattle lost 33-31 at Washington as an 8.5-point favorite; Sam Darnold returned from a glute injury but threw a late pick-six.",
   "The Chargers are 0-3 after a 24-16 loss at Buffalo.",
   "The total has dropped from 45 at open."]),
 ("DET", "CAR"): (277, "2026-10-04 20:20", "NBC", "Bank of America Stadium, Charlotte", "Open air",
   "DET −3, total 49.5", [
   "Detroit beat the Jets 31-24 on a Jahmyr Gibbs touchdown with 2:25 left.",
   "Carolina lost 21-18 at Cleveland on a late touchdown.",
   "The line has moved off 3 to 3.5; Borgata reported early support for Carolina as the home underdog."]),
 ("ATL", "NO"): (279, "2026-10-05 20:15", "ESPN / ABC", "Caesars Superdome, New Orleans", "Dome, artificial turf",
   "NO −2.5, total 46.5", [
   "Atlanta played last Thursday and beat Green Bay 35-14 with Michael Penix back at QB and 194 rushing yards from Bijan Robinson; it has 11 days of rest.",
   "New Orleans led Las Vegas 27-16 in the third quarter and lost 35-27.",
   "The total is up two points since open."]),
}
STALE = {("LAR", "PHI")}


def imp(a): return 100 / (a + 100) if a > 0 else -a / (-a + 100)
def dec(a): return 1 + a / 100 if a > 0 else 1 + 100 / (-a)
SPM = {0: .003, 1: .035, 2: .035, 3: .090, 4: .045, 5: .030, 6: .055, 7: .065, 8: .035, 9: .020, 10: .045,
       11: .025, 12: .015, 13: .020, 14: .040}
def mass_sp(k): return SPM.get(abs(k), .02)
def mass_tot(k): return .035 if abs(k) in (37, 41, 43, 44, 47, 51) else .028


def cover(anchor_t, w_half, t, mass):
    if t < anchor_t:
        w = w_half + sum(mass(k) for k in range(math.floor(t) + 1, math.floor(anchor_t) + 1))
    else:
        w = w_half - sum(mass(k) for k in range(math.floor(anchor_t) + 1, math.floor(t) + 1))
    return w, (mass(int(t)) if float(t).is_integer() else 0.0)


def to_half(t, q, mass):
    if float(t).is_integer():
        m = mass(int(t))
        return t - 0.5, q * (1 - m) + m
    return t, q


def side_offer(v, kind):
    """(threshold t, price) for one book: side wins iff V > t."""
    if kind == "away": return -v[0], v[1]
    if kind == "home": return v[0], v[2]
    if kind == "over": return v[3], v[4]
    if kind == "under": return -v[3], v[5]
    if kind == "away_ml": return 0.0, v[6]
    return 0.0, v[7]


def novig(v, kind):
    if kind in ("away", "home"):
        a, h = imp(v[1]), imp(v[2]); return a / (a + h) if kind == "away" else h / (a + h)
    if kind in ("over", "under"):
        o, u = imp(v[4]), imp(v[5]); return o / (o + u) if kind == "over" else u / (o + u)
    a, h = imp(v[6]), imp(v[7]); return a / (a + h) if kind == "away_ml" else h / (a + h)


def fair_at(others, kind, t):
    if kind.endswith("ml"):
        return st.median(novig(v, kind) for v in others.values()), 0.0
    mass = mass_sp if kind in ("away", "home") else mass_tot
    est = []
    for v in others.values():
        tb, _ = side_offer(v, kind)
        at, w = to_half(tb, novig(v, kind), mass)
        est.append(cover(at, w, t, mass))
    return st.median(e[0] for e in est), st.median(e[1] for e in est)


def ev(w, p, price): return w * (dec(price) - 1) - (1 - w - p)
def breakeven(p, price): return (1 - p) / dec(price)
def fair_price(w, p):
    q = w / (1 - p)
    return round(-100 * q / (1 - q)) if q >= .5 else round(100 * (1 - q) / q)


def fl(x):
    if x == 0: return "PK"
    s = f"{abs(x):g}"
    return ("+" if x > 0 else "\u2212") + s
def fp(a): return ("+" if a > 0 else "\u2212") + str(abs(int(a)))
def fpct(x, d=1): return f"{100 * x:.{d}f}%"
def fedge(x): return ("+" if x >= 0 else "\u2212") + f"{abs(100 * x):.1f}%"
def tier(e):
    e = round(e, 3)
    if e >= 0: return ("value", "Beats the market")
    if e >= -0.025: return ("near", "Near fair")
    return ("below", "Below fair")


def label(aw, hm, kind, v):
    if kind == "away": return f"{aw} {fl(v[0])}"
    if kind == "home": return f"{hm} {fl(-v[0])}"
    if kind == "over": return f"Over {v[3]:g}"
    if kind == "under": return f"Under {v[3]:g}"
    return f"{aw if kind == 'away_ml' else hm} ML"


def cell_text(v, kind):
    if kind == "away": return fl(v[0]), fp(v[1])
    if kind == "home": return fl(-v[0]), fp(v[2])
    if kind == "over": return f"o{v[3]:g}", fp(v[4])
    if kind == "under": return f"u{v[3]:g}", fp(v[5])
    return "", fp(v[6] if kind == "away_ml" else v[7])


