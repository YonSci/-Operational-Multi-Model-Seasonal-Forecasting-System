// Field reports (backend /feedback/*): farmers, extension staff and researchers report sowing, rain, emergence,
// crop stage, water stress, harvest and whether an advisory helped. Reports stay "unverified" until a reviewer
// checks them; contact details are kept only with consent and shown only to reviewers.
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { API_BASE } from '../api/queries'

const CROPS = [['', 'Not stated'], ['maize_early', 'Early-maturing maize'], ['maize_medium', 'Medium-maturing maize'], ['sorghum', 'Sorghum'], ['bean', 'Dry bean']]
const ROLES = [['farmer', 'Farmer'], ['extension', 'Extension officer'], ['researcher', 'Researcher'], ['other', 'Other']]
const FIELD_LABELS = { sown_on: 'Sowing date', variety_note: 'Variety', area_ha: 'Area (ha)', observed_on: 'Date observed', rain_mm: 'Rain (mm)',
  measured_by: 'Measured by', established_pct: 'Plants established (%)', note: 'Note', stage: 'Stage', severity: 'Severity',
  harvested_on: 'Harvest date', yield_t_ha: 'Yield (t/ha)', advisory_id: 'Advisory reference', understandable: 'Was it understandable?',
  feasible: 'Was it feasible?', followed: 'Did you follow it?', comment: 'Comment' }
const inp = { background: 'var(--select-bg)', color: 'var(--heading)', border: '1px solid var(--border-primary)', borderRadius: 6, padding: '5px 7px', fontSize: 13, width: '100%' }
const lbl = { fontSize: 12, color: 'var(--text-meta)' }
const btn = { background: 'var(--btn-primary)', color: '#fff', border: 0, borderRadius: 8, padding: '7px 14px', fontWeight: 600, cursor: 'pointer', minHeight: 36 }
const btn2 = { background: 'var(--bg-elevated)', color: 'var(--accent-text)', border: '1px solid var(--info-border)', borderRadius: 8, padding: '6px 12px', fontWeight: 600, cursor: 'pointer', minHeight: 34 }

function Field({ name, spec, value, onChange }) {
  const id = 'fr-' + name
  const label = FIELD_LABELS[name] ?? name
  let control
  if (spec.kind === 'choice') {
    control = (<select id={id} value={value ?? ''} onChange={e => onChange(e.target.value)} style={inp}>
      <option value="">Choose...</option>{spec.choices.map(c => <option key={c} value={c}>{c}</option>)}</select>)
  } else if (spec.kind === 'date') {
    control = <input id={id} type="date" value={value ?? ''} onChange={e => onChange(e.target.value)} style={inp}/>
  } else if (spec.kind === 'number') {
    control = <input id={id} type="number" inputMode="decimal" min={spec.limits?.[0]} max={spec.limits?.[1]} step="any" value={value ?? ''} onChange={e => onChange(e.target.value)} style={inp}/>
  } else {
    control = <input id={id} type="text" maxLength={spec.limits ?? 300} value={value ?? ''} onChange={e => onChange(e.target.value)} style={inp}/>
  }
  return <label htmlFor={id} style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>{label}{spec.required ? ' *' : ''}</span>{control}</label>
}

function ReportForm({ place, context, onSent }) {
  const { data: st } = useQuery({ queryKey: ['feedback-status'], staleTime: 10 * 60_000,
                                  queryFn: async () => { const r = await fetch(`${API_BASE}/feedback/status`); if (!r.ok) throw new Error('status'); return r.json() } })
  const [type, setType] = useState('sowing')
  const [payload, setPayload] = useState({})
  const [crop, setCrop] = useState('')
  const [role, setRole] = useState('farmer')
  const [contact, setContact] = useState('')
  const [consent, setConsent] = useState(false)
  const [photo, setPhoto] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  useEffect(() => { setPayload({}) }, [type])
  const spec = st?.types?.[type]
  async function submit(e) {
    e.preventDefault()
    setBusy(true); setErr(null)
    const report = { report_type: type, payload, crop: crop || null, reporter_role: role, consent, reporter_contact: consent ? contact : '',
                     lat: place.lat, lon: place.lon, place_name: place.name, country: context.country, season: context.season }
    const fd = new FormData()
    fd.append('report', JSON.stringify(report))
    if (photo) fd.append('photo', photo)
    try {
      const r = await fetch(`${API_BASE}/feedback/report`, { method: 'POST', body: fd })
      const j = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(j.detail ?? `HTTP ${r.status}`)
      onSent({ ...j, report })
    } catch (ex) {
      setErr(String(ex.message ?? ex))
    } finally {
      setBusy(false)
    }
  }
  if (!st) return <p style={lbl}>Loading the form...</p>
  return (
    <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5 }}>Report for <strong>{place.name}</strong> ({place.lat.toFixed(3)}, {place.lon.toFixed(3)}). Pick another place on the map to report elsewhere.</p>
      {!st.storage.permanent && <p style={{ margin: 0, padding: '6px 10px', borderRadius: 6, background: 'var(--caution-bg)', color: 'var(--caution-text)', fontSize: 12.5 }}>{st.storage.note}</p>}
      <label htmlFor="fr-type" style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>What are you reporting?</span>
        <select id="fr-type" value={type} onChange={e => setType(e.target.value)} style={inp}>
          {Object.entries(st.types).map(([k, t]) => <option key={k} value={k}>{t.label}</option>)}
        </select>
      </label>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 8 }}>
        {spec && Object.entries(spec.fields).map(([n, sp]) => <Field key={n} name={n} spec={sp} value={payload[n]} onChange={v => setPayload(p => ({ ...p, [n]: v }))}/>)}
        <label htmlFor="fr-crop" style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Crop</span>
          <select id="fr-crop" value={crop} onChange={e => setCrop(e.target.value)} style={inp}>{CROPS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label htmlFor="fr-role" style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>You are</span>
          <select id="fr-role" value={role} onChange={e => setRole(e.target.value)} style={inp}>{ROLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
      </div>
      <label htmlFor="fr-photo" style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Photo (optional; JPEG, PNG or WebP, up to 5 MB)</span>
        <input id="fr-photo" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" onChange={e => setPhoto(e.target.files?.[0] ?? null)}/></label>
      <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 12.5, lineHeight: 1.45 }}>
        <input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/>
        <span>Reviewers may contact me about this report. My contact is shown only to reviewers, never published.</span></label>
      {consent && <input aria-label="Phone or email" placeholder="Phone or email" value={contact} onChange={e => setContact(e.target.value)} maxLength={120} style={inp}/>}
      {err && <p role="alert" style={{ margin: 0, color: 'var(--bad-text)', fontSize: 13 }}>{err}</p>}
      <div><button type="submit" disabled={busy} style={{ ...btn, opacity: busy ? 0.6 : 1 }}>{busy ? 'Sending...' : 'Send the report'}</button></div>
    </form>
  )
}

function Review() {
  const [token, setToken] = useState(() => { try { return sessionStorage.getItem('fr-token') ?? '' } catch { return '' } })
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState(null)
  const [filter, setFilter] = useState('unverified')
  async function load() {
    setErr(null)
    try { sessionStorage.setItem('fr-token', token) } catch { /* private window */ }
    const r = await fetch(`${API_BASE}/feedback/reports?status=${filter}`, { headers: { 'X-Admin-Token': token } })
    if (!r.ok) { setErr(r.status === 401 ? 'The reviewer token is not right.' : `HTTP ${r.status}`); setRows(null); return }
    setRows((await r.json()).reports)
  }
  async function mark(id, verification) {
    const r = await fetch(`${API_BASE}/feedback/reports/${id}/review`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Admin-Token': token },
                                                                         body: JSON.stringify({ verification, reviewer: 'dashboard reviewer' }) })
    if (r.ok) load(); else setErr(`HTTP ${r.status}`)
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <label htmlFor="fr-token" style={{ display: 'flex', flexDirection: 'column', gap: 3, flex: '1 1 160px' }}><span style={lbl}>Reviewer token</span>
          <input id="fr-token" type="password" value={token} onChange={e => setToken(e.target.value)} style={inp}/></label>
        <label htmlFor="fr-filter" style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Show</span>
          <select id="fr-filter" value={filter} onChange={e => setFilter(e.target.value)} style={inp}>
            <option value="unverified">Unverified</option><option value="verified">Verified</option><option value="rejected">Rejected</option></select></label>
        <button type="button" style={btn2} onClick={load}>Load reports</button>
      </div>
      {err && <p role="alert" style={{ margin: 0, color: 'var(--bad-text)', fontSize: 13 }}>{err}</p>}
      {rows && !rows.length && <p style={lbl}>No reports here.</p>}
      {rows?.map(r => (
        <div key={r.id} style={{ border: '1px solid var(--border-primary)', borderRadius: 8, padding: '8px 10px', fontSize: 13, lineHeight: 1.5 }}>
          <div style={{ fontWeight: 600, color: 'var(--heading)' }}>{r.report_type} at {r.place_name ?? `${r.lat}, ${r.lon}`} <span style={{ ...lbl, fontWeight: 400 }}>({r.evidence_kind}, {String(r.created_at).slice(0, 10)})</span></div>
          <div>{Object.entries(r.payload ?? {}).map(([k, v]) => `${FIELD_LABELS[k] ?? k}: ${v}`).join('; ')}{r.crop ? `; crop: ${r.crop}` : ''}</div>
          {r.reporter_contact && <div style={lbl}>Contact (consented): {r.reporter_contact}</div>}
          {r.photo_url && <a href={r.photo_url} target="_blank" rel="noreferrer">Open the photo</a>}
          {r.photo_triage && <div style={{ ...lbl, marginTop: 4 }}>AI description (not a diagnosis): {r.photo_triage.visible_crop}; {r.photo_triage.growth_stage}; {(r.photo_triage.visible_signs ?? []).join(', ')}. {r.photo_triage.note}</div>}
          <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
            {r.verification !== 'verified' && <button type="button" style={btn2} onClick={() => mark(r.id, 'verified')}>Mark verified</button>}
            {r.verification !== 'rejected' && <button type="button" style={btn2} onClick={() => mark(r.id, 'rejected')}>Reject</button>}
          </div>
        </div>
      ))}
    </div>
  )
}

export default function FieldReportPanel({ place, context, onClose, onUseSowing }) {
  const [tab, setTab] = useState('report')
  const [sent, setSent] = useState(null)
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const tb = a => ({ background: a ? 'var(--nav-active-bg)' : 'transparent', color: a ? 'var(--accent-text)' : 'var(--text-body)', border: '1px solid ' + (a ? 'var(--info-border)' : 'transparent'),
                     borderRadius: 8, padding: '6px 10px', fontSize: 13.5, fontWeight: 600, cursor: 'pointer', minHeight: 36 })
  return (
    <aside role="dialog" aria-modal="false" aria-labelledby="fr-title"
           style={{ position: 'fixed', top: 0, right: 0, bottom: 0, width: 'min(460px, 100vw)', zIndex: 3000, display: 'flex', flexDirection: 'column',
                    background: 'var(--bg-surface)', borderLeft: '1px solid var(--border-primary)', boxShadow: '-8px 0 24px rgba(0,0,0,0.25)', color: 'var(--text-body)', fontSize: 14 }}>
      <header style={{ padding: '14px 16px 8px', borderBottom: '1px solid var(--border-primary)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <h2 id="fr-title" style={{ margin: 0, fontSize: 17, color: 'var(--heading)', flex: 1 }}>Report from the field</h2>
          <button type="button" onClick={onClose} aria-label="Close field reports" style={{ ...tb(false), border: '1px solid var(--border-primary)', minWidth: 36 }}>X</button>
        </div>
        <nav role="tablist" aria-label="Field reports" style={{ display: 'flex', gap: 4, marginTop: 10 }}>
          <button type="button" role="tab" aria-selected={tab === 'report'} onClick={() => setTab('report')} style={tb(tab === 'report')}>Send a report</button>
          <button type="button" role="tab" aria-selected={tab === 'review'} onClick={() => setTab('review')} style={tb(tab === 'review')}>Review (reviewers)</button>
        </nav>
      </header>
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px' }} role="tabpanel">
        {tab === 'report' && (sent ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, lineHeight: 1.55 }}>
            <p style={{ margin: 0 }}><strong>Thank you: the report was received.</strong> It is marked <em>{sent.verification}</em> until a reviewer checks it; it counts as a {sent.evidence_kind}.</p>
            {!sent.storage?.permanent && <p style={{ margin: 0, fontSize: 12.5, color: 'var(--caution-text)' }}>{sent.storage?.note}</p>}
            {sent.report.report_type === 'sowing' && sent.report.payload.sown_on && (
              <button type="button" style={btn2} onClick={() => onUseSowing({ crop: sent.report.crop || 'maize_early', sowing_date: sent.report.payload.sown_on })}>
                Use this sowing in the advisory card
              </button>
            )}
            <div><button type="button" style={btn2} onClick={() => setSent(null)}>Send another report</button></div>
          </div>
        ) : <ReportForm place={place} context={context} onSent={setSent}/>)}
        {tab === 'review' && <Review/>}
      </div>
    </aside>
  )
}
