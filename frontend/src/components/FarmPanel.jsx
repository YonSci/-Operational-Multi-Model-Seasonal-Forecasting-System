// My farms: draw a farm on the map or upload its boundary (GeoJSON or KML), then see the 0.25-degree forecast cells
// it overlaps and each cell's published products (static files under tracker/data, so it works without the
// backend). Farms are kept in this browser only (localStorage); the boundary is never sent anywhere.
import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { cellKey, downloadFarm, readFarmFile } from '../lib/farmGeo'
import FarmSatellite from './FarmSatellite'
import { RULES, STATUS_LABEL, farmStatus } from '../lib/farmStatus'

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const fd = iso => { if (!iso) return 'n/a'; const [, m, d] = String(iso).slice(0, 10).split('-').map(Number); return `${d} ${MON[m - 1]}` }
const num = v => (v === '' || v == null || Number.isNaN(Number(v)) ? null : Number(v))
const pct = v => (v == null ? 'n/a' : `${Math.round(v * 100)}%`)
const mm = v => (v == null ? 'n/a' : `${Math.round(v)} mm`)
const ha = v => (v >= 100 ? `${Math.round(v).toLocaleString()} ha` : `${v.toFixed(v >= 10 ? 1 : 2)} ha`)
const latLon = (lat, lon) => `${Math.abs(lat).toFixed(3)} ${lat >= 0 ? 'N' : 'S'}, ${Math.abs(lon).toFixed(3)} E`
const btn = { background: 'var(--bg-elevated)', color: 'var(--accent-text)', border: '1px solid var(--info-border)', borderRadius: 8, padding: '5px 10px',
              fontWeight: 600, cursor: 'pointer', minHeight: 32, fontSize: 12.5 }
const btnPrimary = { ...btn, background: 'var(--btn-primary)', color: '#fff', border: 0 }
const lbl = { fontSize: 12, color: 'var(--text-meta)' }
const card = { border: '1px solid var(--border-primary)', borderRadius: 10, padding: '10px 12px', background: 'var(--bg-surface)' }

// CSV with quoted fields (products.csv has commas inside quotes)
function parseCSV(text) {
  const rows = []
  let row = [], f = '', q = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (q) {
      if (c === '"') { if (text[i + 1] === '"') { f += '"'; i++ } else q = false } else f += c
    } else if (c === '"') q = true
    else if (c === ',') { row.push(f); f = '' }
    else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; row.push(f); rows.push(row); row = []; f = '' }
    else f += c
  }
  if (f || row.length) { row.push(f); rows.push(row) }
  const [head, ...body] = rows
  return body.filter(r => r.length === head.length).map(r => Object.fromEntries(head.map((h, i) => [h, r[i]])))
}
const getText = path => fetch(path).then(r => (r.ok ? r.text() : null))
const opts = { staleTime: 30 * 60_000, retry: false }

// The published per-cell products, indexed for lookups by cell
function useCellData(enabled) {
  const grid = useQuery({ ...opts, enabled, queryKey: ['farm-grid-csv'], queryFn: async () => {
    const t = await getText('tracker/data/grid.csv')
    return t ? new Map(parseCSV(t).map(r => [cellKey(+r.lat, +r.lon), r])) : null
  } })
  // weather models (0.5-degree cells): per cell, per model, the rain to day 7 and to the last day
  const fc = useQuery({ ...opts, enabled, queryKey: ['farm-forecast-csv'], queryFn: async () => {
    const t = await getText('tracker/data/forecast.csv')
    if (!t) return null
    const by = new Map()
    for (const r of parseCSV(t)) {
      const k = `${(+r.lat).toFixed(2)},${(+r.lon).toFixed(2)}`
      if (!by.has(k)) by.set(k, new Map())
      const m = by.get(k)
      if (!m.has(r.model)) m.set(r.model, { label: r.model_label, days: [] })
      m.get(r.model).days.push({ date: r.date, cum: num(r.cum_mm) })
    }
    return by
  } })
  const crop = useQuery({ ...opts, enabled, queryKey: ['crop-grid'], queryFn: () => fetch('tracker/data/crop/grid.json').then(r => (r.ok ? r.json() : null)) })
  const products = useQuery({ ...opts, enabled, queryKey: ['farm-products-csv'], queryFn: async () => {
    const t = await getText('tracker/data/products.csv')
    return t ? Object.fromEntries(parseCSV(t).map(r => [r.id, r])) : null
  } })
  // cropland greenness per cell (scripts/veg_anomaly.py); the file may not exist yet
  const veg = useQuery({ ...opts, enabled, queryKey: ['farm-veg-csv'], queryFn: async () => {
    const t = await getText('tracker/data/veg.csv')
    return t ? new Map(parseCSV(t).map(r => [cellKey(+r.lat, +r.lon), r])) : null
  } })
  const cropIdx = useMemo(() => {
    const d = crop.data
    if (!d) return null
    return { meta: d.meta, aq: new Map((d.cells ?? []).map(c => [c.id, c])), ds: new Map((d.cells_dssat ?? []).map(c => [c.id, c])) }
  }, [crop.data])
  return { grid: grid.data, fc: fc.data, crop: cropIdx, products: products.data, veg: veg.data,
           loading: grid.isLoading || fc.isLoading || crop.isLoading || veg.isLoading }
}

const parent05 = v => (Math.floor(v * 2) / 2 + 0.25).toFixed(2)
const median = a => { const s = [...a].sort((x, y) => x - y); const n = s.length; return n ? (n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2) : null }

function Row({ k, v, note }) {
  return (
    <div style={{ display: 'flex', gap: 8, fontSize: 13, lineHeight: 1.45 }}>
      <span style={{ flex: 1, color: 'var(--text-meta)' }}>{k}</span>
      <span style={{ fontWeight: 600, color: 'var(--heading)', textAlign: 'right' }}>{v}{note ? <span style={{ fontWeight: 400, color: 'var(--text-meta)' }}> {note}</span> : null}</span>
    </div>
  )
}
const H = ({ children }) => <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent-text)', textTransform: 'uppercase', letterSpacing: '0.04em', marginTop: 8 }}>{children}</div>

function CropBlock({ name, c }) {
  if (!c) return null
  return (
    <>
      <Row k={`${name}: yield, median`} v={`${c.median_t_ha.toFixed(1)} t/ha`} note={`(normal ${c.normal_median_t_ha.toFixed(1)})`}/>
      <Row k={`${name}: mean yield`} v={`${c.pct_normal}% of normal`}/>
      <Row k={`${name}: chance of crop failure`} v={pct(c.p_failure)} note={`(normal ${pct(c.normal_p_failure)})`}/>
      <Row k={`${name}: typical sowing date`} v={fd(c.sowing_median)} note={c.not_sown ? `(${pct(c.not_sown)} of members not sown)` : ''}/>
    </>
  )
}

function CellCard({ c, i, n, data }) {
  const g = data.grid?.get(cellKey(c.lat, c.lon))
  const models = data.fc?.get(`${parent05(c.lat)},${parent05(c.lon)}`)
  const runs = models ? [...models.values()].filter(m => m.days.length) : []
  const d7 = runs.map(m => m.days[Math.min(6, m.days.length - 1)].cum).filter(v => v != null)
  const dEnd = runs.map(m => m.days[m.days.length - 1].cum).filter(v => v != null)
  const fcFrom = runs[0]?.days[0]?.date, fcTo = runs[0]?.days.at(-1)?.date
  const aq = data.crop?.aq.get(c.id), ds = data.crop?.ds.get(c.id)
  const nOnset = g ? ['chirps', 'arc2', 'tamsat', 'pdirnow', 'imerg', 'imerg_early', 'imerg_gee', 'gsmap_gee'].filter(p => g[`${p}_onset_detected`] !== undefined && g[`${p}_onset_detected`] !== '') : []
  const nDet = nOnset.filter(p => g[`${p}_onset_detected`] === '1').length
  const obsTo = data.products?.chirps?.latest_data
  const v = data.veg?.get(cellKey(c.lat, c.lon))
  return (
    <section style={card} aria-label={`Forecast cell ${i + 1}`}>
      <div style={{ fontWeight: 700, color: 'var(--heading)', fontSize: 14 }}>
        {n > 1 ? `Cell ${i + 1} of ${n}: ` : 'Forecast cell: '}{latLon(c.lat, c.lon)}
      </div>
      <div style={{ ...lbl, marginBottom: 4 }}>
        {Math.round(c.share * 100)}% of the farm ({ha(c.ha)}); the cell is about {Math.round(c.km2)} km2
        {data.crop?.aq.get(c.id) ? `, ${aq.county} County` : ''}
      </div>
      {!g && !models && !aq && !v && <p style={{ margin: 0, fontSize: 13 }}>No published products for this cell: it lies outside the Kenya forecast area.</p>}
      {g && (
        <>
          <H>Rain so far</H>
          <Row k={`Since 1 Oct (CHIRPS, to ${fd(obsTo)})`} v={mm(num(g.chirps_total_mm))} note={num(g.chirps_pct_normal) != null ? `(${Math.round(num(g.chirps_pct_normal))}% of normal)` : ''}/>
          {nOnset.length > 0 && <Row k="Satellite products showing a planting onset" v={`${nDet} of ${nOnset.length}`}/>}
        </>
      )}
      {(g?.ens_p_event_7d || runs.length > 0) && <H>Next days</H>}
      {g && num(g.ens_p_event_7d) != null && <Row k="Chance of planting rains within 7 days (ECMWF ensemble)" v={pct(num(g.ens_p_event_7d))}/>}
      {g && num(g.ens_p_onset_15d) != null && <Row k="Chance of a planting onset within 15 days" v={pct(num(g.ens_p_onset_15d))}/>}
      {d7.length > 0 && (
        <Row k={`Rain in the next 7 days (${d7.length} weather models, 0.5-degree cell, from ${fd(fcFrom)})`}
             v={`${Math.round(median(d7))} mm`} note={`(range ${Math.round(Math.min(...d7))}-${Math.round(Math.max(...d7))})`}/>
      )}
      {dEnd.length > 0 && (
        <Row k={`Rain to ${fd(fcTo)}`} v={`${Math.round(median(dEnd))} mm`} note={`(range ${Math.round(Math.min(...dEnd))}-${Math.round(Math.max(...dEnd))})`}/>
      )}
      {v && num(v.ndvi) != null && (
        <>
          <H>Cropland greenness (Sentinel-2, {fd(v.window_start)} to {fd(v.window_end)})</H>
          <Row k="NDVI of the cell's cropland" v={num(v.ndvi).toFixed(2)}
               note={num(v.base_mean) != null ? `(past years ${num(v.base_mean).toFixed(2)})` : ''}/>
          {num(v.z) != null && <Row k="Against the same weeks of past years" v={`${num(v.z) > 0 ? '+' : ''}${num(v.z).toFixed(1)} SD`}
                                    note={`(greener than in ${v.lower_years} of ${v.years})`}/>}
        </>
      )}
      {g && num(g.season_p_early) != null && (
        <>
          <H>Season: planting onset (ECMWF SEAS5 1 Oct with observed rain)</H>
          <Row k="Chance of an early onset" v={pct(num(g.season_p_early))}/>
          <Row k="Chance of a late onset" v={pct(num(g.season_p_late))}/>
          <Row k="Skill in past seasons (RPSS; above 0 beats the normal)" v={num(g.season_rpss_val) == null ? 'n/a' : num(g.season_rpss_val).toFixed(2)}/>
        </>
      )}
      {data.crop && (
        <>
          <H>Crop outlook: {data.crop.meta.variety_label}, sown at the {data.crop.meta.rule_label}</H>
          {aq || ds
            ? <><CropBlock name="AquaCrop" c={aq}/><CropBlock name="DSSAT" c={ds}/></>
            : <p style={{ margin: 0, fontSize: 13 }}>No crop outlook for this cell: the map covers cells with at least {data.crop.meta.min_ha} ha of rainfed maize.</p>}
        </>
      )}
    </section>
  )
}

const STATUS_COLOUR = { attention: ['var(--warn-text)', 'var(--caution-bg)'], watch: ['var(--caution-text)', 'var(--caution-bg)'],
                        normal: ['var(--ok-text)', 'var(--ok-bg)'], insufficient: ['var(--text-meta)', 'var(--bg-elevated)'] }
const LEVEL_WORD = { attention: 'Attention', watch: 'Watch', normal: 'Normal' }

// The farm's status from its main cell (the largest share of the farm) and its own satellite check
function StatusCard({ farm, data, sat }) {
  const c = farm.cells[0]
  if (!c || data.loading) return null
  const st = farmStatus({ grid: data.grid?.get(cellKey(c.lat, c.lon)), aq: data.crop?.aq.get(c.id), ds: data.crop?.ds.get(c.id),
                          veg: data.veg?.get(cellKey(c.lat, c.lon)), sat })
  const [fg, bg] = STATUS_COLOUR[st.status]
  return (
    <section aria-label="Farm status" style={{ ...card, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontWeight: 700, color: 'var(--heading)', fontSize: 14, flex: 1 }}>Farm status</span>
        <span style={{ background: bg, color: fg, border: `1px solid ${fg}`, borderRadius: 999, padding: '2px 10px', fontWeight: 700, fontSize: 13 }}>
          {STATUS_LABEL[st.status]}</span>
      </div>
      {st.signals.map(x => (
        <div key={x.name} style={{ display: 'flex', gap: 8, fontSize: 13, lineHeight: 1.45 }}>
          <span style={{ minWidth: 74, fontWeight: 700, color: STATUS_COLOUR[x.level][0] }}>{LEVEL_WORD[x.level]}</span>
          <span><strong style={{ color: 'var(--heading)' }}>{x.name}:</strong> {x.text}</span>
        </div>
      ))}
      <p style={{ margin: 0, ...lbl, lineHeight: 1.5 }}>
        {st.status === 'insufficient' ? 'Too few signals for this place to set a status. ' : `Based on ${st.used} signal${st.used === 1 ? '' : 's'}. `}
        {!sat?.latest && "Check the crop health below to add the farm's own satellite view. "}
        A status points to what to check; it is not a forecast of the harvest.
      </p>
      <details style={{ fontSize: 12.5, lineHeight: 1.5 }}>
        <summary style={{ cursor: 'pointer', color: 'var(--accent-text)' }}>How the status is set</summary>
        <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
          {RULES.map(([k, t]) => <li key={k}><strong>{k}:</strong> {t}</li>)}
          <li>The status is the most serious signal. With a single signal and nothing flagged, it is Insufficient data.</li>
          <li>The signals are those of the cell holding most of the farm.</li>
        </ul>
      </details>
    </section>
  )
}

function FarmDetail({ farm, country, data, onRename, onDownload, onZoom, onDelete, onImage }) {
  const [sat, setSat] = useState(null)
  const [name, setName] = useState(farm.name)
  useEffect(() => setName(farm.name), [farm.id, farm.name])
  const cells = farm.cells
  const outside = country !== 'kenya'
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 6 }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Farm name</span>
          <input value={name} maxLength={60} onChange={e => setName(e.target.value)} onBlur={() => name.trim() && name !== farm.name && onRename(name.trim())}
                 onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }}
                 style={{ background: 'var(--select-bg)', color: 'var(--heading)', border: '1px solid var(--border-primary)', borderRadius: 6, padding: '5px 7px', fontSize: 13 }}/></label>
        <Row k="Area" v={ha(farm.ha)}/>
        <Row k="Centre" v={latLon(farm.centre[1], farm.centre[0])}/>
        <p style={{ margin: '4px 0 0', fontSize: 12.5, lineHeight: 1.5 }}>
          The forecasts are made for 0.25-degree cells (about 28 km across), not for single farms.
          {cells.length === 1
            ? ` This farm lies in one cell and covers ${(100 * farm.ha / (cells[0].km2 * 100)).toPrecision(2)}% of it: the products below describe the whole cell.`
            : ` This farm spans ${cells.length} cells; each is shown on its own, because averaging their chances would not give the chance for the farm.`}
          {' '}The charts on the page now show the farm&apos;s centre.
        </p>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button type="button" style={btn} onClick={onZoom}>Zoom to farm</button>
          <button type="button" style={btn} onClick={onDownload}>Download GeoJSON</button>
          <button type="button" style={{ ...btn, color: 'var(--warn-text)' }} onClick={onDelete}>Delete</button>
        </div>
      </div>
      <StatusCard farm={farm} data={data} sat={sat}/>
      <FarmSatellite key={farm.id} farm={farm} onImage={onImage} onResult={setSat}/>
      {outside && <p style={{ margin: 0, fontSize: 13, color: 'var(--caution-text)' }}>Forecast products for farms are published for Kenya&apos;s Short Rains so far.</p>}
      {data.loading && <p style={lbl}>Loading the published products...</p>}
      {!data.loading && cells.map((c, i) => <CellCard key={c.id} c={c} i={i} n={cells.length} data={data}/>)}
      <p style={{ margin: 0, ...lbl, lineHeight: 1.5 }}>
        Kenya Short Rains 2026 products, as published on the site today. Rain so far and the next days come from the rainfall tracker; the
        season and crop outlooks from the 1 Oct ECMWF run with the latest observed rain. A cell&apos;s chances are not the chances for one field.
      </p>
    </div>
  )
}

export default function FarmPanel({ farms, selectedId, onSelect, onAdd, onUpdate, onDelete, onDraw, onZoom, country, notice, onImage, onClose }) {
  const [msg, setMsg] = useState(notice)
  useEffect(() => { if (notice) setMsg(notice) }, [notice])
  const fileRef = useRef(null)
  const sel = farms.find(f => f.id === selectedId) ?? null
  const data = useCellData(!!sel)
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  async function upload(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setMsg(null)
    try {
      const { farms: got, errors } = await readFarmFile(file)
      if (got.length) onAdd(got)
      setMsg(errors.length ? { bad: true, text: errors.join(' ') } : { text: `Added ${got.length} farm${got.length > 1 ? 's' : ''} from ${file.name}.` })
    } catch (ex) { setMsg({ bad: true, text: String(ex.message ?? ex) }) }
  }
  return (
    <aside role="dialog" aria-modal="false" aria-labelledby="farm-title"
           style={{ position: 'fixed', top: 0, right: 0, bottom: 0, width: 'min(460px, 100vw)', zIndex: 3000, display: 'flex', flexDirection: 'column',
                    background: 'var(--bg-surface)', borderLeft: '1px solid var(--border-primary)', boxShadow: '-8px 0 24px rgba(0,0,0,0.25)', color: 'var(--text-body)', fontSize: 14 }}>
      <header style={{ padding: '14px 16px 10px', borderBottom: '1px solid var(--border-primary)', display: 'flex', gap: 8, alignItems: 'center' }}>
        <h2 id="farm-title" style={{ margin: 0, fontSize: 17, color: 'var(--heading)', flex: 1 }}>My farms</h2>
        <button type="button" onClick={onClose} aria-label="Close my farms" style={{ ...btn, minWidth: 36 }}>X</button>
      </header>
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5 }}>
          Draw your farm on the map or upload its boundary, then see the forecasts and crop outlook for the area it lies in.
          Farms are kept in this browser only; the boundary is never sent anywhere. To see field edges while drawing, switch the
          map to Satellite (MAP, bottom left).
        </p>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button type="button" style={btnPrimary} onClick={onDraw}>Draw a farm on the map</button>
          <button type="button" style={btn} onClick={() => fileRef.current?.click()}>Upload GeoJSON or KML</button>
          <input ref={fileRef} type="file" accept=".geojson,.json,.kml,application/geo+json,application/vnd.google-earth.kml+xml" onChange={upload} style={{ display: 'none' }}/>
        </div>
        {msg && <p role={msg.bad ? 'alert' : 'status'} style={{ margin: 0, fontSize: 13, color: msg.bad ? 'var(--bad-text)' : 'var(--ok-text)' }}>{msg.text}</p>}
        {farms.length > 0 && (
          <div role="list" aria-label="Saved farms" style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {farms.map(f => (
              <button key={f.id} role="listitem" type="button" onClick={() => onSelect(f.id)} aria-pressed={f.id === selectedId}
                      style={{ ...btn, background: f.id === selectedId ? 'var(--btn-primary)' : 'var(--bg-elevated)', color: f.id === selectedId ? '#fff' : 'var(--accent-text)' }}>
                {f.name} <span style={{ fontWeight: 400 }}>({ha(f.ha)})</span>
              </button>
            ))}
          </div>
        )}
        {!farms.length && <p style={lbl}>No farms yet.</p>}
        {sel && (
          <FarmDetail farm={sel} country={country} data={data} onImage={onImage}
                      onRename={name => onUpdate(sel.id, { name })} onDownload={() => downloadFarm(sel)} onZoom={() => onZoom(sel.id)}
                      onDelete={() => { if (window.confirm(`Delete ${sel.name} from this browser?`)) onDelete(sel.id) }}/>
        )}
      </div>
    </aside>
  )
}
