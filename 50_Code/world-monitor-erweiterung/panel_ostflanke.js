/* World Monitor – Reiter OSTFLANKE (Baltikum, Suwalki-Korridor, Kaliningrad, Belarus, Ostsee).
   Einbindung: <div id="panel-ostflanke"></div> <script src="panel_ostflanke.js"></script>
   Holt /api/ostflanke alle 5 Min. Karte mit Leaflet (wird nachgeladen, falls nicht vorhanden). */
(function () {
  const FARBE = ["#3fb950", "#9be15d", "#e3b341", "#f0883e", "#f85149", "#ff2d55"];
  const STUFE_TXT = { 1: "RUHIG", 2: "ERHÖHT", 3: "ANGESPANNT", 4: "KRITISCH", 5: "AKUT" };
  const SEITE = { RU: "#f85149", BY: "#f85149" };
  const css = `
  .wmo{font:12px/1.4 var(--font,ui-monospace,Consolas,monospace);color:var(--text,#cfe3f0);background:var(--panel-bg,rgba(8,20,32,.85));
       border:1px solid var(--border,#1f4a63);border-radius:6px;padding:10px;margin-bottom:10px}
  .wmo h3{margin:0 0 6px;font-size:13px;letter-spacing:.12em;color:var(--accent,#5fd4ff);display:flex;justify-content:space-between;align-items:center;gap:6px;flex-wrap:wrap}
  .wmo h4{margin:10px 0 4px;font-size:11px;letter-spacing:.1em;color:var(--accent,#5fd4ff)}
  .wmo .badge{padding:1px 8px;border-radius:3px;color:#081420;font-weight:700;font-size:11px}
  .wmo .gauges{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin:6px 0}
  .wmo .g{background:rgba(255,255,255,.04);border-radius:4px;padding:6px}.wmo .g b{font-size:18px}
  .wmo .bar{height:5px;background:#16303f;border-radius:3px;margin-top:4px;overflow:hidden}.wmo .bar i{display:block;height:100%}
  .wmo .karte{height:340px;border-radius:4px;margin:6px 0;background:#0b1a26}
  .wmo .filter button{background:#0f2737;color:inherit;border:1px solid #1f4a63;border-radius:3px;padding:2px 8px;margin:0 4px 4px 0;font:inherit;cursor:pointer}
  .wmo .filter button.an{background:#1f4a63;color:#fff}
  .wmo .tw{overflow-x:auto}
  .wmo table{width:100%;border-collapse:collapse;color:inherit;font:inherit}
  .wmo td,.wmo th{padding:3px 4px;border-top:1px solid rgba(255,255,255,.06);vertical-align:top;text-align:left}
  .wmo th{color:#7d93a3;font-weight:400;font-size:11px}
  .wmo .ev td{word-break:break-word}.wmo .ev td:first-child{white-space:nowrap}
  .wmo a{color:#5fd4ff}.wmo .mut{color:#7d93a3;font-size:11px}.wmo .warn{color:#f0883e}
  .wmo .st{font-size:10px;padding:0 4px;border-radius:2px;white-space:nowrap}
  .wmo .st.b{background:#1d3b25;color:#7ee787}.wmo .st.u{background:#3b2f14;color:#e3b341}.wmo .st.e{background:#3b1717;color:#ff7b72}
  .wmo .dots{white-space:nowrap}.wmo .dots i{display:inline-block;width:7px;height:7px;margin-right:2px;border-radius:50%;background:#16303f}
  .wmo tr.r{cursor:pointer}.wmo tr.r:hover{background:rgba(95,212,255,.06)}
  .wmo .det{display:none;color:#9fb6c6;font-size:11px;padding:4px 2px 8px}.wmo tr.open+tr .det{display:block}
  .wmo ul{margin:4px 0 0;padding-left:16px}
  .wmo .evk{display:none;border-top:1px solid rgba(255,255,255,.08);padding:6px 0}.wmo .evk .f{color:#7d93a3}
  @media (max-width:700px){.wmo .karte{height:260px}.wmo .tw{display:none}.wmo .evk{display:block}}`;
  const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);

  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const dots = n => `<span class="dots">${[0, 1, 2, 3].map(i => `<i style="${i < n ? "background:" + FARBE[n] : ""}"></i>`).join("")}</span>`;
  const badge = s => `<span class="badge" style="background:${FARBE[s]}">STUFE ${s} · ${STUFE_TXT[s]}</span>`;
  const zeit = z => { if (!z) return "–"; const d = new Date(z); return d.toLocaleString("de-CH", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); };
  const stKl = s => s.startsWith("bestätigt") ? "b" : s.startsWith("Eigenangabe") ? "e" : "u";
  function gauge(name, wert, trend, farbeFix) {
    const s = wert < 25 ? 1 : wert < 50 ? 2 : wert < 68 ? 3 : wert < 85 ? 4 : 5;
    const f = farbeFix || FARBE[s];
    return `<div class="g"><div class="mut">${name}</div><b style="color:${f}">${Math.round(wert)}</b> <span class="mut">/100 ${trend || ""}</span>
      <div class="bar"><i style="width:${wert}%;background:${f}"></i></div></div>`;
  }

  let filter = "alle", daten = null, karte = null, schicht = null;
  const passt = e => filter === "alle" ? true : filter === "rub" ? e.wer.some(w => w === "RU" || w === "BY")
    : filter === "nato" ? e.wer.some(w => w !== "RU" && w !== "BY") && !e.wer.some(w => w === "RU" || w === "BY")
    : filter === "best" ? e.status.startsWith("bestätigt") : true;

  function ladeLeaflet() {
    if (window.L) return Promise.resolve();
    return new Promise((ok, fehl) => {
      const l = document.createElement("link"); l.rel = "stylesheet"; l.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"; document.head.appendChild(l);
      const s = document.createElement("script"); s.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"; s.onload = ok; s.onerror = fehl; document.head.appendChild(s);
    });
  }

  function zeichneKarte(el, s) {
    const box = el.querySelector(".karte"); if (!box || !window.L) return;
    if (!karte || karte._container !== box) {
      karte = L.map(box, { zoomControl: true, attributionControl: true }).setView([55.2, 23.5], 5);
      L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", { maxZoom: 10,
        attribution: "Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap contributors" }).addTo(karte);
      // Suwalki-Korridor (schematisch: Grenze PL-LT zwischen Kaliningrad und Belarus)
      L.polygon([[54.42, 22.70], [54.40, 23.10], [53.92, 23.55], [53.88, 23.30]], { color: "#e3b341", weight: 1, fillOpacity: .15 })
        .bindTooltip("Suwalki-Korridor (schematisch)").addTo(karte);
      // Reiter war beim Laden verborgen -> Groesse neu berechnen, sobald sichtbar
      if (window.ResizeObserver) new ResizeObserver(() => karte && karte.invalidateSize()).observe(box);
    }
    if (schicht) schicht.remove();
    schicht = L.layerGroup().addTo(karte);
    (s.orte || []).filter(o => ["ru", "by", "nato"].includes(o.art) && !/^(belarus|litauen|lettland|estland|polen-no|finnland)$/.test(o.id)).forEach(o =>
      L.circleMarker([o.lat, o.lon], { radius: 2, color: o.art === "nato" ? "#5fd4ff" : "#f85149", weight: 1, opacity: .5 }).bindTooltip(o.name).addTo(schicht));
    const proOrt = {};
    (s.ereignisse || []).filter(passt).forEach(e => { if (e.wohin && e.wohin[0]) (proOrt[e.wohin[0].id] = proOrt[e.wohin[0].id] || { o: e.wohin[0], e: [] }).e.push(e); });
    Object.values(proOrt).forEach(({ o, e }) => {
      const rub = e.some(x => x.wer.some(w => SEITE[w]));
      const best = e.some(x => x.status.startsWith("bestätigt"));
      L.circleMarker([o.lat, o.lon], { radius: 5 + Math.min(10, e.length * 1.5), color: rub ? "#f85149" : "#5fd4ff", weight: best ? 2 : 1,
        dashArray: best ? null : "3 3", fillOpacity: .25 })
        .bindPopup(`<b>${esc(o.name)}</b><br>${e.slice(0, 6).map(x => `${zeit(x.zeit)} · ${esc(x.titel)} <i>(${esc(x.status)})</i>`).join("<br>")}`).addTo(schicht);
    });
    ((s.technik || {}).adsb_jetzt || []).forEach(f =>
      L.circleMarker([f.lat, f.lon], { radius: 3, color: "#a5d6ff", weight: 1, fillOpacity: .9 })
        .bindTooltip(`${esc(f.cs || f.hex)} ${esc(f.typ)} (${esc(f.klasse)})${f.alt ? " · " + f.alt + " ft" : ""}`).addTo(schicht));
  }

  function render(el, s) {
    daten = s;
    const evs = (s.ereignisse || []).filter(passt).slice(0, 60);
    const rows = evs.map(e => `<tr class="ev">
      <td>${zeit(e.zeit)}</td><td>${esc((e.wer_llm && e.wer_llm.length ? e.wer_llm : e.wer).join(", ") || "–")}</td>
      <td>${esc(e.was_llm || e.was.slice(0, 3).join(", ") || "–")}</td>
      <td>${esc((e.wie_viel_llm && e.wie_viel_llm.length ? e.wie_viel_llm : e.wie_viel).join(", ") || "–")}</td>
      <td>${esc(e.wohin_llm || (e.wohin[0] || {}).name || "–")}</td>
      <td><span class="st ${stKl(e.status)}">${esc(e.status)}</span> <span class="mut">${esc(e.verl)}</span></td>
      <td class="hide-m"><a href="${esc(e.link)}" target="_blank" rel="noopener">${esc(e.titel)}</a><br><span class="mut">${esc(e.quelle)}${e.n_quellen > 1 ? " +" + (e.n_quellen - 1) + " weitere" : ""}</span></td></tr>`).join("");
    const karten = evs.map(e => `<div class="evk"><div><span class="st ${stKl(e.status)}">${esc(e.status)}</span> <span class="mut">${esc(e.verl)} · ${zeit(e.zeit)}</span></div>
      <div><span class="f">Wer:</span> ${esc((e.wer_llm && e.wer_llm.length ? e.wer_llm : e.wer).join(", ") || "–")} · <span class="f">Was:</span> ${esc(e.was_llm || e.was.slice(0, 3).join(", ") || "–")}</div>
      <div><span class="f">Wie viel:</span> ${esc((e.wie_viel_llm && e.wie_viel_llm.length ? e.wie_viel_llm : e.wie_viel).join(", ") || "–")} · <span class="f">Wohin:</span> ${esc(e.wohin_llm || (e.wohin[0] || {}).name || "–")}</div>
      <div><a href="${esc(e.link)}" target="_blank" rel="noopener">${esc(e.titel)}</a> <span class="mut">${esc(e.quelle)}${e.n_quellen > 1 ? " +" + (e.n_quellen - 1) : ""}</span></div></div>`).join("");
    const inds = (s.indikatoren || []).map(i => `<tr class="r"><td>${esc(i.id)}</td><td>${esc(i.name)}${i.anomalie ? ' <span class="warn">▲ Anomalie</span>' : ""}${i.pruefhinweis ? ' <span class="warn">⚑ prüfen</span>' : ""}${i.index === "verlegung" ? ' <span class="mut">(Abschreckung)</span>' : ""}</td><td>${dots(i.stufe)}</td></tr>
      <tr><td></td><td colspan="2"><div class="det"><b>${esc(i.kriterium)}</b><br>Basis ${i.basis_stufe}: ${esc(i.basis_text)} ${i.basis_quelle ? `<a href="${esc(i.basis_quelle)}" target="_blank" rel="noopener">Quelle</a>` : ""} (Stand ${esc(i.stand)})<br>
      Meldungen ${i.news_stufe} (${i.meldungen_7t} Ereignisse/7T, gewichtet ${i.gewichtet_7t}${i.vorwochen_mittel != null ? ", Ø Vorwochen " + i.vorwochen_mittel : ""}) · Technik ${i.technik_stufe}${i.technik_text ? ": " + esc(i.technik_text) : ""} · massgebend: ${esc(i.stufe_aus)}
      ${i.pruefhinweis ? `<div class="warn">${esc(i.pruefhinweis)}</div>` : ""}</div></td></tr>`).join("");
    const tb = s.technik_bewertung || {};
    const tech = ["adsb", "notam", "ais"].map(k => { const v = tb[k] || {}; const n = { adsb: "Militärflüge (ADS-B)", notam: "Luftraum (NOTAM)", ais: "Marine (AIS)" }[k];
      return `<tr><td>${n}</td><td>${v.ok ? dots(v.stufe) : '<span class="mut">–</span>'}</td><td class="${v.ok ? "" : "warn"}">${esc(v.text || "")}</td></tr>`; }).join("");
    const sf = s.spannungsfall || {};
    const sfTxt = Object.entries(sf).map(([k, v]) => `${esc(k)}: ${esc(v.text || v.pruef)}`).join("<br>");
    const ver = (s.veraenderungen || []).slice(-6).reverse().map(e => `<li>${esc(e.datum)}: ${esc(e.name)} ${e.von} → ${e.nach} (${esc(e.grund)})</li>`).join("");
    const k = s.konvergenz || {};
    el.innerHTML = `<div class="wmo"><h3>OSTFLANKE · BALTIKUM · SUWALKI ${badge(s.stufe)}</h3>
      <div class="mut">${esc(s.stufe_text)} · Grund: ${esc(s.stufe_grund)}</div>
      ${k.aktiv ? `<div class="${k.stark ? "warn" : "mut"}">${k.stark ? "⚠ KONVERGENZ: " : "Konvergenz schwach: "}${esc(k.text)}</div>` : ""}
      <div class="gauges">${gauge("ESKALATION (RU/BY, Vorfälle)", s.eskalation, (s.trend_7t || {}).eskalation)}${gauge("NATO-VERLEGUNGEN (Abschreckung)", s.verlegung, (s.trend_7t || {}).verlegung, "#5fd4ff")}</div>
      <div class="karte"></div>
      <div class="mut">Rot = RU/BY beteiligt, blau = NATO/Partner · durchgezogen = bestätigt, gestrichelt = unbestätigt · kleine Punkte = Militärflugzeuge mit Transponder</div>
      <h4>BEWEGUNGEN, VERLEGUNGEN, VORFÄLLE (14 TAGE)</h4>
      ${s.ausgeblendet_7t ? `<div class="mut">${s.ausgeblendet_7t} Meldungen der letzten 7 Tage ohne Bezug zu Eskalation, Bedrohung oder Truppenbewegung ausgeblendet</div>` : ""}
      <div class="filter">${[["alle", "Alle"], ["rub", "RU/BY"], ["nato", "NATO/Partner"], ["best", "nur bestätigt"]].map(([id, t]) => `<button data-f="${id}" class="${filter === id ? "an" : ""}">${t}</button>`).join("")}</div>
      <div class="tw"><table><tr><th>Zeit</th><th>Wer</th><th>Was</th><th>Wie viel</th><th>Wohin</th><th>Status</th><th class="hide-m">Meldung / Quelle</th></tr>${rows || '<tr><td colspan="7" class="mut">keine Meldungen</td></tr>'}</table></div>${karten}
      <h4>INDIKATOREN</h4><table>${inds}</table>
      <h4>TECHNISCHE SIGNALE</h4><table>${tech}</table>
      ${sfTxt ? `<h4>WIRKUNG AUF SPANNUNGSFALL DE</h4><div class="mut">${sfTxt}</div>` : ""}
      ${ver ? `<h4>VERÄNDERUNGEN</h4><ul>${ver}</ul>` : ""}
      <div class="mut" style="margin-top:8px">aktualisiert ${zeit(s.aktualisiert)} · ${esc(s.hinweis)}<br>Verlässlichkeit: A offizielle Stelle, B seriöse Medien/Analyse bzw. Eigenangabe RU/BY, C Einzelquelle.</div></div>`;
    el.querySelectorAll(".filter button").forEach(b => b.onclick = () => { filter = b.dataset.f; render(el, daten); });
    el.querySelectorAll("tr.r").forEach(tr => tr.onclick = () => tr.classList.toggle("open"));
    karte = null;
    ladeLeaflet().then(() => zeichneKarte(el, s)).catch(() => { const b = el.querySelector(".karte"); if (b) b.innerHTML = '<div class="mut" style="padding:8px">Karte nicht ladbar</div>'; });
  }

  async function lade() {
    const el = document.getElementById("panel-ostflanke"); if (!el) return;
    try { const r = await fetch("/api/ostflanke"); render(el, await r.json()); }
    catch (e) { el.innerHTML = `<div class="wmo"><span class="warn">Ostflanke: keine Daten (${esc(e.message)})</span></div>`; }
  }
  window.wmoOstflanke = { lade, render };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", lade); else lade();
  setInterval(lade, 5 * 60 * 1000);
})();
