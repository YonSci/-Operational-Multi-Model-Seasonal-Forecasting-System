/* Local stand-in for the online dashboard's `dash` API, so frontend/tracker/page.html runs inside the
   platform from CSV/JSON files in ./data (written by scripts/build_tracker_page.py).
   Implements what the page uses: data, onData, calc, params/setParams/resetParams, colors, setLink, refresh.
   Also handles embedding in the React app (iframe, same origin): follows the app's light/dark theme, reports
   the page height to the app and keeps the page's sticky context bar in view while the app scrolls. */
(function () {
  const files = window.TRACKER_DATASETS || {};
  const store = {};
  const calcs = {};
  const listeners = [];
  const defaults = Object.assign({}, window.TRACKER_PARAMS || {});
  let params = Object.assign({}, defaults);
  let pending = false;

  const run = () => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => {
      pending = false;
      listeners.forEach((fn) => { try { fn(); } catch (e) { console.error('[tracker]', e); } });
    });
  };

  const load = (id) => {
    if (store[id]) return;
    const f = files[id];
    if (!f) { store[id] = { status: 'missing', data: [], meta: [] }; return; }
    store[id] = { status: 'loading', data: [], meta: [] };
    const p = f.endsWith('.json')
      ? d3.json(f).then((d) => (Array.isArray(d) ? d : (d.rows || d.data || d.results || [])))
      : d3.csv(f);
    p.then((rows) => {
      store[id] = { status: 'ok', data: rows, columns: rows.columns || Object.keys(rows[0] || {}), meta: [] };
      run();
    }).catch((e) => {
      store[id] = { status: 'error', data: [], meta: [], message: String(e) };
      run();
    });
  };

  const data = (id) => {
    if (calcs[id]) {
      const c = calcs[id];
      const ins = c.inputs.map((i) => data(i));
      const bad = ins.find((d) => d.status !== 'ok');
      if (bad) return { status: bad.status, data: [], meta: [] };
      if (!c.cache || c.cache.src.some((s, k) => s !== ins[k].data)) {
        c.cache = { src: ins.map((d) => d.data), out: c.fn(...ins.map((d) => d.data)) };
      }
      return { status: 'ok', data: c.cache.out, meta: [] };
    }
    load(id);
    return store[id];
  };

  window.dash = {
    data,
    onData(fn) { listeners.push(fn); try { fn(); } catch (e) { console.error('[tracker]', e); } },
    calc(id, spec) { calcs[id] = { inputs: spec.inputs || [], fn: spec.fn }; },
    loader() {},
    params: () => Object.assign({}, params),
    setParams(p) { params = Object.assign({}, params, p); run(); },
    resetParams() { params = Object.assign({}, defaults); run(); },
    colors: ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)',
             'var(--series-5)', 'var(--series-6)', 'var(--series-7)', 'var(--series-8)'],
    setLink() {},
    refresh() {},
  };
  // Redraw on width changes only (height changes come from the app resizing the iframe to the page height)
  let rt, lastW = window.innerWidth;
  window.addEventListener('resize', () => {
    if (window.innerWidth === lastW) return;
    lastW = window.innerWidth;
    clearTimeout(rt); rt = setTimeout(run, 150);
  });

  // ── Embedding in the React app ─────────────────────────────────────────────────────────────────────
  const root = document.documentElement;
  const embedded = window.parent && window.parent !== window;
  let host = null;                                   // the app's window when same origin, else null
  try { if (embedded && window.parent.document) host = window.parent; } catch (e) { host = null; }

  // Theme: follow the app's toggle (class "light" on the app's <html>; dark when absent). Standalone or
  // cross-origin: no data-theme attribute, so theme.css follows prefers-color-scheme. Charts resolve colours
  // when drawn, so a theme change redraws them.
  if (host) {
    const appRoot = host.document.documentElement;
    const sync = () => {
      const t = appRoot.classList.contains('light') ? 'light' : 'dark';
      if (root.dataset.theme !== t) { root.dataset.theme = t; run(); }
    };
    sync();
    new MutationObserver(sync).observe(appRoot, { attributes: true, attributeFilter: ['class'] });
  } else if (window.matchMedia) {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    if (mq.addEventListener) mq.addEventListener('change', run);
  }

  // Height: post the content height to the app so it can size the iframe and keep one scrolling area.
  // Contract: window.parent.postMessage({ type: 'tracker-height', height: <CSS px, integer> }, '*'),
  // sent on load, on resize and whenever the content size changes (ResizeObserver), only when it changed.
  if (embedded) {
    let lastH = 0, raf = 0;
    const post = () => {
      raf = 0;
      const b = document.body;
      if (!b) return;
      const h = Math.ceil(b.getBoundingClientRect().height);
      if (!h || h === lastH) return;
      lastH = h;
      try { window.parent.postMessage({ type: 'tracker-height', height: h }, '*'); } catch (e) { /* ignore */ }
    };
    const req = () => { if (!raf) raf = requestAnimationFrame(post); };
    window.addEventListener('load', req);
    window.addEventListener('resize', req);
    const watch = () => { req(); if ('ResizeObserver' in window) new ResizeObserver(req).observe(document.body); };
    if (document.body) watch(); else document.addEventListener('DOMContentLoaded', watch);
  }

  // Sticky context bar: when the app sizes the iframe to its content, the app (not the iframe) scrolls, so
  // position: sticky inside the page never engages. Publish how far the iframe's top has scrolled above the
  // visible part of the app's scroll container as --kt-sticky-top; the page uses it as the bar's sticky offset.
  if (host && window.frameElement) {
    const fe = window.frameElement;
    let raf = 0, last = -1;
    const upd = () => {
      raf = 0;
      let clip = 0;
      for (let el = fe.parentElement; el && el !== host.document.documentElement; el = el.parentElement) {
        const oy = host.getComputedStyle(el).overflowY;
        if (oy === 'auto' || oy === 'scroll' || oy === 'hidden' || oy === 'clip') clip = Math.max(clip, el.getBoundingClientRect().top);
      }
      const off = Math.max(0, Math.round(clip - fe.getBoundingClientRect().top - (fe.clientTop || 0)));
      if (off !== last) { last = off; root.style.setProperty('--kt-sticky-top', off + 'px'); }
    };
    const req = () => { if (!raf) raf = requestAnimationFrame(upd); };
    host.addEventListener('scroll', req, { capture: true, passive: true });
    host.addEventListener('resize', req);
    window.addEventListener('resize', req);
    req();
  }
})();
