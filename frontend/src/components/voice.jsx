// Languages and voice for the forecast assistant. The languages (and their review status) come from the backend
// (/explain/languages); speech uses the browser's own Web Speech API, so what works depends on the device:
// recognition is mainly in Chrome and Edge, and Kiswahili or Amharic voices are often missing.
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { API_BASE } from '../api/queries'

export function useLanguages() {
  return useQuery({
    queryKey: ['assistant-languages'],
    staleTime: Infinity,
    queryFn: async () => { const r = await fetch(`${API_BASE}/explain/languages`); if (!r.ok) throw new Error('languages'); return (await r.json()).languages },
  })
}

export const speechCode = (langs, code) => langs?.[code]?.speech ?? (code === 'sw' ? 'sw-KE' : code === 'am' ? 'am-ET' : 'en-KE')

function voiceFor(lang) {
  const synth = typeof window !== 'undefined' ? window.speechSynthesis : null
  if (!synth) return null
  const voices = synth.getVoices()
  const base = lang.split('-')[0]
  return voices.find(v => v.lang === lang) ?? voices.find(v => v.lang?.toLowerCase().startsWith(base)) ?? null
}

// read text aloud; returns false when this device has no voice for the language
export function speak(text, lang) {
  const synth = typeof window !== 'undefined' ? window.speechSynthesis : null
  if (!synth || !text) return false
  const v = voiceFor(lang)
  if (!v && !lang.startsWith('en')) return false
  synth.cancel()
  const u = new SpeechSynthesisUtterance(text)
  u.lang = lang
  if (v) u.voice = v
  synth.speak(u)
  return true
}

export function stopSpeaking() { try { window.speechSynthesis?.cancel() } catch { /* not supported */ } }

export function ListenButton({ text, lang, style }) {
  const [msg, setMsg] = useState(null)
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <button type="button" style={style} onClick={() => setMsg(speak(text, lang) ? null : 'No voice for this language on this device.')}
              title="Read aloud with this device's voice">Listen</button>
      <button type="button" style={style} onClick={stopSpeaking} title="Stop reading">Stop</button>
      {msg && <span style={{ fontSize: 12, color: 'var(--text-meta)' }}>{msg}</span>}
    </span>
  )
}

// speech-to-text into a text field; `onText` receives the final transcript
export function useDictation(lang, onText) {
  const recRef = useRef(null)
  const [listening, setListening] = useState(false)
  const Rec = typeof window !== 'undefined' ? (window.SpeechRecognition || window.webkitSpeechRecognition) : null
  useEffect(() => () => { try { recRef.current?.abort() } catch { /* ignore */ } }, [])
  const start = () => {
    if (!Rec || listening) return
    const r = new Rec()
    r.lang = lang
    r.interimResults = false
    r.maxAlternatives = 1
    r.onresult = e => { const t = e.results?.[0]?.[0]?.transcript; if (t) onText(t) }
    r.onend = () => setListening(false)
    r.onerror = () => setListening(false)
    recRef.current = r
    setListening(true)
    r.start()
  }
  const stop = () => { try { recRef.current?.stop() } catch { /* ignore */ } }
  return { supported: !!Rec, listening, start, stop }
}
