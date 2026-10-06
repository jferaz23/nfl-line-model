/* NFL Line Model: renders window.SITE (built by build_site.py). No framework, no build step. */
(function () {
  "use strict";
  const S = window.SITE || {};
  const view = document.getElementById("view");
  const NAMES = {
    ARI: "Arizona Cardinals", ATL: "Atlanta Falcons", BAL: "Baltimore Ravens", BUF: "Buffalo Bills", CAR: "Carolina Panthers",
    CHI: "Chicago Bears", CIN: "Cincinnati Bengals", CLE: "Cleveland Browns", DAL: "Dallas Cowboys", DEN: "Denver Broncos",
    DET: "Detroit Lions", GB: "Green Bay Packers", HOU: "Houston Texans", IND: "Indianapolis Colts", JAX: "Jacksonville Jaguars",
    KC: "Kansas City Chiefs", LA: "Los Angeles Rams", LAC: "Los Angeles Chargers", LV: "Las Vegas Raiders", MIA: "Miami Dolphins",
    MIN: "Minnesota Vikings", NE: "New England Patriots", NO: "New Orleans Saints", NYG: "New York Giants", NYJ: "New York Jets",
    PHI: "Philadelphia Eagles", PIT: "Pittsburgh Steelers", SEA: "Seattle Seahawks", SF: "San Francisco 49ers", TB: "Tampa Bay Buccaneers",
    TEN: "Tennessee Titans", WAS: "Washington Commanders"
  };
  const BOOKS = { draftkings: "DraftKings", fanduel: "FanDuel", betmgm: "BetMGM", williamhill_us: "Caesars", pinnacle: "Pinnacle",
    lowvig: "LowVig", betonlineag: "BetOnline", novig: "Novig", prophetx: "ProphetX", fanatics: "Fanatics", espnbet: "ESPN BET",
    betrivers: "BetRivers", hardrockbet: "Hard Rock" };
  const GROUP_LABELS = {
    baseline: "Average game", team_strength: "Team strength", home_field: "Home field", quarterback: "Quarterbacks",
    injuries: "Injuries beyond the QB", weather: "Weather", rest_travel: "Rest and travel", time_of_day: "Kickoff time and body clock",
    scheme_matchup: "Scheme matchup", venue_history: "Venue history", surface_altitude: "Surface and altitude", coaching: "Coaching",
    officials: "Officials", history: "Head-to-head and ATS history", situational: "Situational and luck", drive_efficiency: "Drive efficiency",
    motivation: "Motivation (late season)", early_down: "Early-down efficiency", big_plays: "Big plays",
    roster_continuity: "Offseason roster turnover (weeks 1-8)", scoring_env: "Scoring environment", calendar: "Calendar", market_view: "Market's recent view of both teams (25% blend)"
  };

  // ------------------------------------------------------------------ helpers
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fin = x => typeof x === "number" && isFinite(x);
  const pct = (p, d = 0) => fin(p) ? (100 * p).toFixed(d) + "%" : "–";
  const num = (x, d = 1) => fin(x) ? x.toFixed(d) : "–";
  const sgn = (x, d = 1) => fin(x) ? (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d) : "–";
  const am = x => fin(x) ? (x > 0 ? "+" + Math.round(x) : "−" + Math.abs(Math.round(x))) : "–";
  const trim = x => (Math.round(x * 10) / 10).toString();
  const hcap = x => !fin(x) ? "–" : Math.abs(x) < 1e-9 ? "pk" : (x > 0 ? "+" : "−") + trim(Math.abs(x));
  const logoCode = t => ({ LA: "lar", WAS: "wsh" }[t] || String(t).toLowerCase());
  const logo = t => `https://a.espncdn.com/i/teamlogos/nfl/500/${logoCode(t)}.png`;
  const team = (t, extra = "", lg = false) => `<span class="team${lg ? " lg" : ""}"><img src="${logo(t)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">${esc(t)}${extra}</span>`;
  const ET = { timeZone: "America/New_York" };
  const dt = s => s ? new Date(s) : null;
  const fmtDay = d => d ? d.toLocaleDateString("en-US", { ...ET, weekday: "short" }) : "";
  const fmtTime = d => d ? d.toLocaleTimeString("en-US", { ...ET, hour: "numeric", minute: "2-digit" }) : "";
  const fmtLong = d => d ? d.toLocaleDateString("en-US", { ...ET, weekday: "long", month: "short", day: "numeric" }) : "";
  const fmtStamp = d => d ? d.toLocaleString("en-US", { ...ET, month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + " ET" : "";
  const kick = g => `${fmtDay(dt(g.kickoff_utc))} ${fmtTime(dt(g.kickoff_utc))}`;
  const implied = a => !fin(a) ? NaN : a < 0 ? -a / (-a + 100) : 100 / (a + 100);
  const noVig = (a, b) => { const x = implied(a), y = implied(b); return fin(x) && fin(y) ? x / (x + y) : NaN; };
  const toAm = p => !fin(p) || p <= 0 || p >= 1 ? NaN : p >= 0.5 ? -100 * p / (1 - p) : 100 * (1 - p) / p;
  const dec = a => a > 0 ? 1 + a / 100 : 1 + 100 / -a;
  const favLine = (h, a, m) => !fin(m) ? "–" : Math.abs(m) < 0.05 ? "Pick'em" : (m > 0 ? h : a) + " −" + trim(Math.abs(m));
  const val = p => p && fin(p.value) ? `${sgn(100 * p.value, 1)} pts` : "–";
  // edges round down so a 3.96-point edge never reads as the 4-point Top-pick line
  const edgeTxt = e => fin(e) ? "+" + (Math.floor(Math.abs(e) * 10) / 10).toFixed(1) : "–";
  const recTxt = r => r && r.n ? `<span class="w">${r.w}</span>-<span class="l">${r.l}</span>${r.p ? `<span class="p">-${r.p}</span>` : ""}` : '<span class="dash">0-0</span>';
  const recSub = r => r && r.n ? `${pct(r.pct, 1)}${fin(r.units) ? ` · ${sgn(r.units, 1)}u` : ""}` : "no graded picks yet";
  const GREEN_HELP = "Green = the chance to win is at least 1 point above what DraftKings' price needs to break even (−110 needs 52.4%), and the model's side has won more than it lost in that range. Ranked by that margin: the best bang for your buck. Top pick = any spread where the model is 4+ points off DraftKings' line (always shown green).";

  // ------------------------------------------------------------------ data prep
  const weekKeys = Object.keys(S.weeks || {}).sort();
  const curKey = weekKeys[weekKeys.length - 1];
  const live = {};
  ((S.live || {}).games || []).forEach(x => { live[`${x.season}-${x.week}-${x.home_team}-${x.away_team}`] = x; });
  const liveFor = g => live[`${g.season}-${g.week}-${g.home_team}-${g.away_team}`];
  const ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl";
  const normTeam = a => ({ WSH: "WAS", LAR: "LA", JAC: "JAX" }[a] || a);
  let lastLive = S.live && S.live.checked ? new Date(S.live.checked) : null, pollTimer = null;
  function parseEvent(ev, season, week) {
    const c = (ev.competitions || [{}])[0], comp = {};
    (c.competitors || []).forEach(x => comp[x.homeAway] = x);
    const st = (ev.status || {}).type || {}, sit = c.situation || {};
    const idTeam = {}; (c.competitors || []).forEach(x => idTeam[x.team && x.team.id] = normTeam(x.team && x.team.abbreviation));
    return { espn_id: ev.id, season, week, home_team: normTeam(comp.home && comp.home.team.abbreviation), away_team: normTeam(comp.away && comp.away.team.abbreviation),
      state: st.state, completed: !!st.completed, detail: st.shortDetail, period: (ev.status || {}).period, clock: (ev.status || {}).displayClock,
      home_score: comp.home ? +comp.home.score : null, away_score: comp.away ? +comp.away.score : null,
      broadcast: (c.broadcasts || []).map(b => (b.names || []).join(", ")).join(", "),
      possession: sit.possession ? idTeam[sit.possession] : null, down: sit.downDistanceText || sit.shortDownDistanceText || "",
      redzone: !!sit.isRedZone, last_play: sit.lastPlay && sit.lastPlay.text, kickoff_utc: ev.date };
  }
  async function pollScores() {
    const W = S.weeks[curKey]; if (!W) return;
    try {
      const d = await fetch(`${ESPN}/scoreboard?dates=${W.season}&seasontype=2&week=${W.week}`, { cache: "no-store" }).then(r => r.json());
      (d.events || []).forEach(ev => { const x = parseEvent(ev, W.season, W.week); live[`${x.season}-${x.week}-${x.home_team}-${x.away_team}`] = Object.assign(live[`${x.season}-${x.week}-${x.home_team}-${x.away_team}`] || {}, x); });
      lastLive = new Date();
      W.games.forEach(g => { delete g._d; });
      onLive();
    } catch (e) { /* keep the last scores; try again next tick */ }
    schedulePoll();
  }
  function schedulePoll() {
    clearTimeout(pollTimer);
    const W = S.weeks[curKey]; if (!W) return;
    const now = Date.now(), gs = W.games.map(g => ({ g, l: liveFor(g) }));
    const inPlay = gs.some(x => x.l && x.l.state === "in");
    const soon = gs.some(x => { const k = +new Date(x.g.kickoff_utc); return k - now < 3 * 3600e3 && k - now > -5 * 3600e3 && !(x.l && x.l.completed); });
    pollTimer = setTimeout(pollScores, inPlay ? 15000 : soon ? 60000 : 300000);
  }
  const REC = S.record || {};
  const graded = {};
  (REC.live || []).forEach(p => { if (p.result) graded[p.game_id + "|" + p.market] = p.result; });

  function records() {
    const r = {};
    const add = (t, k) => { r[t] = r[t] || { w: 0, l: 0, t: 0 }; r[t][k]++; };
    (S.schedule && S.schedule.games || []).forEach(g => {
      if (g.game_type !== "REG") return;
      let hs = g.home_score, as = g.away_score;
      const lv = liveFor(g);
      if ((hs == null) && lv && lv.completed) { hs = lv.home_score; as = lv.away_score; }
      if (hs == null || as == null) return;
      if (hs > as) { add(g.home_team, "w"); add(g.away_team, "l"); }
      else if (as > hs) { add(g.away_team, "w"); add(g.home_team, "l"); }
      else { add(g.home_team, "t"); add(g.away_team, "t"); }
    });
    return r;
  }
  const TREC = records();
  const recText = t => { const x = TREC[t]; return x ? `${x.w}-${x.l}${x.t ? "-" + x.t : ""}` : "0-0"; };

  function derive(W, g) {
    if (g._d) return g._d;
    const h = g.home_team, a = g.away_team;
    const pk = m => (W.picks || []).find(p => p.game_id === g.game_id && p.market === m) || null;
    const d = { h, a, sp: pk("spread"), tt: pk("total"), wn: pk("winner") };
    d.dkMargin = fin(g.dk_home_spread) ? -g.dk_home_spread : null;
    const board = (W.board || []).filter(b => b.game_id === g.game_id);
    const fair = p => { if (!p) return NaN; const b = board.find(x => x.bet === p.bet); return b ? b.p_win / Math.max(b.p_win + b.p_lose, 1e-9) : NaN; };
    d.fair = fair;
    d.pHome = g.p_home_win; d.pHomeMkt = fin(g.dk_home_ml) ? noVig(g.dk_home_ml, g.dk_away_ml) : g.p_home_win_market;
    const T = g.model_total, M = g.model_margin;
    d.mh = (T + M) / 2; d.ma = (T - M) / 2;
    if (fin(g.dk_total) && fin(d.dkMargin)) { d.vh = (g.dk_total + d.dkMargin) / 2; d.va = (g.dk_total - d.dkMargin) / 2; }
    d.lv = liveFor(g);
    d.final = d.lv && d.lv.completed ? [d.lv.home_score, d.lv.away_score] : null;
    d.res = p => { if (!p) return null; const r = graded[g.game_id + "|" + p.market]; if (r) return r;
      return d.final ? gradePick(p, d.final[0], d.final[1]) : null; };
    d.status = p => p && d.lv && d.lv.state === "in" ? liveStatus(p, d.lv.home_score, d.lv.away_score) : "";
    g._d = d;
    return d;
  }
  const resChip = r => r ? `<span class="chip ${r}">${r}</span>` : "";
  function pickMargin(p, hs, as) {
    if (p.market === "total" || p.market === "wind") return (hs + as - p.line) * (p.side === "over" ? 1 : -1);
    const m = p.side === "home" ? hs - as : as - hs;
    return m + (p.market === "spread" || p.teased != null ? (p.teased != null ? p.teased : p.line) : 0);
  }
  const gradePick = (p, hs, as) => { const x = pickMargin(p, hs, as); return x > 1e-9 ? "W" : x < -1e-9 ? "L" : "P"; };
  function liveStatus(p, hs, as) {
    const x = pickMargin(p, hs, as);
    return x > 0 ? `<span class="lstat up">winning by ${trim(x)}</span>` : x < 0 ? `<span class="lstat dn">behind by ${trim(-x)}</span>` : `<span class="lstat">even</span>`;
  }

  // ------------------------------------------------------------------ chrome
  function header() {
    const built = dt(S.built);
    const nBad = (S.checks || []).filter(c => !c[1]).length;
    const Wk = S.weeks[curKey] || {};
    const ago = x => { if (!x) return "–"; const m = Math.round((Date.now() - x) / 60000); return m < 1 ? "just now" : m < 60 ? m + " min ago" : Math.round(m / 60) + " h ago"; };
    document.getElementById("updated").innerHTML =
      `Prices ${esc(ago(dt(Wk.priced_at || Wk.generated)))} <span class="muted small">(${esc(Wk.price_source || "")})</span> · Model ${esc(ago(dt(Wk.generated)))} · Scores ${esc(ago(lastLive))} ` +
      (nBad ? `<a class="badge bad" href="#info">! ${nBad} check${nBad > 1 ? "s" : ""} failing</a>` : `<a class="badge" href="#info">✓ Checks pass</a>`) +
      (S.weeks && S.weeks[curKey] && S.weeks[curKey].demo ? ` <span class="badge bad">Synthetic demo data</span>` : "");
    const A = (REC.all || {}).total || {}, C = (REC.season || {}).total || {};
    const TZ = Object.assign({ p: 0 }, (REC.teasers || {}).teasers || {});
    const W = S.weeks[curKey];
    const nFinal = W ? W.games.filter(g => { const l = liveFor(g); return l && l.completed; }).length : 0;
    const k = (key, label) => `<a class="kpi" href="#record"><div class="kl">${label}</div><div class="kv">${recTxt(A[key])}</div>
      <div class="ks">${recSub(A[key])}</div><div class="ks">${esc(String(REC.current_season || ""))}: ${C[key] && C[key].n ? `${C[key].w}-${C[key].l}${C[key].p ? "-" + C[key].p : ""}` : "0-0"}</div></a>`;
    document.getElementById("kpis").innerHTML = `
      <div class="kpi"><div class="kl">Week ${W ? W.week : ""}</div><div class="kv">${nFinal}/${W ? W.games.length : 0}</div><div class="ks">games final</div><div class="ks">record since ${esc(String(REC.since || ""))} →</div></div>
      <a class="kpi kpi-green" href="#record"><div class="kl">Weekly card</div><div class="kv">${recTxt(REC.card)}</div><div class="ks">${recSub(REC.card)}</div><div class="ks">Top picks, teasers, wind unders</div></a>
      ${k("top", "Top picks")}<a class="kpi" href="#record"><div class="kl">Teasers</div><div class="kv">${recTxt(TZ)}</div><div class="ks">${TZ && TZ.n ? pct(TZ.pct, 1) + " · " + sgn(TZ.units, 1) + "u" : ""}</div><div class="ks">2-team, 6 points</div></a>
      ${k("green", "Green picks")}${k("winner", "Winners")}`;
  }

  const THEME_KEY = "nflmodel-theme";
  function theme() {
    const btn = document.getElementById("theme"), root = document.documentElement;
    const label = () => { btn.textContent = root.dataset.theme === "light" ? "☀ Light" : "☾ Dark"; btn.setAttribute("aria-label", "Switch to " + (root.dataset.theme === "light" ? "dark" : "light") + " mode"); };
    if (!root.dataset.theme) root.dataset.theme = "dark";
    label();
    btn.onclick = () => {
      root.dataset.theme = root.dataset.theme === "light" ? "dark" : "light";
      try { localStorage.setItem(THEME_KEY, root.dataset.theme); } catch (e) { }
      label();
    };
  }

  // ------------------------------------------------------------------ shared pieces
  function bar(kind, leftLabel, leftP, rightLabel) {
    if (!fin(leftP)) return `<div class="bar ${kind}"><span class="lo" style="width:100%">no price</span></div>`;
    const lw = Math.max(0, Math.min(100, 100 * leftP)), hiLeft = leftP >= 0.5;
    return `<div class="bar ${kind}"><span class="a ${hiLeft ? "hi" : "lo"}" style="width:${lw}%">${esc(leftLabel)} ${pct(leftP)}</span>` +
      `<span class="b ${hiLeft ? "lo" : "hi"}" style="width:${100 - lw}%">${esc(rightLabel)} ${pct(1 - leftP)}</span></div>`;
  }

  function lineMove(g) {
    const L = (S.lines || {})[g.game_id];
    const pts = L && L.points ? L.points.map(p => p[1]).filter(fin) : [];
    const nowS = fin(g.dk_home_spread) ? g.dk_home_spread : pts.length ? pts[pts.length - 1] : NaN;
    const openS = pts.length ? pts[0] : NaN;                      // this week's opening line (first one logged)
    if (!fin(nowS) || !fin(openS)) return "";
    const tPts = L && L.points ? L.points.map(p => p[2]).filter(fin) : [];
    const nowT = fin(g.dk_total) ? g.dk_total : tPts.length ? tPts[tPts.length - 1] : NaN;
    const openT = tPts.length ? tPts[0] : NaN;
    const series = [openS].concat(pts, [nowS]);
    const W_ = 70, H_ = 18, lo = Math.min(...series), hi = Math.max(...series), span = Math.max(hi - lo, 1);
    const xy = series.map((v, i) => `${(W_ * i / Math.max(series.length - 1, 1)).toFixed(1)},${(2 + (H_ - 4) * (v - lo) / span).toFixed(1)}`).join(" ");
    const d = nowS - openS, mv = Math.abs(d) < 1e-9 ? "no move" : `${d < 0 ? "toward" : "away from"} ${g.home_team} ${trim(Math.abs(d))}`;
    return `<div class="lmove" title="DraftKings spread for ${esc(g.home_team)}: opened this week at ${hcap(openS)}, now ${hcap(nowS)}${L && fin(L.open_spread) && L.open_spread !== openS ? ` (first posted before the season at ${hcap(L.open_spread)})` : ""}">
      <svg viewBox="0 0 ${W_} ${H_}" width="${W_}" height="${H_}" aria-hidden="true"><polyline points="${xy}" fill="none" stroke="var(--vegas)" stroke-width="1.6"/></svg>
      <span>${esc(g.home_team)} opened ${hcap(openS)} → now ${hcap(nowS)} <span class="muted">(${mv})</span>${fin(openT) && fin(nowT) ? ` · total ${trim(openT)} → ${trim(nowT)}` : ""}</span></div>`;
  }

  function lineChart(gid, g, kind) {
    const L = (S.lines || {})[gid];
    if (!L || !L.points || L.points.length < 1) return `<p class="note">Line history starts once the line watch has logged this game.</p>`;
    const pts = L.points.map(p => ({ t: +new Date(p[0]), v: kind === "total" ? p[2] : p[1] })).filter(p => fin(p.v));
    if (!pts.length) return `<p class="note">No line logged yet.</p>`;
    const open = pts[0].v;                                         // this week's opening line
    const first = kind === "total" ? L.open_total : L.open_spread;  // DraftKings' first posted line (often months earlier)
    pts[0].open = true;
    const model = kind === "total" ? g.model_total : -g.model_margin;
    const now = Date.now(), ko = +new Date(g.kickoff_utc);
    pts.push({ t: Math.max(Math.min(now, ko), pts[pts.length - 1].t), v: pts[pts.length - 1].v });
    const W_ = 560, H_ = 120, pl = 58, pr = 96, pt = 14, pb = 22;
    const t0 = pts[0].t, t1 = Math.max(pts[pts.length - 1].t, t0 + 1);
    const vals = pts.map(p => p.v).concat(fin(model) ? [model] : []);
    let lo = Math.min(...vals), hi = Math.max(...vals); if (hi - lo < 2) { lo -= 1; hi += 1; }
    const x = t => pl + (W_ - pl - pr) * (t - t0) / (t1 - t0), y = v => pt + (H_ - pt - pb) * (hi - v) / (hi - lo);
    let d = `M${x(pts[0].t)},${y(pts[0].v)}`;
    for (let i = 1; i < pts.length; i++) d += `H${x(pts[i].t)}V${y(pts[i].v)}`;
    const lbl = v => kind === "total" ? trim(v) : `${g.home_team} ${hcap(v)}`;
    const last = pts[pts.length - 1].v;
    return `<svg class="chart" viewBox="0 0 ${W_} ${H_}" role="img" aria-label="${kind} line history">
      ${fin(model) ? `<line x1="${pl}" x2="${W_ - pr}" y1="${y(model)}" y2="${y(model)}" stroke="var(--model)" stroke-dasharray="4 4" stroke-width="1.5"/>
      <text x="${W_ - pr + 4}" y="${y(model) + 4}" style="fill:var(--model)">Model ${esc(lbl(model))}</text>` : ""}
      <path d="${d}" fill="none" stroke="var(--vegas)" stroke-width="2"/>
      <text x="${pl - 4}" y="${y(pts[0].v) + 4}" text-anchor="end">${esc(lbl(pts[0].v))}</text>
      <text x="${W_ - pr + 4}" y="${y(last) + (Math.abs(y(last) - y(model)) < 12 ? 14 : 4)}" style="fill:var(--vegas)">DK ${esc(lbl(last))}</text>
      <text x="${pl}" y="${H_ - 6}">${pts[0].open ? "Open" : esc(fmtStamp(new Date(t0)).replace(" ET", ""))}</text>
      ${pts[0].open && pts.length > 2 ? `<text x="${x(pts[1].t)}" y="${H_ - 6}" text-anchor="middle">${esc(fmtStamp(new Date(pts[1].t)).replace(" ET", ""))}</text>` : ""}
      <text x="${W_ - pr}" y="${H_ - 6}" text-anchor="end">${now < ko ? "now" : "kickoff"}</text>
    </svg><div class="legend"><span><i style="background:var(--vegas)"></i>DraftKings line (via ESPN)</span><span><i style="background:var(--model)"></i>Model line</span>${fin(open) ? `<span>Opened this week ${esc(lbl(open))}</span>` : ""}${fin(first) && first !== open ? `<span class="muted">First posted before the season: ${esc(lbl(first))}</span>` : ""}</div>`;
  }

  function booksTable(W, g) {
    const rows = (W.books || []).filter(b => b.game_id === g.game_id);
    if (!rows.length) return `<p class="note">No book prices this run (odds leave the feed at kickoff).</p>`;
    rows.sort((x, y) => (x.book === "draftkings" ? -1 : y.book === "draftkings" ? 1 : x.book.localeCompare(y.book)));
    return `<div class="tablewrap"><table><thead><tr><th>Book</th><th class="num">${esc(g.home_team)} spread</th><th class="num">Price</th><th class="num">Total</th><th class="num">Over</th><th class="num">Under</th><th class="num">${esc(g.away_team)} ML</th><th class="num">${esc(g.home_team)} ML</th></tr></thead><tbody>` +
      rows.map(b => `<tr${b.book === "draftkings" ? ' class="hl"' : ""}><td>${esc(BOOKS[b.book] || b.book)}</td><td class="num">${hcap(b.home_spread)}</td><td class="num">${am(b.home_spread_price)}</td><td class="num">${fin(b.total) ? trim(b.total) : "–"}</td><td class="num">${am(b.over_price)}</td><td class="num">${am(b.under_price)}</td><td class="num">${am(b.away_ml)}</td><td class="num">${am(b.home_ml)}</td></tr>`).join("") +
      `</tbody></table></div>`;
  }

  const topTag = p => (p && p.top ? '<span class="chip top">TOP PICK</span>' : "") +
    (p && p.qb_caution ? '<span class="chip warn" title="The picked team’s quarterback is new or clearly worse than its usual starter. Picks like this broke even historically, so they are not green unless the model is 4+ points off.">QB CAUTION</span>' : "");
  const pickCell = (d, p) => p ? `<div class="${p.top ? "gcell top" : p.highlight ? "gcell" : ""}"><strong>${esc(p.bet.replace(" to win", ""))}</strong> <span class="muted">${am(p.price)}</span>${topTag(p)}${resChip(d.res(p))}${d.status(p)}
    <div class="small ${p.highlight ? "" : "muted"}">${pct(p.chance, 1)} to win${p.market !== "winner" ? ` · ${val(p)}` : ""}</div></div>` : "–";

  function modelTable(W, g) {
    const d = derive(W, g), h = d.h, a = d.a;
    return `<div class="tablewrap"><table class="mtable"><thead><tr><th></th><th>Spread</th><th>Total</th><th>Winner</th></tr></thead><tbody>
      <tr><td>Model</td><td class="m">${esc(favLine(h, a, g.model_margin))}</td><td class="m">${num(g.model_total)}</td><td class="m">${fin(g.p_home_win_model) ? esc((g.p_home_win_model >= .5 ? h : a) + " " + pct(Math.max(g.p_home_win_model, 1 - g.p_home_win_model))) : "–"}</td></tr>
      <tr><td>DraftKings</td><td class="v">${fin(d.dkMargin) ? esc(favLine(h, a, d.dkMargin)) : "–"}</td><td class="v">${fin(g.dk_total) ? trim(g.dk_total) : "–"}</td><td class="v">${fin(d.pHomeMkt) ? esc((d.pHomeMkt >= .5 ? h : a) + " " + pct(Math.max(d.pHomeMkt, 1 - d.pHomeMkt))) : "–"}</td></tr>
      <tr class="edge"><td>Pick</td><td>${pickCell(d, d.sp)}</td><td>${pickCell(d, d.tt)}</td><td>${pickCell(d, d.wn)}</td></tr>
    </tbody></table></div><p class="note">${GREEN_HELP}</p>`;
  }

  // ------------------------------------------------------------------ best picks of the week
  function teaserBlock(W) {
    const T = W.teasers || {}, pairs = T.pairs || [], legs = T.legs || [];
    const price = T.price || -120, need = Math.sqrt(1 / dec(price));
    const H = (REC.teasers || {}).teasers || {};
    const games = {}; W.games.forEach(g => games[g.game_id] = g);
    const legTxt = l => { const g = games[l.game_id], d = g && derive(W, g); const r = d && d.final ? gradePick(l, d.final[0], d.final[1]) : null;
      return `<div class="leg"><strong>${esc(l.bet)}</strong> <span class="muted small">(${esc(l.team)} ${hcap(l.line)} → ${hcap(l.teased)}) · ${g ? esc(g.away_team + " @ " + g.home_team + " · " + kick(g)) : ""}</span>${resChip(r)}${d ? d.status(l) : ""}</div>`; };
    const card = (pr, i) => { const pw = pr.reduce((a, l) => a * l.chance, 1);
      return `<div class="bp green teaser"><div class="top"><span class="rank">Teaser ${i + 1}</span><span class="small muted">2 teams, 6 points, ${am(price)}</span></div>
        ${pr.map(legTxt).join("")}<div class="meta"><span>Both hit <b>${pct(pw, 1)}</b></span><span>Needs <b>${pct(1 / dec(price), 1)}</b></span><span>Each leg ${pct(pr[0].chance, 1)} (needs ${pct(need, 1)})</span></div></div>`; };
    const extra = legs.length % 2 === 1 ? legs[legs.length - 1] : null;
    return `<h3 style="margin-top:14px">Teasers: underdogs +1.5 to +2.5, teased to +7.5 to +8.5</h3>
      ${pairs.length ? `<div class="best-grid">${pairs.map(card).join("")}</div>` : `<p class="note">No underdogs at +1.5 to +2.5 on DraftKings right now.</p>`}
      ${extra ? `<p class="note">Unpaired leg: ${esc(extra.bet)} (pair it with a leg from another game, or wait for the line to settle).</p>` : ""}
      <p class="note">Since 2015 these legs won ${pct(((REC.teasers || {}).legs || {}).pct, 1)}; 2-team teasers went ${H.w || 0}-${H.l || 0} (${pct(H.pct, 1)}, ${sgn(H.units, 1)} units at ${am(price)}). A 2-team teaser at ${am(price)} needs ${pct(1 / dec(price), 1)}. Check DraftKings' teaser price before betting.</p>`;
  }

  function windBlock(W) {
    const R = W.wind_rule || {}, H = (REC.wind || {}), F = H.with_live || H.forecast || {};
    const games = {}; W.games.forEach(g => games[g.game_id] = g);
    const on = (W.wind_unders || []).filter(x => x.highlight && games[x.game_id]);
    const hrs = x => (new Date(x.kickoff_utc) - Date.now()) / 3600e3;
    const card = x => { const g = games[x.game_id], d = derive(W, g), r = d.final ? gradePick(x, d.final[0], d.final[1]) : null;
      const soon = hrs(x) <= 3;
      return `<a class="bp green" href="#breakdown/${esc(g.game_id)}"><div class="top"><span class="rank">WIND UNDER</span><span class="small muted">${esc(kick(g))}</span></div>
        <div class="pick">${esc(x.bet)} <span class="muted" style="font-weight:500">${am(x.price)}</span>${resChip(r)}${d.status(x)}</div>
        <div class="small muted">${esc(g.away_team)} @ ${esc(g.home_team)} · forecast wind ${num(x.wind, 0)} mph, gusts ${num(x.gust, 0)} mph</div>
        <div class="conf" title="Chance ${pct(x.chance, 1)} vs break-even ${pct(x.breakeven, 1)}"><i style="width:${Math.round(100 * x.chance)}%"></i><b style="left:${(100 * x.breakeven).toFixed(1)}%"></b></div>
        <div class="meta"><span>Chance <b>${pct(x.chance, 1)}</b></span><span>Needs <b>${pct(x.breakeven, 1)}</b></span><span>Value <b class="w">${val(x)}</b></span><span>${soon ? "final forecast" : "forecast can still change"}</span></div></a>`; };
    return `<h3 style="margin-top:14px">Wind unders: outdoor games with a kickoff forecast of ${num(R.wind_mph, 0)}+ mph wind or ${num(R.gust_mph, 0)}+ mph gusts</h3>
      ${on.length ? `<div class="best-grid">${on.map(card).join("")}</div>` : `<p class="note">None right now: no outdoor game's kickoff forecast reaches ${num(R.wind_mph, 0)} mph wind or ${num(R.gust_mph, 0)} mph gusts.</p>`}
      <p class="note">Using archived kickoff forecasts, these unders went ${F.w || 0}-${F.l || 0}${F.p ? "-" + F.p : ""} (${pct(F.pct, 1)}, ${sgn(F.units, 1)} units) since ${esc(String(H.forecast_since || 2018))}. The record is built on short-range forecasts, so a pick is final at the run about 80 minutes before kickoff; earlier in the week the forecast can change.</p>`;
  }

  function bestPanel(W, compact) {
    const games = {}; W.games.forEach(g => games[g.game_id] = g);
    const all = (W.picks || []).filter(p => p.market !== "winner" && games[p.game_id]).sort((x, y) => (y.value || -1) - (x.value || -1));
    const top = all.filter(p => p.highlight).sort((x, y) => (y.top ? 1 : 0) - (x.top ? 1 : 0) || y.value - x.value);
    const card = (p, i) => { const g = games[p.game_id], d = derive(W, g), r = d.res(p);
      return `<a class="bp green${p.top ? " topcard" : ""}" href="#breakdown/${esc(g.game_id)}"><div class="top"><span class="rank">#${i + 1}${p.top ? ' <span class="chip top">TOP PICK</span>' : ""}</span><span class="small muted">${esc(kick(g))}</span></div>
        <div class="pick">${esc(p.bet)} <span class="muted" style="font-weight:500">${am(p.price)}</span>${resChip(r)}</div>
        <div class="small muted">${esc(g.away_team)} @ ${esc(g.home_team)} · ${p.market}</div>
        <div class="conf" title="Chance ${pct(p.chance, 1)} vs break-even ${pct(p.breakeven, 1)}"><i style="width:${Math.round(100 * p.chance)}%"></i><b style="left:${(100 * p.breakeven).toFixed(1)}%"></b></div>
        <div class="meta"><span>Chance <b>${pct(p.chance, 1)}</b></span><span>Needs <b>${pct(p.breakeven, 1)}</b></span><span>Value <b class="w">${val(p)}</b></span><span>Model ${edgeTxt(p.edge)} pts</span>${d.lv && d.lv.state !== "pre" ? "" : logBtn(p)}</div></a>`; };
    const next = all.filter(p => !p.highlight).slice(0, compact ? 0 : 50);
    const rows = next.map(p => { const g = games[p.game_id];
      return `<tr><td><strong>${esc(p.bet)}</strong> ${am(p.price)}</td><td>${esc(g.away_team)} @ ${esc(g.home_team)}</td><td class="num">${pct(p.chance, 1)}</td><td class="num">${pct(p.breakeven, 1)}</td><td class="num muted">${val(p)}</td></tr>`; }).join("");
    const G = ((REC.all || {}).total || {}).green, TP = ((REC.all || {}).total || {}).top;
    const tops = top.filter(p => p.top), greens = top.filter(p => !p.top), CR = REC.card || {};
    return `<div class="panel"><div class="toolbar" style="justify-content:space-between;margin:0 0 10px"><div><h2>This week's card</h2>
      <p class="lede" style="margin:0">Top picks, teasers and wind unders make the card: together they went <strong>${CR.w || 0}-${CR.l || 0}${CR.p ? "-" + CR.p : ""}</strong> (${pct(CR.pct, 1)}, ${sgn(CR.units, 1)} units), Top picks and teasers since ${esc(String(REC.since || 2015))}, wind unders since ${esc(String((REC.wind || {}).forecast_since || 2018))}. Green value picks follow.</p></div>
      ${compact ? `<a class="btn" href="#picks">All picks</a>` : ""}</div>
      <h3>Top picks: spreads where the model is 4+ points off DraftKings</h3>
      ${tops.length ? `<div class="best-grid">${tops.map(card).join("")}</div>` : `<p class="note">None right now: no spread is 4+ points off DraftKings' line. Prices update every 15 minutes.</p>`}
      ${teaserBlock(W)}
      ${windBlock(W)}
      <h3 style="margin-top:14px">Green value picks</h3>
      ${greens.length ? `<div class="best-grid">${greens.map((p, i) => card(p, i + tops.length)).join("")}</div>` : `<p class="note">None right now.</p>`}
      <p class="note">${GREEN_HELP} Chance = how often picks with this much model disagreement won from ${esc(String(REC.since || 2015))} on.</p>
      ${!compact && rows ? `<details class="leans"><summary>${next.length} other spread and total picks (below the green line)</summary><div class="tablewrap"><table><thead><tr><th>Pick</th><th>Game</th><th class="num">Chance</th><th class="num">Needs</th><th class="num">Value</th></tr></thead><tbody>${rows}</tbody></table></div></details>` : ""}</div>`;
  }

  // ------------------------------------------------------------------ Games
  let openGame = null, gameTab = "model";
  function renderGames() {
    const W = S.weeks[curKey];
    if (!W) { view.innerHTML = `<p class="empty">No weekly run yet.</p>`; return; }
    const games = W.games.slice().sort((x, y) => (isFollowed(y) ? 1 : 0) - (isFollowed(x) ? 1 : 0) || (x.kickoff_utc || "").localeCompare(y.kickoff_utc || ""));
    const star = t => `<span class="star${follows().has(t) ? " on" : ""}" role="button" tabindex="0" data-follow="${esc(t)}" title="${follows().has(t) ? "Unfollow" : "Follow"} ${esc(t)}">${follows().has(t) ? "★" : "☆"}</span>`;
    const card = g => {
      const d = derive(W, g), lv = d.lv;
      const hs = lv && lv.state !== "pre" ? lv.home_score : null, as = lv && lv.state !== "pre" ? lv.away_score : null;
      const status = !lv || lv.state === "pre" ? `<b>${esc(kick(g))}</b>` : lv.completed ? `<b>Final</b>` : `<span class="live">${esc(lv.detail || "Live")}</span>`;
      const pk = (p, label) => { if (!p) return ""; const r = d.res(p);
        return `<span class="pk${r ? " " + r : p.top ? " green top" : p.highlight ? " green" : ""}">${p.top ? "TOP · " : ""}${esc(label || p.bet)}${r ? " · " + r : ""}</span>`; };
      const scoreCls = (mine, other) => mine != null && other != null && mine < other ? "score lose" : "score";
      return `<button class="gcard${[d.sp, d.tt].some(p => p && p.highlight) ? " has-green" : ""}${isFollowed(g) ? " fav" : ""}" type="button" data-g="${esc(g.game_id)}" aria-expanded="${openGame === g.game_id}" style="--ac:${COLORS[g.away_team] || "var(--line)"};--hc:${COLORS[g.home_team] || "var(--line)"}">
        <div class="row">${team(g.away_team, ` <span class="rec">${recText(g.away_team)}</span>${star(g.away_team)}`)}${as != null ? `<span class="${scoreCls(as, hs)}">${as}</span>` : ""}</div>
        <div class="row">${team(g.home_team, ` <span class="rec">${recText(g.home_team)}</span>${star(g.home_team)}`)}${hs != null ? `<span class="${scoreCls(hs, as)}">${hs}</span>` : ""}</div>
        <div class="picks">${pk(d.sp)}${pk(d.tt)}${d.wn ? pk(d.wn, d.wn.bet.replace(" to win", " ML")) : ""}${(W.wind_unders || []).filter(x => x.game_id === g.game_id && x.highlight).map(x => `<span class="pk green">WIND ${esc(x.bet)}</span>`).join("")}</div>
        ${lineMove(g)}
        <div class="foot">${status}<span class="muted">${esc((lv && lv.broadcast) || "")}</span></div></button>`;
    };
    view.innerHTML = `<div id="gdetail-slot"></div>${bestPanel(W, true)}<p class="section-label">Week ${W.week} · all games</p><div class="ggrid">${games.map(card).join("")}</div>`;
    const slot = view.querySelector("#gdetail-slot");
    const drawDetail = () => {
      view.querySelectorAll(".gcard").forEach(c => c.setAttribute("aria-expanded", String(c.dataset.g === openGame)));
      const g = openGame && games.find(x => x.game_id === openGame);
      if (!g) { slot.innerHTML = ""; return; }
      const d = derive(W, g);
      const tabs = [["model", "Model"], ["win", "Win chance"], ["books", "All books"], ["news", "Injuries and context"]];
      let body = "";
      if (gameTab === "model") body = modelTable(W, g);
      else if (gameTab === "win") body = `<div class="bars"><span class="lab">Model</span>${bar("model", g.away_team, fin(g.p_home_win_model) ? 1 - g.p_home_win_model : NaN, g.home_team)}
        <span class="lab">DK</span>${bar("vegas", g.away_team, fin(d.pHomeMkt) ? 1 - d.pHomeMkt : NaN, g.home_team)}</div>
        <p class="note">Model = the model alone. DK = DraftKings' moneyline with the margin removed.</p>`;
      else if (gameTab === "line") body = `<div class="two"><div><h3>Spread</h3>${lineChart(g.game_id, g, "spread")}</div><div><h3>Total</h3>${lineChart(g.game_id, g, "total")}</div></div>`;
      else if (gameTab === "books") body = booksTable(W, g);
      else body = contextBlock(W, g);
      slot.innerHTML = `<div class="gdetail" id="gdetail">
        <div class="gd-head">${team(g.away_team, "", true)}<span class="at">at</span>${team(g.home_team, "", true)}
          ${d.lv && d.lv.state !== "pre" ? `<strong class="cond" style="font-size:20px">${d.lv.away_score}–${d.lv.home_score}</strong> <span class="${d.lv.completed ? "muted" : "live"}">${esc(d.lv.detail || "")}</span>` : ""}
          <button class="btn close" type="button" data-close>Close</button></div>
        <p class="gd-sub">${esc(fmtLong(dt(g.kickoff_utc)))} · ${esc(fmtTime(dt(g.kickoff_utc)))} ET${d.lv && d.lv.broadcast ? " · " + esc(d.lv.broadcast) : ""} · <a href="#breakdown/${esc(g.game_id)}">Full breakdown</a></p>
        <div class="two" style="margin:6px 0 10px"><div><h3>Spread: where it opened and where it is now</h3>${lineChart(g.game_id, g, "spread")}</div><div><h3>Total: where it opened and where it is now</h3>${lineChart(g.game_id, g, "total")}</div></div>
        <div class="subtabs">${tabs.map(([k, l]) => `<button type="button" data-gt="${k}" aria-pressed="${gameTab === k}">${l}</button>`).join("")}</div>${body}</div>`;
      slot.querySelectorAll("[data-gt]").forEach(b => b.onclick = () => { gameTab = b.dataset.gt; drawDetail(); });
      slot.querySelector("[data-close]").onclick = () => { openGame = null; drawDetail(); };
    };
    view.querySelectorAll(".gcard").forEach(b => b.onclick = () => {
      openGame = openGame === b.dataset.g ? null : b.dataset.g; drawDetail();
      if (openGame) slot.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
    drawDetail();
  }

  function contextBlock(W, g) {
    const miss = s => s ? esc(s) : '<span class="muted">No regular starters on the injury report</span>';
    const cont = (o, d) => fin(o) ? `${pct(o)} offense, ${pct(d)} defense` : "–";
    const wx = g.indoor ? "Indoors" : [fin(g.temp_used) ? Math.round(g.temp_used) + "°F" : null, fin(g.wind_used) ? "wind " + Math.round(g.wind_used) + " mph" : null, fin(g.precip) && g.precip > 0.01 ? "rain " + g.precip.toFixed(2) + " in" : null].filter(Boolean).join(", ") || "–";
    return `<div class="tablewrap"><table><tbody>
      <tr><td class="muted">Quarterbacks</td><td>${esc(g.a_qb_name_used || "–")} (${esc(g.away_team)}) vs ${esc(g.h_qb_name_used || "–")} (${esc(g.home_team)})</td></tr>
      <tr><td class="muted">${esc(g.away_team)} missing</td><td>${miss(g.a_miss_names)}</td></tr>
      <tr><td class="muted">${esc(g.home_team)} missing</td><td>${miss(g.h_miss_names)}</td></tr>
      <tr><td class="muted">Weather</td><td>${esc(wx)}</td></tr>
      <tr><td class="muted">Venue</td><td>${esc(g.stadium || "")}${g.roof ? " · " + esc(g.roof) : ""}${g.location === "Neutral" ? " · neutral site" : ""}</td></tr>
      <tr><td class="muted">Rest</td><td>${esc(g.away_team)} ${fin(g.away_rest) ? g.away_rest + " days" : "–"}, ${esc(g.home_team)} ${fin(g.home_rest) ? g.home_rest + " days" : "–"}${fin(g.away_travel_kmi) ? ` · ${esc(g.away_team)} travel ${Math.round(g.away_travel_kmi * 1000).toLocaleString()} mi` : ""}</td></tr>
      <tr><td class="muted">Returning snaps</td><td>${esc(g.away_team)} ${cont(g.a_off_cont, g.a_def_cont)} · ${esc(g.home_team)} ${cont(g.h_off_cont, g.h_def_cont)}</td></tr>
      <tr><td class="muted">Coaches</td><td>${esc(g.away_coach || "–")} vs ${esc(g.home_coach || "–")}${g.referee ? " · referee " + esc(g.referee) : ""}</td></tr>
    </tbody></table></div><p class="note">Missing players are regular starters (by snap share) listed out, doubtful or questionable (ESPN's same-day page over the league report), counted by their chance of sitting.</p>`;
  }

  // ------------------------------------------------------------------ Picks
  let picksWeek = null, rankMarket = "all";
  const teaserPrices = { 2: -120, 3: 160, 4: 260 };
  function renderPicks() {
    const key = picksWeek || curKey, W = S.weeks[key];
    if (!W) { view.innerHTML = `<p class="empty">No weekly run yet.</p>`; return; }
    const games = W.games.slice().sort((x, y) => (x.kickoff_utc || "").localeCompare(y.kickoff_utc || ""));
    const rows = games.map(g => { const d = derive(W, g);
      return `<tr><td>${team(g.away_team)} <span class="muted">@</span> ${team(g.home_team)}<div class="small muted">${esc(kick(g))}</div></td>
        <td>${pickCell(d, d.sp)}</td><td>${pickCell(d, d.tt)}</td><td>${pickCell(d, d.wn)}</td>
        <td class="num">${esc(g.away_team)} ${num(d.ma)}<br>${esc(g.home_team)} ${num(d.mh)}</td>
        <td class="num">${fin(d.va) ? num(d.va) + "<br>" + num(d.vh) : "–"}</td>
        <td class="num">${d.final ? `${d.final[1]}–${d.final[0]}` : ""}</td></tr>`; }).join("");
    const byG = {}; games.forEach(g => byG[g.game_id] = g);
    const rank = (W.picks || []).filter(p => p.market !== "winner" && byG[p.game_id] && (rankMarket === "all" || p.market === rankMarket))
      .sort((x, y) => (y.value || -1) - (x.value || -1));
    const rankRows = rank.map((p, i) => { const g = byG[p.game_id], d = derive(W, g);
      return `<tr${p.top ? ' class="grow top"' : p.highlight ? ' class="grow"' : ""}><td class="num">${i + 1}</td><td><strong>${esc(p.bet)}</strong>${topTag(p)}${resChip(d.res(p))}</td>
      <td>${esc(g.away_team)} @ ${esc(g.home_team)}</td><td class="muted">${esc(kick(g))}</td><td>${p.market === "spread" ? "Spread" : "Total"}</td>
      <td class="num">${am(p.price)}</td><td class="num">${edgeTxt(p.edge)}</td><td class="num"><strong>${pct(p.chance, 1)}</strong></td>
      <td class="num">${pct(p.breakeven, 1)}</td><td class="num ${p.highlight ? "w" : "muted"}"><strong>${val(p)}</strong></td></tr>`; }).join("");
    view.innerHTML = `
      <div class="toolbar noprint"><select id="wk" aria-label="Week">${weekKeys.map(k => `<option value="${k}"${k === key ? " selected" : ""}>Week ${+k.split("-")[1]}, ${k.split("-")[0]}</option>`).join("")}</select>
        <button class="btn primary" type="button" id="pdf">Download PDF</button><span class="small muted">Prices from ${esc(fmtStamp(dt(W.generated)))}</span></div>
      ${key === curKey ? betNowPanel(W) + earlyPanel(W) : ""}
      ${key === curKey && ALERTS.some(a => a.kind === "pick") ? `<div class="panel noprint"><div class="toolbar" style="justify-content:space-between;margin:0"><h2>Recent pick changes</h2><a href="#alerts">All alerts →</a></div>${alertList(ALERTS.filter(a => a.kind === "pick").slice(0, 4), lastSeen())}</div>` : ""}
      ${bestPanel(W, false)}
      <div class="panel"><h2>Every game</h2><div class="tablewrap"><table><thead><tr><th>Game</th><th>Spread</th><th>Total</th><th>Winner</th><th class="num">Model score</th><th class="num">Vegas score</th><th class="num">Final</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="note">Spread and total picks take the model's side of DraftKings' number. The winner pick is the team the model makes more likely to win. Green cells are the best-value picks.</p></div>
      <div class="panel"><div class="toolbar" style="justify-content:space-between"><h2>Every spread and total, by value</h2>
        <div class="seg noprint" role="group" aria-label="Market">${[["all", "All"], ["spread", "Spreads"], ["total", "Totals"]].map(([m, l]) => `<button type="button" data-rm="${m}" aria-pressed="${rankMarket === m}">${l}</button>`).join("")}</div></div>
        <div class="tablewrap"><table><thead><tr><th class="num">#</th><th>Pick</th><th>Game</th><th>Kickoff</th><th>Market</th><th class="num">DK price</th><th class="num">Model edge</th><th class="num">Chance</th><th class="num">Needs</th><th class="num">Value</th></tr></thead><tbody>${rankRows}</tbody></table></div>
        <p class="note">Model edge: points between the model's number and DraftKings'. Chance: how often picks with that edge won against the closing line from ${esc(String(REC.since || 2015))} on (pushes excluded). Needs: the win rate DraftKings' price requires to break even. Value = chance − needs.</p></div>
      ${teaserPanel(W, games)}`;
    view.querySelector("#wk").onchange = e => { picksWeek = e.target.value; renderPicks(); };
    view.querySelector("#pdf").onclick = () => window.print();
    view.querySelectorAll("[data-rm]").forEach(b => b.onclick = () => { rankMarket = b.dataset.rm; renderPicks(); });
    wireTeaser(W, games);
  }

  function teaserLegs(games) {
    const legs = [];
    games.forEach(g => { const t = g.tease || {};
      if (t.home) legs.push({ gid: g.game_id, g, label: `${g.home_team} ${hcap(t.home.line)}`, p: t.home.p });
      if (t.away) legs.push({ gid: g.game_id, g, label: `${g.away_team} ${hcap(t.away.line)}`, p: t.away.p });
      if (t.over) legs.push({ gid: g.game_id, g, label: `Over ${trim(t.over.line)}`, p: t.over.p });
      if (t.under) legs.push({ gid: g.game_id, g, label: `Under ${trim(t.under.line)}`, p: t.under.p }); });
    return legs.sort((x, y) => y.p - x.p);
  }
  const teaserPicked = new Set();
  function teaserPanel(W, games) {
    const legs = teaserLegs(games);
    if (!legs.length) return "";
    const best = n => { const out = [], used = new Set(); for (const l of legs) { if (used.has(l.gid)) continue; out.push(l); used.add(l.gid); if (out.length === n) break; } return out; };
    const card = n => { const b = best(n); if (b.length < n) return ""; const p = b.reduce((a, l) => a * l.p, 1), price = teaserPrices[n], ev = p * dec(price) - 1;
      return `<div class="bd-card${ev > 0 ? " green" : ""}"><h3>Best ${n}-leg</h3><div><strong>${b.map(l => esc(l.label)).join(" · ")}</strong></div>
        <div class="small muted">${pct(p)} to hit · fair ${am(toAm(p))} · at ${am(price)}: <span class="${ev > 0 ? "w" : "l"}">${sgn(100 * ev, 1)}% expected return</span></div></div>`; };
    return `<div class="panel" id="teaser"><h2>6-point teasers</h2>
      <p class="lede">Each leg moves DraftKings' spread or total 6 points your way. Chances come from how often NFL games land on each margin, so legs through 3 and 7 rank higher. Legs are treated as independent. Enter DraftKings' current teaser price.</p>
      <div class="toolbar noprint">${[2, 3, 4].map(n => `<label class="small">${n} legs <input type="number" step="5" data-tp="${n}" value="${teaserPrices[n]}" style="width:78px"></label>`).join("")}</div>
      <div class="bd-grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr))">${card(2)}${card(3)}${card(4)}</div>
      <div id="teaser-mine" class="note"></div>
      <div class="tablewrap" style="margin-top:8px"><table><thead><tr><th></th><th>Teased line</th><th>Game</th><th>Kickoff</th><th class="num">Chance</th></tr></thead><tbody>
      ${legs.slice(0, 40).map((l, i) => `<tr><td><input type="checkbox" data-leg="${i}" aria-label="Add ${esc(l.label)}"${teaserPicked.has(l.label + l.gid) ? " checked" : ""}></td><td><strong>${esc(l.label)}</strong></td><td>${esc(l.g.away_team)} @ ${esc(l.g.home_team)}</td><td class="muted">${esc(kick(l.g))}</td><td class="num">${pct(l.p)}</td></tr>`).join("")}
      </tbody></table></div></div>`;
  }
  function wireTeaser(W, games) {
    const legs = teaserLegs(games), box = view.querySelector("#teaser-mine");
    if (!box) return;
    const upd = () => {
      const chosen = legs.filter(l => teaserPicked.has(l.label + l.gid)), n = chosen.length;
      if (n < 2) { box.textContent = "Tick two to four legs to price your own teaser."; return; }
      const dup = new Set(chosen.map(l => l.gid)).size < n;
      const p = chosen.reduce((a, l) => a * l.p, 1), price = teaserPrices[Math.min(n, 4)], ev = p * dec(price) - 1;
      box.innerHTML = `Your ${n}-leg teaser: <strong>${pct(p)}</strong> to hit, fair ${am(toAm(p))}` +
        (n <= 4 ? `, at ${am(price)}: <strong class="${ev > 0 ? "w" : "l"}">${sgn(100 * ev, 1)}% expected return</strong>` : "") +
        (dup ? " · two legs from one game are correlated, so this overstates the chance." : "");
    };
    view.querySelectorAll("[data-leg]").forEach(cb => cb.onchange = () => { const l = legs[+cb.dataset.leg], k = l.label + l.gid; cb.checked ? teaserPicked.add(k) : teaserPicked.delete(k); upd(); });
    view.querySelectorAll("[data-tp]").forEach(inp => inp.onchange = () => { const v = parseFloat(inp.value); if (fin(v) && Math.abs(v) >= 100) { teaserPrices[+inp.dataset.tp] = v; renderPicks(); } });
    upd();
  }

  // ------------------------------------------------------------------ Breakdown
  let bdGame = null;
  function renderBreakdown(sel) {
    const W = S.weeks[curKey];
    if (!W) { view.innerHTML = `<p class="empty">No weekly run yet.</p>`; return; }
    const games = W.games.slice().sort((x, y) => (x.kickoff_utc || "").localeCompare(y.kickoff_utc || ""));
    bdGame = sel || bdGame || games[0].game_id;
    const g = games.find(x => x.game_id === bdGame) || games[0], d = derive(W, g), h = d.h, a = d.a;
    const chips = games.map(x => { const dx = derive(W, x), gr = [dx.sp, dx.tt].some(p => p && p.highlight);
      return `<button type="button" data-bd="${esc(x.game_id)}" class="${gr ? "green" : ""}" aria-pressed="${x.game_id === g.game_id}">${esc(x.away_team)} @ ${esc(x.home_team)}</button>`; }).join("");
    const wx = g.indoor ? "Indoors" : [fin(g.temp_used) ? Math.round(g.temp_used) + "°F" : null, fin(g.wind_used) ? "wind " + Math.round(g.wind_used) + " mph" : null].filter(Boolean).join(", ");
    const pickBox = p => p ? `<div class="edgebox${p.highlight ? "" : " none"}"><span class="el">${p.top ? "TOP PICK" : p.highlight ? "BEST VALUE" : "PICK"}</span><span>${esc(p.bet)} ${am(p.price)}</span>
      <span class="small">${pct(p.chance, 1)} to win · needs ${pct(p.breakeven, 1)} · value ${val(p)}</span></div>` : `<div class="edgebox none">No DraftKings price</div>`;
    const other = (p, m) => !p ? "" : m === "total" ? (p.side === "over" ? "Under" : "Over") : (p.side === "home" ? a : h);
    const spCard = `<div class="bd-card"><h3>Spread</h3><dl class="kv"><dt>Model</dt><dd class="m">${esc(favLine(h, a, g.model_margin))}</dd><dt>DK</dt><dd class="v">${fin(d.dkMargin) ? esc(favLine(h, a, d.dkMargin)) : "–"}</dd><dt>Edge</dt><dd>${d.sp ? edgeTxt(d.sp.edge) + " pts toward " + esc(d.sp.team) : "–"}</dd></dl>
      ${pickBox(d.sp)}
      ${d.sp ? `<div class="bars"><span class="lab">History</span>${bar("hist", d.sp.bet, d.sp.chance, other(d.sp, "spread"))}<span class="lab">Fair</span>${bar("model", d.sp.bet, d.fair(d.sp), other(d.sp, "spread"))}<span class="lab">DK</span>${bar("vegas", d.sp.bet, fin(d.sp.breakeven) ? d.sp.breakeven / (d.sp.breakeven + implied(d.sp.side === "home" ? g.dk_away_spread_price : g.dk_home_spread_price)) : NaN, other(d.sp, "spread"))}</div>` : ""}
      <div style="margin-top:10px">${lineChart(g.game_id, g, "spread")}</div></div>`;
    const ttCard = `<div class="bd-card"><h3>Total</h3><dl class="kv"><dt>Model</dt><dd class="m">${num(g.model_total)}</dd><dt>DK</dt><dd class="v">${fin(g.dk_total) ? trim(g.dk_total) : "–"}</dd><dt>Edge</dt><dd>${d.tt ? edgeTxt(d.tt.edge) + " pts " + (d.tt.side === "over" ? "over" : "under") : "–"}</dd></dl>
      ${pickBox(d.tt)}
      ${d.tt ? `<div class="bars"><span class="lab">History</span>${bar("hist", d.tt.bet, d.tt.chance, other(d.tt, "total"))}<span class="lab">Fair</span>${bar("model", d.tt.bet, d.fair(d.tt), other(d.tt, "total"))}<span class="lab">DK</span>${bar("vegas", d.tt.bet, fin(d.tt.breakeven) ? d.tt.breakeven / (d.tt.breakeven + implied(d.tt.side === "over" ? g.dk_under_price : g.dk_over_price)) : NaN, other(d.tt, "total"))}</div>` : ""}
      <div style="margin-top:10px">${lineChart(g.game_id, g, "total")}</div></div>`;
    const ptCard = `<div class="bd-card"><h3>Points</h3><div class="tablewrap"><table><thead><tr><th></th><th class="num">${esc(a)}</th><th class="num">${esc(h)}</th></tr></thead><tbody>
      <tr><td class="muted">Model</td><td class="num" style="color:var(--model)">${num(d.ma)}</td><td class="num" style="color:var(--model)">${num(d.mh)}</td></tr>
      <tr><td class="muted">DraftKings</td><td class="num" style="color:var(--vegas)">${num(d.va)}</td><td class="num" style="color:var(--vegas)">${num(d.vh)}</td></tr>
      ${d.lv && d.lv.state !== "pre" ? `<tr><td class="muted">${d.lv.completed ? "Final" : "Now"}</td><td class="num"><strong>${d.lv.away_score}</strong></td><td class="num"><strong>${d.lv.home_score}</strong></td></tr>` : ""}</tbody></table></div></div>`;
    const winCard = `<div class="bd-card"><h3>Win</h3>${d.wn ? `<div class="edgebox none"><span class="el">WINNER</span><span>${esc(d.wn.team)} ${am(d.wn.price)}</span><span class="small">${pct(d.wn.chance)} to win${fin(d.wn.breakeven) ? " · price needs " + pct(d.wn.breakeven) : ""}</span></div>` : ""}
      <div class="bars"><span class="lab">Model</span>${bar("model", a, fin(g.p_home_win_model) ? 1 - g.p_home_win_model : NaN, h)}<span class="lab">DK</span>${bar("vegas", a, fin(d.pHomeMkt) ? 1 - d.pHomeMkt : NaN, h)}</div></div>`;
    const h2h = ((S.schedule || {}).h2h || {})[g.game_id] || [];
    const h2hRows = h2h.map(m => { const cover = fin(m.result) && fin(m.spread_line) ? m.result - m.spread_line : NaN;
      const ats = !fin(cover) ? "–" : Math.abs(cover) < 1e-9 ? "Push" : (cover > 0 ? m.home_team : m.away_team) + " covered";
      return `<tr><td>${m.season} W${m.week}</td><td>${esc(m.away_team)} ${m.away_score} @ ${esc(m.home_team)} ${m.home_score}</td><td class="num">${fin(m.spread_line) ? esc(favLine(m.home_team, m.away_team, m.spread_line)) : "–"}</td><td>${esc(ats)}</td><td class="num">${fin(m.total_line) ? trim(m.total_line) + (m.total > m.total_line ? " (O)" : m.total < m.total_line ? " (U)" : " (P)") : "–"}</td></tr>`; }).join("");
    view.innerHTML = `<h2 class="cond" style="margin:4px 0 8px;font-size:20px">Week ${W.week}, ${W.season}</h2><div class="chips" role="group" aria-label="Game">${chips}</div>
      <article class="panel"><div class="gd-head">${team(a, "", true)}<span class="at">@</span>${team(h, "", true)}<span class="muted small">${esc(fmtLong(dt(g.kickoff_utc)))} · ${esc(fmtTime(dt(g.kickoff_utc)))} ET · ${esc(g.stadium || "")}${wx ? " · " + esc(wx) : ""}</span></div>
      <div class="bd-grid" style="margin-top:12px">${spCard}${ttCard}${ptCard}${winCard}</div>
      <p class="note">History = how often picks with this much model disagreement won since ${esc(String(REC.since || 2015))}. Fair = the model blended with the sharp-book consensus at DraftKings' number. DK = DraftKings' price with its margin removed.</p>
      <details class="fold" open><summary>Score projection</summary>${contribBlock(g)}</details>
      <details class="fold"><summary>Injury report and context</summary>${contextBlock(W, g)}</details>
      <details class="fold"><summary>Matchup history</summary>${h2hRows ? `<div class="tablewrap"><table><thead><tr><th>Game</th><th>Score</th><th class="num">Closing spread</th><th>Against the spread</th><th class="num">Total</th></tr></thead><tbody>${h2hRows}</tbody></table></div>` : `<p class="note">No recent meetings.</p>`}</details>
      <details class="fold"><summary>Prices at every book</summary>${booksTable(W, g)}</details>
      </article>`;
    view.querySelectorAll("[data-bd]").forEach(b => b.onclick = () => { location.hash = "breakdown/" + b.dataset.bd; });
  }

  function contribBlock(g) {
    const block = (obj, title, unit) => {
      if (!obj || !Object.keys(obj).length) return "";
      const base = obj.baseline;
      const items = Object.entries(obj).filter(([k]) => k !== "baseline").sort((x, y) => Math.abs(y[1]) - Math.abs(x[1]));
      const mx = Math.max(1, ...items.map(([, v]) => Math.abs(v)));
      const sum = items.reduce((s, [, v]) => s + v, 0) + (fin(base) ? base : 0);
      return `<div><h3>${title}</h3><div class="contrib">
        <span class="muted">${GROUP_LABELS.baseline}</span><span></span><span class="num">${num(base)}</span>
        ${items.map(([k, v]) => `<span>${esc(GROUP_LABELS[k] || k)}</span><span class="cb"><i class="${v >= 0 ? "pos" : "neg"}" style="width:${50 * Math.abs(v) / mx}%"></i></span><span class="num">${sgn(v, 2)}</span>`).join("")}
        <strong>Model ${unit}</strong><span></span><strong class="num">${num(sum)}</strong></div></div>`;
    };
    return `<p class="note" style="margin:0 0 10px">How each factor group moves the model's number, in points (the linear part of the model; ${esc(g.home_team)} margin is positive when ${esc(g.home_team)} is better).</p>
      <div class="two">${block(g.contrib_margin, `${esc(g.home_team)} margin`, "margin")}${block(g.contrib_total, "Total points", "total")}</div>`;
  }

  // ------------------------------------------------------------------ Record (2015 to now)
  function windRecord(chart) {
    const H = REC.wind || {}; if (!H.seasons) return "";
    const r = x => x && x.n ? `${x.w}-${x.l}${x.p ? "-" + x.p : ""}` : "–";
    const cell = x => x && x.n ? `${r(x)} <span class="small ${x.pct > 0.524 ? "w" : "muted"}">${pct(x.pct, 1)}</span> <span class="small muted">${sgn(x.units, 1)}u</span>` : "–";
    const F = H.forecast || {}, A = H.forecast_2018_21 || {}, B = H.forecast_2022_on || {}, Rc = H.recorded || {}, All = H.all_outdoor_forecast_era || {};
    return `<div class="panel"><h2>Wind unders</h2>
      <p class="lede">Rule: ${esc(H.rule || "")}. Graded at the closing total and under price.</p>
      <div class="kpis" style="grid-template-columns:repeat(4,minmax(0,1fr));margin:0 0 10px">
        <div class="kpi kpi-green"><div class="kl">Forecast rule, since ${esc(String(H.forecast_since))}</div><div class="kv">${recTxt(F)}</div><div class="ks">${pct(F.pct, 1)} · ${sgn(F.units, 1)} units</div><div class="ks">the rule exactly as used</div></div>
        <div class="kpi"><div class="kl">2018-21 (independent check)</div><div class="kv">${recTxt(A)}</div><div class="ks">${pct(A.pct, 1)} · ${sgn(A.units, 1)}u</div><div class="ks">seasons not used to choose the rule</div></div>
        <div class="kpi"><div class="kl">Recorded wind 10+ mph, since ${esc(String(H.recorded_since))}</div><div class="kv">${recTxt(Rc)}</div><div class="ks">${pct(Rc.pct, 1)} · ${sgn(Rc.units, 1)}u</div><div class="ks">wind measured at kickoff</div></div>
        <div class="kpi"><div class="kl">All outdoor unders, same seasons</div><div class="kv">${recTxt(All)}</div><div class="ks">${pct(All.pct, 1)} · ${sgn(All.units, 1)}u</div><div class="ks">for comparison</div></div></div>
      <div class="tablewrap"><table><thead><tr><th>Season</th><th class="num gcol">Forecast rule</th><th class="num">Recorded wind 10+</th><th class="num">All outdoor unders</th></tr></thead><tbody>
      ${H.seasons.slice().reverse().map(s => `<tr><td>${s.season}</td><td class="num gcol">${s.forecast ? cell(s.forecast) : '<span class="muted">no archive</span>'}</td><td class="num">${cell(s.recorded)}</td><td class="num">${cell(s.all_outdoor)}</td></tr>`).join("")}</tbody></table></div>
      <p class="note">Archived forecasts (Open-Meteo's historical forecast API) have wind and gust data from 2018. Forecast and recorded kickoff wind correlate at ${num(H.corr, 2)}. The 2018-21 forecasts were not looked at when the rule was chosen, so that record is the honest out-of-sample check: positive, but smaller than 2022-26 (${r(B)}, ${pct(B.pct, 1)}).</p>
      <h3 style="margin-top:14px">Forecast rule: units won over time</h3>${chart(H.cum, "var(--accent)", "Wind unders")}</div>`;
  }

  function teaserRecord() {
    const T = REC.teasers || {}; if (!T.seasons) return "";
    const L = T.legs || {}, P = T.teasers || {};
    return `<div class="panel"><h2>Teasers since ${esc(String(REC.since || 2015))}</h2>
      <p class="lede">Every underdog at +1.5 to +2.5 at the closing line, teased 6 points, paired in schedule order each week. A 2-team teaser at ${am(T.price)} needs ${pct(1 / dec(T.price), 1)} (each leg ${pct(T.need_leg, 1)}).</p>
      <div class="kpis" style="grid-template-columns:repeat(3,minmax(0,1fr));margin:0 0 10px">
        <div class="kpi kpi-green"><div class="kl">2-team teasers</div><div class="kv">${recTxt(Object.assign({ p: 0, n: P.n }, P))}</div><div class="ks">${pct(P.pct, 1)} · ${sgn(P.units, 1)} units</div></div>
        <div class="kpi"><div class="kl">Legs</div><div class="kv">${recTxt(Object.assign({ p: 0, n: (L.w || 0) + (L.l || 0) }, L))}</div><div class="ks">${pct(L.pct, 1)} won</div></div>
        <div class="kpi"><div class="kl">Card (Top picks + teasers)</div><div class="kv">${recTxt(Object.assign({ n: (REC.card || {}).w }, REC.card))}</div><div class="ks">${recSub(Object.assign({ n: 1 }, REC.card))}</div></div></div>
      <div class="tablewrap"><table><thead><tr><th>Season</th><th class="num">Legs</th><th class="num">Teasers</th><th class="num">Units</th></tr></thead><tbody>
      ${T.seasons.slice().reverse().map(s => `<tr><td>${s.season}</td><td class="num">${s.legs_w}-${s.legs_l}</td><td class="num">${s.w}-${s.l}</td><td class="num ${s.units >= 0 ? "w" : "l"}">${sgn(s.units, 1)}</td></tr>`).join("")}</tbody></table></div></div>`;
  }
  function explorerPanel() {
    const E = REC.explorer || []; if (!E.length) return "";
    const row = r => `<tr><td>${r.market === "spread" ? "Spreads" : "Totals"} ${r.min_edge ? r.min_edge + "+ pts" : "(every game)"}</td>
      <td class="num">${r.a.w}-${r.a.l} <span class="small ${r.a.pct > 0.524 ? "w" : "muted"}">${pct(r.a.pct, 1)}</span></td><td class="num ${r.a.units >= 0 ? "w" : "l"}">${sgn(r.a.units, 1)}</td><td class="num muted">${num(r.a.per_week, 1)}</td>
      <td class="num">${r.b.w}-${r.b.l} <span class="small ${r.b.pct > 0.524 ? "w" : "muted"}">${pct(r.b.pct, 1)}</span></td><td class="num ${r.b.units >= 0 ? "w" : "l"}">${sgn(r.b.units, 1)}</td><td class="num muted">${num(r.b.per_week, 1)}</td></tr>`;
    return `<div class="panel"><h2>More picks or better picks?</h2><p class="lede">Every threshold for the model's disagreement with the closing line: fewer picks win more often. Rules were chosen on 2015-2020; 2021-2026 is the check they never saw. Units at the closing price.</p>
      <div class="tablewrap"><table><thead><tr><th>Bet when the model is off by</th><th class="num">2015-20</th><th class="num">Units</th><th class="num">Per week</th><th class="num">2021-26</th><th class="num">Units</th><th class="num">Per week</th></tr></thead><tbody>${E.map(row).join("")}</tbody></table></div>
      <p class="note">Spreads profit in both halves from about 2 points up; totals do not hold up, so they stay off the card. Top picks use 4+ points.</p></div>`;
  }
  function renderRecord() {
    const A = REC.all || {}, T = A.total || {}, seasons = A.seasons || [];
    if (!seasons.length) { view.innerHTML = `<p class="empty">Run optimize.py to build the track record.</p>`; return; }
    const card = (k, l, help) => { const r = T[k] || {};
      return `<div class="kpi${k === "green" ? " kpi-green" : ""}"><div class="kl">${l}</div><div class="kv">${recTxt(r)}</div>
        <div class="ks">${pct(r.pct, 1)} won${fin(r.units) ? ` · ${sgn(r.units, 1)} units · ROI ${sgn(100 * r.roi, 1)}%` : ""}</div><div class="ks">${help}</div></div>`; };
    const cell = r => r && r.n ? `${r.w}-${r.l}${r.p ? "-" + r.p : ""} <span class="small ${r.pct > 0.524 ? "w" : "muted"}">${pct(r.pct, 1)}</span>${fin(r.units) ? ` <span class="small muted">${sgn(r.units, 1)}u</span>` : ""}` : "–";
    const rows = seasons.slice().reverse().map(s => `<tr><td><strong>${s.season}</strong>${s.season === REC.current_season ? ' <span class="small muted">so far</span>' : ""}</td>
      <td class="num gcol">${cell(s.top)}</td><td class="num gcol">${cell(s.green)}</td><td class="num">${cell(s.green_total)}</td>
      <td class="num">${cell(s.spread)}</td><td class="num">${cell(s.total)}</td><td class="num">${cell(s.winner)}</td></tr>`).join("");
    const unitsChart = (cum, color, label) => {
      if (!cum || cum.length < 2) return '<p class="note">Not enough picks yet.</p>';
      const W_ = 720, H_ = 180, pl = 44, pr = 12, pt = 12, pb = 24, vals = cum.map(x => x[1]);
      const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
      const x = i => pl + (W_ - pl - pr) * i / (cum.length - 1), y = v => pt + (H_ - pt - pb) * (hi - v) / Math.max(hi - lo, 1);
      const ss = []; cum.forEach((p, i) => { const s = p[0].slice(0, 4); if (!ss.length || ss[ss.length - 1][0] !== s) ss.push([s, i]); });
      return `<svg class="chart" viewBox="0 0 ${W_} ${H_}" role="img" aria-label="Cumulative units">
        <line x1="${pl}" x2="${W_ - pr}" y1="${y(0)}" y2="${y(0)}" stroke="var(--line)"/>
        ${ss.map(([s, i]) => `<line x1="${x(i)}" x2="${x(i)}" y1="${pt}" y2="${H_ - pb}" stroke="var(--line2)"/><text x="${x(i) + 3}" y="${H_ - 7}">${s.slice(2)}</text>`).join("")}
        <polyline fill="none" stroke="${color}" stroke-width="2.2" points="${cum.map((p, i) => `${x(i)},${y(p[1])}`).join(" ")}"/>
        <text x="${pl - 5}" y="${y(hi) + 4}" text-anchor="end">${sgn(hi, 0)}</text><text x="${pl - 5}" y="${y(lo) + 4}" text-anchor="end">${sgn(lo, 0)}</text>
        <text x="${pl - 5}" y="${y(0) + 4}" text-anchor="end">0</text></svg><p class="note">${label}: ${sgn(vals[vals.length - 1], 1)} units over ${cum.length} weeks with a pick.</p>`;
    };
    const bands = (A.bands || []).map(b => `<tr><td>${pct(b.lo)}–${b.hi < 1 ? pct(b.hi) : "up"}</td><td class="num">${b.n.toLocaleString()}</td><td class="num">${pct(b.said, 1)}</td><td class="num ${b.won >= b.said - 0.01 ? "w" : "l"}">${pct(b.won, 1)}</td></tr>`).join("");
    const B = S.backtest || {}, o = B.overall || {};
    view.innerHTML = `<div class="panel"><h2>Track record since ${esc(String(REC.since))}</h2>
      <p class="lede">Every game from ${esc(String(REC.since))} to today, picked with the same rule the page uses now and graded at the real closing line and price. Each season was predicted by a model trained only on earlier seasons, and each season's chance curve was fit only on earlier seasons. Some settings were chosen by looking at these same years (which factor groups to keep, how fast ratings react, and the 4-point line for Top picks), so expect live results to run somewhat below the backtest. This season's games after the last backtest run are graded live at DraftKings' price from the last run before kickoff, which is the truest test.</p>
      <div class="kpis" style="grid-template-columns:repeat(4,minmax(0,1fr));margin:10px 0 0">
        ${card("top", "Top picks", "spreads 4+ pts off the line")}${card("green", "Green picks", "chance beat the price's break-even")}${card("spread", "Every spread pick", "the model's side, every game")}${card("winner", "Straight-up winners", "the model's likelier winner")}</div>
      <div class="kpis" style="grid-template-columns:repeat(4,minmax(0,1fr));margin:10px 0 0">${card("green_spread", "Green spreads", "")}${card("green_total", "Green totals", "")}${card("total", "Every total pick", "the model's side, every game")}
        <div class="kpi"><div class="kl">Break-even</div><div class="kv">52.4%</div><div class="ks">win rate a −110 bet needs</div></div></div></div>
      ${windRecord(unitsChart)}
      ${teaserRecord()}
      ${explorerPanel()}
      <div class="panel"><h2>Season by season</h2><div class="tablewrap"><table class="rec-table"><thead><tr><th>Season</th><th class="num gcol">Top picks</th><th class="num gcol">Green picks</th><th class="num">Green totals</th><th class="num">All spreads</th><th class="num">All totals</th><th class="num">Winners</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="note">Win % excludes pushes. Units are 1-unit bets at the closing price (spreads and totals; winners at the closing moneyline). Break-even at −110 is 52.4%.</p></div>
      <div class="two"><div class="panel"><h2>Top picks: units won over time</h2>${unitsChart(A.cum_top, "var(--green-ink)", "Top picks")}</div>
      <div class="panel"><h2>Green picks: units won over time</h2>${unitsChart(A.cum, "var(--accent)", "Green picks")}</div></div>
      <div class="two"><div class="panel"><h2>Does the chance hold up?</h2><p class="lede">Spread and total picks grouped by the chance the page gave them, against how often they actually won.</p>
        <div class="tablewrap"><table><thead><tr><th>Stated chance</th><th class="num">Picks</th><th class="num">Said</th><th class="num">Won</th></tr></thead><tbody>${bands}</tbody></table></div></div>
      <div class="panel"><h2>Accuracy vs the closing line</h2><p class="lede">Average miss in points, every prediction made before the game.</p>
        <div class="tablewrap"><table><thead><tr><th>Season</th><th class="num">Spread: model</th><th class="num">close</th><th class="num">Total: model</th><th class="num">close</th></tr></thead><tbody>
        ${(B.by_season || []).slice().reverse().map(s => `<tr><td>${s.season}</td><td class="num${s.spread_model < s.spread_market ? " w" : ""}">${num(s.spread_model, 2)}</td><td class="num">${num(s.spread_market, 2)}</td><td class="num${s.total_model < s.total_market ? " w" : ""}">${num(s.total_model, 2)}</td><td class="num">${num(s.total_market, 2)}</td></tr>`).join("")}
        <tr><td><strong>All</strong></td><td class="num"><strong>${num(o.spread_model, 2)}</strong></td><td class="num"><strong>${num(o.spread_market, 2)}</strong></td><td class="num"><strong>${num(o.total_model, 2)}</strong></td><td class="num"><strong>${num(o.total_market, 2)}</strong></td></tr></tbody></table></div>
        <p class="note">The closing line is the toughest benchmark in sports; a model that matches it is doing well. Green picks are where the disagreement has historically been worth betting.</p></div></div>`;
  }

  // ------------------------------------------------------------------ your profit and loss (overrides/bet_slips.csv)
  function pnlPanel() {
    const P = S.pnl || {}, T = P.total || {}, wk = (P.weeks || []).slice().reverse(), slips = P.slips || [];
    if (!slips.length) return "";
    const usd = x => fin(x) ? (x >= 0 ? "+$" : "−$") + Math.abs(x).toFixed(2) : "–";
    const cls = x => fin(x) ? (x > 0 ? "w" : x < 0 ? "l" : "") : "";
    const rec = x => x && x.n ? `${x.w}-${x.l}${x.p ? "-" + x.p : ""}` : "0-0";
    const kp = (label, val, sub, c) => `<div class="kpi${c ? " kpi-green" : ""}"><div class="kl">${label}</div><div class="kv ${cls(val)}">${usd(val)}</div><div class="ks">${sub}</div></div>`;
    return `<div class="panel"><h2>My bets: profit and loss</h2>
      <p class="lede" style="margin:0">Your DraftKings bets as DraftKings settled them, week by week and all time.</p>
      <div class="kpis" style="grid-template-columns:repeat(4,minmax(0,1fr));margin:10px 0">
        ${kp("All time", T.profit, `${rec(T)} · $${num(T.staked, 0)} staked · ${fin(T.roi) ? sgn(100 * T.roi, 1) + "%" : "–"} return`, true)}
        ${kp("This week", wk.length ? wk[0].profit : NaN, wk.length ? `Week ${wk[0].week}: ${rec(wk[0])}` : "")}
        ${kp("Straight bets", (P.singles || {}).profit, `${rec(P.singles)} · $${num((P.singles || {}).staked, 0)} staked`)}
        ${kp("Parlays", (P.parlays || {}).profit, `${rec(P.parlays)} · $${num((P.parlays || {}).staked, 0)} staked`)}</div>
      ${T.open ? `<p class="note">${T.open} open bet${T.open > 1 ? "s" : ""} ($${num(T.open_stake, 0)} at risk) not counted yet.</p>` : ""}
      <div class="tablewrap"><table><thead><tr><th>Week</th><th class="num">Record</th><th class="num">Staked</th><th class="num">Profit</th><th class="num">Return</th><th class="num">Running total</th></tr></thead><tbody>
      ${wk.map(w => `<tr><td>Week ${w.week}, ${w.season}</td><td class="num">${rec(w)}</td><td class="num">$${num(w.staked, 0)}</td><td class="num ${cls(w.profit)}">${usd(w.profit)}</td><td class="num">${fin(w.roi) ? sgn(100 * w.roi, 1) + "%" : "–"}</td><td class="num ${cls(w.cum)}">${usd(w.cum)}</td></tr>`).join("")}</tbody></table></div>
      <details style="margin-top:8px"><summary>All ${slips.length} bets</summary><div class="tablewrap"><table><thead><tr><th>Date</th><th>Bet</th><th class="num">Odds</th><th class="num">Stake</th><th class="num">Result</th><th class="num">Profit</th></tr></thead><tbody>
      ${slips.map(x => `<tr><td class="muted">${esc(x.date)}</td><td>${x.type === "parlay" ? '<span class="chip">PARLAY</span> ' : ""}${esc(x.bet)}</td><td class="num">${fin(x.price) ? am(x.price) : "–"}</td><td class="num">$${num(x.stake, 0)}</td><td class="num">${x.result ? resChip(x.result) : '<span class="muted">open</span>'}</td><td class="num ${cls(x.profit)}">${usd(x.profit)}</td></tr>`).join("")}</tbody></table></div></details>
      <p class="note">Send me your new bets (screenshots are fine) and I'll add them. Past results don't guarantee future ones.</p></div>`;
  }

  // ------------------------------------------------------------------ Bets (this season, live)
  let betsFilter = "top";
  function renderBets() {
    const all = (REC.live || []).slice().sort((x, y) => (y.run_at || "").localeCompare(x.run_at || ""));
    const list = betsFilter === "top" ? all.filter(p => p.top) : betsFilter === "green" ? all.filter(p => p.highlight && p.market !== "wind") : betsFilter === "all" ? all : all.filter(p => p.market === betsFilter);
    const wk = (REC.by_week || []).slice().reverse();
    const c = r => r && r.n ? `${recTxt(r)} <span class="small muted">${pct(r.pct, 0)}${fin(r.units) ? " · " + sgn(r.units, 1) + "u" : ""}</span>` : '<span class="dash">–</span>';
    view.innerHTML = `${pnlPanel()}<div class="panel"><h2>${esc(String(REC.current_season || ""))} week by week</h2><p class="lede">Weeks the backtest already covers are graded at the closing line; later weeks at DraftKings' price from the last run before kickoff.</p>
      ${wk.length ? `<div class="tablewrap"><table class="rec-table"><thead><tr><th>Week</th><th class="num gcol">Top picks</th><th class="num gcol">Green picks</th><th class="num">All spreads</th><th class="num">All totals</th><th class="num">Winners</th></tr></thead><tbody>
      ${wk.map(w => `<tr><td>Week ${w.week}</td><td class="num gcol">${c(w.top)}</td><td class="num gcol">${c(w.green)}</td><td class="num">${c(w.spread)}</td><td class="num">${c(w.total)}</td><td class="num">${c(w.winner)}</td></tr>`).join("")}</tbody></table></div>` : `<p class="empty">No graded weeks yet.</p>`}</div>
      <div class="panel"><div class="toolbar" style="justify-content:space-between"><div><h2>Live pick tracker</h2><p class="lede">Every pick from the weekly runs as the page showed it before kickoff. CLV = points better than DraftKings' closing line, the best early test of whether the edge is real.</p></div>
        <div class="seg" role="group" aria-label="Filter">${[["top", "Top"], ["green", "Green"], ["wind", "Wind"], ["spread", "Spreads"], ["total", "Totals"], ["winner", "Winners"], ["all", "All"]].map(([k, l]) => `<button type="button" data-bf="${k}" aria-pressed="${betsFilter === k}">${l}</button>`).join("")}</div></div>
      ${list.length ? `<div class="tablewrap"><table><thead><tr><th>Week</th><th>Game</th><th>Pick</th><th class="num">Price</th><th class="num">Chance</th><th class="num">Value</th><th class="num">CLV</th><th class="num">Result</th><th class="num">Units</th></tr></thead><tbody>
      ${list.map(p => `<tr${p.highlight ? ' class="grow"' : ""}><td>${p.week}</td><td>${esc(p.matchup)}</td><td><strong>${esc(p.bet)}</strong>${topTag(p)}</td><td class="num">${am(p.price)}</td><td class="num">${pct(p.chance, 1)}</td><td class="num">${p.market === "winner" ? "" : val(p)}</td><td class="num">${fin(p.clv) ? sgn(p.clv) : "–"}</td><td class="num">${p.result ? resChip(p.result) : '<span class="muted">pending</span>'}</td><td class="num">${fin(p.units) ? sgn(p.units, 2) : ""}</td></tr>`).join("")}</tbody></table></div>` : `<p class="empty">Picks are logged from the scheduled weekly runs and graded after each game.</p>`}</div>
      ${myStatsPanel()}`;
    wireMyStats();
    view.querySelectorAll("[data-bf]").forEach(b => b.onclick = () => { betsFilter = b.dataset.bf; renderBets(); });
  }

  // ------------------------------------------------------------------ Futures
  let futSort = "p_sb", futGroup = "all";
  function renderFutures() {
    const sim = S.season_sim;
    if (!sim) { view.innerHTML = `<p class="empty">The season simulation runs with the weekly model.</p>`; return; }
    const teams = sim.teams.slice().sort((x, y) => (y[futSort] || 0) - (x[futSort] || 0));
    const grouped = {};
    if (futGroup === "div") teams.forEach(t => (grouped[t.division] = grouped[t.division] || []).push(t));
    else if (futGroup === "conf") teams.forEach(t => { const c = t.division.slice(0, 3); (grouped[c] = grouped[c] || []).push(t); });
    else grouped["All teams"] = teams;
    const col = (k, l) => `<th class="num"><button class="btn" type="button" data-fs="${k}" style="padding:2px 6px;font-size:11px;${futSort === k ? "background:var(--ink);color:var(--card)" : ""}">${l}</button></th>`;
    const cell = p => `<td class="num">${pct(p, p < 0.1 && p > 0 ? 1 : 0)}<span class="pbar" style="width:${Math.round(40 * p)}px"></span></td>`;
    const table = ts => `<div class="tablewrap"><table><thead><tr><th>Team</th><th class="num">Record</th><th class="num">Rating</th>
      ${col("wins_mean", "Wins")}${col("p_playoffs", "Playoffs")}${col("p_div", "Division")}${col("p_bye", "Bye")}${col("p_conf", "Conference")}${col("p_sb", "Super Bowl")}<th class="num">Fair SB odds</th></tr></thead><tbody>
      ${ts.map(t => `<tr><td>${team(t.team)}</td><td class="num">${t.wins_now}-${t.losses_now}${t.ties_now ? "-" + t.ties_now : ""}</td><td class="num">${sgn(t.rating)}</td>
        <td class="num">${num(t.wins_mean)} <span class="small muted">${num(t.wins_p10, 0)}–${num(t.wins_p90, 0)}</span></td>${cell(t.p_playoffs)}${cell(t.p_div)}${cell(t.p_bye)}${cell(t.p_conf)}${cell(t.p_sb)}
        <td class="num">${t.p_sb > 0.0005 ? am(toAm(t.p_sb)) : "–"}</td></tr>`).join("")}</tbody></table></div>`;
    view.innerHTML = `<div class="panel"><div class="toolbar" style="justify-content:space-between"><div><h2>Season simulation</h2>
      <p class="lede">${Number(sim.n_sims).toLocaleString()} simulated seasons of the ${sim.games_left} remaining games, as of week ${sim.week}. Ratings are points per game against an average team: the market's rating from closing lines, nudged by the model.</p></div>
      <div class="seg" role="group" aria-label="Group">${[["all", "All"], ["conf", "Conference"], ["div", "Division"]].map(([k, l]) => `<button type="button" data-fg="${k}" aria-pressed="${futGroup === k}">${l}</button>`).join("")}</div></div>
      ${Object.entries(grouped).sort().map(([k, ts]) => (futGroup === "all" ? "" : `<p class="section-label">${esc(k)}</p>`) + table(ts)).join("")}
      <p class="note">Each season plays out with a random rating shock per team (sd ${sim.rating_sd} pts) plus game noise (sd ${sim.game_sd}), home field ${num(sim.hfa)} pts. Seeding: division winners 1-4, then three wild cards; ties broken by point differential (the league's tiebreakers are more involved). Fair odds carry no bookmaker margin.</p></div>`;
    view.querySelectorAll("[data-fs]").forEach(b => b.onclick = () => { futSort = b.dataset.fs; renderFutures(); });
    view.querySelectorAll("[data-fg]").forEach(b => b.onclick = () => { futGroup = b.dataset.fg; renderFutures(); });
  }

  // ------------------------------------------------------------------ Teams
  let teamOpen = null;
  function renderTeams(sel) {
    const W = S.weeks[curKey], sim = S.season_sim;
    if (sel) teamOpen = sel;
    const power = (W && W.power) || [];
    const simBy = {}; (sim ? sim.teams : []).forEach(t => simBy[t.team] = t);
    const nextG = {}; (W ? W.games : []).forEach(g => { nextG[g.home_team] = g; nextG[g.away_team] = g; });
    const list = sim ? sim.teams.slice().sort((x, y) => y.rating - x.rating) : power.map(p => ({ team: p.team, rating: p.net_pts }));
    const rows = list.map((t, i) => {
      const p = power.find(x => x.team === t.team) || {}, g = nextG[t.team];
      const cont = g ? (g.home_team === t.team ? [g.h_off_cont, g.h_def_cont] : [g.a_off_cont, g.a_def_cont]) : [];
      const opp = g ? (g.home_team === t.team ? "vs " + g.away_team : "@ " + g.home_team) : "bye";
      return `<tr class="teamrow" data-team="${esc(t.team)}"><td class="num">${i + 1}</td><td>${team(t.team, ` <span class="rec">${recText(t.team)}</span>`)}</td>
        <td class="num"><strong>${sgn(t.rating)}</strong></td><td class="num">${sgn(t.market_rating)}</td><td class="num">${sgn(p.net_pts)}</td>
        <td class="num">${sgn(p.off_pts)}</td><td class="num">${sgn(fin(p.def_pts) ? -p.def_pts : NaN)}</td><td>${esc(p.proj_qb || "")}</td>
        <td class="num">${fin(cont[0]) ? pct((cont[0] + cont[1]) / 2) : "–"}</td><td>${esc(opp)}</td></tr>`;
    }).join("");
    let detail = "";
    if (teamOpen) {
      const T = teamOpen;
      const gs = ((S.schedule || {}).games || []).filter(g => g.home_team === T || g.away_team === T);
      const grow = gs.map(g => {
        const home = g.home_team === T, opp = home ? g.away_team : g.home_team;
        const lv = liveFor(g); let hs = g.home_score, as = g.away_score;
        if (hs == null && lv && lv.completed) { hs = lv.home_score; as = lv.away_score; }
        const my = home ? hs : as, their = home ? as : hs;
        const line = fin(g.spread_line) ? (home ? -g.spread_line : g.spread_line) : NaN;
        const ats = my != null && fin(line) ? (my - their + line > 0 ? "W" : my - their + line < 0 ? "L" : "P") : "";
        const when = g.gameday ? new Date(g.gameday + "T17:00:00Z").toLocaleDateString("en-US", { ...ET, weekday: "short", month: "short", day: "numeric" }) : "";
        return `<tr><td>W${g.week}</td><td>${home ? "vs" : "@"} ${team(opp)}</td><td class="num">${my != null ? `<strong class="${my > their ? "w" : my < their ? "l" : ""}">${my > their ? "W" : my < their ? "L" : "T"}</strong> ${my}–${their}` : esc(when)}</td>
          <td class="num">${fin(line) ? esc(T + " " + hcap(line)) : "–"}</td><td>${ats ? resChip(ats) : ""}</td></tr>`;
      }).join("");
      const st = simBy[T];
      detail = `<div class="panel" id="teamdetail"><div class="gd-head">${team(T, "", true)}<h2 style="margin:0">${esc(NAMES[T] || T)}</h2><span class="rec">${recText(T)}</span><button class="btn close" type="button" data-tclose>Close</button></div>
        ${st ? `<p class="gd-sub">Projected ${num(st.wins_mean)} wins · playoffs ${pct(st.p_playoffs)} · division ${pct(st.p_div)} · Super Bowl ${pct(st.p_sb, 1)}</p>` : ""}
        <div class="tablewrap"><table><thead><tr><th>Week</th><th>Opponent</th><th class="num">Result</th><th class="num">Line</th><th>ATS</th></tr></thead><tbody>${grow}</tbody></table></div></div>`;
    }
    view.innerHTML = detail + `<div class="panel"><h2>Power ratings</h2><p class="lede">Points per game better than an average team on a neutral field. Click a team for its schedule and results.</p>
      <div class="tablewrap"><table><thead><tr><th class="num">#</th><th>Team</th><th class="num">Rating</th><th class="num">Market</th><th class="num">Model</th><th class="num">Offense</th><th class="num">Defense</th><th>Projected QB</th><th class="num">Returning snaps</th><th>This week</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="note">Rating = market rating blended with the model's by the backtest weight (used for the season simulation). Market = rating implied by closing spreads. Model, Offense, Defense = the model's opponent-adjusted points ratings (defense positive = allows fewer). Returning snaps = share of last season's snaps by players still on the roster.</p></div>`;
    view.querySelectorAll("[data-team]").forEach(r => r.onclick = () => { location.hash = "teams/" + r.dataset.team; });
    const c = view.querySelector("[data-tclose]"); if (c) c.onclick = () => { teamOpen = null; location.hash = "teams"; };
    if (sel) { const el = document.getElementById("teamdetail"); if (el) el.scrollIntoView({ block: "start" }); }
  }

  // ------------------------------------------------------------------ Players
  function renderPlayers() {
    const W = S.weeks[curKey];
    const qbs = (W && W.qbs) || [];
    const starters = new Set(); (W ? W.games : []).forEach(g => { starters.add(g.h_qb_name_used); starters.add(g.a_qb_name_used); });
    const miss = []; (W ? W.games : []).forEach(g => { [["a", g.away_team], ["h", g.home_team]].forEach(([s, t]) => {
      const txt = g[s + "_miss_names"]; if (txt) txt.split("; ").forEach(x => miss.push({ team: t, text: x })); }); });
    view.innerHTML = `<div class="two"><div class="panel"><h2>Quarterback ratings</h2><p class="lede">Expected points per game above an average QB: recency-weighted EPA per play, shrunk toward replacement level for small samples. Bold = projected starter this week.</p>
      <div class="tablewrap"><table><thead><tr><th class="num">#</th><th>QB</th><th>Team</th><th class="num">Pts/game vs avg</th><th class="num">EPA/play</th><th class="num">Weighted plays</th></tr></thead><tbody>
      ${qbs.slice(0, 64).map((q, i) => { const st = [...starters].some(n => n && q.qb_name && (n === q.qb_name || n.split(" ").pop() === q.qb_name.split(".").pop()));
        return `<tr><td class="num">${i + 1}</td><td>${st ? "<strong>" + esc(q.qb_name) + "</strong>" : esc(q.qb_name)}</td><td>${team(q.team)}</td><td class="num">${sgn(q.pts_vs_avg)}</td><td class="num">${num(q.value, 3)}</td><td class="num">${Math.round(q.wplays)}</td></tr>`; }).join("")}</tbody></table></div></div>
      <div class="panel"><h2>Starters on the injury report</h2><p class="lede">Regular starters (by snap share) listed out, doubtful or questionable, or off the active roster. The model counts each by his chance of sitting. Source: ESPN's same-day injury page over the league's report.</p>
      ${miss.length ? `<div class="tablewrap"><table><thead><tr><th>Team</th><th>Player (position, status)</th></tr></thead><tbody>${miss.map(m => `<tr><td>${team(m.team)}</td><td>${esc(m.text)}</td></tr>`).join("")}</tbody></table></div>` : `<p class="empty">No regular starters on the injury report.</p>`}</div></div>`;
  }

  // ------------------------------------------------------------------ Info
  function auditPanel() {
    const A = S.audit;
    if (!A) return "";
    const ok = x => x && x.ok ? '<span class="w">✓ verified</span>' : x && x.note ? '<span class="muted">not run</span>' : '<span class="l">✗ check</span>';
    const sc = A.scores || {}, ln = A.lines || {}, vn = A.venues || {}, ij = A.injuries || {}, bk = A.books || {};
    const rows = [
      ["Final scores", "nflverse vs ESPN scoreboard", sc.games ? `${(sc.matched || 0) - (sc.n_mismatch || 0)} of ${sc.games} games match exactly (${esc(sc.seasons || "")})` : esc(sc.note || "not run"), sc],
      ["Closing lines", "nflverse, internal consistency", ln.games ? `${ln.games} games: ${ln.missing_spread} missing spreads, ${ln.missing_total} missing totals, ${ln.n_favorite_disagree} spread/moneyline favorite conflicts; spread vs result correlation ${num(ln.spread_result_corr, 2)}${ln.n_moneyline_entry_errors ? `; ${ln.n_moneyline_entry_errors} games with a moneyline entry error in the source` : ""}` : "", ln],
      ["Stadiums", "our table vs ESPN venue data", `${vn.stadiums || 0} home stadiums, ${vn.n_issues || 0} roof or surface conflicts`, vn],
      ["Injuries", "ESPN same-day page vs rosters and the league report", ij.listings ? `${ij.listings} listings, ${pct(ij.matched_share, 1)} matched to a rostered player; ${ij.n_status_disagree} status conflicts with the league report; ${ij.qb_flags && ij.qb_flags.length ? ij.qb_flags.length + " projected starting QB(s) listed out" : "no projected starting QB listed out"}` : esc(ij.note || ""), ij],
      ["Sportsbooks", "The Odds API, latest snapshot", bk.books_seen ? `${Object.keys(bk.books_seen).length} books returned prices: ${Object.keys(bk.books_seen).map(b => BOOKS[b] || b).join(", ")}` : esc(bk.note || ""), bk]
    ];
    return `<div class="panel"><h2>Data audit</h2><p class="lede">Every source checked against an independent one, ${esc(fmtStamp(dt(A.built)))}.</p>
      <div class="tablewrap"><table><thead><tr><th>Data</th><th>Checked against</th><th>Result</th><th></th></tr></thead><tbody>
      ${rows.map(([a, b, c, x]) => `<tr><td><strong>${a}</strong></td><td class="muted">${b}</td><td>${c}</td><td class="num">${ok(x)}</td></tr>`).join("")}</tbody></table></div>
      ${ij.unmatched && ij.unmatched.length ? `<details class="leans"><summary>${ij.unmatched.length} injury listings not on a roster (usually practice-squad players)</summary><p class="small muted">${ij.unmatched.map(u => esc(`${u.full_name} (${u.team} ${u.position}, ${u.report_status})`)).join(" · ")}</p></details>` : ""}
      <p class="note">nflverse's own surface field lists some turf stadiums as grass, so the model uses its own stadium table, checked here against ESPN.</p></div>`;
  }

  function renderInfo() {
    const W = S.weeks[curKey] || {};
    view.innerHTML = `<div class="panel"><h2>Checks</h2><p class="lede">Run on every site build. ${(S.checks || []).filter(c => c[1]).length} of ${(S.checks || []).length} pass.</p>
      <ul class="checks">${(S.checks || []).map(c => `<li><span class="${c[1] ? "ok" : "bad"}">${c[1] ? "✓" : "✗"}</span>${esc(c[0])}${c[2] ? ` <span class="muted small">${esc(c[2])}</span>` : ""}</li>`).join("")}</ul></div>
      ${auditPanel()}
      <div class="panel prose"><h2>How the model works</h2>
      <p>Every week the model sets its own spread and total for each game from about 140 inputs: opponent-adjusted team ratings from play-by-play (weighted EPA, early downs, big plays, points per drive, pass and run efficiency), the projected starting quarterback, missing starters by position, offseason roster turnover, rest, travel, time zones, kickoff time, weather forecasts, surface, altitude, coaching, officials and more. Each factor group has to earn its place in a walk-forward backtest; groups that make out-of-sample predictions worse are dropped.</p>
      <p><strong>Picks.</strong> For spreads and totals the pick is the model's side of DraftKings' number. Its chance comes from history: of every game since ${esc(String(REC.since || 2015))} where the model disagreed with the closing line by that many points, how often its side won. <strong>Green</strong> marks picks whose chance is at least 1 point above the win rate DraftKings' price needs to break even (and whose disagreement range has actually favored the model), ranked by that margin. <strong>Top picks</strong> are spreads where the model is 4 or more points off the line (always shown green), the range with the strongest record in both halves of the backtest. Until Oct 2, 2026 they also had to pass the green test, which made the record jumpy: small model changes could switch a whole season's 4+ picks off. <strong>Injury report.</strong> A Questionable player counts as playing 66% of the time (42% if he missed his last practice, 68% if limited, 79% if full) and a Doubtful player 1%, the rates measured from 41,663 listings in 2013-2025. The same rule, applied to every past season with only earlier seasons' information, produces the track record on the Record tab.</p>
      <h3>Schedule</h3><p>The model runs Tuesday morning, Thursday and Friday afternoon, twice on Sunday before kickoff and Monday afternoon. The line watch logs DraftKings' line from ESPN and live scores every 20 minutes. Calibration re-runs every Tuesday after Monday night.</p>
      <h3>Sources</h3><p>Play-by-play, schedules, closing lines, rosters, snap counts and the league injury report: nflverse (the open NFL data project behind nflfastR). Same-day injury reports, live scores, venues and the DraftKings line history: ESPN. DraftKings and other sportsbook prices: The Odds API. Weather forecasts: Open-Meteo. Every source is cross-checked above on each weekly run.</p>
      <h3>Read this before betting</h3><p>NFL closing lines miss the final margin by about 10 points on average, and the model does not beat them on its own. Break-even at −110 is 52.4%, and a real edge is a few points above that at best. Judge the model over seasons, not weekends. For information only, not financial advice. If betting stops being fun, call 1-800-GAMBLER.</p>
      ${W.notes && W.notes.length ? `<h3>Notes from the latest run</h3><ul>${W.notes.map(n => `<li class="small">${esc(n)}</li>`).join("")}</ul>` : ""}</div>`;
  }

  // ------------------------------------------------------------------ Gamecast
  let gcGame = null, gcData = null, gcTimer = null, gcErr = "";
  async function loadSummary(id) {
    try { gcData = await fetch(`${ESPN}/summary?event=${id}`, { cache: "no-store" }).then(r => r.json()); gcErr = ""; }
    catch (e) { gcErr = "ESPN's game feed did not respond; retrying."; }
  }
  function renderLive(sel) {
    const W = S.weeks[curKey];
    if (!W) { view.innerHTML = `<p class="empty">No weekly run yet.</p>`; return; }
    const games = W.games.slice().sort((x, y) => { const a = liveFor(x) || {}, b = liveFor(y) || {};
      const rank = l => l.state === "in" ? 0 : l.state === "pre" ? 1 : 2; return rank(a) - rank(b) || (x.kickoff_utc || "").localeCompare(y.kickoff_utc || ""); });
    if (sel) gcGame = sel;
    if (!gcGame) { const lv = games.find(g => (liveFor(g) || {}).state === "in"); gcGame = (lv || games[0]).game_id; }
    const g = games.find(x => x.game_id === gcGame) || games[0], lv = liveFor(g) || {};
    const chips = games.map(x => { const l = liveFor(x) || {};
      return `<button type="button" data-gc="${esc(x.game_id)}" aria-pressed="${x.game_id === g.game_id}" class="${l.state === "in" ? "livechip" : ""}">${esc(x.away_team)} ${l.state !== "pre" && l.away_score != null ? l.away_score : ""} @ ${esc(x.home_team)} ${l.state !== "pre" && l.home_score != null ? l.home_score : ""}${l.state === "in" ? ` · ${esc(l.detail || "")}` : l.completed ? " · F" : ""}</button>`; }).join("");
    const d = derive(W, g);
    const S_ = gcData && gcData.header && gcData.header.id === String(lv.espn_id) ? gcData : null;
    const picks = [d.sp, d.tt, d.wn].filter(Boolean).concat(((W.teasers || {}).legs || []).filter(l => l.game_id === g.game_id))
      .concat((W.wind_unders || []).filter(x => x.game_id === g.game_id && x.highlight).map(x => Object.assign({}, x, { bet: "Wind: " + x.bet })));
    const pickRows = picks.map(p => `<tr${p.top ? ' class="grow top"' : p.highlight ? ' class="grow"' : ""}><td><strong>${esc(p.bet)}</strong>${p.teased != null ? ' <span class="muted small">teaser leg</span>' : ""}${topTag(p)}</td><td class="num">${p.price != null ? am(p.price) : ""}</td><td>${d.lv && d.lv.state === "in" ? liveStatus(p, d.lv.home_score, d.lv.away_score) : resChip(d.res(p)) || '<span class="muted">not started</span>'}</td></tr>`).join("");
    let body = `<p class="note">Loading ESPN's game feed…</p>`;
    if (S_) {
      const comp = (S_.header.competitions || [{}])[0], teamsById = {};
      (comp.competitors || []).forEach(c => teamsById[c.id || (c.team && c.team.id)] = normTeam(c.team && c.team.abbreviation));
      const started = lv.state === "in" || lv.completed || lv.state === "post";
      const drives = ((S_.drives || {}).previous || []).slice().reverse();
      const cur = (S_.drives || {}).current;
      const allDrives = cur ? [cur].concat(drives) : drives;
      const plays = allDrives.length ? (allDrives[0].plays || []).slice().reverse().slice(0, 10) : [];
      const wp = (S_.winprobability || []).map(x => x.homeWinPercentage).filter(fin);
      let wpChart = "";
      if (wp.length > 1) {
        const W_ = 600, H_ = 130, pl = 36, pr = 8, pt = 8, pb = 18, x = i => pl + (W_ - pl - pr) * i / (wp.length - 1), y = v => pt + (H_ - pt - pb) * (1 - v);
        wpChart = `<svg class="chart" viewBox="0 0 ${W_} ${H_}" role="img" aria-label="Win probability"><line x1="${pl}" x2="${W_ - pr}" y1="${y(0.5)}" y2="${y(0.5)}" stroke="var(--line)" stroke-dasharray="3 3"/>
          <polyline fill="none" stroke="var(--model)" stroke-width="2" points="${wp.map((v, i) => `${x(i)},${y(v)}`).join(" ")}"/>
          <text x="${pl - 4}" y="${y(1) + 8}" text-anchor="end">${esc(g.home_team)}</text><text x="${pl - 4}" y="${y(0)}" text-anchor="end">${esc(g.away_team)}</text>
          <text x="${W_ - pr}" y="${y(wp[wp.length - 1]) - 4}" text-anchor="end" style="fill:var(--model)">${esc(g.home_team)} ${pct(wp[wp.length - 1])}</text></svg>`;
      }
      const bx = ((S_.boxscore || {}).teams || []);
      const want = ["Total Yards", "Passing", "Rushing", "Yards per Play", "3rd down efficiency", "4th down efficiency", "Turnovers", "Penalties", "Possession", "Red Zone (Made-Att)", "1st Downs", "Sacks-Yards Lost"];
      const statOf = (tm, lab) => { const s = (tm.statistics || []).find(z => z.label === lab); return s ? s.displayValue : "–"; };
      const aBx = bx.find(z => normTeam(z.team && z.team.abbreviation) === g.away_team) || bx[0] || {}, hBx = bx.find(z => normTeam(z.team && z.team.abbreviation) === g.home_team) || bx[1] || {};
      const stats = want.filter(l => (aBx.statistics || []).some(z => z.label === l)).map(l => `<tr><td class="num">${esc(statOf(aBx, l))}</td><td style="text-align:center" class="muted">${esc(l)}</td><td class="num">${esc(statOf(hBx, l))}</td></tr>`).join("");
      const leaders = (S_.leaders || []).map(tm => `<div><h3>${esc(normTeam(tm.team && tm.team.abbreviation))}</h3>${(tm.leaders || []).slice(0, 3).map(cat => { const L = (cat.leaders || [])[0]; return L ? `<div class="small"><span class="muted">${esc(cat.displayName)}:</span> <strong>${esc(L.athlete && L.athlete.displayName)}</strong> ${esc(L.displayValue)}</div>` : ""; }).join("")}</div>`).join("");
      const scoring = (S_.scoringPlays || []).slice().reverse().map(sp => `<li><span class="muted small">Q${sp.period && sp.period.number} ${esc(sp.clock && sp.clock.displayValue)}</span> <strong>${esc(normTeam(sp.team && sp.team.abbreviation))}</strong> ${esc(sp.text)} <span class="muted small">(${sp.awayScore}-${sp.homeScore})</span></li>`).join("");
      body = `<div class="two"><div><h3>${cur ? "Current drive" : "Last drive"}${allDrives[0] ? ` · ${esc(teamsById[allDrives[0].team && allDrives[0].team.id] || normTeam(allDrives[0].team && allDrives[0].team.abbreviation) || "")} ${esc(allDrives[0].description || "")}` : ""}</h3>
          ${plays.length ? `<ol class="plays">${plays.map(pl => `<li><span class="muted small">${esc((pl.start && pl.start.downDistanceText) || "")}</span> ${esc(pl.text)}</li>`).join("")}</ol>` : '<p class="note">No plays yet.</p>'}</div>
        <div><h3>Win probability (ESPN)</h3>${wpChart || '<p class="note">Starts at kickoff.</p>'}</div></div>
        ${!started ? '<p class="note">Game stats and leaders appear at kickoff (until then ESPN reports season totals, which are not shown here).</p>' : ""}
        ${started && stats ? `<h3 style="margin-top:12px">Team stats</h3><div class="tablewrap"><table class="gcstats"><thead><tr><th class="num">${esc(g.away_team)}</th><th></th><th class="num">${esc(g.home_team)}</th></tr></thead><tbody>${stats}</tbody></table></div>` : ""}
        ${started && leaders ? `<div class="two" style="margin-top:12px">${leaders}</div>` : ""}
        ${scoring ? `<h3 style="margin-top:12px">Scoring plays</h3><ul class="scoring">${scoring}</ul>` : ""}`;
    }
    const sit = lv.state === "in" ? `<div class="sit">${lv.possession ? `<span class="poss">● ${esc(lv.possession)} ball</span>` : ""}${lv.down ? ` <strong>${esc(lv.down)}</strong>` : ""}${lv.redzone ? ' <span class="chip warn">RED ZONE</span>' : ""}${lv.last_play ? `<div class="small muted">Last play: ${esc(lv.last_play)}</div>` : ""}</div>` : "";
    view.innerHTML = `<div class="chips" role="group" aria-label="Game">${chips}</div>
      <article class="panel gamecast"><div class="gc-score">
        <div class="gc-team">${team(g.away_team, "", true)}<span class="gc-pts">${lv.state && lv.state !== "pre" ? lv.away_score : ""}</span></div>
        <div class="gc-mid">${lv.state === "in" ? `<span class="live">${esc(lv.detail || "")}</span>` : lv.completed ? "<strong>Final</strong>" : `<strong>${esc(kick(g))}</strong>`}<div class="small muted">${esc(lv.broadcast || "")}</div></div>
        <div class="gc-team right"><span class="gc-pts">${lv.state && lv.state !== "pre" ? lv.home_score : ""}</span>${team(g.home_team, "", true)}</div></div>
        ${sit}
        ${pickRows ? `<h3 style="margin-top:12px">Our picks</h3><div class="tablewrap"><table><tbody>${pickRows}</tbody></table></div>` : ""}
        ${gcErr ? `<p class="note">${esc(gcErr)}</p>` : ""}
        <div style="margin-top:12px">${body}</div>
        <p class="note">Live data from ESPN, refreshed every 15 seconds while the game is on.</p></article>`;
    view.querySelectorAll("[data-gc]").forEach(b => b.onclick = () => { location.hash = "live/" + b.dataset.gc; });
    clearTimeout(gcTimer);
    if (lv.espn_id && (!S_ || lv.state === "in")) {
      gcTimer = setTimeout(async () => { await loadSummary(lv.espn_id); if (currentRoute === "live") renderLive(); }, S_ ? 15000 : 0);
    }
  }

  let currentRoute = "games";
  function onLive() {
    header();
    if (["games", "live", "picks", "bets"].includes(currentRoute) && !document.querySelector("#view input:focus, #view select:focus")) {
      const y = window.scrollY; ROUTES[currentRoute](); window.scrollTo({ top: y });
    }
  }

  // ------------------------------------------------------------------ alerts (pick status changes + DraftKings line moves)
  const SEEN_KEY = "nflmodel-alerts-seen", NOTIFY_KEY = "nflmodel-notify";
  const store = { get: k => { try { return localStorage.getItem(k); } catch (e) { return null; } },
                  set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } } };
  const ALERTS = S.alerts || [];
  const lastSeen = () => store.get(SEEN_KEY) || "";
  const isLost = a => /^No longer/.test(a.title);
  const unseen = () => ALERTS.filter(a => a.level === "high" && a.ts > lastSeen());
  function alertBadge() {
    const tab = document.getElementById("alerts-tab"); if (!tab) return;
    const n = unseen().length;
    tab.innerHTML = "Alerts" + (n ? `<span class="alert-count" title="${n} new pick change${n > 1 ? "s" : ""}">${n}</span>` : "");
  }
  let alertFilter = "pick";
  function alertList(list, seenBefore) {
    if (!list.length) return '<p class="empty">Nothing yet this week.</p>';
    return `<ul class="alist">${list.map(a => `<li class="${a.level}${isLost(a) ? " lost" : ""}${a.level === "high" && a.ts > seenBefore ? " new" : ""}">
      <div class="when">${esc(fmtDay(dt(a.ts)))} ${esc(fmtTime(dt(a.ts)))}</div>
      <div><div><span class="ttl">${esc(a.title)}</span> · <a href="#breakdown/${esc(a.game_id)}">${esc(a.matchup)}</a></div><div class="small">${esc(a.text)}</div></div></li>`).join("")}</ul>`;
  }
  function renderAlerts() {
    const seenBefore = lastSeen();
    const list = alertFilter === "all" ? ALERTS : ALERTS.filter(a => a.kind === alertFilter);
    const perm = "Notification" in window ? Notification.permission : "unsupported";
    const on = store.get(NOTIFY_KEY) === "on" && perm === "granted";
    view.innerHTML = `<div class="panel"><div class="toolbar" style="justify-content:space-between"><div><h2>Alerts this week</h2>
      <p class="lede" style="margin:0">Every time a pick turns green or Top, stops being green or Top, or switches sides, and every DraftKings line move, with what changed. The pick that counts is the one from the last run before kickoff (about 80 minutes before).</p></div>
      <div class="seg" role="group" aria-label="Filter">${[["pick", "Pick changes"], ["line", "Line moves"], ["all", "All"]].map(([k, l]) => `<button type="button" data-af="${k}" aria-pressed="${alertFilter === k}">${l}</button>`).join("")}</div></div>
      ${alertList(list, seenBefore)}
      <div class="toolbar" style="margin-top:12px">${perm === "unsupported" ? '<span class="small muted">This browser does not support notifications.</span>'
        : on ? '<span class="small">Notifications are on for this browser.</span> <button class="btn" type="button" id="notify-off">Turn off</button>'
        : perm === "denied" ? '<span class="small muted">Notifications are blocked for this site in your browser settings.</span>'
        : '<button class="btn primary" type="button" id="notify-on">Notify me about pick changes</button>'}</div>
      <p class="note">Browser notifications work while this page is open in a tab (it checks for updates every 5 minutes). New pick changes also show as a red count on the Alerts tab.</p></div>${alertSettings()}`;
    wireAlertSettings();
    view.querySelectorAll("[data-af]").forEach(b => b.onclick = () => { alertFilter = b.dataset.af; renderAlerts(); });
    const bOn = document.getElementById("notify-on"), bOff = document.getElementById("notify-off");
    if (bOn) bOn.onclick = async () => { const p = await Notification.requestPermission(); if (p === "granted") { store.set(NOTIFY_KEY, "on"); new Notification("NFL Line Model", { body: "Alerts are on. You'll hear about pick changes while this page is open." }); } renderAlerts(); };
    if (bOff) bOff.onclick = () => { store.set(NOTIFY_KEY, "off"); renderAlerts(); };
    if (ALERTS.length) store.set(SEEN_KEY, ALERTS.reduce((m, a) => a.ts > m ? a.ts : m, ""));
    alertBadge();
  }
  // check for a newer build every 5 minutes; tell the viewer about new pick changes
  function watchUpdates() {
    const known = new Set(ALERTS.map(a => a.id)), told = new Set();
    setInterval(async () => {
      try {
        const txt = await (await fetch("data/site.js?t=" + Date.now(), { cache: "no-store" })).text();
        const N = JSON.parse(txt.slice(txt.indexOf("=") + 1).replace(/;\s*$/, ""));
        if (!N.built || N.built === S.built) return;
        const fresh = (N.alerts || []).filter(a => a.level === "high" && !known.has(a.id) && !told.has(a.id));
        const ban = document.getElementById("update-banner");
        ban.hidden = false;
        ban.innerHTML = `<span><strong>${fresh.length ? `${fresh.length} new pick change${fresh.length > 1 ? "s" : ""}` : "New prices"}</strong>${fresh.length ? ": " + esc(fresh.slice(0, 2).map(a => `${a.matchup}, ${a.title.toLowerCase()}`).join("; ")) : " are available"}.</span> <button class="btn primary" type="button" id="reload-btn">Refresh</button>`;
        document.getElementById("reload-btn").onclick = () => location.reload();
        const mineA = fresh.filter(wantAlert);
        if (mineA.length && store.get(NOTIFY_KEY) === "on" && "Notification" in window && Notification.permission === "granted") {
          mineA.slice(0, 3).forEach(a => new Notification(`${a.title}: ${a.matchup}`, { body: a.text, tag: a.id }));
          if (mineA.length > 3) new Notification("NFL Line Model", { body: `${mineA.length - 3} more pick changes. Open the Alerts tab.` });
        }
        fresh.forEach(a => told.add(a.id));
      } catch (e) { /* offline or mid-deploy: try again next time */ }
    }, 300000);
  }

  // ------------------------------------------------------------------ early-week value (information only)
  function earlyPanel(W) {
    const E = S.early || {}; const R = E.record || {}; const rows = E.week || [];
    const games = {}; W.games.forEach(g => games[g.game_id] = g);
    const moved = x => !fin(x.moved) ? "–" : x.moved > 0 ? `<span class="w">${sgn(x.moved, 1)} for</span>` : x.moved < 0 ? `<span class="l">${sgn(x.moved, 1)} against</span>` : "no move";
    const now = x => fin(x.line_now) ? (x.line_now > 0 ? "+" : x.line_now < 0 ? "−" : "") + trim(Math.abs(x.line_now)) : "–";
    const body = rows.length ? `<div class="tablewrap"><table><thead><tr><th>Game</th><th>Early pick</th><th class="num">Edge</th><th>Logged</th><th class="num">DraftKings now</th><th class="num">Line since</th><th class="num">Result</th></tr></thead><tbody>
      ${rows.map(x => { const g = games[x.game_id]; return `<tr><td>${g ? `<a href="#breakdown/${esc(x.game_id)}">${esc(x.matchup)}</a>` : esc(x.matchup)}</td><td><strong>${esc(x.bet)}</strong> ${am(x.price)}</td><td class="num">${edgeTxt(x.edge)}</td>
        <td class="small muted">${esc(fmtDay(dt(x.run_at)))} ${esc(fmtTime(dt(x.run_at)))}</td><td class="num">${now(x)}</td><td class="num">${moved(x)}</td><td class="num">${x.result ? resChip(x.result) : '<span class="muted">pending</span>'}</td></tr>`; }).join("")}</tbody></table></div>`
      : `<p class="note">None this week: the week's first model run had no spread ${num(E.edge, 0)}+ points off DraftKings.</p>`;
    return `<div class="panel noprint"><h2>Early-week value <span class="small muted">(information only)</span></h2>
      <p class="lede" style="margin:0">Spreads where the week's first model run was ${num(E.edge, 0)}+ points off DraftKings' early line, logged at that line and price. In the backtest these did better at early lines than the same bets at the close (56-59% at 3+ points against two sources' opening lines, 2015-2026), but that is not proven at DraftKings, so it is tracked here first. Early in the week the model does not know the final injury reports.</p>
      ${body}
      <p class="note">Tracked since ${esc(R.since || "2026 week 4")}: ${R.n ? `${R.w}-${R.l}${R.p ? "-" + R.p : ""} (${pct(R.pct, 1)}, ${sgn(R.units, 1)} units at the early price)` : "no graded games yet"}${fin(R.clv) && R.clv_n ? `; the line moved ${sgn(R.clv, 2)} points per pick in their favor by kickoff (${R.clv_n} games)` : ""}. "Line since" = points the early pick gained (+) or lost (−) vs DraftKings' line now.</p></div>`;
  }

  // ------------------------------------------------------------------ How it works
  function renderHow() {
    const A = (REC.all || {}).total || {}, T = A.top || {}, G = A.green || {}, SP = A.spread || {};
    const WI = ((REC.wind || {}).with_live) || {}, TZ = ((REC.teasers || {}).teasers) || {}, CR = REC.card || {};
    const B = (S.backtest || {}).overall || {};
    const r = x => x && x.n ? `${x.w}-${x.l}${x.p ? "-" + x.p : ""} (${pct(x.pct, 1)}, ${sgn(x.units, 1)} units)` : "–";
    const sec = (h, body) => `<div class="panel"><h2>${h}</h2>${body}</div>`;
    const flow = `<svg viewBox="0 0 760 92" class="chart" role="img" aria-label="From data to picks">
      ${[["Data", "games, plays, injuries, weather"], ["Team ratings", "and other factors"], ["Model line", "spread and total"],
         ["vs DraftKings", "how many points off"], ["Chance and value", "from history"], ["Picks", "green, Top, card"]].map(([a, b], i) => {
        const x = 6 + i * 126;
        return `<rect x="${x}" y="14" width="112" height="56" rx="8" fill="var(--card2)" stroke="var(--line)"/>
          <text x="${x + 56}" y="38" text-anchor="middle" style="font-weight:600;fill:var(--ink)">${a}</text>
          <text x="${x + 56}" y="56" text-anchor="middle" style="font-size:10.5px">${b}</text>
          ${i < 5 ? `<path d="M${x + 114} 42 h10" stroke="var(--muted)" stroke-width="1.5" marker-end="url(#arr)"/>` : ""}`; }).join("")}
      <defs><marker id="arr" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="var(--muted)"/></marker></defs></svg>`;
    view.innerHTML = `<div class="panel"><h2>How the numbers are made</h2>
      <p class="lede">The model sets its own spread and total for every game, compares them with DraftKings, and uses history to say how often that much disagreement has actually won. Everything below is the same rule the site uses live and for the track record.</p>${flow}</div>
      ${sec("1. Where the data comes from", `<ul>
        <li><strong>nflverse</strong> (free, public NFL data): every play since 2012 with expected points (EPA), schedules, scores and closing lines, snap counts, weekly rosters and injury reports.</li>
        <li><strong>DraftKings prices</strong>: from The Odds API (also 9 other books for comparison) and ESPN's scoreboard, which shows DraftKings' line. The site checks them every 15 minutes.</li>
        <li><strong>ESPN</strong>: the newest injury designations and live scores. <strong>Open-Meteo</strong>: kickoff weather forecasts. <strong>Kalshi</strong>: prediction-market prices, saved for a future test only.</li></ul>`)}
      ${sec("2. How the model sets a line", `<p>For each team it builds ratings from recent games, weighted toward the latest weeks and adjusted for opponents: passing and rushing efficiency on offense and defense, points per drive, special teams, and the market's own view of each team from earlier weeks' closing lines. It then adds the game's situation: the projected quarterbacks' value, which regular players are out, rest and travel, kickoff time, weather, venue, coaching and officials.</p>
        <p>A statistical model (ridge regression with a small boosted-tree part) turns all of that into a predicted margin and total. It learns how much each factor is worth only from <em>earlier</em> seasons, and it never sees this game's betting line. The spread is then blended 75/25 with the market's recent view of both teams, which tested better than the model alone.</p>
        <p><strong>Injuries:</strong> a Questionable player counts as playing 66% of the time (42% if he missed his last practice, 68% limited, 79% full) and Doubtful 1%, the rates measured from 41,663 past listings. A Questionable starting quarterback starts 57% of the time (37% / 53% / 85% by last practice), so his value is blended with the backup's.</p>`)}
      ${sec("3. From the model's number to a pick", `<p><strong>The pick</strong> is the model's side of DraftKings' number. Example: the model has Tampa Bay by 0.5 and DraftKings has Tampa Bay +3.5, so the model is 4 points off and the pick is Tampa Bay +3.5.</p>
        <p><strong>Chance</strong> comes from history, not the model's own confidence: of every past game where the model was that far off the closing line (0-2, 2-4 or 4+ points), how often its side won. It is pulled toward 50% so thin samples can't overstate it.</p>
        <p><strong>Value</strong> = chance minus what the price needs to break even (-110 needs 52.4%). <strong>Green</strong> = at least 1 point of value. <strong>Top pick</strong> = any spread where the model is 4+ points off DraftKings (always green).</p>
        <p><strong>Fair line</strong> (on the breakdown): about 90% the betting market and 10% the model, because the closing line is very hard to beat; the model's own error is ${num(B.spread_model, 2)} points per game vs ${num(B.spread_market, 2)} for the closing line.</p>`)}
      ${sec("4. The weekly card and other picks", `<ul>
        <li><strong>Top picks</strong>: ${esc(r(T))} since ${esc(String(REC.since || 2015))} at closing prices.</li>
        <li><strong>Teasers</strong>: two underdogs of +1.5 to +2.5, teased 6 points past 3 and 7: ${esc(r(TZ))}.</li>
        <li><strong>Wind unders</strong>: outdoor games with a kickoff forecast of 10+ mph wind or 20+ mph gusts: ${esc(r(WI))} since 2018.</li>
        <li>All together the card went ${esc(r(CR))}. Green picks overall: ${esc(r(G))}. Every spread pick, no filter: ${esc(r(SP))}.</li>
        <li><strong>Early-week value</strong> (information only): spreads 3+ points off at the week's first run, graded at that early line, to test whether betting early helps at DraftKings.</li></ul>`)}
      ${sec("5. How the track record is built", `<p>Each season from ${esc(String(REC.since || 2015))} on was predicted by a model trained only on earlier seasons, and each season's chance numbers use only earlier seasons too. Picks are graded at the real closing line and price. This season's games are also graded live at DraftKings' price from the last update before kickoff, which is the truest test.</p>
        <p><strong>Be realistic:</strong> some settings were chosen by looking at these same years, and a test with random noise showed the pick records swing by 10+ units from tiny changes. Expect live results somewhat below the backtest, and losing weeks are normal even at 57%.</p>`)}
      ${sec("6. How new ideas get tested", `<p>Every idea is tested against a fresh copy of the model on the same data. It goes in only if it cuts the spread error by more than random noise does (0.006 points) in both 2015-20 and 2021-26, and the pick record stays within the range random changes produce. Most ideas fail: ESPN's FPI, about 60 public computer ratings, Next Gen Stats, skill-player injuries and 32 classic betting angles all did not help. You approve every change before it goes live.</p>`)}
      ${sec("7. Limits", `<p>NFL betting markets are efficient and these edges are small; even the best group wins a bit under 60%. Lines and injuries change through the week, so a pick is final at the update about 80 minutes before kickoff. Confirm every price in the DraftKings app. Information only, not financial advice.</p>`)}`;
  }

  // ================================================================== extras (Oct 2026): app install, phone tab bar,
  // bet logging, personal stats, recap, parlay calculator, bet sizing, team follows, team colors
  const COLORS = { ARI: "#97233F", ATL: "#A71930", BAL: "#241773", BUF: "#00338D", CAR: "#0085CA", CHI: "#0B162A", CIN: "#FB4F14",
    CLE: "#FF3C00", DAL: "#003594", DEN: "#FB4F14", DET: "#0076B6", GB: "#203731", HOU: "#03202F", IND: "#002C5F", JAX: "#006778",
    KC: "#E31837", LA: "#003594", LAC: "#0080C6", LV: "#A5ACAF", MIA: "#008E97", MIN: "#4F2683", NE: "#002244", NO: "#D3BC8D",
    NYG: "#0B2265", NYJ: "#125740", PHI: "#004C54", PIT: "#FFB612", SEA: "#69BE28", SF: "#AA0000", TB: "#D50A0A", TEN: "#4B92DB", WAS: "#5A1414" };
  const jget = (k, d) => { try { const v = JSON.parse(store.get(k) || "null"); return v == null ? d : v; } catch (e) { return d; } };
  const jset = (k, v) => store.set(k, JSON.stringify(v));
  const MYBETS = "nflmodel-mybets", FOLLOW = "nflmodel-follow", BANK = "nflmodel-bankroll", KELLY = "nflmodel-kelly", BNOTE = "nflmodel-bnotify";
  const follows = () => new Set(jget(FOLLOW, []));
  const isFollowed = g => { const f = follows(); return f.has(g.home_team) || f.has(g.away_team); };
  const toggleFollow = t => { const f = follows(); f.has(t) ? f.delete(t) : f.add(t); jset(FOLLOW, [...f]); };
  const usd = x => fin(x) ? (x >= 0 ? "+$" : "−$") + Math.abs(x).toFixed(2) : "–";
  const profitOf = (res, price, stake) => res === "W" ? stake * (dec(price) - 1) : res === "L" ? -stake : res === "P" ? 0 : null;
  const allGames = () => { const m = {}; (S.schedule && S.schedule.games || []).forEach(g => m[g.game_id] = g); Object.values(S.weeks || {}).forEach(W => W.games.forEach(g => m[g.game_id] = Object.assign({}, m[g.game_id] || {}, g))); return m; };
  function finalFor(gid) {
    const g = allGames()[gid]; if (!g) return null;
    if (g.home_score != null && g.away_score != null && g.result != null) return [g.home_score, g.away_score];
    const lv = liveFor(g); return lv && lv.completed ? [lv.home_score, lv.away_score] : null;
  }
  const gradeLeg = l => { if (!l.game_id || !l.market) return null; const f = finalFor(l.game_id); return f ? gradePick(l, f[0], f[1]) : null; };
  function myBets() {   // bets logged on this device, graded automatically when their games are final
    return jget(MYBETS, []).map(b => {
      let res = b.result || null;
      if (!res && b.type === "single") res = gradeLeg(b);
      if (!res && b.type === "parlay" && b.legs && b.legs.length) {
        const rs = b.legs.map(gradeLeg);
        res = rs.includes("L") ? "L" : rs.every(r => r === "W") ? "W" : null;
      }
      return Object.assign({}, b, { result: res, profit: profitOf(res, b.price, b.stake) });
    });
  }
  // ---------- bottom sheet (log a bet, more menu)
  function sheet(html) {
    const el = document.getElementById("sheet"); if (!el) return;
    el.innerHTML = `<div class="sheet-card" role="dialog" aria-modal="true">${html}</div>`; el.hidden = false;
    el.onclick = e => { if (e.target === el || e.target.closest("[data-close-sheet]")) el.hidden = true; };
    return el;
  }
  function logBetSheet(b) {
    const k = jget(KELLY, 0.25), bank = jget(BANK, null);
    const sug = bank && fin(b.chance) && fin(b.price) ? kellyStake(b.chance, b.price, bank, k) : null;
    const el = sheet(`<h3 style="margin-top:0">Log this bet</h3>
      <label class="fld">Bet<input id="lb-bet" value="${esc(b.bet || "")}"></label>
      <div class="two-fld"><label class="fld">Odds<input id="lb-price" inputmode="numeric" value="${fin(b.price) ? Math.round(b.price) : ""}"></label>
      <label class="fld">Stake ($)<input id="lb-stake" inputmode="decimal" value="${jget("nflmodel-laststake", 10)}"></label></div>
      ${sug != null ? `<p class="note">Bet sizing guide (${Math.round(k * 100)}% Kelly, bankroll $${num(bank, 0)}): about $${num(sug, 2)}. Information only.</p>` : ""}
      <p class="note">Saved on this device and graded automatically when the game ends. Use "Export for Claude" on the Bets tab to add it to your official record.</p>
      <div class="toolbar"><button class="btn primary" type="button" id="lb-save">Save bet</button><button class="btn" type="button" data-close-sheet>Cancel</button></div>`);
    el.querySelector("#lb-save").onclick = () => {
      const price = parseFloat(el.querySelector("#lb-price").value), stake = parseFloat(el.querySelector("#lb-stake").value);
      if (!fin(price) || Math.abs(price) < 100 || !fin(stake) || stake <= 0) { alert("Enter American odds (like -110 or +150) and a stake."); return; }
      const list = jget(MYBETS, []);
      list.push(Object.assign({ id: "b" + Date.now(), date: new Date().toISOString().slice(0, 10), type: "single" }, b,
        { bet: el.querySelector("#lb-bet").value, price, stake, logged: new Date().toISOString() }));
      jset(MYBETS, list); jset("nflmodel-laststake", stake); el.hidden = true;
      if (currentRoute === "bets") renderBets();
    };
  }
  const logAttr = (p, src) => `data-log='${esc(JSON.stringify({ game_id: p.game_id, season: p.season, week: p.week, market: p.market === "wind" ? "total" : p.market,
    side: p.side, line: p.line, teased: p.teased, price: p.price, chance: p.chance, bet: p.bet, source: src || (p.top ? "top" : p.highlight ? "green" : "lean") }))}'`;
  const logBtn = (p, src) => `<span class="logbtn" role="button" tabindex="0" ${logAttr(p, src)}>+ Log bet</span>`;
  document.addEventListener("click", e => {
    const t = e.target.closest("[data-log]");
    if (t) { e.preventDefault(); e.stopPropagation(); try { logBetSheet(JSON.parse(t.getAttribute("data-log"))); } catch (err) { /* ignore */ } return; }
    const f = e.target.closest("[data-follow]");
    if (f) { e.preventDefault(); e.stopPropagation(); toggleFollow(f.getAttribute("data-follow")); route(); }
  }, true);
  // ---------- bet sizing (Kelly), information only
  function kellyStake(p, price, bank, frac) {
    const b = dec(price) - 1, f = (b * p - (1 - p)) / b;
    return Math.max(0, Math.min(f * frac, 0.03)) * bank;     // never more than 3% of the bankroll
  }
  // ---------- "Bet now": this week's card at a glance, with price movement since the week opened
  function betNowPanel(W) {
    const games = {}; W.games.forEach(g => games[g.game_id] = g);
    const open = gid => { const L = (S.lines || {})[gid]; return L && L.points && L.points.length ? L.points[0] : null; };
    const row = (p, kind) => { const g = games[p.game_id]; if (!g) return ""; const o = open(p.game_id); let mv = "";
      if (o && p.market === "spread" && fin(g.dk_home_spread)) { const d = g.dk_home_spread - o[1]; if (Math.abs(d) > 1e-9) mv = `line ${hcap(o[1])} → ${hcap(g.dk_home_spread)} (${g.home_team})`; }
      if (o && (p.market === "total" || p.market === "wind") && fin(g.dk_total)) { const d = g.dk_total - o[2]; if (Math.abs(d) > 1e-9) mv = `total ${trim(o[2])} → ${trim(g.dk_total)}`; }
      const d = derive(W, g), started = d.lv && d.lv.state !== "pre";
      return `<div class="bn-row${isFollowed(g) ? " fav" : ""}"><span class="chip ${kind === "TOP" ? "top" : ""}">${kind}</span><strong>${esc(p.bet)}</strong> <span class="muted">${am(p.price)}</span>
        <span class="small muted">${esc(g.away_team)} @ ${esc(g.home_team)} · ${esc(kick(g))}${mv ? " · " + esc(mv) : ""}</span>${started ? "" : logBtn(p, kind === "TOP" ? "top" : kind === "WIND" ? "wind" : "green")}</div>`; };
    const tops = (W.picks || []).filter(p => p.top), wind = (W.wind_unders || []).filter(x => x.highlight),
      greens = (W.picks || []).filter(p => p.highlight && !p.top && p.market !== "winner");
    const items = tops.map(p => row(p, "TOP")).concat(wind.map(x => row(x, "WIND")), greens.map(p => row(p, "GREEN"))).join("");
    return `<div class="panel betnow"><div class="toolbar" style="justify-content:space-between;margin:0"><h2>Bet now: this week's picks at DraftKings' current price</h2><a class="btn" href="#tools">Parlay calculator</a></div>
      ${items || `<p class="note">No Top, wind or green picks right now. Prices update every 15 minutes; picks are final about 80 minutes before kickoff.</p>`}
      <p class="note">Check the price in the DraftKings app before betting. Information only, not financial advice.</p></div>`;
  }
  // ---------- personal stats on the Bets tab
  function myStatsPanel() {
    const P = S.pnl || {}, mine = myBets();
    const SRC = { top: "Top picks", green: "Green picks", wind: "Wind unders", teaser: "Teasers", lean: "Model leans (not green)", parlay: "Parlays", other: "Other" };
    const bs = P.by_source || {}, C = P.clv || {};
    const rows = Object.keys(bs).map(k => { const x = bs[k]; return `<tr><td>${esc(SRC[k] || k)}</td><td class="num">${x.w}-${x.l}${x.p ? "-" + x.p : ""}</td><td class="num">$${num(x.staked, 0)}</td><td class="num ${x.profit > 0 ? "w" : x.profit < 0 ? "l" : ""}">${usd(x.profit)}</td></tr>`; }).join("");
    const cum = P.cum || [];
    let chart = "";
    if (cum.length > 1) {
      const W_ = 560, H_ = 120, pl = 44, pr = 10, pt = 10, pb = 18, v = cum.map(c => c[1]), lo = Math.min(0, ...v), hi = Math.max(0, ...v);
      const x = i => pl + (W_ - pl - pr) * i / (cum.length - 1), y = q => pt + (H_ - pt - pb) * (hi - q) / Math.max(hi - lo, 1);
      chart = `<svg class="chart" viewBox="0 0 ${W_} ${H_}" role="img" aria-label="Your running profit"><line x1="${pl}" x2="${W_ - pr}" y1="${y(0)}" y2="${y(0)}" stroke="var(--line)"/>
        <polyline fill="none" stroke="var(--accent)" stroke-width="2.2" points="${cum.map((c, i) => `${x(i)},${y(c[1])}`).join(" ")}"/>
        <text x="${pl - 5}" y="${y(hi) + 4}" text-anchor="end">${usd(hi)}</text><text x="${pl - 5}" y="${y(lo) + 4}" text-anchor="end">${usd(lo)}</text></svg>`;
    }
    const mineRows = mine.slice().reverse().map(b => `<tr><td class="muted">${esc(b.date)}</td><td>${b.type === "parlay" ? '<span class="chip">PARLAY</span> ' : ""}${esc(b.bet)}</td><td class="num">${am(b.price)}</td><td class="num">$${num(b.stake, 0)}</td><td class="num">${b.result ? resChip(b.result) : '<span class="muted">open</span>'}</td><td class="num">${usd(b.profit)}</td><td><span class="logbtn" role="button" data-del="${esc(b.id)}">remove</span></td></tr>`).join("");
    const mineTot = mine.reduce((s, b) => s + (b.profit || 0), 0);
    return `<div class="panel"><h2>Your betting stats</h2>
      ${rows ? `<div class="two"><div><h3>By pick type</h3><div class="tablewrap"><table><thead><tr><th>Type</th><th class="num">Record</th><th class="num">Staked</th><th class="num">Profit</th></tr></thead><tbody>${rows}</tbody></table></div>
        <p class="note">${C.n ? `Your line vs DraftKings' closing line (straight bets): better on ${C.beat}, same on ${C.same}, worse on ${C.n - C.beat - C.same}; average ${sgn(C.avg, 2)} points. Beating the close is the best early sign of a real edge.` : ""}</p></div>
        <div><h3>Running profit</h3>${chart || '<p class="note">The chart starts after a second graded bet.</p>'}</div></div>` : ""}
      <h3>Logged on this device</h3>
      ${mine.length ? `<div class="tablewrap"><table><thead><tr><th>Date</th><th>Bet</th><th class="num">Odds</th><th class="num">Stake</th><th class="num">Result</th><th class="num">Profit</th><th></th></tr></thead><tbody>${mineRows}</tbody></table></div>
        <p class="note">Total: ${usd(mineTot)} (not in the official record above until you send them to me).</p>
        <div class="toolbar"><button class="btn primary" type="button" id="mb-export">Export for Claude</button><button class="btn" type="button" id="mb-clear">Clear after export</button></div>`
        : `<p class="note">Tap "+ Log bet" on any pick to save it here; it is graded automatically when the game ends.</p>`}</div>`;
  }
  function wireMyStats() {
    view.querySelectorAll("[data-del]").forEach(b => b.onclick = () => { jset(MYBETS, jget(MYBETS, []).filter(x => x.id !== b.dataset.del)); renderBets(); });
    const ex = document.getElementById("mb-export"), cl = document.getElementById("mb-clear");
    if (ex) ex.onclick = async () => {
      const lines = myBets().map(b => [b.date, b.season, b.week, b.type, `"${(b.bet || "").replace(/"/g, "'")} (logged in app)"`, b.price, b.stake, b.result || "",
        b.result === "W" ? (b.stake + b.profit).toFixed(2) : "", b.source || "", b.game_id || "", b.market || "", b.side || "", b.line != null ? b.line : ""].join(","));
      const text = "My logged bets (bet_slips.csv rows):\n" + lines.join("\n");
      try { if (navigator.share) await navigator.share({ text }); else { await navigator.clipboard.writeText(text); alert("Copied. Paste it to Claude."); } } catch (e) { prompt("Copy this and send it to Claude:", text); }
    };
    if (cl) cl.onclick = () => { if (confirm("Remove the bets logged on this device? Do this after I have added them to your record.")) { jset(MYBETS, []); renderBets(); } };
  }
  // ---------- weekly recap
  let recapKey = null;
  function renderRecap() {
    const live = (REC.live || []).filter(p => p.result);
    const keys = [...new Set(live.map(p => `${p.season}-${String(p.week).padStart(2, "0")}`).concat((S.pnl && S.pnl.weeks || []).map(w => `${w.season}-${String(w.week).padStart(2, "0")}`)))].sort();
    if (!keys.length) { view.innerHTML = `<div class="panel"><h2>Weekly recap</h2><p class="empty">The first recap appears once a week's games are graded.</p></div>`; return; }
    const key = recapKey && keys.includes(recapKey) ? recapKey : keys[keys.length - 1];
    const [se, wk] = key.split("-").map(Number);
    const rows = live.filter(p => p.season === se && p.week === wk);
    const games = allGames();
    const score = gid => { const f = finalFor(gid), g = games[gid]; return f && g ? `${g.away_team} ${f[1]}, ${g.home_team} ${f[0]}` : ""; };
    const sumr = list => { const w = list.filter(p => p.result === "W").length, l = list.filter(p => p.result === "L").length, u = list.reduce((s, p) => s + (p.units || 0), 0);
      return `${w}-${l}${list.length - w - l ? "-" + (list.length - w - l) : ""}, ${sgn(u, 1)} units`; };
    const lst = list => list.length ? `<ul class="recap">${list.map(p => `<li>${resChip(p.result)} <strong>${esc(p.bet)}</strong> ${am(p.price)} <span class="muted small">· ${esc(p.matchup || "")} · ${esc(score(p.game_id))}${fin(p.edge) && p.edge >= 0.1 ? ` · model ${edgeTxt(p.edge)} pts off` : ""}${fin(p.clv) ? ` · line vs close ${sgn(p.clv, 1)}` : ""}</span></li>`).join("")}</ul>` : '<p class="note">None.</p>';
    const tops = rows.filter(p => p.top), greens = rows.filter(p => p.highlight && !p.top && p.market !== "wind"), wind = rows.filter(p => p.market === "wind");
    const early = ((S.early || {}).all || []).filter(x => x.season === se && x.week === wk && x.result);
    const mine = (S.pnl && S.pnl.slips || []).filter(x => x.season === se && x.week === wk && x.result);
    const mp = mine.reduce((s, x) => s + (x.profit || 0), 0);
    const hl = tops.concat(greens, wind), best = hl.filter(p => p.result === "W").sort((a, b) => (b.edge || 0) - (a.edge || 0))[0], worst = hl.filter(p => p.result === "L").sort((a, b) => (b.edge || 0) - (a.edge || 0))[0];
    view.innerHTML = `<div class="panel"><div class="toolbar" style="justify-content:space-between;margin:0"><h2>Week ${wk} recap, ${se}</h2>
      <select id="rk" aria-label="Week">${keys.map(k => `<option value="${k}"${k === key ? " selected" : ""}>Week ${+k.split("-")[1]}, ${k.split("-")[0]}</option>`).join("")}</select></div>
      <div class="kpis" style="grid-template-columns:repeat(4,minmax(0,1fr));margin:10px 0">
        <div class="kpi kpi-green"><div class="kl">Top picks</div><div class="kv">${tops.length ? sumr(tops).split(",")[0] : "–"}</div><div class="ks">${tops.length ? sumr(tops).split(",")[1] : "none this week"}</div></div>
        <div class="kpi"><div class="kl">Green picks</div><div class="kv">${greens.length ? sumr(greens).split(",")[0] : "–"}</div><div class="ks">${greens.length ? sumr(greens).split(",")[1] : ""}</div></div>
        <div class="kpi"><div class="kl">Wind unders</div><div class="kv">${wind.length ? sumr(wind).split(",")[0] : "–"}</div><div class="ks">${wind.length ? sumr(wind).split(",")[1] : ""}</div></div>
        <div class="kpi"><div class="kl">Your bets</div><div class="kv ${mp > 0 ? "w" : mp < 0 ? "l" : ""}">${mine.length ? usd(mp) : "–"}</div><div class="ks">${mine.length ? `${mine.filter(x => x.result === "W").length}-${mine.filter(x => x.result === "L").length}` : "none logged"}</div></div></div>
      ${best || worst ? `<p class="lede">${best ? `Best call: <strong>${esc(best.bet)}</strong> (${esc(best.matchup || "")})${fin(best.edge) && best.edge >= 0.1 ? `, the model was ${edgeTxt(best.edge)} points off` : ""} and it hit. ` : ""}${worst ? `Toughest miss: <strong>${esc(worst.bet)}</strong> (${esc(worst.matchup || "")})${fin(worst.edge) && worst.edge >= 0.1 ? `, ${edgeTxt(worst.edge)} points off` : ""}. ` : ""}One week is mostly luck; the record is what matters.</p>` : ""}</div>
      <div class="two"><div class="panel"><h3 style="margin-top:0">Top picks</h3>${lst(tops)}<h3>Wind unders</h3>${lst(wind)}</div>
      <div class="panel"><h3 style="margin-top:0">Green picks</h3>${lst(greens)}<h3>Early-week value (information only)</h3>${early.length ? `<ul class="recap">${early.map(x => `<li>${resChip(x.result)} <strong>${esc(x.bet)}</strong> ${am(x.price)} <span class="muted small">· ${esc(x.matchup)}${fin(x.clv) ? ` · line vs close ${sgn(x.clv, 1)}` : ""}</span></li>`).join("")}</ul>` : '<p class="note">None.</p>'}</div></div>
      ${mine.length ? `<div class="panel"><h3 style="margin-top:0">Your bets</h3><ul class="recap">${mine.map(x => `<li>${resChip(x.result)} ${x.type === "parlay" ? '<span class="chip">PARLAY</span> ' : ""}<strong>${esc(x.bet)}</strong> <span class="muted small">· $${num(x.stake, 0)} · ${usd(x.profit)}</span></li>`).join("")}</ul></div>` : ""}
      <p class="note">Picks as the site showed them at the last update before kickoff, graded at that DraftKings price (the all-time record grades covered weeks at the closing line, so its week totals can differ). Information only, not financial advice.</p>`;
    view.querySelector("#rk").onchange = e => { recapKey = e.target.value; renderRecap(); };
  }
  // ---------- tools: parlay calculator + bet sizing
  let parlayLegs = [];
  function renderTools() {
    const W = S.weeks[curKey] || { games: [], picks: [] };
    const games = {}; W.games.forEach(g => games[g.game_id] = g);
    const pool = (W.picks || []).filter(p => p.market !== "winner" && games[p.game_id] && fin(p.price) && fin(p.chance))
      .concat((W.wind_unders || []).filter(x => x.highlight && fin(x.price)))
      .sort((a, b) => (b.top ? 1 : 0) - (a.top ? 1 : 0) || (b.highlight ? 1 : 0) - (a.highlight ? 1 : 0) || (b.value || 0) - (a.value || 0));
    const key = p => `${p.game_id}|${p.market}`;
    const legs = parlayLegs.filter(l => l.custom || pool.some(p => key(p) === l.key));
    const legObjs = legs.map(l => l.custom ? l : Object.assign({}, pool.find(p => key(p) === l.key), { key: l.key }));
    const boost = parseFloat(store.get("nflmodel-boost") || "0") || 0, stake = parseFloat(store.get("nflmodel-pstake") || "10") || 10;
    const dkOverride = parseFloat(store.get("nflmodel-dkodds") || "");
    let html = "";
    if (legObjs.length >= 2) {
      const decAll = legObjs.reduce((a, l) => a * dec(l.price), 1);
      const dkDec = fin(dkOverride) && Math.abs(dkOverride) >= 100 ? dec(dkOverride) : decAll;
      const pay = stake * (1 + (dkDec - 1) * (1 + boost / 100));
      const pTrue = legObjs.reduce((a, l) => a * l.chance, 1);
      const ev = pTrue * (pay - stake) - (1 - pTrue) * stake;
      const sameGame = new Set(legObjs.map(l => l.game_id)).size < legObjs.length;
      html = `<div class="kpis" style="grid-template-columns:repeat(4,minmax(0,1fr));margin:10px 0">
        <div class="kpi"><div class="kl">DraftKings pays</div><div class="kv">$${num(pay, 2)}</div><div class="ks">odds ${am(dkDec >= 2 ? (dkDec - 1) * 100 : -100 / (dkDec - 1))}${boost ? ` + ${boost}% boost` : ""} on $${num(stake, 0)}</div></div>
        <div class="kpi"><div class="kl">Model chance it hits</div><div class="kv">${pct(pTrue, 1)}</div><div class="ks">legs multiplied</div></div>
        <div class="kpi"><div class="kl">Break-even chance</div><div class="kv">${pct(stake / pay, 1)}</div><div class="ks">what the payout needs</div></div>
        <div class="kpi ${ev > 0 ? "kpi-green" : ""}"><div class="kl">Expected value</div><div class="kv ${ev > 0 ? "w" : "l"}">${usd(ev)}</div><div class="ks">per $${num(stake, 0)}, long run</div></div></div>
        ${sameGame ? '<p class="note">Two legs are from the same game; their outcomes are linked, so the multiplied chance is only a rough guide.</p>' : ""}
        <div class="toolbar"><span class="logbtn" role="button" id="pc-log">+ Log this parlay</span></div>`;
    }
    const bank = jget(BANK, null), k = jget(KELLY, 0.25);
    const sized = (W.picks || []).filter(p => p.highlight && p.market !== "winner").concat((W.wind_unders || []).filter(x => x.highlight)).map(p => {
      const g = games[p.game_id]; const s = bank ? kellyStake(p.chance, p.price, bank, k) : null;
      return `<tr><td><strong>${esc(p.bet)}</strong> ${am(p.price)}${p.top ? ' <span class="chip top">TOP</span>' : ""}</td><td>${g ? esc(g.away_team + " @ " + g.home_team) : ""}</td><td class="num">${pct(p.chance, 1)}</td><td class="num">${s != null ? "$" + num(s, 2) : "–"}</td></tr>`; }).join("");
    view.innerHTML = `<div class="panel"><h2>Parlay calculator</h2>
      <p class="lede" style="margin:0">Pick legs from this week's picks to see what DraftKings pays against the model's chance that every leg hits. Each leg's chance is its historical win rate, so a 3-leg parlay of 55% legs hits about 17% of the time.</p>
      <div class="toolbar" style="margin-top:10px"><label class="fld">Stake ($)<input id="pc-stake" inputmode="decimal" value="${stake}"></label>
        <label class="fld">Boost (%)<input id="pc-boost" inputmode="decimal" value="${boost || ""}" placeholder="0"></label>
        <label class="fld">DraftKings parlay odds (optional)<input id="pc-dk" inputmode="numeric" value="${fin(dkOverride) ? dkOverride : ""}" placeholder="from the bet slip"></label></div>
      <div class="pc-legs">${pool.map(p => { const g = games[p.game_id]; const on = legs.some(l => l.key === key(p));
        return `<label class="pc-leg${on ? " on" : ""}"><input type="checkbox" data-leg="${esc(key(p))}"${on ? " checked" : ""}> <strong>${esc(p.bet)}</strong> ${am(p.price)} <span class="muted small">${g ? esc(g.away_team + " @ " + g.home_team) : ""} · ${pct(p.chance, 0)}${p.top ? " · TOP" : p.highlight ? " · green" : ""}</span></label>`; }).join("")}</div>
      ${legObjs.length < 2 ? '<p class="note">Choose at least two legs.</p>' : html}
      <p class="note">Boosted parlays raise the payout, but the legs still all have to hit. Information only, not financial advice.</p></div>
      <div class="panel"><h2>Bet sizing guide</h2>
      <p class="lede" style="margin:0">A cautious stake for each green pick from its edge and your bankroll (fractional Kelly, capped at 3% of the bankroll per bet). Information only.</p>
      <div class="toolbar" style="margin-top:10px"><label class="fld">Bankroll ($)<input id="bs-bank" inputmode="decimal" value="${bank || ""}" placeholder="e.g. 200"></label>
        <label class="fld">Kelly fraction<select id="bs-k">${[[0.125, "1/8 (very cautious)"], [0.25, "1/4 (cautious)"], [0.5, "1/2"]].map(([v, l]) => `<option value="${v}"${v === k ? " selected" : ""}>${l}</option>`).join("")}</select></label></div>
      ${sized ? `<div class="tablewrap"><table><thead><tr><th>Pick</th><th>Game</th><th class="num">Chance</th><th class="num">Suggested stake</th></tr></thead><tbody>${sized}</tbody></table></div>` : '<p class="note">No green picks right now.</p>'}
      <p class="note">Edges are small, so the guide keeps stakes small; flat betting the same amount each time is also reasonable.</p></div>
      <div class="panel"><h2>Teams you follow</h2><p class="lede" style="margin:0">Followed teams' games show first on the Games tab and can be the only browser alerts you get (Alerts tab).</p>
      <div class="follow-grid">${Object.keys(COLORS).sort().map(t => `<span class="followchip${follows().has(t) ? " on" : ""}" role="button" data-follow="${t}" style="--tc:${COLORS[t]}">${esc(t)}</span>`).join("")}</div></div>`;
    view.querySelectorAll("[data-leg]").forEach(c => c.onchange = () => {
      const k2 = c.dataset.leg; parlayLegs = c.checked ? parlayLegs.concat([{ key: k2 }]) : parlayLegs.filter(l => l.key !== k2); renderTools(); });
    const bind = (id, keyName) => { const el = document.getElementById(id); if (el) el.onchange = () => { store.set(keyName, el.value); renderTools(); }; };
    bind("pc-stake", "nflmodel-pstake"); bind("pc-boost", "nflmodel-boost"); bind("pc-dk", "nflmodel-dkodds");
    const bb = document.getElementById("bs-bank"); if (bb) bb.onchange = () => { jset(BANK, parseFloat(bb.value) || null); renderTools(); };
    const bk = document.getElementById("bs-k"); if (bk) bk.onchange = () => { jset(KELLY, parseFloat(bk.value)); renderTools(); };
    const lp = document.getElementById("pc-log");
    if (lp) lp.onclick = () => {
      const decAll = legObjs.reduce((a, l) => a * dec(l.price), 1), dkDec = fin(dkOverride) && Math.abs(dkOverride) >= 100 ? dec(dkOverride) : decAll;
      const eff = 1 + (dkDec - 1) * (1 + boost / 100), price = eff >= 2 ? Math.round((eff - 1) * 100) : Math.round(-100 / (eff - 1));
      const list = jget(MYBETS, []);
      list.push({ id: "b" + Date.now(), date: new Date().toISOString().slice(0, 10), type: "parlay", season: W.season, week: W.week, source: "parlay",
        bet: `${legObjs.length} legs: ` + legObjs.map(l => l.bet).join(", ") + (boost ? ` (+${boost}% boost)` : ""), price, stake,
        legs: legObjs.map(l => ({ game_id: l.game_id, market: l.market === "wind" ? "total" : l.market, side: l.side, line: l.line })) });
      jset(MYBETS, list); alert("Saved on this device. It shows on the Bets tab and is graded when the games end.");
    };
  }
  // ---------- phone: install as an app, bottom tab bar, more menu
  let installEvt = null;
  window.addEventListener("beforeinstallprompt", e => { e.preventDefault(); installEvt = e; installHint(); });
  function installHint() {
    const standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;
    if (standalone || store.get("nflmodel-installhint") === "no") return;
    const ios = /iphone|ipad|ipod/i.test(navigator.userAgent), small = window.innerWidth < 760;
    if (!installEvt && !(ios && small)) return;
    const ban = document.getElementById("install-banner"); if (!ban) return;
    ban.hidden = false;
    ban.innerHTML = `<span>${installEvt ? "Install the site as an app for one-tap access." : "Add this site to your home screen: tap the Share button, then <strong>Add to Home Screen</strong>."}</span>
      ${installEvt ? '<button class="btn primary" type="button" id="inst-yes">Install</button>' : ""}<button class="btn" type="button" id="inst-no">Not now</button>`;
    const y = document.getElementById("inst-yes"); if (y) y.onclick = async () => { installEvt.prompt(); installEvt = null; ban.hidden = true; };
    document.getElementById("inst-no").onclick = () => { store.set("nflmodel-installhint", "no"); ban.hidden = true; };
  }
  function bottomBar() {
    const bb = document.getElementById("bottombar"); if (!bb) return;
    bb.querySelectorAll("a").forEach(a => a.getAttribute("href") === "#" + currentRoute ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
    const more = document.getElementById("more-btn");
    if (more) more.onclick = () => sheet(`<h3 style="margin-top:0">More</h3><div class="more-grid">${[["games", "Games"], ["live", "Gamecast"], ["picks", "Picks"], ["breakdown", "Breakdown"], ["alerts", "Alerts"], ["recap", "Weekly recap"], ["tools", "Parlay calculator and bet sizing"], ["futures", "Futures"], ["teams", "Teams"], ["players", "Players"], ["record", "Record"], ["bets", "Bets and P&L"], ["how", "How it works"], ["info", "Info"]].map(([k, l]) => `<a class="btn" href="#${k}" data-close-sheet>${l}</a>`).join("")}</div>`);
  }
  if ("serviceWorker" in navigator && location.protocol === "https:") navigator.serviceWorker.register("sw.js").catch(() => {});

  // ---------- browser alert settings (which pick changes notify this device)
  const ASET = "nflmodel-alertset";
  function wantAlert(a) {
    const s = jget(ASET, { which: "all", follow: false });
    if (s.which === "top" && !/Top/.test(a.title)) return false;
    if (s.follow && follows().size) { const tm = (a.matchup || "").split(" @ "); if (!tm.some(x => follows().has(x))) return false; }
    return true;
  }
  function alertSettings() {
    const s = jget(ASET, { which: "all", follow: false }), nf = follows().size;
    return `<div class="panel"><h2>Alert settings</h2>
      <div class="toolbar"><label class="fld">Browser notifications for<select id="as-which"><option value="all"${s.which === "all" ? " selected" : ""}>Every pick change</option><option value="top"${s.which === "top" ? " selected" : ""}>Top picks only</option></select></label>
      <label class="chk"><input type="checkbox" id="as-follow"${s.follow ? " checked" : ""}> Only teams I follow ${nf ? `(${nf})` : '(none yet: pick them on the <a href="#tools">Tools</a> tab)'}</label></div>
      <p class="note">Phone (ntfy) channels: your usual topic gets everything (pick changes plus one combined line-move push per update). Subscribe in the ntfy app to the same topic name with <strong>-picks</strong> on the end for pick changes only, or <strong>-top</strong> for Top picks only. Line-move pushes pause overnight (midnight to 7 AM Eastern); pick changes always go through.</p></div>`;
  }
  function wireAlertSettings() {
    const w = document.getElementById("as-which"), f = document.getElementById("as-follow");
    const save = () => jset(ASET, { which: w.value, follow: f.checked });
    if (w) w.onchange = save; if (f) f.onchange = save;
  }
  const SCROLL = {};

  // ------------------------------------------------------------------ router
  const ROUTES = { recap: renderRecap, tools: renderTools, how: renderHow, alerts: renderAlerts, games: renderGames, picks: renderPicks, breakdown: renderBreakdown, futures: renderFutures, teams: renderTeams,
    players: renderPlayers, record: renderRecord, backtest: renderRecord, bets: renderBets, info: renderInfo, live: renderLive };
  function route() {
    const [name, arg] = (location.hash.replace(/^#/, "") || "games").split("/");
    const r = ROUTES[name] ? (name === "backtest" ? "record" : name) : "games";
    if (r !== "live") { clearTimeout(gcTimer); }
    if (r === "live" && arg && arg !== gcGame) { gcData = null; }
    SCROLL[currentRoute] = window.scrollY;
    currentRoute = r;
    view.classList.remove("fade"); void view.offsetWidth; view.classList.add("fade");
    document.querySelectorAll("nav.tabs a").forEach(a => a.getAttribute("href") === "#" + r ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
    ROUTES[r](arg ? decodeURIComponent(arg) : undefined);
    bottomBar();
    if (!arg) window.scrollTo({ top: SCROLL[r] || 0 });
  }
  theme();
  if (!S.weeks || !weekKeys.length) { view.innerHTML = `<p class="empty">No data yet. The site fills in after the first weekly run.</p>`; return; }
  header();
  window.addEventListener("hashchange", route);
  route();
  pollScores();
  setInterval(header, 60000);              // keep the "updated ... ago" labels honest
  alertBadge();
  watchUpdates();
  installHint();
})();
