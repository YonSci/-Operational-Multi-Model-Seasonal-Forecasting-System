import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

// Gridded regional crop outlook (crop_engine/grid.py): AquaCrop on every 0.25° maize cell of the eastern Kenya Short
// Rains counties, and the counties as the maize-area-weighted mean of their cells.
const DATA = 'tracker/data/crop/grid.json'
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const fmtDate = iso => { if (!iso) return '—'; const [, m, d] = iso.split('-').map(Number); return `${d} ${MONTHS[m - 1]}` }
const pct = v => v == null ? '—' : `${Math.round(v * 100)}%`
const fmtT = v => v == null ? '—' : v < 0.05 ? '0' : v.toFixed(1)
const ha = v => v == null ? '—' : v >= 10000 ? `${Math.round(v / 1000)}k` : `${Math.round(v / 100) * 100}`

// percent of normal: brown below, a neutral grey at normal, blue-green above (bins of the expected yield)
const PCT_BINS = [
  { max: 60, c: '#8c510a', l: 'below 60%' }, { max: 80, c: '#bf812d', l: '60–80%' }, { max: 95, c: '#dfc27d', l: '80–95%' },
  { max: 105, c: '#a3a9b0', l: '95–105%' }, { max: 120, c: '#80cdc1', l: '105–120%' }, { max: 140, c: '#35978f', l: '120–140%' },
  { max: Infinity, c: '#01665e', l: 'above 140%' }]
// a chance, 0–1: one hue, light to dark
const P_BINS = [
  { max: 0.2, c: '#fdd9b5', l: 'under 20%' }, { max: 0.35, c: '#fdae6b', l: '20–35%' }, { max: 0.5, c: '#f16913', l: '35–50%' },
  { max: 0.65, c: '#c4440a', l: '50–65%' }, { max: Infinity, c: '#7f2704', l: '65% or more' }]
const LAYERS = {
  pct: { label: 'Yield vs normal', get: c => c.pct_normal, bins: PCT_BINS,
         sub: 'Expected (mean) yield of the forecast members as a percent of the cell’s average in the simulated past seasons.' },
  below: { label: 'Chance below normal', get: c => c.p_below_normal, bins: P_BINS,
           sub: 'Share of members below the lowest third of the simulated past seasons (1993–2016). A third is the usual chance.' },
  fail: { label: 'Chance of crop failure', get: c => c.p_failure, bins: P_BINS,
          sub: 'Share of members with no crop or a yield below the failure threshold.' },
}
const colorOf = (v, bins) => v == null ? null : bins.find(b => v < b.max)?.c ?? bins[bins.length - 1].c

function ringsOf(g) {
  return g.type === 'Polygon' ? g.coordinates : g.type === 'MultiPolygon' ? g.coordinates.flat() : []
}

function Legend({ bins, none }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 12px', fontSize: 12.5, color: 'var(--text-meta)', marginTop: 8 }}>
      {bins.map(b => (
        <span key={b.l} style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
          <span style={{ width: 12, height: 12, borderRadius: 2, background: b.c, display: 'inline-block' }}/>{b.l}
        </span>
      ))}
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
        <span style={{ width: 12, height: 12, borderRadius: 2, border: '1px dashed var(--text-meta)', display: 'inline-block' }}/>{none}
      </span>
    </div>
  )
}

function GridMap({ data, layer, site, onHover, hover }) {
  const L = LAYERS[layer]
  const geo = useMemo(() => {
    const pts = Object.values(data.outlines).flatMap(g => ringsOf(g).flat())
    const lons = pts.map(p => p[0]).concat(data.cells.map(c => c.lon))
    const lats = pts.map(p => p[1]).concat(data.cells.map(c => c.lat))
    const x0 = Math.min(...lons) - 0.15, x1 = Math.max(...lons) + 0.15, y0 = Math.min(...lats) - 0.15, y1 = Math.max(...lats) + 0.15
    const k = 100                                                       // px per degree (near the equator: no correction)
    const X = lon => (lon - x0) * k, Y = lat => (y1 - lat) * k
    const path = g => ringsOf(g).map(r => 'M' + r.map(p => `${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join('L') + 'Z').join('')
    return { W: (x1 - x0) * k, H: (y1 - y0) * k, X, Y, k, paths: Object.entries(data.outlines).map(([n, g]) => [n, path(g)]),
             labels: Object.entries(data.outlines).map(([n, g]) => {
               const r = [...ringsOf(g)].sort((a, b) => b.length - a.length)[0] ?? []
               return [n, X(r.reduce((s, p) => s + p[0], 0) / r.length), Y(r.reduce((s, p) => s + p[1], 0) / r.length)]
             }) }
  }, [data.outlines, data.cells])
  const half = data.meta.cell_deg / 2
  return (
    <svg viewBox={`0 0 ${geo.W} ${geo.H}`} role="img" style={{ width: '100%', maxWidth: 460, height: 'auto', display: 'block' }}
         aria-label={`Map of ${L.label.toLowerCase()} for each 0.25° cell; the table below has the county values`}
         onMouseLeave={() => onHover(null)}>
      {data.cells.map(c => {
        const v = L.get(c)
        const col = colorOf(v, L.bins)
        const on = hover?.id === c.id
        return (
          <rect key={c.id} x={geo.X(c.lon - half) + 1} y={geo.Y(c.lat + half) + 1} width={geo.k * 2 * half - 2} height={geo.k * 2 * half - 2}
                rx={2} fill={col ?? 'transparent'} stroke={on ? 'var(--heading)' : col ? 'none' : 'var(--text-meta)'}
                strokeWidth={on ? 2 : 1} strokeDasharray={col || on ? undefined : '3 2'}
                onMouseEnter={() => onHover(c)} onClick={() => onHover(c)} style={{ cursor: 'pointer' }}/>
        )
      })}
      {geo.paths.map(([n, d]) => <path key={n} d={d} fill="none" stroke="var(--heading)" strokeOpacity={0.75} strokeWidth={1.2} pointerEvents="none"/>)}
      {geo.labels.map(([n, x, y]) => (
        <text key={n} x={x} y={y} textAnchor="middle" fontSize={11} fontWeight={600} fill="var(--heading)" pointerEvents="none"
              style={{ paintOrder: 'stroke', stroke: 'var(--bg-surface)', strokeWidth: 3 }}>{n}</text>
      ))}
      {site && Number.isFinite(+site.lat) && (
        <g pointerEvents="none">
          <circle cx={geo.X(+site.lon)} cy={geo.Y(+site.lat)} r={5} fill="none" stroke="var(--heading)" strokeWidth={2}/>
          <circle cx={geo.X(+site.lon)} cy={geo.Y(+site.lat)} r={1.8} fill="var(--heading)"/>
        </g>
      )}
    </svg>
  )
}

function CellCard({ c, thr }) {
  if (!c) return (
    <p style={{ fontSize: 13.5, color: 'var(--text-meta)', margin: 0, lineHeight: 1.5 }}>
      Hover over or tap a cell for its values.
    </p>
  )
  const rows = [
    ['Yield vs normal', c.pct_normal == null ? '—' : `${c.pct_normal}%`],
    ['Expected yield', `${fmtT(c.mean_t_ha)} t/ha (normal ${fmtT(c.normal_mean_t_ha)})`],
    ['8 in 10 members', `${fmtT(c.p10_t_ha)}–${fmtT(c.p90_t_ha)} t/ha`],
    ['Below / above normal', c.p_below_normal == null ? 'no normal range' : `${pct(c.p_below_normal)} / ${pct(c.p_above_normal)}`],
    ['Crop failure', `${pct(c.p_failure)} (normal ${pct(c.normal_p_failure)}; below ${thr} t/ha)`],
    ['Sowing', `${fmtDate(c.sowing_median)} (median)${c.not_sown ? `; no sowing chance in ${pct(c.not_sown)}` : ''}`],
  ]
  return (
    <div>
      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--heading)' }}>
        {Object.keys(c.weights).join(' / ')} · {c.lat.toFixed(3)}, {c.lon.toFixed(3)}
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--text-meta)', margin: '2px 0 6px' }}>{ha(c.area_ha)} ha of rainfed maize (MapSPAM 2020)</div>
      <dl style={{ margin: 0, fontSize: 13.5, color: 'var(--text-body)', lineHeight: 1.5 }}>
        {rows.map(([k, v]) => (
          <div key={k} style={{ display: 'flex', gap: 8 }}>
            <dt style={{ flex: '0 0 140px', color: 'var(--text-meta)' }}>{k}</dt><dd style={{ margin: 0 }}>{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

const rTxt = v => v == null ? '—' : (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(2)

export default function CropRegionalPanel({ site }) {
  const q = useQuery({ queryKey: ['crop-grid'], staleTime: 30 * 60_000, retry: false,
                       queryFn: () => fetch(DATA).then(r => r.ok ? r.json() : null).catch(() => null) })
  const [layer, setLayer] = useState('pct')
  const [hover, setHover] = useState(null)
  const [model, setModel] = useState('aquacrop')
  const raw = q.data
  if (!raw?.cells?.length) return null                                  // not made yet: the panel stays hidden
  const hasD = !!raw.cells_dssat?.length
  const useD = hasD && model === 'dssat'                                 // DSSAT: its own cells and counties, same map
  const d = useD ? { ...raw, cells: raw.cells_dssat, counties: raw.counties_dssat ?? [] } : raw
  const m = d.meta
  const pick = k => { setModel(k); setHover(null) }
  const counties = [...d.counties].sort((a, b) => b.area_ha - a.area_ha)
  return (
    <section aria-label="Regional maize outlook" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-primary)', borderRadius: 12,
                                                          padding: '16px 18px', minWidth: 0 }}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 style={{ fontSize: 16, fontWeight: 600, color: 'var(--heading)', margin: 0 }}>Maize across the eastern Kenya counties</h3>
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--caution-text)', background: 'var(--caution-bg)', borderRadius: 999, padding: '2px 9px' }}>Pilot</span>
      </div>
      <p style={{ fontSize: 13.5, color: 'var(--text-meta)', margin: '4px 0 0', lineHeight: 1.5, maxWidth: 860 }}>
        {useD ? 'DSSAT (CERES-Maize)' : 'AquaCrop'} on every 0.25° cell (about 28 km) that grows rainfed maize: {m.variety_label.toLowerCase()} sown at the {m.rule_label} of
        each cell, in the {m.members} members of {m.model_label}, observations to {fmtDate(m.obs_end)}. Each is compared with the same crop in the
        observed weather of {m.years[0]}–{m.years[1]}{hasD ? ', grown by the same model' : ''}. A county is the mean of its cells, weighted by their maize area.
      </p>
      {hasD && (
        <div role="radiogroup" aria-label="Crop model" className="flex flex-wrap items-center gap-2" style={{ margin: '12px 0 0' }}>
          <span style={{ fontSize: 13, color: 'var(--text-meta)' }}>Crop model</span>
          {[['aquacrop', 'AquaCrop'], ['dssat', 'DSSAT']].map(([k, lab]) => (
            <button key={k} type="button" role="radio" aria-checked={model === k} onClick={() => pick(k)}
                    style={{ fontSize: 13.5, fontWeight: 600, borderRadius: 999, padding: '5px 12px', minHeight: 32, cursor: 'pointer',
                             border: '1px solid var(--border-primary)',
                             background: model === k ? 'var(--nav-active-bg)' : 'transparent', color: model === k ? 'var(--heading)' : 'var(--text-body)' }}>
              {lab}
            </button>
          ))}
        </div>
      )}
      <div role="radiogroup" aria-label="Map layer" className="flex flex-wrap gap-2" style={{ margin: '12px 0 4px' }}>
        {Object.entries(LAYERS).map(([k, L]) => (
          <button key={k} type="button" role="radio" aria-checked={layer === k} onClick={() => setLayer(k)}
                  style={{ fontSize: 13.5, fontWeight: 600, borderRadius: 999, padding: '5px 12px', minHeight: 32, cursor: 'pointer',
                           border: '1px solid var(--border-primary)',
                           background: layer === k ? 'var(--nav-active-bg)' : 'transparent', color: layer === k ? 'var(--heading)' : 'var(--text-body)' }}>
            {L.label}
          </button>
        ))}
      </div>
      <p style={{ fontSize: 13, color: 'var(--text-meta)', margin: '0 0 8px' }}>{LAYERS[layer].sub}</p>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,460px)_minmax(0,1fr)]" style={{ alignItems: 'start' }}>
        <div style={{ minWidth: 0 }}>
          <GridMap data={d} layer={layer} site={site} onHover={setHover} hover={hover}/>
          <Legend bins={LAYERS[layer].bins} none={layer === 'below' ? 'no normal range (a third or more of past seasons failed)' : 'no value'}/>
        </div>
        <div style={{ minWidth: 0, border: '1px solid var(--border-primary)', borderRadius: 8, padding: '10px 12px' }}>
          <CellCard c={hover} thr={m.failure_t_ha}/>
        </div>
      </div>

      <div style={{ overflowX: 'auto', marginTop: 14 }}>
        <table className="crop-table wrap" style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr><th>County</th><th>Maize area</th><th>Yield vs normal</th><th>8 in 10 members</th><th>Below normal</th><th>Above normal</th>
                <th>Maize area failing</th><th>Past seasons vs reported yields</th></tr>
          </thead>
          <tbody>
            {counties.map(c => {
              const v = c.verification ?? {}
              return (
                <tr key={c.name}>
                  <td style={{ fontWeight: 600, color: 'var(--heading)' }}>{c.name}</td>
                  <td>{ha(c.area_ha)} ha, {c.n_cells} cell{c.n_cells > 1 ? 's' : ''}</td>
                  <td>{c.pct_normal == null ? '—' : `${c.pct_normal}%`} <span style={{ color: 'var(--text-meta)' }}>({fmtT(c.mean_t_ha)} vs {fmtT(c.normal_mean_t_ha)} t/ha)</span></td>
                  <td>{fmtT(c.p10_t_ha)}–{fmtT(c.p90_t_ha)} t/ha</td>
                  <td>{pct(c.p_below_normal)}</td>
                  <td>{pct(c.p_above_normal)}</td>
                  <td>{pct(c.failed_area_share_median)} <span style={{ color: 'var(--text-meta)' }}>(normal {pct(c.normal_failed_area_share_median)})</span></td>
                  <td>{v.r_rank != null ? <>r {rTxt(v.r_rank)} over {v.n_years} seasons{v.site_r_rank != null ? <><br/><span style={{ color: 'var(--text-meta)' }}>the site’s cell alone: r {rTxt(v.site_r_rank)}</span></> : ''}</>
                       : v.n_years != null ? `${v.n_years} seasons: too few` : '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p style={{ fontSize: 13, color: 'var(--text-meta)', margin: '8px 0 0', lineHeight: 1.5, maxWidth: 860 }}>
        Maize area failing: the median, over the members, of the share of the county’s maize area with a failed crop. Past seasons vs reported
        yields: rank correlation of the county’s simulated past seasons with its Short Rains maize yields reported by HarvestStat Africa
        (1 is a perfect ranking, 0 none): how well the model ranks good and bad seasons, not a check of this forecast.
      </p>
      <details style={{ marginTop: 8 }}>
        <summary style={{ cursor: 'pointer', fontSize: 14, color: 'var(--accent-text)' }}>Every cell as a table, and the caveats</summary>
        <div style={{ overflowX: 'auto', marginTop: 8, maxHeight: 360, overflowY: 'auto' }}>
          <table className="crop-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr><th>Cell</th><th>County</th><th>Maize area</th><th>Yield vs normal</th><th>Below / above normal</th><th>Crop failure (normal)</th><th>Sowing</th></tr></thead>
            <tbody>
              {d.cells.map(c => (
                <tr key={c.id}>
                  <td>{c.lat.toFixed(3)}, {c.lon.toFixed(3)}</td><td>{c.county}</td><td>{ha(c.area_ha)} ha</td>
                  <td>{c.pct_normal == null ? '—' : `${c.pct_normal}%`}</td>
                  <td>{c.p_below_normal == null ? '—' : `${pct(c.p_below_normal)} / ${pct(c.p_above_normal)}`}</td>
                  <td>{pct(c.p_failure)} ({pct(c.normal_p_failure)})</td><td>{fmtDate(c.sowing_median)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul style={{ fontSize: 13.5, color: 'var(--text-meta)', lineHeight: 1.55, margin: '10px 0 0', paddingLeft: 18, listStyle: 'disc' }}>
          {(m.caveats ?? []).map(c => <li key={c}>{c}</li>)}
        </ul>
      </details>
    </section>
  )
}
