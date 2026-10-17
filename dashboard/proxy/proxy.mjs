// Proxy "Air Majoro Dashboard": reescribe Evidence sin tocar su código.
import http from 'node:http';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const UPSTREAM_HOST = process.env.UPSTREAM_HOST || 'localhost';
const UPSTREAM_PORT = Number(process.env.UPSTREAM_PORT || 4001);
const PORT = Number(process.env.PORT || 4000);

// Forzar siempre el modo claro (evita el toggle oscuro)
const FORCE_LIGHT = process.env.FORCE_LIGHT !== 'false';

// --- Cargar config desde los .txt ---
function loadTranslations() {
	try {
		return readFileSync(path.join(__dirname, 'translations.txt'), 'utf8')
			.split('\n')
			.map((l) => l.trim())
			.filter((l) => l && !l.startsWith('#'))
			.map((l) => l.split('=>').map((s) => s.trim()))
			.filter((p) => p.length === 2 && p[0]);
	} catch {
		return [];
	}
}

function loadHide() {
	try {
		return readFileSync(path.join(__dirname, 'hide.txt'), 'utf8')
			.split('\n')
			.map((l) => l.trim())
			.filter((l) => l && !l.startsWith('#'));
	} catch {
		return [];
	}
}

const TRANSLATIONS = loadTranslations();
const HIDE = loadHide();
const MAP = Object.fromEntries(TRANSLATIONS);
const NAME = MAP['Evidence'] || 'Air Majoro Dashboard';

// --- Favicon propio ---
const FAVICON_PATH = path.join(__dirname, 'favico.ico');
let FAVICON = null;
try {
	FAVICON = readFileSync(FAVICON_PATH);
} catch {
	console.warn('⚠ No se encontró favico.ico en ' + FAVICON_PATH);
}
// Rutas de icono que servimos nosotros (incluye la petición automática del navegador)
const ICON_ROUTES = new Set(['/favico.ico', '/favicon.ico', '/favicon.svg']);

// --- Tipografía global (Poppins) -----------------------------------------
// Evidence 0.10.1 restringe el token `fonts` de theme.yaml a
// sans-serif | serif | mono (fuentes empaquetadas), así que una fuente propia
// como Poppins no se puede declarar allí. Se carga e inyecta aquí, en la
// capa que ya usa el proyecto para personalizar Evidence sin tocar su código.
const FONT_FAMILY = "'Poppins', 'Geist', sans-serif";
const FONT_FAMILY_MONO = "'Poppins', 'Geist Mono', Consolas, monospace";
const FONT_GOOGLE_URL =
	'https://fonts.googleapis.com/css2?family=Poppins:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&display=swap';

// --- Snippet inyectado en cada página ---
const INJECT = `
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="${FONT_GOOGLE_URL}">
<style id="am-style">
:root { color-scheme: light; }
/* Poppins en toda la interfaz: sobrescribe las variables de tema de Evidence.
   Usamos html:root (mayor especificidad que :root) + !important para ganar
   a las variables que Evidence fija con !important. */
html:root {
  --theme-font-heading: ${FONT_FAMILY} !important;
  --theme-font-body: ${FONT_FAMILY} !important;
  --theme-font-mono: ${FONT_FAMILY_MONO} !important;
  --default-font-family: ${FONT_FAMILY} !important;
  --default-mono-font-family: ${FONT_FAMILY_MONO} !important;
  --evidence-font-body: ${FONT_FAMILY} !important;
  --evidence-font-mono: ${FONT_FAMILY_MONO} !important;
}
${HIDE.map((s) => `${s} { display: none !important; }`).join('\n')}
</style>
<script id="am-script">
(function () {
  var MAP = ${JSON.stringify(MAP)};
  var NAME = ${JSON.stringify(NAME)};
  var FORCE_LIGHT = ${FORCE_LIGHT ? 'true' : 'false'};
  var HIDE_MENU_TEXT = ['Light', 'Dark'];
  var FONT_FAMILY = ${JSON.stringify(FONT_FAMILY)};

  // allow-downloads en los iframes del sandbox de Evidence. El bloque {% html %}
  // (nuestra tabla custom) vive en un iframe con sandbox="allow-scripts", es
  // decir origen OPAXO: la activación de usuario NO se propaga al padre
  // cross-origin, así que si la descarga la hace el padre (postMessage) el
  // navegador la ve como "automática" y Brave la bloquea. Al añadir
  // allow-downloads al sandbox, el clic del usuario DENTRO del iframe mantiene
  // su gesto y la descarga nativa funciona (Chrome/Brave y Firefox).
  function patchIframeSandbox() {
    try {
      var ensure = function (v) {
        if (typeof v !== 'string' || /allow-downloads/.test(v)) return v;
        return (v + ' allow-downloads').trim();
      };
      // Svelte 5 (usa xe/template) monta los nodos clonando un <template> cuyo
      // HTML se asigna por innerHTML; ahí es donde nace el iframe del sandbox.
      var ensureHtml = function (v) {
        if (typeof v !== 'string' || v.indexOf('<iframe') === -1 ||
            v.indexOf('sandbox=') === -1 || /allow-downloads/.test(v)) return v;
        return v.replace(/<iframe([^>]*?)sandbox="([^"]*)"/g,
          '<iframe$1sandbox="$2 allow-downloads"');
      };
      var d1 = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML');
      if (d1 && d1.set) {
        Object.defineProperty(Element.prototype, 'innerHTML', {
          configurable: true,
          enumerable: d1.enumerable,
          get: d1.get,
          set: function (v) { return d1.set.call(this, ensureHtml(v)); }
        });
      }
      // Elementos creados con setAttribute('sandbox', ...).
      var origSet = Element.prototype.setAttribute;
      if (origSet) {
        Element.prototype.setAttribute = function (name, value) {
          if (this instanceof HTMLIFrameElement && String(name).toLowerCase() === 'sandbox')
            value = ensure(value);
          return origSet.apply(this, arguments);
        };
      }
      // Asignaciones a la propiedad .sandbox (DOMTokenList reflejada).
      var desc = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'sandbox');
      if (desc && desc.set) {
        Object.defineProperty(HTMLIFrameElement.prototype, 'sandbox', {
          configurable: true,
          enumerable: desc.enumerable,
          get: desc.get,
          set: function (v) { return desc.set.call(this, ensure(v)); }
        });
      }
      // Svelte 5 monta el iframe CLONANDO una plantilla (Node.cloneNode). Los
      // flags del sandbox se calculan al crear el browsing context (al insertar
      // el nodo); cambiar el atributo después ya no sirve. Por eso arreglamos el
      // CLON antes de que Svelte lo inserte en el DOM.
      var fixNode = function (n) {
        try {
          if (n && n.nodeType === 1 && n.tagName === 'IFRAME') {
            var v = n.getAttribute('sandbox');
            if (v !== null && v.indexOf('allow-downloads') === -1) n.setAttribute('sandbox', ensure(v));
          } else if (n && n.querySelectorAll) {
            var l = n.querySelectorAll('iframe[sandbox]');
            for (var i = 0; i < l.length; i++) {
              var v2 = l[i].getAttribute('sandbox');
              if (v2 && v2.indexOf('allow-downloads') === -1) l[i].setAttribute('sandbox', ensure(v2));
            }
          }
        } catch (e) {}
        return n;
      };
      var origClone = Node.prototype.cloneNode;
      if (origClone) {
        Node.prototype.cloneNode = function (deep) { return fixNode(origClone.call(this, deep)); };
      }
      var origImport = Document.prototype.importNode;
      if (origImport) {
        Document.prototype.importNode = function (n, deep) { return fixNode(origImport.call(this, n, deep)); };
      }
      // Refuerzo: cualquier iframe que llegue al DOM por otra vía.
      var fix = function (root) {
        try {
          if (root.nodeType === 1 && root.tagName === 'IFRAME') {
            var v = root.getAttribute('sandbox');
            if (v !== null && v.indexOf('allow-downloads') === -1) root.setAttribute('sandbox', ensure(v));
          } else if (root.querySelectorAll) {
            var list = root.querySelectorAll('iframe[sandbox]');
            for (var k = 0; k < list.length; k++) {
              var v2 = list[k].getAttribute('sandbox');
              if (v2 && v2.indexOf('allow-downloads') === -1) list[k].setAttribute('sandbox', ensure(v2));
            }
          }
        } catch (e) {}
      };
      new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++) {
          var added = muts[i].addedNodes;
          for (var j = 0; j < added.length; j++) fix(added[j]);
        }
      }).observe(document.documentElement, { childList: true, subtree: true });
    } catch (e) {}
  }
  patchIframeSandbox();

  // Meses en español. Evidence formatea las fechas con date-fns (inglés) y no
  // expone un locale en la configuración, así que traducimos las etiquetas de
  // mes tanto en el DOM (tablas/pivotes) como en <canvas> (gráficos ECharts).
  var MONTHS = {
    January: 'Enero', February: 'Febrero', March: 'Marzo', April: 'Abril',
    June: 'Junio', July: 'Julio', August: 'Agosto', September: 'Setiembre',
    October: 'Octubre', November: 'Noviembre', December: 'Diciembre',
    Jan: 'Ene', Feb: 'Feb', Mar: 'Mar', Apr: 'Abr', May: 'May', Jun: 'Jun',
    Jul: 'Jul', Aug: 'Ago', Sep: 'Set', Sept: 'Set', Oct: 'Oct', Nov: 'Nov', Dec: 'Dic'
  };
  var MONTH_RE = /\\b(January|February|March|April|June|July|August|September|October|November|December|Sept|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\\b/g;
  function trMonths(s) {
    return s.replace(MONTH_RE, function (m) { return MONTHS[m] || m; });
  }

  // Los gráficos (ECharts) dibujan el texto en <canvas>, donde el CSS no
  // aplica. Parcheamos el setter de ctx.font para que "sans-serif" (familia
  // por defecto de Evidence) se resuelva a Poppins.
  function patchCanvasFont() {
    try {
      var proto = CanvasRenderingContext2D.prototype;
      var desc = Object.getOwnPropertyDescriptor(proto, 'font');
      if (!desc || !desc.set) return;
      Object.defineProperty(proto, 'font', {
        configurable: true,
        enumerable: desc.enumerable,
        get: function () { return desc.get.call(this); },
        set: function (value) {
          if (typeof value === 'string' && /sans-serif/i.test(value) && !/Poppins/i.test(value))
            value = value.replace(/sans-serif/gi, FONT_FAMILY);
          desc.set.call(this, value);
        }
      });
    } catch (e) {}
  }
  patchCanvasFont();

  // Traduce las etiquetas de mes que ECharts dibuja en <canvas>.
  function patchCanvasMonths() {
    try {
      var proto = CanvasRenderingContext2D.prototype;
      ['fillText', 'strokeText'].forEach(function (fn) {
        var orig = proto[fn];
        if (!orig) return;
        proto[fn] = function (text) {
          if (typeof text === 'string') {
            var t = trMonths(text);
            if (t !== text) arguments[0] = t;
          }
          return orig.apply(this, arguments);
        };
      });
    } catch (e) {}
  }
  patchCanvasMonths();

  // Cuando la fuente termina de cargar, forzamos un re-render de los gráficos
  // para que el texto (ya medido con la fuente) use Poppins.
  function refreshCharts() {
    if (document.fonts && document.fonts.ready)
      document.fonts.ready.then(function () {
        window.dispatchEvent(new Event('resize'));
        setTimeout(function () { window.dispatchEvent(new Event('resize')); }, 800);
      });
  }

  // Descarga puente: la tabla custom (outline_table) vive en un iframe con
  // sandbox="allow-scripts", donde el navegador bloquea las descargas. El iframe
  // nos manda el CSV por postMessage y descargamos aquí, en el documento padre.
  window.addEventListener('message', function (ev) {
    var d = ev && ev.data;
    if (!d) return;
    // Ping de capacidades: el componente pregunta si puede descargar directo
    // (es decir, si el sandbox tiene allow-downloads → lo tendrá).
    if (d.__amCapsRequest === true) {
      try { ev.source.postMessage({ __amCaps: { download: true } }, '*'); } catch (e) {}
      return;
    }
    if (d.__amDownload !== true || typeof d.csv !== 'string') return;
    try {
      var blob = new Blob(['\\ufeff' + d.csv], { type: 'text/csv;charset=utf-8;' });
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = d.filename || 'datos.csv';
      a.style.display = 'none';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
    } catch (e) {}
  });

  function fixTitle() {
    if (document.title.indexOf('Evidence') === 0)
      document.title = document.title.replace(/^Evidence/, NAME);
  }
  function fixText(root) {
    if (!root) return;
    var w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT), n;
    while ((n = w.nextNode())) {
      var t = n.nodeValue.trim();
      if (MAP[t]) {
        n.nodeValue = n.nodeValue.replace(t, MAP[t]);
      } else if (/[A-Za-z]/.test(n.nodeValue)) {
        var mt = trMonths(n.nodeValue);
        if (mt !== n.nodeValue) n.nodeValue = mt;
      }
    }
  }

  function hideMenuItems() {
    var items = document.querySelectorAll('[role="menuitem"]');
    for (var i = 0; i < items.length; i++) {
      if (HIDE_MENU_TEXT.indexOf(items[i].textContent.trim()) >= 0)
        items[i].style.display = 'none';
    }
  }
  function forceLight() {
    var el = document.documentElement;
    if (el.classList.contains('dark')) el.classList.remove('dark');
    if (el.getAttribute('data-theme') !== 'light') el.setAttribute('data-theme', 'light');
    if (el.style.colorScheme !== 'light') el.style.colorScheme = 'light';
    try {
      if (localStorage.getItem('mode-watcher-mode') !== 'light')
        localStorage.setItem('mode-watcher-mode', 'light');
      localStorage.removeItem('mode-watcher-theme');
    } catch (e) {}
  }
  function boot() {
    if (FORCE_LIGHT) forceLight();
    fixTitle();
    fixText(document.body);
    hideMenuItems();
    refreshCharts();
    if (FORCE_LIGHT) {
      new MutationObserver(forceLight).observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['class', 'data-theme', 'style']
      });
    }
    new MutationObserver(function () {
      if (FORCE_LIGHT) forceLight();
      fixTitle();
      fixText(document.body);
      hideMenuItems();
    }).observe(document.body, { childList: true, subtree: true, characterData: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
</script>
`;

// --- Reescritura del HTML server-rendered ---
function rewrite(html) {
	// Título (sin parpadeo)
	html = html.replace(/<title>Evidence\b/g, '<title>' + NAME);
	// Nodos de texto exactos (ej: el "Evidence" del sidebar)
	html = html.replace(/>([^<>]+)</g, (m, inner) => {
		const t = inner.trim();
		if (MAP[t]) return '>' + inner.replace(t, MAP[t]) + '<';
		return m;
	});
	// Favicon propio (sobrescribe el de Evidence, absoluto para no depender de la ruta)
	html = html.replace(
		/<link[^>]*rel="(?:icon|shortcut icon)"[^>]*>/gi,
		'<link rel="icon" href="/favico.ico" type="image/x-icon" />'
	);
	// Inyectar CSS + JS
	return html.replace('</head>', INJECT + '</head>');
}

// --- Servidor proxy ---
const server = http.createServer((req, res) => {
	// Servir nuestro favicon directamente (sin pasar por Evidence)
	if (FAVICON && req.method === 'GET') {
		const { pathname } = new URL(req.url, 'http://localhost');
		if (ICON_ROUTES.has(pathname)) {
			res.writeHead(200, {
				'content-type': 'image/x-icon',
				'content-length': FAVICON.length,
				'cache-control': 'public, max-age=86400'
			});
			res.end(FAVICON);
			return;
		}
	}

	const headers = { ...req.headers, host: `${UPSTREAM_HOST}:${UPSTREAM_PORT}` };
	delete headers['accept-encoding']; // sin compresión para poder reescribir

	const upstream = http.request(
		{ host: UPSTREAM_HOST, port: UPSTREAM_PORT, method: req.method, path: req.url, headers },
		(up) => {
			const isHtml = (up.headers['content-type'] || '').includes('text/html');
			if (!isHtml) {
				res.writeHead(up.statusCode, up.headers);
				up.pipe(res);
				return;
			}
			const chunks = [];
			up.on('data', (c) => chunks.push(c));
			up.on('end', () => {
				const html = rewrite(Buffer.concat(chunks).toString('utf8'));
				const h = { ...up.headers };
				delete h['content-length'];
				h['content-type'] = 'text/html; charset=utf-8';
				res.writeHead(up.statusCode, h);
				res.end(html);
			});
		}
	);
	upstream.on('error', (e) => {
		res.writeHead(502, { 'content-type': 'text/plain' });
		res.end('Proxy error: ' + e.message);
	});
	req.pipe(upstream);
});

server.listen(PORT, () =>
	console.log(`Air Majoro proxy -> http://localhost:${PORT}  (Evidence :${UPSTREAM_PORT})`)
);
