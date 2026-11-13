// Bulletin Studio (backend /studio/*): compose a bulletin from a snapshot of the platform's evidence, edit it, check
// it (numbers against the evidence, certainty, draft and experimental labels), export it (Word, Markdown, print/PDF,
// SMS, audio script) and keep versions (reviewer token).
import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { API_BASE } from '../api/queries'
import { AUDIENCES } from './ExplainPanel'

const CROPS = [['maize_early', 'Early-maturing maize'], ['maize_medium', 'Medium-maturing maize'], ['sorghum', 'Sorghum'], ['bean', 'Dry bean']]
const inp = { background: 'var(--select-bg)', color: 'var(--heading)', border: '1px solid var(--border-primary)', borderRadius: 6, padding: '5px 7px', fontSize: 13, width: '100%' }
const lbl = { fontSize: 12, color: 'var(--text-meta)' }
const btn = { background: 'var(--btn-primary)', color: '#fff', border: 0, borderRadius: 8, padding: '7px 14px', fontWeight: 600, cursor: 'pointer', minHeight: 36 }
const btn2 = { background: 'var(--bg-elevated)', color: 'var(--accent-text)', border: '1px solid var(--info-border)', borderRadius: 8, padding: '6px 11px', fontWeight: 600, cursor: 'pointer', minHeight: 34, fontSize: 13 }
const KIND = { unsupported_number: 'Figure not in the evidence', certainty: 'Too certain', missing_label: 'Missing label', empty: 'Empty part', too_long: 'Too long' }

const getJSON = async (path) => { const r = await fetch(`${API_BASE}${path}`); if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() }
async function postJSON(path, body, headers = {}) {
  const r = await fetch(`${API_BASE}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(body) })
  if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.detail ?? `HTTP ${r.status}`) }
  return r
}
function download(blob, name) {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob); a.download = name
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(a.href), 2000)
}
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))

export default function BulletinStudio({ place, season, model, onClose }) {
  const { data: meta } = useQuery({ queryKey: ['studio-formats'], queryFn: () => getJSON('/studio/formats'), staleTime: Infinity })
  const { data: regions } = useQuery({ queryKey: ['explain-regions', season], queryFn: () => getJSON(`/explain/regions?season=${encodeURIComponent(season)}`), staleTime: Infinity })
  const [cfg, setCfg] = useState({ format: 'site_update', audience: 'general', length: 'standard', area: '', crop: 'maize_early', planted: 'unknown', sowing_date: '' })
  const [b, setB] = useState(null)
  const [snap, setSnap] = useState(null)
  const [issues, setIssues] = useState([])
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState(null)
  const [token, setToken] = useState(() => { try { return sessionStorage.getItem('fr-token') ?? '' } catch { return '' } })
  const [author, setAuthor] = useState('')
  const [status, setStatus] = useState('draft')
  const [saved, setSaved] = useState(null)
  const [parentId, setParentId] = useState(null)
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const scope = meta?.formats?.[cfg.format]?.scope
  const set = patch => setCfg(c => ({ ...c, ...patch }))

  async function run(label, fn) {
    setBusy(label); setErr(null)
    try { await fn() } catch (e) { setErr(String(e.message ?? e)) } finally { setBusy('') }
  }
  const compose = () => run('compose', async () => {
    const body = { format: cfg.format, season, model, audience: cfg.audience, length: cfg.length, crop: cfg.crop, planted: cfg.planted,
                   sowing_date: cfg.planted === 'yes' ? (cfg.sowing_date || null) : null,
                   ...(scope === 'place' ? { lat: place.lat, lon: place.lon } : {}), ...(scope === 'area' ? { area: cfg.area } : {}) }
    const j = await (await postJSON('/studio/compose', body)).json()
    setB(j.bulletin); setSnap(j.snapshot); setIssues(j.quality); setParentId(null); setSaved(null)
  })
  const check = () => run('check', async () => { setIssues((await (await postJSON('/studio/check', { bulletin: b, snapshot: snap })).json()).quality) })
  const exportAs = fmt => run('export', async () => {
    const r = await postJSON(`/studio/export?fmt=${fmt}`, { bulletin: b, snapshot: snap })
    const name = (b.title || 'bulletin').replace(/[^A-Za-z0-9]+/g, '_').slice(0, 60)
    download(await r.blob(), `${name}${fmt === 'docx' ? '.docx' : fmt === 'md' ? '.md' : `_${fmt}.txt`}`)
  })
  const print = () => {
    const w = window.open('', '_blank')
    if (!w) return
    const parts = (meta?.sections ?? []).map(s => `<h2>${esc(s.label)}</h2><ul>${(b.sections[s.id] ?? []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>`).join('')
    w.document.write(`<!doctype html><meta charset="utf-8"><title>${esc(b.title)}</title><style>body{font:14px/1.5 Calibri,Arial,sans-serif;margin:32px;max-width:760px}h1{font-size:22px}h2{font-size:15px;margin:18px 0 4px}footer{margin-top:24px;font-size:11px;color:#555}</style><h1>${esc(b.title)}</h1>${parts}<footer>Seasonal to Sub-seasonal Climate &amp; Agricultural Intelligence System (ILRI / ICPAC)</footer>`)
    w.document.close(); w.focus(); w.print()
  }
  const save = () => run('save', async () => {
    try { sessionStorage.setItem('fr-token', token) } catch { /* private window */ }
    const j = await (await postJSON('/studio/save', { bulletin: b, snapshot: snap, status, author, parent_id: parentId }, { 'X-Admin-Token': token })).json()
    setParentId(j.id); setSaved(j)
  })
  const [list, setList] = useState(null)
  const loadList = () => run('list', async () => {
    const r = await fetch(`${API_BASE}/studio/saved`, { headers: { 'X-Admin-Token': token } })
    setList(r.ok ? (await r.json()).bulletins : (await getJSON('/studio/published')).bulletins)
  })
  const open = id => run('open', async () => {
    const r = await fetch(`${API_BASE}/studio/saved/${id}`, { headers: { 'X-Admin-Token': token } })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const row = await r.json()
    setB({ title: row.title, sections: row.sections, sms: row.sms, audio_script: row.audio_script, format: row.format, audience: row.audience, length: row.length })
    setSnap(row.snapshot); setIssues(row.quality ?? []); setParentId(row.id); setSaved(null)
  })
  const editLines = (k, text) => setB(x => ({ ...x, sections: { ...x.sections, [k]: text.split('\n').map(s => s.trim()).filter(Boolean) } }))
  const byPart = useMemo(() => issues.reduce((m, i) => { (m[i.part] = m[i.part] ?? []).push(i); return m }, {}), [issues])

  return (
    <aside role="dialog" aria-modal="false" aria-labelledby="studio-title"
           style={{ position: 'fixed', top: 0, right: 0, bottom: 0, width: 'min(880px, 100vw)', zIndex: 3000, display: 'flex', flexDirection: 'column',
                    background: 'var(--bg-surface)', borderLeft: '1px solid var(--border-primary)', boxShadow: '-8px 0 24px rgba(0,0,0,0.25)', color: 'var(--text-body)', fontSize: 14 }}>
      <header style={{ padding: '14px 16px 10px', borderBottom: '1px solid var(--border-primary)', display: 'flex', gap: 8, alignItems: 'center' }}>
        <h2 id="studio-title" style={{ margin: 0, fontSize: 17, color: 'var(--heading)', flex: 1 }}>Bulletin Studio</h2>
        <button type="button" onClick={onClose} aria-label="Close the Bulletin Studio" style={{ ...btn2, minWidth: 36 }}>X</button>
      </header>
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <section aria-label="Set up" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8, alignItems: 'end' }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Format</span>
            <select value={cfg.format} onChange={e => set({ format: e.target.value })} style={inp}>
              {Object.entries(meta?.formats ?? {}).map(([k, f]) => <option key={k} value={k}>{f.label}</option>)}</select></label>
          {scope === 'place' && <div style={{ fontSize: 13 }}><span style={lbl}>Place</span><div style={{ color: 'var(--heading)' }}>{place.name}</div></div>}
          {scope === 'area' && <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>{regions?.kind === 'region' ? 'Region' : 'County'}</span>
            <select value={cfg.area} onChange={e => set({ area: e.target.value })} style={inp}><option value="">Choose...</option>
              {(regions?.names ?? []).map(n => <option key={n} value={n}>{n}</option>)}</select></label>}
          {scope === 'sites' && <div style={{ fontSize: 13 }}><span style={lbl}>Scope</span><div style={{ color: 'var(--heading)' }}>All monitored sites</div></div>}
          {cfg.format === 'crop_advisory' && <>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Crop</span>
              <select value={cfg.crop} onChange={e => set({ crop: e.target.value })} style={inp}>{CROPS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Field</span>
              <select value={cfg.planted} onChange={e => set({ planted: e.target.value })} style={inp}>
                <option value="unknown">Not stated</option><option value="no">Not yet sown</option><option value="yes">Sown</option></select></label>
            {cfg.planted === 'yes' && <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Sowing date</span>
              <input type="date" value={cfg.sowing_date} onChange={e => set({ sowing_date: e.target.value })} style={inp}/></label>}
          </>}
          <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Audience</span>
            <select value={cfg.audience} onChange={e => set({ audience: e.target.value })} style={inp}>{AUDIENCES.map(a => <option key={a.id} value={a.id}>{a.label}</option>)}</select></label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Length</span>
            <select value={cfg.length} onChange={e => set({ length: e.target.value })} style={inp}>
              <option value="short">Short</option><option value="standard">Standard</option><option value="detailed">Detailed</option></select></label>
          <div><button type="button" style={{ ...btn, opacity: busy ? 0.6 : 1 }} disabled={!!busy || (scope === 'area' && !cfg.area)} onClick={compose}>
            {busy === 'compose' ? 'Composing...' : b ? 'Compose again' : 'Compose'}</button></div>
        </section>
        {meta?.formats?.[cfg.format] && <p style={{ ...lbl, margin: 0 }}>{meta.formats[cfg.format].about}</p>}
        {err && <p role="alert" style={{ margin: 0, color: 'var(--bad-text)', fontSize: 13 }}>{err}</p>}
        {b && (
          <>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
              <span style={{ ...lbl, marginRight: 4 }}>{b.source === 'claude' ? `Drafted by an AI assistant (${b.model}); figures checked` : (b.note ?? 'Standard draft from the evidence')}</span>
              <button type="button" style={btn2} onClick={check}>{busy === 'check' ? 'Checking...' : 'Check'}</button>
              <button type="button" style={btn2} onClick={() => exportAs('docx')}>Word</button>
              <button type="button" style={btn2} onClick={() => exportAs('md')}>Markdown</button>
              <button type="button" style={btn2} onClick={print}>Print / PDF</button>
              <button type="button" style={btn2} onClick={() => exportAs('sms')}>SMS text</button>
              <button type="button" style={btn2} onClick={() => exportAs('audio')}>Audio script</button>
            </div>
            <div role="status" style={{ padding: '8px 10px', borderRadius: 6, fontSize: 13, background: issues.length ? 'var(--caution-bg)' : 'var(--ok-bg)', color: issues.length ? 'var(--caution-text)' : 'var(--ok-text)' }}>
              {issues.length ? <><strong>{issues.length} issue(s) to fix before reviewing or publishing:</strong>
                <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{issues.map((i, k) => <li key={k}>{KIND[i.kind] ?? i.kind} ({i.part}): {i.detail}</li>)}</ul></>
                : 'Check passed: every figure is in the evidence snapshot, and the labels are in place.'}
            </div>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Title</span>
              <input value={b.title} onChange={e => setB(x => ({ ...x, title: e.target.value }))} style={inp}/></label>
            {(meta?.sections ?? []).map(s => (
              <label key={s.id} style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                <span style={{ ...lbl, fontWeight: 600, color: byPart[s.id] ? 'var(--caution-text)' : 'var(--heading)' }}>{s.label}{byPart[s.id] ? ' (see issues)' : ''}</span>
                <textarea rows={Math.max(2, (b.sections[s.id] ?? []).length + 1)} value={(b.sections[s.id] ?? []).join('\n')} onChange={e => editLines(s.id, e.target.value)}
                          style={{ ...inp, fontFamily: 'inherit', lineHeight: 1.5 }}/>
              </label>
            ))}
            <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>SMS ({(b.sms ?? '').length} characters; up to 300)</span>
              <textarea rows={3} value={b.sms ?? ''} onChange={e => setB(x => ({ ...x, sms: e.target.value }))} style={{ ...inp, fontFamily: 'inherit' }}/></label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Audio script (radio)</span>
              <textarea rows={4} value={b.audio_script ?? ''} onChange={e => setB(x => ({ ...x, audio_script: e.target.value }))} style={{ ...inp, fontFamily: 'inherit' }}/></label>
          </>
        )}
        <section aria-label="Versions" style={{ borderTop: '1px solid var(--border-primary)', paddingTop: 10, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 8, alignItems: 'end' }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Reviewer token</span>
            <input type="password" value={token} onChange={e => setToken(e.target.value)} style={inp}/></label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Author</span>
            <input value={author} onChange={e => setAuthor(e.target.value)} maxLength={80} style={inp}/></label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Status</span>
            <select value={status} onChange={e => setStatus(e.target.value)} style={inp}>
              <option value="draft">Draft</option><option value="reviewed">Reviewed</option><option value="published">Published</option></select></label>
          <div style={{ display: 'flex', gap: 6 }}>
            <button type="button" style={btn2} disabled={!b || !token} onClick={save}>{parentId ? 'Save new version' : 'Save'}</button>
            <button type="button" style={btn2} onClick={loadList}>Saved bulletins</button>
          </div>
        </section>
        {saved && <p style={{ margin: 0, fontSize: 13 }}>Saved as version {saved.version} ({saved.status}).{saved.storage?.permanent ? '' : ' ' + saved.storage?.note}</p>}
        {list && (list.length ? (
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>{list.map(x => (
            <li key={x.id}><button type="button" onClick={() => open(x.id)} style={{ background: 'none', border: 0, color: 'var(--accent-text)', cursor: 'pointer', padding: 0, textDecoration: 'underline' }}>{x.title}</button>{' '}
              <span style={lbl}>v{x.version}, {x.status}, {String(x.created_at).slice(0, 10)}{x.author ? `, ${x.author}` : ''}</span></li>))}</ul>
        ) : <p style={lbl}>No saved bulletins.</p>)}
      </div>
    </aside>
  )
}
