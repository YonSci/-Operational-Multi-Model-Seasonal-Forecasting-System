import { useState } from 'react'
import { ArrowRight, Sun, Moon, CalendarRange, CloudRain, Sprout, BookOpen, ShieldCheck } from 'lucide-react'
import { version } from '../../package.json'
import { useHealth, useModels, usePixelStats } from '../api/queries'
import { BRAND } from '../brand'
import { latestShortRainsInit } from '../shortRainsRuns'

// Landing page: the product's identity, one live example, and three ways in (forecasts, rainfall tracking, crop
// outlooks). Navigation uses real links to dashboard addresses, so they open in a new tab too; an address that names
// no run opens the newest published run, the one the preview shows.
const ADDR = {
  forecast: '#/forecast?country=kenya&season=short_rains',
  probabilistic: '#/probabilistic?country=kenya&season=short_rains',
  multimodel: '#/multimodel?country=kenya&season=long_rains',
  validation: '#/validation?country=kenya&season=short_rains',
  historical: '#/historical?country=kenya&season=short_rains',
  tracker: '#/tracker?country=kenya&season=short_rains',
  crop: '#/crop?country=kenya&season=short_rains',
  subseasonal: '#/forecast?country=kenya&season=short_rains&type=subseasonal&model=s2s-ecmwf',
  medium: '#/forecast?country=kenya&season=short_rains&type=medium&model=ecmwf_ifs025',
  about: '#/about/overview',
}

const TIMESCALES = [
  { label: 'Seasonal', short: 'The season ahead', coverage: 'Kenya and Ethiopia, every season', address: ADDR.forecast },
  { label: 'Sub-seasonal', short: 'Weeks 2\u20136', coverage: 'Kenya Short Rains', address: ADDR.subseasonal },
  { label: 'Medium-range', short: 'The next 7\u201316 days', coverage: 'Kenya Short Rains', address: ADDR.medium },
  { label: 'Rainfall tracking', short: 'Recent observations', coverage: 'Kenya Short Rains, monitored sites', address: ADDR.tracker },
]

const COVERAGE = [
  ['Seasonal timing and probabilities', 'Kenya: Long Rains (MAM), Short Rains (OND). Ethiopia: Kiremt (JJAS), Belg (FMAM), Bega (ONDJ)'],
  ['Model comparison', 'Seven C3S seasonal systems, Kenya Long Rains (other seasons: ECMWF SEAS5)'],
  ['Timing definitions', 'Five: rainfall pattern, three planting-rain rules and a crop-water balance, Kenya Short Rains'],
  ['Sub-seasonal and medium-range', 'Kenya Short Rains, joined to the seasonal forecast, a new run each day'],
  ['Rainfall tracking', 'Kenya Short Rains, monitored sites, five satellite products, updated daily'],
  ['Crop outlooks (experimental)', 'Maize, sorghum and bean at the monitored Kenyan sites, Short Rains'],
]

const METHOD_FAMILIES = [
  ['Rainfall pattern', 'When does the seasonal rainfall pattern begin and end?'],
  ['Agricultural rainfall rules', 'Does a wet spell meet the rainfall and dry-spell criteria for planting?'],
  ['Crop-water balance', 'What do rainfall, evaporative demand and soil water imply for the growing period?'],
]

const PRINCIPLES = [
  'A forecast date summarises a range of possible outcomes; read it with that range and the chances.',
  'Different methods answer different questions, so their dates can differ.',
  'Forecast skill varies by location, season and method: check it before relying on a forecast.',
]

// ---- helpers ------------------------------------------------------------------------------------------------------
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const doyDate = (doy, year) => { const d = new Date(Date.UTC(year, 0, 1) + (Math.round(doy) - 1) * 864e5); return `${d.getUTCDate()} ${MON[d.getUTCMonth()]}` }
const isoDate = iso => { const [y, m, d] = iso.slice(0, 10).split('-').map(Number); return `${d} ${MON[m - 1]} ${y}` }
const isoDoy = iso => { const [y, m, d] = iso.slice(0, 10).split('-').map(Number); return (Date.UTC(y, m - 1, d) - Date.UTC(y, 0, 1)) / 864e5 + 1 }
const pct = v => `${Math.round(v * 100)}%`
// "2026-11-13T13:05+03:00" -> "13 Nov 2026, 13:05 EAT"
const stamp = iso => {
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2})?(Z|[+-]\d{2}:\d{2})?/.exec(iso ?? '')
  if (!m) return null
  const zone = { '+03:00': 'EAT', 'Z': 'UTC', '+00:00': 'UTC' }[m[3]] ?? ''
  return `${isoDate(m[1])}, ${m[2]} ${zone}`.trim()
}

// A link to a dashboard address: a real link (new tab, copy), opened in place by the app on a plain click
function AppLink({ to, open, className, children, ...rest }) {
  return (
    <a href={to} className={className} {...rest}
       onClick={e => { if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return; e.preventDefault(); open(to) }}>
      {children}
    </a>
  )
}

// ---- the live forecast preview ------------------------------------------------------------------------------------
const PREVIEW_SITE = { site_name: 'KALRO Kiboko, Makueni', lat: -2.21046, lon: 37.7190 }

function ForecastPreview({ open }) {
  const { data: models } = useModels('short_rains')
  const { data: health } = useHealth()
  const latest = models?.models ? latestShortRainsInit(models) : null
  const runs = models?.models ? Object.values(models.models) : []
  const run = latest && runs.find(r => r.raw_name === latest.model)
  const { data: px } = usePixelStats(run ? PREVIEW_SITE : null, 'short_rains', latest?.model ?? '')
  const m = px?.models?.[latest?.model] ?? px?.models?.['ECMWF SEAS5']
  if (!run || !m?.on_med || !Array.isArray(m.p_on)) {
    return <p className="lp-preview-wait">Loading the current forecast...</p>
  }

  const year = run.op_year
  const today = new Date().toISOString().slice(0, 10)
  const archived = run.valid_end && today > run.valid_end
  const daily = !!run.obs_end && /latest/.test(run.raw_name ?? '')
  const lastUpdate = health?.data_status?.last_update
  const hoursSince = lastUpdate ? (Date.now() - Date.parse(lastUpdate)) / 3.6e6 : null
  const status = archived ? ['Archived example', 'neutral']
    : daily && hoursSince != null && hoursSince > 36 ? ['Update overdue', 'warn']
    : daily ? ['Updated daily', 'ok'] : ['Current run', 'ok']

  // where the onset falls against the observations: a forecast, partly observed, or estimated from observations
  const obs = run.obs_end ? isoDoy(run.obs_end) : null
  const observed = obs != null && m.on_p90 != null && m.on_p90 <= obs
  const partly = !observed && obs != null && m.on_p10 != null && m.on_p10 <= obs
  const onsetLabel = observed ? 'Onset estimated from observations so far' : partly ? 'Median onset (partly observed)' : 'Median forecast onset'
  const range = m.on_p10 != null && m.on_p90 != null
    ? (Math.round(m.on_p10) === Math.round(m.on_p90)
      ? `8 in 10 members agree on ${doyDate(m.on_p10, year)}`
      : `8 in 10 members: ${doyDate(m.on_p10, year)} to ${doyDate(m.on_p90, year)}`)
    : null

  // the chances: the members' own, and the skill-weighted ones shown (alpha x members + (1 - alpha) / 3)
  const [early, normal, late] = m.p_on
  const t33 = px.t33?.onset, t67 = px.t67?.onset
  const members = Array.isArray(m.on_v) && m.on_v.length && t33 != null && t67 != null ? (() => {
    const n = m.on_v.length, e = m.on_v.filter(v => v < t33).length / n, l = m.on_v.filter(v => v > t67).length / n
    return [e, 1 - e - l, l]
  })() : null
  const alpha = typeof m.alpha_on_px === 'number' ? m.alpha_on_px : null

  // timeline: the normal range (middle third of 1993-2016), 8 in 10 members, the median, the observation cut-off
  const lo = isoDoy(run.valid_start), hi = isoDoy(run.valid_end)
  const W = 420, x = d => 8 + ((d - lo) / (hi - lo)) * (W - 16)
  const ticks = MON.map((_, i) => isoDoy(`${year}-${String(i + 1).padStart(2, '0')}-01`)).filter(d => d >= lo && d <= hi)
  const address = `#/forecast?country=kenya&season=short_rains&run=${latest.init}&method=dunning&site=${PREVIEW_SITE.lat.toFixed(3)},${PREVIEW_SITE.lon.toFixed(3)}`

  return (
    <div className="lp-preview-body">
      <div className="lp-preview-top">
        <span className="lp-kicker">Short Rains forecast</span>
        <span className={`lp-badge lp-badge-${status[1]}`}>{status[0]}</span>
      </div>
      <h3 className="lp-preview-title">KALRO Kiboko, Kenya</h3>
      <p className="lp-preview-sub">Short Rains {year} &middot; rainfall-pattern onset (Dunning) &middot; ECMWF SEAS5</p>

      <p className="lp-preview-figure"><strong>{doyDate(m.on_med, year)}</strong> <span>{onsetLabel}</span></p>
      {range && <p className="lp-preview-range">{range}</p>}

      <svg viewBox={`0 0 ${W} 74`} className="lp-timeline" role="img"
           aria-label={`${onsetLabel}: ${doyDate(m.on_med, year)}. ${range ?? ''}. Normal range ${t33 && t67 ? doyDate(t33, year) + ' to ' + doyDate(t67, year) : 'not available'}.`}>
        {t33 != null && t67 != null && <rect x={x(t33)} y={10} width={Math.max(2, x(t67) - x(t33))} height={12} rx={3} className="lp-tl-normal"/>}
        {m.on_p10 != null && m.on_p90 != null && <rect x={x(m.on_p10)} y={30} width={Math.max(6, x(m.on_p90) - x(m.on_p10))} height={12} rx={3} className="lp-tl-members"/>}
        <circle cx={x(m.on_med)} cy={36} r={6} className="lp-tl-median"/>
        {obs != null && obs >= lo && obs <= hi && <line x1={x(obs)} x2={x(obs)} y1={4} y2={50} className="lp-tl-obs"/>}
        <line x1={8} x2={W - 8} y1={54} y2={54} className="lp-tl-axis"/>
        {ticks.map(d => <text key={d} x={x(d) + 2} y={68} className="lp-tl-tick">{MON[new Date(Date.UTC(year, 0, d)).getUTCMonth()]}</text>)}
      </svg>
      <p className="lp-legend">
        <span><i className="lp-key-normal"/>Normal (middle third, 1993&ndash;2016)</span>
        <span><i className="lp-key-members"/>8 in 10 members</span>
        {obs != null && <span><i className="lp-key-obs"/>Observed to {isoDate(run.obs_end)}</span>}
      </p>

      <div className="lp-chances" role="group" aria-label="Chance of an early, normal or late onset">
        {[['Early', early], ['Normal', normal], ['Late', late]].map(([k, v]) => (
          <div key={k} className="lp-chance"><span className="lp-chance-v">{pct(v)}</span><span className="lp-chance-k">{k}</span></div>
        ))}
      </div>
      <p className="lp-preview-note">
        {members && alpha != null
          ? <>Chances are skill-weighted: the members alone give early {pct(members[0])}, normal {pct(members[1])}, late {pct(members[2])}; these are blended with the long-term average (one in three each) by past forecast skill (weight {alpha.toFixed(2)}).</>
          : <>Chances are skill-weighted: the members&apos; chances blended with the long-term average by past forecast skill.</>}
        {observed && <> With the onset already within the observed period, the blend understates how far the members agree. A rainfall-pattern onset is final only once the season&apos;s rainfall is complete.</>}
      </p>

      <dl className="lp-preview-meta">
        <div><dt>Forecast run</dt><dd>{latest.initLabel}</dd></div>
        <div><dt>Forecast initialised</dt><dd>{isoDate(run.init_date)}</dd></div>
        <div><dt>Observations through</dt><dd>{run.obs_end ? isoDate(run.obs_end) : 'None (forecast only)'}</dd></div>
        <div><dt>Last update</dt><dd>{stamp(lastUpdate) ?? 'Not reported'}</dd></div>
      </dl>
      <AppLink to={address} open={open} className="lp-link">Open this forecast <ArrowRight size={16} aria-hidden="true"/></AppLink>
    </div>
  )
}

function RainfallPreview({ open }) {
  return (
    <div className="lp-preview-body">
      <div className="lp-preview-top"><span className="lp-kicker">Rainfall tracking</span><span className="lp-badge lp-badge-info">Kenya Short Rains</span></div>
      <h3 className="lp-preview-title">Follow the season as it unfolds.</h3>
      <p className="lp-preview-text">Compare satellite rainfall estimates at monitored sites with the weather outlook for the next 7&ndash;16 days.</p>
      <ul className="lp-chips" aria-label="Satellite rainfall products">
        {['CHIRPS', 'ARC2', 'TAMSAT', 'PDIR-Now', 'IMERG'].map(p => <li key={p}>{p}</li>)}
      </ul>
      <p className="lp-preview-note">Each product carries its own observation date and reporting delay.</p>
      <AppLink to={ADDR.tracker} open={open} className="lp-link">Open rainfall tracking <ArrowRight size={16} aria-hidden="true"/></AppLink>
    </div>
  )
}

function CropPreview({ open }) {
  return (
    <div className="lp-preview-body">
      <div className="lp-preview-top"><span className="lp-kicker">Crop outlook</span><span className="lp-badge lp-badge-exp">Experimental</span></div>
      <h3 className="lp-preview-title">Examine possible crop outcomes.</h3>
      <p className="lp-preview-text">Maize, sorghum and bean simulations, model comparisons and management scenarios at monitored Kenyan sites.</p>
      <ul className="lp-chips lp-chips-plain" aria-label="Crop models">
        {['AquaCrop', 'WOFOST', 'DSSAT'].map(p => <li key={p}>{p}</li>)}
      </ul>
      <p className="lp-preview-note">Model availability depends on crop and run. Crop forecasts are not yet verified against observed crop outcomes.</p>
      <AppLink to={ADDR.crop} open={open} className="lp-link">Open crop outlooks <ArrowRight size={16} aria-hidden="true"/></AppLink>
    </div>
  )
}

const PREVIEWS = [
  { id: 'forecast', label: 'Forecasts', Panel: ForecastPreview },
  { id: 'rainfall', label: 'Rainfall', Panel: RainfallPreview },
  { id: 'crops', label: 'Crops', Panel: CropPreview },
]

function PreviewCard({ open }) {
  const [tab, setTab] = useState('forecast')
  const i = PREVIEWS.findIndex(p => p.id === tab)
  const onKey = e => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    const next = PREVIEWS[(i + (e.key === 'ArrowRight' ? 1 : PREVIEWS.length - 1)) % PREVIEWS.length]
    setTab(next.id)
    document.getElementById(`lp-tab-${next.id}`)?.focus()
  }
  const { Panel } = PREVIEWS[i]
  return (
    <div className="lp-preview">
      <div className="lp-tabs" role="tablist" aria-label="Product examples" onKeyDown={onKey}>
        {PREVIEWS.map(p => (
          <button key={p.id} id={`lp-tab-${p.id}`} type="button" role="tab" aria-selected={tab === p.id}
                  aria-controls="lp-preview-panel" tabIndex={tab === p.id ? 0 : -1} className="lp-tab" onClick={() => setTab(p.id)}>
            {p.label}
          </button>
        ))}
      </div>
      <div id="lp-preview-panel" role="tabpanel" aria-labelledby={`lp-tab-${tab}`} className="lp-preview-panel">
        <Panel open={open}/>
      </div>
    </div>
  )
}

// ---- the page ------------------------------------------------------------------------------------------------------
export default function LandingPage({ onEnter, onOpenAddress, darkMode, setDarkMode }) {
  const open = onOpenAddress
  return (
    <div className="site lp relative w-full min-h-screen overflow-x-hidden overflow-y-auto touch-scroll">
      <header className="lp-header">
        <div className="site-container lp-header-inner">
          <div className="lp-brand">
            <span className="lp-brand-name">{BRAND.short}</span>
            <span className="lp-brand-sub">{BRAND.tagline}</span>
          </div>
          <nav className="lp-nav" aria-label="Main">
            <AppLink to={ADDR.forecast} open={open}>Forecasts</AppLink>
            <AppLink to={ADDR.tracker} open={open}>Rainfall tracking</AppLink>
            <AppLink to={ADDR.crop} open={open}>Crop outlooks</AppLink>
            <AppLink to={ADDR.about} open={open}>About</AppLink>
          </nav>
          <div className="lp-header-actions">
            <AppLink to={ADDR.forecast} open={open} className="site-btn site-btn-primary lp-btn-sm">Explore forecasts</AppLink>
            <button type="button" className="lp-icon-btn" onClick={() => setDarkMode(d => !d)}
                    aria-label={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}>
              {darkMode ? <Sun size={18} aria-hidden="true"/> : <Moon size={18} aria-hidden="true"/>}
            </button>
          </div>
        </div>
      </header>

      <main>
        <section className="lp-hero" aria-labelledby="lp-hero-title">
          <div className="site-container lp-hero-grid">
            <div className="lp-hero-text">
              <p className="site-eyebrow">Kenya &amp; Ethiopia &middot; months to days</p>
              <h1 id="lp-hero-title">Climate insight for the season ahead.</h1>
              <p className="lp-lede">
                Explore rainfall forecasts from months to days, follow recent conditions, and examine seasonal timing and experimental
                crop outlooks for Kenya and Ethiopia.
              </p>
              <div className="lp-actions">
                <AppLink to={ADDR.forecast} open={open} className="site-btn site-btn-primary">
                  Explore forecasts <ArrowRight size={18} aria-hidden="true"/>
                </AppLink>
                <button type="button" className="site-btn site-btn-secondary"
                        onClick={() => onEnter('about', { section: 'data', anchor: 'about-seasons' })}>
                  View coverage
                </button>
              </div>
              <p className="lp-note">
                Read forecasts alongside observations, local conditions, and the evidence of forecast skill.{' '}
                <AppLink to={ADDR.about} open={open} className="lp-inline">How it works</AppLink>
              </p>
              <p className="lp-attribution">
                Produced by ILRI Climate Services, in collaboration with ICPAC, EMI and KMD.
              </p>
            </div>
            <PreviewCard open={open}/>
          </div>
        </section>

        <section className="lp-section site-container" aria-labelledby="lp-tasks">
          <h2 id="lp-tasks">Where to start</h2>
          <ul className="lp-tasks">
            <li className="lp-task">
              <span className="lp-task-icon"><CalendarRange size={20} aria-hidden="true"/></span>
              <h3><AppLink to={ADDR.forecast} open={open} className="lp-task-link">Explore forecasts</AppLink></h3>
              <p>Examine when rains may start and end, possible season length, and forecast uncertainty.</p>
              <p className="lp-task-label">Kenya and Ethiopia, every season</p>
              <ul className="lp-sublinks" aria-label="More forecast views">
                <li><AppLink to={ADDR.probabilistic} open={open}>Probabilities</AppLink></li>
                <li><AppLink to={ADDR.multimodel} open={open}>Compare models</AppLink></li>
                <li><AppLink to={ADDR.historical} open={open}>Historical rainfall</AppLink></li>
                <li><AppLink to={ADDR.validation} open={open}>Forecast performance</AppLink></li>
              </ul>
            </li>
            <li className="lp-task">
              <span className="lp-task-icon"><CloudRain size={20} aria-hidden="true"/></span>
              <h3><AppLink to={ADDR.tracker} open={open} className="lp-task-link">Track rainfall</AppLink></h3>
              <p>Follow satellite rainfall estimates and updated weather outlooks at monitored sites.</p>
              <p className="lp-task-label">Kenya Short Rains</p>
            </li>
            <li className="lp-task">
              <span className="lp-task-icon"><Sprout size={20} aria-hidden="true"/></span>
              <h3><AppLink to={ADDR.crop} open={open} className="lp-task-link">Explore crop outlooks</AppLink></h3>
              <p>Examine possible crop outcomes, model differences, and management scenarios.</p>
              <p className="lp-task-label"><span className="lp-badge lp-badge-exp">Experimental</span> Monitored Kenyan sites</p>
            </li>
          </ul>
        </section>

        <section className="lp-section site-container" aria-labelledby="lp-coverage">
          <h2 id="lp-coverage">Timescales and coverage</h2>
          <ul className="lp-strip" aria-label="Forecast timescales">
            {TIMESCALES.map(t => (
              <li key={t.label}>
                <AppLink to={t.address} open={open} className="lp-strip-item">
                  <span className="lp-strip-label">{t.label}</span>
                  <span className="lp-strip-short">{t.short}</span>
                  <span className="lp-strip-cov">{t.coverage}</span>
                </AppLink>
              </li>
            ))}
          </ul>
          <dl className="lp-coverage">
            {COVERAGE.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
          </dl>
          <p className="lp-more">
            <button type="button" className="lp-inline lp-inline-btn" onClick={() => onEnter('about', { section: 'data' })}>Data and methods</button>
          </p>
        </section>

        <section className="lp-section site-container" aria-labelledby="lp-read">
          <h2 id="lp-read">How to read the outlook</h2>
          <div className="lp-read">
            <ol className="lp-principles">
              {PRINCIPLES.map(p => <li key={p}>{p}</li>)}
            </ol>
            <div>
              <h3 className="lp-read-h">Three ways to time the season</h3>
              <dl className="lp-methods">
                {METHOD_FAMILIES.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
              </dl>
              <p className="lp-more">
                <AppLink to={ADDR.validation} open={open} className="lp-inline"><ShieldCheck size={16} aria-hidden="true"/> Forecast performance</AppLink>
                <button type="button" className="lp-inline lp-inline-btn" onClick={() => onEnter('about', { section: 'methods' })}>
                  <BookOpen size={16} aria-hidden="true"/> Method details
                </button>
              </p>
            </div>
          </div>
        </section>

        <section className="lp-section site-container lp-closing" aria-labelledby="lp-closing">
          <h2 id="lp-closing">Explore the season ahead</h2>
          <div className="lp-actions">
            <AppLink to={ADDR.forecast} open={open} className="site-btn site-btn-primary">Explore forecasts <ArrowRight size={18} aria-hidden="true"/></AppLink>
            <AppLink to={ADDR.about} open={open} className="site-btn site-btn-secondary">Documentation</AppLink>
          </div>
        </section>
      </main>

      <footer className="site-footer">
        <div className="site-container site-footer-grid">
          <div>
            <h2>Produced by</h2>
            <p>ILRI Climate Services, in collaboration with ICPAC, the Ethiopian Meteorological Institute (EMI) and the Kenya Meteorological Department (KMD).</p>
          </div>
          <div>
            <h2>Contact</h2>
            <p>Dr. Teferi Demissie, project lead: <a href="mailto:t.demissie@cgiar.org">t.demissie@cgiar.org</a></p>
            <p>Yonas Mersha, technical lead: <a href="mailto:y.mersha@cgiar.org">y.mersha@cgiar.org</a></p>
          </div>
          <div>
            <h2>How to cite</h2>
            <p>Demissie, T., Mersha, Y., et al. (2026). {BRAND.full} (v{version}). ILRI / ICPAC.</p>
            <p className="site-footer-version">{BRAND.short} v{version}</p>
          </div>
        </div>
      </footer>
    </div>
  )
}
