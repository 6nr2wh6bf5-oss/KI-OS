/* World Monitor – Panels ENERGIE und SPANNUNGSFALL DE.
   Einbindung: <div id="panel-energie"></div> <div id="panel-spannungsfall"></div>
               <script src="panel_energie_spannungsfall.js"></script>
   Holt /api/energie und /api/spannungsfall alle 10 Min. Keine Abhaengigkeiten. */
(function () {
  const FARBE = ["#3fb950", "#9be15d", "#e3b341", "#f0883e", "#f85149", "#ff2d55"];
  const STUFE_TXT = { 1: "NORMAL", 2: "ERHÖHT", 3: "ANGESPANNT", 4: "KRITISCH", 5: "AKUT" };
  const css = `
  .wmx{font:12px/1.4 var(--font,ui-monospace,Consolas,monospace);color:var(--text,#cfe3f0);background:var(--panel-bg,rgba(8,20,32,.85));
       border:1px solid var(--border,#1f4a63);border-radius:6px;padding:10px;margin-bottom:10px}
  .wmx h3{margin:0 0 6px;font-size:13px;letter-spacing:.12em;color:var(--accent,#5fd4ff);display:flex;justify-content:space-between;align-items:center}
  .wmx .badge{padding:1px 8px;border-radius:3px;color:#081420;font-weight:700;font-size:11px}
  .wmx .gauges{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:6px 0}
  .wmx .g{background:rgba(255,255,255,.04);border-radius:4px;padding:6px}
  .wmx .g b{font-size:18px}.wmx .bar{height:5px;background:#16303f;border-radius:3px;margin-top:4px;overflow:hidden}
  .wmx .bar i{display:block;height:100%}
  .wmx table{width:100%;border-collapse:collapse;color:inherit;font:inherit}.wmx td{padding:3px 2px;border-top:1px solid rgba(255,255,255,.06);vertical-align:top}
  .wmx tr.k td{color:var(--accent,#5fd4ff);font-size:11px;letter-spacing:.08em;padding-top:8px;border:0}
  .wmx .dots{white-space:nowrap}.wmx td:nth-child(n+3){white-space:nowrap;text-align:right}.wmx .dots i{display:inline-block;width:7px;height:7px;margin-right:2px;border-radius:50%;background:#16303f}
  .wmx tr.r{cursor:pointer}.wmx tr.r:hover{background:rgba(95,212,255,.06)}
  .wmx .det{display:none;color:#9fb6c6;font-size:11px;padding:4px 2px 8px}.wmx .det a{color:#5fd4ff}
  .wmx tr.open+tr .det{display:block}
  .wmx .mut{color:#7d93a3;font-size:11px}.wmx .warn{color:#f0883e}
  .wmx svg{width:100%;height:46px;display:block}
  .wmx ul{margin:4px 0 0;padding-left:16px}`;
  const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);

  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const dots = n => `<span class="dots">${[0, 1, 2, 3].map(i => `<i style="${i < n ? "background:" + FARBE[n] : ""}"></i>`).join("")}</span>`;
  const badge = s => `<span class="badge" style="background:${FARBE[s]}">STUFE ${s} · ${STUFE_TXT[s]}</span>`;

  function spark(verlauf, keys, farben) {
    const v = (verlauf || []).slice(-90);
    if (v.length < 2) return `<div class="mut">Verlauf: ab morgen sichtbar (1 Wert pro Tag)</div>`;
    const W = 300, H = 46, n = v.length - 1;
    const lines = keys.map((k, j) => {
      const pts = v.map((h, i) => `${(i / n * W).toFixed(1)},${(H - 2 - (h[k] ?? 0) / 100 * (H - 4)).toFixed(1)}`).join(" ");
      return `<polyline fill="none" stroke="${farben[j]}" stroke-width="1.5" points="${pts}"/>`;
    }).join("");
    return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${[25, 50, 75].map(y => `<line x1="0" x2="${W}" y1="${H - 2 - y / 100 * (H - 4)}" y2="${H - 2 - y / 100 * (H - 4)}" stroke="#16303f"/>`).join("")}${lines}</svg>
      <div class="mut">${esc(v[0].datum)} – ${esc(v[v.length - 1].datum)} · ${keys.map((k, j) => `<span style="color:${farben[j]}">■</span> ${k}`).join(" ")}</div>`;
  }
  function gauge(name, wert, trend) {
    const s = wert < 20 ? 1 : wert < 40 ? 2 : wert < 60 ? 3 : wert < 80 ? 4 : 5;
    return `<div class="g"><div class="mut">${name}</div><b style="color:${FARBE[s]}">${Math.round(wert)}</b> <span class="mut">/100 ${trend || ""}</span>
      <div class="bar"><i style="width:${wert}%;background:${FARBE[s]}"></i></div></div>`;
  }
  function toggle(root) {
    root.querySelectorAll("tr.r").forEach(tr => tr.onclick = () => tr.classList.toggle("open"));
  }
  const bsp = arr => (arr || []).length ? `<ul>${arr.map(b => `<li><a href="${esc(b.link)}" target="_blank" rel="noopener">${esc(b.titel)}</a></li>`).join("")}</ul>` : "";

  function renderSpannung(el, s) {
    const kat = s.kategorien_namen || {};
    let rows = "";
    Object.keys(kat).forEach(k => {
      rows += `<tr class="k"><td colspan="4">${esc(kat[k])} · ${Math.round((s.kategorien || {})[k] || 0)}</td></tr>`;
      s.indikatoren.filter(i => i.kategorie === k).forEach(i => {
        rows += `<tr class="r"><td>${esc(i.id)}</td><td>${esc(i.name)}${i.anomalie ? ' <span class="warn">▲ Anomalie</span>' : ""}${i.pruefhinweis ? ' <span class="warn">⚑ prüfen</span>' : ""}</td>
          <td>${dots(i.stufe)}</td><td title="Trend 30 Tage">${i.trend_30t || "→"}</td></tr>
          <tr><td></td><td colspan="3"><div class="det"><b>${esc(i.kriterium)}</b><br>${esc(i.text)}<br>
          <span class="mut">Basis ${i.basis_stufe} · Meldungen ${i.news_stufe} (${i.meldungen_7t}/7T${i.vorwochen_mittel != null ? ", Ø Vorwochen " + i.vorwochen_mittel : ""}) · Stand ${esc(i.stand)}${i.veraltet ? ' <span class="warn">Bewertung veraltet</span>' : ""}<br>Quelle: ${/^https?:/.test(i.quelle) ? `<a href="${esc(i.quelle)}" target="_blank" rel="noopener">Link</a>` : esc(i.quelle)}</span>
          ${i.pruefhinweis ? `<div class="warn">${esc(i.pruefhinweis)}</div>` : ""}${bsp(i.beispiele)}</div></td></tr>`;
      });
    });
    const ev = (s.ereignisse || []).slice(-6).reverse().map(e => `<li>${esc(e.datum)}: ${esc(e.text || `${e.name} Stufe ${e.von} → ${e.nach} (${e.grund})`)}</li>`).join("");
    el.innerHTML = `<div class="wmx"><h3>SPANNUNGSFALL DE · AUFRÜSTUNG NATO ${badge(s.stufe)}</h3>
      <div class="mut">${esc(s.stufe_text)} · Grund: ${esc(s.stufe_grund)}</div>
      <div class="gauges">${gauge("ESKALATION (akut)", s.eskalation, (s.trend_7t || {}).eskalation)}${gauge("AUFRÜSTUNG (strukturell)", s.aufruestung, (s.trend_7t || {}).aufruestung)}</div>
      ${spark(s.verlauf, ["eskalation", "aufruestung"], ["#f0883e", "#5fd4ff"])}
      <table>${rows}</table>
      ${ev ? `<div class="mut" style="margin-top:8px">VERÄNDERUNGEN</div><ul>${ev}</ul>` : ""}
      <div class="mut" style="margin-top:6px">Basisbewertung ${esc(s.katalog_bewertet_am)} · aktualisiert ${esc((s.aktualisiert || "").replace("T", " ").slice(0, 16))} UTC${(s.veraltete_bewertungen || []).length ? ' · <span class="warn">veraltet: ' + s.veraltete_bewertungen.join(", ") + "</span>" : ""}<br>
      Aufrüstung allein ist Abschreckung, kein Kriegsindikator. Formelle Auslöser (Art. 80a/115a GG, NATO Art. 5) werden nur manuell gesetzt.</div></div>`;
    toggle(el);
  }

  function renderEnergie(el, s) {
    const rows = s.indikatoren.map(i => `<tr class="r"><td>${esc(i.name)}</td><td>${i.ok ? dots(i.stufe) : '<span class="mut">–</span>'}</td>
      <td>${i.ok ? esc(i.wert) + " " + esc(i.einheit) : ""}</td><td>${i.trend || ""}</td></tr>
      <tr><td colspan="4"><div class="det">${esc(i.text)}<br><span class="mut">Quelle: ${esc(i.quelle)}</span>${bsp(i.beispiele)}</div></td></tr>`).join("");
    el.innerHTML = `<div class="wmx"><h3>ENERGIE · VERSORGUNG ${badge(s.stufe)}</h3>
      <div class="gauges">${gauge("ENERGIE-INDEX", s.index, s.trend_7d)}<div class="g"><div class="mut">DATENLÜCKEN</div>${(s.datenluecken || []).length ? `<span class="warn">${esc(s.datenluecken.join(", "))}</span>` : "keine"}</div></div>
      ${spark(s.verlauf, ["index"], ["#e3b341"])}
      <table>${rows}</table>
      <div class="mut" style="margin-top:6px">aktualisiert ${esc((s.aktualisiert || "").replace("T", " ").slice(0, 16))} UTC · Zeile antippen für Details</div></div>`;
    toggle(el);
  }

  async function lade() {
    const ziele = [["panel-energie", "/api/energie", renderEnergie], ["panel-spannungsfall", "/api/spannungsfall", renderSpannung]];
    for (const [id, url, fn] of ziele) {
      const el = document.getElementById(id); if (!el) continue;
      try { const r = await fetch(url); fn(el, await r.json()); }
      catch (e) { el.innerHTML = `<div class="wmx"><span class="warn">${id}: keine Daten (${esc(e.message)})</span></div>`; }
    }
  }
  window.wmxRender = { energie: renderEnergie, spannungsfall: renderSpannung, lade };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", lade); else lade();
  setInterval(lade, 10 * 60 * 1000);
})();
