import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

// How well past crop forecasts did, in full (crop_engine/hindcast.py; crop_engine/dashboard.py write_hindcast writes
// hindcast.json; the sub-seasonal scores come from skill.json): every 1 Oct SEAS5 forecast of the hindcast years grown
// again through the crop model, as this season's is, and compared year by year with the same model's crop grown in the
// weather that came. It tests the forecast, not the crop model: the reference is a simulated crop, not a measured one.
const DATA = 'tracker/data/crop/'
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const fmtDate = iso => { if (!iso) return '—'; const [, m, d] = iso.split('-').map(Number); return `${d} ${MONTHS[m - 1]}` }
const getJSON = u => fetch(u).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json() })
const r2 = v => v == null ? '—' : v.toFixed(2)
const pct = v => v == null ? '—' : `${Math.round(v * 100)}%`
const fmtT = v => v == null ? '—' : v < 0.05 ? '0' : v.toFixed(1)
const median = a => { const s = a.filter(v => v != null).sort((x, y) => x - y); if (!s.length) return null
                      const h = s.length >> 1; return s.length % 2 ? s[h] : (s[h - 1] + s[h]) / 2 }
const ENGINES = { aquacrop: 'AquaCrop', wofost: 'WOFOST', dssat: 'DSSAT' }
const PREDICTORS = [['lgp', 'Season length'], ['rain', 'Oct–Dec rain'], ['onset', 'Onset date']]
const IN_TEXT = { lgp: 'season length', rain: 'Oct–Dec rain', onset: 'onset date' }
const S2S_CROPS = ['maize_early', 'sorghum']

// plain words for a score; rough bands, since with 24 years a value is uncertain by about ±0.2
const wordR = r => r == null ? '' : r >= 0.6 ? 'strong' : r >= 0.4 ? 'useful' : r >= 0.2 ? 'weak' : 'none'
const wordAuc = a => a == null ? '' : a >= 0.8 ? 'good' : a >= 0.7 ? 'useful' : a >= 0.6 ? 'weak' : 'none'
const wordBss = b => b == null ? '' : b >= 0.3 ? 'good' : b >= 0.1 ? 'some' : b > 0 ? 'little' : 'none'

const madeNote = (made, current) => {
  if (!made) return ''
  const old = made.config_hash && current && made.config_hash !== current
  return `made ${fmtDate(made.created?.slice(0, 10))}${old ? ', with an earlier crop configuration than this outlook' : ''}`
}

function useWidth() {
  const ref = useRef(null)
  const [w, setW] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return undefined
    const ro = new ResizeObserver(([x]) => setW(Math.floor(x.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, w]
}

const th = { padding: '7px 9px', textAlign: 'left', fontSize: 12.5, fontWeight: 600, color: 'var(--text-meta)', borderBottom: '1px solid var(--border-primary)',
             whiteSpace: 'nowrap', verticalAlign: 'bottom' }
const td = { padding: '7px 9px', fontSize: 13.5, color: 'var(--text-body)', borderBottom: '1px solid var(--border-primary)', fontVariantNumeric: 'tabular-nums',
             whiteSpace: 'nowrap' }
const H4 = ({ children }) => <h4 style={{ fontSize: 14.5, fontWeight: 600, color: 'var(--heading)', margin: '20px 0 6px' }}>{children}</h4>
const Note = ({ children, style }) => <p style={{ fontSize: 13, color: 'var(--text-meta)', margin: '6px 0 0', lineHeight: 1.5, ...style }}>{children}</p>

function Tile({ label, value, word, sub }) {
  return (
    <div style={{ border: '1px solid var(--border-primary)', borderRadius: 10, padding: '12px 14px', minWidth: 0 }}>
      <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-meta)' }}>{label}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 2 }}>
        <span style={{ fontSize: 24, fontWeight: 600, color: 'var(--heading)', fontVariantNumeric: 'tabular-nums' }}>{value}</span>
        {word && <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-body)' }}>{word}</span>}
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--text-meta)', marginTop: 4, lineHeight: 1.45 }}>{sub}</div>
    </div>
  )
}

// ── Year by year: the crop in the observed weather, the forecast median, and the forecast's chance of failure ───────
function YearChart({ years, e, thr, eng }) {
  const [ref, w] = useWidth()
  const [hi, setHi] = useState(null)
  const n = years.length
  const m = { l: 44, r: 10, t: 12 }
  const H1 = 190, GAP = 26, H2 = 96, AX = 34
  const H = m.t + H1 + GAP + H2 + AX
  const iw = Math.max(0, w - m.l - m.r), bw = iw / n
  const cx = i => m.l + (i + 0.5) * bw
  const top = Math.max(2, ...e.obs.filter(v => v != null), ...e.fc.filter(v => v != null))
  const step = top > 6 ? 2 : 1, yMax = Math.ceil(top / step) * step
  const y1 = v => m.t + (1 - v / yMax) * H1
  const b0 = m.t + H1 + GAP, y2 = p => b0 + (1 - p) * H2
  const failed = e.obs.map(v => v == null ? null : v < thr)
  const every = bw >= 34 ? 1 : bw >= 17 ? 2 : 4
  const barW = Math.max(3, Math.min(14, bw - 4))
  const usual = e.all?.fail_rate
  const move = ev => {
    const r = ev.currentTarget.getBoundingClientRect()
    const i = Math.floor((ev.clientX - r.left - m.l) / bw)
    setHi(i < 0 || i >= n ? null : i)
  }
  const nFail = failed.filter(Boolean).length
  const caught = failed.map((f, i) => f && e.p_fail[i] >= 0.5).filter(Boolean).length
  const legend = [
    ['dot', 'var(--heading)', `Crop grown in the observed weather (${ENGINES[eng]})`],
    ['dot', 'var(--crop-fc)', 'Forecast: median of the 25 members'],
    ['bar', 'var(--crop-fc)', 'Forecast chance of crop failure'],
    ['x', 'var(--heading)', `The crop failed in the observed weather (below ${thr} t/ha or not grown)`],
    ['dash', 'var(--text-meta)', `Failure threshold, ${thr} t/ha`],
    ...(usual != null ? [['dash', 'var(--heading)', `Usual failure rate, ${pct(usual)}`]] : []),
  ]
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <div className="flex flex-wrap gap-x-5 gap-y-1" style={{ fontSize: 13, color: 'var(--text-body)', marginBottom: 6 }}>
        {legend.map(([k, c, l]) => (
          <span key={l} className="inline-flex items-center gap-2">
            <svg width="14" height="14" aria-hidden="true">
              {k === 'dot' && <circle cx="7" cy="7" r="5" fill={c}/>}
              {k === 'bar' && <rect x="3" y="1" width="8" height="13" rx="2" fill={c} opacity="0.55"/>}
              {k === 'dash' && <line x1="0" x2="14" y1="7" y2="7" stroke={c} strokeWidth="1.5" strokeDasharray="4 3"/>}
              {k === 'x' && <path d="M3 3L11 11M11 3L3 11" stroke={c} strokeWidth="2" strokeLinecap="round"/>}
            </svg>
            {l}
          </span>
        ))}
      </div>
      {w > 0 && (
        <svg width={w} height={H} role="img" style={{ display: 'block', touchAction: 'pan-y' }}
             aria-label={`Year by year, ${years[0]}–${years[n - 1]}: the crop failed in the observed weather in ${nFail} of ${n} years; `
                         + `the forecast gave it a chance of failure of 50% or more in ${caught} of those. The table below has every value.`}
             onPointerMove={move} onPointerLeave={() => setHi(null)}>
          {/* top: yields */}
          {Array.from({ length: yMax / step + 1 }, (_, k) => k * step).map(v => (
            <g key={'y' + v}>
              <line x1={m.l} x2={m.l + iw} y1={y1(v)} y2={y1(v)} stroke="var(--chart-grid)"/>
              <text x={m.l - 8} y={y1(v) + 4} fontSize="12" textAnchor="end" fill="var(--text-meta)">{v}</text>
            </g>
          ))}
          <text x={m.l} y={m.t - 2} fontSize="12" fill="var(--text-meta)" dy="-1">t/ha</text>
          <line x1={m.l} x2={m.l + iw} y1={y1(thr)} y2={y1(thr)} stroke="var(--text-meta)" strokeDasharray="4 4"/>
          {hi != null && <rect x={m.l + hi * bw} y={m.t} width={bw} height={H1 + GAP + H2} fill="var(--text-meta)" opacity="0.08"/>}
          {years.map((yr, i) => e.obs[i] != null && e.fc[i] != null && (
            <line key={'l' + yr} x1={cx(i)} x2={cx(i)} y1={y1(e.obs[i])} y2={y1(e.fc[i])} stroke="var(--text-meta)" strokeOpacity="0.5" strokeWidth="1.5"/>
          ))}
          {years.map((yr, i) => e.obs[i] != null && (
            <circle key={'o' + yr} cx={cx(i)} cy={y1(e.obs[i])} r="4.5" fill="var(--heading)" stroke="var(--bg-surface)" strokeWidth="2"/>
          ))}
          {years.map((yr, i) => e.fc[i] != null && (
            <circle key={'f' + yr} cx={cx(i)} cy={y1(e.fc[i])} r="4.5" fill="var(--crop-fc)" stroke="var(--bg-surface)" strokeWidth="2"/>
          ))}
          {/* bottom: the forecast's chance of failure */}
          {[0, 0.5, 1].map(p => (
            <g key={'p' + p}>
              <line x1={m.l} x2={m.l + iw} y1={y2(p)} y2={y2(p)} stroke="var(--chart-grid)"/>
              <text x={m.l - 8} y={y2(p) + 4} fontSize="12" textAnchor="end" fill="var(--text-meta)">{p * 100}%</text>
            </g>
          ))}
          {years.map((yr, i) => {
            const p = e.p_fail[i]
            if (p == null || p <= 0) return null
            const h = H2 * p, x = cx(i) - barW / 2, y = y2(p), rr = Math.min(4, barW / 2, h)
            return <path key={'b' + yr} fill="var(--crop-fc)" opacity="0.55"
                         d={`M${x},${b0 + H2}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + barW - rr}Q${x + barW},${y} ${x + barW},${y + rr}V${b0 + H2}Z`}/>
          })}
          {usual != null && (
            <line x1={m.l} x2={m.l + iw} y1={y2(usual)} y2={y2(usual)} stroke="var(--heading)" strokeDasharray="4 3" strokeWidth="1.5"/>
          )}
          {years.map((yr, i) => failed[i] && (
            <path key={'x' + yr} d={`M${cx(i) - 4},${b0 + H2 + 6}l8,8M${cx(i) + 4},${b0 + H2 + 6}l-8,8`} stroke="var(--heading)" strokeWidth="2" strokeLinecap="round"/>
          ))}
          {years.map((yr, i) => i % every === 0 && (
            <text key={'t' + yr} x={cx(i)} y={b0 + H2 + 30} fontSize="12" textAnchor="middle" fill="var(--text-meta)">{every > 1 ? `’${String(yr).slice(2)}` : yr}</text>
          ))}
        </svg>
      )}
      {hi != null && (
        <div style={{ position: 'absolute', top: 34, left: Math.min(Math.max(cx(hi) + 14, 0), Math.max(0, w - 250)), width: 236, pointerEvents: 'none',
                      background: 'var(--chart-tooltip-bg)', border: '1px solid var(--border-primary)', borderRadius: 8, padding: '8px 10px',
                      fontSize: 13, color: 'var(--text-body)', boxShadow: '0 4px 14px rgba(0,0,0,.18)' }}>
          <div style={{ fontWeight: 600, color: 'var(--heading)', marginBottom: 4 }}>Short Rains {years[hi]}</div>
          {[['Observed weather', `${fmtT(e.obs[hi])} t/ha${failed[hi] ? ' (failed)' : ''}`], ['Forecast median', `${fmtT(e.fc[hi])} t/ha`],
            ['Chance of failure', pct(e.p_fail[hi])], ['Season length (forecast)', e.lgp?.[hi] == null ? '—' : `${Math.round(e.lgp[hi])} days`]].map(([k, v]) => (
            <div key={k} className="flex justify-between gap-3"><span>{k}</span><span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{v}</span></div>
          ))}
        </div>
      )}
    </div>
  )
}

function download(name, rows) {
  const csv = rows.map(r => r.map(v => v == null ? '' : String(v)).join(',')).join('\n') + '\n'
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}

// one row of scores: each model's rank correlation, ROC area and Brier skill, and the platform's predictors
function ScoreCells({ c, county, models }) {
  const b = c?.aquacrop?.baselines
  return (
    <>
      {models.flatMap(k => {
        const x = c?.[k]?.all
        return [<td key={k + 'r'} style={{ ...td, fontWeight: 600 }}>{r2(x?.r)}</td>, <td key={k + 'a'} style={td}>{r2(x?.auc)}</td>,
                <td key={k + 'b'} style={td}>{r2(x?.bss)}</td>]
      })}
      {PREDICTORS.map(([k]) => <td key={k} style={td}>{r2(b?.[k]?.r)}</td>)}
      {county !== undefined && <td style={td}>{county ? `${r2(county.aquacrop?.forecast)} (${county.years.length} yr)` : '—'}</td>}
    </>
  )
}
const ScoreHead = ({ first, county, models }) => (
  <thead>
    <tr>
      <th style={th} rowSpan={2}>{first}</th>
      {models.map(k => <th key={k} style={{ ...th, textAlign: 'center' }} colSpan={3}>{ENGINES[k]}</th>)}
      <th style={{ ...th, textAlign: 'center', whiteSpace: 'normal' }} colSpan={3}>The platform’s forecasts as predictors, r</th>
      {county && <th style={{ ...th, whiteSpace: 'normal' }} rowSpan={2}>County yields, r (AquaCrop forecast)</th>}
    </tr>
    <tr>
      {models.flatMap(k => ['r', 'ROC', 'BSS'].map(x => <th key={k + x} style={th}>{x}</th>))}
      {PREDICTORS.map(([k, l]) => <th key={k} style={th}>{l}</th>)}
    </tr>
  </thead>
)

export default function CropHindcastPanel({ ix, sid, vk, rk, skill, onSite }) {
  const q = useQuery({ queryKey: ['crop-hindcast'], staleTime: 30 * 60_000, retry: false,
                       queryFn: () => getJSON(DATA + 'hindcast.json').catch(() => null) })
  const [eng, setEng] = useState('aquacrop')
  const d = q.data
  if (!d?.sites) return null                                            // not made yet: the section stays hidden
  const years = d.years
  const cell = d.sites[sid]?.[vk]?.[rk]
  const engs = Object.keys(ENGINES).filter(k => cell?.[k])
  const ek = cell?.[eng] ? eng : engs[0]
  const e = cell?.[ek]
  const v = ix.varieties?.[vk] ?? {}
  const thr = v.failure_t_ha ?? 0.5
  const ruleLabel = ix.planting_rules?.[rk] ?? rk
  const siteName = id => ix.sites?.[id]?.name ?? id
  const label = k => ix.varieties?.[k]?.label ?? k
  const county = d.county?.[sid]?.[vk]?.[rk]
  const all = Object.values(d.sites).flatMap(vs => Object.values(vs).flatMap(rs => Object.values(rs)))
  const models = Object.keys(ENGINES).filter(k => d.made?.[k])                 // the models with a hindcast on disk
  const overall = Object.keys(ENGINES).map(k => [k, median(all.map(c => c[k]?.all?.r)), median(all.map(c => c[k]?.all?.auc)),
                                                 all.filter(c => c[k]).length]).filter(x => x[3])
  const s2s = S2S_CROPS.includes(vk) && rk === 'rule1' ? skill?.s2s?.sites?.[sid]?.[vk] : null
  const best = e ? PREDICTORS.map(([k]) => [IN_TEXT[k], e.baselines?.[k]]).filter(([, x]) => x?.r != null).sort((a, b) => b[1].r - a[1].r)[0] : null
  const verdict = !e?.all?.r || !best ? ''
    : e.all.r > best[1].r + 0.1 ? ` Here the crop model ranks the years better than ${best[0]} alone does.`
    : e.all.r < best[1].r - 0.1 ? ` Here the ${best[0]} forecast alone ranks the years better (r ${r2(best[1].r)}): the crop model adds noise more than information.`
    : ` Here that is on a par with the best of them, ${best[0]} (r ${r2(best[1].r)}).`
  const csv = () => download(`crop_hindcast_${sid}_${vk}_${rk}.csv`, [
    ['year', ...engs.flatMap(k => [`${k}_observed_weather_t_ha`, `${k}_forecast_median_t_ha`, `${k}_forecast_p_failure`, `${k}_forecast_season_length_days`])],
    ...years.map((y, i) => [y, ...engs.flatMap(k => [cell[k].obs[i], cell[k].fc[i], cell[k].p_fail[i], cell[k].lgp?.[i]])])])

  return (
    <section aria-label="How well past forecasts did" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-primary)', borderRadius: 12,
                                                              padding: '16px 18px', minWidth: 0 }}>
      <h3 style={{ fontSize: 16, fontWeight: 600, color: 'var(--heading)', margin: 0 }}>How well past forecasts did (hindcast)</h3>
      <p style={{ fontSize: 13.5, color: 'var(--text-meta)', margin: '4px 0 0', lineHeight: 1.5, maxWidth: 900 }}>
        Every 1 Oct SEAS5 forecast of {years[0]}–{years[years.length - 1]} grown again through the crop model, as this season’s is, and compared
        with the same model’s crop grown in the weather that came. It tests the forecast, not the crop model: the reference is a simulated
        crop, not a measured yield (the county yields below are the measured check).
        {overall.length > 0 && ` Over every site, crop and sowing rule, the median rank correlation is ${overall.map(([k, r, a]) => `${r2(r)} with a failure ROC area of ${r2(a)} for ${ENGINES[k]}`).join(', and ')}.`}
      </p>

      {!e ? (
        <Note style={{ marginTop: 12 }}>No hindcast for {label(vk)}, {ruleLabel} at {siteName(sid)} yet.</Note>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2" role="radiogroup" aria-label="Crop model" style={{ margin: '14px 0 10px' }}>
            <span style={{ fontSize: 13.5, color: 'var(--text-meta)', marginRight: 4 }}>{siteName(sid)}, {label(vk)}, {ruleLabel}:</span>
            {engs.map(k => (
              <button key={k} type="button" role="radio" aria-checked={ek === k} onClick={() => setEng(k)}
                      style={{ fontSize: 13.5, fontWeight: 600, borderRadius: 999, padding: '5px 12px', minHeight: 32, cursor: 'pointer',
                               border: '1px solid var(--border-primary)', background: ek === k ? 'var(--nav-active-bg)' : 'transparent',
                               color: ek === k ? 'var(--heading)' : 'var(--text-body)' }}>
                {ENGINES[k]}
              </button>
            ))}
            {!engs.includes('wofost') && <span style={{ fontSize: 13, color: 'var(--text-meta)' }}>(WOFOST does not grow this crop)</span>}
          </div>

          <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
            <Tile label="Ranking the years" value={r2(e.all.r)} word={wordR(e.all.r)}
                  sub={<>Rank correlation of the forecast median with the crop in the observed weather, {e.all.n} years (1: every year in
                    order, 0: no better than chance).{e.sown_before_oct > 0 && e.oct?.r != null ? ` Crops sown from 1 Oct only: ${r2(e.oct.r)} (${e.oct.n} years).` : ''}</>}/>
            <Tile label="Spotting failed seasons" value={r2(e.all.auc)} word={wordAuc(e.all.auc)}
                  sub="ROC area of the forecast chance of failure: how often a failed year got a higher chance than a good year (0.5: a coin toss, 1: always)."/>
            <Tile label="Chance of failure vs. the usual rate" value={r2(e.all.bss)} word={wordBss(e.all.bss)}
                  sub={`Brier skill score against always giving the usual failure rate, ${pct(e.all.fail_rate)} (0: no better, 1: perfect, below 0: worse).`}/>
            <Tile label="Seasons that failed" value={e.all.ok != null ? `${e.all.n - e.all.ok} of ${e.all.n}` : '—'}
                  sub={<>In the observed weather: no crop, or below {thr} t/ha.{e.sown_before_oct > 0
                    ? ` ${e.sown_before_oct} sown in September, before the forecast starts (rain already observed).` : ''}</>}/>
          </div>
          <Note style={{ marginTop: 10 }}>
            The platform’s own forecasts, read as yield predictors for the same years and the same crop: {PREDICTORS.map(([k]) =>
              `${IN_TEXT[k]} r ${r2(e.baselines?.[k]?.r)}, ROC ${r2(e.baselines?.[k]?.auc)}`).join('; ')}.{verdict}
          </Note>

          <H4>Year by year</H4>
          <YearChart years={e.years ?? years} e={e} thr={thr} eng={ek}/>
          <details style={{ marginTop: 8 }}>
            <summary style={{ cursor: 'pointer', fontSize: 13.5, fontWeight: 600, color: 'var(--accent-text)' }}>The numbers, year by year</summary>
            <div style={{ overflowX: 'auto', marginTop: 6 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead><tr>
                  <th style={th} rowSpan={2}>Year</th>
                  {engs.map(k => <th key={k} style={{ ...th, textAlign: 'center' }} colSpan={4}>{ENGINES[k]}</th>)}
                </tr><tr>
                  {engs.flatMap(k => ['Observed weather, t/ha', 'Forecast median, t/ha', 'Chance of failure', 'Season length, days']
                    .map(h => <th key={k + h} style={{ ...th, whiteSpace: 'normal' }}>{h}</th>))}
                </tr></thead>
                <tbody>
                  {(e.years ?? years).map((y, i) => (
                    <tr key={y}>
                      <td style={td}>{y}</td>
                      {engs.flatMap(k => {
                        const c = cell[k]
                        return [<td key={k + 'o'} style={{ ...td, fontWeight: c.obs[i] < thr ? 400 : 600 }}>{fmtT(c.obs[i])}{c.obs[i] < thr ? ' ✕' : ''}</td>,
                                <td key={k + 'f'} style={td}>{fmtT(c.fc[i])}</td>, <td key={k + 'p'} style={td}>{pct(c.p_fail[i])}</td>,
                                <td key={k + 'l'} style={td}>{c.lgp?.[i] == null ? '—' : Math.round(c.lgp[i])}</td>]
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button type="button" onClick={csv}
                    style={{ marginTop: 8, background: 'none', border: '1px solid var(--border-primary)', color: 'var(--accent-text)', borderRadius: 8,
                             padding: '6px 12px', fontSize: 13.5, fontWeight: 600, cursor: 'pointer', minHeight: 34 }}>
              Download as CSV
            </button>
          </details>
        </>
      )}

      {county && (
        <>
          <H4>Against measured county yields</H4>
          <Note style={{ marginTop: 0 }}>
            The site’s county Short Rains maize yields (HarvestStat), {county.years.length} years ({county.years.join(', ')}): rank correlation of
            the yearly county yield with the forecast, with the crop grown in the observed weather, and with the forecast season length.
          </Note>
          <div style={{ overflowX: 'auto', marginTop: 6 }}>
            <table style={{ borderCollapse: 'collapse' }}>
              <thead><tr><th style={th}>Model</th><th style={th}>Forecast</th><th style={th}>Observed-weather crop</th><th style={th}>Season length</th></tr></thead>
              <tbody>
                {Object.keys(ENGINES).filter(k => county[k]).map(k => (
                  <tr key={k}><td style={td}>{ENGINES[k]}</td><td style={{ ...td, fontWeight: 600 }}>{r2(county[k].forecast)}</td>
                    <td style={td}>{r2(county[k].benchmark)}</td><td style={td}>{r2(county[k].lgp)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <Note>
            With so few years a value is uncertain by about ±0.4, and a county’s yield mixes every farm, variety and management in it, while the
            model grows one crop at one site: where even the observed-weather crop does not follow the county yields, the forecast cannot either.
            The regional outlook above checks every maize cell of the eastern counties against the same yields.
          </Note>
        </>
      )}

      <H4>Every site: {label(vk)}, {ruleLabel}</H4>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <ScoreHead first="Site" county models={models}/>
          <tbody>
            {Object.keys(d.sites).filter(id => d.sites[id]?.[vk]?.[rk]).map(id => (
              <tr key={id} style={id === sid ? { background: 'var(--nav-active-bg)' } : undefined}>
                <td style={{ ...td, whiteSpace: 'normal', minWidth: 160 }}>
                  {id === sid || !onSite ? <span style={{ fontWeight: id === sid ? 600 : 400 }}>{siteName(id)}</span>
                    : <button type="button" className="crop-step-link" style={{ fontSize: 13.5 }} onClick={() => onSite(id)}>{siteName(id)}</button>}
                </td>
                <ScoreCells c={d.sites[id][vk][rk]} county={d.county?.[id]?.[vk]?.[rk] ?? null} models={models}/>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <details style={{ marginTop: 12 }}>
        <summary style={{ cursor: 'pointer', fontSize: 13.5, fontWeight: 600, color: 'var(--accent-text)' }}>Every crop and sowing rule at {siteName(sid)}</summary>
        <div style={{ overflowX: 'auto', marginTop: 6 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <ScoreHead first="Crop, sowing rule" models={models}/>
            <tbody>
              {Object.entries(d.sites[sid] ?? {}).flatMap(([k, rs]) => Object.entries(rs).map(([r, c]) => (
                <tr key={k + r} style={k === vk && r === rk ? { background: 'var(--nav-active-bg)' } : undefined}>
                  <td style={{ ...td, whiteSpace: 'normal', minWidth: 160 }}>{label(k)}, {ix.planting_rules?.[r] ?? r}</td>
                  <ScoreCells c={c} models={models}/>
                </tr>
              )))}
            </tbody>
          </table>
        </div>
      </details>

      {s2s && (
        <>
          <H4>Sub-seasonal forecasts</H4>
          <Note style={{ marginTop: 0 }}>
            ECMWF extended-range reforecasts {skill.s2s.years?.join('–')} (AquaCrop, {label(vk)}): from each start
            date, the observed weather up to it and then other years’ weather (observations only), or the forecast’s 46 days of rain, or its rain and
            temperature, in between. Sown by {ix.planting_rules?.rule1 ?? 'rule 1'}, against the crop in the observed weather.
          </Note>
          <div style={{ overflowX: 'auto', marginTop: 6 }}>
            <table style={{ borderCollapse: 'collapse' }}>
              <thead><tr><th style={th}>Start date</th><th style={th}>Observations only, r / ROC</th><th style={th}>With the forecast rain</th>
                <th style={th}>With rain and temperature</th></tr></thead>
              <tbody>
                {Object.entries(s2s).map(([md, x]) => (
                  <tr key={md}><td style={td}>{fmtDate('2026-' + md)}</td>
                    {['reference', 'forecast', 'forecast_t'].map(k => <td key={k} style={td}>{x[k] ? `${r2(x[k].r)} / ${r2(x[k].auc)}` : '—'}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Note>The forecast helps where its column is higher than the observations-only one. These scores were {madeNote(skill.s2s, skill.s2s.current_config)}.</Note>
        </>
      )}

      <details style={{ marginTop: 14 }}>
        <summary style={{ cursor: 'pointer', fontSize: 13.5, fontWeight: 600, color: 'var(--accent-text)' }}>What the scores mean</summary>
        <ul style={{ fontSize: 13.5, color: 'var(--text-body)', lineHeight: 1.55, margin: '8px 0 0', paddingLeft: 20, maxWidth: 900 }}>
          <li><strong>r</strong>, the rank (Spearman) correlation of the forecast median with the reference yield over the years: does the forecast put good
            and bad seasons in the right order? 1 is a perfect order, 0 none. About 0.4 or more is useful with {years.length} years.</li>
          <li><strong>ROC</strong>, the area under the ROC curve of the forecast chance of failure: the chance that a year whose crop failed got a higher forecast
            chance of failure than a year whose crop did not. 0.5 is a coin toss, 1 perfect; 0.7 or more is useful.</li>
          <li><strong>BSS</strong>, the Brier skill score of the chance of failure, against always giving the usual (past) failure rate: above 0 it is better
            than the usual rate, 1 is perfect, below 0 it is worse.</li>
          <li><strong>The platform’s forecasts as predictors</strong>: the season length, the Oct–Dec rain and the onset date of the same forecasts, scored in the
            same way against the same crop. A crop model is worth its cost when it beats them; at present it is mostly on a par.</li>
          <li><strong>County yields</strong>: HarvestStat’s measured Short Rains maize yields of the site’s county, the only independent check; few years.</li>
          <li>With {years.length} years each value is uncertain by about ±0.2: differences smaller than that, between sites, crops or models, are noise.</li>
        </ul>
      </details>
      <Note style={{ marginTop: 10 }}>
        {Object.entries(d.made).map(([k, mm]) => `${ENGINES[k]}’s hindcast ${madeNote(mm, k === 'aquacrop' ? d.current_config : null)}`).join('; ')}. Temperature: the season’s
        average for each day (the forecast’s own temperature changes the scores by less than their noise). Method: CROP_ENGINE.md, Hindcast verification.
      </Note>
    </section>
  )
}
