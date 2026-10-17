---
type: component
description: "Tabla jerárquica (outline) colapsable: proveedor y sub-nivel en una sola columna"
attributes:
  data:
    type: query
    required: true
  value:
    type: column
    required: true
  total_label:
    type: string
    default: Total
  title:
    type: string
    default: ""
---

{% html
  variables={ q=$data measure=$value total=$total_label title=$title }
%}
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fontsource/geist-sans@5/index.css">
<div id="am_card" class="am-card">
  <div id="am_outline" class="am-outline"></div>
  <div class="am-tools">
    <button class="am-btn" id="am-dl" title="Descargar datos" aria-label="Descargar datos">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
    </button>
  </div>
  <div id="am_toast" class="am-toast"></div>
</div>
<style id="am_style">
  html, body { margin: 0; padding: 0; }
  .am-card, .am-outline { font-family: 'Geist Sans', 'Geist', system-ui, -apple-system, 'Segoe UI', sans-serif; }
  .am-card { font-size: 12px; color: #09090b; background: #ffffff; border: 1px solid #e4e4e7; border-radius: 8px; overflow: hidden; }
  .am-outline table { border-collapse: collapse; width: 100%; }
  .am-outline th, .am-outline td { padding: 4px 12px 4px 4px; text-align: right; white-space: nowrap; }
  .am-outline th { font-weight: 500; color: #71717a; border-bottom: 1px solid #e4e4e7; }
  .am-outline th.am-label, .am-outline td.am-label { text-align: left; }
  .am-outline tbody tr { border-bottom: 1px solid #e4e4e7; }
  .am-outline tbody tr.am-group { cursor: pointer; }
  .am-outline tbody tr.am-group td { font-weight: 400; }
  .am-outline tbody tr.am-group:hover td { background: #f4f4f5; }
  .am-outline td.am-child { padding-left: 32px; font-weight: 400; }
  .am-outline .am-toggle { display: inline-block; width: 14px; color: #71717a; }
  .am-outline tbody tr.am-total td { font-weight: 400; border-top: 1px solid #a1a1aa; background: #f4f4f5; }
  .am-tools { display: flex; justify-content: flex-end; gap: 2px; padding: 2px 6px; }
  .am-btn { background: none; border: 0; padding: 3px; cursor: pointer; color: #71717a; display: inline-flex; }
  .am-btn:hover { color: #09090b; }
  /* modo oscuro */
  .am-card[data-mode="dark"] { color: #f8fafc; background: #09090b; border-color: #313133; }
  .am-card[data-mode="dark"] th { color: #a1a1aa; border-bottom-color: #313133; }
  .am-card[data-mode="dark"] tbody tr { border-bottom-color: #313133; }
  .am-card[data-mode="dark"] tbody tr.am-group:hover td { background: #18181b; }
  .am-card[data-mode="dark"] .am-toggle { color: #a1a1aa; }
  .am-card[data-mode="dark"] tbody tr.am-total td { border-top-color: #52525b; background: #2d2d2f; }
  .am-card[data-mode="dark"] .am-btn { color: #a1a1aa; }
  .am-card[data-mode="dark"] .am-btn:hover { color: #f8fafc; }
  .am-toast { position: fixed; left: 50%; bottom: 10px; transform: translateX(-50%); background: #18181b; color: #fff;
    font-size: 11px; padding: 6px 10px; border-radius: 6px; opacity: 0; transition: opacity .2s; pointer-events: none; }
  .am-toast.show { opacity: 1; }
</style>
<script>
const MONTHS = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Set', 'Oct', 'Nov', 'Dic'];
const nf = new Intl.NumberFormat('es-PE', { maximumFractionDigits: 0 });
const state = { q: '', measure: '', totalLabel: 'Total', title: '', model: { months: [], groups: [] }, expanded: {} };

const iso = (v) => (v instanceof Date ? v.toISOString() : String(v));
const monthKey = (v) => iso(v).slice(0, 7);
const monthLabel = (v) => { const s = iso(v); return (MONTHS[Number(s.slice(5, 7)) - 1] || '') + '-' + s.slice(2, 4); };
const money = (n) => { const x = Number(n || 0); return x ? nf.format(x) : '-'; };
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function buildModel(rows, measure) {
  const months = [...new Set(rows.map((r) => monthKey(r.mes)))].sort();
  const groups = []; const index = {};
  rows.forEach((r) => {
    const p = r.proveedor || '(sin proveedor)';
    const d = r.descripcion_servicio || '(sin descripción)';
    if (!index[p]) { index[p] = { name: p, descs: {}, id: groups.length }; groups.push(index[p]); }
    const g = index[p];
    if (!g.descs[d]) g.descs[d] = {};
    const k = monthKey(r.mes);
    g.descs[d][k] = (g.descs[d][k] || 0) + Number(r[measure] || 0);
  });
  return { months, groups };
}

function tableHTML() {
  const { months, groups } = state.model;
  const total = {}; let grand = 0;
  groups.forEach((g) => Object.values(g.descs).forEach((dm) => { for (const k in dm) { total[k] = (total[k] || 0) + dm[k]; grand += dm[k]; } }));
  let h = '<table><thead><tr><th class="am-label"></th>';
  months.forEach((m) => { h += '<th>' + monthLabel(m) + '</th>'; });
  h += '<th>' + esc(state.totalLabel) + '</th></tr></thead><tbody>';
  groups.forEach((g) => {
    const gt = {}; let t = 0;
    Object.values(g.descs).forEach((dm) => { for (const k in dm) { gt[k] = (gt[k] || 0) + dm[k]; t += dm[k]; } });
    const open = !!state.expanded[g.id];
    h += '<tr class="am-group" data-g="' + g.id + '"><td class="am-label"><span class="am-toggle">' + (open ? '▾' : '▸') + '</span>' + esc(g.name) + '</td>';
    months.forEach((m) => { h += '<td>' + money(gt[m]) + '</td>'; });
    h += '<td>' + money(t) + '</td></tr>';
    Object.keys(g.descs).sort().forEach((d) => {
      const dm = g.descs[d]; let dt = 0; for (const k in dm) dt += dm[k];
      h += '<tr class="am-child-row" data-g="' + g.id + '" style="display:' + (open ? '' : 'none') + '"><td class="am-label am-child">' + esc(d) + '</td>';
      months.forEach((m) => { h += '<td>' + money(dm[m]) + '</td>'; });
      h += '<td>' + money(dt) + '</td></tr>';
    });
  });
  h += '<tr class="am-total"><td class="am-label">' + esc(state.totalLabel) + '</td>';
  months.forEach((m) => { h += '<td>' + money(total[m]) + '</td>'; });
  h += '<td>' + money(grand) + '</td></tr></tbody></table>';
  return h;
}

function draw() {
  const el = document.getElementById('am_outline');
  el.innerHTML = tableHTML();
  el.querySelectorAll('tr.am-group').forEach((tr) => {
    tr.addEventListener('click', () => {
      const gid = tr.getAttribute('data-g');
      state.expanded[gid] = !state.expanded[gid];
      const open = state.expanded[gid];
      el.querySelectorAll('tr.am-child-row[data-g="' + gid + '"]').forEach((c) => { c.style.display = open ? '' : 'none'; });
      tr.querySelector('.am-toggle').textContent = open ? '▾' : '▸';
    });
  });
}

function applyTheme() {
  const dark = !!(evidence.theme && evidence.theme.mode === 'dark');
  document.getElementById('am_card').setAttribute('data-mode', dark ? 'dark' : 'light');
  const bg = dark ? '#09090b' : '#ffffff';
  document.documentElement.style.background = bg;
  document.body.style.background = bg;
}

function toCSV() {
  const { months, groups } = state.model;
  const rowsCsv = [[state.title || 'Proveedor', 'Descripción del servicio'].concat(months.map(monthLabel)).concat([state.totalLabel])];
  groups.forEach((g) => {
    const gt = {}; let t = 0;
    Object.values(g.descs).forEach((dm) => { for (const k in dm) { gt[k] = (gt[k] || 0) + dm[k]; t += dm[k]; } });
    rowsCsv.push([g.name, ''].concat(months.map((m) => gt[m] || 0)).concat([t]));
    Object.keys(g.descs).sort().forEach((d) => {
      const dm = g.descs[d]; let dt = 0; for (const k in dm) dt += dm[k];
      rowsCsv.push(['', d].concat(months.map((m) => dm[m] || 0)).concat([dt]));
    });
  });
  return rowsCsv.map((r) => r.map((c) => '"' + String(c).replace(/"/g, '""') + '"').join(',')).join('\r\n');
}

let toastTimer;
function toast(msg) {
  const t = document.getElementById('am_toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 2500);
}

// El proxy añade `allow-downloads` al iframe del sandbox (Evidence lo crea con
// sandbox="allow-scripts", cuyo origen opaco impide que el gesto del clic en el
// iframe se propague al padre). Con allow-downloads, el clic del usuario aquí
// dentro conserva su gesto y la descarga nativa funciona en Chrome/Brave y
// Firefox. Le preguntamos al padre si esa capacidad está disponible.
let canDownloadDirect = false;
window.addEventListener('message', (ev) => {
  const d = ev.data;
  if (d && d.__amCaps) canDownloadDirect = !!d.__amCaps.download;
});
try {
  if (window.parent && window.parent !== window) window.parent.postMessage({ __amCapsRequest: true }, '*');
} catch (e) {}

function saveCSV(csv, name) {
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = name; a.rel = 'noopener';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

async function download() {
  const csv = toCSV();
  const name = (state.title || 'datos').replace(/[^\w-]+/g, '_') + '.csv';
  // 1) Descarga directa, aprovechando el gesto del clic (allow-downloads).
  if (canDownloadDirect) {
    try { saveCSV(csv, name); toast('Descarga iniciada'); return; } catch (e) {}
  }
  // 2) Respaldo: el documento padre (sin sandbox) hace la descarga.
  try {
    if (window.parent && window.parent !== window) {
      window.parent.postMessage({ __amDownload: true, filename: name, csv: csv }, '*');
      toast('Descarga iniciada');
      return;
    }
  } catch (e) {}
  // 3) Último recurso: intento directo de todos modos.
  try { saveCSV(csv, name); toast('Descarga iniciada'); } catch (e) { toast('No se pudo descargar'); }
}

async function load() {
  const vars = evidence.variables || {};
  state.q = vars.q; state.measure = vars.measure;
  state.totalLabel = vars.total || 'Total';
  state.title = vars.title || '';
  const rows = (await evidence.query(state.q)) || [];
  state.model = buildModel(rows, state.measure);
  draw();
  applyTheme();
}

document.getElementById('am-dl').addEventListener('click', download);

evidence.onThemeChange(applyTheme);
evidence.subscribe(() => { load(); });
await load();
evidence.ready();
</script>
{% /html %}
