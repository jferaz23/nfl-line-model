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
    betrivers: "BetRivers", hardrockbet: "Hard Rock", bovada: "Bovada", mybookieag: "MyBookie", betus: "BetUS" };
  const GROUP_LABELS = {
    baseline: "Average game", team_strength: "Team strength", home_field: "Home field", quarterback: "Quarterbacks",
    injuries: "Injuries beyond the QB", weather: "Weather", rest_travel: "Rest and travel", time_of_day: "Kickoff time and body clock",
    scheme_matchup: "Scheme matchup", venue_history: "Venue history", surface_altitude: "Surface and altitude", coaching: "Coaching",
    officials: "Officials", history: "Head-to-head and ATS history", situational: "Situational and luck", drive_efficiency: "Drive efficiency",
    motivation: "Motivation (late season)", early_down: "Early-down efficiency", big_plays: "Big plays",
    roster_continuity: "Offseason roster turnover (weeks 1-8)", scoring_env: "Scoring environment", calendar: "Calendar"
  };

  // ------------------------------------------------------------------ helpers
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fin = x => typeof x === "number" && isFinite(x);
  const pct = (p, d = 0) => fin(p) ? (100 * p).toFixed(d) + "%" : "–";
  const num = (x, d = 1) => fin(x) ? x.toFixed(d) : "–";
  const sgn = (x, d = 1) => fin(x) ? (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d) : "–";
  const am = x => fin(x) ? (x > 0 ? "+" + Math.round(x) : "−" + Math.abs(Math.round(x))) : "–";
  const hcap = x => !fin(x) ? "–" : Math.abs(x) < 1e-9 ? "pk" : (x > 0 ? "+" : "−") + trim(Math.abs(x));
  const trim = x => (Math.round(x * 10) / 10).toString();
  const logoCode = t => ({ LA: "lar", WAS: "wsh" }[t] || String(t).toLowerCase());
  const logo = t => `https://a.espncdn.com/i/teamlogos/nfl/500/${logoCode(t)}.png`;
  const team = (t, extra = "", lg = false) => `<span class="team${lg ? " lg" : ""}"><img src="${logo(t)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">${esc(t)}${extra}</span>`;
  const ET = { timeZone: "America/New_York" };
  const dt = s => s ? new Date(s) : null;
  const fmtDay = d => d ? d.toLocaleDateString("en-US", { ...ET, weekday: "short" }) : "";
  const fmtTime = d => d ? d.toLocaleTimeString("en-US", { ...ET, hour: "numeric", minute: "2-digit" }) : "";
  const fmtLong = d => d ? d.toLocaleDateString("en-US", { ...ET, weekday: "long", month: "short", day: "numeric" }) : "";
  const fmtStamp = d => d ? d.toLocaleString("en-US", { ...ET, month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + " ET" : "";
  const implied = a => !fin(a) ? NaN : a < 0 ? -a / (-a + 100) : 100 / (a + 100);
  const noVig = (a, b) => { const x = implied(a), y = implied(b); return fin(x) && fin(y) ? x / (x + y) : NaN; };
  const toAm = p => !fin(p) || p <= 0 || p >= 1 ? NaN : p >= 0.5 ? -100 * p / (1 - p) : 100 * (1 - p) / p;
  const dec = a => a > 0 ? 1 + a / 100 : 1 + 100 / -a;
  const favLine = (h, a, m) => !fin(m) ? "–" : Math.abs(m) < 0.05 ? "Pick'em" : (m > 0 ? h : a) + " −" + trim(Math.abs(m));
  const logistic = (b, e) => 1 / (1 + Math.exp(-b * e));
  const byId = {};

  // ------------------------------------------------------------------ data prep
  const weekKeys = Object.keys(S.weeks || {}).sort();
  const curKey = weekKeys[weekKeys.length - 1];
  const live = {};
  ((S.live || {}).games || []).forEach(x => { live[`${x.season}-${x.week}-${x.home_team}-${x.away_team}`] = x; });
  const liveFor = g => live[`${g.season}-${g.week}-${g.home_team}-${g.away_team}`];
  const hist = (S.backtest && S.backtest.history) || {};
  const tracked = {};
  ((S.tracker || {}).picks || []).forEach(p => { (tracked[p.game_id] = tracked[p.game_id] || []).push(p); });

  function records() {
    const r = {};
    const add = (t, k) => { r[t] = r[t] || { w: 0, l: 0, t: 0 }; r[t][k]++; };
    const seen = new Set();
    (S.schedule && S.schedule.games || []).forEach(g => {
      if (g.game_type !== "REG") return;
      let hs = g.home_score, as = g.away_score;
      const lv = liveFor(g);
      if ((hs == null) && lv && lv.completed) { hs = lv.home_score; as = lv.away_score; }
      if (hs == null || as == null) return;
      seen.add(g.game_id);
      if (hs > as) { add(g.home_team, "w"); add(g.away_team, "l"); }
      else if (as > hs) { add(g.away_team, "w"); add(g.home_team, "l"); }
      else { add(g.home_team, "t"); add(g.away_team, "t"); }
    });
    return r;
  }
  const REC = records();
  const recText = t => { const x = REC[t]; return x ? `${x.w}-${x.l}${x.t ? "-" + x.t : ""}` : "0-0"; };

  // per-game derived numbers
  function derive(W, g) {
    if (g._d) return g._d;
    const h = g.home_team, a = g.away_team;
    const offers = (W.board || []).filter(b => b.game_id === g.game_id);
    const pr = b => b.p_win / Math.max(b.p_win + b.p_lose, 1e-9);
    const best = m => offers.filter(b => b.market === m).sort((x, y) => pr(y) - pr(x))[0] || null;
    const sp = best("spread"), tt = best("total"), ml = best("moneyline");
    const dkMargin = fin(g.dk_home_spread) ? -g.dk_home_spread : null;
    const d = { h, a, offers, sp, tt, ml, pr, dkMargin };
    // points of model disagreement toward each pick, and the historical hit rate for that disagreement
    if (sp) {
      const home = sp.bet.startsWith(h + " ");
      d.spEdge = fin(dkMargin) ? (home ? 1 : -1) * (g.model_margin - dkMargin) : null;
      d.spHist = fin(d.spEdge) && hist.spread ? logistic(hist.spread.b, d.spEdge) : null;
      d.spVegas = home ? noVig(g.dk_home_spread_price, g.dk_away_spread_price) : noVig(g.dk_away_spread_price, g.dk_home_spread_price);
      d.spHome = home;
    }
    if (tt) {
      const over = tt.bet.startsWith("Over");
      d.ttEdge = fin(g.dk_total) ? (over ? 1 : -1) * (g.model_total - g.dk_total) : null;
      d.ttHist = fin(d.ttEdge) && hist.total ? logistic(hist.total.b, d.ttEdge) : null;
      d.ttVegas = over ? noVig(g.dk_over_price, g.dk_under_price) : noVig(g.dk_under_price, g.dk_over_price);
      d.ttOver = over;
    }
    d.pHome = g.p_home_win; d.pHomeMkt = fin(g.dk_home_ml) ? noVig(g.dk_home_ml, g.dk_away_ml) : g.p_home_win_market;
    d.winner = fin(d.pHome) ? (d.pHome >= 0.5 ? h : a) : null;
    // implied team scores
    const T = g.model_total, M = g.model_margin;
    d.mh = (T + M) / 2; d.ma = (T - M) / 2;
    if (fin(g.dk_total) && fin(dkMargin)) { d.vh = (g.dk_total + dkMargin) / 2; d.va = (g.dk_total - dkMargin) / 2; }
    d.lv = liveFor(g);
    d.final = d.lv && d.lv.completed ? [d.lv.home_score, d.lv.away_score] : null;
    d.graded = {};
    (tracked[g.game_id] || []).forEach(p => { if (p.result) d.graded[p.bet] = p.result; });
    g._d = d;
    return d;
  }

  // ------------------------------------------------------------------ chrome
  function header() {
    const built = dt(S.built);
    const nBad = (S.checks || []).filter(c => !c[1]).length;
    document.getElementById("updated").innerHTML =
      `Updated ${esc(fmtStamp(built))} ` +
      (nBad ? `<a class="badge bad" href="#info">! ${nBad} check${nBad > 1 ? "s" : ""} failing</a>` :
        `<a class="badge" href="#info">✓ Checks pass</a>`) +
      (S.weeks && S.weeks[curKey] && S.weeks[curKey].demo ? ` <span class="badge bad">Synthetic demo data</span>` : "");
    const R = (S.tracker && S.tracker.records) || {};
    const W = S.weeks[curKey];
    const nFinal = W ? W.games.filter(g => { const l = liveFor(g); return l && l.completed; }).length : 0;
    const rec = k => { const r = (R[k] || {}).season; if (!r || !r.graded) return `<span class="dash">0-0</span>`;
      return `<span class="w">${r.w}</span>-<span class="l">${r.l}</span>${r.p ? `<span class="p">-${r.p}</span>` : ""}`; };
    const sub = k => { const r = (R[k] || {}).season; return r && r.graded ? `${sgn(r.units, 1)}u${fin(r.clv_avg) ? ` · CLV ${sgn(r.clv_avg, 1)}` : ""}` : "no graded picks yet"; };
    document.getElementById("kpis").innerHTML = `
      <div class="kpi"><div class="kl">Week ${W ? W.week : ""}</div><div class="kv">${nFinal}/${W ? W.games.length : 0}</div><div class="ks">games final</div></div>
      <div class="kpi"><div class="kl">Spread</div><div class="kv">${rec("spread")}</div><div class="ks">${sub("spread")}</div></div>
      <div class="kpi"><div class="kl">Totals</div><div class="kv">${rec("total")}</div><div class="ks">${sub("total")}</div></div>
      <div class="kpi"><div class="kl">Winners</div><div class="kv">${rec("winner")}</div><div class="ks">${sub("winner")}</div></div>
      <div class="kpi"><div class="kl">Bets</div><div class="kv">${rec("bets")}</div><div class="ks">${sub("bets")}</div></div>`;
  }

  const THEME_KEY = "nflmodel-theme";
  function theme() {
    const btn = document.getElementById("theme");
    let t = null; try { t = localStorage.getItem(THEME_KEY); } catch (e) { }
    if (t) document.documentElement.dataset.theme = t;
    const label = () => { const cur = document.documentElement.dataset.theme; btn.textContent = cur === "dark" ? "Dark" : cur === "light" ? "Light" : "Auto"; };
    label();
    btn.onclick = () => {
      const cur = document.documentElement.dataset.theme;
      const nxt = !cur ? "light" : cur === "light" ? "dark" : "";
      if (nxt) document.documentElement.dataset.theme = nxt; else delete document.documentElement.dataset.theme;
      try { nxt ? localStorage.setItem(THEME_KEY, nxt) : localStorage.removeItem(THEME_KEY); } catch (e) { }
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

  function lineChart(gid, g, kind) {
    const L = (S.lines || {})[gid];
    if (!L || !L.points || L.points.length < 1) return `<p class="note">Line history starts once the line watch has logged this game.</p>`;
    const pts = L.points.map(p => ({ t: +new Date(p[0]), v: kind === "total" ? p[2] : p[1] })).filter(p => fin(p.v));
    const open = kind === "total" ? L.open_total : L.open_spread;
    if (fin(open)) pts.unshift({ t: pts[0].t - 3600e3 * 12, v: open, open: true });
    const model = kind === "total" ? g.model_total : -g.model_margin;
    const now = Date.now(), ko = +new Date(g.kickoff_utc);
    pts.push({ t: Math.min(now, ko), v: pts[pts.length - 1].v });
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
    </svg><div class="legend"><span><i style="background:var(--vegas)"></i>DraftKings line (via ESPN)</span><span><i style="background:var(--model)"></i>Model line</span>${fin(open) ? `<span>Opened ${esc(lbl(open))}</span>` : ""}</div>`;
  }

  function booksTable(W, g) {
    const rows = (W.books || []).filter(b => b.game_id === g.game_id);
    if (!rows.length) return `<p class="note">No book prices this run.</p>`;
    rows.sort((x, y) => (x.book === "draftkings" ? -1 : y.book === "draftkings" ? 1 : x.book.localeCompare(y.book)));
    return `<div class="tablewrap"><table><thead><tr><th>Book</th><th class="num">${esc(g.home_team)} spread</th><th class="num">Price</th><th class="num">Total</th><th class="num">Over</th><th class="num">Under</th><th class="num">${esc(g.away_team)} ML</th><th class="num">${esc(g.home_team)} ML</th></tr></thead><tbody>` +
      rows.map(b => `<tr${b.book === "draftkings" ? ' class="hl"' : ""}><td>${esc(BOOKS[b.book] || b.book)}</td><td class="num">${hcap(b.home_spread)}</td><td class="num">${am(b.home_spread_price)}</td><td class="num">${fin(b.total) ? trim(b.total) : "–"}</td><td class="num">${am(b.over_price)}</td><td class="num">${am(b.under_price)}</td><td class="num">${am(b.away_ml)}</td><td class="num">${am(b.home_ml)}</td></tr>`).join("") +
      `</tbody></table></div>`;
  }

  function modelTable(W, g) {
    const d = derive(W, g), h = d.h, a = d.a;
    const dkSp = fin(d.dkMargin) ? favLine(h, a, d.dkMargin) : "–";
    return `<div class="tablewrap"><table class="mtable"><thead><tr><th></th><th>Spread</th><th>Total</th><th>Winner</th></tr></thead><tbody>
      <tr><td>Model</td><td class="m">${esc(favLine(h, a, g.model_margin))}</td><td class="m">${num(g.model_total)}</td><td class="m">${fin(g.p_home_win_model) ? esc((g.p_home_win_model >= .5 ? h : a) + " " + pct(Math.max(g.p_home_win_model, 1 - g.p_home_win_model))) : "–"}</td></tr>
      <tr><td>Fair (blend)</td><td>${esc(favLine(h, a, g.fair_margin))}</td><td>${num(g.fair_total)}</td><td>${fin(d.pHome) ? esc(d.winner + " " + pct(Math.max(d.pHome, 1 - d.pHome))) : "–"}</td></tr>
      <tr><td>DraftKings</td><td class="v">${esc(dkSp)}</td><td class="v">${fin(g.dk_total) ? trim(g.dk_total) : "–"}</td><td class="v">${fin(d.pHomeMkt) ? esc((d.pHomeMkt >= .5 ? h : a) + " " + pct(Math.max(d.pHomeMkt, 1 - d.pHomeMkt))) : "–"}</td></tr>
      <tr class="edge"><td>Pick</td><td>${d.sp ? esc(d.sp.bet) + (d.sp.is_play ? '<span class="chip">BET</span>' : "") + `<div class="small muted">${pct(d.pr(d.sp))} · edge ${sgn(d.spEdge)} pts</div>` : "–"}</td>
        <td>${d.tt ? esc(d.tt.bet) + (d.tt.is_play ? '<span class="chip">BET</span>' : "") + `<div class="small muted">${pct(d.pr(d.tt))} · edge ${sgn(d.ttEdge)} pts</div>` : "–"}</td>
        <td>${d.ml ? esc(d.ml.bet.replace(" to win", "")) + ` ${am(d.ml.price)}` + (d.ml.is_play ? '<span class="chip">BET</span>' : "") : "–"}</td></tr>
    </tbody></table></div>`;
  }

  // ------------------------------------------------------------------ Games
  let openGame = null, gameTab = "model";
  function renderGames() {
    const W = S.weeks[curKey];
    if (!W) { view.innerHTML = `<p class="empty">No weekly run yet.</p>`; return; }
    const games = W.games.slice().sort((x, y) => (x.kickoff_utc || "").localeCompare(y.kickoff_utc || ""));
    const card = g => {
      const d = derive(W, g), lv = d.lv;
      const hs = lv && lv.state !== "pre" ? lv.home_score : null, as = lv && lv.state !== "pre" ? lv.away_score : null;
      const status = !lv || lv.state === "pre" ? `<b>${esc(fmtDay(dt(g.kickoff_utc)))} ${esc(fmtTime(dt(g.kickoff_utc)))}</b>` :
        lv.completed ? `<b>Final</b>` : `<span class="live">${esc(lv.detail || "Live")}</span>`;
      const pk = (b, label) => { if (!b) return ""; const r = d.graded[b.bet]; return `<span class="pk${r ? " " + r : b.is_play ? " bet" : ""}">${esc(label || b.bet)}${r ? " · " + r : ""}</span>`; };
      const scoreCls = (mine, other) => mine != null && other != null && mine < other ? "score lose" : "score";
      return `<button class="gcard" type="button" data-g="${esc(g.game_id)}" aria-expanded="${openGame === g.game_id}">
        <div class="row">${team(g.away_team, ` <span class="rec">${recText(g.away_team)}</span>`)}${as != null ? `<span class="${scoreCls(as, hs)}">${as}</span>` : ""}</div>
        <div class="row">${team(g.home_team, ` <span class="rec">${recText(g.home_team)}</span>`)}${hs != null ? `<span class="${scoreCls(hs, as)}">${hs}</span>` : ""}</div>
        <div class="picks">${pk(d.sp)}${pk(d.tt)}${d.ml ? pk(d.ml, d.ml.bet.replace(" to win", " ML")) : ""}</div>
        <div class="foot">${status}<span class="muted">${esc((lv && lv.broadcast) || "")}</span></div></button>`;
    };
    let detail = "";
    if (openGame) {
      const g = games.find(x => x.game_id === openGame);
      if (g) {
        const d = derive(W, g);
        const tabs = [["model", "Model"], ["win", "Win chance"], ["line", "Line history"], ["books", "All books"], ["news", "Injuries and context"]];
        let body = "";
        if (gameTab === "model") body = modelTable(W, g);
        else if (gameTab === "win") body = `<div class="bars"><span class="lab">Fair</span>${bar("model", g.away_team, fin(d.pHome) ? 1 - d.pHome : NaN, g.home_team)}
          <span class="lab">Model</span>${bar("hist", g.away_team, fin(g.p_home_win_model) ? 1 - g.p_home_win_model : NaN, g.home_team)}
          <span class="lab">DK</span>${bar("vegas", g.away_team, fin(d.pHomeMkt) ? 1 - d.pHomeMkt : NaN, g.home_team)}</div>
          <p class="note">Fair = the blended line the picks use. Model = the model alone. DK = DraftKings' moneyline with the margin removed.</p>`;
        else if (gameTab === "line") body = `<div class="two"><div><h3>Spread</h3>${lineChart(g.game_id, g, "spread")}</div><div><h3>Total</h3>${lineChart(g.game_id, g, "total")}</div></div>`;
        else if (gameTab === "books") body = booksTable(W, g);
        else body = contextBlock(W, g);
        detail = `<div class="gdetail" id="gdetail">
          <div class="gd-head">${team(g.away_team, "", true)}<span class="at">at</span>${team(g.home_team, "", true)}
            ${d.lv && d.lv.state !== "pre" ? `<strong class="cond" style="font-size:20px">${d.lv.away_score}–${d.lv.home_score}</strong> <span class="${d.lv.completed ? "muted" : "live"}">${esc(d.lv.detail || "")}</span>` : ""}
            <button class="btn close" type="button" data-close>Close</button></div>
          <p class="gd-sub">${esc(fmtLong(dt(g.kickoff_utc)))} · ${esc(fmtTime(dt(g.kickoff_utc)))} ET${d.lv && d.lv.broadcast ? " · " + esc(d.lv.broadcast) : ""} · <a href="#breakdown/${esc(g.game_id)}">Full breakdown</a></p>
          <div class="subtabs">${tabs.map(([k, l]) => `<button type="button" data-gt="${k}" aria-pressed="${gameTab === k}">${l}</button>`).join("")}</div>${body}</div>`;
      }
    }
    view.innerHTML = detail + `<p class="section-label">Coming up · Week ${W.week}</p><div class="ggrid">${games.map(card).join("")}</div>`;
    view.querySelectorAll(".gcard").forEach(b => b.onclick = () => { openGame = openGame === b.dataset.g ? null : b.dataset.g; renderGames(); if (openGame) document.getElementById("gdetail").scrollIntoView({ block: "nearest" }); });
    view.querySelectorAll("[data-gt]").forEach(b => b.onclick = () => { gameTab = b.dataset.gt; renderGames(); });
    const c = view.querySelector("[data-close]"); if (c) c.onclick = () => { openGame = null; renderGames(); };
  }

  function contextBlock(W, g) {
    const miss = s => s ? esc(s) : '<span class="muted">No regular starters listed out</span>';
    const cont = (o, d) => fin(o) ? `${pct(o)} offense, ${pct(d)} defense` : "–";
    const wx = g.indoor ? "Indoors" : [fin(g.temp_used) ? Math.round(g.temp_used) + "°F" : null, fin(g.wind_used) ? "wind " + Math.round(g.wind_used) + " mph" : null, fin(g.precip) && g.precip > 0.01 ? "rain " + g.precip.toFixed(2) + " in" : null].filter(Boolean).join(", ") || "–";
    return `<div class="tablewrap"><table><tbody>
      <tr><td class="muted">Quarterbacks</td><td>${esc(g.a_qb_name_used || "–")} (${esc(g.away_team)}) vs ${esc(g.h_qb_name_used || "–")} (${esc(g.home_team)})</td></tr>
      <tr><td class="muted">${esc(g.away_team)} missing</td><td>${miss(g.a_miss_names)}</td></tr>
      <tr><td class="muted">${esc(g.home_team)} missing</td><td>${miss(g.h_miss_names)}</td></tr>
      <tr><td class="muted">Weather</td><td>${esc(wx)}</td></tr>
      <tr><td class="muted">Venue</td><td>${esc(g.stadium || "")}${g.roof ? " · " + esc(g.roof) : ""}${g.surface ? " · " + esc(g.surface) : ""}${g.location === "Neutral" ? " · neutral site" : ""}</td></tr>
      <tr><td class="muted">Rest</td><td>${esc(g.away_team)} ${fin(g.away_rest) ? g.away_rest + " days" : "–"}, ${esc(g.home_team)} ${fin(g.home_rest) ? g.home_rest + " days" : "–"}${fin(g.away_travel_kmi) ? ` · ${esc(g.away_team)} travel ${Math.round(g.away_travel_kmi * 1000).toLocaleString()} mi` : ""}</td></tr>
      <tr><td class="muted">Returning snaps</td><td>${esc(g.away_team)} ${cont(g.a_off_cont, g.a_def_cont)} · ${esc(g.home_team)} ${cont(g.h_off_cont, g.h_def_cont)}</td></tr>
      <tr><td class="muted">Coaches</td><td>${esc(g.away_coach || "–")} vs ${esc(g.home_coach || "–")}${g.referee ? " · referee " + esc(g.referee) : ""}</td></tr>
    </tbody></table></div><p class="note">Missing players are regular starters (by snap share) listed out or doubtful on the injury report (ESPN's same-day page over the league report), weighted by how much they play.</p>`;
  }

  // ------------------------------------------------------------------ Picks
  let picksWeek = null, rankMarket = "all";
  const teaserPrices = { 2: -120, 3: 160, 4: 260 };
  function renderPicks() {
    const key = picksWeek || curKey, W = S.weeks[key];
    if (!W) { view.innerHTML = `<p class="empty">No weekly run yet.</p>`; return; }
    const games = W.games.slice().sort((x, y) => (x.kickoff_utc || "").localeCompare(y.kickoff_utc || ""));
    const res = (d, b) => { const r = b && d.graded[b.bet]; return r ? `<span class="chip ${r}">${r}</span>` : ""; };
    const rows = games.map(g => {
      const d = derive(W, g);
      const cell = (b, p) => b ? `<strong>${esc(b.bet.replace(" to win", ""))}</strong>${b.is_play ? '<span class="chip">BET</span>' : ""}${res(d, b)}<div class="small muted">${pct(p)}</div>` : "–";
      const fscore = d.final ? `${d.final[1]}–${d.final[0]}` : "";
      return `<tr${[d.sp, d.tt, d.ml].some(b => b && b.is_play) ? ' class="hl"' : ""}>
        <td>${team(g.away_team)} <span class="muted">@</span> ${team(g.home_team)}<div class="small muted">${esc(fmtDay(dt(g.kickoff_utc)))} ${esc(fmtTime(dt(g.kickoff_utc)))}</div></td>
        <td>${cell(d.sp, d.sp && d.pr(d.sp))}</td><td>${cell(d.tt, d.tt && d.pr(d.tt))}</td>
        <td>${d.winner ? `<strong>${esc(d.winner)}</strong>${d.ml && d.ml.is_play ? '<span class="chip">BET</span>' : ""}${res(d, d.ml)}<div class="small muted">${pct(Math.max(d.pHome, 1 - d.pHome))}</div>` : "–"}</td>
        <td class="num">${esc(g.away_team)} ${num(d.ma)}<br>${esc(g.home_team)} ${num(d.mh)}</td>
        <td class="num">${fin(d.va) ? num(d.va) + "<br>" + num(d.vh) : "–"}</td>
        <td class="num">${esc(fscore)}</td></tr>`;
    }).join("");
    // bet ranking: every spread and total pick, sorted by chance of hitting
    const rank = [];
    games.forEach(g => { const d = derive(W, g);
      if (d.sp) rank.push({ g, d, b: d.sp, m: "Spread", edge: d.spEdge, hist: d.spHist, p: d.pr(d.sp) });
      if (d.tt) rank.push({ g, d, b: d.tt, m: "Total", edge: d.ttEdge, hist: d.ttHist, p: d.pr(d.tt) }); });
    const rsel = rank.filter(r => rankMarket === "all" || r.m === rankMarket).sort((x, y) => y.p - x.p);
    const rankRows = rsel.map((r, i) => `<tr${r.b.is_play ? ' class="hl"' : ""}><td class="num">${i + 1}</td><td><strong>${esc(r.b.bet)}</strong>${r.b.is_play ? '<span class="chip">BET</span>' : ""}${res(r.d, r.b)}</td>
      <td>${esc(r.g.away_team)} @ ${esc(r.g.home_team)}</td><td class="muted">${esc(fmtDay(dt(r.g.kickoff_utc)))} ${esc(fmtTime(dt(r.g.kickoff_utc)))}</td><td>${r.m}</td>
      <td class="num">${am(r.b.price)}</td><td class="num"><strong>${pct(r.p, 1)}</strong>${r.b.p_push > 0.005 ? `<div class="small muted">+${pct(r.b.p_push)} push</div>` : ""}</td>
      <td class="num">${pct(r.hist)}</td><td class="num">${sgn(r.edge)}</td><td class="num">${pct(1 / dec(r.b.price), 1)}</td>
      <td class="num ${r.b.ev > 0 ? "w" : "muted"}">${sgn(100 * r.b.ev, 1)}%</td><td class="small">${esc(r.b.timing || "")}</td></tr>`).join("");
    view.innerHTML = `
      <div class="toolbar noprint"><select id="wk" aria-label="Week">${weekKeys.map(k => `<option value="${k}"${k === key ? " selected" : ""}>Week ${+k.split("-")[1]}, ${k.split("-")[0]}</option>`).join("")}</select>
        <button class="btn primary" type="button" id="pdf">Download PDF</button><span class="small muted">Run ${esc(fmtStamp(dt(W.generated)))}</span></div>
      <div class="panel"><div class="tablewrap"><table><thead><tr><th>Game</th><th>Spread</th><th>Total</th><th>Winner</th><th class="num">Model score</th><th class="num">Vegas score</th><th class="num">Final</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="note">Each pick is the side of DraftKings' number with the higher chance to hit on the fair line (the model blended with the sharp-book consensus, weighted by backtest). BET = expected value of at least ${pct(W.min_ev)} at DraftKings' price.</p></div>
      <div class="panel"><div class="toolbar" style="justify-content:space-between"><h2>Bet ranking: spreads and totals by chance of hitting</h2>
        <div class="seg noprint" role="group" aria-label="Market">${["all", "Spread", "Total"].map(m => `<button type="button" data-rm="${m}" aria-pressed="${rankMarket === m}">${m === "all" ? "All" : m + "s"}</button>`).join("")}</div></div>
        <div class="tablewrap"><table><thead><tr><th class="num">#</th><th>Pick</th><th>Game</th><th>Kickoff</th><th>Market</th><th class="num">DK price</th><th class="num">Chance</th><th class="num">History</th><th class="num">Edge pts</th><th class="num">Break-even</th><th class="num">EV</th><th>When</th></tr></thead><tbody>${rankRows}</tbody></table></div>
        <p class="note">Chance: fair-line probability of winning (pushes excluded). History: how often picks with this much model disagreement won in the ${esc((S.backtest && S.backtest.overall && S.backtest.overall.seasons) || "")} backtest. Edge pts: the model's own number minus DraftKings', toward the pick; negative means the model alone leans the other way and the pick follows the market.</p></div>
      ${teaserPanel(W, games)}`;
    view.querySelector("#wk").onchange = e => { picksWeek = e.target.value; renderPicks(); };
    view.querySelector("#pdf").onclick = () => window.print();
    view.querySelectorAll("[data-rm]").forEach(b => b.onclick = () => { rankMarket = b.dataset.rm; renderPicks(); });
    wireTeaser(W, games);
  }

  function teaserLegs(games) {
    const legs = [];
    games.forEach(g => { const t = g.tease || {};
      if (t.home) legs.push({ gid: g.game_id, g, label: `${g.home_team} ${hcap(t.home.line)}`, p: t.home.p, m: "spread" });
      if (t.away) legs.push({ gid: g.game_id, g, label: `${g.away_team} ${hcap(t.away.line)}`, p: t.away.p, m: "spread" });
      if (t.over) legs.push({ gid: g.game_id, g, label: `Over ${trim(t.over.line)}`, p: t.over.p, m: "total" });
      if (t.under) legs.push({ gid: g.game_id, g, label: `Under ${trim(t.under.line)}`, p: t.under.p, m: "total" }); });
    return legs.sort((x, y) => y.p - x.p);
  }
  let teaserPicked = new Set();
  function teaserPanel(W, games) {
    const legs = teaserLegs(games);
    if (!legs.length) return "";
    const best = n => { const out = [], used = new Set(); for (const l of legs) { if (used.has(l.gid)) continue; out.push(l); used.add(l.gid); if (out.length === n) break; } return out; };
    const card = n => { const b = best(n); if (b.length < n) return ""; const p = b.reduce((a, l) => a * l.p, 1), price = teaserPrices[n];
      return `<div class="bd-card"><h3>Best ${n}-leg</h3><div><strong>${b.map(l => esc(l.label)).join(" · ")}</strong></div>
        <div class="small muted">${pct(p)} to hit · fair ${am(toAm(p))} · at ${am(price)}: <span class="${p * dec(price) - 1 > 0 ? "w" : "l"}">${sgn(100 * (p * dec(price) - 1), 1)}% EV</span></div></div>`; };
    return `<div class="panel" id="teaser"><h2>6-point teasers</h2>
      <p class="lede">Each leg moves DraftKings' spread or total 6 points your way. Probabilities come from the same key-number distributions as the picks, so legs that cross 3 and 7 rank higher. Legs are treated as independent. Teaser prices vary: enter DraftKings' current price.</p>
      <div class="toolbar noprint">${[2, 3, 4].map(n => `<label class="small">${n} legs <input type="number" step="5" data-tp="${n}" value="${teaserPrices[n]}" style="width:78px"></label>`).join("")}</div>
      <div class="bd-grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr))">${card(2)}${card(3)}${card(4)}</div>
      <div id="teaser-mine" class="note"></div>
      <div class="tablewrap" style="margin-top:8px"><table><thead><tr><th></th><th>Teased line</th><th>Game</th><th>Kickoff</th><th class="num">Chance</th></tr></thead><tbody>
      ${legs.slice(0, 40).map((l, i) => `<tr><td><input type="checkbox" data-leg="${i}" aria-label="Add ${esc(l.label)}"${teaserPicked.has(l.label + l.gid) ? " checked" : ""}></td><td><strong>${esc(l.label)}</strong></td><td>${esc(l.g.away_team)} @ ${esc(l.g.home_team)}</td><td class="muted">${esc(fmtDay(dt(l.g.kickoff_utc)))} ${esc(fmtTime(dt(l.g.kickoff_utc)))}</td><td class="num">${pct(l.p)}</td></tr>`).join("")}
      </tbody></table></div></div>`;
  }
  function wireTeaser(W, games) {
    const legs = teaserLegs(games), box = view.querySelector("#teaser-mine");
    if (!box) return;
    const upd = () => {
      const chosen = legs.filter(l => teaserPicked.has(l.label + l.gid)), n = chosen.length;
      if (n < 2) { box.textContent = "Tick two to four legs to price your own teaser."; return; }
      const dup = new Set(chosen.map(l => l.gid)).size < n;
      const p = chosen.reduce((a, l) => a * l.p, 1), price = teaserPrices[Math.min(n, 4)];
      box.innerHTML = `Your ${n}-leg teaser: <strong>${pct(p)}</strong> to hit, fair ${am(toAm(p))}` +
        (n <= 4 ? `, at ${am(price)}: <strong class="${p * dec(price) - 1 > 0 ? "w" : "l"}">${sgn(100 * (p * dec(price) - 1), 1)}% EV</strong>` : " (enter a price for more than 4 legs in the app)") +
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
    const chips = games.map(x => { const dx = derive(W, x), bet = [dx.sp, dx.tt, dx.ml].some(b => b && b.is_play);
      return `<button type="button" data-bd="${esc(x.game_id)}" class="${bet ? "bet" : ""}" aria-pressed="${x.game_id === g.game_id}">${esc(x.away_team)} @ ${esc(x.home_team)}</button>`; }).join("");
    const wx = g.indoor ? "Indoors" : [fin(g.temp_used) ? Math.round(g.temp_used) + "°F" : null, fin(g.wind_used) ? "wind " + Math.round(g.wind_used) + " mph" : null].filter(Boolean).join(", ");
    const edgeBox = (b, e) => b ? `<div class="edgebox${b.is_play ? "" : " none"}"><span class="el">${b.is_play ? "BET" : "PICK"}</span><span>${esc(b.bet)} ${am(b.price)}</span><span class="small">${sgn(100 * b.ev, 1)}% EV · model ${sgn(e)} pts</span></div>` : `<div class="edgebox none">No DraftKings price</div>`;
    const spCard = `<div class="bd-card"><h3>Spread</h3><dl class="kv"><dt>Model</dt><dd class="m">${esc(favLine(h, a, g.model_margin))}</dd><dt>Fair</dt><dd>${esc(favLine(h, a, g.fair_margin))}</dd><dt>DK</dt><dd class="v">${fin(d.dkMargin) ? esc(favLine(h, a, d.dkMargin)) : "–"}</dd></dl>
      ${edgeBox(d.sp, d.spEdge)}
      ${d.sp ? `<div class="bars"><span class="lab">Fair</span>${bar("model", d.sp.bet, d.pr(d.sp), "other side")}<span class="lab">History</span>${bar("hist", d.sp.bet, d.spHist, "other side")}<span class="lab">DK</span>${bar("vegas", d.sp.bet, d.spVegas, "other side")}</div>` : ""}
      <div style="margin-top:10px">${lineChart(g.game_id, g, "spread")}</div></div>`;
    const ttCard = `<div class="bd-card"><h3>Total</h3><dl class="kv"><dt>Model</dt><dd class="m">${num(g.model_total)}</dd><dt>Fair</dt><dd>${num(g.fair_total)}</dd><dt>DK</dt><dd class="v">${fin(g.dk_total) ? trim(g.dk_total) : "–"}</dd></dl>
      ${edgeBox(d.tt, d.ttEdge)}
      ${d.tt ? `<div class="bars"><span class="lab">Fair</span>${bar("model", d.tt.bet, d.pr(d.tt), d.ttOver ? "Under" : "Over")}<span class="lab">History</span>${bar("hist", d.tt.bet, d.ttHist, d.ttOver ? "Under" : "Over")}<span class="lab">DK</span>${bar("vegas", d.tt.bet, d.ttVegas, d.ttOver ? "Under" : "Over")}</div>` : ""}
      <div style="margin-top:10px">${lineChart(g.game_id, g, "total")}</div></div>`;
    const ptCard = `<div class="bd-card"><h3>Points</h3><div class="tablewrap"><table><thead><tr><th></th><th class="num">${esc(a)}</th><th class="num">${esc(h)}</th></tr></thead><tbody>
      <tr><td class="muted">Model</td><td class="num" style="color:var(--model)">${num(d.ma)}</td><td class="num" style="color:var(--model)">${num(d.mh)}</td></tr>
      <tr><td class="muted">DraftKings</td><td class="num" style="color:var(--vegas)">${num(d.va)}</td><td class="num" style="color:var(--vegas)">${num(d.vh)}</td></tr>
      ${d.lv && d.lv.state !== "pre" ? `<tr><td class="muted">${d.lv.completed ? "Final" : "Now"}</td><td class="num"><strong>${d.lv.away_score}</strong></td><td class="num"><strong>${d.lv.home_score}</strong></td></tr>` : ""}</tbody></table></div></div>`;
    const winCard = `<div class="bd-card"><h3>Win</h3>${d.ml ? edgeBox(d.ml, NaN).replace(/ · model –? ?pts/, "") : ""}
      <div class="bars"><span class="lab">Fair</span>${bar("model", a, fin(d.pHome) ? 1 - d.pHome : NaN, h)}<span class="lab">Model</span>${bar("hist", a, fin(g.p_home_win_model) ? 1 - g.p_home_win_model : NaN, h)}<span class="lab">DK</span>${bar("vegas", a, fin(d.pHomeMkt) ? 1 - d.pHomeMkt : NaN, h)}</div></div>`;
    const h2h = ((S.schedule || {}).h2h || {})[g.game_id] || [];
    const h2hRows = h2h.map(m => { const cover = fin(m.result) && fin(m.spread_line) ? m.result - m.spread_line : NaN;
      const atsTeam = !fin(cover) ? "–" : Math.abs(cover) < 1e-9 ? "Push" : (cover > 0 ? m.home_team : m.away_team) + " covered";
      return `<tr><td>${m.season} W${m.week}</td><td>${esc(m.away_team)} ${m.away_score} @ ${esc(m.home_team)} ${m.home_score}</td><td class="num">${fin(m.spread_line) ? esc(favLine(m.home_team, m.away_team, m.spread_line)) : "–"}</td><td>${esc(atsTeam)}</td><td class="num">${fin(m.total_line) ? trim(m.total_line) + (m.total > m.total_line ? " (O)" : m.total < m.total_line ? " (U)" : " (P)") : "–"}</td></tr>`; }).join("");
    view.innerHTML = `<h2 class="cond" style="margin:4px 0 8px;font-size:20px">Week ${W.week}, ${W.season}</h2><div class="chips" role="group" aria-label="Game">${chips}</div>
      <article class="panel"><div class="gd-head">${team(a, "", true)}<span class="at">@</span>${team(h, "", true)}<span class="muted small">${esc(fmtLong(dt(g.kickoff_utc)))} · ${esc(fmtTime(dt(g.kickoff_utc)))} ET · ${esc(g.stadium || "")}${wx ? " · " + esc(wx) : ""}</span></div>
      <div class="bd-grid" style="margin-top:12px">${spCard}${ttCard}${ptCard}${winCard}</div>
      <details class="fold" open><summary>Score projection</summary>${contribBlock(g)}</details>
      <details class="fold"><summary>Injury report and context</summary>${contextBlock(W, g)}</details>
      <details class="fold"><summary>Matchup history</summary>${h2hRows ? `<div class="tablewrap"><table><thead><tr><th>Game</th><th>Score</th><th class="num">Closing spread</th><th>Against the spread</th><th class="num">Total</th></tr></thead><tbody>${h2hRows}</tbody></table></div>` : `<p class="note">No meetings since ${esc(String((S.schedule || {}).season - 14))}.</p>`}</details>
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
    return `<p class="note" style="margin:0 0 10px">How each factor group moves the model's number, in points (the linear part of the model; ${g.home_team} margin is positive when ${g.home_team} is better). Factor groups that did not help out of sample were left out by the backtest.</p>
      <div class="two">${block(g.contrib_margin, `${esc(g.home_team)} margin`, "margin")}${block(g.contrib_total, "Total points", "total")}</div>`;
  }

  // ------------------------------------------------------------------ Futures
  let futSort = "p_sb", futGroup = "all";
  function renderFutures() {
    const sim = S.season_sim;
    if (!sim) { view.innerHTML = `<p class="empty">The season simulation runs with the weekly model.</p>`; return; }
    let teams = sim.teams.slice();
    teams.sort((x, y) => (y[futSort] || 0) - (x[futSort] || 0));
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
      <p class="note">Each season plays out with a random rating shock per team (sd ${sim.rating_sd} pts) plus game noise (sd ${sim.game_sd}), home field ${num(sim.hfa)} pts. Seeding: division winners 1-4, then three wild cards; ties broken by point differential (the league's tiebreakers are more involved). Fair odds have no bookmaker margin; compare with DraftKings' futures before betting any.</p></div>`;
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
    const rows = (sim ? sim.teams.slice().sort((x, y) => y.rating - x.rating) : power.map(p => ({ team: p.team, rating: p.net_pts }))).map((t, i) => {
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
      const pk = {}; ((S.tracker || {}).picks || []).forEach(p => { if (p.market === "spread" && (p.matchup.endsWith(T) || p.matchup.startsWith(T + " "))) pk[p.game_id] = p; });
      const grow = gs.map(g => {
        const home = g.home_team === T, opp = home ? g.away_team : g.home_team;
        const lv = liveFor(g); let hs = g.home_score, as = g.away_score;
        if (hs == null && lv && lv.completed) { hs = lv.home_score; as = lv.away_score; }
        const my = home ? hs : as, their = home ? as : hs;
        const line = fin(g.spread_line) ? (home ? -g.spread_line : g.spread_line) : NaN;
        const ats = my != null && fin(line) ? (my - their + line > 0 ? "W" : my - their + line < 0 ? "L" : "P") : "";
        const p = pk[g.game_id];
        return `<tr><td>W${g.week}</td><td>${home ? "vs" : "@"} ${team(opp)}</td><td class="num">${my != null ? `<strong class="${my > their ? "w" : my < their ? "l" : ""}">${my > their ? "W" : my < their ? "L" : "T"}</strong> ${my}–${their}` : esc(g.gameday ? new Date(g.gameday + "T17:00:00Z").toLocaleDateString("en-US", { ...ET, weekday: "short", month: "short", day: "numeric" }) : "")}</td>
          <td class="num">${fin(line) ? esc(T + " " + hcap(line)) : "–"}</td><td>${ats ? `<span class="chip ${ats}">${ats}</span>` : ""}</td><td>${p ? esc(p.bet) + (p.result ? ` <span class="chip ${p.result}">${p.result}</span>` : "") : ""}</td></tr>`;
      }).join("");
      const st = simBy[T];
      detail = `<div class="panel" id="teamdetail"><div class="gd-head">${team(T, "", true)}<h2 style="margin:0">${esc(NAMES[T] || T)}</h2><span class="rec">${recText(T)}</span><button class="btn close" type="button" data-tclose>Close</button></div>
        ${st ? `<p class="gd-sub">Projected ${num(st.wins_mean)} wins · playoffs ${pct(st.p_playoffs)} · division ${pct(st.p_div)} · Super Bowl ${pct(st.p_sb, 1)}</p>` : ""}
        <div class="tablewrap"><table><thead><tr><th>Week</th><th>Opponent</th><th class="num">Result</th><th class="num">Closing line</th><th>ATS</th><th>Model pick</th></tr></thead><tbody>${grow}</tbody></table></div></div>`;
    }
    view.innerHTML = detail + `<div class="panel"><h2>Power ratings</h2><p class="lede">Points per game better than an average team on a neutral field. Click a team for its schedule and results.</p>
      <div class="tablewrap"><table><thead><tr><th class="num">#</th><th>Team</th><th class="num">Rating</th><th class="num">Market</th><th class="num">Model</th><th class="num">Offense</th><th class="num">Defense</th><th>Projected QB</th><th class="num">Returning snaps</th><th>This week</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="note">Rating = market rating blended with the model's by the backtest weight (used for the season simulation). Market = rating implied by closing spreads, recent weeks weighted most. Model, Offense, Defense = the model's opponent-adjusted points ratings (defense positive = allows fewer). Returning snaps = share of last season's snaps by players still on the roster.</p></div>`;
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

  // ------------------------------------------------------------------ Backtest
  function renderBacktest() {
    const B = S.backtest;
    if (!B || !B.available) { view.innerHTML = `<p class="empty">Run optimize.py to create the backtest.</p>`; return; }
    const o = B.overall, c = B.calibration || {};
    const cum = B.cum_units || [];
    let chart = "";
    if (cum.length > 1) {
      const W_ = 700, H_ = 180, pl = 40, pr = 10, pt = 10, pb = 22, vals = cum.map(x => x[1]);
      const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
      const x = i => pl + (W_ - pl - pr) * i / (cum.length - 1), y = v => pt + (H_ - pt - pb) * (hi - v) / Math.max(hi - lo, 1);
      const seasons = []; cum.forEach((p, i) => { const s = p[0].slice(0, 4); if (!seasons.length || seasons[seasons.length - 1][0] !== s) seasons.push([s, i]); });
      chart = `<svg class="chart" viewBox="0 0 ${W_} ${H_}" role="img" aria-label="Cumulative units">
        <line x1="${pl}" x2="${W_ - pr}" y1="${y(0)}" y2="${y(0)}" stroke="var(--line)"/>
        ${seasons.map(([s, i]) => `<line x1="${x(i)}" x2="${x(i)}" y1="${pt}" y2="${H_ - pb}" stroke="var(--line2)"/><text x="${x(i) + 3}" y="${H_ - 6}">${s}</text>`).join("")}
        <polyline fill="none" stroke="var(--accent)" stroke-width="2" points="${cum.map((p, i) => `${x(i)},${y(p[1])}`).join(" ")}"/>
        <text x="${pl - 4}" y="${y(hi) + 4}" text-anchor="end">${sgn(hi, 0)}</text><text x="${pl - 4}" y="${y(lo) + 4}" text-anchor="end">${sgn(lo, 0)}</text></svg>
        <p class="note">Flat 1 unit at −110 on every game where the model alone disagreed with the closing spread by 3+ points: ${cum.length} bets, ${sgn(vals[vals.length - 1], 1)} units. Closing lines are harder to beat than the Tuesday lines you can actually bet, so treat this as an upper bound.</p>`;
    }
    const hb = (h, k) => (h[k] ? h[k].bins : []).map(b => `<tr><td>${b.lo}${b.hi ? "–" + b.hi : "+"} pts</td><td class="num">${b.n}</td><td class="num">${pct(b.hit, 1)}</td><td class="num">${pct(b.fit, 1)}</td></tr>`).join("");
    view.innerHTML = `<div class="kpis" style="grid-template-columns:repeat(4,minmax(0,1fr));margin-top:0">
      <div class="kpi"><div class="kl">Spread miss, model</div><div class="kv">${num(o.spread_model, 2)}</div><div class="ks">closing line ${num(o.spread_market, 2)}</div></div>
      <div class="kpi"><div class="kl">Total miss, model</div><div class="kv">${num(o.total_model, 2)}</div><div class="ks">closing line ${num(o.total_market, 2)}</div></div>
      <div class="kpi"><div class="kl">Model weight</div><div class="kv">${pct(c.model_weight_spread)} / ${pct(c.model_weight_total)}</div><div class="ks">spread / total, rest is the market</div></div>
      <div class="kpi"><div class="kl">Games</div><div class="kv">${Number(o.games).toLocaleString()}</div><div class="ks">walk-forward, ${esc(o.seasons)}</div></div></div>
      <div class="two"><div class="panel"><h2>Average miss by season</h2><p class="lede">Points between the line and the final margin (or total). Every prediction used only data from before that week.</p>
        <div class="tablewrap"><table><thead><tr><th>Season</th><th class="num">Games</th><th class="num">Spread: model</th><th class="num">close</th><th class="num">Total: model</th><th class="num">close</th></tr></thead><tbody>
        ${B.by_season.map(s => `<tr><td>${s.season}</td><td class="num">${s.games}</td><td class="num${s.spread_model < s.spread_market ? " w" : ""}">${num(s.spread_model, 2)}</td><td class="num">${num(s.spread_market, 2)}</td><td class="num${s.total_model < s.total_market ? " w" : ""}">${num(s.total_model, 2)}</td><td class="num">${num(s.total_market, 2)}</td></tr>`).join("")}</tbody></table></div></div>
      <div class="panel"><h2>When the model disagrees</h2><p class="lede">How often the model's side won against the closing line, by size of disagreement (pushes excluded). Break-even at −110 is 52.4%.</p>
        <div class="tablewrap"><table><thead><tr><th>Disagreement</th><th class="num">Spread n</th><th class="num">ATS</th><th class="num">Total n</th><th class="num">O/U</th></tr></thead><tbody>
        ${B.thresholds.map(t => `<tr><td>${t.edge}+ pts</td><td class="num">${t.ats_n}</td><td class="num${t.ats_pct > 0.524 ? " w" : ""}">${pct(t.ats_pct, 1)}</td><td class="num">${t.ou_n}</td><td class="num${t.ou_pct > 0.524 ? " w" : ""}">${pct(t.ou_pct, 1)}</td></tr>`).join("")}</tbody></table></div></div></div>
      <div class="panel"><h2>Flat-bet record at 3+ points of disagreement</h2>${chart || '<p class="note">Not enough games.</p>'}</div>
      <div class="two"><div class="panel"><h2>History column: spreads</h2><p class="lede">Hit rate by disagreement and the smooth curve the Picks page uses.</p><div class="tablewrap"><table><thead><tr><th>Disagreement</th><th class="num">Games</th><th class="num">Won</th><th class="num">Curve</th></tr></thead><tbody>${hb(B.history, "spread")}</tbody></table></div></div>
      <div class="panel"><h2>History column: totals</h2><p class="lede">Same for totals.</p><div class="tablewrap"><table><thead><tr><th>Disagreement</th><th class="num">Games</th><th class="num">Won</th><th class="num">Curve</th></tr></thead><tbody>${hb(B.history, "total")}</tbody></table></div></div></div>
      <div class="panel"><h2>What the backtest decided</h2><p class="lede">Factor groups left out because they made out-of-sample predictions worse: spreads ${esc((c.drop_groups_margin || []).join(", ") || "none")}; totals ${esc((c.drop_groups_total || []).join(", ") || "none")}. Gradient boosting share: spreads ${pct(c.gbm_weight_margin)}, totals ${pct(c.gbm_weight_total)}.</p></div>`;
  }

  // ------------------------------------------------------------------ Bets
  let betsFilter = "bets";
  function renderBets() {
    const T = S.tracker || {}, R = T.records || {};
    const all = (T.picks || []).slice().sort((x, y) => (y.run_at || "").localeCompare(x.run_at || ""));
    const list = betsFilter === "bets" ? all.filter(p => p.is_play) : all;
    const recCard = (k, l) => { const r = (R[k] || {}).season || {};
      return `<div class="kpi"><div class="kl">${l}</div><div class="kv">${r.graded ? `<span class="w">${r.w}</span>-<span class="l">${r.l}</span>${r.p ? "-" + r.p : ""}` : '<span class="dash">0-0</span>'}</div>
        <div class="ks">${r.graded ? `${sgn(r.units, 2)} units` : "none graded"}${fin(r.clv_avg) ? ` · CLV ${sgn(r.clv_avg, 2)} pts, ${pct(r.clv_pos)} beat the close` : ""}</div></div>`; };
    const mine = S.my_bets || [];
    const myTot = mine.reduce((s, b) => s + (b.profit || 0), 0);
    view.innerHTML = `<div class="kpis" style="grid-template-columns:repeat(4,minmax(0,1fr));margin-top:0">${recCard("bets", "Flagged bets")}${recCard("spread", "All spread picks")}${recCard("total", "All total picks")}${recCard("winner", "Winners")}</div>
      <div class="panel"><div class="toolbar" style="justify-content:space-between"><div><h2>Pick tracker</h2><p class="lede">Every pick as the page showed it at the last run before kickoff, graded at that DraftKings price. CLV = points better than DraftKings' closing line (the best test of whether an edge is real).</p></div>
        <div class="seg" role="group" aria-label="Filter">${[["bets", "Flagged bets"], ["all", "All picks"]].map(([k, l]) => `<button type="button" data-bf="${k}" aria-pressed="${betsFilter === k}">${l}</button>`).join("")}</div></div>
      ${list.length ? `<div class="tablewrap"><table><thead><tr><th>Week</th><th>Game</th><th>Pick</th><th class="num">Price</th><th class="num">Chance</th><th class="num">EV</th><th class="num">CLV</th><th class="num">Result</th><th class="num">Units</th></tr></thead><tbody>
      ${list.map(p => `<tr${p.is_play ? ' class="hl"' : ""}><td>${p.week}</td><td>${esc(p.matchup)}</td><td><strong>${esc(p.bet)}</strong>${p.is_play ? '<span class="chip">BET</span>' : ""}</td><td class="num">${am(p.price)}</td><td class="num">${pct(p.p_win / Math.max(p.p_win + (1 - p.p_win - p.p_push), 1e-9))}</td><td class="num">${sgn(100 * p.ev, 1)}%</td><td class="num">${fin(p.clv) ? sgn(p.clv) : "–"}</td><td class="num">${p.result ? `<span class="chip ${p.result}">${p.result}</span>` : '<span class="muted">pending</span>'}</td><td class="num">${fin(p.units) ? sgn(p.units, 2) : ""}</td></tr>`).join("")}</tbody></table></div>` : `<p class="empty">Picks are logged from the first scheduled weekly run and graded after each game.</p>`}</div>
      <div class="panel"><h2>My bets</h2><p class="lede">From overrides/my_bets.csv in the repo (add a row per bet you place at DraftKings).</p>
      ${mine.length ? `<div class="tablewrap"><table><thead><tr><th>Week</th><th>Game</th><th>Bet</th><th class="num">Price</th><th class="num">Stake</th><th class="num">Result</th><th class="num">Profit</th></tr></thead><tbody>
      ${mine.map(b => `<tr><td>${b.week}</td><td>${esc(b.matchup)}</td><td>${esc(b.market)} ${esc(b.side)} ${b.market === "moneyline" ? "" : esc(trim(b.line))}</td><td class="num">${am(b.price)}</td><td class="num">$${num(b.stake, 0)}</td><td class="num">${b.result ? `<span class="chip ${b.result}">${b.result}</span>` : "pending"}</td><td class="num">${fin(b.profit) ? (b.profit >= 0 ? "+$" : "−$") + Math.abs(b.profit).toFixed(2) : ""}</td></tr>`).join("")}</tbody></table></div><p class="note">Total: ${myTot >= 0 ? "+$" : "−$"}${Math.abs(myTot).toFixed(2)}</p>` : `<p class="empty">No bets logged yet.</p>`}</div>`;
    view.querySelectorAll("[data-bf]").forEach(b => b.onclick = () => { betsFilter = b.dataset.bf; renderBets(); });
  }

  // ------------------------------------------------------------------ Info
  function renderInfo() {
    const W = S.weeks[curKey] || {};
    view.innerHTML = `<div class="panel"><h2>Checks</h2><p class="lede">Run on every site build. ${(S.checks || []).filter(c => c[1]).length} of ${(S.checks || []).length} pass.</p>
      <ul class="checks">${(S.checks || []).map(c => `<li><span class="${c[1] ? "ok" : "bad"}">${c[1] ? "✓" : "✗"}</span>${esc(c[0])}${c[2] ? ` <span class="muted small">${esc(c[2])}</span>` : ""}</li>`).join("")}</ul></div>
      <div class="panel prose"><h2>How the model works</h2>
      <p>Every week the model sets its own spread and total for each game from about 140 inputs: opponent-adjusted team ratings from play-by-play (weighted EPA, early downs, big plays, points per drive, pass and run efficiency), the projected starting quarterback, missing starters by position, offseason roster turnover, rest, travel, time zones, kickoff time, weather forecasts, surface, altitude, coaching, officials and more. Each factor group has to earn its place in a walk-forward backtest; groups that make out-of-sample predictions worse are dropped.</p>
      <p>The model's number is then blended with the sharp-book consensus (Pinnacle and other low-margin books) using the weight the backtest found (${pct(W.weights && W.weights.spread)} model for spreads, ${pct(W.weights && W.weights.total)} for totals). That fair line is turned into a probability for every DraftKings price, using how often NFL games land on each margin (3 and 7 most of all). A pick is the likelier side; a <strong>BET</strong> is a pick whose expected value at DraftKings' price is at least ${pct(W.min_ev)}.</p>
      <h3>Schedule</h3><p>The model runs Tuesday morning, Thursday and Friday afternoon, twice on Sunday before kickoff and Monday afternoon. The line watch logs DraftKings' line from ESPN and live scores every 20 minutes. Calibration re-runs every Tuesday after Monday night.</p>
      <h3>Sources</h3><p>Play-by-play, schedules, rosters, snap counts and injuries: nflverse. Same-day injury reports, scores and the line history: ESPN's public scoreboard and injury feeds. DraftKings and other sportsbook prices: The Odds API. Weather: Open-Meteo. Team logos: ESPN.</p>
      <h3>Read this before betting</h3><p>NFL closing lines miss the final margin by about 10 points on average, and the model does not beat them on its own; it adds a small amount when blended. Break-even at −110 is 52.4%. Judge the model by closing-line value over a full season, not by a weekend's record. For information only, not financial advice. If betting stops being fun, call 1-800-GAMBLER.</p>
      ${W.notes && W.notes.length ? `<h3>Notes from the latest run</h3><ul>${W.notes.map(n => `<li class="small">${esc(n)}</li>`).join("")}</ul>` : ""}</div>`;
  }

  // ------------------------------------------------------------------ router
  const ROUTES = { games: renderGames, picks: renderPicks, breakdown: renderBreakdown, futures: renderFutures, teams: renderTeams,
    players: renderPlayers, backtest: renderBacktest, bets: renderBets, info: renderInfo };
  function route() {
    const [name, arg] = (location.hash.replace(/^#/, "") || "games").split("/");
    const r = ROUTES[name] ? name : "games";
    document.querySelectorAll("nav.tabs a").forEach(a => a.getAttribute("href") === "#" + r ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
    ROUTES[r](arg ? decodeURIComponent(arg) : undefined);
    if (!arg) window.scrollTo({ top: 0 });
  }
  theme();
  if (!S.weeks || !weekKeys.length) { view.innerHTML = `<p class="empty">No data yet. The site fills in after the first weekly run.</p>`; return; }
  header();
  window.addEventListener("hashchange", route);
  route();
})();
