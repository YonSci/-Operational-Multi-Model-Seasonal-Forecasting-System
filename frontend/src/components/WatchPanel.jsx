// Saved watches ("Did the advice change?") and the decision calendar (backend /watches/*). A watch is anonymous:
// its id and private key live in this browser (localStorage); the server keeps only the key's hash.
import { useEffect, useState } from 'react'
import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { API_BASE } from '../api/queries'

const STORE_KEY = 'cai-watches'
export const loadWatches = () => { try { return JSON.parse(localStorage.getItem(STORE_KEY) ?? '[]') } catch { return [] } }
const saveWatches = list => { try { localStorage.setItem(STORE_KEY, JSON.stringify(list)) } catch { /* storage blocked */ } }

const VERDICT = { unchanged: ['No change', 'var(--ok-text)', 'var(--ok-bg)'], forecast_changed: ['Forecast changed', 'var(--accent-text)', 'var(--info-bg)'],
                  advice_changed: ['Advice changed', 'var(--warn-text)', 'var(--caution-bg)'], needs_review: ['Needs review', 'var(--warn-text)', 'var(--caution-bg)'],
                  onset_detected: ['Planting onset', 'var(--accent-text)', 'var(--info-bg)'], dry_spell: ['Dry spell', 'var(--warn-text)', 'var(--caution-bg)'],
                  outlook_changed: ['Rain outlook changed', 'var(--accent-text)', 'var(--info-bg)'] }
export const ALERT_STATUSES = ['advice_changed', 'needs_review', 'forecast_changed', 'onset_detected', 'dry_spell', 'outlook_changed']
const TRACKING = 'rain_tracking'
const DECISIONS = [['sowing', 'When to sow'], ['crop_choice', 'Which crop or maturity class'], ['establishment', 'Establishment after sowing'],
                   ['replanting', 'Replanting'], ['water', 'Water management']]
const CROPS = [['maize_early', 'Early-maturing maize'], ['maize_medium', 'Medium-maturing maize'], ['sorghum', 'Sorghum'], ['bean', 'Dry bean']]
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const fd = iso => { if (!iso) return ''; const [, m, d] = String(iso).slice(0, 10).split('-').map(Number); return `${d} ${MON[m - 1]}` }
const inp = { background: 'var(--select-bg)', color: 'var(--heading)', border: '1px solid var(--border-primary)', borderRadius: 6, padding: '5px 7px', fontSize: 13, width: '100%' }
const lbl = { fontSize: 12, color: 'var(--text-meta)' }
const btn2 = { background: 'var(--bg-elevated)', color: 'var(--accent-text)', border: '1px solid var(--info-border)', borderRadius: 8, padding: '5px 10px', fontWeight: 600, cursor: 'pointer', minHeight: 32, fontSize: 12.5 }

async function checkWatch(w) {
  const r = await fetch(`${API_BASE}/watches/${w.id}`, { headers: { 'X-Watch-Key': w.key } })
  if (r.status === 404) return { gone: true }
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

// statuses of the saved watches, for the panel and the button's badge
export function useWatchStatuses(list) {
  return useQueries({ queries: list.map(w => ({ queryKey: ['watch', w.id], queryFn: () => checkWatch(w), staleTime: 15 * 60_000, retry: 1 })) })
}

function Calendar({ w }) {
  const q = new URLSearchParams({ lat: w.lat, lon: w.lon, season: w.season, model: w.model, crop: w.crop, planted: w.planted, sowing_date: w.sowing_date ?? '' })
  const { data, isLoading } = useQuery({ queryKey: ['calendar', q.toString()], staleTime: 30 * 60_000,
                                         queryFn: async () => { const r = await fetch(`${API_BASE}/watches/calendar/for?${q}`); if (!r.ok) throw new Error('calendar'); return r.json() } })
  if (isLoading) return <p style={lbl}>Loading the calendar...</p>
  if (!data) return null
  return (
    <ol style={{ margin: '6px 0 0', paddingLeft: 0, listStyle: 'none', fontSize: 13 }}>
      {data.events.map((e, i) => (
        <li key={i} style={{ display: 'flex', gap: 10, padding: '4px 0', borderBottom: '1px solid var(--border-primary)', opacity: e.past ? 0.6 : 1 }}>
          <span style={{ flex: '0 0 92px', fontWeight: 600, color: 'var(--heading)' }}>{e.date ? fd(e.date) : 'When due'}</span>
          <span style={{ minWidth: 0 }}>{e.what}{e.range && e.range[0] && e.range[1] && e.range[0] !== e.range[1] ? ` (8 in 10: ${fd(e.range[0])} to ${fd(e.range[1])})` : ''}
            {e.note && <span style={{ ...lbl, display: 'block' }}>{e.note}</span>}</span>
        </li>
      ))}
    </ol>
  )
}

function WatchCard({ w, q, onRemove, onOpenAdvisory }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(null)
  const d = q.data
  const v = VERDICT[d?.status] ?? ['Checking...', 'var(--text-meta)', 'transparent']
  async function ack() {
    await fetch(`${API_BASE}/watches/${w.id}/acknowledge`, { method: 'POST', headers: { 'X-Watch-Key': w.key } })
    qc.invalidateQueries({ queryKey: ['watch', w.id] })
  }
  async function del() {
    await fetch(`${API_BASE}/watches/${w.id}`, { method: 'DELETE', headers: { 'X-Watch-Key': w.key } })
    onRemove(w.id)
  }
  return (
    <div style={{ border: '1px solid var(--border-primary)', borderRadius: 8, padding: '8px 10px', fontSize: 13 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <strong style={{ color: 'var(--heading)', flex: 1, minWidth: 0 }}>{w.name || w.place_name}</strong>
        <span style={{ padding: '2px 8px', borderRadius: 10, fontSize: 12, fontWeight: 600, color: v[1], background: v[2] }}>{d?.gone ? 'Removed' : v[0]}</span>
      </div>
      <div style={lbl}>{w.decision === TRACKING
        ? `Rainfall tracking at ${w.place_name}: planting onset, dry spells of ${w.thresholds?.dry_days ?? 10} days or more, and changes in the next days' rain`
        : <>{CROPS.find(c => c[0] === w.crop)?.[1] ?? w.crop}, {DECISIONS.find(x => x[0] === w.decision)?.[1] ?? w.decision}{w.sowing_date ? `, sown ${fd(w.sowing_date)}` : ''}</>}</div>
      {q.isError && <p style={{ margin: '4px 0 0', color: 'var(--bad-text)' }}>Could not check this watch.</p>}
      {d && !d.gone && <p style={{ margin: '6px 0 0' }}>{d.headline}</p>}
      {d?.changes?.length > 0 && (
        <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{d.changes.map((c, i) => <li key={i}><strong>{c.what}:</strong> {c.detail}</li>)}</ul>
      )}
      {d && !d.gone && <div style={{ ...lbl, marginTop: 4 }}>Compared with {new Date(d.baseline_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })} (when you last acknowledged).</div>}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
        {d?.changes?.length > 0 && <button type="button" style={btn2} onClick={ack}>Acknowledge</button>}
        {w.decision !== TRACKING && <button type="button" style={btn2} onClick={() => setOpen(o => o === 'cal' ? null : 'cal')} aria-expanded={open === 'cal'}>Calendar</button>}
        {w.season === 'short_rains' && w.decision !== TRACKING && <button type="button" style={btn2} onClick={() => onOpenAdvisory(w)}>Open the advice</button>}
        <button type="button" style={btn2} onClick={del}>Delete</button>
      </div>
      {open === 'cal' && <Calendar w={w}/>}
    </div>
  )
}

export default function WatchPanel({ place, season, model, onClose, onOpenAdvisory, list, setList, tracking }) {
  const statuses = useWatchStatuses(list)
  const [form, setForm] = useState({ name: '', crop: 'maize_early', planted: 'no', sowing_date: '', decision: 'sowing', objective: 'maturity' })
  const [dryDays, setDryDays] = useState(10)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [note, setNote] = useState(null)
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const set = p => setForm(f => ({ ...f, ...p }))
  async function create(e) {
    e.preventDefault()
    setBusy(true); setErr(null)
    try {
      const spec = tracking
        ? { name: form.name || `Rain at ${tracking.name}`, lat: tracking.lat, lon: tracking.lon, place_name: tracking.name, season: 'short_rains',
            model: 'tracker', decision: TRACKING, thresholds: { dry_days: Number(dryDays) || 10 } }
        : { ...form, name: form.name || place.name, lat: place.lat, lon: place.lon, place_name: place.name, season, model,
            sowing_date: form.planted === 'yes' ? (form.sowing_date || null) : null }
      const r = await fetch(`${API_BASE}/watches`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(spec) })
      const j = await r.json()
      if (!r.ok) throw new Error(j.detail ?? `HTTP ${r.status}`)
      const next = [...list, { ...spec, id: j.id, key: j.key }]
      setList(next); saveWatches(next)
      setNote(j.storage?.permanent ? null : j.storage?.note)
    } catch (ex) { setErr(String(ex.message ?? ex)) } finally { setBusy(false) }
  }
  const remove = id => { const next = list.filter(w => w.id !== id); setList(next); saveWatches(next) }
  return (
    <aside role="dialog" aria-modal="false" aria-labelledby="watch-title"
           style={{ position: 'fixed', top: 0, right: 0, bottom: 0, width: 'min(460px, 100vw)', zIndex: 3000, display: 'flex', flexDirection: 'column',
                    background: 'var(--bg-surface)', borderLeft: '1px solid var(--border-primary)', boxShadow: '-8px 0 24px rgba(0,0,0,0.25)', color: 'var(--text-body)', fontSize: 14 }}>
      <header style={{ padding: '14px 16px 10px', borderBottom: '1px solid var(--border-primary)', display: 'flex', gap: 8, alignItems: 'center' }}>
        <h2 id="watch-title" style={{ margin: 0, fontSize: 17, color: 'var(--heading)', flex: 1 }}>My watches</h2>
        <button type="button" onClick={onClose} aria-label="Close my watches" style={{ ...btn2, minWidth: 36 }}>X</button>
      </header>
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5 }}>A watch remembers a place, crop and decision, and tells you when the forecast or the advice has changed
          enough to matter since you last looked. Watches are kept in this browser.</p>
        {list.map((w, i) => <WatchCard key={w.id} w={w} q={statuses[i] ?? {}} onRemove={remove} onOpenAdvisory={onOpenAdvisory}/>)}
        {!list.length && <p style={lbl}>No watches yet.</p>}
        {tracking && (
          <form onSubmit={create} style={{ borderTop: '1px solid var(--border-primary)', paddingTop: 10, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 8, alignItems: 'end' }}>
            <div style={{ gridColumn: '1 / -1', fontWeight: 600, color: 'var(--heading)' }}>Watch the rain at {tracking.name}</div>
            <p style={{ gridColumn: '1 / -1', margin: 0, fontSize: 12.5, lineHeight: 1.5 }}>Tells you when more satellite products show a planting onset, when a
              dry spell builds, and when the weather models&apos; rain for the next days changes.</p>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Name (optional)</span>
              <input value={form.name} onChange={e => set({ name: e.target.value })} maxLength={60} style={inp}/></label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Dry spell alert after (days without 1 mm)</span>
              <input type="number" min={3} max={30} value={dryDays} onChange={e => setDryDays(e.target.value)} style={inp}/></label>
            <div><button type="submit" disabled={busy} style={{ background: 'var(--btn-primary)', color: '#fff', border: 0, borderRadius: 8, padding: '7px 14px', fontWeight: 600, cursor: 'pointer', minHeight: 36 }}>
              {busy ? 'Saving...' : 'Watch this site'}</button></div>
          </form>
        )}
        {!tracking && (
        <form onSubmit={create} style={{ borderTop: '1px solid var(--border-primary)', paddingTop: 10, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 8, alignItems: 'end' }}>
          <div style={{ gridColumn: '1 / -1', fontWeight: 600, color: 'var(--heading)' }}>Watch {place.name}</div>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Name (optional)</span>
            <input value={form.name} onChange={e => set({ name: e.target.value })} maxLength={60} style={inp}/></label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Crop</span>
            <select value={form.crop} onChange={e => set({ crop: e.target.value })} style={inp}>{CROPS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Field</span>
            <select value={form.planted} onChange={e => set({ planted: e.target.value, decision: e.target.value === 'yes' ? 'establishment' : 'sowing' })} style={inp}>
              <option value="no">Not yet sown</option><option value="yes">Sown</option><option value="unknown">Not stated</option></select></label>
          {form.planted === 'yes' && <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Sowing date</span>
            <input type="date" value={form.sowing_date} onChange={e => set({ sowing_date: e.target.value })} style={inp}/></label>}
          <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Decision</span>
            <select value={form.decision} onChange={e => set({ decision: e.target.value })} style={inp}>{DECISIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
          <div><button type="submit" disabled={busy} style={{ background: 'var(--btn-primary)', color: '#fff', border: 0, borderRadius: 8, padding: '7px 14px', fontWeight: 600, cursor: 'pointer', minHeight: 36 }}>
            {busy ? 'Saving...' : 'Watch this place'}</button></div>
        </form>
        )}
        {err && <p role="alert" style={{ margin: 0, color: 'var(--bad-text)', fontSize: 13 }}>{err}</p>}
        {note && <p style={{ margin: 0, fontSize: 12.5, color: 'var(--caution-text)' }}>{note}</p>}
      </div>
    </aside>
  )
}
