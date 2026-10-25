/* Local stand-in for the online dashboard's `dash` API, so frontend/tracker/page.html runs inside the
   platform from CSV/JSON files in ./data (written by scripts/build_tracker_page.py).
   Implements what the page uses: data, onData, calc, params/setParams/resetParams, colors, setLink, refresh. */
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
  let rt;
  window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(run, 150); });
})();
