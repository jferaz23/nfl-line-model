/* Layout helpers: run after app.js (main site = Spotlight; previews use the others). Read window.SITE; never change app.js.
   data-layout on <html> picks the extras: "ticker" (game strip), "spotlight" (pick of the week hero), "bento" (route flag). */
(function () {
  const S = window.SITE || {}, root = document.documentElement, mode = root.dataset.layout || "";
  const keys = Object.keys(S.weeks || {}).sort(), W = S.weeks && S.weeks[keys[keys.length - 1]];
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const logo = t => `https://a.espncdn.com/i/teamlogos/nfl/500/${({ LA: "lar", WAS: "wsh" }[t] || String(t).toLowerCase())}.png`;
  const am = p => (p > 0 ? "+" : "") + Math.round(p);
  const dt = s => new Date(s);
  const day = d => d.toLocaleDateString("en-US", { weekday: "short", timeZone: "America/New_York" });
  const time = d => d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" });
  const live = {};
  ((S.live || {}).games || []).forEach(x => { live[`${x.home_team}-${x.away_team}`] = x; });
  const setRoute = () => { root.dataset.route = (location.hash.replace(/^#/, "").split("/")[0] || "games"); };
  window.addEventListener("hashchange", setRoute); setRoute();
  if (!W) return;
  const picks = W.picks || [];
  const pickFor = gid => picks.filter(p => p.game_id === gid && p.highlight && p.market !== "winner").sort((a, b) => (b.top ? 1 : 0) - (a.top ? 1 : 0))[0];
  const wind = gid => (W.wind_unders || []).find(x => x.game_id === gid && x.highlight);

  if (mode === "ticker") {
    const games = W.games.slice().sort((a, b) => (a.kickoff_utc || "").localeCompare(b.kickoff_utc || ""));
    const items = games.map(g => {
      const lv = live[`${g.home_team}-${g.away_team}`], started = lv && lv.state !== "pre";
      const p = pickFor(g.game_id), w = wind(g.game_id);
      const status = !started ? `${day(dt(g.kickoff_utc))} ${time(dt(g.kickoff_utc))}` : lv.completed ? "Final" : (lv.detail || "Live");
      const row = (t, sc) => `<div class="tk-row"><img src="${logo(t)}" alt="" loading="lazy"><b>${esc(t)}</b>${started ? `<span class="tk-sc">${sc}</span>` : ""}</div>`;
      const tag = p ? `<span class="tk-pick ${p.top ? "top" : ""}">${p.top ? "TOP · " : ""}${esc(p.bet)}</span>` : w ? `<span class="tk-pick wind">WIND ${esc(w.bet)}</span>` : `<span class="tk-pick none">no pick</span>`;
      return `<a class="tk-item${p ? " has" : ""}" href="#breakdown/${esc(g.game_id)}"><div class="tk-st${started && !lv.completed ? " live" : ""}">${esc(status)}</div>${row(g.away_team, lv ? lv.away_score : "")}${row(g.home_team, lv ? lv.home_score : "")}${tag}</a>`;
    }).join("");
    const bar = document.createElement("div");
    bar.className = "ticker"; bar.innerHTML = `<div class="tk-track">${items}</div>`;
    document.querySelector("header.top").after(bar);
  }

  if (mode === "spotlight") {
    const ko = gid => { const g = W.games.find(x => x.game_id === gid); return g ? new Date(g.kickoff_utc) : new Date(0); };
    const upcoming = p => { const lv = live[`${p.home_team}-${p.away_team}`]; return ko(p.game_id) > new Date() && !(lv && lv.state !== "pre"); };
    const best = picks.filter(p => p.highlight && p.market === "spread" && upcoming(p)).sort((a, b) => (b.top ? 1 : 0) - (a.top ? 1 : 0) || (b.value || 0) - (a.value || 0))[0];
    const REC = S.record || {}, T = ((REC.all || {}).total || {}), top = T.top || {}, green = T.green || {};
    const hero = document.createElement("section");
    hero.className = "spotlight";
    if (best) {
      const g = W.games.find(x => x.game_id === best.game_id) || {};
      const c = Math.max(0, Math.min(1, best.chance || 0)), R = 44, C = 2 * Math.PI * R;
      hero.innerHTML = `<div class="sp-main"><div class="sp-kicker">${best.top ? "Top pick of the week" : "Best green pick right now"}</div>
          <div class="sp-teams"><img src="${logo(g.away_team)}" alt=""><span>${esc(g.away_team)} @ ${esc(g.home_team)}</span><img src="${logo(g.home_team)}" alt=""></div>
          <div class="sp-bet">${esc(best.bet)} <span>${am(best.price)}</span></div>
          <div class="sp-meta">${esc(day(dt(g.kickoff_utc)))} ${esc(time(dt(g.kickoff_utc)))} ET · model ${(Math.floor(best.edge * 10) / 10).toFixed(1)} pts off DraftKings · needs ${(100 * best.breakeven).toFixed(1)}%</div>
          <a class="sp-cta" href="#breakdown/${esc(best.game_id)}">See the breakdown →</a></div>
        <div class="sp-ring"><svg viewBox="0 0 110 110" role="img" aria-label="Chance ${(100 * c).toFixed(1)} percent"><circle cx="55" cy="55" r="${R}" class="trk"/><circle cx="55" cy="55" r="${R}" class="val" stroke-dasharray="${(C * c).toFixed(1)} ${C.toFixed(1)}" transform="rotate(-90 55 55)"/></svg>
          <div class="sp-pct">${(100 * c).toFixed(1)}%<small>chance</small></div></div>
        <div class="sp-stats"><div><b>${top.w || 0}-${top.l || 0}</b><span>Top picks since ${esc(String(REC.since || 2015))}</span></div><div><b>${green.pct ? (100 * green.pct).toFixed(1) + "%" : "–"}</b><span>green picks win rate</span></div><div><b>${(REC.card || {}).w || 0}-${(REC.card || {}).l || 0}</b><span>weekly card</span></div></div>`;
    } else {
      hero.innerHTML = `<div class="sp-main"><div class="sp-kicker">This week</div><div class="sp-bet">No green spread right now</div><div class="sp-meta">Either this week's picks are already underway or none qualify yet. Picks fill in through the week as injury reports and lines settle.</div></div>`;
    }
    document.querySelector("#kpis").before(hero);
  }
})();
