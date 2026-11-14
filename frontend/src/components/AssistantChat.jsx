// Forecast assistant chat (backend POST /explain/chat): questions about the forecast on screen. The backend answers
// through tools that return the platform's evidence records, checks every number against them, and falls back to
// the standard explanation when it cannot (or when the server has no Claude key).
import { useEffect, useRef, useState } from 'react'
import { API_BASE } from '../api/queries'
import { AUDIENCES } from './ExplainPanel'
import { useLanguages, speechCode, ListenButton, useDictation } from './voice'

const SUGGESTIONS = [
  'When will the rains start here, and how sure is that?',
  'What does the onset range mean?',
  'What changed since the previous run?',
  'What does the map on screen show?',
  'Which crop fits this season here?',
]
const TRACKER_SUGGESTIONS = [
  'How much rain has fallen here so far, and is that normal?',
  'Has the planting onset happened here yet?',
  'Will planting rains come in the next 7 days?',
  'What changed since the previous weather-model run?',
  'Why do the satellite products disagree?',
]
const KIND_LABEL = { location: 'Place outlook', changes: 'Run comparison', map: 'Map layer', advisory: 'Advisory (draft)',
                     tracker: 'Rainfall tracking', tracker_changes: 'Weather-model runs' }

export default function AssistantChat({ messages, setMessages, context, onClose, onAction }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [audience, setAudience] = useState('general')
  const [language, setLanguage] = useState('en')
  const { data: langs } = useLanguages()
  const dict = useDictation(speechCode(langs, language), t => setText(x => (x ? x + ' ' : '') + t))
  const endRef = useRef(null)
  const inputRef = useRef(null)
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }) }, [messages, busy])
  useEffect(() => { inputRef.current?.focus() }, [])
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  async function send(q) {
    const question = (q ?? text).trim()
    if (!question || busy) return
    const next = [...messages, { role: 'user', content: question }]
    setMessages(next); setText(''); setBusy(true)
    try {
      const res = await fetch(`${API_BASE}/explain/chat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: next.map(m => ({ role: m.role, content: m.content })), context, audience, language }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const j = await res.json()
      setMessages([...next, { role: 'assistant', content: j.reply, source: j.source, note: [j.note, j.translation_notice, j.translation_note].filter(Boolean).join(' '),
                              evidence: j.evidence ?? [], actions: j.actions ?? [], cautions: j.cautions ?? [], language: j.language ?? 'en' }])
    } catch (e) {
      setMessages([...next, { role: 'assistant', content: `The assistant could not answer (${e.message}). The Explain buttons still work.`, source: 'error', evidence: [], actions: [] }])
    } finally {
      setBusy(false)
    }
  }

  const chip = { background: 'var(--bg-elevated)', color: 'var(--accent-text)', border: '1px solid var(--info-border)', borderRadius: 16,
                 padding: '5px 10px', fontSize: 12.5, cursor: 'pointer', textAlign: 'left' }
  return (
    <aside role="dialog" aria-modal="false" aria-labelledby="chat-title"
           style={{ position: 'fixed', top: 0, right: 0, bottom: 0, width: 'min(460px, 100vw)', zIndex: 3000, display: 'flex', flexDirection: 'column',
                    background: 'var(--bg-surface)', borderLeft: '1px solid var(--border-primary)', boxShadow: '-8px 0 24px rgba(0,0,0,0.25)',
                    color: 'var(--text-body)', fontSize: 14 }}>
      <header style={{ padding: '14px 16px 10px', borderBottom: '1px solid var(--border-primary)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <h2 id="chat-title" style={{ margin: 0, fontSize: 17, color: 'var(--heading)', flex: 1 }}>Ask the forecast assistant</h2>
          <button type="button" onClick={onClose} aria-label="Close the assistant"
                  style={{ background: 'transparent', color: 'var(--text-body)', border: '1px solid var(--border-primary)', borderRadius: 8, minWidth: 36, minHeight: 36, cursor: 'pointer' }}>X</button>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8, flexWrap: 'wrap' }}>
          <label htmlFor="chat-audience" style={{ fontSize: 12, color: 'var(--text-meta)' }}>Written for</label>
          <select id="chat-audience" value={audience} onChange={e => setAudience(e.target.value)}
                  style={{ background: 'var(--select-bg)', color: 'var(--heading)', border: '1px solid var(--border-primary)', borderRadius: 6, padding: '4px 6px', fontSize: 13 }}>
            {AUDIENCES.map(a => <option key={a.id} value={a.id}>{a.label}</option>)}
          </select>
          <label htmlFor="chat-language" style={{ fontSize: 12, color: 'var(--text-meta)' }}>Language</label>
          <select id="chat-language" value={language} onChange={e => setLanguage(e.target.value)}
                  style={{ background: 'var(--select-bg)', color: 'var(--heading)', border: '1px solid var(--border-primary)', borderRadius: 6, padding: '4px 6px', fontSize: 13 }}>
            {Object.entries(langs ?? { en: { native: 'English' } }).map(([k, l]) => <option key={k} value={k}>{l.native}</option>)}
          </select>
          {messages.length > 0 && (
            <button type="button" onClick={() => setMessages([])} style={{ ...chip, marginLeft: 'auto' }}>New conversation</button>
          )}
        </div>
      </header>
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px' }} aria-live="polite">
        {messages.length === 0 && (
          <>
            <p style={{ marginTop: 0, lineHeight: 1.55 }}>
              {context?.page === 'tracker'
                ? `Ask about the rain at ${context.tracker_site ?? 'the monitoring site on screen'}: observed rain so far, the planting onset, dry days and the weather models' next days. Answers use the page's own figures.`
                : <>Ask about the forecast on screen: the place, run, method and map layer you have selected. Answers use the
                  platform&apos;s own figures; advisories are drafts that no agronomist has reviewed yet.</>}
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {(context?.page === 'tracker' ? TRACKER_SUGGESTIONS : SUGGESTIONS).map(s => <button key={s} type="button" style={chip} onClick={() => send(s)}>{s}</button>)}
            </div>
          </>
        )}
        {messages.map((m, i) => (
          <div key={i} style={{ display: 'flex', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start', margin: '8px 0' }}>
            <div style={{ maxWidth: '88%', padding: '8px 11px', borderRadius: 10, lineHeight: 1.55, whiteSpace: 'pre-wrap',
                          background: m.role === 'user' ? 'var(--nav-active-bg)' : 'var(--bg-elevated)',
                          border: '1px solid ' + (m.role === 'user' ? 'var(--info-border)' : 'var(--border-primary)') }}>
              {m.content}
              {m.role === 'assistant' && m.cautions?.length > 0 && (
                <ul style={{ margin: '6px 0 0', paddingLeft: 16, fontSize: 12.5, color: 'var(--caution-text)' }}>{m.cautions.map((c, k) => <li key={k}>{c}</li>)}</ul>
              )}
              {m.role === 'assistant' && m.source !== 'error' && (
                <div style={{ marginTop: 6 }}><ListenButton text={m.content} lang={speechCode(langs, m.language ?? 'en')} style={chip}/></div>
              )}
              {m.role === 'assistant' && m.actions?.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
                  {m.actions.map((a, k) => <button key={k} type="button" style={chip} onClick={() => onAction(a)}>{a.label}</button>)}
                </div>
              )}
              {m.role === 'assistant' && (m.evidence?.length > 0 || m.note) && (
                <div style={{ marginTop: 6, fontSize: 11.5, color: 'var(--text-meta)' }}>
                  {m.source === 'claude' ? 'AI answer, figures checked against: ' : m.evidence?.length ? 'From: ' : ''}
                  {m.evidence?.map(e => `${KIND_LABEL[e.kind] ?? e.kind} ${e.id}`).join(', ')}
                  {m.note ? ` ${m.note}` : ''}
                </div>
              )}
            </div>
          </div>
        ))}
        {busy && <p style={{ color: 'var(--text-meta)' }}>Looking at the forecast...</p>}
        <div ref={endRef}/>
      </div>
      <form onSubmit={e => { e.preventDefault(); send() }}
            style={{ display: 'flex', gap: 8, padding: '10px 16px 14px', borderTop: '1px solid var(--border-primary)' }}>
        <label htmlFor="chat-input" style={{ position: 'absolute', left: -9999 }}>Your question</label>
        <input id="chat-input" ref={inputRef} value={text} onChange={e => setText(e.target.value)} maxLength={2000}
               placeholder={context?.page === 'tracker' ? 'Ask about the rain at this site' : 'Ask about this forecast'} autoComplete="off"
               style={{ flex: 1, minWidth: 0, background: 'var(--select-bg)', color: 'var(--heading)', border: '1px solid var(--border-primary)',
                        borderRadius: 8, padding: '8px 10px', fontSize: 14 }}/>
        {dict.supported && (
          <button type="button" onClick={dict.listening ? dict.stop : dict.start} aria-pressed={dict.listening}
                  title="Speak your question (uses this browser's speech recognition)"
                  style={{ ...chip, borderRadius: 8, minHeight: 38 }}>{dict.listening ? 'Listening...' : 'Speak'}</button>
        )}
        <button type="submit" disabled={busy || !text.trim()}
                style={{ background: 'var(--btn-primary)', color: '#fff', border: 0, borderRadius: 8, padding: '0 14px', fontWeight: 600,
                         minHeight: 38, cursor: busy ? 'wait' : 'pointer', opacity: busy || !text.trim() ? 0.6 : 1 }}>Ask</button>
      </form>
    </aside>
  )
}
