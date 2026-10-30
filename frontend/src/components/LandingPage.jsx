import {
  CalendarRange, Percent, Layers, ShieldCheck, History as HistoryIcon, Satellite,
  ArrowRight, Sun, Moon, BookOpen
} from 'lucide-react'
import { version } from '../../package.json'

const FEATURES = [
  { id: 'forecast', icon: CalendarRange, title: 'Seasonal timing',
    desc: 'When the rains may start and end, and how long the season may last, for the method you choose.' },
  { id: 'probabilistic', icon: Percent, title: 'Forecast probabilities',
    desc: 'The chance of an early, normal or late onset, and of a short or long season.' },
  { id: 'multimodel', icon: Layers, title: 'Compare models',
    desc: 'Long Rains outlooks from seven C3S seasonal models, combined according to their past skill.' },
  { id: 'validation', icon: ShieldCheck, title: 'Forecast performance',
    desc: 'How closely past forecasts matched the observed seasons, location by location.' },
  { id: 'historical', icon: HistoryIcon, title: 'Historical rainfall',
    desc: 'Observed onset, cessation and season length in past years, with the long-term trend.' },
  { id: 'tracker', icon: Satellite, title: 'Short Rains Tracker',
    desc: 'Satellite rainfall, near real-time conditions and 10–15 day weather forecasts at monitored sites, updated every day.' },
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

// Facts strip: each card opens the dashboard tab, or the About section, that explains it
const FACTS = [
  { value: '7', label: 'C3S seasonal models', cta: 'About the models', tab: 'about', at: { section: 'data', anchor: 'about-models' },
    items: ['ECMWF SEAS5', 'UKMO GloSea6', 'Meteo-France Sys8', 'DWD GCFS2.1', 'CMCC-SPS4', 'NCEP CFSv2', 'ECCC CanSIPS'] },
  { value: '5', label: 'Methods', cta: 'How they work', tab: 'about', at: { section: 'methods' },
    items: ['Dunning', 'Agri rule 1', 'Agri rule 2', 'Agri rule 3', 'FAO water balance'] },
  { value: '5', label: 'Seasons', cta: 'Seasons covered', tab: 'about', at: { section: 'data', anchor: 'about-seasons' },
    items: ['Ethiopia: JJAS, FMAM, ONDJ', 'Kenya: MAM, OND'] },
  { value: '2', label: 'Countries: Kenya and Ethiopia', cta: 'Open the maps', tab: 'forecast' },
  { value: '10–15 days', label: 'Satellite & medium-range rainfall forecasts', cta: 'Open the tracker', tab: 'tracker' },
]

export default function LandingPage({ onEnter, darkMode, setDarkMode, health }) {
  const online = health?.status === 'ok' ? health.models_loaded : null

  return (
    <div className="site relative w-full min-h-screen overflow-x-hidden overflow-y-auto touch-scroll">
      <header className="site-container site-topbar">
        <div className="site-brand">
          <span className="site-brand-name">Seasonal Climate Forecast Dashboard</span>
          <span className="site-brand-sub">ILRI Climate Services, in collaboration with ICPAC</span>
        </div>
        <div className="site-topbar-actions">
          {online != null && (
            <span className="site-status" title="Forecast configurations the server has loaded: models, seasons, start dates and methods">
              <span className="site-status-dot" aria-hidden="true" />{online} forecast configurations online
            </span>
          )}
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
          <div className="site-facts">
            {FACTS.map(f => (
              <button key={f.label} type="button" className="site-fact" onClick={() => onEnter(f.tab, f.at)}>
                <span className="site-fact-value">{f.value}</span>
                <span className="site-fact-label">{f.label}</span>
                {f.items && <ul className="site-fact-list">{f.items.map(i => <li key={i}>{i}</li>)}</ul>}
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
        </section>
      </main>

      <footer className="site-footer">
        <div className="site-container site-footer-inner">
          <span>Kenya &amp; Ethiopia · 0.25° analysis grid</span>
          <span>Project lead: Dr. Teferi Demissie (ILRI) · Technical lead: Yonas Mersha (ILRI)</span>
          <span>Seasonal Climate Forecast Dashboard v{version}</span>
        </div>
      </footer>
    </div>
  )
}
