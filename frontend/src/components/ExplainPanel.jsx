// Forecast assistant: "Explain this location", "What changed?" and "Explain this map" (backend /explain/*).
// The backend computes an evidence record from the platform's data, then writes the explanation from it: the
// standard template, or Claude when the server has a key (every number Claude writes is checked against the
// evidence). This panel shows the explanation with the evidence beside it.
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { API_BASE } from '../api/queries'
import { useLanguages, speechCode, ListenButton } from './voice'

export const AUDIENCES = [
  { id: 'general', label: 'General' },
  { id: 'farmer', label: 'Farmer' },
  { id: 'extension', label: 'Extension officer' },
  { id: 'technical', label: 'Technical' },
]
const TITLES = { location: 'Explain this location', changes: 'What changed?', map: 'Explain this map', advisory: 'Advisory (draft)',
                 area: 'Explain an area', attention: 'Areas needing attention', chart: 'Explain a chart',
                 tracker: 'How is the season going here?', tracker_changes: 'What changed since the last run?' }
const CRITERIA = [['late_onset', 'Higher chance of a late onset'], ['early_cessation', 'Higher chance of an early end of the rains'],
                  ['short_season', 'Higher chance of a short season'], ['onset_delay', 'Onset later than normal'],
                  ['season_shorter', 'Season shorter than normal'], ['no_onset', 'Members finding no onset']]
const CHARTS = [['member_dates', 'Member dates (onset, cessation, season length)'], ['crop_outcomes', 'Crop outcomes (yield, harvest, canopy)'],
                ['rain_plume', 'Rainfall plume']]
const QUANTITIES = [['onset', 'Onset'], ['cessation', 'Cessation'], ['lgp', 'Season length']]
// Advisory profile choices (backend/assistant/advisory_rules.yaml)
const DECISIONS = [['sowing', 'When to sow'], ['crop_choice', 'Which crop or maturity class'], ['establishment', 'Establishment after sowing'],
                   ['replanting', 'Replanting after poor establishment'], ['water', 'Water management']]
const CROPS = [['maize_early', 'Early-maturing maize'], ['maize_medium', 'Medium-maturing maize'], ['sorghum', 'Sorghum'], ['bean', 'Dry bean']]
const PLANTED = [['unknown', 'Not stated'], ['no', 'Not yet sown'], ['yes', 'Sown']]
const WATERS = [['rainfed', 'Rainfed'], ['irrigated', 'Irrigation available']]
const OBJECTIVES = [['maturity', 'Reach maturity'], ['establishment', 'Reduce establishment failure'], ['downside', 'Protect the poor years'],
                    ['yield', 'Higher typical yield'], ['water', 'Use less irrigation water']]
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const fdate = iso => { if (!iso) return 'n/a'; const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number); return `${d} ${MON[m - 1]} ${y}` }
const STATUS = { estimated_from_observations: 'Estimated from observations so far', partly_observed: 'Partly within the observed period', forecast: 'Forecast' }

async function fetchExplain(req) {
  const { kind, ...params } = req
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== '').map(([k, v]) => [k, String(v)]))
  const path = kind === 'tracker_changes' ? 'tracker/changes' : kind
  const res = await fetch(`${API_BASE}/explain/${path}?${q}`)
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
    enabled: !!req && !(req.kind === 'area' && !req.name && !req.bbox),
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

function Pick({ id, label, value, choices, onChange }) {
  return (
    <label htmlFor={id} style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
      <span style={lbl}>{label}</span>
      <select id={id} value={value} onChange={e => onChange(e.target.value)}
              style={{ background: 'var(--select-bg)', color: 'var(--heading)', border: '1px solid var(--border-primary)', borderRadius: 6, padding: '4px 6px', fontSize: 13 }}>
        {choices.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  )
}

function useRegions(season) {
  return useQuery({ queryKey: ['explain-regions', season], staleTime: Infinity, enabled: !!season,
                    queryFn: async () => { const r = await fetch(`${API_BASE}/explain/regions?season=${encodeURIComponent(season)}`); if (!r.ok) throw new Error('regions'); return r.json() } })
}

export function useTrackerSites(enabled = true) {
  return useQuery({ queryKey: ['tracker-sites'], staleTime: 30 * 60_000, enabled,
                    queryFn: async () => { const r = await fetch(`${API_BASE}/explain/tracker/sites`); if (!r.ok) throw new Error('sites'); return (await r.json()).sites } })
}

function TrackerForm({ request, onProfile }) {
  const { data } = useTrackerSites()
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'flex-end', marginTop: 8 }}>
      <Pick id="tracker-site" label="Monitoring site" value={request.site || ''} onChange={v => onProfile({ site: v })}
            choices={[...(request.site ? [] : [['', 'Choose...']]), ...(data ?? []).map(x => [x.name, x.name])]}/>
    </div>
  )
}

const mm = v => v == null ? 'n/a' : `${v} mm`
const dm = iso => fdate(iso).replace(/ \d{4}$/, '')

function TrackerEvidence({ ev }) {
  const r = ev.rain_so_far, w = ev.weather_models, e = ev.ecmwf_ensemble
  const th = { textAlign: 'left', fontWeight: 600, fontSize: 12, color: 'var(--text-meta)', padding: '4px 6px', borderBottom: '1px solid var(--border-primary)' }
  const td = { padding: '4px 6px', borderBottom: '1px solid var(--border-primary)', fontSize: 12.5, fontVariantNumeric: 'tabular-nums' }
  const recent = Object.fromEntries((ev.recent_rain?.by_product ?? []).map(x => [x.product, x]))
  const rows = [{ product: 'CHIRPS 2.0', mm: r.chirps_mm, through: r.through }, ...r.other_products]
  return (
    <>
      <div style={box}>
        <KV k="Site" v={`${ev.scope.site} (${ev.scope.lat}, ${ev.scope.lon})`}/>
        <KV k="Season" v={`${ev.season.label} ${ev.season.year}`}/>
        <KV k="Issued" v={fdate(ev.issued)}/>
        <KV k="Since 1 Oct (CHIRPS)" v={`${mm(r.chirps_mm)}, ${r.pct_of_normal ?? 'n/a'}% of normal (${mm(r.normal_mm)})`}/>
        <KV k="Planting onset" v={`${r.products_with_planting_onset} of ${r.products} satellite products`}/>
      </div>
      <div style={{ ...box, marginTop: 8, overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <caption style={{ ...lbl, textAlign: 'left', marginBottom: 4 }}>Observed rain by satellite product (a wet day has at least {ev.recent_rain?.wet_day_mm ?? 1} mm)</caption>
          <thead><tr><th style={th} scope="col">Product</th><th style={th} scope="col">Since 1 Oct</th><th style={th} scope="col">Last 7 days</th><th style={th} scope="col">Last wet day</th><th style={th} scope="col">Data to</th></tr></thead>
          <tbody>{rows.map(x => {
            const rc = recent[x.product] ?? {}
            return (
              <tr key={x.product}><td style={td}>{x.product}</td><td style={td}>{mm(x.mm)}</td><td style={td}>{mm(rc.last_7_days_mm)}</td>
                <td style={td}>{rc.last_wet_day ? `${dm(rc.last_wet_day)} (${rc.days_since_last_wet_day} d before)` : 'n/a'}</td><td style={td}>{dm(x.through)}</td></tr>
            )
          })}</tbody>
        </table>
      </div>
      {w && (
        <div style={{ ...box, marginTop: 8, overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <caption style={{ ...lbl, textAlign: 'left', marginBottom: 4 }}>Weather models from {dm(w.from)} (raw); planting rains = {w.planting_rain_rule}</caption>
            <thead><tr><th style={th} scope="col">Model</th><th style={th} scope="col">5 days</th><th style={th} scope="col">7 days</th><th style={th} scope="col">10 days</th><th style={th} scope="col">First planting rains</th></tr></thead>
            <tbody>{w.by_model.map(m => (
              <tr key={m.model}><td style={td}>{m.model} ({m.forecast_days} d)</td><td style={td}>{mm(m.total_5_days_mm)}</td><td style={td}>{mm(m.total_7_days_mm)}</td>
                <td style={td}>{mm(m.total_10_days_mm)}</td><td style={td}>{m.first_planting_rain ? dm(m.first_planting_rain) : 'none'}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {e && (
        <div style={{ ...box, marginTop: 8 }}>
          <div style={{ fontWeight: 600, color: 'var(--heading)', marginBottom: 4 }}>ECMWF ensemble ({fdate(e.initialised)})</div>
          <KV k="Planting rains within 7 / 15 days" v={`${e.planting_rain_within_7_days_pct ?? 'n/a'}% / ${e.planting_rain_within_15_days_pct ?? 'n/a'}% of members`}/>
          <KV k="Planting onset within 15 days" v={e.planting_onset_within_15_days_pct != null ? `${e.planting_onset_within_15_days_pct}% of members` : null}/>
          <KV k="Planting onset median" v={e.planting_onset_median}/>
        </div>
      )}
      {Object.keys(ev.seasonal_outlook?.quantities ?? {}).length > 0 && (
        <div style={{ ...box, marginTop: 8 }}>
          <div style={{ fontWeight: 600, color: 'var(--heading)', marginBottom: 4 }}>Seasonal outlook (ECMWF SEAS5{ev.seasonal_outlook.run ? `, ${fdate(ev.seasonal_outlook.run)}` : ''})</div>
          {Object.entries(ev.seasonal_outlook.quantities).map(([k, q]) => (
            <KV key={k} k={q.label} v={`median ${q.median ?? 'n/a'}, normal ${q.normal ?? 'n/a'}; ${pctTriple(q.chances_pct) ?? ''}${q.skill ? ` (skill: ${q.skill})` : ''}`}/>
          ))}
        </div>
      )}
    </>
  )
}

function TrackerChangesEvidence({ ev }) {
  const th = { textAlign: 'left', fontWeight: 600, fontSize: 12, color: 'var(--text-meta)', padding: '4px 6px', borderBottom: '1px solid var(--border-primary)' }
  const td = { padding: '4px 6px', borderBottom: '1px solid var(--border-primary)', fontSize: 12.5, fontVariantNumeric: 'tabular-nums' }
  return (
    <>
      <div style={{ ...box, overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <caption style={{ ...lbl, textAlign: 'left', marginBottom: 4 }}>Runs of {dm(ev.runs.previous)} and {dm(ev.runs.latest)}, over the days both cover</caption>
          <thead><tr><th style={th} scope="col">Model</th><th style={th} scope="col">Days</th><th style={th} scope="col">Previous</th><th style={th} scope="col">Latest</th><th style={th} scope="col">Change</th></tr></thead>
          <tbody>{ev.weather_models.map(m => (
            <tr key={m.model}><td style={td}>{m.model}</td><td style={td}>{dm(m.days[0])} - {dm(m.days[1])}</td>
              <td style={td}>{mm(m.previous_run_mm)}</td><td style={td}>{mm(m.latest_run_mm)}</td><td style={td}>{m.change_mm > 0 ? '+' : ''}{m.change_mm} mm</td></tr>
          ))}</tbody>
        </table>
      </div>
      <div style={{ ...box, marginTop: 8 }}>
        <div style={{ fontWeight: 600, color: 'var(--heading)', marginBottom: 4 }}>Observed, last 3 days of data</div>
        {(ev.observed_last_3_days ?? []).map(o => <KV key={o.product} k={o.product} v={`${mm(o.mm)} (${dm(o.days[0])} - ${dm(o.days[1])})`}/>)}
      </div>
    </>
  )
}

function AreaForm({ request, onProfile, onDraw, drawing }) {
  const { data } = useRegions(request.season)
  const kind = data?.kind === 'region' ? 'Region' : 'County'
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'flex-end', marginTop: 8 }}>
      <Pick id="area-name" label={kind} value={request.name || ''} onChange={v => onProfile({ name: v, bbox: '' })}
            choices={[['', request.bbox ? 'Drawn area' : 'Choose...'], ...(data?.names ?? []).map(n => [n, n])]}/>
      <button type="button" onClick={onDraw} aria-pressed={drawing}
              style={{ background: drawing ? 'var(--nav-active-bg)' : 'var(--bg-elevated)', color: 'var(--accent-text)', border: '1px solid var(--info-border)',
                       borderRadius: 8, padding: '5px 10px', fontSize: 13, fontWeight: 600, cursor: 'pointer', minHeight: 32 }}>
        {drawing ? 'Click two corners on the map...' : 'Draw an area on the map'}
      </button>
    </div>
  )
}

function AttentionForm({ request, onProfile, onShowLayer }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'flex-end', marginTop: 8 }}>
      <Pick id="att-criterion" label="Criterion" value={request.criterion ?? 'late_onset'} choices={CRITERIA} onChange={v => onProfile({ criterion: v })}/>
      <button type="button" onClick={onShowLayer}
              style={{ background: 'var(--bg-elevated)', color: 'var(--accent-text)', border: '1px solid var(--info-border)', borderRadius: 8,
                       padding: '5px 10px', fontSize: 13, fontWeight: 600, cursor: 'pointer', minHeight: 32 }}>Show on the map</button>
    </div>
  )
}

function ChartForm({ request, onProfile }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 8, marginTop: 8 }}>
      <Pick id="chart-kind" label="Chart" value={request.chart ?? 'member_dates'} choices={CHARTS} onChange={v => onProfile({ chart: v })}/>
      {(request.chart ?? 'member_dates') === 'member_dates' && <Pick id="chart-q" label="Quantity" value={request.quantity ?? 'onset'} choices={QUANTITIES} onChange={v => onProfile({ quantity: v })}/>}
      {request.chart === 'crop_outcomes' && <Pick id="chart-crop" label="Crop" value={request.crop ?? 'maize_early'} choices={CROPS} onChange={v => onProfile({ crop: v })}/>}
    </div>
  )
}

function AttentionTable({ ev }) {
  const u = ev.criterion.value_unit === '%' ? '%' : ' days'
  const th = { textAlign: 'left', fontWeight: 600, fontSize: 12, color: 'var(--text-meta)', padding: '4px 6px', borderBottom: '1px solid var(--border-primary)' }
  const td = { padding: '5px 6px', borderBottom: '1px solid var(--border-primary)', fontSize: 13, fontVariantNumeric: 'tabular-nums' }
  const rows = ev.ranked_areas.filter(r => r.flagged_cells > 0)
  if (!rows.length) return <p style={{ ...lbl, fontSize: 13 }}>No area meets this criterion in the current run.</p>
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 8 }}>
      <caption style={{ ...lbl, textAlign: 'left', marginBottom: 4 }}>{ev.criterion.label}: {ev.criterion.test}</caption>
      <thead><tr><th style={th} scope="col">#</th><th style={th} scope="col">Area</th><th style={th} scope="col">Cells meeting it</th><th style={th} scope="col">Average</th></tr></thead>
      <tbody>{rows.map((r, i) => (
        <tr key={r.area}><td style={td}>{i + 1}</td><td style={td}>{r.area}</td><td style={td}>{r.flagged_pct}% of {r.cells}</td><td style={td}>{r.mean_value}{u}</td></tr>
      ))}</tbody>
    </table>
  )
}

function AreaEvidence({ ev }) {
  return (
    <>
      <div style={box}>
        <KV k="Area" v={ev.scope.name}/>
        <KV k="Grid cells" v={ev.scope.cells}/>
        <KV k="Run" v={ev.run.model}/>
      </div>
      {Object.entries(ev.quantities).map(([k, q]) => (
        <div key={k} style={{ ...box, marginTop: 8 }}>
          <div style={{ fontWeight: 600, color: 'var(--heading)', marginBottom: 4 }}>{q.label}</div>
          <KV k="Middle of the area" v={valueOf(q, q.cell_medians.median)}/>
          <KV k="8 in 10 cells" v={`${valueOf(q, q.cell_medians.p10)} to ${valueOf(q, q.cell_medians.p90)}`}/>
          <KV k="Area-wide (members)" v={q.area_event_chances_pct ? Object.entries(q.area_event_chances_pct).map(([c, v]) => `${c} ${v}%`).join(', ') : null}/>
          <KV k="Typical place (skill-weighted)" v={pctTriple(q.average_cell_chances_pct)}/>
        </div>
      ))}
    </>
  )
}

function ChartEvidence({ ev }) {
  if (ev.chart === 'member_dates') {
    const max = Math.max(1, ...ev.members_by_week.map(b => b.members))
    const lab = b => ev.quantity.unit === 'date' ? `${fdate(b.from).replace(/ \d{4}$/, '')} - ${fdate(b.to).replace(/ \d{4}$/, '')}` : `${b.from}-${b.to} d`
    return (
      <div style={box}>
        <div style={{ fontWeight: 600, color: 'var(--heading)', marginBottom: 6 }}>{ev.quantity.label}: members by week</div>
        {ev.members_by_week.map((b, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, margin: '2px 0' }}>
            <span style={{ flex: '0 0 120px', color: 'var(--text-meta)' }}>{lab(b)}</span>
            <span aria-hidden="true" style={{ height: 10, width: `${(b.members / max) * 60}%`, background: 'var(--accent-text)', borderRadius: 3 }}/>
            <span>{b.members}</span>
          </div>
        ))}
      </div>
    )
  }
  if (ev.chart === 'crop_outcomes') {
    return (
      <div style={box}>
        <KV k="Crop" v={`${ev.crop} at ${ev.scope.crop_site}`}/>
        <KV k="Yield (t/ha)" v={`median ${ev.yield_t_ha.median}; 8 in 10 between ${ev.yield_t_ha.p10} and ${ev.yield_t_ha.p90}`}/>
        <KV k="Outcomes" v={Object.entries(ev.outcomes).map(([k, v]) => `${k} ${v}`).join(', ')}/>
        <KV k="Harvest" v={ev.harvest_range ? `${fdate(ev.harvest_range[0])} to ${fdate(ev.harvest_range[1])}` : null}/>
      </div>
    )
  }
  return <div style={box}><KV k="Rainfall plume" v={ev.illustrative ? 'Illustrative on this server (not the forecast members)' : `season total median ${ev.season_total_mm?.median} mm`}/></div>
}

function AdvisoryForm({ request, onProfile }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 8, marginTop: 8 }}>
      <Pick id="adv-decision" label="Decision" value={request.decision ?? 'sowing'} choices={DECISIONS} onChange={v => onProfile({ decision: v })}/>
      <Pick id="adv-crop" label="Crop" value={request.crop ?? 'maize_early'} choices={CROPS} onChange={v => onProfile({ crop: v })}/>
      <Pick id="adv-planted" label="Field" value={request.planted ?? 'unknown'} choices={PLANTED} onChange={v => onProfile({ planted: v })}/>
      {request.planted === 'yes' && (
        <label htmlFor="adv-sown" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={lbl}>Sowing date</span>
          <input id="adv-sown" type="date" value={request.sowing_date ?? ''} onChange={e => onProfile({ sowing_date: e.target.value })}
                 style={{ background: 'var(--select-bg)', color: 'var(--heading)', border: '1px solid var(--border-primary)', borderRadius: 6, padding: '3px 6px', fontSize: 13 }}/>
        </label>
      )}
      <Pick id="adv-water" label="Water" value={request.water ?? 'rainfed'} choices={WATERS} onChange={v => onProfile({ water: v })}/>
      <Pick id="adv-objective" label="Objective" value={request.objective ?? 'maturity'} choices={OBJECTIVES} onChange={v => onProfile({ objective: v })}/>
    </div>
  )
}

const num = (v, unit = '') => v == null ? 'n/a' : `${v}${unit}`

function OptionsTable({ ev }) {
  if (!ev.options?.length) {
    return <p style={{ ...lbl, fontSize: 13 }}>{ev.crop_outlook?.reason ?? 'No crop options for this choice.'}</p>
  }
  const th = { textAlign: 'left', fontWeight: 600, fontSize: 12, color: 'var(--text-meta)', padding: '4px 6px', borderBottom: '1px solid var(--border-primary)' }
  const td = { padding: '5px 6px', borderBottom: '1px solid var(--border-primary)', fontSize: 13, fontVariantNumeric: 'tabular-nums', verticalAlign: 'top' }
  return (
    <div style={{ overflowX: 'auto', marginTop: 8 }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <caption style={{ ...lbl, textAlign: 'left', marginBottom: 4 }}>
          Options under the same forecast, ranked by: {ev.objective.label.toLowerCase()} (crop outlook, experimental)
        </caption>
        <thead><tr>
          <th style={th} scope="col">#</th><th style={th} scope="col">Option</th><th style={th} scope="col">Reach maturity</th>
          <th style={th} scope="col">Median yield (t/ha)</th><th style={th} scope="col">Poor year, 1 in 10 (t/ha)</th><th style={th} scope="col">Irrigation (mm)</th>
        </tr></thead>
        <tbody>
          {ev.options.map(o => (
            <tr key={o.id} style={{ opacity: o.past ? 0.55 : 1, background: o.rank === 1 ? 'var(--nav-active-bg)' : 'transparent' }}>
              <td style={td}>{o.rank ?? '-'}</td>
              <td style={td}>{o.label}{o.is_baseline ? ' (reference)' : ''}{o.past ? ' (date already past)' : ''}
                {o.sowing_median && <div style={{ ...lbl, fontSize: 11.5 }}>sown about {fdate(o.sowing_median)}</div>}</td>
              <td style={td}>{num(o.p_mature_pct, '%')}</td>
              <td style={td}>{num(o.yield_median)}</td>
              <td style={td}>{num(o.yield_p10)}</td>
              <td style={td}>{num(o.irrigation_mm)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AdvisoryEvidence({ ev }) {
  const a = ev.applies_to
  return (
    <>
      <div style={box}>
        <KV k="Decision" v={`${ev.decision.label}: ${ev.decision.question}`}/>
        <KV k="Place" v={typeof a.place === 'string' ? a.place : `${a.place.lat}, ${a.place.lon}`}/>
        <KV k="Crop" v={a.crop}/>
        <KV k="Stage" v={a.stage}/>
        <KV k="Water" v={a.water}/>
        <KV k="Season and method" v={`${a.season}, ${a.method}`}/>
        <KV k="Crop site" v={a.crop_site ? `${a.crop_site} (${a.crop_site_km} km)` : null}/>
        <KV k="Sowing rule" v={a.sowing_rule}/>
        <KV k="Crop outlook" v={ev.crop_outlook.available ? `${ev.crop_outlook.engine}, ${ev.crop_outlook.run}, observations to ${fdate(ev.crop_outlook.observations_through)}` : ev.crop_outlook.reason}/>
      </div>
      <div style={{ ...box, marginTop: 8 }}>
        <div style={{ fontWeight: 600, color: 'var(--heading)', marginBottom: 4 }}>Rules used</div>
        {ev.rules_used.length ? ev.rules_used.map(r => <KV key={r.id} k={r.id} v={r.status === 'reviewed' ? `Reviewed by ${r.reviewed_by}` : 'Draft: not yet reviewed'}/>)
          : <p style={{ ...lbl, margin: 0 }}>No rule applies to this situation.</p>}
      </div>
      <div style={{ ...box, marginTop: 8 }}>
        <div style={{ fontWeight: 600, color: 'var(--heading)', marginBottom: 4 }}>Forecast behind the card</div>
        {['onset', 'cessation', 'lgp'].map(k => {
          const c = ev.climate[k]
          const unit = k === 'lgp' ? 'days' : 'date'
          return <KV key={k} k={{ onset: 'Onset', cessation: 'Cessation', lgp: 'Season length' }[k]}
                     v={`${valueOf({ unit }, c.median) ?? 'n/a'}${c.chances_pct ? '; ' + pctTriple(c.chances_pct) : ''}`}/>
        })}
      </div>
    </>
  )
}

export default function ExplainPanel({ request, onClose, onAudience, compareOptions, onCompare, onProfile, onDraw, drawing, onShowLayer }) {
  const { data: langs } = useLanguages()
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
          <label style={lbl} htmlFor="explain-language">Language</label>
          <select id="explain-language" value={request.language ?? 'en'} onChange={e => onProfile({ language: e.target.value })}
                  style={{ background: 'var(--select-bg)', color: 'var(--heading)', border: '1px solid var(--border-primary)', borderRadius: 6, padding: '4px 6px', fontSize: 13 }}>
            {Object.entries(langs ?? { en: { native: 'English' } }).map(([k, l]) => <option key={k} value={k}>{l.native}</option>)}
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
        {request.kind === 'advisory' && <AdvisoryForm request={request} onProfile={onProfile}/>}
        {request.kind === 'area' && <AreaForm request={request} onProfile={onProfile} onDraw={onDraw} drawing={drawing}/>}
        {request.kind === 'attention' && <AttentionForm request={request} onProfile={onProfile} onShowLayer={onShowLayer}/>}
        {request.kind === 'chart' && <ChartForm request={request} onProfile={onProfile}/>}
        {(request.kind === 'tracker' || request.kind === 'tracker_changes') && <TrackerForm request={request} onProfile={onProfile}/>}
        <nav role="tablist" aria-label="Explanation sections" style={{ display: 'flex', gap: 4, marginTop: 10 }}>
          {tabs.map(([id, label]) => (
            <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)} style={btn(tab === id)}>{label}</button>
          ))}
        </nav>
      </header>
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px' }} role="tabpanel">
        {isLoading && <p style={{ color: 'var(--text-meta)' }}>Preparing the explanation...</p>}
        {isError && <p style={{ color: 'var(--bad-text)' }}>{error?.message ?? 'The explanation could not be made.'}</p>}
        {ev?.kind === 'advisory' && tab !== 'evidence' && (
          <p style={{ margin: '0 0 10px', padding: '6px 10px', borderRadius: 6, background: 'var(--exp-bg)', color: 'var(--exp-text)', fontSize: 13, fontWeight: 600 }}>
            Draft guidance: not yet reviewed by an agronomist. Options to consider, not instructions.
          </p>
        )}
        {ex?.translation_notice && tab !== 'evidence' && (
          <p style={{ margin: '0 0 10px', padding: '6px 10px', borderRadius: 6, background: 'var(--caution-bg)', color: 'var(--caution-text)', fontSize: 12.5 }}>{ex.translation_notice}</p>
        )}
        {ex?.translation_note && tab !== 'evidence' && <p style={{ ...lbl, margin: '0 0 8px' }}>{ex.translation_note}</p>}
        {ex && tab !== 'evidence' && (
          <div style={{ marginBottom: 8 }}>
            <ListenButton text={(tab === 'summary' ? ex.sections.summary : ex.sections.local_implications).join(' ')} lang={speechCode(langs, ex.language ?? 'en')}
                          style={{ background: 'var(--bg-elevated)', color: 'var(--accent-text)', border: '1px solid var(--info-border)', borderRadius: 8, padding: '3px 9px', fontSize: 12.5, fontWeight: 600, cursor: 'pointer' }}/>
          </div>
        )}
        {ex && tab === 'summary' && <Para lines={ex.sections.summary}/>}
        {ev?.kind === 'advisory' && tab === 'summary' && <OptionsTable ev={ev}/>}
        {ev?.kind === 'attention' && tab === 'summary' && <AttentionTable ev={ev}/>}
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
            {ev.kind === 'advisory' && <AdvisoryEvidence ev={ev}/>}
            {ev.kind === 'area' && <AreaEvidence ev={ev}/>}
            {ev.kind === 'attention' && <AttentionTable ev={ev}/>}
            {ev.kind === 'chart' && <ChartEvidence ev={ev}/>}
            {ev.kind === 'tracker' && <TrackerEvidence ev={ev}/>}
            {ev.kind === 'tracker_changes' && <TrackerChangesEvidence ev={ev}/>}
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
