// Crop health for a farm from Sentinel-2 (lib/sentinel2.js, loaded only when asked for): the newest clear view with
// NDVI, EVI and NDMI over the farm, an NDVI map of the farm, and NDVI in the same weeks of the past five years.
// Downloads go straight from the browser to the public archive on AWS; nothing about the farm is sent elsewhere.
import { useEffect, useRef, useState } from 'react'

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const fd = iso => { const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number); return `${d} ${MON[m - 1]} ${y}` }
const daysAgo = iso => Math.round((Date.now() - new Date(`${iso}T12:00:00Z`)) / 86400000)
const f2 = v => (v == null ? 'n/a' : v.toFixed(2))
const btn = { background: 'var(--bg-elevated)', color: 'var(--accent-text)', border: '1px solid var(--info-border)', borderRadius: 8, padding: '5px 10px',
              fontWeight: 600, cursor: 'pointer', minHeight: 32, fontSize: 12.5 }
const lbl = { fontSize: 12, color: 'var(--text-meta)' }

export const ndviWord = v => (v < 0.2 ? 'bare soil or very sparse cover' : v < 0.35 ? 'sparse or young vegetation' : v < 0.5 ? 'moderate green cover'
                              : v < 0.7 ? 'dense green cover' : 'very dense green cover')
const ndmiWord = v => (v < 0 ? 'low (dry vegetation or bare soil)' : v < 0.2 ? 'moderate' : 'high')

// results per farm outline, kept for the visit (a second look costs no download)
const cache = new Map()
const keyOf = farm => JSON.stringify(farm.geometry)

function Row({ k, v, note }) {
  return (
    <div style={{ display: 'flex', gap: 8, fontSize: 13, lineHeight: 1.45 }}>
      <span style={{ flex: 1, color: 'var(--text-meta)' }}>{k}</span>
      <span style={{ fontWeight: 600, color: 'var(--heading)', textAlign: 'right' }}>{v}{note ? <span style={{ fontWeight: 400, color: 'var(--text-meta)' }}> {note}</span> : null}</span>
    </div>
  )
}

function Legend({ ramp }) {
  const stops = ramp.map(([v, c]) => `rgb(${c.join(',')}) ${v * 100}%`).join(', ')
  return (
    <div aria-label="NDVI colours" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <div style={{ height: 10, borderRadius: 3, background: `linear-gradient(90deg, ${stops})` }}/>
      <div style={{ display: 'flex', justifyContent: 'space-between', ...lbl, fontSize: 11 }}>
        <span>0 bare</span><span>0.5</span><span>1 dense green</span>
      </div>
      <div style={{ ...lbl, fontSize: 11 }}>Grey: cloud or shadow in this view</div>
    </div>
  )
}

function Comparison({ now, past }) {
  const got = past.filter(p => !p.none && p.ndvi)
  if (!got.length) return <p style={{ margin: 0, fontSize: 13 }}>No clear view of the farm in the same weeks of the past five years.</p>
  const lower = got.filter(p => now > p.ndvi.mean).length
  const s = [...got.map(p => p.ndvi.mean)].sort((a, b) => a - b)
  const med = s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2
  const diff = now - med
  const verdict = lower === got.length ? `Greener than in all ${got.length} past years with a clear view at this time.`
    : lower === 0 ? `Less green than in all ${got.length} past years with a clear view at this time.`
    : `Greener than in ${lower} of ${got.length} past years with a clear view at this time.`
  const unusual = diff <= -0.1 && lower <= 1
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {past.map(p => (
        <Row key={p.year} k={p.none ? `${p.year}` : `${p.year} (${fd(p.date).replace(/ \d{4}$/, '')})`}
             v={p.none ? 'no clear view' : `NDVI ${f2(p.ndvi.mean)}`}/>
      ))}
      <Row k="This season" v={`NDVI ${f2(now)}`} note={`(${diff >= 0 ? '+' : ''}${f2(diff)} against the past years' median)`}/>
      <p style={{ margin: '4px 0 0', fontSize: 13, lineHeight: 1.5, color: unusual ? 'var(--warn-text)' : 'var(--text-body)' }}>
        {verdict}{unusual ? ' This is a possible vegetation anomaly. The satellite cannot tell its cause (a dry spell, late sowing, an early harvest, pests or a different crop): check in the field.' : ''}
      </p>
      <p style={{ margin: 0, ...lbl, lineHeight: 1.5 }}>The past years may have had another crop, fallow or a different sowing date on this land.</p>
    </div>
  )
}

export default function FarmSatellite({ farm, onImage }) {
  const key = keyOf(farm)
  const [st, setSt] = useState(() => cache.get(key) ?? {})
  const [busy, setBusy] = useState(null)       // 'latest' | 'past' | null
  const [msg, setMsg] = useState(null)
  const [showMap, setShowMap] = useState(true)
  const [ramp, setRamp] = useState(null)
  const abort = useRef(null)
  useEffect(() => {
    setSt(cache.get(key) ?? {}); setMsg(null); setBusy(null)
    return () => abort.current?.abort()
  }, [key])
  useEffect(() => { onImage(showMap && st.latest?.image ? st.latest.image : null) }, [st.latest, showMap, onImage])
  useEffect(() => () => onImage(null), [onImage])
  const save = patch => setSt(s => { const n = { ...s, ...patch }; cache.set(key, n); return n })

  async function check() {
    abort.current?.abort()
    const ac = new AbortController(); abort.current = ac
    setBusy('latest'); setMsg('Looking for the newest clear view of the farm...')
    try {
      const s2 = await import('../lib/sentinel2')
      setRamp(s2.NDVI_RAMP)
      const r = await s2.latestHealth(farm.geometry, farm.bounds, { signal: ac.signal,
        progress: p => setMsg(`Checking clouds over the farm in Sentinel-2 views: ${p.checked + 1} of ${p.total}...`) })
      save({ latest: r, past: null }); setMsg(null)
    } catch (e) {
      if (e?.name !== 'AbortError') setMsg(`The satellite data could not be read: ${e.message ?? e}. Try again later.`)
    } finally { if (abort.current === ac) setBusy(null) }
  }
  async function compare() {
    abort.current?.abort()
    const ac = new AbortController(); abort.current = ac
    setBusy('past'); setMsg('Looking for clear views in the same weeks of the past five years...')
    try {
      const s2 = await import('../lib/sentinel2')
      const past = await s2.pastYears(farm.geometry, farm.bounds, st.latest.date, { signal: ac.signal,
        progress: p => setMsg(`Past years: ${p.done} of ${p.total} done...`) })
      save({ past }); setMsg(null)
    } catch (e) {
      if (e?.name !== 'AbortError') setMsg(`The past years could not be read: ${e.message ?? e}. Try again later.`)
    } finally { if (abort.current === ac) setBusy(null) }
  }
  useEffect(() => { if (st.latest && !ramp) import('../lib/sentinel2').then(m => setRamp(m.NDVI_RAMP)) }, [st.latest, ramp])

  const L = st.latest
  const big = farm.ha > 2000
  return (
    <section aria-label="Crop health from satellite" style={{ border: '1px solid var(--border-primary)', borderRadius: 10, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ fontWeight: 700, color: 'var(--heading)', fontSize: 14 }}>Crop health from satellite (Sentinel-2, 10 m)</div>
      {!L && !busy && (
        <>
          <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5 }}>
            How green the farm is in the newest Sentinel-2 view without clouds over it, mapped on the farm, and how that compares with
            the same weeks of past years. This reads the farm itself, not the forecast cell.
          </p>
          <div><button type="button" style={btn} onClick={check}>Check crop health (downloads up to {big ? '30' : '8'} MB)</button></div>
        </>
      )}
      {msg && <p role="status" style={{ margin: 0, fontSize: 13, color: busy ? 'var(--accent-text)' : 'var(--bad-text)' }}>{msg}</p>}
      {busy && <div><button type="button" style={btn} onClick={() => { abort.current?.abort(); setBusy(null); setMsg(null) }}>Stop</button></div>}
      {L?.none && (
        <>
          <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5 }}>
            <strong>Insufficient data:</strong> clouds covered the farm in every Sentinel-2 view from {fd(L.from)} to {fd(L.to)}
            ({L.tried.length} views checked).
          </p>
          <div><button type="button" style={btn} onClick={check} disabled={!!busy}>Check again</button></div>
        </>
      )}
      {L && !L.none && (
        <>
          <Row k="Newest clear view" v={fd(L.date)} note={`(${daysAgo(L.date)} days ago; ${Math.round(L.clear * 100)}% of the farm clear)`}/>
          <Row k="NDVI (greenness), farm mean" v={f2(L.ndvi?.mean)} note={L.ndvi ? `(${f2(L.ndvi.p10)}-${f2(L.ndvi.p90)} across the farm)` : ''}/>
          {L.ndvi && <p style={{ margin: 0, fontSize: 13 }}>Reads as {ndviWord(L.ndvi.mean)}.</p>}
          {L.evi && <Row k="EVI (greenness, less saturated in dense crops)" v={f2(L.evi.mean)}/>}
          {L.ndmi && <Row k="NDMI (water in the canopy)" v={f2(L.ndmi.mean)} note={`(${ndmiWord(L.ndmi.mean)})`}/>}
          {L.low != null && (
            <Row k="Part of the farm much less green than the rest" v={`${Math.round(L.low * 100)}%`}
                 note="(NDVI under 75% of the farm's median)"/>
          )}
          {L.low != null && L.low >= 0.15 && (
            <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5, color: 'var(--warn-text)' }}>
              Patches of the farm are much less green than the rest (brown or yellow on the map). They may be bare, later sown, or stressed: worth a look in the field.
            </p>
          )}
          {daysAgo(L.date) > 20 && <p style={{ margin: 0, fontSize: 12.5, color: 'var(--caution-text)' }}>This view is {daysAgo(L.date)} days old: clouds hid the farm since.</p>}
          {L.image && (
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
              <input type="checkbox" checked={showMap} onChange={e => setShowMap(e.target.checked)}/> Show NDVI on the map
            </label>
          )}
          {L.image && showMap && ramp && <Legend ramp={ramp}/>}
          {!st.past && busy !== 'past' && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <button type="button" style={btn} onClick={compare} disabled={!!busy}>Compare with the past 5 years (up to {big ? '60' : '20'} MB)</button>
              <button type="button" style={btn} onClick={check} disabled={!!busy}>Check again</button>
            </div>
          )}
          {st.past && L.ndvi && <Comparison now={L.ndvi.mean} past={st.past}/>}
        </>
      )}
      <p style={{ margin: 0, ...lbl, lineHeight: 1.5 }}>
        Copernicus Sentinel-2 L2A, from the Earth Search catalogue (Element 84) on AWS Open Data; clouds from the scene classification.
        Greenness shows the state of the vegetation, not its cause, and cannot by itself tell a pest, a disease or a lack of fertiliser.
      </p>
    </section>
  )
}
