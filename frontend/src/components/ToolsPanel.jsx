// More assistant tools (backend /extras/*): past seasons like this one (analogues), the end-of-season review,
// guided learning with this forecast's own numbers, participatory scenario planning, and official outlooks
// (uploaded by hand) compared with the platform.
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { API_BASE } from '../api/queries'
import { useLanguages } from './voice'

const TABS = [['analogues', 'Past seasons'], ['review', 'Season review'], ['learn', 'Learn'], ['plan', 'Scenario planning'], ['official', 'Official outlooks']]
const CROPS = [['maize_early', 'Early-maturing maize'], ['maize_medium', 'Medium-maturing maize'], ['sorghum', 'Sorghum'], ['bean', 'Dry bean']]
const inp = { background: 'var(--select-bg)', color: 'var(--heading)', border: '1px solid var(--border-primary)', borderRadius: 6, padding: '5px 7px', fontSize: 13, width: '100%' }
const lbl = { fontSize: 12, color: 'var(--text-meta)' }
const btn2 = { background: 'var(--bg-elevated)', color: 'var(--accent-text)', border: '1px solid var(--info-border)', borderRadius: 8, padding: '5px 10px', fontWeight: 600, cursor: 'pointer', minHeight: 32, fontSize: 12.5 }
const th = { textAlign: 'left', fontWeight: 600, fontSize: 12, color: 'var(--text-meta)', padding: '4px 6px', borderBottom: '1px solid var(--border-primary)' }
const td = { padding: '5px 6px', borderBottom: '1px solid var(--border-primary)', fontSize: 13, fontVariantNumeric: 'tabular-nums', verticalAlign: 'top' }

const get = async path => { const r = await fetch(`${API_BASE}${path}`); const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.detail ?? `HTTP ${r.status}`); return j }

function Explained({ data }) {
  const ex = data?.explanation
  if (!ex) return null
  return (
    <div style={{ lineHeight: 1.55 }}>
      {ex.translation_notice && <p style={{ margin: '0 0 8px', padding: '6px 10px', borderRadius: 6, background: 'var(--caution-bg)', color: 'var(--caution-text)', fontSize: 12.5 }}>{ex.translation_notice}</p>}
      {ex.sections.summary.map((t, i) => <p key={i} style={{ margin: '0 0 6px' }}>{t}</p>)}
      {ex.sections.local_implications.map((t, i) => <p key={'l' + i} style={{ margin: '0 0 6px' }}>{t}</p>)}
      <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12.5, color: 'var(--caution-text)' }}>{ex.sections.cautions.map((c, i) => <li key={i}>{c}</li>)}</ul>
    </div>
  )
}

function useTool(key, path, enabled = true) {
  return useQuery({ queryKey: ['tool', key, path], queryFn: () => get(path), enabled, staleTime: 10 * 60_000, retry: 0 })
}

function Learn({ q }) {
  const [picked, setPicked] = useState({})
  const { data, isLoading, error } = useTool('learn', `/extras/lessons?${q}`)
  if (isLoading) return <p style={lbl}>Loading the lessons...</p>
  if (error) return <p style={{ color: 'var(--bad-text)' }}>{error.message}</p>
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {data.translation_notice && <p style={{ margin: 0, fontSize: 12.5, color: 'var(--caution-text)' }}>{data.translation_notice}</p>}
      {data.lessons.map(l => (
        <div key={l.id} style={{ border: '1px solid var(--border-primary)', borderRadius: 8, padding: '8px 10px', fontSize: 13, lineHeight: 1.5 }}>
          <div style={{ fontWeight: 600, color: 'var(--heading)' }}>{l.title}</div>
          <p style={{ margin: '4px 0' }}>{l.text}</p>
          <p style={{ margin: '4px 0', color: 'var(--accent-text)' }}>In this forecast: {l.example}</p>
          <div role="group" aria-label={l.question.prompt}>
            <div style={{ fontWeight: 600, margin: '6px 0 4px' }}>{l.question.prompt}</div>
            {l.question.options.map((o, i) => (
              <button key={i} type="button" onClick={() => setPicked(p => ({ ...p, [l.id]: i }))}
                      style={{ ...btn2, display: 'block', width: '100%', textAlign: 'left', marginBottom: 4,
                               background: picked[l.id] === i ? (i === l.question.answer ? 'var(--ok-bg)' : 'var(--caution-bg)') : 'var(--bg-elevated)' }}>{o}</button>
            ))}
            {picked[l.id] != null && <p style={{ margin: '4px 0 0', fontSize: 12.5 }}>{picked[l.id] === l.question.answer ? 'Right. ' : 'Not quite. '}{l.question.why}</p>}
          </div>
        </div>
      ))}
    </div>
  )
}

function Plan({ q }) {
  const [crop, setCrop] = useState('maize_early')
  const [notes, setNotes] = useState({})
  const { data, isLoading, error } = useTool('plan', `/extras/scenario-plan?${q}&crop=${crop}`)
  const exportMd = () => {
    const lines = [`# Scenario planning: ${data.scope?.site?.name ?? 'selected place'}, ${data.season?.label} ${data.season?.year}`, '', '## Possible outcomes', '']
    data.outcomes.forEach(o => lines.push(`- ${o.quantity}, ${o.outcome}: ${o.chance_pct}% chance`))
    if (data.crop_by_rain) { lines.push('', `## ${data.crop} at ${data.crop_site}, by season rain (experimental)`, ''); data.crop_by_rain.forEach(g => lines.push(`- ${g.group} (${g.season_rain_mm[0]}-${g.season_rain_mm[1]} mm): median yield ${g.median_yield_t_ha} t/ha, ${g.matured_pct}% matured`)) }
    lines.push('', '## Discussion', '')
    data.discussion_questions.forEach((x, i) => lines.push(`**${x}**`, '', notes[i] || '_(notes)_', ''))
    lines.push('', ...data.caveats.map(c => `> ${c}`))
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/markdown' })); a.download = 'scenario_planning.md'; a.click()
  }
  if (isLoading) return <p style={lbl}>Preparing the planning sheet...</p>
  if (error) return <p style={{ color: 'var(--bad-text)' }}>{error.message}</p>
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 13 }}>
      <p style={{ margin: 0, lineHeight: 1.5 }}>A sheet for a planning session with farmers or extension staff: the season&apos;s possible outcomes with their chances,
        what the crop outlook shows in drier and wetter seasons, and questions to discuss. Notes stay in this browser until you export them.</p>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr><th style={th} scope="col">Outcome</th><th style={th} scope="col">Chance</th></tr></thead>
        <tbody>{data.outcomes.map((o, i) => <tr key={i}><td style={td}>{o.quantity}: {o.outcome}</td><td style={td}>{o.chance_pct}%</td></tr>)}</tbody>
      </table>
      <label style={{ display: 'flex', flexDirection: 'column', gap: 3, maxWidth: 260 }}><span style={lbl}>Crop</span>
        <select value={crop} onChange={e => setCrop(e.target.value)} style={inp}>{CROPS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
      {data.crop_by_rain ? (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <caption style={{ ...lbl, textAlign: 'left', marginBottom: 4 }}>{data.crop} at {data.crop_site}: members grouped by season rain (experimental)</caption>
          <thead><tr><th style={th} scope="col">Seasons</th><th style={th} scope="col">Rain (mm)</th><th style={th} scope="col">Median yield (t/ha)</th><th style={th} scope="col">Matured</th></tr></thead>
          <tbody>{data.crop_by_rain.map(g => <tr key={g.group}><td style={td}>{g.group}</td><td style={td}>{g.season_rain_mm[0]}-{g.season_rain_mm[1]}</td><td style={td}>{g.median_yield_t_ha}</td><td style={td}>{g.matured_pct}%</td></tr>)}</tbody>
        </table>
      ) : <p style={lbl}>No crop outlook near this place.</p>}
      {data.discussion_questions.map((x, i) => (
        <label key={i} style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={{ fontWeight: 600 }}>{x}</span>
          <textarea rows={2} value={notes[i] ?? ''} onChange={e => setNotes(n => ({ ...n, [i]: e.target.value }))} style={{ ...inp, fontFamily: 'inherit' }}/></label>
      ))}
      <div><button type="button" style={btn2} onClick={exportMd}>Export the sheet (Markdown)</button></div>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, color: 'var(--caution-text)' }}>{data.caveats.map((c, i) => <li key={i}>{c}</li>)}</ul>
    </div>
  )
}

function Official({ season, model, langQ }) {
  const [sel, setSel] = useState(null)
  const list = useTool('outlooks', `/extras/outlooks?season=${season}`)
  const cmp = useTool('compare', sel ? `/extras/outlooks/${sel}/compare?model=${encodeURIComponent(model)}${langQ}` : '', !!sel)
  const { data: regions } = useQuery({ queryKey: ['explain-regions', season], queryFn: () => get(`/explain/regions?season=${season}`), staleTime: Infinity })
  const [form, setForm] = useState({ source: '', year: new Date().getFullYear(), issued_on: '', variable: 'rainfall', rows: [{ name: '', below: '', normal: '', above: '' }] })
  const [token, setToken] = useState(() => { try { return sessionStorage.getItem('fr-token') ?? '' } catch { return '' } })
  const [msg, setMsg] = useState(null)
  const setRow = (i, p) => setForm(f => ({ ...f, rows: f.rows.map((r, k) => k === i ? { ...r, ...p } : r) }))
  async function upload(e) {
    e.preventDefault(); setMsg(null)
    try { sessionStorage.setItem('fr-token', token) } catch { /* private window */ }
    const body = { source: form.source, season, year: Number(form.year), issued_on: form.issued_on || null, variable: form.variable,
                   regions: form.rows.filter(r => r.name).map(r => ({ name: r.name, below: Number(r.below), normal: Number(r.normal), above: Number(r.above) })) }
    const r = await fetch(`${API_BASE}/extras/outlooks`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Admin-Token': token }, body: JSON.stringify(body) })
    const j = await r.json().catch(() => ({}))
    if (!r.ok) { setMsg(j.detail ?? `HTTP ${r.status}`); return }
    setMsg('Uploaded.'); list.refetch(); setSel(j.id)
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 13 }}>
      <p style={{ margin: 0, lineHeight: 1.5 }}>Compare an official outlook (ICPAC GHACOF, KMD, EMI) with the platform, area by area. Outlooks are entered by hand.</p>
      {list.data?.outlooks?.length ? (
        <ul style={{ margin: 0, paddingLeft: 18 }}>{list.data.outlooks.map(o => (
          <li key={o.id}><button type="button" onClick={() => setSel(o.id)} style={{ background: 'none', border: 0, padding: 0, color: 'var(--accent-text)', textDecoration: 'underline', cursor: 'pointer' }}>
            {o.source} {o.variable} {o.year}</button> <span style={lbl}>{o.issued_on ? `issued ${o.issued_on}` : ''}</span></li>))}</ul>
      ) : <p style={lbl}>No official outlook entered for this season yet.</p>}
      {cmp.isLoading && sel && <p style={lbl}>Comparing...</p>}
      {cmp.error && <p style={{ color: 'var(--bad-text)' }}>{cmp.error.message}</p>}
      {cmp.data && <Explained data={cmp.data}/>}
      <form onSubmit={upload} style={{ borderTop: '1px solid var(--border-primary)', paddingTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ fontWeight: 600, color: 'var(--heading)' }}>Enter an official outlook (reviewers)</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 8 }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Source</span><input value={form.source} onChange={e => setForm(f => ({ ...f, source: e.target.value }))} placeholder="e.g. ICPAC GHACOF 70" style={inp}/></label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Year</span><input type="number" value={form.year} onChange={e => setForm(f => ({ ...f, year: e.target.value }))} style={inp}/></label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Issued on</span><input type="date" value={form.issued_on} onChange={e => setForm(f => ({ ...f, issued_on: e.target.value }))} style={inp}/></label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}><span style={lbl}>Quantity</span><select value={form.variable} onChange={e => setForm(f => ({ ...f, variable: e.target.value }))} style={inp}><option value="rainfall">Rainfall totals</option><option value="onset">Onset</option></select></label>
        </div>
        {form.rows.map((r, i) => (
          <div key={i} style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr', gap: 6 }}>
            <select aria-label="Area" value={r.name} onChange={e => setRow(i, { name: e.target.value })} style={inp}><option value="">Area...</option>{(regions?.names ?? []).map(n => <option key={n} value={n}>{n}</option>)}</select>
            {['below', 'normal', 'above'].map(k => <input key={k} aria-label={`${k} (%)`} placeholder={`${form.variable === 'onset' ? { below: 'early', normal: 'normal', above: 'late' }[k] : k} %`} type="number" min="0" max="100" value={r[k]} onChange={e => setRow(i, { [k]: e.target.value })} style={inp}/>)}
          </div>
        ))}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          <button type="button" style={btn2} onClick={() => setForm(f => ({ ...f, rows: [...f.rows, { name: '', below: '', normal: '', above: '' }] }))}>Add an area</button>
          <input type="password" aria-label="Reviewer token" placeholder="Reviewer token" value={token} onChange={e => setToken(e.target.value)} style={{ ...inp, width: 160 }}/>
          <button type="submit" style={btn2}>Save the outlook</button>
          {msg && <span style={{ fontSize: 12.5 }}>{msg}</span>}
        </div>
      </form>
    </div>
  )
}

export default function ToolsPanel({ place, season, model, onClose }) {
  const [tab, setTab] = useState('analogues')
  const [language, setLanguage] = useState('en')
  const { data: langs } = useLanguages()
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const langQ = language !== 'en' ? `&language=${language}` : ''
  const q = new URLSearchParams({ lat: place.lat, lon: place.lon, season, model }).toString()
  const ana = useTool('analogues', `/extras/analogues?${q}${langQ}`, tab === 'analogues')
  const rev = useTool('review', `/extras/season-review?${q}${langQ}`, tab === 'review')
  const tb = a => ({ background: a ? 'var(--nav-active-bg)' : 'transparent', color: a ? 'var(--accent-text)' : 'var(--text-body)', border: '1px solid ' + (a ? 'var(--info-border)' : 'transparent'),
                     borderRadius: 8, padding: '5px 9px', fontSize: 13, fontWeight: 600, cursor: 'pointer', minHeight: 34 })
  return (
    <aside role="dialog" aria-modal="false" aria-labelledby="tools-title"
           style={{ position: 'fixed', top: 0, right: 0, bottom: 0, width: 'min(560px, 100vw)', zIndex: 3000, display: 'flex', flexDirection: 'column',
                    background: 'var(--bg-surface)', borderLeft: '1px solid var(--border-primary)', boxShadow: '-8px 0 24px rgba(0,0,0,0.25)', color: 'var(--text-body)', fontSize: 14 }}>
      <header style={{ padding: '14px 16px 8px', borderBottom: '1px solid var(--border-primary)' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <h2 id="tools-title" style={{ margin: 0, fontSize: 17, color: 'var(--heading)', flex: 1 }}>More tools: {place.name}</h2>
          <button type="button" onClick={onClose} aria-label="Close more tools" style={{ ...btn2, minWidth: 36 }}>X</button>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8 }}>
          <label htmlFor="tools-language" style={lbl}>Language</label>
          <select id="tools-language" value={language} onChange={e => setLanguage(e.target.value)} style={{ ...inp, width: 'auto' }}>
            {Object.entries(langs ?? { en: { native: 'English' } }).map(([k, l]) => <option key={k} value={k}>{l.native}</option>)}</select>
        </div>
        <nav role="tablist" aria-label="Tools" style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 8 }}>
          {TABS.map(([id, l]) => <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)} style={tb(tab === id)}>{l}</button>)}
        </nav>
      </header>
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px' }} role="tabpanel">
        {tab === 'analogues' && (ana.isLoading ? <p style={lbl}>Finding past seasons...</p> : ana.error ? <p style={{ color: 'var(--bad-text)' }}>{ana.error.message}</p> : <Explained data={ana.data}/>)}
        {tab === 'review' && (rev.isLoading ? <p style={lbl}>Reviewing past seasons...</p> : rev.error ? <p style={{ color: 'var(--bad-text)' }}>{rev.error.message}</p> : <Explained data={rev.data}/>)}
        {tab === 'learn' && <Learn q={q + langQ}/>}
        {tab === 'plan' && <Plan q={q}/>}
        {tab === 'official' && <Official season={season} model={model} langQ={langQ}/>}
      </div>
    </aside>
  )
}
