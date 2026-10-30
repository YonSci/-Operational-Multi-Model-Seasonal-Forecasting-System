import {
  CalendarRange, Percent, Layers, ShieldCheck, History as HistoryIcon, Satellite,
  ArrowRight, Sun, Moon, BookOpen
} from 'lucide-react'
import { version } from '../../package.json'
import { useModels, usePixelStats } from '../api/queries'

// One label per destination, the same as the dashboard's tabs
const FEATURES = [
  { id: 'forecast', icon: CalendarRange, title: 'Seasonal timing',
    desc: 'When the rains may start and end, and how long the season may last, for the method you choose.' },
  { id: 'probabilistic', icon: Percent, title: 'Probabilities',
    desc: 'The chance of an early, normal or late onset, and of a short or long season.' },
  { id: 'multimodel', icon: Layers, title: 'Compare models',
    desc: 'Kenya Long Rains outlooks from seven C3S seasonal models, combined according to their past skill.' },
  { id: 'validation', icon: ShieldCheck, title: 'Forecast performance',
    desc: 'How closely past forecasts matched the observed seasons, location by location.' },
  { id: 'historical', icon: HistoryIcon, title: 'Historical rainfall',
    desc: 'Observed onset, cessation and season length in past years, with the long-term trend.' },
  { id: 'tracker', icon: Satellite, title: 'Short Rains Tracker',
    desc: 'Rain so far from satellites and the next 7–16 days from weather models at monitored sites, updated daily.' },
]

// Onset / cessation methods offered for the Kenya Short Rains (Method selector in the dashboard)
const METHODS = [
  { name: 'Dunning', tag: 'Rainfall pattern',
    rule: 'Onset and cessation are the turning points of the accumulated rainfall anomaly over 1 Sep – 31 Dec (Dunning et al. 2016).',
    data: 'CHIRPS v2 · ECMWF SEAS5' },
  { name: 'Agri rules 1–3', tag: 'First planting rains',
    rule: 'Onset is the first rain heavy enough to plant on (20 mm in 3 or 5 days) with no long dry spell after it; cessation comes when rain falls short of evaporation demand. Adapted from ICPAC definitions.',
    data: 'CHIRPS v2 · ECMWF SEAS5 · Hargreaves PET' },
  { name: 'FAO water balance', tag: 'Soil water for the crop',
    rule: 'Onset when rain meets half the evaporation demand and the root zone holds enough water for maize; cessation when soil water, crop water use and rain all fall short.',
    data: 'CHIRPS v3 · ERA5-Land · SoilGrids · ECMWF SEAS5' },
]

// Compact overview: what the platform covers, with its scope; the full lists are one click away
const OVERVIEW = [
  { value: '7 models', label: 'Seasonal forecast models',
    desc: 'Seven C3S systems, combined for the Kenya Long Rains. Every other season uses ECMWF SEAS5.',
    cta: 'View models', tab: 'about', at: { section: 'data', anchor: 'about-models' } },
  { value: '5 methods', label: 'Ways to time the season',
    desc: 'Rainfall pattern, planting-rain rules and a crop-water balance, all five for the Kenya Short Rains.',
    cta: 'View methods', tab: 'about', at: { section: 'methods' } },
  { value: '2 countries', label: 'Coverage',
    desc: 'Kenya: Long Rains (MAM), Short Rains (OND). Ethiopia: Kiremt (JJAS), Belg (FMAM), Bega (ONDJ).',
    cta: 'View coverage', tab: 'about', at: { section: 'data', anchor: 'about-seasons' } },
  { value: 'Daily', label: 'Monitoring',
    desc: 'Satellite rainfall observations and 7–16 day weather forecasts for the Kenya Short Rains.',
    cta: 'View data sources', tab: 'about', at: { section: 'data', anchor: 'about-satellite' } },
]

// Live preview: the current Short Rains forecast at one monitored site, from the same API as the dashboard
const PREVIEW_SITE = { site_name: 'KALRO Kiboko, Makueni', lat: -2.21046, lon: 37.7190 }
const PREVIEW_RUNS = [['1001ol', 'ECMWF SEAS5 (Oct+Obs latest)', 'Oct 01 + latest observations'], ['0901', 'ECMWF SEAS5 (Sep)', 'Sep 01']]
const MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
const doyDate = (doy, year) => { const d = new Date(Date.UTC(year, 0, 1) + (Math.round(doy) - 1) * 864e5); return `${d.getUTCDate()} ${MON[d.getUTCMonth()]}` }
const isoDate = iso => { const [y, m, d] = iso.split('-').map(Number); return `${d} ${MON[m-1]} ${y}` }
const isoDoy = iso => { const [y, m, d] = iso.split('-').map(Number); return (Date.UTC(y, m - 1, d) - Date.UTC(y, 0, 1)) / 864e5 + 1 }

function ForecastPreview({ onOpen }) {
  const { data: models } = useModels('short_rains')
  const runs = models?.models ? Object.values(models.models) : []
  const pick = PREVIEW_RUNS.find(([, name]) => runs.some(r => r.raw_name === name))
  const run = pick && runs.find(r => r.raw_name === pick[1])
  const { data: px } = usePixelStats(pick ? PREVIEW_SITE : null, 'short_rains', pick?.[1] ?? '')
  const m = px?.models?.[pick?.[1]] ?? px?.models?.['ECMWF SEAS5']
  if (!run || !m?.on_med || !Array.isArray(m.p_on)) return null

  const year = run.op_year
  const lo = isoDoy(run.valid_start), hi = isoDoy(run.valid_end)
  const W = 680, L = 150, x = d => L + ((d - lo) / (hi - lo)) * (W - L - 16)   // left column holds the row labels
  const t33 = px.t33?.onset, t67 = px.t67?.onset
  const obs = run.obs_end ? isoDoy(run.obs_end) : null
  const ticks = MON.map((_, i) => isoDoy(`${year}-${String(i + 1).padStart(2, '0')}-01`)).filter(d => d >= lo && d <= hi)
  const pct = v => Math.round(v * 100) + '%'
  const [early, normal, late] = m.p_on
  const summary = `Onset median ${doyDate(m.on_med, year)}; 8 in 10 members between ${doyDate(m.on_p10, year)} and ${doyDate(m.on_p90, year)}.`
  const address = `#/forecast?country=kenya&season=short_rains&run=${pick[0]}&method=dunning&site=${PREVIEW_SITE.lat.toFixed(3)},${PREVIEW_SITE.lon.toFixed(3)}`

  return (
    <section className="site-section site-container" aria-labelledby="preview-heading">
      <div className="site-section-head">
        <h2 id="preview-heading">A current forecast</h2>
        <p className="site-section-intro">This is the live Short Rains onset forecast for one monitored site, exactly as the dashboard shows it.</p>
      </div>
      <div className="site-preview">
        <dl className="site-preview-meta">
          <div><dt>Location</dt><dd>{PREVIEW_SITE.site_name}, Kenya</dd></div>
          <div><dt>Season</dt><dd>Short Rains (OND) {year}</dd></div>
          <div><dt>Forecast run</dt><dd>ECMWF SEAS5, {pick[2]}</dd></div>
          <div><dt>Method</dt><dd>Dunning (rainfall pattern)</dd></div>
          <div><dt>Forecast initialised</dt><dd>{isoDate(run.init_date)}</dd></div>
          <div><dt>Observations through</dt><dd>{run.obs_end ? isoDate(run.obs_end) : 'None (forecast only)'}</dd></div>
        </dl>
        <div className="site-preview-body">
          <p className="site-preview-figure">Onset: median <strong>{doyDate(m.on_med, year)}</strong></p>
          <div className="site-preview-chart" tabIndex={0} aria-label="Onset timeline (scrolls sideways on small screens)">
          <svg viewBox={`0 0 ${W} 124`} role="img" aria-label={`${summary} Normal range ${t33 && t67 ? doyDate(t33, year) + ' to ' + doyDate(t67, year) : 'not available'}.`} className="site-preview-svg">
            {obs != null && obs >= lo && obs <= hi && <>
              <line x1={x(obs)} x2={x(obs)} y1={20} y2={96} stroke="var(--text-meta)" strokeDasharray="3 3"/>
              <text x={x(obs) - 4} y={14} textAnchor="end" className="site-preview-lbl">Observed to {isoDate(run.obs_end).replace(/ \d{4}$/, '')}</text>
            </>}
            <text x={0} y={44} className="site-preview-lbl">Normal (1993–2016)</text>
            {t33 != null && t67 != null && <rect x={x(t33)} y={30} width={Math.max(2, x(t67) - x(t33))} height={20} rx={4} fill="var(--border-primary)"/>}
            <text x={0} y={78} className="site-preview-lbl">Forecast members</text>
            <rect x={x(m.on_p10)} y={64} width={Math.max(2, x(m.on_p90) - x(m.on_p10))} height={20} rx={4} fill="var(--info-bg)" stroke="var(--accent-blue)"/>
            {m.on_p25 != null && m.on_p75 != null && <rect x={x(m.on_p25)} y={64} width={Math.max(2, x(m.on_p75) - x(m.on_p25))} height={20} fill="var(--accent-blue)" opacity="0.45"/>}
            <circle cx={x(m.on_med)} cy={74} r={7} fill="var(--btn-primary)" stroke="var(--bg-surface)" strokeWidth="2"/>
            <line x1={L} x2={W - 16} y1={100} y2={100} stroke="var(--border-primary)"/>
            {ticks.map(d => <g key={d}><line x1={x(d)} x2={x(d)} y1={100} y2={105} stroke="var(--text-meta)"/><text x={x(d) + 3} y={118} className="site-preview-tick">{MON[new Date(Date.UTC(year, 0, d)).getUTCMonth()]}</text></g>)}
          </svg>
          </div>
          <p className="site-preview-key">
            <span><i style={{background:'var(--border-primary)'}}/>Normal: middle third of 1993–2016</span>
            <span><i style={{background:'var(--info-bg)',border:'1px solid var(--accent-blue)'}}/>8 in 10 members</span>
            <span><i style={{background:'var(--accent-blue)',opacity:0.6}}/>Middle half of members</span>
            <span><i style={{background:'var(--btn-primary)',borderRadius:'50%'}}/>Median</span>
          </p>
          <p className="site-preview-text">{summary} Chance of an early onset {pct(early)}, normal {pct(normal)}, late {pct(late)}, compared with 1993–2016.</p>
          <p className="site-preview-note">A median date is a summary of the forecast members, not a promise: read it with the range and the chances.</p>
          <a className="site-btn site-btn-primary" href={address} onClick={e => { e.preventDefault(); onOpen(address) }}>
            Open this forecast <ArrowRight size={18} aria-hidden="true" />
          </a>
        </div>
      </div>
    </section>
  )
}

export default function LandingPage({ onEnter, onOpenAddress, darkMode, setDarkMode }) {
  return (
    <div className="site relative w-full min-h-screen overflow-x-hidden overflow-y-auto touch-scroll">
      <header className="site-container site-topbar">
        <div className="site-brand">
          <span className="site-brand-name">Seasonal Climate Forecast Dashboard</span>
          <span className="site-brand-sub">ILRI Climate Services, in collaboration with ICPAC</span>
        </div>
        <div className="site-topbar-actions">
          <button type="button" className="site-btn site-btn-quiet" onClick={() => setDarkMode(d => !d)}>
            {darkMode ? <Sun size={16} aria-hidden="true" /> : <Moon size={16} aria-hidden="true" />}
            {darkMode ? 'Light mode' : 'Dark mode'}
          </button>
        </div>
      </header>

      <main>
        <section className="site-hero">
          <div className="site-hero-grid" aria-hidden="true" />
          <div className="site-container">
            <div className="site-hero-inner">
              <p className="site-eyebrow">Kenya &amp; Ethiopia · Seasonal climate outlooks</p>
              <h1>Understand the timing of the rainy season</h1>
              <p className="site-hero-lede">
                Explore when rains may start and end, how long the season may last, and the uncertainty around these estimates.
              </p>
              <div className="site-hero-actions">
                <button type="button" className="site-btn site-btn-primary" onClick={() => onEnter('forecast')}>
                  Explore forecasts <ArrowRight size={18} aria-hidden="true" />
                </button>
                <button type="button" className="site-btn site-btn-secondary" onClick={() => onEnter('about')}>
                  <BookOpen size={18} aria-hidden="true" /> How the forecasts work
                </button>
              </div>
              <p className="site-hero-note">
                Forecast dates describe possible outcomes. Use them alongside current rainfall observations and weather updates.
              </p>
            </div>
          </div>
        </section>

        <div className="site-container">
          <div className="site-facts" role="list" aria-label="What the platform covers">
            {OVERVIEW.map(f => (
              <button key={f.label} type="button" role="listitem" className="site-fact" onClick={() => onEnter(f.tab, f.at)}>
                <span className="site-fact-value">{f.value}</span>
                <span className="site-fact-label">{f.label}</span>
                <span className="site-fact-desc">{f.desc}</span>
                <span className="site-card-link">{f.cta} <ArrowRight size={15} aria-hidden="true" /></span>
              </button>
            ))}
          </div>
        </div>

        <section className="site-section site-container" aria-labelledby="explore-heading">
          <div className="site-section-head">
            <h2 id="explore-heading">What you can explore</h2>
            <p className="site-section-intro">Each view opens the dashboard on that topic. You can switch between them at any time.</p>
          </div>
          <div className="site-grid-3">
            {FEATURES.map(f => {
              const Icon = f.icon
              return (
                <button key={f.id} type="button" className="site-card" onClick={() => onEnter(f.id)}>
                  <span className="site-card-icon"><Icon size={20} aria-hidden="true" /></span>
                  <h3>{f.title}</h3>
                  <p>{f.desc}</p>
                  <span className="site-card-link">Open <ArrowRight size={15} aria-hidden="true" /></span>
                </button>
              )
            })}
          </div>
        </section>

        <ForecastPreview onOpen={onOpenAddress} />

        <section className="site-section site-container" aria-labelledby="methods-heading">
          <div className="site-section-head">
            <h2 id="methods-heading">How the start and end of the season are defined</h2>
            <p className="site-section-intro">
              For the Kenya Short Rains you can choose the definition with the Method selector; the maps, probabilities, skill and bulletin follow it.
              The definitions answer different questions, so their dates can differ.
            </p>
          </div>
          <div className="site-grid-3">
            {METHODS.map(m => (
              <div key={m.name} className="site-card">
                <span className="site-card-tag">{m.tag}</span>
                <h3>{m.name}</h3>
                <p>{m.rule}</p>
                <span className="site-card-meta">Data: {m.data}</span>
              </div>
            ))}
          </div>
          <div className="site-callout">
            <h3>Reading the uncertainty</h3>
            <p>
              Each forecast is a set of equally likely model runs (members). The dashboard reports their median date, the range most of them fall in,
              and the chance of an early, normal or late season compared with 1993–2016. Forecast skill, shown under Forecast performance, varies by
              place, season and method, and is separate from this spread.
            </p>
          </div>
        </section>
      </main>

      <footer className="site-footer">
        <div className="site-container site-footer-grid">
          <div>
            <h2>Produced by</h2>
            <p>ILRI Climate Services, in collaboration with ICPAC, the Ethiopian Meteorological Institute and the Kenya Meteorological Department.</p>
          </div>
          <div>
            <h2>Contact</h2>
            <p>Dr. Teferi Demissie, project lead: <a href="mailto:t.demissie@cgiar.org">t.demissie@cgiar.org</a></p>
            <p>Yonas Mersha, technical lead: <a href="mailto:y.mersha@cgiar.org">y.mersha@cgiar.org</a></p>
          </div>
          <div>
            <h2>How to cite</h2>
            <p>Demissie, T., Mersha, Y., et al. (2026). Operational Multi-Model Seasonal Climate Forecast System for Onset, Cessation, and Length of Growing Period in Eastern Africa (v{version}). ILRI / ICPAC.</p>
            <p className="site-footer-version">Seasonal Climate Forecast Dashboard v{version}</p>
          </div>
        </div>
      </footer>
    </div>
  )
}
