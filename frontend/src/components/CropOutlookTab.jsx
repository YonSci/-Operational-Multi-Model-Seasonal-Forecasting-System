import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import CropRegionalPanel from './CropRegionalPanel.jsx'

// Crop outlook (experimental): AquaCrop grown in every member of each forecast run at the Kenya monitored sites, sown on
// the platform's onset date, compared with the same crop in the observed seasons of 1993–2025 (crop_engine/,
// CROP_ENGINE.md). Data: tracker/data/crop/ (crop_engine/dashboard.py, published with the daily update).
const DATA = 'tracker/data/crop/'
const METHOD_URL = 'https://github.com/YonSci/-Operational-Multi-Model-Seasonal-Forecasting-System/blob/main/CROP_ENGINE.md'
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const KINDS = [
  { id: 'seasonal', label: 'Seasonal', test: s => s === 'seasonal' },
  { id: 's2s', label: 'Sub-seasonal (weeks 2–6)', test: s => s.startsWith('s2s-') },
  { id: 'medium', label: 'Medium-range (7–16 days)', test: s => s.startsWith('mr-') },
]
// Outcomes in order, best to worst: one blue ramp (validated ordinal, light and dark), darkest = matured in light mode
const GROUPS = [
  { id: 'ok', label: 'Matured', ids: ['ok'] },
  { id: 'died', label: 'Died before maturity', ids: ['died'] },
  { id: 'failed_establishment', label: 'Failed to establish', ids: ['failed_establishment'] },
  { id: 'not_grown', label: 'Not grown', ids: ['too_late', 'not_sown'] },
]
const SIMULATED = ['ok', 'died', 'failed_establishment']
const STATUS_LABEL = { ok: 'Matured', died: 'Died before maturity', failed_establishment: 'Failed to establish',
                       too_late: 'Too late to mature', not_sown: 'No sowing opportunity', error: 'Model error' }

const CSS = `
.crop-viz { --crop-fc:#3987e5; --crop-o1:#b7d3f6; --crop-o2:#6da7ec; --crop-o3:#2a78d6; --crop-o4:#184f95;
            --crop-ink1:#0f172a; --crop-ink2:#0f172a; --crop-ink3:#ffffff; --crop-ink4:#ffffff; --crop-wof:#d96a1f; }
html.light .crop-viz { --crop-fc:#2a78d6; --crop-o1:#104281; --crop-o2:#256abf; --crop-o3:#5598e7; --crop-o4:#86b6ef;
                       --crop-ink1:#ffffff; --crop-ink2:#ffffff; --crop-ink3:#0f172a; --crop-ink4:#0f172a; --crop-wof:#c2560c; }
.crop-viz select:focus-visible, .crop-viz button:focus-visible, .crop-viz summary:focus-visible { outline:2px solid var(--focus); outline-offset:2px; }
.crop-table th, .crop-table td { padding:8px 10px; text-align:left; border-bottom:1px solid var(--border-primary); white-space:nowrap; }
.crop-table th { font-size:13px; font-weight:600; color:var(--text-meta); }
.crop-table.wrap th { white-space:normal; vertical-align:bottom; }
.crop-table.wrap td:first-child { white-space:normal; min-width:200px; }
.crop-step-link { background:none; border:0; padding:0; cursor:pointer; color:var(--accent-text); font-size:13px; font-weight:600; text-align:left; }
.crop-step-link:hover { text-decoration:underline; }
.crop-table td { font-size:14px; color:var(--text-body); font-variant-numeric:tabular-nums; }
`

const getJSON = u => fetch(u).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json() })
const kindOf = source => KINDS.find(k => k.test(source)) ?? KINDS[0]
const fmtDate = iso => { if (!iso) return '—'; const [, m, d] = iso.split('-').map(Number); return `${d} ${MONTHS[m - 1]}` }
const fmtT = v => v == null ? '—' : v < 0.05 ? '0' : v.toFixed(1)
const pct = v => v == null ? '—' : `${Math.round(v * 100)}%`
const median = a => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y), h = s.length >> 1
                      return s.length % 2 ? s[h] : (s[h - 1] + s[h]) / 2 }
const effYield = (status, y) => SIMULATED.includes(status) ? (y ?? 0) : 0
const groupOf = status => GROUPS.find(g => g.ids.includes(status))?.id ?? 'not_grown'
const runLabel = r => r.source === 'seasonal' ? r.model_label : `${r.model_label} · ${fmtDate(r.run)}`
const quant = (a, q) => {                                              // linear, as numpy.quantile
  if (!a.length) return null
  const s = [...a].sort((x, y) => x - y), pos = (s.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos)
  return s[lo] + (s[hi] - s[lo]) * (pos - lo)
}
// The outcome rates of crop_engine.run_outlook.outcome_rates, each with its own denominator, from member or season
// records ({ status, y }): model errors are in none; no sowing opportunity is the rule's outcome, kept apart from
// crop failure
function rates(recs, thr) {
  const valid = recs.filter(r => r.status !== 'error'), sown = valid.filter(r => SIMULATED.includes(r.status))
  const ys = sown.map(r => r.y ?? 0)
  const rate = (k, n) => n ? k / n : null
  return { nValid: valid.length, nError: recs.length - valid.length, nSown: sown.length,
           pSowing: rate(valid.filter(r => r.status !== 'not_sown').length, valid.length),
           pEst: rate(sown.filter(r => r.status === 'failed_establishment').length, sown.length),
           pFailSown: rate(ys.filter(y => y < thr).length, sown.length),
           ySown: { median: quant(ys, 0.5), p10: quant(ys, 0.1), p90: quant(ys, 0.9) },
           pFail: rate(valid.filter(r => effYield(r.status, r.y) < thr).length, valid.length),
           pOk: rate(valid.filter(r => r.status === 'ok').length, valid.length) }
}
const km = (a, b, c, d) => {                                            // great-circle distance
  const r = Math.PI / 180, x = Math.sin((c - a) * r / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin((d - b) * r / 2) ** 2
  return 2 * 6371 * Math.asin(Math.sqrt(x))
}
const SAME_SITE_KM = 2
const LINK_KM = 25                                                     // the Forecast tab's card names a crop site within this
const TRACKER_SITES = 'tracker/data/sites.csv'                         // Near real-time rainfall tracking: one row per station
// RFC 4180 CSV (quoted fields may hold commas, e.g. "KALRO Kiboko, Makueni Farm") → [{ column: value }]
function parseCSV(text) {
  const rows = []
  let row = [], f = '', q = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (q) {
      if (c === '"') { if (text[i + 1] === '"') { f += '"'; i++ } else q = false } else f += c
    } else if (c === '"') q = true
    else if (c === ',') { row.push(f); f = '' }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++
      row.push(f); rows.push(row); row = []; f = ''
    } else f += c
  }
  if (f !== '' || row.length) { row.push(f); rows.push(row) }
  const [head, ...body] = rows.filter(r => r.length > 1 || r[0] !== '')
  return head ? body.map(r => Object.fromEntries(head.map((h, i) => [h, r[i] ?? '']))) : []
}
const useTrackerSites = () => useQuery({ queryKey: ['tracker-sites'], staleTime: 30 * 60_000, retry: false,
  queryFn: () => fetch(TRACKER_SITES).then(r => r.ok ? r.text() : '').then(parseCSV).catch(() => []) })
// the tracker's row for a crop site: by name, else the station within SAME_SITE_KM
const trackerRowOf = (rows, site) => rows?.find(r => r.site === site?.name)
  ?? rows?.find(r => site?.lat != null && km(+r.lat, +r.lon, site.lat, site.lon) <= SAME_SITE_KM)
const num = v => (v === '' || v == null || !Number.isFinite(+v)) ? null : +v
// The two crop models as a confidence signal, from their summaries of the same members (the same rule in the bulletin,
// backend/bulletin_crop.py, and CROP_ENGINE.md): agree when the yields if sown are within AGREE_T t/ha and the chances
// of failure if sown within AGREE_P; depend on the model when they differ by more than twice that; partly in between
const AGREE_T = 1.0, AGREE_P = 0.15
const AGREEMENT = {
  agree: { short: 'agree', label: 'The two crop models agree', tone: 'ok' },
  partly: { short: 'partly agree', label: 'The two crop models partly agree', tone: 'mid' },
  differ: { short: 'depends on the model', label: 'The outcome depends on the crop model', tone: 'warn' },
}
function agreementOf(a, w) {
  const ya = a?.yield_if_sown_t_ha?.median, yw = w?.yield_if_sown_t_ha?.median
  const pa = a?.p_failure_if_sown, pw = w?.p_failure_if_sown
  if (ya == null || yw == null || pa == null || pw == null) return null
  const dY = yw - ya, dP = pw - pa
  const level = Math.abs(dY) <= AGREE_T && Math.abs(dP) <= AGREE_P ? 'agree'
    : Math.abs(dY) > 2 * AGREE_T || Math.abs(dP) > 2 * AGREE_P ? 'differ' : 'partly'
  return { level, dY, dP, ...AGREEMENT[level] }
}
const TONE = { ok: { bg: 'var(--bg-surface)', fg: 'var(--heading)' }, mid: { bg: 'var(--bg-surface)', fg: 'var(--heading)' },
               warn: { bg: 'var(--caution-bg)', fg: 'var(--caution-text)' } }
const useSkill = () => useQuery({ queryKey: ['crop-skill'], staleTime: 30 * 60_000, retry: false,
                                  queryFn: () => getJSON(DATA + 'skill.json').catch(() => null) })
const r2 = v => v == null ? '—' : v.toFixed(2)
const madeNote = (made, current) => {
  if (!made) return ''
  const old = made.config_hash && current && made.config_hash !== current
  return `made ${fmtDate(made.created?.slice(0, 10))}${old ? ' with an earlier crop configuration than this outlook' : ''}`
}
const cropOf = vk => ['maize', 'sorghum', 'bean'].find(c => vk.startsWith(c)) ?? vk
// the dashboard's onset methods that are also crop sowing rules (the others are climate onsets)
const SOWING_RULE_OF = { r1: 'rule1', 'fao-agricultural': 'fao-agricultural' }
const SEASONAL_CROP_INIT = '1001ol'                                    // the crop outlook's seasonal run: Oct 01 + latest obs

function useWidth() {
  const ref = useRef(null)
  const [w, setW] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return undefined
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, w]
}

const Select = ({ label, value, onChange, children }) => (
  <label className="flex items-center gap-2" style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-meta)' }}>
    {label}
    <select value={value} onChange={e => onChange(e.target.value)}
            style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-primary)', color: 'var(--heading)', borderRadius: 8,
                     padding: '6px 10px', minHeight: 36, fontSize: 14, fontWeight: 500, cursor: 'pointer', maxWidth: 'min(100%, 340px)' }}>
      {children}
    </select>
  </label>
)

const Panel = ({ title, sub, children }) => (
  <section style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-primary)', borderRadius: 12, padding: '16px 18px', minWidth: 0 }}>
    {title && <h3 style={{ fontSize: 16, fontWeight: 600, color: 'var(--heading)', margin: 0 }}>{title}</h3>}
    {sub && <p style={{ fontSize: 13.5, color: 'var(--text-meta)', margin: '4px 0 0', lineHeight: 1.5 }}>{sub}</p>}
    <div style={{ marginTop: title || sub ? 14 : 0 }}>{children}</div>
  </section>
)

function Stat({ label, value, sub }) {
  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-primary)', borderRadius: 12, padding: '14px 16px', minWidth: 0 }}>
      <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-meta)' }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 600, color: 'var(--heading)', marginTop: 4, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
      {sub && <div style={{ fontSize: 13, color: 'var(--text-meta)', marginTop: 4, lineHeight: 1.45 }}>{sub}</div>}
    </div>
  )
}

// ── Chance of at least each yield: forecast members vs past seasons ─────────────────────────────────────────────────
const share = (vals, x) => vals.length ? vals.filter(v => v > x).length / vals.length : 0
function stepPath(vals, xs, ys, max) {
  let d = `M${xs(0)},${ys(share(vals, 0))}`
  for (const v of [...new Set(vals)].filter(v => v > 0 && v < max).sort((a, b) => a - b)) d += `H${xs(v)}V${ys(share(vals, v))}`
  return d + `H${xs(max)}`
}
function ExceedanceChart({ fc, past, threshold, fcLabel }) {
  const [ref, w] = useWidth()
  const [hx, setHx] = useState(null)
  const H = 270, m = { l: 46, r: 18, t: 30, b: 42 }
  const top = Math.max(...fc, ...past, threshold * 2, 1)
  const step = top > 8 ? 2 : top > 3 ? 1 : 0.5
  const max = Math.ceil(top / step) * step
  const iw = Math.max(0, w - m.l - m.r), ih = H - m.t - m.b
  const xs = v => m.l + v / max * iw
  const ys = p => m.t + (1 - p) * ih
  const xTicks = Array.from({ length: Math.round(max / step) + 1 }, (_, i) => +(i * step).toFixed(2))
  const series = [
    { key: 'fc', label: fcLabel, vals: fc, color: 'var(--crop-fc)', dash: null },
    { key: 'past', label: `Simulated past seasons (${past.length})`, vals: past, color: 'var(--text-meta)', dash: '6 4' },
  ]
  // direct labels where the two curves are furthest apart (the higher one above its line, the lower one below),
  // dropped when they are closer than a label's height
  const grid = Array.from({ length: 101 }, (_, i) => i / 100 * max).filter(x => x > threshold * 1.2 && x < max * 0.8)
  const xl = grid.reduce((a, x) => Math.abs(share(fc, x) - share(past, x)) > Math.abs(share(fc, a) - share(past, a)) ? x : a, grid[0] ?? max / 2)
  const yl = series.map(s => ys(share(s.vals, xl)))
  const labelsFit = Math.abs(yl[0] - yl[1]) >= 30
  const move = e => {
    const r = e.currentTarget.getBoundingClientRect()
    const v = (e.clientX - r.left - m.l) / iw * max
    setHx(v < 0 || v > max ? null : Math.round(v * 20) / 20)
  }
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <div className="flex flex-wrap gap-x-5 gap-y-1" style={{ fontSize: 13, color: 'var(--text-body)', marginBottom: 6 }}>
        {series.map(s => (
          <span key={s.key} className="inline-flex items-center gap-2">
            <svg width="22" height="8" aria-hidden="true"><line x1="1" x2="21" y1="4" y2="4" stroke={s.color} strokeWidth="2" strokeDasharray={s.dash ?? undefined} strokeLinecap="round"/></svg>
            {s.label}
          </span>
        ))}
      </div>
      {w > 0 && (
        <svg width={w} height={H} role="img" style={{ display: 'block', touchAction: 'pan-y' }}
             aria-label={`Chance of more than each yield: ${series.map(s => `${s.label} ${pct(share(s.vals, threshold))} above ${threshold} t/ha`).join('; ')}`}
             onPointerMove={move} onPointerLeave={() => setHx(null)}>
          {[0, 0.25, 0.5, 0.75, 1].map(p => (
            <g key={p}>
              <line x1={m.l} x2={m.l + iw} y1={ys(p)} y2={ys(p)} stroke="var(--chart-grid)"/>
              <text x={m.l - 8} y={ys(p) + 4} fontSize="12" textAnchor="end" fill="var(--text-meta)">{p * 100}%</text>
            </g>
          ))}
          {xTicks.map(t => <text key={t} x={xs(t)} y={m.t + ih + 18} fontSize="12" textAnchor="middle" fill="var(--text-meta)">{t}</text>)}
          <text x={m.l + iw / 2} y={H - 4} fontSize="12" textAnchor="middle" fill="var(--text-meta)">Yield (t/ha, dry grain)</text>
          <line x1={xs(threshold)} x2={xs(threshold)} y1={m.t - 6} y2={m.t + ih} stroke="var(--text-meta)" strokeDasharray="2 3"/>
          <text x={xs(threshold) + 6} y={m.t - 10} fontSize="12" fill="var(--text-meta)">crop failure below {threshold} t/ha</text>
          {series.map(s => (
            <path key={s.key} d={stepPath(s.vals, xs, ys, max)} fill="none" stroke={s.color} strokeWidth="2"
                  strokeDasharray={s.dash ?? undefined} strokeLinejoin="round"/>
          ))}
          {labelsFit && series.map((s, i) => (
            <text key={s.key} x={xs(xl)} y={yl[i] + (yl[i] < yl[1 - i] ? -8 : 17)} fontSize="12" fontWeight="600" fill="var(--text-body)"
                  textAnchor="middle" stroke="var(--bg-surface)" strokeWidth="4" paintOrder="stroke">
              {i === 0 ? 'This forecast' : 'Simulated past'}
            </text>
          ))}
          {hx != null && (
            <g pointerEvents="none">
              <line x1={xs(hx)} x2={xs(hx)} y1={m.t} y2={m.t + ih} stroke="var(--text-meta)"/>
              {series.map(s => <circle key={s.key} cx={xs(hx)} cy={ys(share(s.vals, hx))} r="5" fill={s.color} stroke="var(--bg-surface)" strokeWidth="2"/>)}
            </g>
          )}
        </svg>
      )}
      {hx != null && (
        <div style={{ position: 'absolute', top: 34, left: Math.min(Math.max(xs(hx) + 12, 0), Math.max(0, w - 230)), width: 218, pointerEvents: 'none',
                      background: 'var(--chart-tooltip-bg)', border: '1px solid var(--border-primary)', borderRadius: 8, padding: '8px 10px',
                      fontSize: 13, color: 'var(--text-body)', boxShadow: '0 4px 14px rgba(0,0,0,.18)' }}>
          <div style={{ fontWeight: 600, color: 'var(--heading)', marginBottom: 4 }}>More than {hx.toFixed(hx < 1 ? 2 : 1)} t/ha</div>
          {series.map(s => (
            <div key={s.key} className="flex justify-between gap-3">
              <span>{s.key === 'fc' ? 'This forecast' : 'Simulated past seasons'}</span>
              <span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{pct(share(s.vals, hx))}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── What happens to the crop: outcome shares, forecast vs past seasons ──────────────────────────────────────────────
function OutcomeBars({ rows }) {
  const [tip, setTip] = useState(null)
  const wrap = useRef(null)
  const show = (e, row, g, n) => {
    const r = wrap.current.getBoundingClientRect()
    setTip({ x: e.clientX - r.left, y: e.clientY - r.top, row, g, n })
  }
  return (
    <div ref={wrap} style={{ position: 'relative' }} onPointerLeave={() => setTip(null)}>
      <div className="flex flex-wrap gap-x-5 gap-y-1" style={{ fontSize: 13, color: 'var(--text-body)', marginBottom: 10 }}>
        {GROUPS.map((g, i) => (
          <span key={g.id} className="inline-flex items-center gap-2"
                title={g.id === 'not_grown' ? 'Too late to mature by 31 Mar, or no sowing opportunity by 15 Jan' : undefined}>
            <span aria-hidden="true" style={{ width: 12, height: 12, borderRadius: 3, background: `var(--crop-o${i + 1})` }}/>
            {g.label}
          </span>
        ))}
      </div>
      {rows.map(row => (
        <div key={row.label} style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 13.5, color: 'var(--text-body)', marginBottom: 4 }}>
            {row.label} <span style={{ color: 'var(--text-meta)' }}>({row.n} {row.unit})</span>
          </div>
          <div className="flex" style={{ gap: 2, height: 30, borderRadius: 4, overflow: 'hidden' }}
               aria-label={`${row.label}: ${GROUPS.map(g => `${g.label} ${pct(row.counts[g.id] / row.n)}`).join(', ')}`}>
            {GROUPS.map((g, i) => {
              const n = row.counts[g.id]
              if (!n) return null
              const p = n / row.n
              return (
                <div key={g.id} onPointerMove={e => show(e, row, g, n)}
                     style={{ flex: `${n} 1 0`, minWidth: 3, background: `var(--crop-o${i + 1})`, color: `var(--crop-ink${i + 1})`,
                              fontSize: 13, fontWeight: 600, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'default' }}>
                  {p >= 0.12 ? pct(p) : ''}
                </div>
              )
            })}
          </div>
        </div>
      ))}
      {tip && (
        <div style={{ position: 'absolute', left: Math.min(tip.x + 12, (wrap.current?.clientWidth ?? 300) - 250), top: tip.y + 14, width: 240,
                      pointerEvents: 'none', background: 'var(--chart-tooltip-bg)', border: '1px solid var(--border-primary)', borderRadius: 8,
                      padding: '8px 10px', fontSize: 13, color: 'var(--text-body)', boxShadow: '0 4px 14px rgba(0,0,0,.18)', zIndex: 2 }}>
          <div style={{ fontWeight: 600, color: 'var(--heading)' }}>{tip.g.label}: {tip.n} of {tip.row.n} ({pct(tip.n / tip.row.n)})</div>
          <div style={{ color: 'var(--text-meta)', marginTop: 2 }}>{tip.row.label}</div>
          {tip.g.id === 'not_grown' && (
            <div style={{ marginTop: 4 }}>
              {['too_late', 'not_sown'].filter(s => tip.row.raw[s]).map(s => <div key={s}>{STATUS_LABEL[s]}: {tip.row.raw[s]}</div>)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── How the canopy develops: weekly canopy cover of the sown crops, forecast band vs past seasons ───────────────────
const DAY = 86_400_000
function CanopyChart({ fc, past, nMembers }) {
  const [ref, w] = useWidth()
  const [hi, setHi] = useState(null)
  const H = 250, m = { l: 46, r: 18, t: 14, b: 34 }
  const step = fc.step_days ?? 7
  const t0 = new Date(fc.start + 'T00:00:00Z').getTime()
  const n = fc.median.length
  const span = Math.max(1, (n - 1) * step)
  const iw = Math.max(0, w - m.l - m.r), ih = H - m.t - m.b
  const xs = i => m.l + (i * step) / span * iw
  const ys = v => m.t + (1 - v) * ih
  const label = i => { const d = new Date(t0 + i * step * DAY); return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}` }
  const line = arr => arr.reduce((d, v, i) => v == null ? d : d + `${i && arr[i - 1] != null ? 'L' : 'M'}${xs(i)},${ys(v)}`, '')
  const keep = fc.median.map((_, i) => fc.p10[i] != null && fc.p90[i] != null)
  const top = fc.p90.map((v, i) => keep[i] ? `${xs(i)},${ys(v)}` : null).filter(Boolean)
  const bot = fc.p10.map((v, i) => keep[i] ? `${xs(i)},${ys(v)}` : null).filter(Boolean).reverse()
  const band = top.length ? `M${top.join('L')}L${bot.join('L')}Z` : ''
  const months = []                                                   // a tick on the 1st of each month in range
  for (let d = new Date(t0); d.getTime() <= t0 + span * DAY; d.setUTCDate(d.getUTCDate() + 1)) {
    if (d.getUTCDate() === 1) months.push({ x: m.l + (d.getTime() - t0) / DAY / span * iw, label: MONTHS[d.getUTCMonth()] })
  }
  const pastMed = past?.median?.slice(0, n)
  const series = [
    { key: 'fc', label: `This forecast: median of the sown crops (${fc.n} of ${nMembers} members); band: 8 in 10`, color: 'var(--crop-fc)', dash: null },
    ...(pastMed ? [{ key: 'past', label: `Simulated past seasons: median (${past.n} sown seasons)`, color: 'var(--text-meta)', dash: '6 4' }] : []),
  ]
  const move = e => {
    const r = e.currentTarget.getBoundingClientRect()
    const i = Math.round((e.clientX - r.left - m.l) / iw * (n - 1))
    setHi(i < 0 || i > n - 1 ? null : i)
  }
  const pc = v => v == null ? '—' : `${Math.round(v * 100)}%`
  const peak = fc.median.reduce((a, v, i) => (v ?? -1) > (fc.median[a] ?? -1) ? i : a, 0)
  const pastPeak = pastMed ? Math.max(...pastMed.filter(v => v != null)) : null
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <div className="flex flex-wrap gap-x-5 gap-y-1" style={{ fontSize: 13, color: 'var(--text-body)', marginBottom: 6 }}>
        {series.map(s => (
          <span key={s.key} className="inline-flex items-center gap-2">
            <svg width="22" height="10" aria-hidden="true">
              {s.key === 'fc' && <rect x="1" y="1" width="20" height="8" rx="2" fill="var(--crop-fc)" opacity="0.2"/>}
              <line x1="1" x2="21" y1="5" y2="5" stroke={s.color} strokeWidth="2" strokeDasharray={s.dash ?? undefined} strokeLinecap="round"/>
            </svg>
            {s.label}
          </span>
        ))}
      </div>
      {w > 0 && (
        <svg width={w} height={H} role="img" style={{ display: 'block', touchAction: 'pan-y' }}
             aria-label={`Canopy cover of the sown crops, week by week: this forecast's median peaks at ${pc(fc.median[peak])} in the week of ${label(peak)}`
                         + (pastPeak != null ? `; the simulated past seasons' median peaks at ${pc(pastPeak)}` : '')}
             onPointerMove={move} onPointerLeave={() => setHi(null)}>
          {[0, 0.25, 0.5, 0.75, 1].map(p => (
            <g key={p}>
              <line x1={m.l} x2={m.l + iw} y1={ys(p)} y2={ys(p)} stroke="var(--chart-grid)"/>
              <text x={m.l - 8} y={ys(p) + 4} fontSize="12" textAnchor="end" fill="var(--text-meta)">{p * 100}%</text>
            </g>
          ))}
          {months.map(mo => <text key={mo.label + mo.x} x={mo.x} y={m.t + ih + 20} fontSize="12" textAnchor="middle" fill="var(--text-meta)">{mo.label}</text>)}
          <path d={band} fill="var(--crop-fc)" opacity="0.18"/>
          {pastMed && <path d={line(pastMed)} fill="none" stroke="var(--text-meta)" strokeWidth="2" strokeDasharray="6 4" strokeLinejoin="round"/>}
          <path d={line(fc.median)} fill="none" stroke="var(--crop-fc)" strokeWidth="2" strokeLinejoin="round"/>
          {hi != null && (
            <g pointerEvents="none">
              <line x1={xs(hi)} x2={xs(hi)} y1={m.t} y2={m.t + ih} stroke="var(--text-meta)"/>
              {fc.median[hi] != null && <circle cx={xs(hi)} cy={ys(fc.median[hi])} r="5" fill="var(--crop-fc)" stroke="var(--bg-surface)" strokeWidth="2"/>}
              {pastMed?.[hi] != null && <circle cx={xs(hi)} cy={ys(pastMed[hi])} r="5" fill="var(--text-meta)" stroke="var(--bg-surface)" strokeWidth="2"/>}
            </g>
          )}
        </svg>
      )}
      {hi != null && (
        <div style={{ position: 'absolute', top: 30, left: Math.min(Math.max(xs(hi) + 12, 0), Math.max(0, w - 240)), width: 228, pointerEvents: 'none',
                      background: 'var(--chart-tooltip-bg)', border: '1px solid var(--border-primary)', borderRadius: 8, padding: '8px 10px',
                      fontSize: 13, color: 'var(--text-body)', boxShadow: '0 4px 14px rgba(0,0,0,.18)' }}>
          <div style={{ fontWeight: 600, color: 'var(--heading)', marginBottom: 4 }}>Week of {label(hi)}</div>
          <div className="flex justify-between gap-3"><span>This forecast</span>
            <span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{pc(fc.median[hi])}</span></div>
          <div className="flex justify-between gap-3" style={{ color: 'var(--text-meta)' }}><span>8 in 10 sown crops</span>
            <span style={{ fontVariantNumeric: 'tabular-nums' }}>{pc(fc.p10[hi])}–{pc(fc.p90[hi])}</span></div>
          {pastMed && <div className="flex justify-between gap-3"><span>Simulated past seasons</span>
            <span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{pc(pastMed[hi])}</span></div>}
        </div>
      )}
    </div>
  )
}

// ── The season at this site, step by step ────────────────────────────────────────────────────────────────────────
// Rain so far is the Near real-time rainfall tracking tab's own figure (tracker/data/sites.csv), the soil water the
// FAO water balance's, sowing, canopy and yield this crop run's: each step reads as the tab it links to does
function SeasonChain({ tr, sw, initial, summary, R, wofR, rk, ruleLabel, fao, canopy, onOpen }) {
  const rain = num(tr?.rain_since_oct1_chirps_mm), normal = num(tr?.normal_same_days_mm), pn = num(tr?.pct_of_normal)
  const peak = canopy?.median?.length ? canopy.median.reduce((a, v, i) => (v ?? -1) > (canopy.median[a] ?? -1) ? i : a, 0) : null
  const peakDate = peak == null ? null : new Date(Date.parse(canopy.start + 'T00:00:00Z') + peak * (canopy.step_days ?? 7) * DAY).toISOString().slice(0, 10)
  const go = id => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  const pl = summary?.planting
  const steps = [
    { title: 'Rain so far', kind: 'Observed', value: rain != null ? `${Math.round(rain)} mm` : '—',
      sub: rain != null ? `since 1 Oct, ${pn != null ? `${pn}% of normal` : ''}${normal != null ? ` (${Math.round(normal)} mm)` : ''}; CHIRPS to ${fmtDate(tr.through_chirps || tr.obs_through)}`
                        : 'Not in the rainfall tracking data for this site.',
      link: ['Rainfall tracking', () => onOpen('tracker')] },
    { title: 'Soil water', kind: 'Observed', value: sw ? pct(sw.paw_fraction) : pct(initial),
      sub: sw ? `of the available water on ${fmtDate(sw.date)} (FAO water balance); ${pct(initial)} on 1 Aug`
              : 'of the available water on 1 Aug (ERA5-Land); the latest day comes with the next crop run',
      link: ['FAO water balance', () => onOpen('forecast')] },
    { title: 'Sowing', kind: 'Forecast', value: pl ? fmtDate(pl.median) : '—',
      sub: pl ? `${ruleLabel}${pl.p10 !== pl.p90 ? `, 8 in 10 between ${fmtDate(pl.p10)} and ${fmtDate(pl.p90)}` : ''}; sowing opportunity ${pct(R?.pSowing)}`
                + (fao?.onset_median && rk !== 'fao-agricultural' ? `. FAO agricultural onset of this forecast: ${fmtDate(fao.onset_median)}` : '')
              : 'No sowing date for this choice.',
      link: ['Onset forecast', () => onOpen('forecast')] },
    { title: 'Crop growth', kind: 'Forecast', value: peak != null ? pct(canopy.median[peak]) : '—',
      sub: peak != null ? `canopy cover at its peak, week of ${fmtDate(peakDate)}; harvest about ${fmtDate(summary?.harvest_median)}`
                        : `harvest about ${fmtDate(summary?.harvest_median)}`,
      link: ['Canopy chart', () => go('crop-canopy')] },
    { title: 'Yield if sown', kind: 'Forecast', value: R?.nSown ? `${fmtT(R.ySown.median)} t/ha` : '—',
      sub: `AquaCrop${wofR?.nSown ? `; WOFOST ${fmtT(wofR.ySown.median)} t/ha` : ''}. Failure if sown ${pct(R?.pFailSown)}${wofR?.nSown ? ` (WOFOST ${pct(wofR.pFailSown)})` : ''}`,
      link: ['Two crop models', () => go('crop-models')] },
  ]
  return (
    <section aria-label="The season at this site, step by step" style={{ marginBottom: 18 }}>
      <h3 style={{ fontSize: 16, fontWeight: 600, color: 'var(--heading)', margin: '0 0 8px' }}>The season at this site, step by step</h3>
      <ol className="grid gap-2 grid-cols-1 sm:grid-cols-2 lg:grid-cols-5" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {steps.map((st, i) => (
          <li key={st.title} style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-primary)', borderRadius: 12, padding: '12px 14px',
                                      minWidth: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div className="flex items-center gap-2" style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-meta)' }}>
              <span aria-hidden="true" style={{ width: 22, height: 22, borderRadius: '50%', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                                                fontSize: 12, fontWeight: 700, color: '#fff', background: 'var(--btn-primary)' }}>{i + 1}</span>
              <span>{st.title}</span>
              <span style={{ marginLeft: 'auto', fontSize: 11.5, fontWeight: 600, borderRadius: 999, padding: '1px 8px',
                             color: st.kind === 'Observed' ? 'var(--heading)' : 'var(--accent-text)',
                             border: '1px solid var(--border-primary)' }}>{st.kind}</span>
            </div>
            <div style={{ fontSize: 22, fontWeight: 600, color: 'var(--heading)', fontVariantNumeric: 'tabular-nums' }}>{st.value}</div>
            <div style={{ fontSize: 13, color: 'var(--text-meta)', lineHeight: 1.45, flex: 1 }}>{st.sub}</div>
            <button type="button" className="crop-step-link" onClick={st.link[1]}>{st.link[0]} →</button>
          </li>
        ))}
      </ol>
    </section>
  )
}

// ── How the outlook has changed: one point per day its run was rebuilt (history.json, crop_engine/dashboard.py) ──
function HistoryChart({ pts, kind, thr }) {
  const [ref, w] = useWidth()
  const [hi, setHi] = useState(null)
  const H = 210, m = { l: 46, r: 18, t: 12, b: 34 }
  const iw = Math.max(0, w - m.l - m.r), ih = H - m.t - m.b
  const T = pts.map(p => Date.parse(p.date + 'T00:00:00Z'))
  const t0 = Math.min(...T), t1 = Math.max(...T)
  const xs = t => t1 > t0 ? m.l + (t - t0) / (t1 - t0) * iw : m.l + iw / 2
  const yield_ = kind === 'yield'
  const A = pts.map(p => yield_ ? p.v[0] : p.v[3]), W = pts.map(p => yield_ ? p.v[5] : p.v[6])
  const lo = pts.map(p => yield_ ? p.v[1] : null), up = pts.map(p => yield_ ? p.v[2] : null)
  const hiV = Math.max(...[...up, ...A, ...W].filter(v => v != null), 0.5)
  const step = yield_ ? [0.5, 1, 2, 2.5, 5].find(x => hiV / x <= 4) ?? 5 : 0.25      // at most 5 round ticks
  const top = yield_ ? Math.ceil(hiV / step) * step : 1
  const ys = v => m.t + (1 - v / top) * ih
  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, i) => +(i * step).toFixed(2))
  const fmt = v => v == null ? '—' : yield_ ? `${fmtT(v)} t/ha` : pct(v)
  // a change of the crop model's configuration breaks the lines: the points before it are another model's
  const segs = []
  pts.forEach((p, i) => { if (!i || p.config !== pts[i - 1].config) segs.push([]); segs[segs.length - 1].push(i) })
  const breaks = segs.slice(1).map(g => (xs(T[g[0] - 1]) + xs(T[g[0]])) / 2)
  const path = (arr, idx) => idx.reduce((d, i) => arr[i] == null ? d : d + `${d ? 'L' : 'M'}${xs(T[i])},${ys(arr[i])}`, '')
  const band = idx => {
    const k = idx.filter(i => lo[i] != null && up[i] != null)
    return k.length > 1 ? `M${k.map(i => `${xs(T[i])},${ys(up[i])}`).join('L')}L${k.reverse().map(i => `${xs(T[i])},${ys(lo[i])}`).join('L')}Z` : ''
  }
  const labelEvery = Math.max(1, Math.ceil(pts.length / Math.max(1, Math.floor(iw / 70))))
  const move = e => {
    const r = e.currentTarget.getBoundingClientRect(), x = e.clientX - r.left
    let best = 0
    T.forEach((t, i) => { if (Math.abs(xs(t) - x) < Math.abs(xs(T[best]) - x)) best = i })
    setHi(best)
  }
  const title = yield_ ? 'Yield if sown (median of the sown crops)' : `Chance of crop failure if sown (yield below ${thr} t/ha)`
  return (
    <div ref={ref} style={{ position: 'relative', minWidth: 0 }}>
      <h4 style={{ fontSize: 14, fontWeight: 600, color: 'var(--heading)', margin: '0 0 6px' }}>{title}</h4>
      {w > 0 && (
        <svg width={w} height={H} role="img" style={{ display: 'block', touchAction: 'pan-y' }}
             aria-label={`${title}, by the day the outlook was made: AquaCrop ${fmt(A[A.length - 1])}, WOFOST ${fmt(W[W.length - 1])} on ${fmtDate(pts[pts.length - 1].date)}`}
             onPointerMove={move} onPointerLeave={() => setHi(null)}>
          {ticks.map(v => (
            <g key={v}>
              <line x1={m.l} x2={m.l + iw} y1={ys(v)} y2={ys(v)} stroke="var(--chart-grid)"/>
              <text x={m.l - 8} y={ys(v) + 4} fontSize="12" textAnchor="end" fill="var(--text-meta)">{yield_ ? v : `${v * 100}%`}</text>
            </g>
          ))}
          {pts.map((p, i) => i % labelEvery === 0 && (
            <text key={p.date} x={xs(T[i])} y={m.t + ih + 20} fontSize="12" textAnchor="middle" fill="var(--text-meta)">{fmtDate(p.date)}</text>
          ))}
          {breaks.map(x => (
            <g key={x}>
              <line x1={x} x2={x} y1={m.t} y2={m.t + ih} stroke="var(--text-meta)" strokeDasharray="3 3"/>
              <text x={x + 4} y={m.t + 11} fontSize="11.5" fill="var(--text-meta)">crop model updated</text>
            </g>
          ))}
          {segs.map(g => <path key={'b' + g[0]} d={band(g)} fill="var(--crop-fc)" opacity="0.16"/>)}
          {segs.map(g => <path key={'w' + g[0]} d={path(W, g)} fill="none" stroke="var(--crop-wof)" strokeWidth="2" strokeDasharray="6 4" strokeLinejoin="round"/>)}
          {segs.map(g => <path key={'a' + g[0]} d={path(A, g)} fill="none" stroke="var(--crop-fc)" strokeWidth="2" strokeLinejoin="round"/>)}
          {pts.map((p, i) => (
            <g key={'p' + p.date}>
              {W[i] != null && <rect x={xs(T[i]) - 4} y={ys(W[i]) - 4} width="8" height="8" fill="var(--crop-wof)" stroke="var(--bg-surface)" strokeWidth="2"/>}
              {A[i] != null && <circle cx={xs(T[i])} cy={ys(A[i])} r={hi === i ? 6 : 4.5} fill="var(--crop-fc)" stroke="var(--bg-surface)" strokeWidth="2"/>}
            </g>
          ))}
          {hi != null && <line x1={xs(T[hi])} x2={xs(T[hi])} y1={m.t} y2={m.t + ih} stroke="var(--text-meta)" pointerEvents="none"/>}
        </svg>
      )}
      {hi != null && (
        <div style={{ position: 'absolute', top: 34, left: Math.min(Math.max(xs(T[hi]) + 12, 0), Math.max(0, w - 240)), width: 228, pointerEvents: 'none',
                      background: 'var(--chart-tooltip-bg)', border: '1px solid var(--border-primary)', borderRadius: 8, padding: '8px 10px',
                      fontSize: 13, color: 'var(--text-body)', boxShadow: '0 4px 14px rgba(0,0,0,.18)' }}>
          <div style={{ fontWeight: 600, color: 'var(--heading)', marginBottom: 4 }}>Outlook of {fmtDate(pts[hi].date)}</div>
          <div style={{ color: 'var(--text-meta)', marginBottom: 4 }}>Observations to {fmtDate(pts[hi].obs)}</div>
          <div className="flex justify-between gap-3"><span>AquaCrop</span><span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{fmt(A[hi])}</span></div>
          {yield_ && lo[hi] != null && <div className="flex justify-between gap-3" style={{ color: 'var(--text-meta)' }}><span>8 in 10 sown crops</span>
            <span style={{ fontVariantNumeric: 'tabular-nums' }}>{fmtT(lo[hi])}–{fmtT(up[hi])} t/ha</span></div>}
          <div className="flex justify-between gap-3"><span>WOFOST</span><span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{fmt(W[hi])}</span></div>
        </div>
      )}
    </div>
  )
}

function HistoryPanel({ hist, loading, source, sid, vk, rk, thr, msg }) {
  const pts = (hist?.sources?.[source] ?? []).map(e => ({ date: e.date, obs: e.obs_end, config: e.config, v: e.cells?.[sid]?.[vk]?.[rk] }))
    .filter(p => p.v)
  const sub = 'Each point is the outlook as made on that day, from the observations then available: how it has moved as the season '
            + 'unfolds. A point is added each day the run is rebuilt (new observations or a new crop model).'
  if (loading) return <Panel title="How this outlook has changed" sub={sub}>{msg('Loading…')}</Panel>
  if (!pts.length) return <Panel title="How this outlook has changed" sub={sub}>{msg('The record of this outlook starts with the next daily update.')}</Panel>
  return (
    <Panel title="How this outlook has changed" sub={sub}>
      <div className="flex flex-wrap gap-x-5 gap-y-1" style={{ fontSize: 13, color: 'var(--text-body)', marginBottom: 8 }}>
        <span className="inline-flex items-center gap-2">
          <svg width="22" height="12" aria-hidden="true"><rect x="1" y="2" width="20" height="8" rx="2" fill="var(--crop-fc)" opacity="0.2"/>
            <line x1="1" x2="21" y1="6" y2="6" stroke="var(--crop-fc)" strokeWidth="2"/><circle cx="11" cy="6" r="3.5" fill="var(--crop-fc)"/></svg>
          AquaCrop, the published outlook (band: 8 in 10 sown crops)
        </span>
        <span className="inline-flex items-center gap-2">
          <svg width="22" height="12" aria-hidden="true"><line x1="1" x2="21" y1="6" y2="6" stroke="var(--crop-wof)" strokeWidth="2" strokeDasharray="6 4"/>
            <rect x="7.5" y="2.5" width="7" height="7" fill="var(--crop-wof)"/></svg>
          WOFOST, the second model
        </span>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <HistoryChart pts={pts} kind="yield" thr={thr}/>
        <HistoryChart pts={pts} kind="fail" thr={thr}/>
      </div>
      <p style={{ fontSize: 13, color: 'var(--text-meta)', margin: '8px 0 0', lineHeight: 1.5 }}>
        {pts.length === 1 ? `Recorded from ${fmtDate(pts[0].date)}: one point so far.` : `${pts.length} outlooks, ${fmtDate(pts[0].date)} to ${fmtDate(pts[pts.length - 1].date)}.`}
        {' '}A dashed vertical line marks a change of the crop model (calibration or configuration): the points before it are not comparable with those after.
      </p>
    </Panel>
  )
}

// ── The two crop models as a confidence signal ───────────────────────────────────────────────────────────────────
function ModelAgreement({ a, w, share, vk }) {
  const g = agreementOf(a, w)
  if (!g) return (
    <p style={{ fontSize: 13.5, color: 'var(--text-meta)', margin: '10px 0 0', lineHeight: 1.5 }}>
      {cropOf(vk) === 'bean' ? 'One crop model only: WOFOST has no dry bean, so there is no second opinion on this crop.'
                             : 'No second crop model for this run, so there is no second opinion on it.'}
    </p>)
  const t = TONE[g.tone]
  const yA = a.yield_if_sown_t_ha.median, yW = w.yield_if_sown_t_ha.median
  return (
    <div role="status" className="flex flex-wrap items-center gap-x-3 gap-y-1"
         style={{ marginTop: 10, background: t.bg, color: t.fg, border: '1px solid var(--border-primary)', borderRadius: 10, padding: '9px 14px',
                  fontSize: 14, lineHeight: 1.5 }}>
      <strong>{g.label}.</strong>
      <span style={{ color: g.tone === 'warn' ? t.fg : 'var(--text-body)' }}>
        Yield if sown {fmtT(yA)} t/ha (AquaCrop) and {fmtT(yW)} t/ha (WOFOST); failure if sown {pct(a.p_failure_if_sown)} and {pct(w.p_failure_if_sown)}
        {share != null ? `; they agree on whether the crop fails in ${pct(share)} of the members` : ''}.
        {g.level === 'differ' ? ' Read this outlook with care: the answer here rests on the model as much as on the forecast.'
          : g.level === 'agree' ? ' The outcome rests less on the choice of model.' : ''}
      </span>
    </div>
  )
}

// ── How well past forecasts did, for this site and crop (skill.json, crop_engine/dashboard.py write_skill) ──
function SkillLine({ skill, source, sid, vk, rk }) {
  if (source === 'seasonal') {
    const c = skill?.seasonal?.sites?.[sid]?.[vk]?.[rk]
    if (!c?.aquacrop) return null
    const m = skill.seasonal.made ?? {}
    const best = [['season length', c.lgp], ['Oct–Dec rain', c.rain], ['onset', c.onset]].filter(([, x]) => x?.r != null)
    return (
      <p style={{ fontSize: 13.5, color: 'var(--text-meta)', margin: '8px 0 0', lineHeight: 1.5 }}>
        <strong style={{ color: 'var(--text-body)' }}>How past forecasts did</strong> (SEAS5 1 Oct, {m.aquacrop?.years?.join('–')}): rank correlation with
        the crop grown in the observed weather {r2(c.aquacrop.r)} (AquaCrop){c.wofost ? `, ${r2(c.wofost.r)} (WOFOST)` : ''}, failure ROC area
        {' '}{r2(c.aquacrop.auc)}{c.wofost ? ` / ${r2(c.wofost.auc)}` : ''}. The platform’s own forecasts read as yield predictors:
        {' '}{best.map(([k, x]) => `${k} ${r2(x.r)}`).join(', ')}. 1 is a perfect ranking, 0 none; with {c.aquacrop.n} years a value is uncertain
        by about ±0.2 ({madeNote(m.aquacrop, skill.seasonal.current_config)}; Forecast performance tab).
      </p>)
  }
  if (source === 's2s-ecmwf' && rk === 'rule1') {
    const c = skill?.s2s?.sites?.[sid]?.[vk]
    if (!c) return null
    return (
      <p style={{ fontSize: 13.5, color: 'var(--text-meta)', margin: '8px 0 0', lineHeight: 1.5 }}>
        <strong style={{ color: 'var(--text-body)' }}>How past forecasts did</strong> (ECMWF extended-range reforecasts {skill.s2s.years?.join('–')},
        AquaCrop): rank correlation with the crop grown in the observed weather, observations only → with the forecast’s 46-day rain:
        {' '}{Object.entries(c).map(([md, x]) => `${fmtDate('2026-' + md)} ${r2(x.reference?.r)} → ${r2(x.forecast?.r)}`).join('; ')}.
      </p>)
  }
  return null
}

// ── The Forecast performance tab's card: crop skill at the crop site nearest the map's location ──────────────────────
export function CropSkillPanel({ selectedSite, onOpen }) {
  const idx = useQuery({ queryKey: ['crop-index'], queryFn: () => getJSON(DATA + 'index.json'), staleTime: 30 * 60_000, retry: false })
  const sk = useSkill()
  const ix = idx.data, skill = sk.data
  if (!ix || !skill?.seasonal || !selectedSite || !Number.isFinite(+selectedSite.lat)) return null
  const near = Object.keys(ix.sites ?? {}).filter(id => ix.sites[id].lat != null && skill.seasonal.sites?.[id])
    .map(id => ({ id, d: km(+selectedSite.lat, +selectedSite.lon, ix.sites[id].lat, ix.sites[id].lon) })).sort((a, b) => a.d - b.d)[0]
  if (!near) return null
  const site = ix.sites[near.id], cells = skill.seasonal.sites[near.id], m = skill.seasonal.made ?? {}
  const rows = ['maize_early', 'sorghum'].filter(vk => cells[vk]).flatMap(vk => Object.keys(ix.planting_rules ?? {})
    .filter(rk => cells[vk][rk]).map(rk => ({ vk, rk, c: cells[vk][rk] })))
  const s2s = skill.s2s?.sites?.[near.id]
  const th = { padding: '6px 8px', textAlign: 'left', fontSize: 12.5, fontWeight: 600, color: 'var(--text-meta)', borderBottom: '1px solid var(--border-primary)', whiteSpace: 'nowrap' }
  const td = { padding: '6px 8px', fontSize: 13.5, color: 'var(--text-body)', borderBottom: '1px solid var(--border-primary)', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }
  return (
    <section style={{ margin: '12px 0 0', background: 'var(--bg-surface)', border: '1px solid var(--border-primary)', borderRadius: 12, padding: '14px 16px', minWidth: 0 }}>
      <h3 style={{ fontSize: 15, fontWeight: 600, color: 'var(--heading)', margin: 0 }}>
        Crop outlook: how past forecasts did at {site.name}{near.d > LINK_KM ? ` (nearest crop site, ${Math.round(near.d)} km away)` : ''}
      </h3>
      <p style={{ fontSize: 13, color: 'var(--text-meta)', margin: '4px 0 10px', lineHeight: 1.5 }}>
        The 1 Oct SEAS5 forecasts of {m.aquacrop?.years?.join('–')} grown by each crop model, against the same model’s crop in the observed weather:
        the rank correlation of the yields (1: a perfect ranking, 0: none) and the failure ROC area (0.5: no skill). Beside them, the
        platform’s own season-length, Oct–Dec rain and onset forecasts read as yield predictors, scored the same way.
      </p>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr><th style={th}>Crop, sowing rule</th><th style={th}>AquaCrop</th><th style={th}>WOFOST</th>
            <th style={th}>Season length</th><th style={th}>Oct–Dec rain</th><th style={th}>Onset</th><th style={th}>Failure ROC, AquaCrop / WOFOST</th></tr></thead>
          <tbody>
            {rows.map(({ vk, rk, c }) => (
              <tr key={vk + rk}>
                <td style={{ ...td, whiteSpace: 'normal' }}>{ix.varieties?.[vk]?.label ?? vk}, {ix.planting_rules[rk]}</td>
                <td style={{ ...td, fontWeight: 600 }}>{r2(c.aquacrop?.r)}</td><td style={{ ...td, fontWeight: 600 }}>{r2(c.wofost?.r)}</td>
                <td style={td}>{r2(c.lgp?.r)}</td><td style={td}>{r2(c.rain?.r)}</td><td style={td}>{r2(c.onset?.r)}</td>
                <td style={td}>{r2(c.aquacrop?.auc)} / {r2(c.wofost?.auc)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {s2s && (
        <p style={{ fontSize: 13, color: 'var(--text-meta)', margin: '10px 0 0', lineHeight: 1.5 }}>
          Sub-seasonal (ECMWF extended-range reforecasts {skill.s2s.years?.join('–')}, early maize, rule 1), rank correlation, observations only → with
          the forecast’s 46-day rain: {Object.entries(s2s.maize_early ?? {}).map(([md, x]) => `${fmtDate('2026-' + md)} ${r2(x.reference?.r)} → ${r2(x.forecast?.r)}`).join('; ')}.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2" style={{ marginTop: 10 }}>
        <span style={{ fontSize: 12.5, color: 'var(--text-meta)', flex: '1 1 320px' }}>
          Against the crop simulated in the observed weather, not measured yields; {rows[0]?.c?.aquacrop?.n ?? 24} years, so a value is uncertain by about ±0.2.
          AquaCrop’s scores {madeNote(m.aquacrop, skill.seasonal.current_config)}; WOFOST’s {madeNote(m.wofost)}.
        </span>
        <button type="button" onClick={() => onOpen({ lat: site.lat, lon: site.lon, site_name: site.name })}
                style={{ background: 'none', border: '1px solid var(--border-primary)', color: 'var(--accent-text)', borderRadius: 8, padding: '6px 12px',
                         fontSize: 13.5, fontWeight: 600, cursor: 'pointer', minHeight: 34 }}>
          Open the Crop outlook →
        </button>
      </div>
    </section>
  )
}

// ── The Forecast tab's card: the crop outlook at (or nearest to) the location on the map, and a way there ──────────
export function CropSiteLink({ selectedSite, onsetDef, onOpen }) {
  const idx = useQuery({ queryKey: ['crop-index'], queryFn: () => getJSON(DATA + 'index.json'), staleTime: 30 * 60_000, retry: false })
  const ix = idx.data
  if (!ix || !selectedSite || !Number.isFinite(+selectedSite.lat)) return null
  const near = Object.keys(ix.sites ?? {}).filter(id => ix.sites[id].lat != null)
    .map(id => ({ id, d: km(+selectedSite.lat, +selectedSite.lon, ix.sites[id].lat, ix.sites[id].lon) })).sort((a, b) => a.d - b.d)[0]
  if (!near) return null
  const site = ix.sites[near.id], run = (ix.runs ?? []).find(r => r.source === 'seasonal')
  const rk = ix.planting_rules?.[SOWING_RULE_OF[onsetDef]] ? SOWING_RULE_OF[onsetDef] : ix.planting_rules?.['fao-agricultural'] ? 'fao-agricultural' : Object.keys(ix.planting_rules ?? {})[0]
  const vk = ix.varieties?.maize_early ? 'maize_early' : Object.keys(ix.varieties ?? {})[0]
  const sm = ix.summaries?.[run?.id]?.[near.id]?.[vk]?.[rk], w = ix.wofost?.[run?.id]?.[near.id]?.[vk]?.[rk]
  const here = near.d <= LINK_KM
  return (
    <div role="note" className="flex flex-wrap items-center gap-x-4 gap-y-2"
         style={{ margin: '0 0 10px', background: 'var(--bg-surface)', border: '1px solid var(--border-primary)', borderRadius: 10,
                  padding: '10px 14px', fontSize: 14, color: 'var(--text-body)', lineHeight: 1.5 }}>
      <span style={{ flex: '1 1 420px', minWidth: 0 }}>
        <strong style={{ color: 'var(--heading)' }}>Crop outlook {here ? `at ${site.name}` : `(nearest crop site: ${site.name}, ${Math.round(near.d)} km away)`}:</strong>{' '}
        {sm ? <>{ix.varieties[vk].label.toLowerCase()} sown by {ix.planting_rules[rk]}, yield if sown {sm.yield_if_sown_t_ha ? `${fmtT(sm.yield_if_sown_t_ha.median)} t/ha` : '—'}
              {w?.yield_if_sown_t_ha ? ` (WOFOST ${fmtT(w.yield_if_sown_t_ha.median)})` : ''}, failure if sown {pct(sm.p_failure_if_sown)} (seasonal forecast)
              {agreementOf(sm, w) ? `; ${agreementOf(sm, w).label.charAt(0).toLowerCase() + agreementOf(sm, w).label.slice(1)}` : ''}.</>
            : 'not available for this site yet.'}
      </span>
      <button type="button" onClick={() => onOpen({ lat: site.lat, lon: site.lon, site_name: site.name })}
              style={{ background: 'var(--btn-primary)', color: '#fff', border: 0, borderRadius: 8, padding: '7px 12px', fontSize: 13.5,
                       fontWeight: 600, cursor: 'pointer', minHeight: 36 }}>
        Open the Crop outlook →
      </button>
    </div>
  )
}

const countOutcomes = statuses => {
  const raw = {}, counts = Object.fromEntries(GROUPS.map(g => [g.id, 0]))
  for (const s of statuses) { raw[s] = (raw[s] ?? 0) + 1; counts[groupOf(s)] += 1 }
  return { raw, counts }
}

// ── The tab ─────────────────────────────────────────────────────────────────────────────────────────────────────────
// ── Management scenarios: the seasonal run's crops grown again with one choice changed ──────────────────────────
// the change between two yields as shown (fmtT's one decimal), so 3.9 against 3.8 reads +0.1, never "same"
const fmtDiff = (a, b) => {
  if (a == null || b == null) return ''
  const d = Math.round(Number(fmtT(a)) * 10) - Math.round(Number(fmtT(b)) * 10)
  return d === 0 ? ' (same)' : ` (${d > 0 ? '+' : '−'}${(Math.abs(d) / 10).toFixed(1)})`
}
// The scenario amounts are assumptions: farm managers at the sites are asked what is used there. PARTNER_FORM_URL is the
// online form (Google Forms); empty, only the PDF of the questions is offered.
const PARTNER_PDF = 'docs/crop_scenario_questions_for_partners.pdf'
const PARTNER_FORM_URL = 'https://docs.google.com/forms/d/e/1FAIpQLSeSm0ZhEjV3MhBCayBJEdrwtgLh2iBfyzd-b90o56vXo9B9vw/viewform'
function PartnerAsk() {
  const link = { color: 'var(--accent-text)', fontWeight: 600 }
  return (
    <div role="note" style={{ marginTop: 12, border: '1px solid var(--border-primary)', background: 'var(--bg-elevated)', borderRadius: 8,
                              padding: '10px 14px', fontSize: 14, color: 'var(--text-body)', lineHeight: 1.55 }}>
      <strong style={{ color: 'var(--heading)' }}>These amounts are our assumptions.</strong> Farm managers and agronomists at the
      monitored sites: tell us how much water farmers near you can apply in a season, how much residue they leave and which ridges or
      pits they use, and the scenarios will be set to match.{' '}
      {PARTNER_FORM_URL && <><a href={PARTNER_FORM_URL} target="_blank" rel="noreferrer" style={link}>Answer the online form</a>{' or '}</>}
      <a href={PARTNER_PDF} target="_blank" rel="noreferrer" style={link}>{PARTNER_FORM_URL ? 'download the questions (PDF)' : 'Download the questions (PDF)'}</a>
      {PARTNER_FORM_URL ? '.' : ', fill in the table for your site and return it to the platform team.'}
    </div>
  )
}

function ScenarioPanel({ data, loading, seasonal, sid, vk, rk, ruleLabel, msg }) {
  const sub = 'The seasonal forecast’s crops grown again in the same weather members with one management choice changed. '
            + 'The first row is the outlook above.'
  if (!seasonal) return <Panel title="Management scenarios" sub={sub}>{msg('Scenarios are made for the seasonal forecast only: choose ECMWF SEAS5 under Forecast.')}<PartnerAsk/></Panel>
  if (loading) return <Panel title="Management scenarios" sub={sub}>{msg('Loading…')}</Panel>
  const cell = data?.sites?.[sid]?.results?.[vk]?.[rk]
  if (!cell) return <Panel title="Management scenarios" sub={sub}>{msg(data ? 'No scenarios for this site, crop and rule yet.'
                                                                             : 'The scenarios come with the next weekly crop run.')}<PartnerAsk/></Panel>
  const meta = data.meta, base = cell.baseline, baseW = cell.baseline_wofost
  const groups = [...new Set(Object.values(meta.scenarios).map(s => s.group))]
  const row = (key, label, s, strong) => (
    <tr key={key}>
      <td style={{ fontWeight: strong ? 600 : 400, color: strong ? 'var(--heading)' : undefined }}>
        {label}
        {s.irrigation_mm_median > 0 && <div style={{ fontSize: 12, color: 'var(--text-meta)' }}>
          {Math.round(s.irrigation_mm_median)} mm of irrigation (median of the sown crops)</div>}
      </td>
      <td>{s.planting?.p10 === s.planting?.p90 ? fmtDate(s.planting?.median) : `${fmtDate(s.planting?.p10)} – ${fmtDate(s.planting?.p90)}`}</td>
      <td>{pct(s.p_sowing_opportunity)}</td>
      <td>{s.yield_if_sown_t_ha?.median != null ? `${fmtT(s.yield_if_sown_t_ha.median)} t/ha` : '—'}</td>
      <td>{s.yield_if_sown_t_ha?.median != null ? `${fmtT(s.yield_if_sown_t_ha.p10)}–${fmtT(s.yield_if_sown_t_ha.p90)} t/ha` : '—'}</td>
      <td>{pct(s.p_failure_if_sown)}</td>
      <td>{pct((s.share?.too_late ?? 0))}</td>
      <td>{fmtT(s.yield_t_ha?.median)} t/ha{strong ? '' : fmtDiff(s.yield_t_ha?.median, base.yield_t_ha?.median)}</td>
      {baseW && <td>{(() => {
        const w = strong ? baseW : s.wofost
        if (!w) return '—'
        return `${fmtT(w.yield_t_ha?.median)} t/ha${strong ? '' : fmtDiff(w.yield_t_ha?.median, baseW.yield_t_ha?.median)}`
      })()}</td>}
    </tr>
  )
  return (
    <Panel title="Management scenarios"
           sub={`${sub} Sowing rule: ${ruleLabel}. Made from observations to ${fmtDate(meta.obs_end)}, refreshed weekly.`}>
      <div style={{ overflowX: 'auto' }}>
        <table className="crop-table wrap" style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr><th>Scenario</th><th>Sowing (8 in 10)</th><th>Sowing opportunity</th><th>Yield if sown</th><th>8 in 10 sown</th>
                <th>Failure if sown</th><th>Too late</th><th>Median yield, all members</th>
                {baseW && <th>WOFOST: median yield, all members</th>}</tr>
          </thead>
          <tbody>
            {row('baseline', 'As the outlook', base, true)}
            {groups.map(g => [
              <tr key={g}><td colSpan={baseW ? 9 : 8} style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-meta)', paddingTop: 14 }}>{g}</td></tr>,
              ...Object.entries(meta.scenarios).filter(([k, s]) => s.group === g && cell[k]).map(([k, s]) => row(k, s.label, cell[k], false)),
            ])}
          </tbody>
        </table>
      </div>
      <p style={{ fontSize: 13, color: 'var(--text-meta)', margin: '8px 0 0', lineHeight: 1.5 }}>
        Median yield over all members counts a member with no crop as zero; in brackets, the change from the outlook. A shifted sowing
        keeps members with no sowing opportunity unsown; a calendar sowing sows every member on that date, rain or not. Plant density
        changes only how fast the canopy closes (AquaCrop-OSPy sets the initial canopy from it), not the maximum canopy calibrated at
        Kiboko. Soil water on 1 Aug replaces the ERA5-Land value. Supplementary irrigation waters the crop whenever its root zone
        falls below 30 % of its available water from sowing to flowering, at most 100 mm a season reaching the soil (about 130 mm
        drawn at 75 % efficiency); full irrigation keeps it above 70 % throughout, the yield with water no longer limiting. Mulch
        covers half the soil with residues, halving evaporation there; tied ridges or pits let no rain run off the field.
        {baseW && <> The last column is WOFOST, the second crop model, grown with the same choice (plant density is AquaCrop’s
        only: WOFOST has no plant population); where the two models agree on a practice’s gain, it depends less on the model.</>}
      </p>
      <PartnerAsk/>
    </Panel>
  )
}

// The dashboard's own choices (season, seasonal run, onset method, forecast type and model) set the defaults here; a
// choice the crop outlook cannot follow is named in a notice, never replaced silently
// ── Two crop models on the same members: AquaCrop (published) and WOFOST (second model) ─────────────────────────────
function EnginePanel({ aqua, wof, v, vk, why, past, pastWof }) {
  if (!wof) {
    const reason = why ?? (cropOf(vk) === 'bean' ? 'WOFOST has no dry bean crop set, so the bean is grown by AquaCrop only.'
      : 'This run was made before the second model was added, or without its radiation, humidity and wind.')
    return <p style={{ fontSize: 14, color: 'var(--text-meta)', margin: 0, lineHeight: 1.55 }}>{reason}</p>
  }
  const thr = v.failure_t_ha
  const ra = rates(aqua.map(m => ({ status: m[3], y: m[2] })), thr)
  const rw = rates(wof.map(m => ({ status: m[3], y: m[2] })), thr)
  const harvest = ms => median(ms.filter(m => SIMULATED.includes(m[3]) && m[1]).map(m => Date.parse(m[1])))
  const pairs = aqua.map((m, i) => [m, wof[i]]).filter(([a, w]) => w && a[3] !== 'error' && w[3] !== 'error')
  const agree = pairs.length ? pairs.filter(([a, w]) => (effYield(a[3], a[2]) < thr) === (effYield(w[3], w[2]) < thr)).length / pairs.length : null
  const d = rw.ySown.median != null && ra.ySown.median != null ? rw.ySown.median - ra.ySown.median : null
  const rows = [['AquaCrop (the published outlook)', ra, harvest(aqua)], ['WOFOST (second model)', rw, harvest(wof)]]
  const seasonRates = s => rates(s.map(x => ({ status: x[4], y: x[3] })), thr)
  const pastRows = [past && ['AquaCrop, simulated past seasons', seasonRates(past), null],
                    pastWof && ['WOFOST, simulated past seasons', seasonRates(pastWof), null]].filter(Boolean)
  const iso = t => t == null ? null : new Date(t).toISOString().slice(0, 10)
  return (
    <>
      <div style={{ overflowX: 'auto' }}>
        <table className="crop-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr><th>Crop model</th><th>Yield if sown</th><th>8 in 10 sown</th><th>Failure if sown</th><th>Matured</th><th>Harvest</th></tr></thead>
          <tbody>
            {[...rows, ...pastRows].map(([label, r, h], i) => (
              <tr key={label}>
                <td style={{ fontWeight: i < 2 ? 600 : 400, color: i < 2 ? 'var(--heading)' : undefined }}>{label}</td>
                <td>{r.nSown ? `${fmtT(r.ySown.median)} t/ha` : '—'}</td>
                <td>{r.nSown ? `${fmtT(r.ySown.p10)}–${fmtT(r.ySown.p90)} t/ha` : '—'}</td>
                <td>{pct(r.pFailSown)}</td>
                <td>{pct(r.pOk)}</td>
                <td>{fmtDate(iso(h))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p style={{ fontSize: 13.5, color: 'var(--text-meta)', margin: '10px 0 0', lineHeight: 1.5 }}>
        {d == null ? 'No sown crop to compare.'
          : Math.abs(d) < 0.25 ? 'The two models give about the same yield for the sown crops. '
          : `WOFOST’s median yield of the sown crops is ${fmtT(Math.abs(d))} t/ha ${d < 0 ? 'lower' : 'higher'} than AquaCrop’s. `}
        {agree != null && `They agree on whether a member’s crop fails for ${pct(agree)} of the members. `}
        {pastRows.length === 2 && 'Each model is also grown in the observed weather of the same past seasons, so each forecast can be read against its own model’s normal. '}
        Same weather, soil, starting water and sowing dates; only the crop model differs, so the gap between them is part of the
        uncertainty the forecast does not show on its own. WOFOST’s maize yield level is calibrated to the same Kiboko trial as
        AquaCrop’s, and its sorghum to AquaCrop’s own sorghum level; it has no dry bean.
      </p>
    </>
  )
}

export default function CropOutlookTab({ country, selectedSite, season, initId, initLabel, onsetDef, onsetLabel,
                                         forecastType, mrfModel, s2sModel, onOpenTab }) {
  const idx = useQuery({ queryKey: ['crop-index'], queryFn: () => getJSON(DATA + 'index.json'), staleTime: 30 * 60_000 })
  const bench = useQuery({ queryKey: ['crop-benchmark'], queryFn: () => getJSON(DATA + 'benchmark.json'), staleTime: 30 * 60_000 })
  const ix = idx.data
  const runs = useMemo(() => (ix?.runs ?? []).slice().sort((a, b) =>
    KINDS.indexOf(kindOf(a.source)) - KINDS.indexOf(kindOf(b.source)) || runLabel(a).localeCompare(runLabel(b))), [ix])
  const siteIds = Object.keys(ix?.sites ?? {})
  // the map's location: a crop site by name or within SAME_SITE_KM; otherwise the nearest, named as such below
  const near = useMemo(() => {
    if (!ix || !selectedSite) return null
    const byName = siteIds.find(id => ix.sites[id].name === selectedSite.site_name)
    if (byName) return { id: byName, km: 0 }
    if (!Number.isFinite(+selectedSite.lat) || !Number.isFinite(+selectedSite.lon)) return null
    return siteIds.filter(id => ix.sites[id].lat != null)
      .map(id => ({ id, km: km(+selectedSite.lat, +selectedSite.lon, ix.sites[id].lat, ix.sites[id].lon) }))
      .sort((a, b) => a.km - b.km)[0] ?? null
  }, [ix, selectedSite])                                                // eslint-disable-line react-hooks/exhaustive-deps
  const [siteId, setSiteId] = useState(null)
  const [variety, setVariety] = useState('maize_early')
  const [rule, setRule] = useState(null)                               // null: follow the dashboard's onset method
  const [runId, setRunId] = useState(null)                             // null: follow the dashboard's forecast
  const sid = siteIds.includes(siteId) ? siteId
    : near?.id ?? (siteIds.includes('kalro_kiboko_makueni_farm') ? 'kalro_kiboko_makueni_farm' : siteIds[0])
  const vk = ix?.varieties?.[variety] ? variety : Object.keys(ix?.varieties ?? {})[0]
  const rules = ix?.planting_rules ?? {}
  const mainRule = SOWING_RULE_OF[onsetDef]
  const rk = rules[rule] ? rule : rules[mainRule] ? mainRule : rules['fao-agricultural'] ? 'fao-agricultural' : Object.keys(rules)[0]
  const mainSource = forecastType === 'medium' ? `mr-${mrfModel}` : forecastType === 'subseasonal' ? s2sModel : 'seasonal'
  const mainRun = runs.find(r => r.source === mainSource)
  const run = runs.find(r => r.id === runId) ?? mainRun ?? runs[0]
  const runQ = useQuery({ queryKey: ['crop-run', run?.id], enabled: !!run, staleTime: 30 * 60_000,
                          queryFn: () => getJSON(DATA + (run.file ?? run.source + '.json')) })
  // management scenarios of the seasonal run (crop_engine/run_scenarios.py); absent until first made
  const scenQ = useQuery({ queryKey: ['crop-scenarios'], staleTime: 30 * 60_000, retry: false,
                           queryFn: () => getJSON(DATA + 'scenarios.json').catch(() => null) })
  // each outlook's summary on every day it was rebuilt (crop_engine/dashboard.py write_history); absent until first made
  const histQ = useQuery({ queryKey: ['crop-history'], staleTime: 30 * 60_000, retry: false,
                           queryFn: () => getJSON(DATA + 'history.json').catch(() => null) })
  const trackerQ = useTrackerSites()
  const skillQ = useSkill()

  const msg = t => <div className="flex items-center justify-center min-h-[300px] p-6 text-center" style={{ fontSize: 15, color: 'var(--text-meta)' }}>{t}</div>
  if (country !== 'kenya') return msg('The crop outlook covers the Kenya monitored sites for now. Switch the country to Kenya to see it.')
  if (idx.isLoading) return msg('Loading the crop outlook…')
  if (idx.isError || !runs.length) return msg('The crop outlook is not available yet. It is made by the daily update once the crop engine has run.')

  const site = ix.sites[sid]
  const v = ix.varieties[vk]
  const summary = ix.summaries?.[run.id]?.[sid]?.[vk]?.[rk]
  const res = runQ.data?.sites?.[sid]
  const members = res?.results?.[vk]?.[rk]?.members ?? []
  const canopy = res?.results?.[vk]?.[rk]?.canopy
  const wofMembers = res?.results?.[vk]?.[rk]?.wofost?.members
  const b = bench.data?.sites?.[sid]?.[vk]?.[rk]
  const fcY = members.filter(m => m[3] !== 'error').map(m => effYield(m[3], m[2]))
  const pastY = (b?.seasons ?? []).filter(s => s[4] !== 'error').map(s => effYield(s[4], s[3]))
  const R = members.length ? rates(members.map(m => ({ status: m[3], y: m[2] })), v.failure_t_ha) : null
  const RB = b ? rates(b.seasons.map(s => ({ status: s[4], y: s[3] })), v.failure_t_ha) : null
  const measured = ix.observed_yields?.[sid]?.[cropOf(vk)] ?? []
  const notes = []
  if (!siteId && near && near.km > SAME_SITE_KM)
    notes.push(`The location selected on the map (${(+selectedSite.lat).toFixed(2)}, ${(+selectedSite.lon).toFixed(2)}) is not a crop site: the crop `
               + `model runs only at the monitored sites. Shown: the nearest, ${ix.sites[near.id].name}, ${Math.round(near.km)} km away.`)
  if (season && season !== 'short_rains') notes.push('The crop outlook covers the Short Rains only; the dashboard is set to another season.')
  if (!runId && !mainRun)
    notes.push(`The dashboard's forecast (${forecastType === 'medium' ? mrfModel : s2sModel}) has no crop run yet. Shown: ${runLabel(run)}.`)
  else if (!runId && mainSource === 'seasonal' && initId && initId !== SEASONAL_CROP_INIT)
    notes.push(`The dashboard shows the ${initLabel ?? initId} seasonal run; the crop outlook is made only from the Oct 01 + latest obs run, shown here.`)
  if (!rule && !mainRule && onsetLabel)
    notes.push(`The dashboard's onset method (${onsetLabel}) is a climate onset, not a sowing rule: crops are sown here by `
               + `${Object.values(rules).join(' or ')}. Shown: ${rules[rk]}.`)
  const pastPotential = median((b?.seasons ?? []).filter(s => SIMULATED.includes(s[4]) && s[5] != null).map(s => s[5]))
  const vb = summary?.vs_benchmark ?? {}
  const wofR = wofMembers?.length ? rates(wofMembers.map(m => ({ status: m[3], y: m[2] })), v.failure_t_ha) : null
  const openTab = tab => onOpenTab?.(tab, { lat: site.lat, lon: site.lon, site_name: site.name })
  const wSummary = ix.wofost?.[run.id]?.[sid]?.[vk]?.[rk]
  const agreeShare = (() => {                                          // members on which both models give the same failure verdict
    const pairs = (wofMembers ?? []).map((w, i) => [members[i], w]).filter(([a, w]) => a && w && a[3] !== 'error' && w[3] !== 'error')
    return pairs.length ? pairs.filter(([a, w]) => (effYield(a[3], a[2]) < v.failure_t_ha) === (effYield(w[3], w[2]) < v.failure_t_ha)).length / pairs.length : null
  })()
  const years = bench.data?.years ?? [1993, 2025]

  return (
    <div className="crop-viz" style={{ maxWidth: 1200, width: '100%', minWidth: 0, margin: '0 auto', padding: '20px 16px 40px', boxSizing: 'border-box' }}>
      <style>{CSS}</style>
      <div className="flex flex-wrap items-center gap-3">
        <h2 style={{ fontSize: 22, fontWeight: 600, color: 'var(--heading)', margin: 0 }}>Crop outlook</h2>
        <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--caution-text)', background: 'var(--caution-bg)', borderRadius: 999, padding: '3px 10px' }}>
          Experimental
        </span>
      </div>
      <p style={{ fontSize: 15, color: 'var(--text-body)', lineHeight: 1.6, margin: '8px 0 0', maxWidth: 860 }}>
        What each forecast means for a crop at the monitored sites: the AquaCrop crop model grown in the weather of every forecast
        member, sown on the platform’s onset date, and compared with the same crop simulated in the observed weather of {years[0]}–{years[1]}
        (simulated past seasons, not measured yields) and with the yields measured in field trials at the site, where there are any.
        A second crop model, WOFOST, grows the same maize and sorghum members, to show how much the answer depends on the model.
      </p>
      <div role="note" style={{ marginTop: 12, background: 'var(--caution-bg)', color: 'var(--caution-text)', borderRadius: 8, padding: '10px 14px',
                                fontSize: 14, lineHeight: 1.55, maxWidth: 860 }}>
        First calibration only (maize and sorghum, against trials at Kiboko), not verified: use for discussion, not as advice. Yields
        are water-limited (no nutrient, pest or management losses), so they are higher than most smallholder fields get.
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-3" style={{ margin: '18px 0' }}>
        <Select label="Site" value={sid} onChange={setSiteId}>
          {siteIds.map(id => <option key={id} value={id}>{ix.sites[id].name}</option>)}
        </Select>
        <Select label="Crop" value={vk} onChange={setVariety}>
          {Object.entries(ix.varieties).map(([k, x]) => <option key={k} value={k}>{x.label} ({x.maturity_days} days)</option>)}
        </Select>
        <Select label="Sowing rule" value={rk} onChange={setRule}>
          {Object.entries(ix.planting_rules).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </Select>
        <Select label="Forecast" value={run.id} onChange={setRunId}>
          {KINDS.map(k => {
            const rs = runs.filter(r => kindOf(r.source) === k)
            return rs.length ? <optgroup key={k.id} label={k.label}>{rs.map(r => <option key={r.id} value={r.id}>{runLabel(r)}</option>)}</optgroup> : null
          })}
        </Select>
        {ix.bulletins?.[sid] && (
          <a href={DATA + ix.bulletins[sid]} download={`crop_outlook_${sid}.pdf`} target="_blank" rel="noreferrer"
             title="This site's crop outlook on one page: every crop, both models, the management choices, past skill"
             style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6, background: 'var(--btn-primary)', color: '#fff',
                      borderRadius: 8, padding: '7px 12px', fontSize: 13.5, fontWeight: 600, textDecoration: 'none', minHeight: 36 }}>
            Download the crop bulletin (PDF)
          </a>
        )}
      </div>
      {notes.length > 0 && (
        <div role="status" style={{ margin: '-6px 0 16px', border: '1px solid var(--border-primary)', background: 'var(--bg-surface)', borderRadius: 8,
                                    padding: '10px 14px', fontSize: 14, color: 'var(--text-body)', lineHeight: 1.55, maxWidth: 860 }}>
          {notes.map(n => <div key={n}>{n}</div>)}
        </div>
      )}

      {summary && R && (
        <SeasonChain tr={trackerRowOf(trackerQ.data, site)} sw={res?.soil_water} initial={res?.initial_water_fraction} summary={summary}
                     R={R} wofR={wofR} rk={rk} ruleLabel={rules[rk]} fao={res?.fao_reference?.agricultural} canopy={canopy} onOpen={openTab}/>
      )}
      {summary && R && (
        <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Sowing opportunity" value={pct(R.pSowing)}
                sub={!R.pSowing ? 'No member has a sowing opportunity by 15 Jan under this rule'
                     : <>Sowing {summary.planting.p10 === summary.planting.p90 ? fmtDate(summary.planting.median)
                          : `${fmtDate(summary.planting.p10)} – ${fmtDate(summary.planting.p90)} (median ${fmtDate(summary.planting.median)})`}
                         {summary.resown ? `; re-sown after a failed start in ${pct(summary.resown)}` : ''}.
                         {' '}Simulated past seasons: {pct(RB?.pSowing)}</>}/>
          <Stat label="Yield if sown" value={R.nSown ? `${fmtT(R.ySown.median)} t/ha` : '—'}
                sub={<>{R.nSown ? `8 in 10 sown crops: ${fmtT(R.ySown.p10)}–${fmtT(R.ySown.p90)} t/ha. ` : 'No sown crop. '}
                       Simulated past seasons: {fmtT(RB?.ySown.median)} t/ha.
                       {measured.map(o => ` Measured in trials here: median ${fmtT(o.median_t_ha)}, high-input ${fmtT(o.p90_t_ha)} t/ha (${o.n} plots${o.years ? `, ${o.years}` : ''}).`).join('')}</>}/>
          <Stat label="Crop failure if sown" value={pct(R.pFailSown)}
                sub={<>Yield below {v.failure_t_ha} t/ha. Failed to establish: {pct(R.pEst)}. Simulated past seasons: {pct(RB?.pFailSown)}</>}/>
          <Stat label="Harvest" value={fmtDate(summary.harvest_median)}
                sub={summary.stress_days_median != null ? <>Water-stress days: {Math.round(summary.stress_days_median)}. Season rain: {Math.round(summary.rain_mm_median)} mm (medians of sown crops)</> : 'No sown crop'}/>
        </div>
      )}
      {summary && R && <ModelAgreement a={summary} w={wSummary} share={agreeShare} vk={vk}/>}
      {summary && R && <SkillLine skill={skillQ.data} source={run.source} sid={sid} vk={vk} rk={rk}/>}
      {summary && R && (
        <p style={{ fontSize: 13.5, color: 'var(--text-meta)', margin: '10px 0 0', lineHeight: 1.5 }}>
          All {R.nValid} members, a member with no crop counted as no yield: median {fmtT(summary.yield_t_ha.median)} t/ha, chance of no crop
          or a failed one {pct(R.pFail)} (simulated past seasons: {pct(RB?.pFail)}).
          {R.nError ? ` ${R.nError} member${R.nError > 1 ? 's' : ''} failed to run in the crop model and ${R.nError > 1 ? 'are' : 'is'} left out of every figure.` : ''}
          {' '}{vb.p_below_normal != null
            ? <>Compared with the simulated past seasons: {pct(vb.p_below_normal)} of members below their normal range ({fmtT(vb.t33)}–{fmtT(vb.t67)} t/ha), {pct(vb.p_above_normal)} above it.</>
            : <>No normal range for this crop: a third or more of the simulated past seasons were crop failures, so the failure chances are the comparison.</>}
          {summary.potential_t_ha?.median != null && <>
            {' '}Water stress: the sown crops yield a median {fmtT(summary.potential_t_ha.yield_median)} t/ha, against {fmtT(summary.potential_t_ha.median)} t/ha
            without water stress (AquaCrop’s potential yield).</>}
          {' '}{run.members_kind?.startsWith('deterministic') ? `${run.model_label} is a single forecast, repeated in all 25 members: the spread comes from the observations and the seasonal forecast after it.` : ''}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-2" style={{ marginTop: 18 }}>
        <Panel title="Chance of more than each yield"
               sub="Share of forecast members (solid) and of simulated past seasons (dashed) with a yield above the value on the axis; a member or season with no crop counts as zero. Hover for values.">
          {runQ.isLoading || bench.isLoading ? msg('Loading…')
            : fcY.length ? <ExceedanceChart fc={fcY} past={pastY} threshold={v.failure_t_ha} fcLabel={`This forecast (${fcY.length} members)`}/>
            : msg('No members for this choice.')}
        </Panel>
        <Panel title="What happens to the crop" sub="Outcome of each forecast member and of each simulated past season.">
          {R?.nValid && RB?.nValid ? (
            <OutcomeBars rows={[
              { label: 'This forecast', unit: 'members', n: R.nValid, ...countOutcomes(members.map(m => m[3]).filter(s => s !== 'error')) },
              { label: `Simulated past seasons ${years[0]}–${years[1]}`, unit: 'seasons', n: RB.nValid, ...countOutcomes(b.seasons.map(s => s[4]).filter(s => s !== 'error')) },
            ]}/>
          ) : msg(runQ.isLoading || bench.isLoading ? 'Loading…' : 'No outcomes for this choice.')}
          <p style={{ fontSize: 13, color: 'var(--text-meta)', margin: '6px 0 0', lineHeight: 1.5 }}>
            Failed to establish: a sowing rain followed by a dry spell, the seedlings dried out. Not grown: sown too late to mature by
            31 Mar (the season’s end), or no sowing opportunity by 15 Jan under this rule. Model errors are left out.
          </p>
        </Panel>
      </div>

      <div id="crop-regional" style={{ marginTop: 18, scrollMarginTop: 12 }}>
        <CropRegionalPanel site={site}/>
      </div>

      <div id="crop-models" style={{ marginTop: 18, scrollMarginTop: 12 }}>
        <Panel title="Two crop models, the same forecast"
               sub="AquaCrop, the published outlook, and WOFOST 7.2 grown in the same members of this forecast, sown on the same dates.">
          {runQ.isLoading ? msg('Loading…')
            : members.length ? <EnginePanel aqua={members} wof={wofMembers} v={v} vk={vk} past={b?.seasons}
                                            pastWof={bench.data?.wofost?.[sid]?.[vk]?.[rk]?.seasons}
                                            why={runQ.data?.meta?.second_engine?.why_not && !wofMembers ? `No second model for this run: ${runQ.data.meta.second_engine.why_not}.` : null}/>
            : msg('No members for this choice.')}
        </Panel>
      </div>

      <div id="crop-canopy" style={{ marginTop: 18, scrollMarginTop: 12 }}>
        <Panel title="How the crop canopy develops"
               sub="Canopy cover of the sown crops week by week, from 1 Aug. It falls to zero as each crop is harvested or dies, so the median drops once about half the crops are done. Hover for values.">
          {runQ.isLoading ? msg('Loading…')
            : canopy ? <CanopyChart fc={canopy} past={b?.canopy} nMembers={members.length}/>
            : msg(!members.length ? 'No members for this choice.'
                  : R?.nSown ? 'The canopy curve comes with the next crop run (this run was made before it was added).'
                  : 'No sown crop in this forecast: no canopy to show.')}
        </Panel>
      </div>

      <div style={{ marginTop: 18 }}>
        <HistoryPanel hist={histQ.data} loading={histQ.isLoading} source={run.source} sid={sid} vk={vk} rk={rk} thr={v.failure_t_ha} msg={msg}/>
      </div>

      <div style={{ marginTop: 18 }}>
        <Panel title="Every forecast for this site and crop" sub="Select a row to show that forecast above.">
          <div style={{ overflowX: 'auto' }}>
            <table className="crop-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr><th>Forecast</th><th>Type</th><th>Sowing</th><th>Sowing opportunity</th><th>Yield if sown</th><th>8 in 10 sown</th>
                    <th>Without water stress</th><th>Failure if sown</th><th>Matured</th><th>WOFOST yield if sown</th><th>Crop models</th></tr>
              </thead>
              <tbody>
                {runs.map(r => {
                  const s = ix.summaries?.[r.id]?.[sid]?.[vk]?.[rk]
                  if (!s) return null
                  const ws = ix.wofost?.[r.id]?.[sid]?.[vk]?.[rk]
                  const on = r.id === run.id
                  return (
                    <tr key={r.id} style={{ background: on ? 'var(--nav-active-bg)' : undefined }}>
                      <td>
                        <button type="button" onClick={() => setRunId(r.id)} aria-pressed={on}
                                style={{ background: 'none', border: 0, padding: 0, cursor: 'pointer', color: on ? 'var(--heading)' : 'var(--accent-text)',
                                         fontWeight: on ? 600 : 500, fontSize: 14, textAlign: 'left' }}>
                          {runLabel(r)}
                        </button>
                      </td>
                      <td>{kindOf(r.source).label.split(' (')[0]}{r.members_kind?.startsWith('deterministic') ? ', single run' : ''}</td>
                      <td>{fmtDate(s.planting.median)}</td>
                      <td>{pct(s.p_sowing_opportunity ?? 1 - (s.share.not_sown ?? 0))}</td>
                      <td>{s.yield_if_sown_t_ha ? `${fmtT(s.yield_if_sown_t_ha.median)} t/ha` : '—'}</td>
                      <td>{s.yield_if_sown_t_ha ? `${fmtT(s.yield_if_sown_t_ha.p10)}–${fmtT(s.yield_if_sown_t_ha.p90)} t/ha` : '—'}</td>
                      <td>{s.potential_t_ha?.median != null ? `${fmtT(s.potential_t_ha.median)} t/ha` : '—'}</td>
                      <td>{pct(s.p_failure_if_sown)}</td>
                      <td>{pct(s.share.ok)}</td>
                      <td>{ws?.yield_if_sown_t_ha?.median != null ? `${fmtT(ws.yield_if_sown_t_ha.median)} t/ha` : '—'}</td>
                      <td style={{ color: agreementOf(s, ws)?.tone === 'warn' ? 'var(--caution-text)' : undefined }}>{agreementOf(s, ws)?.short ?? '—'}</td>
                    </tr>
                  )
                })}
                {b && RB && (
                  <tr>
                    <td style={{ fontWeight: 600, color: 'var(--heading)' }}>Simulated past seasons {years[0]}–{years[1]}</td>
                    <td>AquaCrop in observed weather</td>
                    <td>—</td>
                    <td>{pct(RB.pSowing)}</td>
                    <td>{fmtT(RB.ySown.median)} t/ha</td>
                    <td>{fmtT(RB.ySown.p10)}–{fmtT(RB.ySown.p90)} t/ha</td>
                    <td>{pastPotential != null ? `${fmtT(pastPotential)} t/ha` : '—'}</td>
                    <td>{pct(RB.pFailSown)}</td>
                    <td>{pct(RB.pOk)}</td>
                    <td>—</td><td>—</td>
                  </tr>
                )}
                {measured.map(o => (
                  <tr key={o.irrigated + o.years}>
                    <td style={{ fontWeight: 600, color: 'var(--heading)' }}>Measured: field trials here{o.years ? `, ${o.years}` : ''}</td>
                    <td>{o.n} plots, {o.studies} {o.studies > 1 ? 'studies' : 'study'}{o.n_kg_ha ? `, ${o.n_kg_ha} kg N/ha` : ''}</td>
                    <td>—</td><td>—</td>
                    <td>{fmtT(o.median_t_ha)} t/ha</td>
                    <td>high-input {fmtT(o.p90_t_ha)} t/ha</td>
                    <td>—</td><td>—</td><td>—</td><td>—</td><td>—</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      <div style={{ marginTop: 18 }}>
        <ScenarioPanel data={scenQ.data} loading={scenQ.isLoading} seasonal={run.source === 'seasonal'} sid={sid} vk={vk} rk={rk}
                       ruleLabel={rules[rk]} msg={msg}/>
      </div>

      <div className="grid gap-4" style={{ marginTop: 18 }}>
        <Panel title="Members of this forecast">
          <details>
            <summary style={{ cursor: 'pointer', fontSize: 14, color: 'var(--accent-text)' }}>Show each member’s sowing, harvest and yield</summary>
            <div style={{ overflowX: 'auto', marginTop: 10, maxHeight: 420, overflowY: 'auto' }}>
              <table className="crop-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead><tr><th>Member</th><th>Sowing</th><th>Harvest</th><th>Yield</th><th>Without water stress</th><th>Outcome</th><th>Stress days</th><th>Rain</th></tr></thead>
                <tbody>
                  {members.map((m, i) => (
                    <tr key={i}>
                      <td>{i + 1}</td><td>{fmtDate(m[0])}{m[7] > 1 ? ' (re-sown)' : ''}</td><td>{fmtDate(m[1])}</td><td>{fmtT(effYield(m[3], m[2]))} t/ha</td>
                      <td>{SIMULATED.includes(m[3]) && m[6] != null ? `${fmtT(m[6])} t/ha` : '—'}</td>
                      <td>{STATUS_LABEL[m[3]] ?? m[3]}</td><td>{m[4] ?? '—'}</td><td>{m[5] != null ? `${Math.round(m[5])} mm` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </Panel>
        <Panel title="About this result">
          <dl style={{ fontSize: 14, color: 'var(--text-body)', lineHeight: 1.6, margin: 0 }}>
            {[
              ['Crop', `${v.label}: ${v.maturity_days} days to maturity at about 21 °C, built from AquaCrop's ${v.aquacrop_crop} (stands for ${v.examples})`],
              ['Forecast', `${runLabel(run)}; observations to ${fmtDate(run.obs_end)}`],
              ['Rainfall', [...(runQ.data?.meta?.segments ?? []).map((s, i) =>      // the crop season starts on 1 Aug
                              `${s.label} ${i === 0 && s.kind === 'obs' ? '1 Aug' : fmtDate(s.start)} – ${fmtDate(s.end)}`),
                            'ECMWF SEAS5 1 Jan – 28 Feb',
                            `1–31 Mar: ${runQ.data?.meta?.weather?.march_rain ?? 'climatology (each member the observed March of a past year)'}; the season ends on 31 Mar`].join('; ')],
              ['Temperature, ET0', (() => {
                const t = runQ.data?.meta?.weather?.temperature ?? ''
                const s2s = t.startsWith('first ') ? t.slice(6).split(', member')[0] : null
                const seas = t.includes('ECMWF SEAS5') || t.startsWith('ECMWF')
                return 'ERA5-Land to its latest day, then '
                  + (s2s ? `the ${s2s} member paired with the rain, bias-corrected to ERA5-Land, to its last day, then ` : '')
                  + (seas ? 'ECMWF SEAS5 member by member, bias-corrected to ERA5-Land; ET0 the ERA5-Land climatology scaled by that temperature'
                          : 'the 1993–2016 average for the day of the year')
              })()],
              ['Site', `${site.name}, 0.25° grid cell ${site.cell?.join(', ')}`],
              ['Soil', `SoilGrids, ${site.topsoil?.sand}% sand and ${site.topsoil?.clay}% clay at the surface; ${site.soil_taw_100cm_mm} mm available water in the top metre`
                       + (res ? `; ${pct(res.initial_water_fraction)} of it on 1 Aug (ERA5-Land)` : '')],
              ['FAO water balance', res?.fao_reference?.agricultural
                ? `this forecast's agricultural onset ${fmtDate(res.fao_reference.agricultural.onset_median)}, cessation ${fmtDate(res.fao_reference.agricultural.cessation_median)}, season ${res.fao_reference.agricultural.lgp_days_median ?? '—'} days (medians)` : '—'],
            ].map(([k, val]) => (
              <div key={k} style={{ display: 'flex', flexWrap: 'wrap', gap: '0 12px', padding: '6px 0', borderBottom: '1px solid var(--border-primary)' }}>
                <dt style={{ flex: '0 0 160px', fontWeight: 600, color: 'var(--text-meta)' }}>{k}</dt>
                <dd style={{ flex: '1 1 320px', margin: 0, minWidth: 0, maxWidth: 860 }}>{val}</dd>
              </div>
            ))}
          </dl>
          <ul style={{ fontSize: 13.5, color: 'var(--text-meta)', lineHeight: 1.55, margin: '12px 0 0', paddingLeft: 18, listStyle: 'disc' }}>
            {(ix.caveats ?? []).map(c => <li key={c}>{c}</li>)}
          </ul>
          <p style={{ fontSize: 13.5, margin: '10px 0 0' }}>
            <a href={METHOD_URL} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-text)' }}>Method: CROP_ENGINE.md</a>
            <span style={{ color: 'var(--text-meta)' }}> · {ix.engine}{ix.second_engine ? ` · second model ${ix.second_engine}` : ''}</span>
          </p>
        </Panel>
      </div>
    </div>
  )
}
