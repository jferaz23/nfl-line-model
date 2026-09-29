from pathlib import Path as _P
HERE = _P(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "reports" / "site"
OUT.mkdir(parents=True, exist_ok=True)
import math, statistics as st, csv
from board import G
def imp(a): return 100/(a+100) if a>0 else -a/(-a+100)
def dec(a): return 1+a/100 if a>0 else 1+100/(-a)
# approx P(final margin lands exactly on k) when the spread is near k (post-2015 NFL; 3 and 7 are the key numbers)
SPM = {0:.003,1:.035,2:.035,3:.090,4:.045,5:.030,6:.055,7:.065,8:.035,9:.020,10:.045,11:.025,12:.015,13:.020,14:.040}
def mass_sp(k): return SPM.get(abs(k), .02)
def mass_tot(k): return .035 if k in (37,41,43,44,47,51) else .028
def cover(anchor_t, w_half, t, mass):
    """P(V>t), P(V=t) given P(V>anchor_t)=w_half at a half-point anchor_t."""
    if t < anchor_t:
        w = w_half + sum(mass(k) for k in range(math.floor(t)+1, math.floor(anchor_t)+1))
    else:
        w = w_half - sum(mass(k) for k in range(math.floor(anchor_t)+1, math.floor(t)+1))
    p = mass(int(t)) if float(t).is_integer() else 0.0
    return w, p
def to_half(t, q, mass):
    """book line t with no-vig q (conditional on no push) -> (half-point anchor, P(V>anchor))"""
    if float(t).is_integer():
        m = mass(int(t)); w = q*(1-m)
        return t-0.5, w+m          # P(V > t-0.5) = P(V>t) + P(V=t)
    return t, q
rows=[]
for (aw,hm,when),bk in G.items():
    dk = bk["draftkings"]; others = {b:v for b,v in bk.items() if b!="draftkings"}
    offers = []
    # spread: V = margin for that side; side covers handicap h iff V > -h
    for side,sgn,pi in (("away",1,1),("home",-1,2)):
        h = dk[0]*sgn; offers.append(("spread", f"{aw if side=='away' else hm} {h:+g}", dk[pi], "sp", side, h))
    offers.append(("total", f"Over {dk[3]:g}", dk[4], "ov", None, dk[3]))
    offers.append(("total", f"Under {dk[3]:g}", dk[5], "un", None, dk[3]))
    offers.append(("moneyline", f"{aw} ML", dk[6], "mla", None, None))
    offers.append(("moneyline", f"{hm} ML", dk[7], "mlh", None, None))
    for mk,label,price,kind,side,h in offers:
        ests=[]
        for b,v in others.items():
            if kind=="sp":
                pa,ph = imp(v[1]),imp(v[2]); qa = pa/(pa+ph)
                bh = v[0] if side=="away" else -v[0]; q = qa if side=="away" else 1-qa
                at,w = to_half(-bh, q, mass_sp); w2,p2 = cover(at, w, -h, mass_sp)
            elif kind in ("ov","un"):
                po,pu = imp(v[4]),imp(v[5]); q = po/(po+pu) if kind=="ov" else pu/(po+pu)
                t_b = v[3] if kind=="ov" else -v[3]; t = h if kind=="ov" else -h
                at,w = to_half(t_b, q, mass_tot); w2,p2 = cover(at, w, t, mass_tot)
            else:
                pa,ph = imp(v[6]),imp(v[7]); w2 = (pa if kind=="mla" else ph)/(pa+ph); p2 = 0.0
            ests.append((w2,p2))
        w = st.median(e[0] for e in ests); p = st.median(e[1] for e in ests)
        ev = w*(dec(price)-1) - (1-w-p)
        fair = w/(w+(1-w-p))
        fair_am = -100*fair/(1-fair) if fair>=.5 else 100*(1-fair)/fair
        rows.append(dict(game=f"{aw} @ {hm}", kickoff=when, market=mk, bet=label, dk_price=price,
                         fair_win=round(w,4), push=round(p,3), fair_price=round(fair_am), ev_pct=round(100*ev,2)))
rows.sort(key=lambda r:-r["ev_pct"])
with open(OUT / "dk_week4_vs_other_books.csv","w",newline="") as f:
    wr=csv.DictWriter(f, fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)
print(f"{len(rows)} DK offers. EV>0: {sum(r['ev_pct']>0 for r in rows)}")
for r in rows[:14]: print(r)
print("...worst:"); 
for r in rows[-4:]: print(r)
import collections
print("median EV by market", {m: st.median(r['ev_pct'] for r in rows if r['market']==m) for m in ('spread','total','moneyline')})
