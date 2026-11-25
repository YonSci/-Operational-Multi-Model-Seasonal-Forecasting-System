// The farm's latest daily crop run (crop_engine/farms.py, posted to the backend): AquaCrop from the farm's own
// sowing date and irrigation, in its cell's weather (observed rain, then the SEAS5 members) and soil, against the
// same crop and sowing day in the observed seasons 1993-2025.
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const fd = iso => { if (!iso) return 'n/a'; const [, m, d] = String(iso).slice(0, 10).split('-').map(Number); return `${d} ${MON[m - 1]}` }
const pct = v => (v == null ? 'n/a' : `${Math.round(v * 100)}%`)
const t = v => (v == null ? 'n/a' : `${Number(v).toFixed(1)} t/ha`)
const lbl = { fontSize: 12, color: 'var(--text-meta)' }

function Row({ k, v, note }) {
  return (
    <div style={{ display: 'flex', gap: 8, fontSize: 13, lineHeight: 1.45 }}>
      <span style={{ flex: 1, color: 'var(--text-meta)' }}>{k}</span>
      <span style={{ fontWeight: 600, color: 'var(--heading)', textAlign: 'right' }}>{v}{note ? <span style={{ fontWeight: 400, color: 'var(--text-meta)' }}> {note}</span> : null}</span>
    </div>
  )
}

// how many members ended each way, in words
function outcomes(share) {
  const words = { ok: 'reach maturity', died: 'end before full maturity (some still yield grain)', failed_establishment: 'fail to establish', too_late: 'cannot mature by the end of March',
                  not_sown: 'not sown', error: 'model error' }
  return Object.entries(share ?? {}).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${pct(v)} ${words[k] ?? k}`).join(', ')
}

export default function FarmRun({ sim, season }) {
  if (!season) return null
  const r = sim?.result
  const stale = r && !r.error && sim.inputs && season && (sim.inputs.sowing_date !== season.sowing_date || sim.inputs.crop !== season.crop
                || JSON.stringify(sim.inputs.irrigation ?? []) !== JSON.stringify(season.irrigation ?? []))
  const box = { border: '1px solid var(--border-primary)', borderRadius: 8, padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 4,
                background: 'var(--bg-elevated)' }
  if (!r) {
    return <div style={box}><p style={{ margin: 0, fontSize: 13 }}>The first crop run for this sowing arrives after the next daily update (it starts at 19:30, East Africa Time).</p></div>
  }
  if (r.error) {
    return <div style={box}><p style={{ margin: 0, fontSize: 13, color: 'var(--caution-text)' }}>The last crop run could not simulate this farm: {r.error}.</p></div>
  }
  const s = r.summary, b = s.vs_benchmark ?? {}, m = r.meta ?? {}
  return (
    <div style={box} aria-label="Farm crop run">
      <div style={{ fontWeight: 700, color: 'var(--heading)', fontSize: 13.5 }}>
        Crop run: {r.variety_label}, sown {fd(r.sowing_date)}{r.irrigation_mm ? `, ${Math.round(r.irrigation_mm)} mm irrigation` : ''}
      </div>
      <div style={lbl}>Run of {fd(sim.created_at)}; observed rain to {fd(m.obs_end)}, then the {m.members} members of {m.model_label}</div>
      {stale && <p style={{ margin: 0, fontSize: 12.5, color: 'var(--caution-text)' }}>The diary changed since this run; the next daily update uses the new entries.</p>}
      <Row k="Yield, median" v={t(s.yield_t_ha?.median)} note={`(${t(s.yield_t_ha?.p10)} to ${t(s.yield_t_ha?.p90)}; normal ${t(b.benchmark_median)})`}/>
      <Row k="Chance of crop failure" v={pct(s.p_failure)} note={`(under ${m.failure_t_ha} t/ha; normal ${pct(b.benchmark_p_failure)})`}/>
      {b.p_below_normal != null && <Row k="Chance of a below / above normal yield" v={`${pct(b.p_below_normal)} / ${pct(b.p_above_normal)}`}/>}
      {s.harvest_median && <Row k="Harvest, median" v={fd(s.harvest_median)}/>}
      {s.stress_days_median != null && <Row k="Days of water stress, median" v={Math.round(s.stress_days_median)}/>}
      <p style={{ margin: 0, fontSize: 12.5, lineHeight: 1.5 }}>Of the {m.members} forecast members, {outcomes(s.share)}.</p>
      <p style={{ margin: 0, ...lbl, lineHeight: 1.5 }}>
        {m.engine}, water-limited: the cell&apos;s weather and soil (about 28 km), not your field&apos;s;
        {r.nitrogen_kg_ha ? ` the ${Math.round(r.nitrogen_kg_ha)} kg N/ha recorded are not modelled yet;` : ''} no pests, diseases or weeds.
        The normal is the same crop sown on the same day in the observed seasons 1993-2025. Read the chances and the comparison with the
        normal, not the tonnes.
      </p>
    </div>
  )
}
