import {
  CloudRain, Percent, Layers, CheckCircle2, History as HistoryIcon,
  ArrowRight, Sun, Moon, Sprout, MapPin, BookOpen, Satellite
} from 'lucide-react'

const FEATURES = [
  {
    id: 'forecast', icon: CloudRain, title: 'Forecasting',
    desc: 'Onset, cessation and season-length outlooks for the chosen method: rainfall plume, the A(D) plume (Dunning), the dates of every member (Agri rules, FAO) and the soil-water outlook (FAO).'
  },
  {
    id: 'probabilistic', icon: Percent, title: 'Probabilistic',
    desc: 'Tercile probabilities (below / near / above normal) and failure risk drawn from the full ensemble spread.'
  },
  {
    id: 'multimodel', icon: Layers, title: 'Multi-Model',
    desc: 'Skill-weighted ensemble blending 8 C3S seasonal models by hit-rate or RPSS.'
  },
  {
    id: 'validation', icon: CheckCircle2, title: 'Validation',
    desc: 'Hindcast hit-rate and RPSS skill scores benchmarked against 36 years of CHIRPS observations.'
  },
  {
    id: 'historical', icon: HistoryIcon, title: 'Historical',
    desc: 'Observed CHIRPS onset, cessation and season-length time series with long-term trend.'
  },
  {
    id: 'tracker', icon: Satellite, title: 'Short Rains Tracker',
    desc: 'Satellite rainfall day by day, 10-16 day forecasts from six weather models and the season outlook at the monitored sites, updated daily.'
  },
]

// Onset / cessation methods offered for the Kenya Short Rains (Method selector in the dashboard)
const METHODS = [
  { name: 'Dunning', tag: 'Cumulative anomaly',
    rule: 'Onset and cessation are the turning points of the accumulated rainfall anomaly, A(D), over 1 Sep - 31 Dec (Dunning et al. 2016).',
    data: 'CHIRPS v2 · ECMWF SEAS5', chart: 'C(d) / A(D) plume' },
  { name: 'Agri rule 1', tag: 'Agricultural (ICPAC)',
    rule: 'Onset: a wet day starting more than 20 mm in 3 days, with no 7-day dry spell in the next 21. Cessation: after a 10-day rain deficit (< 0.5 PET), the day a 100 mm soil store runs dry.',
    data: 'CHIRPS v2 · SEAS5 · Hargreaves PET', chart: 'Member onset and cessation dates' },
  { name: 'Agri rule 2', tag: 'Agricultural (ICPAC)',
    rule: 'Onset: at least 20 mm in 5 days with 3 or more rainy days, no dry spell longer than 7 days in the next 21. Cessation as rule 1.',
    data: 'CHIRPS v2 · SEAS5 · Hargreaves PET', chart: 'Member onset and cessation dates' },
  { name: 'Agri rule 3', tag: 'Agricultural (ICPAC)',
    rule: 'Onset: more than 20 mm in 3 days, no dry spell longer than 10 days in the next 30. Cessation: the first 10-day period with rain below half the PET.',
    data: 'CHIRPS v2 · SEAS5 · Hargreaves PET', chart: 'Member onset and cessation dates' },
  { name: 'FAO water balance', tag: 'Soil water and crop need · new',
    rule: 'Agricultural onset when rain meets half the atmospheric demand (FAO-56 ET0) and plant-available water holds at 20% or more of the root zone; agricultural cessation when soil water, crop water use and rain all fall short. Rainfall and crop-water definitions alongside, each with its own season length.',
    data: 'CHIRPS v3 · ERA5-Land · SoilGrids · SEAS5', chart: 'Member dates · soil-water outlook · timing chances' },
]

const STATS = [
  { label: 'Seasonal Models', value: '8' },
  { label: 'Onset Methods', value: '5' },
  { label: 'Countries', value: '2' },
  { label: 'Calibration Years', value: '36' },
  { label: 'Grid Resolution', value: '0.25 deg' },
]

export default function LandingPage({ onEnter, darkMode, setDarkMode, health }) {
  const modelsLive = health?.status === 'ok' ? health.models_loaded : null

  return (
    <div className="relative w-full min-h-screen overflow-x-hidden overflow-y-auto touch-scroll"
         style={{ background: 'var(--bg-base)', color: 'var(--text-primary)', fontFamily: "'IBM Plex Mono','Fira Code',monospace" }}>

      {/* Ambient background accents */}
      <div aria-hidden="true" style={{ position: 'fixed', inset: 0, overflow: 'hidden', pointerEvents: 'none', zIndex: 0 }}>
        <div style={{
          position: 'absolute', top: '-12%', left: '-8%', width: 520, height: 520, borderRadius: '50%',
          background: 'var(--accent-blue)', opacity: 0.14, filter: 'blur(120px)'
        }} />
        <div style={{
          position: 'absolute', bottom: '-16%', right: '-10%', width: 600, height: 600, borderRadius: '50%',
          background: 'var(--accent-blue-dk)', opacity: 0.16, filter: 'blur(140px)'
        }} />
        <div style={{
          position: 'absolute', inset: 0,
          backgroundImage: 'linear-gradient(var(--border-primary) 1px, transparent 1px), linear-gradient(90deg, var(--border-primary) 1px, transparent 1px)',
          backgroundSize: '42px 42px', opacity: 0.35
        }} />
      </div>

      <div style={{ position: 'relative', zIndex: 1, display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>

        {/* Top bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-8 sm:py-5">
          <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1 }}>
            <span style={{ fontSize: 11, fontWeight: 900, letterSpacing: '0.2em', textTransform: 'uppercase', color: 'var(--accent-blue)' }}>ILRI Climate Services</span>
            <span style={{ fontSize: 9, letterSpacing: '0.1em', marginTop: 3, color: 'var(--header-muted)' }}>in collaboration with ICPAC</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            {modelsLive != null && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, color: 'var(--header-muted)' }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#34d399' }} />
                {modelsLive} models live
              </div>
            )}
            <button onClick={() => setDarkMode(d => !d)}
              style={{
                display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px', borderRadius: 8, fontSize: 10, fontWeight: 600, cursor: 'pointer',
                background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', color: 'var(--accent-blue)'
              }}>
              {darkMode ? <Sun size={12} /> : <Moon size={12} />}
              {darkMode ? 'Light mode' : 'Dark mode'}
            </button>
          </div>
        </div>

        {/* Hero */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center', padding: '30px 16px sm:40px 20px' }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8, padding: '6px 14px', borderRadius: 999, marginBottom: 22,
            background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-muted)'
          }}>
            <Sprout size={13} color="var(--accent-blue)" />
            Kenya &amp; Ethiopia  |  Seasonal Climate Forecasting
          </div>

          <h1 style={{ fontSize: 'clamp(24px, 5vw, 50px)', fontWeight: 800, letterSpacing: '-0.02em', margin: 0, maxWidth: 880, lineHeight: 1.18 }}>
            Onset, Cessation &amp; Season-Length<br />
            <span style={{ color: 'var(--accent-blue)' }}>Seasonal Climate Forecast Dashboard</span>
          </h1>

          <p style={{ fontSize: 13, color: 'var(--text-secondary)', maxWidth: 660, marginTop: 18, lineHeight: 1.7, padding: '0 8px' }}>
            Operational seasonal climate forecasting for Kenya and Ethiopia -- multi-model C3S ensemble and single-model operational runs, calibrated against CHIRPS observations to deliver onset, cessation, and season-length outlooks. For the Kenya Short Rains, five onset methods: Dunning, Agri rules 1-3 and the FAO water balance.
          </p>

          <div style={{ display: 'flex', gap: 12, marginTop: 28, flexWrap: 'wrap', justifyContent: 'center', width: '100%', maxWidth: 440 }}>
            <button onClick={() => onEnter('forecast')}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '12px 22px', borderRadius: 10, fontSize: 12, fontWeight: 700,
                letterSpacing: '0.04em', textTransform: 'uppercase', cursor: 'pointer', border: 'none',
                background: 'var(--accent-blue)', color: '#fff', flex: '1 1 180px'
              }}>
              Enter Dashboard <ArrowRight size={14} />
            </button>
            <button onClick={() => onEnter('about')}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '12px 22px', borderRadius: 10, fontSize: 12, fontWeight: 700,
                letterSpacing: '0.04em', textTransform: 'uppercase', cursor: 'pointer',
                background: 'transparent', border: '1px solid var(--border-primary)', color: 'var(--text-secondary)', flex: '1 1 180px'
              }}>
              <BookOpen size={14} /> Methodology
            </button>
          </div>

          {/* Stats */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 10, marginTop: 36, width: '100%', maxWidth: 640 }}>
            {STATS.map(s => (
              <div key={s.label} style={{
                padding: '12px 14px', borderRadius: 10,
                background: 'var(--bg-surface)', border: '1px solid var(--border-primary)'
              }}>
                <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--accent-blue)' }}>{s.value}</div>
                <div style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', marginTop: 4 }}>{s.label}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Feature grid - Five Dashboards text removed */}
        <div style={{ padding: '8px 16px 40px', maxWidth: 1180, margin: '0 auto', width: '100%' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
            {FEATURES.map(f => {
              const Icon = f.icon
              return (
                <button key={f.id} onClick={() => onEnter(f.id)}
                  style={{
                    textAlign: 'left', cursor: 'pointer', padding: '16px', borderRadius: 12,
                    background: 'var(--bg-surface)', border: '1px solid var(--border-primary)', color: 'inherit',
                    display: 'flex', flexDirection: 'column', gap: 10, transition: 'all 0.15s'
                  }}
                  onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent-blue)' }}
                  onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border-primary)' }}>
                  <div style={{
                    width: 32, height: 32, borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center',
                    background: 'var(--bg-elevated)'
                  }}>
                    <Icon size={16} color="var(--accent-blue)" />
                  </div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>{f.title}</div>
                  <div style={{ fontSize: 10, color: 'var(--text-secondary)', lineHeight: 1.6 }}>{f.desc}</div>
                </button>
              )
            })}
          </div>
        </div>

        {/* Onset and cessation methods */}
        <div style={{ padding: '8px 16px 40px', maxWidth: 1180, margin: '0 auto', width: '100%' }}>
          <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>
            Onset and cessation methods (Kenya Short Rains)
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginBottom: 12, lineHeight: 1.6 }}>
            Pick one with the Method selector in the dashboard; maps, probabilities, skill, charts and the bulletin follow it. Agri rules 1-3 are adapted from the ICPAC operational definitions.
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 12 }}>
            {METHODS.map(mt => (
              <div key={mt.name} style={{
                padding: '14px 16px', borderRadius: 12, background: 'var(--bg-surface)', border: '1px solid var(--border-primary)',
                display: 'flex', flexDirection: 'column', gap: 8
              }}>
                <div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>{mt.name}</div>
                  <div style={{ fontSize: 9, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--accent-blue)', marginTop: 3 }}>{mt.tag}</div>
                </div>
                <div style={{ fontSize: 10, color: 'var(--text-secondary)', lineHeight: 1.6, flex: 1 }}>{mt.rule}</div>
                <div style={{ fontSize: 9, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                  <div><b>Data:</b> {mt.data}</div>
                  <div><b>Chart:</b> {mt.chart}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3 text-center sm:text-left px-4 py-3 sm:px-8 sm:py-4"
          style={{
            borderTop: '1px solid var(--border-primary)', fontSize: 9, color: 'var(--text-faint)'
          }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <MapPin size={11} /> Kenya &amp; Ethiopia -- 0.25 deg CHIRPS-native grid
          </div>
          <div>
            Project Lead: Dr. Teferi Demissie (ILRI)  |  Technical Lead: Yonas Mersha (ILRI)
          </div>
          <div>Seasonal Climate Forecast Dashboard  v3.0.0</div>
        </div>
      </div>
    </div>
  )
}
