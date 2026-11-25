// A farm saved online (backend /farms, Supabase): the farm diary and the daily farm crop runs. A farm is saved only
// when its owner ticks the consent box; the server keeps its outline, name and diary under an anonymous id, and the
// private key stays in this browser (a backup file can carry it to another device).
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { API_BASE } from '../api/queries'

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const fd = iso => { if (!iso) return ''; const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number); return `${d} ${MON[m - 1]} ${y}` }
const today = () => new Date().toISOString().slice(0, 10)
const btn = { background: 'var(--bg-elevated)', color: 'var(--accent-text)', border: '1px solid var(--info-border)', borderRadius: 8, padding: '5px 10px',
              fontWeight: 600, cursor: 'pointer', minHeight: 32, fontSize: 12.5 }
const btnPrimary = { ...btn, background: 'var(--btn-primary)', color: '#fff', border: 0 }
const inp = { background: 'var(--select-bg)', color: 'var(--heading)', border: '1px solid var(--border-primary)', borderRadius: 6, padding: '5px 7px', fontSize: 13, width: '100%' }
const lbl = { fontSize: 12, color: 'var(--text-meta)' }
const card = { border: '1px solid var(--border-primary)', borderRadius: 10, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 }

async function api(path, { method = 'GET', key, body } = {}) {
  const r = await fetch(`${API_BASE}/farms${path}`, { method, headers: { ...(key ? { 'X-Farm-Key': key } : {}), ...(body ? { 'Content-Type': 'application/json' } : {}) },
                                                     body: body ? JSON.stringify(body) : undefined })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) {
    const e = new Error(j.detail ?? `HTTP ${r.status}`)
    e.status = r.status
    throw e
  }
  return j
}
export const useFarmSchema = enabled => useQuery({ queryKey: ['farm-schema'], enabled, staleTime: 60 * 60_000, retry: 1, queryFn: () => api('/status') })

export function downloadBackup(farm) {
  const blob = new Blob([JSON.stringify({ cai_farm_backup: 1, id: farm.online.id, key: farm.online.key, name: farm.name }, null, 1)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${(farm.name || 'farm').replace(/[^\w.-]+/g, '_')}_key.json`
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// a backup file -> the farm as saved online (its outline and name) with its key, for this browser's list
export async function restoreBackup(j) {
  const got = await api(`/${encodeURIComponent(j.id)}`, { key: j.key })
  return { name: got.farm.name, geometry: got.farm.geometry, online: { id: j.id, key: j.key } }
}

function summary(e, schema) {
  const p = e.payload ?? {}
  const crops = schema?.crops ?? {}
  switch (e.entry_type) {
    case 'sowing': return `${crops[p.crop] ?? p.crop}${p.variety_note ? ` (${p.variety_note})` : ''}${p.area_ha ? `, ${p.area_ha} ha` : ''}`
    case 'irrigation': return `${p.mm} mm${p.note ? `: ${p.note}` : ''}`
    case 'fertiliser': return [p.product, p.n_kg_ha != null ? `${p.n_kg_ha} kg N/ha` : null, p.p_kg_ha != null ? `${p.p_kg_ha} kg P/ha` : null, p.note].filter(Boolean).join(', ')
    case 'pest_disease': return `${p.what} (${p.severity})${p.note ? `: ${p.note}` : ''}`
    case 'crop_stage': return p.stage
    case 'rainfall': return `${p.mm} mm (${p.measured_by})`
    case 'harvest': return [p.yield_t_ha != null ? `${p.yield_t_ha} t/ha` : null, p.area_ha ? `${p.area_ha} ha` : null, p.note].filter(Boolean).join(', ') || 'harvested'
    case 'cost': return `${p.item}: ${p.amount}${p.currency ? ` ${p.currency}` : ''}`
    default: return p.text ?? p.note ?? ''
  }
}

function EntryForm({ schema, onAdd, busy }) {
  const types = schema.entry_types
  const [t, setT] = useState('sowing')
  const [date, setDate] = useState(today())
  const [vals, setVals] = useState({})
  const fields = types[t]?.fields ?? {}
  const submit = e => {
    e.preventDefault()
    const payload = Object.fromEntries(Object.entries(vals).filter(([k, v]) => k in fields && v !== ''))
    onAdd({ entry_type: t, date, payload }).then(ok => { if (ok) setVals({}) })
  }
  return (
    <form onSubmit={submit} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8, alignItems: 'end' }}>
      <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>What</span>
        <select value={t} onChange={e => { setT(e.target.value); setVals({}) }} style={inp}>
          {Object.entries(types).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select></label>
      <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Date</span>
        <input type="date" value={date} onChange={e => setDate(e.target.value)} required style={inp}/></label>
      {Object.entries(fields).map(([k, f]) => (
        <label key={k} style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <span style={lbl}>{k.replace(/_/g, ' ').replace('kg ha', 'kg/ha').replace(/^n /, 'N ').replace(/^p /, 'P ')}{f.required ? '' : ' (optional)'}</span>
          {f.kind === 'choice'
            ? <select value={vals[k] ?? ''} required={f.required} onChange={e => setVals(v => ({ ...v, [k]: e.target.value }))} style={inp}>
                <option value="">Choose</option>
                {f.choices.map(c => <option key={c} value={c}>{k === 'crop' ? schema.crops[c] ?? c : c}</option>)}</select>
            : <input type={f.kind === 'number' ? 'number' : 'text'} step="any" value={vals[k] ?? ''} required={f.required}
                     onChange={e => setVals(v => ({ ...v, [k]: e.target.value }))} style={inp}/>}
        </label>
      ))}
      <div><button type="submit" disabled={busy} style={btnPrimary}>{busy ? 'Saving...' : 'Add to diary'}</button></div>
    </form>
  )
}

function Season({ s, schema }) {
  if (!s) return <p style={{ margin: 0, fontSize: 13 }}>Record this season&apos;s sowing in the diary to start the daily crop runs for this farm.</p>
  const n = s.nitrogen.reduce((t, x) => t + x.kg_ha, 0), irr = s.irrigation.reduce((t, x) => t + x.mm, 0)
  return (
    <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5 }}>
      This season: <strong>{schema.crops[s.crop] ?? s.crop}</strong> sown {fd(s.sowing_date)}
      {s.irrigation.length ? `; ${s.irrigation.length} irrigation${s.irrigation.length > 1 ? 's' : ''} (${Math.round(irr)} mm)` : ''}
      {s.nitrogen.length ? `; ${Math.round(n)} kg N/ha` : ''}{s.harvested ? '; harvested' : ''}.
    </p>
  )
}

export default function FarmOnline({ farm, country, onLinked, Simulation }) {
  const qc = useQueryClient()
  const on = farm.online
  const schemaQ = useFarmSchema(true)
  const schema = schemaQ.data
  const q = useQuery({ queryKey: ['farm', on?.id], enabled: !!on, staleTime: 5 * 60_000, retry: (n, e) => e?.status !== 404 && n < 1,
                       queryFn: () => api(`/${encodeURIComponent(on.id)}`, { key: on.key }) })
  const [consent, setConsent] = useState(false)
  const [crop, setCrop] = useState('maize_early')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const refresh = () => qc.invalidateQueries({ queryKey: ['farm', on?.id] })
  const run = async (fn, ok) => {
    setBusy(true); setMsg(null)
    try { const r = await fn(); if (ok) setMsg({ text: ok }); return r ?? true } catch (e) { setMsg({ bad: true, text: e.status === 503 ? 'Farm storage is not set up on the server yet.' : String(e.message ?? e) }); return false } finally { setBusy(false) }
  }

  if (!on) {
    return (
      <section aria-label="Save this farm online" style={card}>
        <div style={{ fontWeight: 700, color: 'var(--heading)', fontSize: 14 }}>Farm diary and daily crop runs</div>
        <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5 }}>
          Save this farm online to keep a diary (sowing, irrigation, fertiliser, harvest...) and get a daily crop run for the farm: the
          crop models grow your crop from your own sowing date, in the farm&apos;s soil and this season&apos;s weather and forecast.
        </p>
        {schema && !schema.storage?.permanent && (
          <p style={{ margin: 0, fontSize: 12.5, color: 'var(--caution-text)' }}>This server keeps saved farms only until its next restart.</p>
        )}
        <label style={{ display: 'flex', flexDirection: 'column', gap: 3, maxWidth: 260 }}><span style={lbl}>Main crop</span>
          <select value={crop} onChange={e => setCrop(e.target.value)} style={inp}>
            {Object.entries(schema?.crops ?? { maize_early: 'Early-maturing maize' }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 13, lineHeight: 1.45 }}>
          <input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} style={{ marginTop: 3 }}/>
          <span>I agree that this farm&apos;s outline, name and diary are stored on the project&apos;s server (ILRI, Supabase) to run the crop
            models for it. The farm is anonymous: a private key kept in this browser opens it, and deleting it online removes everything.</span>
        </label>
        <div><button type="button" style={btnPrimary} disabled={!consent || busy}
                     onClick={() => run(async () => {
                       const r = await api('', { method: 'POST', body: { name: farm.name, geometry: farm.geometry, crop, country, simulate: true, consent: true } })
                       onLinked({ id: r.id, key: r.key })
                     })}>{busy ? 'Saving...' : 'Save online'}</button></div>
        {msg && <p role={msg.bad ? 'alert' : 'status'} style={{ margin: 0, fontSize: 13, color: msg.bad ? 'var(--bad-text)' : 'var(--ok-text)' }}>{msg.text}</p>}
      </section>
    )
  }

  const d = q.data
  return (
    <section aria-label="Farm diary" style={card}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontWeight: 700, color: 'var(--heading)', fontSize: 14, flex: 1 }}>Farm diary and daily crop runs</span>
        <span style={{ ...lbl, color: 'var(--ok-text)' }}>Saved online</span>
      </div>
      {q.isLoading && <p style={lbl}>Loading the diary...</p>}
      {q.error?.status === 404 && (
        <>
          <p style={{ margin: 0, fontSize: 13, color: 'var(--caution-text)' }}>The online copy of this farm was not found (deleted, or the key does not match).</p>
          <div><button type="button" style={btn} onClick={() => onLinked(null)}>Keep it in this browser only</button></div>
        </>
      )}
      {q.error && q.error.status !== 404 && <p style={{ margin: 0, fontSize: 13, color: 'var(--bad-text)' }}>The diary could not be loaded: {q.error.message}</p>}
      {d && schema && (
        <>
          <Season s={d.season} schema={schema}/>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
            <input type="checkbox" checked={!!d.farm.simulate} disabled={busy}
                   onChange={e => run(() => api(`/${on.id}/edit`, { method: 'POST', key: on.key, body: { patch: { simulate: e.target.checked } } }).then(refresh))}/>
            Run the crop models for this farm every day (results after the next daily update, which starts at 19:30 East Africa Time)
          </label>
          {Simulation && <Simulation sim={d.simulation} season={d.season} schema={schema}/>}
          <div style={{ fontWeight: 600, color: 'var(--heading)', fontSize: 13, marginTop: 4 }}>Diary</div>
          {!d.diary.length && <p style={lbl}>No entries yet.</p>}
          {d.diary.length > 0 && (
            <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 4 }}>
              {[...d.diary].reverse().map(e => (
                <li key={e.id} style={{ display: 'flex', gap: 8, fontSize: 13, lineHeight: 1.45, alignItems: 'baseline' }}>
                  <span style={{ minWidth: 86, color: 'var(--text-meta)' }}>{fd(e.entry_date)}</span>
                  <span style={{ flex: 1 }}><strong style={{ color: 'var(--heading)' }}>{schema.entry_types[e.entry_type]?.label ?? e.entry_type}:</strong> {summary(e, schema)}</span>
                  <button type="button" aria-label="Delete this entry" style={{ ...btn, minHeight: 24, padding: '1px 7px' }} disabled={busy}
                          onClick={() => run(() => api(`/${on.id}/diary/${e.id}`, { method: 'DELETE', key: on.key }).then(refresh))}>X</button>
                </li>
              ))}
            </ul>
          )}
          <EntryForm schema={schema} busy={busy}
                     onAdd={entry => run(() => api(`/${on.id}/diary`, { method: 'POST', key: on.key, body: entry }).then(refresh), 'Added to the diary.')}/>
        </>
      )}
      {msg && <p role={msg.bad ? 'alert' : 'status'} style={{ margin: 0, fontSize: 13, color: msg.bad ? 'var(--bad-text)' : 'var(--ok-text)' }}>{msg.text}</p>}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', borderTop: '1px solid var(--border-primary)', paddingTop: 8 }}>
        <button type="button" style={btn} onClick={() => downloadBackup(farm)}>Download the farm&apos;s key</button>
        <button type="button" style={{ ...btn, color: 'var(--warn-text)' }} disabled={busy}
                onClick={() => { if (window.confirm('Delete the online copy of this farm, with its diary and crop runs? The outline stays in this browser.'))
                  run(() => api(`/${on.id}`, { method: 'DELETE', key: on.key }).then(() => onLinked(null))) }}>Delete online copy</button>
      </div>
      <p style={{ margin: 0, ...lbl, lineHeight: 1.5 }}>
        The key that opens this farm online is kept in this browser only. Download it to open the farm on another device (upload the file
        in My farms), and keep it private: anyone with the file can read and change the diary.
      </p>
    </section>
  )
}
