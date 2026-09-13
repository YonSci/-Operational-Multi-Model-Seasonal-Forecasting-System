import {
  CloudRain, Percent, Layers, CheckCircle2, History as HistoryIcon,
  ArrowRight, Sun, Moon, Sprout, MapPin, BookOpen
} from 'lucide-react'

const FEATURES = [
  { id:'forecast',      icon: CloudRain,    title:'Forecasting',
    desc:'Deterministic onset, cessation and LGP outlooks per model, with A(D) accumulated-anomaly plume diagnostics.' },
  { id:'probabilistic', icon: Percent,      title:'Probabilistic',
    desc:'Tercile probabilities (below / near / above normal) and failure risk drawn from the full ensemble spread.' },
  { id:'multimodel',    icon: Layers,       title:'Multi-Model',
    desc:'Skill-weighted ensemble blending 8 C3S seasonal models by hit-rate or RPSS.' },
  { id:'validation',    icon: CheckCircle2, title:'Validation',
    desc:'Hindcast hit-rate and RPSS skill scores benchmarked against 36 years of CHIRPS observations.' },
  { id:'historical',    icon: HistoryIcon,  title:'Historical',
    desc:'Observed CHIRPS onset, cessation and season-length time series with long-term trend.' },
]

const STATS = [
  { label:'Seasonal Models',     value:'8' },
  { label:'Countries',           value:'2' },
  { label:'Calibration Years',   value:'36' },
  { label:'Grid Resolution',     value:'0.25 deg' },
]

export default function LandingPage({ onEnter, darkMode, setDarkMode, health }) {
  const modelsLive = health?.status === 'ok' ? health.models_loaded : null

  return (
    <div style={{position:'relative', minHeight:'100vh', overflow:'auto', background:'var(--bg-base)', color:'var(--text-primary)', fontFamily:"'IBM Plex Mono','Fira Code',monospace"}}>

      {/* Ambient background accents */}
      <div aria-hidden="true" style={{position:'fixed', inset:0, overflow:'hidden', pointerEvents:'none', zIndex:0}}>
        <div style={{position:'absolute', top:'-12%', left:'-8%', width:520, height:520, borderRadius:'50%',
                     background:'var(--accent-blue)', opacity:0.14, filter:'blur(120px)'}}/>
        <div style={{position:'absolute', bottom:'-16%', right:'-10%', width:600, height:600, borderRadius:'50%',
                     background:'var(--accent-blue-dk)', opacity:0.16, filter:'blur(140px)'}}/>
        <div style={{position:'absolute', inset:0,
                     backgroundImage:'linear-gradient(var(--border-primary) 1px, transparent 1px), linear-gradient(90deg, var(--border-primary) 1px, transparent 1px)',
                     backgroundSize:'42px 42px', opacity:0.35}}/>
      </div>

      <div style={{position:'relative', zIndex:1, display:'flex', flexDirection:'column', minHeight:'100vh'}}>

        {/* Top bar */}
        <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', padding:'20px 32px'}}>
          <div style={{display:'flex', flexDirection:'column', lineHeight:1}}>
            <span style={{fontSize:11, fontWeight:900, letterSpacing:'0.2em', textTransform:'uppercase', color:'var(--accent-blue)'}}>ILRI Climate Services</span>
            <span style={{fontSize:9, letterSpacing:'0.1em', marginTop:3, color:'var(--header-muted)'}}>in collaboration with ICPAC</span>
          </div>
          <div style={{display:'flex', alignItems:'center', gap:10}}>
            {modelsLive!=null&&(
              <div style={{display:'flex', alignItems:'center', gap:6, fontSize:10, color:'var(--header-muted)'}}>
                <span style={{width:6, height:6, borderRadius:'50%', background:'#34d399'}}/>
                {modelsLive} models live
              </div>
            )}
            <button onClick={()=>setDarkMode(d=>!d)}
              style={{display:'flex', alignItems:'center', gap:6, padding:'6px 10px', borderRadius:8, fontSize:10, fontWeight:600, cursor:'pointer',
                      background:'var(--bg-elevated)', border:'1px solid var(--border-primary)', color:'var(--accent-blue)'}}>
              {darkMode?<Sun size={12}/>:<Moon size={12}/>}
              {darkMode?'Light mode':'Dark mode'}
            </button>
          </div>
        </div>

        {/* Hero */}
        <div style={{flex:1, display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', textAlign:'center', padding:'40px 20px'}}>
          <div style={{display:'flex', alignItems:'center', gap:8, padding:'6px 14px', borderRadius:999, marginBottom:22,
                       background:'var(--bg-elevated)', border:'1px solid var(--border-primary)', fontSize:10, letterSpacing:'0.1em', textTransform:'uppercase', color:'var(--text-muted)'}}>
            <Sprout size={13} color="var(--accent-blue)"/>
            Kenya &amp; Ethiopia  |  Seasonal Forecasting
          </div>

          <h1 style={{fontSize:'clamp(28px, 5vw, 52px)', fontWeight:800, letterSpacing:'-0.02em', margin:0, maxWidth:820, lineHeight:1.15}}>
            Onset, Cessation &amp; Season-Length<br/>
            <span style={{color:'var(--accent-blue)'}}>Seasonal Forecast System</span>
          </h1>

          <p style={{fontSize:14, color:'var(--text-secondary)', maxWidth:620, marginTop:20, lineHeight:1.7}}>
            Operational probabilistic seasonal forecasting for Kenya and Ethiopia -- an 8-model C3S ensemble, calibrated
            against 36 years of CHIRPS observations, delivering onset, cessation and length-of-growing-period outlooks
            pixel by pixel.
          </p>

          <div style={{display:'flex', gap:12, marginTop:32, flexWrap:'wrap', justifyContent:'center'}}>
            <button onClick={()=>onEnter('forecast')}
              style={{display:'flex', alignItems:'center', gap:8, padding:'12px 22px', borderRadius:10, fontSize:12, fontWeight:700,
                      letterSpacing:'0.04em', textTransform:'uppercase', cursor:'pointer', border:'none',
                      background:'var(--accent-blue)', color:'#fff'}}>
              Enter Dashboard <ArrowRight size={14}/>
            </button>
            <button onClick={()=>onEnter('about')}
              style={{display:'flex', alignItems:'center', gap:8, padding:'12px 22px', borderRadius:10, fontSize:12, fontWeight:700,
                      letterSpacing:'0.04em', textTransform:'uppercase', cursor:'pointer',
                      background:'transparent', border:'1px solid var(--border-primary)', color:'var(--text-secondary)'}}>
              <BookOpen size={14}/> Methodology
            </button>
          </div>

          {/* Stats */}
          <div style={{display:'flex', gap:14, marginTop:48, flexWrap:'wrap', justifyContent:'center'}}>
            {STATS.map(s=>(
              <div key={s.label} style={{minWidth:130, padding:'14px 18px', borderRadius:10,
                                          background:'var(--bg-surface)', border:'1px solid var(--border-primary)'}}>
                <div style={{fontSize:22, fontWeight:800, color:'var(--accent-blue)'}}>{s.value}</div>
                <div style={{fontSize:9, textTransform:'uppercase', letterSpacing:'0.1em', color:'var(--text-muted)', marginTop:4}}>{s.label}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Feature grid */}
        <div style={{padding:'10px 32px 48px', maxWidth:1180, margin:'0 auto', width:'100%'}}>
          <div style={{fontSize:10, fontWeight:700, letterSpacing:'0.14em', textTransform:'uppercase', color:'var(--text-muted)',
                       textAlign:'center', marginBottom:20}}>
            Five Dashboards, One Ensemble
          </div>
          <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(210px, 1fr))', gap:14}}>
            {FEATURES.map(f=>{
              const Icon = f.icon
              return (
                <button key={f.id} onClick={()=>onEnter(f.id)}
                  style={{textAlign:'left', cursor:'pointer', padding:'18px', borderRadius:12,
                          background:'var(--bg-surface)', border:'1px solid var(--border-primary)', color:'inherit',
                          display:'flex', flexDirection:'column', gap:10, transition:'border-color 0.15s'}}
                  onMouseEnter={e=>{e.currentTarget.style.borderColor='var(--accent-blue)'}}
                  onMouseLeave={e=>{e.currentTarget.style.borderColor='var(--border-primary)'}}>
                  <div style={{width:32, height:32, borderRadius:8, display:'flex', alignItems:'center', justifyContent:'center',
                               background:'var(--bg-elevated)'}}>
                    <Icon size={16} color="var(--accent-blue)"/>
                  </div>
                  <div style={{fontSize:12, fontWeight:700, color:'var(--text-primary)'}}>{f.title}</div>
                  <div style={{fontSize:10, color:'var(--text-secondary)', lineHeight:1.6}}>{f.desc}</div>
                </button>
              )
            })}
          </div>
        </div>

        {/* Footer */}
        <div style={{borderTop:'1px solid var(--border-primary)', padding:'18px 32px', display:'flex', flexWrap:'wrap',
                     alignItems:'center', justifyContent:'space-between', gap:10, fontSize:9, color:'var(--text-faint)'}}>
          <div style={{display:'flex', alignItems:'center', gap:6}}>
            <MapPin size={11}/> Kenya &amp; Ethiopia -- 0.25 deg CHIRPS-native grid
          </div>
          <div>
            Project Lead: Dr. Teferi Demissie (ILRI)  |  Technical Lead: Yonas Mersha (ILRI)
          </div>
          <div>Seasonal Forecast System  v3.0.0</div>
        </div>
      </div>
    </div>
  )
}
