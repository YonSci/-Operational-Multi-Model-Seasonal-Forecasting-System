import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

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
  { id: 'not_grown', label: 'Not grown', ids: ['too_late', 'not_sown', 'error'] },
]
const SIMULATED = ['ok', 'died', 'failed_establishment']
const STATUS_LABEL = { ok: 'Matured', died: 'Died before maturity', failed_establishment: 'Failed to establish',
                       too_late: 'Too late to mature', not_sown: 'No sowing opportunity', error: 'Model error' }

const CSS = `
.crop-viz { --crop-fc:#3987e5; --crop-o1:#b7d3f6; --crop-o2:#6da7ec; --crop-o3:#2a78d6; --crop-o4:#184f95;
            --crop-ink1:#0f172a; --crop-ink2:#0f172a; --crop-ink3:#ffffff; --crop-ink4:#ffffff; }
html.light .crop-viz { --crop-fc:#2a78d6; --crop-o1:#104281; --crop-o2:#256abf; --crop-o3:#5598e7; --crop-o4:#86b6ef;
                       --crop-ink1:#ffffff; --crop-ink2:#ffffff; --crop-ink3:#0f172a; --crop-ink4:#0f172a; }
.crop-viz select:focus-visible, .crop-viz button:focus-visible, .crop-viz summary:focus-visible { outline:2px solid var(--focus); outline-offset:2px; }
.crop-table th, .crop-table td { padding:8px 10px; text-align:left; border-bottom:1px solid var(--border-primary); white-space:nowrap; }
.crop-table th { font-size:13px; font-weight:600; color:var(--text-meta); }
.crop-table td { font-size:14px; color:var(--text-body); font-variant-numeric:tabular-nums; }
`

const getJSON = u => fetch(u).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json() })
const kindOf = source => KINDS.find(k => k.test(source)) ?? KINDS[0]
const fmtDate = iso => { if (!iso) return '—'; const [, m, d] = iso.split('-').map(Number); return `${d} ${MONTHS[m - 1]}` }
const fmtT = v => v == null ? '—' : v < 0.05 ? '0' : v.toFixed(1)
const pct = v => v == null ? '—' : `${Math.round(v * 100)}%`
const effYield = (status, y) => SIMULATED.includes(status) ? (y ?? 0) : 0
const groupOf = status => GROUPS.find(g => g.ids.includes(status))?.id ?? 'not_grown'
const runLabel = r => r.source === 'seasonal' ? r.model_label : `${r.model_label} · ${fmtDate(r.run)}`

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
    { key: 'past', label: `Past seasons (${past.length})`, vals: past, color: 'var(--text-meta)', dash: '6 4' },
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
              {i === 0 ? 'This forecast' : 'Past seasons'}
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
              <span>{s.key === 'fc' ? 'This forecast' : 'Past seasons'}</span>
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
              {['too_late', 'not_sown', 'error'].filter(s => tip.row.raw[s]).map(s => <div key={s}>{STATUS_LABEL[s]}: {tip.row.raw[s]}</div>)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const countOutcomes = statuses => {
  const raw = {}, counts = Object.fromEntries(GROUPS.map(g => [g.id, 0]))
  for (const s of statuses) { raw[s] = (raw[s] ?? 0) + 1; counts[groupOf(s)] += 1 }
  return { raw, counts }
}

// ── The tab ─────────────────────────────────────────────────────────────────────────────────────────────────────────
export default function CropOutlookTab({ country, selectedSite }) {
  const idx = useQuery({ queryKey: ['crop-index'], queryFn: () => getJSON(DATA + 'index.json'), staleTime: 30 * 60_000 })
  const bench = useQuery({ queryKey: ['crop-benchmark'], queryFn: () => getJSON(DATA + 'benchmark.json'), staleTime: 30 * 60_000 })
  const ix = idx.data
  const runs = useMemo(() => (ix?.runs ?? []).slice().sort((a, b) =>
    KINDS.indexOf(kindOf(a.source)) - KINDS.indexOf(kindOf(b.source)) || runLabel(a).localeCompare(runLabel(b))), [ix])
  const siteIds = Object.keys(ix?.sites ?? {})
  const fromMap = siteIds.find(id => ix.sites[id].name === selectedSite?.site_name)
  const [siteId, setSiteId] = useState(null)
  const [variety, setVariety] = useState('maize_early')
  const [rule, setRule] = useState('fao-agricultural')
  const [runId, setRunId] = useState(null)
  const sid = siteIds.includes(siteId) ? siteId : fromMap ?? (siteIds.includes('kalro_kiboko_makueni_farm') ? 'kalro_kiboko_makueni_farm' : siteIds[0])
  const vk = ix?.varieties?.[variety] ? variety : Object.keys(ix?.varieties ?? {})[0]
  const rk = ix?.planting_rules?.[rule] ? rule : Object.keys(ix?.planting_rules ?? {})[0]
  const run = runs.find(r => r.id === runId) ?? runs[0]
  const runQ = useQuery({ queryKey: ['crop-run', run?.id], enabled: !!run, staleTime: 30 * 60_000,
                          queryFn: () => getJSON(DATA + (run.file ?? run.source + '.json')) })

  const msg = t => <div className="flex items-center justify-center min-h-[300px] p-6 text-center" style={{ fontSize: 15, color: 'var(--text-meta)' }}>{t}</div>
  if (country !== 'kenya') return msg('The crop outlook covers the Kenya monitored sites for now. Switch the country to Kenya to see it.')
  if (idx.isLoading) return msg('Loading the crop outlook…')
  if (idx.isError || !runs.length) return msg('The crop outlook is not available yet. It is made by the daily update once the crop engine has run.')

  const site = ix.sites[sid]
  const v = ix.varieties[vk]
  const summary = ix.summaries?.[run.id]?.[sid]?.[vk]?.[rk]
  const res = runQ.data?.sites?.[sid]
  const members = res?.results?.[vk]?.[rk]?.members ?? []
  const b = bench.data?.sites?.[sid]?.[vk]?.[rk]
  const fcY = members.map(m => effYield(m[3], m[2]))
  const pastY = (b?.seasons ?? []).map(s => effYield(s[4], s[3]))
  const vb = summary?.vs_benchmark ?? {}
  const sownShare = summary ? 1 - (summary.share.not_sown ?? 0) : null
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
        member, sown on the platform’s onset date, and compared with the same crop grown in the observed seasons of {years[0]}–{years[1]}.
      </p>
      <div role="note" style={{ marginTop: 12, background: 'var(--caution-bg)', color: 'var(--caution-text)', borderRadius: 8, padding: '10px 14px',
                                fontSize: 14, lineHeight: 1.55, maxWidth: 860 }}>
        Not calibrated or verified yet: use for discussion, not as advice. Yields are water-limited (no nutrient, pest or management
        losses), so they are higher than most smallholder fields get.
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-3" style={{ margin: '18px 0' }}>
        <Select label="Site" value={sid} onChange={setSiteId}>
          {siteIds.map(id => <option key={id} value={id}>{ix.sites[id].name}</option>)}
        </Select>
        <Select label="Crop" value={vk} onChange={setVariety}>
          {Object.entries(ix.varieties).map(([k, x]) => <option key={k} value={k}>{x.label} ({x.maturity_days} days)</option>)}
        </Select>
        <Select label="Sowing date" value={rk} onChange={setRule}>
          {Object.entries(ix.planting_rules).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </Select>
        <Select label="Forecast" value={run.id} onChange={setRunId}>
          {KINDS.map(k => {
            const rs = runs.filter(r => kindOf(r.source) === k)
            return rs.length ? <optgroup key={k.id} label={k.label}>{rs.map(r => <option key={r.id} value={r.id}>{runLabel(r)}</option>)}</optgroup> : null
          })}
        </Select>
      </div>

      {summary && (
        <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Likely yield" value={`${fmtT(summary.yield_t_ha.median)} t/ha`}
                sub={<>Middle 8 in 10 members: {fmtT(summary.yield_t_ha.p10)}–{fmtT(summary.yield_t_ha.p90)} t/ha. Past seasons: {fmtT(vb.benchmark_median)} t/ha</>}/>
          <Stat label="Chance of crop failure" value={pct(summary.p_failure)}
                sub={<>Yield below {v.failure_t_ha} t/ha, or no crop. Past seasons: {pct(vb.benchmark_p_failure)}</>}/>
          <Stat label="Sowing date" value={fmtDate(summary.planting.median)}
                sub={sownShare === 0 ? 'No member has a sowing opportunity by 15 Jan'
                     : <>{summary.planting.p10 === summary.planting.p90 ? `Most members: ${fmtDate(summary.planting.p10)}`
                          : `Most members ${fmtDate(summary.planting.p10)} – ${fmtDate(summary.planting.p90)}`}
                         {summary.share.not_sown ? `; no sowing opportunity in ${pct(summary.share.not_sown)}` : ''}</>}/>
          <Stat label="Harvest" value={fmtDate(summary.harvest_median)}
                sub={summary.stress_days_median != null ? <>Water-stress days: {Math.round(summary.stress_days_median)}. Season rain: {Math.round(summary.rain_mm_median)} mm (medians of sown crops)</> : 'No sown crop'}/>
        </div>
      )}
      {summary && (
        <p style={{ fontSize: 13.5, color: 'var(--text-meta)', margin: '10px 0 0', lineHeight: 1.5 }}>
          {vb.p_below_normal != null
            ? <>Compared with past seasons: {pct(vb.p_below_normal)} of members below the normal range ({fmtT(vb.t33)}–{fmtT(vb.t67)} t/ha), {pct(vb.p_above_normal)} above it.</>
            : <>No normal range for this crop: a third or more of the past seasons were crop failures, so the failure chance is the comparison.</>}
          {' '}{run.members_kind?.startsWith('deterministic') ? `${run.model_label} is a single forecast, repeated in all 25 members: the spread comes from the observations and the seasonal forecast after it.` : ''}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-2" style={{ marginTop: 18 }}>
        <Panel title="Chance of more than each yield"
               sub="Share of forecast members (solid) and of past seasons (dashed) with a yield above the value on the axis. Hover for values.">
          {runQ.isLoading || bench.isLoading ? msg('Loading…')
            : members.length ? <ExceedanceChart fc={fcY} past={pastY} threshold={v.failure_t_ha} fcLabel={`This forecast (${members.length} members)`}/>
            : msg('No members for this choice.')}
        </Panel>
        <Panel title="What happens to the crop" sub="Outcome of each forecast member and of each past season.">
          {members.length && b ? (
            <OutcomeBars rows={[
              { label: 'This forecast', unit: 'members', n: members.length, ...countOutcomes(members.map(m => m[3])) },
              { label: `Past seasons ${years[0]}–${years[1]}`, unit: 'seasons', n: b.seasons.length, ...countOutcomes(b.seasons.map(s => s[4])) },
            ]}/>
          ) : msg(runQ.isLoading || bench.isLoading ? 'Loading…' : 'No outcomes for this choice.')}
          <p style={{ fontSize: 13, color: 'var(--text-meta)', margin: '6px 0 0', lineHeight: 1.5 }}>
            Failed to establish: a sowing rain followed by a dry spell, the seedlings dried out. Not grown: sown too late to mature by
            31 Mar, or no sowing opportunity by 15 Jan.
          </p>
        </Panel>
      </div>

      <div style={{ marginTop: 18 }}>
        <Panel title="Every forecast for this site and crop" sub="Select a row to show that forecast above.">
          <div style={{ overflowX: 'auto' }}>
            <table className="crop-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr><th>Forecast</th><th>Type</th><th>Sowing</th><th>Yield, median</th><th>8 in 10 members</th><th>Crop failure</th><th>Matured</th></tr>
              </thead>
              <tbody>
                {runs.map(r => {
                  const s = ix.summaries?.[r.id]?.[sid]?.[vk]?.[rk]
                  if (!s) return null
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
                      <td>{fmtT(s.yield_t_ha.median)} t/ha</td>
                      <td>{fmtT(s.yield_t_ha.p10)}–{fmtT(s.yield_t_ha.p90)} t/ha</td>
                      <td>{pct(s.p_failure)}</td>
                      <td>{pct(s.share.ok)}</td>
                    </tr>
                  )
                })}
                {b && (
                  <tr>
                    <td style={{ fontWeight: 600, color: 'var(--heading)' }}>Past seasons {years[0]}–{years[1]}</td>
                    <td>Observed weather</td>
                    <td>—</td>
                    <td>{fmtT(b.median)} t/ha</td>
                    <td>—</td>
                    <td>{pct(b.p_failure)}</td>
                    <td>{pct(b.seasons.filter(x => x[4] === 'ok').length / b.seasons.length)}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      <div className="grid gap-4" style={{ marginTop: 18 }}>
        <Panel title="Members of this forecast">
          <details>
            <summary style={{ cursor: 'pointer', fontSize: 14, color: 'var(--accent-text)' }}>Show each member’s sowing, harvest and yield</summary>
            <div style={{ overflowX: 'auto', marginTop: 10, maxHeight: 420, overflowY: 'auto' }}>
              <table className="crop-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead><tr><th>Member</th><th>Sowing</th><th>Harvest</th><th>Yield</th><th>Outcome</th><th>Stress days</th><th>Rain</th></tr></thead>
                <tbody>
                  {members.map((m, i) => (
                    <tr key={i}>
                      <td>{i + 1}</td><td>{fmtDate(m[0])}</td><td>{fmtDate(m[1])}</td><td>{fmtT(effYield(m[3], m[2]))} t/ha</td>
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
                            'ECMWF SEAS5 1 Jan – 28 Feb', 'an observed past March (climatology)'].join('; ')],
              ['Temperature, ET0', 'ERA5-Land to its latest day, then the 1993–2016 average for the day of the year'],
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
            <span style={{ color: 'var(--text-meta)' }}> · {ix.engine}</span>
          </p>
        </Panel>
      </div>
    </div>
  )
}
