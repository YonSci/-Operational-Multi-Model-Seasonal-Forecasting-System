// Forecast assistant: "Explain this location", "What changed?" and "Explain this map" (backend /explain/*).
// The backend computes an evidence record from the platform's data, then writes the explanation from it: the
// standard template, or Claude when the server has a key (every number Claude writes is checked against the
// evidence). This panel shows the explanation with the evidence beside it.
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { API_BASE } from '../api/queries'

export const AUDIENCES = [
  { id: 'general', label: 'General' },
  { id: 'farmer', label: 'Farmer' },
  { id: 'extension', label: 'Extension officer' },
  { id: 'technical', label: 'Technical' },
]
const TITLES = { location: 'Explain this location', changes: 'What changed?', map: 'Explain this map' }
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const fdate = iso => { if (!iso) return 'n/a'; const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number); return `${d} ${MON[m - 1]} ${y}` }
const STATUS = { estimated_from_observations: 'Estimated from observations so far', partly_observed: 'Partly within the observed period', forecast: 'Forecast' }

async function fetchExplain(req) {
  const { kind, ...params } = req
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== '').map(([k, v]) => [k, String(v)]))
  const res = await fetch(`${API_BASE}/explain/${kind}?${q}`)
  if (!res.ok) {
    let msg = `The explanation could not be made (HTTP ${res.status}).`
    try { const j = await res.json(); if (j?.detail) msg = String(j.detail) } catch { /* not JSON */ }
    throw new Error(msg)
  }
  return res.json()
}

export function useExplain(req) {
  return useQuery({
    queryKey: ['explain', req],
    queryFn: () => fetchExplain(req),
    enabled: !!req,
    staleTime: 10 * 60_000,
    retry: 1,
  })
}

const box = { background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8, padding: '10px 12px' }
const lbl = { fontSize: 12, color: 'var(--text-meta)' }

function Para({ lines }) {
  if (!lines?.length) return <p style={{ color: 'var(--text-meta)', margin: 0 }}>Nothing to add here.</p>
  return lines.map((t, i) => <p key={i} style={{ margin: '0 0 8px', lineHeight: 1.55 }}>{t}</p>)
}

function KV({ k, v }) {
  if (v == null || v === '') return null
  return (
    <div style={{ display: 'flex', gap: 10, padding: '4px 0', borderBottom: '1px solid var(--border-primary)' }}>
      <span style={{ ...lbl, flex: '0 0 42%' }}>{k}</span>
      <span style={{ fontSize: 13.5, color: 'var(--heading)', fontVariantNumeric: 'tabular-nums', minWidth: 0 }}>{v}</span>
    </div>
  )
}

const pctTriple = c => c ? Object.entries(c).map(([k, v]) => `${k} ${v}%`).join(', ') : null
const valueOf = (q, v) => q.unit === 'date' ? fdate(v) : (v == null ? null : `${v} days`)

function LocationEvidence({ ev }) {
  const run = ev.run
  return (
    <>
      <div style={box}>
        <KV k="Place" v={ev.scope.site ? `${ev.scope.site.name} (${ev.scope.site.distance_km} km from the point)` : `${ev.scope.point.lat}, ${ev.scope.point.lon}`}/>
        <KV k="Scope" v={ev.scope.description}/>
        <KV k="Season" v={`${ev.season.label} ${ev.season.year}`}/>
        <KV k="Run" v={run.model}/>
        <KV k="Initialised" v={fdate(run.initialised)}/>
        <KV k="Observations through" v={run.observations_through ? fdate(run.observations_through) : 'None (forecast only)'}/>
        <KV k="Method" v={`${run.method.label}: ${run.method.question}`}/>
        <KV k="Members" v={run.members}/>
        <KV k="Skill weight (alpha)" v={ev.skill_weight_alpha}/>
      </div>
      {['onset', 'cessation', 'lgp'].map(key => {
        const q = ev.quantities[key]
        return (
          <div key={key} style={{ ...box, marginTop: 8 }}>
            <div style={{ fontWeight: 600, color: 'var(--heading)', marginBottom: 4 }}>{q.label}</div>
            <KV k="Status" v={STATUS[q.status] ?? q.status}/>
            <KV k="Median" v={valueOf(q, q.median)}/>
            <KV k="8 in 10 members" v={q.range_80?.[0] ? `${valueOf(q, q.range_80[0])} to ${valueOf(q, q.range_80[1])}` : null}/>
            <KV k="Normal" v={valueOf(q, q.normal)}/>
            <KV k="Chances (skill-weighted)" v={pctTriple(q.chances_pct) ?? q.chances_note}/>
            <KV k="Members' own chances" v={pctTriple(q.members_chances_pct)}/>
            <KV k="Hit rate / RPSS" v={q.skill.hit_rate != null || q.skill.rpss != null ? `${q.skill.hit_rate ?? 'n/a'} / ${q.skill.rpss ?? 'n/a'} (${q.skill.period})` : null}/>
          </div>
        )
      })}
    </>
  )
}

function ChangesEvidence({ ev }) {
  return (
    <>
      <div style={box}>
        <KV k="From" v={`${ev.from_run.model} (obs. ${ev.from_run.observations_through ? fdate(ev.from_run.observations_through) : 'none'})`}/>
        <KV k="To" v={`${ev.to_run.model} (obs. ${ev.to_run.observations_through ? fdate(ev.to_run.observations_through) : 'none'})`}/>
        <KV k="Same event definition" v={ev.same_event_definition ? 'Yes' : 'No: the methods define different events'}/>
        {ev.input_changes.map((c, i) => <KV key={i} k={`Input: ${c.what}`} v={`${typeof c.from === 'string' && /^\d{4}-/.test(c.from) ? fdate(c.from) : String(c.from)} -> ${typeof c.to === 'string' && /^\d{4}-/.test(c.to) ? fdate(c.to) : String(c.to)}`}/>)}
      </div>
      {Object.entries(ev.differences).map(([key, d]) => (
        <div key={key} style={{ ...box, marginTop: 8 }}>
          <div style={{ fontWeight: 600, color: 'var(--heading)', marginBottom: 4 }}>{d.label}</div>
          <KV k="Median" v={`${valueOf(d, d.from_median) ?? 'n/a'} -> ${valueOf(d, d.to_median) ?? 'n/a'}`}/>
          <KV k="Shift" v={d.median_shift_days != null ? `${d.median_shift_days} days` : null}/>
          <KV k="Chances" v={d.chances_pct_from ? `${pctTriple(d.chances_pct_from)} -> ${pctTriple(d.chances_pct_to)}` : null}/>
        </div>
      ))}
    </>
  )
}

function MapEvidence({ ev }) {
  const d = ev.distribution
  const unit = ev.layer.display_unit
  const show = v => v == null ? 'n/a' : unit === 'date' ? fdate(v) : unit === '%' ? `${v}%` : unit === 'days' ? `${v} days` : String(v)
  return (
    <>
      <div style={box}>
        <KV k="Layer" v={ev.layer.shows}/>
        <KV k="Season" v={`${ev.season.label} ${ev.season.year}`}/>
        <KV k="Run" v={ev.run.model}/>
        <KV k="Cells with values" v={ev.cells.with_values}/>
        {d && <KV k="Middle value" v={show(d.median)}/>}
        {d && <KV k="8 in 10 cells" v={`${show(d.p10)} to ${show(d.p90)}`}/>}
        {ev.shares_pct && Object.entries(ev.shares_pct).map(([k, v]) => <KV key={k} k={k} v={`${v}% of cells`}/>)}
      </div>
      {ev.sites?.length > 0 && (
        <div style={{ ...box, marginTop: 8 }}>
          <div style={{ fontWeight: 600, color: 'var(--heading)', marginBottom: 4 }}>Monitored sites</div>
          {ev.sites.map(s => <KV key={s.name} k={s.name} v={show(s.value)}/>)}
        </div>
      )}
    </>
  )
}

export default function ExplainPanel({ request, onClose, onAudience, compareOptions, onCompare }) {
  const [tab, setTab] = useState('summary')
  const closeRef = useRef(null)
  const { data, isLoading, isError, error } = useExplain(request)
  useEffect(() => { setTab('summary') }, [request?.kind])
  useEffect(() => { closeRef.current?.focus() }, [request?.kind])
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  if (!request) return null
  const ex = data?.explanation
  const ev = data?.evidence
  const tabs = [['summary', 'Summary'], ['local', 'Local implications'], ['evidence', 'Evidence']]
  const btn = active => ({ background: active ? 'var(--nav-active-bg)' : 'transparent', color: active ? 'var(--accent-text)' : 'var(--text-body)',
                           border: '1px solid ' + (active ? 'var(--info-border)' : 'transparent'), borderRadius: 8, padding: '6px 10px',
                           fontSize: 13.5, fontWeight: 600, cursor: 'pointer', minHeight: 36 })
  return (
    <aside role="dialog" aria-modal="false" aria-labelledby="explain-title"
           style={{ position: 'fixed', top: 0, right: 0, bottom: 0, width: 'min(460px, 100vw)', zIndex: 3000, display: 'flex', flexDirection: 'column',
                    background: 'var(--bg-surface)', borderLeft: '1px solid var(--border-primary)', boxShadow: '-8px 0 24px rgba(0,0,0,0.25)',
                    color: 'var(--text-body)', fontSize: 14 }}>
      <header style={{ padding: '14px 16px 8px', borderBottom: '1px solid var(--border-primary)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <h2 id="explain-title" style={{ margin: 0, fontSize: 17, color: 'var(--heading)', flex: 1 }}>{TITLES[request.kind]}</h2>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close the explanation"
                  style={{ ...btn(false), border: '1px solid var(--border-primary)', minWidth: 36 }}>X</button>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginTop: 8 }}>
          <label style={lbl} htmlFor="explain-audience">Written for</label>
          <select id="explain-audience" value={request.audience ?? 'general'} onChange={e => onAudience(e.target.value)}
                  style={{ background: 'var(--select-bg)', color: 'var(--heading)', border: '1px solid var(--border-primary)', borderRadius: 6, padding: '4px 6px', fontSize: 13 }}>
            {AUDIENCES.map(a => <option key={a.id} value={a.id}>{a.label}</option>)}
          </select>
          {request.kind === 'changes' && compareOptions?.length > 0 && (
            <>
              <label style={lbl} htmlFor="explain-compare">Compared with</label>
              <select id="explain-compare" value={request.compare_to} onChange={e => onCompare(e.target.value)}
                      style={{ background: 'var(--select-bg)', color: 'var(--heading)', border: '1px solid var(--border-primary)', borderRadius: 6, padding: '4px 6px', fontSize: 13, maxWidth: 220 }}>
                {compareOptions.map(o => <option key={o.model} value={o.model}>{o.label}</option>)}
              </select>
            </>
          )}
        </div>
        <nav role="tablist" aria-label="Explanation sections" style={{ display: 'flex', gap: 4, marginTop: 10 }}>
          {tabs.map(([id, label]) => (
            <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)} style={btn(tab === id)}>{label}</button>
          ))}
        </nav>
      </header>
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px' }} role="tabpanel">
        {isLoading && <p style={{ color: 'var(--text-meta)' }}>Preparing the explanation...</p>}
        {isError && <p style={{ color: 'var(--bad-text)' }}>{error?.message ?? 'The explanation could not be made.'}</p>}
        {ex && tab === 'summary' && <Para lines={ex.sections.summary}/>}
        {ex && tab === 'local' && <Para lines={ex.sections.local_implications}/>}
        {ex && tab !== 'evidence' && ex.sections.cautions?.length > 0 && (
          <div style={{ marginTop: 10, padding: '8px 10px', borderRadius: 6, background: 'var(--caution-bg)', color: 'var(--caution-text)', fontSize: 13, lineHeight: 1.5 }}>
            <strong>Keep in mind</strong>
            <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{ex.sections.cautions.map((c, i) => <li key={i}>{c}</li>)}</ul>
          </div>
        )}
        {ev && tab === 'evidence' && (
          <>
            {ev.kind === 'location' && <LocationEvidence ev={ev}/>}
            {ev.kind === 'changes' && <ChangesEvidence ev={ev}/>}
            {ev.kind === 'map' && <MapEvidence ev={ev}/>}
            <div style={{ ...box, marginTop: 8 }}>
              <div style={{ fontWeight: 600, color: 'var(--heading)', marginBottom: 4 }}>Sources</div>
              {(ev.sources ?? []).map((s, i) => <KV key={i} k={s.what} v={s.detail}/>)}
            </div>
            <details style={{ marginTop: 8 }}>
              <summary style={{ cursor: 'pointer', fontSize: 13 }}>Evidence record (JSON)</summary>
              <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 320, overflow: 'auto' }}>{JSON.stringify(ev, null, 1)}</pre>
            </details>
          </>
        )}
      </div>
      {ex && (
        <footer style={{ padding: '8px 16px 12px', borderTop: '1px solid var(--border-primary)', fontSize: 12, color: 'var(--text-meta)', lineHeight: 1.5 }}>
          {ex.source === 'claude'
            ? <>Written by an AI assistant ({ex.model}) from the evidence record; every number was checked against it. Evidence {ev?.id}.</>
            : <>{ex.note ?? 'Standard explanation written from the evidence record.'} Evidence {ev?.id}.</>}
        </footer>
      )}
    </aside>
  )
}
