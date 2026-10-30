import React, { Fragment, useEffect, useState } from 'react'
import { Info, Database, CalendarRange, Map as MapIcon, ShieldCheck, FileCode2 } from 'lucide-react'
import { version } from '../../package.json'

// Seasonal forecast systems combined for the Kenya Long Rains (About > Data & coverage)
const C3S_MODEL_INFO = [
  { name: 'ECMWF SEAS5', desc: 'The 5th generation seasonal forecasting system from the European Centre for Medium-Range Weather Forecasts. It features high horizontal atmospheric resolution (~36 km) coupled with the NEMO ocean model. It is widely considered the global benchmark for operational seasonal prediction and serves as a core component of the Copernicus Climate Change Service (C3S) multi-model ensemble.' },
  { name: 'Met Office UKMO GloSea6', desc: 'The UK Met Office’s Global Seasonal prediction system version 6. Built on the HadGEM3-GC3.1 coupled physical model, it is recognized for its high-resolution ocean component and strong representation of stratospheric dynamics, which significantly improves the forecasting of wintertime phenomena like the North Atlantic Oscillation (NAO).' },
  { name: 'Meteo-France Sys8', desc: 'Meteo-France’s 8th generation seasonal forecasting system. Relying on the CNRM-CM6-1 coupled global climate model, System 8 features updated initialization techniques and improved physics, leading to better representations of tropical convection, the El Niño-Southern Oscillation (ENSO), and ocean-atmosphere coupling.' },
  { name: 'DWD GCFS2.1', desc: 'The German Climate Forecast System version 2.1 by Deutscher Wetterdienst. It is based on the high-resolution Max Planck Institute Earth System Model (MPI-ESM-HR). It utilizes an advanced assimilation scheme for ocean and sea ice initialization, providing robust global seasonal outlooks with a strong focus on European climate variability.' },
  { name: 'CMCC CMCC-SPS4', desc: 'The Centro Euro-Mediterraneo sui Cambiamenti Climatici Seasonal Prediction System 4 (Italy). This coupled system utilizes the Community Earth System Model (CESM) framework with specific CMCC modifications. It features high-resolution ocean and atmospheric components optimized to capture both mid-latitude teleconnections and tropical climate variability.' },
  { name: 'NCEP CFSv2', desc: 'The Climate Forecast System version 2 from the US National Centers for Environmental Prediction. Operational since 2011, it is a fully coupled ocean-land-atmosphere dynamical prediction system. While relying on an older architecture than some European counterparts, it is highly reliable, heavily used in operational meteorology globally, and serves as a foundational model for the North American Multi-Model Ensemble (NMME).' },
  { name: 'ECCC CanSIPS', desc: 'The Canadian Seasonal to Interannual Prediction System by Environment and Climate Change Canada. It operates as an internal multi-model ensemble system by combining forecasts from two distinct coupled global climate models (GEM-NEMO and CanCM4i). It provides comprehensive probabilistic seasonal forecasts and is a major contributor to the NMME.' },
]
// Short Rains Tracker inputs (see public/tracker/data/products.csv for the live latency of each)
const SATELLITE_INFO = [
  { name: 'CHIRPS 2.0', meta: 'UC Santa Barbara Climate Hazards Center · 0.05°, used at 0.25° · preliminary ~2–5 days, final ~3 weeks after the month',
    desc: 'Satellite infrared rainfall blended with rain-gauge reports, 1981 to present. CHIRPS is the reference for the whole platform: climatology, bias correction and verification all use it. Preliminary daily files fill the days after the last complete month.' },
  { name: 'ARC2', meta: 'NOAA Climate Prediction Center (FEWS NET) · 0.1° · ~1–2 days',
    desc: 'Africa Rainfall Climatology version 2: Meteosat infrared cloud-top temperatures merged with daily rain-gauge reports. Quick and with a long record; tends to miss light rain.' },
  { name: 'TAMSAT v3.1', meta: 'University of Reading · 0.0375° · ~2–5 days',
    desc: 'Africa-only rainfall from Meteosat thermal-infrared cold-cloud duration, calibrated against historical gauges. Good at telling rain from no rain; weaker for heavy amounts.' },
  { name: 'PDIR-Now', meta: 'UC Irvine Center for Hydrometeorology and Remote Sensing · 0.04° · ~1 day',
    desc: 'Rainfall estimated from infrared imagery by a neural network (PERSIANN family), near-global and quasi-real-time. The fastest product here; it has no gauge correction.' },
  { name: 'IMERG Late and Early (V07)', meta: 'NASA Global Precipitation Measurement (GPM) · 0.1° · Early ~1 day, Late ~1–2 days',
    desc: 'Passive-microwave rainfall from the GPM satellite constellation, with gaps filled from infrared. The Late run includes more microwave overpasses; the Early run is issued sooner for monitoring when speed matters.' },
]
const NWP_INFO = [
  { name: 'ECMWF IFS (HRES)', meta: 'ECMWF · 0.25° · 15 days', desc: 'The European Centre’s deterministic global forecast, from its open data.' },
  { name: 'ECMWF ensemble (ENS)', meta: 'ECMWF · 0.25° · 15 days', desc: 'A 51-member ensemble. The maps show the member median; the chances of planting rains use the 50 perturbed members.' },
  { name: 'GFS', meta: 'NOAA National Centers for Environmental Prediction · 0.25° · 16 days', desc: 'The US Global Forecast System.' },
  { name: 'GDPS (GEM)', meta: 'Environment and Climate Change Canada · 15 km · 10 days', desc: 'Canada’s Global Deterministic Prediction System, run with the GEM model.' },
  { name: 'ICON', meta: 'Deutscher Wetterdienst (DWD) · 13 km · 7.5 days', desc: 'Germany’s ICOsahedral Nonhydrostatic global model, from the DWD open-data server.' },
  { name: 'UKMO Global', meta: 'Met Office · 10 km · 7 days', desc: 'The Met Office Unified Model global deterministic forecast, from AWS open data.' },
]

export default function AboutTab({ initial, section: sectionProp, onSectionChange }) {
  const [section, setSection] = useState(sectionProp ?? initial?.section ?? 'overview')
  const scrollRef = React.useRef(null)
  useEffect(() => { if (sectionProp && sectionProp !== section) setSection(sectionProp) }, [sectionProp])
  const go = id => { setSection(id); onSectionChange?.(id); scrollRef.current?.scrollTo({ top: 0 }) }
  // Opened from a landing-page card: jump to the block it points at
  useEffect(() => { if (initial?.anchor) document.getElementById(initial.anchor)?.scrollIntoView({ block: 'start' }) }, [])

  const S = ({title,children,id})=>(<section id={id} className="about-block"><h3>{title}</h3>{children}</section>)
  const ModelList = ({items})=>(<dl className="about-models">{items.map(m => (<div key={m.name}><dt>{m.name}</dt>{m.meta && <dd className="about-models-meta">{m.meta}</dd>}<dd>{m.desc}</dd></div>))}</dl>)
  const Tbl = ({head,rows})=>(<div style={{overflowX:'auto'}}><table style={{width:'100%',borderCollapse:'collapse',fontSize:15}}><thead><tr style={{borderBottom:'2px solid var(--border-primary)'}}>{head.map(h=>(<th key={h} scope="col" style={{padding:'8px 10px',textAlign:'left',color:'var(--text-meta)',fontWeight:600,fontSize:14,whiteSpace:'nowrap'}}>{h}</th>))}</tr></thead><tbody>{rows.map((r,i)=>(<tr key={i} style={{borderBottom:'1px solid var(--border-primary)'}}>{r.map((c,j)=>(<td key={j} style={{padding:'10px',color:j===0?'var(--heading)':'var(--text-body)',fontWeight:j===0?600:400,lineHeight:1.6,verticalAlign:'top',minWidth:j===0?140:120}}>{c}</td>))}</tr>))}</tbody></table></div>)
  const KV = ({label,value,wide=false})=>(<div style={{display:'flex',flexWrap:'wrap',gap:'2px 16px',padding:'10px 0',borderBottom:'1px solid var(--border-primary)'}}><span style={{flex:`0 0 ${wide?240:200}px`,fontSize:14,fontWeight:600,color:'var(--text-meta)',lineHeight:1.6,fontFamily:label.startsWith('GET ')?"'IBM Plex Mono',monospace":'inherit'}}>{label}</span><span style={{flex:'1 1 320px',minWidth:0,fontSize:16,color:'var(--text-body)',lineHeight:1.65}}>{value}</span></div>)
  const Step = ({n,title,eq,desc,table})=>(
    <div style={{display:'flex',gap:14,marginBottom:24,alignItems:'flex-start'}}>
      <div style={{flexShrink:0,width:30,height:30,borderRadius:'50%',display:'flex',alignItems:'center',justifyContent:'center',fontSize:14,fontWeight:700,background:'var(--btn-primary)',color:'#fff',marginTop:1}}>{n}</div>
      <div style={{flex:1,minWidth:0}}>
        <h4 style={{fontSize:18,fontWeight:600,color:'var(--heading)',margin:'0 0 6px',lineHeight:1.4}}>{title}</h4>
        {eq&&<div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:15,color:'var(--heading)',background:'var(--bg-elevated)',border:'1px solid var(--border-primary)',borderRadius:8,padding:'10px 14px',marginBottom:8,overflowX:'auto',whiteSpace:'pre'}}>{eq}</div>}
        {desc&&<p style={{fontSize:16,color:'var(--text-body)',lineHeight:1.7,margin:table?'0 0 8px':0}}>{desc}</p>}
        {table&&(<div style={{overflowX:'auto',marginTop:4}}><table style={{borderCollapse:'collapse',fontSize:15,width:'100%'}}><tbody>{table.map(([sym,def],i)=>(<tr key={i} style={{borderBottom:'1px solid var(--border-primary)'}}><td style={{padding:'7px 10px',fontFamily:"'IBM Plex Mono',monospace",fontSize:14,color:'var(--accent-text)',whiteSpace:'nowrap',verticalAlign:'top'}}>{sym}</td><td style={{padding:'7px 10px',color:'var(--text-body)',lineHeight:1.6}}>{def}</td></tr>))}</tbody></table></div>)}
      </div>
    </div>
  )
  const GaugeDef = ({name,thresh,derivation,justification,strength})=>(
    <div style={{marginBottom:8,padding:'8px 10px',background:'var(--bg-elevated)',borderRadius:8,border:'1px solid var(--border-primary)'}}>
      <div style={{display:'flex',flexWrap:'wrap',justifyContent:'space-between',alignItems:'flex-start',gap:'2px 12px',marginBottom:4}}>
        <span style={{fontSize:16,fontWeight:700,color:'var(--text-primary)'}}>{name}</span>
        <span style={{fontSize:14,color:'var(--accent-text)',fontFamily:"'IBM Plex Mono',monospace"}}>{thresh}</span>
      </div>
      <div style={{fontSize:14,color:'var(--text-secondary)',lineHeight:1.5,marginBottom:3}}>{justification}</div>
      <div style={{display:'flex',gap:12,fontSize:13,color:'var(--text-faint)',flexWrap:'wrap'}}>
        <span><strong style={{color:'var(--text-muted)'}}>Derivation:</strong> {derivation}</span>
        <span><strong style={{color:'var(--text-muted)'}}>Strength:</strong> {strength}</span>
      </div>
    </div>
  )

  const [expandedStations, setExpandedStations] = useState({ gambella: true })
  const [stationFilter, setStationFilter] = useState('all')
  const [stationSearch, setStationSearch] = useState('')

  const toggleStation = (id) => {
    setExpandedStations(prev => ({ ...prev, [id]: !prev[id] }))
  }

  const AUDITED_STATIONS = [
    { id: 'gambella', name: 'Gambella', req: '8.25°N, 34.58°E', grid: '8.125°N, 34.625°E', idx: '(20, 06)', pann: '1,189.1', c1: '3.39', c2: '0.11', rh: '0.03', reg: 'Regime 1: Western Unimodal', desc: 'Extended unimodal monsoon; single broad wet season', elev: '526 m', rationale: 'Single broad monsoon peak in July–August. The annual Fourier harmonic (C1=3.39) overwhelmingly dominates the negligible semi-annual cycle (C2=0.11), producing an ultra-low harmonic ratio (rH=0.03 << 1.0). Rains proceed continuously without a June cessation break.' },
    { id: 'assosa', name: 'Assosa', req: '10.07°N, 34.53°E', grid: '10.125°N, 34.625°E', idx: '(28, 06)', pann: '1,197.3', c1: '4.21', c2: '0.60', rh: '0.14', reg: 'Regime 1: Western Unimodal', desc: 'Benishangul-Gumuz unimodal summer rainfall belt', elev: '1,570 m', rationale: 'Western unimodal summer belt with monsoon peak in July–August. Very low harmonic ratio (rH=0.14) confirms absence of distinct bimodal transitions.' },
    { id: 'jimma', name: 'Jimma', req: '7.67°N, 36.83°E', grid: '7.625°N, 36.875°E', idx: '(18, 15)', pann: '1,599.2', c1: '3.62', c2: '0.37', rh: '0.10', reg: 'Regime 1: Western Unimodal', desc: 'High-rainfall coffee zone; continuous season Mar-Oct', elev: '1,780 m', rationale: 'High-rainfall southwestern agro-ecological zone. Rains begin in March and build smoothly through August without any intervening dry interval (rH=0.10).' },
    { id: 'bahir_dar', name: 'Bahir Dar', req: '11.60°N, 37.38°E', grid: '11.625°N, 37.375°E', idx: '(34, 17)', pann: '1,385.1', c1: '5.57', c2: '2.46', rh: '0.44', reg: 'Regime 1: Western Unimodal', desc: 'Lake Tana basin unimodal summer rainfall', elev: '1,820 m', rationale: 'Lake Tana basin unimodal summer rainfall. Strong unimodal summer concentration (July peak > 380 mm) keeps rH=0.44 well below the biannual threshold.' },
    { id: 'gondar', name: 'Gondar', req: '12.60°N, 37.47°E', grid: '12.625°N, 37.375°E', idx: '(38, 17)', pann: '1,198.4', c1: '4.57', c2: '1.77', rh: '0.39', reg: 'Regime 1: Western Unimodal', desc: 'Northwestern unimodal monsoon domain', elev: '2,133 m', rationale: 'Northwestern unimodal monsoon regime dominated by heavy July–August rains (peak ~300 mm). Single unimodal wet cycle with rH=0.39.' },
    { id: 'bedele', name: 'Bedele', req: '8.45°N, 36.35°E', grid: '8.375°N, 36.375°E', idx: '(21, 13)', pann: '1,810.7', c1: '5.10', c2: '0.35', rh: '0.07', reg: 'Regime 1: Western Unimodal', desc: 'Western high-rainfall core unimodal belt', elev: '2,011 m', rationale: 'Western high-rainfall core belt with annual rainfall exceeding 1,800 mm. Fourier decomposition reveals complete unimodal dominance (rH=0.07).' },
    { id: 'addis_ababa', name: 'Addis Ababa', req: '9.03°N, 38.74°E', grid: '9.125°N, 38.625°E', idx: '(24, 22)', pann: '1,180.7', c1: '4.07', c2: '2.25', rh: '0.55', reg: 'Regime 2: Bimodal Type 1', desc: 'Classic central highland: Belg early + Kiremt main', elev: '2,355 m', rationale: 'Classic central highland bimodal Type 1 regime. Clearly shows the early spring Belg secondary peak (April ~75 mm), a dry depression in June, and the intense summer Kiremt peak (July–August ~300 mm). Harmonic ratio rH=0.55 captures the dual-peak structure.' },
    { id: 'kombolcha', name: 'Kombolcha', req: '11.08°N, 39.73°E', grid: '11.125°N, 39.625°E', idx: '(32, 26)', pann: '1,150.0', c1: '3.38', c2: '2.50', rh: '0.74', reg: 'Regime 2: Bimodal Type 1', desc: 'Wollo escarpment; vital Belg early agricultural cycle', elev: '1,857 m', rationale: 'Eastern escarpment of Wollo where Belg rains are vital for early crops. Distinct April peak followed by a June break before the main Kiremt rains (rH=0.74).' },
    { id: 'mekelle', name: 'Mekelle', req: '13.50°N, 39.47°E', grid: '13.375°N, 39.375°E', idx: '(41, 25)', pann: '689.6', c1: '2.91', c2: '2.01', rh: '0.69', reg: 'Regime 2: Bimodal Type 1', desc: 'Tigray highlands; minor Belg + major Kiremt', elev: '2,254 m', rationale: 'Northern highland bimodal regime with a modest spring Belg peak and intense July–August Kiremt rains (rH=0.69).' },
    { id: 'dire_dawa', name: 'Dire Dawa', req: '9.60°N, 41.87°E', grid: '9.625°N, 41.875°E', idx: '(26, 35)', pann: '625.6', c1: '1.21', c2: '1.01', rh: '0.84', reg: 'Regime 2: Bimodal Type 1', desc: 'Eastern escarpment; spring Belg & summer Kiremt', elev: '1,260 m', rationale: 'Eastern transition escarpment. Balanced bimodal Type 1 profile with distinct April and August peaks separated by June dry conditions (rH=0.84).' },
    { id: 'jijiga', name: 'Jijiga', req: '9.35°N, 42.80°E', grid: '9.375°N, 42.875°E', idx: '(25, 39)', pann: '544.5', c1: '1.21', c2: '0.77', rh: '0.64', reg: 'Regime 2: Bimodal Type 1', desc: 'Eastern transition; Type-1 summer/spring rainfall', elev: '1,609 m', rationale: 'Eastern highland edge showing Type 1 bimodal distribution with active spring and late-summer rainfall (rH=0.64).' },
    { id: 'hawassa', name: 'Hawassa', req: '7.05°N, 38.48°E', grid: '7.125°N, 38.375°E', idx: '(16, 21)', pann: '1,050.2', c1: '1.84', c2: '0.76', rh: '0.41', reg: 'Regime 2: Bimodal Type 1', desc: 'Rift Valley; dual May/Jul peaks with June drop', elev: '1,708 m', rationale: 'Central Rift Valley station exhibiting twin rainfall peaks in May and July/August with a notable dip in June (rH=0.41).' },
    { id: 'arba_minch', name: 'Arba Minch', req: '6.03°N, 37.55°E', grid: '6.125°N, 37.625°E', idx: '(12, 18)', pann: '1,001.9', c1: '0.98', c2: '1.61', rh: '1.65', reg: 'Regime 3: Bimodal Type 2', desc: 'Gamo Gofa; bimodal with major Gu spring peak', elev: '1,285 m', rationale: 'Southern rift transition with prominent Gu spring peak (April–May) and secondary autumn peak (October), separated by a relatively dry summer (rH=1.65 > 1.0).' },
    { id: 'goba_bale', name: 'Goba / Bale', req: '7.00°N, 39.98°E', grid: '6.875°N, 39.875°E', idx: '(15, 27)', pann: '1,127.3', c1: '1.07', c2: '1.88', rh: '1.76', reg: 'Regime 3: Bimodal Type 2', desc: 'Bale zone; bimodal spring & autumn peaks', elev: '2,743 m', rationale: 'Highland Bale zone with equinoctial biannual peaks in spring (April–May) and autumn (September–October) and a marked July reduction (rH=1.76).' },
    { id: 'negelle_borana', name: 'Negelle Borana', req: '5.33°N, 39.58°E', grid: '5.375°N, 39.625°E', idx: '(09, 26)', pann: '666.5', c1: '0.88', c2: '2.59', rh: '2.94', reg: 'Regime 3: Bimodal Type 2', desc: 'Borana pastoral; Gu/Ganna (MAM) + Deyr/Hagaya (SON)', elev: '1,475 m', rationale: 'Southern Borana pastoral heartland. High harmonic ratio (rH=2.94) proves clean biannual rainfall driven by the ITCZ: Gu/Ganna (MAM) and Deyr/Hagaya (SON) with bone-dry JJA.' },
    { id: 'yabello', name: 'Yabello', req: '4.88°N, 38.09°E', grid: '4.875°N, 38.125°E', idx: '(07, 20)', pann: '643.9', c1: '0.88', c2: '2.03', rh: '2.31', reg: 'Regime 3: Bimodal Type 2', desc: 'Borana rangeland; symmetric bimodal pastoral rains', elev: '1,857 m', rationale: 'Borana rangeland with symmetric spring (April peak) and autumn (October/November peak) pastoral rains. Summer months (JJA) are virtually rainless (rH=2.31).' },
    { id: 'moyale', name: 'Moyale', req: '3.53°N, 39.05°E', grid: '3.625°N, 39.125°E', idx: '(02, 24)', pann: '628.6', c1: '0.70', c2: '2.16', rh: '3.08', reg: 'Regime 3: Bimodal Type 2', desc: 'Border equatorial biannual; dry summer (JJA)', elev: '1,113 m', rationale: 'Southern border equatorial regime with strong semi-annual harmonic dominance (rH=3.08). Dual MAM and OND wet seasons align with Kenyan equatorial dynamics.' },
    { id: 'kebri_dehar', name: 'Kebri Dehar', req: '6.73°N, 44.28°E', grid: '6.625°N, 44.375°E', idx: '(14, 45)', pann: '425.8', c1: '0.06', c2: '1.99', rh: '35.76', reg: 'Regime 3: Bimodal Type 2', desc: 'Ogaden lowlands; dry summer, Gu + Deyr pastoral', elev: '493 m', rationale: 'Somali region (Ogaden) lowlands. Extreme biannual harmonic ratio (rH=35.76) due to near-zero annual cycle and two symmetric brief wet seasons (Gu & Deyr).' },
    { id: 'gode', name: 'Gode', req: '5.95°N, 43.58°E', grid: '5.875°N, 43.625°E', idx: '(11, 42)', pann: '280.9', c1: '0.06', c2: '1.33', rh: '23.04', reg: 'Regime 3: Bimodal Type 2', desc: 'Shebelle basin; hyper-bimodal pastoral rains', elev: '290 m', rationale: 'Lower Wabi Shebelle basin pastoral domain. Extreme biannual regime (rH=23.04) with two sharp peaks in April–May and October–November and an arid summer.' },
    { id: 'semera', name: 'Semera', req: '11.79°N, 41.00°E', grid: '11.875°N, 40.875°E', idx: '(35, 31)', pann: '263.5', c1: '0.57', c2: '0.55', rh: '0.97', reg: 'Regime 0: Arid / Marginal', desc: 'Afar / Danakil; hyper-arid, no reliable rainy season', elev: '433 m', rationale: 'Afar / Danakil lowlands with low annual precipitation (P_ann = 263.5 mm). Spurious harmonic ratios due to noise; properly screened out under Regime 0.' },
  ]


  const SECTIONS = [
    { id: 'overview',    label: 'Overview',                  icon: Info },
    { id: 'data',        label: 'Data & coverage',           icon: Database },
    { id: 'methods',     label: 'Forecast methods',          icon: CalendarRange },
    { id: 'regimes',     label: 'Rainfall regimes',          icon: MapIcon },
    { id: 'performance', label: 'Performance & limitations', icon: ShieldCheck },
    { id: 'technical',   label: 'Technical documentation',   icon: FileCode2 },
  ]
  const current = SECTIONS.find(s => s.id === section) ?? SECTIONS[0]
  const Link = ({to, children}) => <button type="button" className="about-link" onClick={() => go(to)}>{children}</button>

  return (
    <div ref={scrollRef} className="site h-full overflow-y-auto touch-scroll">
     <div className="about-shell">
      <header className="about-head">
        <p className="site-eyebrow">About</p>
        <h1>About the platform</h1>
        <p className="about-lede">The Seasonal Climate Forecast Dashboard helps users explore the timing and uncertainty of rainfall seasons in Kenya and Ethiopia.</p>
      </header>
      <div className="about-layout">
       <nav className="about-nav" aria-label="About sections">
        <p className="about-nav-label">About sections</p>
        {SECTIONS.map(s => { const Icon = s.icon; return (
          <button key={s.id} type="button" aria-current={section === s.id ? 'true' : undefined} onClick={() => go(s.id)}>
            <Icon size={18} aria-hidden="true" />{s.label}
          </button>) })}
       </nav>
       <article className="about-article">
        <h2>{current.label}</h2>

      {section === 'overview' && (
        <div className="about-prose">
          <h3>What you can explore</h3>
          <p>
            The platform presents estimates of rainfall <strong>onset</strong>, <strong>cessation</strong> and <strong>season length</strong>, together with
            probabilities and the spread of outcomes across forecast members. It brings together seasonal climate-model forecasts, CHIRPS-based rainfall
            estimates and recent weather information. You can compare the available models, examine historical seasons and review forecast performance.
          </p>
          <p>The Short Rains Tracker adds recent satellite rainfall and short- to medium-range weather forecasts for monitored sites.</p>

          <h3>How seasonal timing is defined</h3>
          <p>
            Onset and cessation depend on the definition selected. A change in the rainfall pattern, a sustained wet spell and enough soil moisture for
            crop establishment can occur at different times.
          </p>
          <p>
            For Kenya’s Short Rains, the dashboard offers the Dunning cumulative-anomaly method, three agricultural rainfall rules adapted from ICPAC
            definitions, and a water-balance approach that uses FAO-56 reference evapotranspiration with soil-water and crop-demand criteria.
          </p>
          <p>
            For Ethiopia, the platform uses a rainfall-regime classification to represent regional differences in seasonal behaviour. It combines a Dunning
            harmonic baseline with refinements informed by Ethiopian rainfall climatology.
          </p>
          <p>
            The Dunning method follows a published approach (Dunning, Black and Allan, 2016). The Ethiopian regime refinements, the adaptation of the ICPAC
            rules and the water-balance criteria were developed for this platform. Thresholds, assumptions and references are under <Link to="methods">Forecast
            methods</Link>, <Link to="regimes">Rainfall regimes</Link> and <Link to="technical">Technical documentation</Link>.
          </p>

          <h3>How to interpret the results</h3>
          <p>
            A forecast date is a representative estimate within a range of possible outcomes. Read it alongside the date range, the probabilities, the
            selected method and the available evidence of forecast skill.
          </p>
          <p>
            As the season approaches, combine the seasonal outlook with recent rainfall observations, updated weather forecasts and local conditions. An onset
            estimate alone does not establish that a particular crop has enough water for planting or establishment.
          </p>

          <h3>Coverage and limitations</h3>
          <div className="about-callout" style={{margin:'0 0 20px'}}>
            <Info size={20} aria-hidden="true" />
            <div><strong>Regional coverage</strong>The four rainfall-regime categories apply to Ethiopia. Kenya’s seasonal products use their own regional definitions, including the Long Rains and Short Rains.</div>
          </div>
          <p>
            <strong>Season length</strong> is the interval between the selected onset and cessation dates. A crop-specific length of growing period also needs
            crop and water-availability assumptions; the FAO water balance makes them explicit (maize by default).
          </p>
          <p>
            Forecast skill, data availability and uncertainty vary by location, season, model and method. See <Link to="performance">Performance &amp;
            limitations</Link> and the Forecast performance tab when interpreting the results.
          </p>
        </div>
      )}

      {section === 'data' && (
        <div>
          <p className="about-intro">
            Every product is computed on the same 0.25° analysis grid (about 28 km) from daily rainfall. Observed rainfall comes from CHIRPS; forecasts are
            bias-corrected against it, so forecast and observed dates are directly comparable.
          </p>
          <S title="Countries and seasons" id="about-seasons">
            <Tbl head={['Country','Season','Forecast start','Models']} rows={[
              ['Kenya', 'Short Rains (OND)', '1 Sep; 1 Oct, also with observed rainfall to 30 Sep or to the latest day', 'ECMWF SEAS5'],
              ['Kenya', 'Long Rains (MAM)', '1 Feb', 'Seven C3S models, single and combined'],
              ['Ethiopia', 'Kiremt (JJAS), highland main rains', '1 May', 'ECMWF SEAS5'],
              ['Ethiopia', 'Belg (FMAM), highland early rains', '1 Jan', 'ECMWF SEAS5'],
              ['Ethiopia', 'Annual wet season (western unimodal)', '1 May', 'ECMWF SEAS5'],
              ['Ethiopia', 'Gu/Ganna (MAM), spring rains', '1 Jan', 'ECMWF SEAS5'],
              ['Ethiopia', 'Deyr/Hagaya (SON–OND), autumn rains', '1 Sep', 'ECMWF SEAS5'],
            ]}/>
          </S>
          <S title="Datasets">
            <Tbl head={['Dataset','Used for','Resolution','Period']} rows={[
              ['CHIRPS v2 daily rainfall', 'Observed onset, cessation and season length; terciles; bias correction of the forecasts', '0.25°', '1981 on (Long Rains), 1993 on (other seasons)'],
              ['CHIRPS v3 daily rainfall', 'FAO water balance: observations, terciles and its own bias correction', '0.05°, averaged to 0.25°', '1993 on'],
              ['ECMWF SEAS5 and C3S seasonal models', 'Seasonal forecasts and hindcasts (25 members for SEAS5)', 'Regridded to 0.25°', 'SEAS5 hindcasts from 1981 (Long Rains) or 1993; other C3S models from 1993'],
              ['ERA5-Land', 'FAO-56 reference evapotranspiration (ET0) and starting soil moisture', '0.1°, averaged to 0.25°', '1993 on'],
              ['SoilGrids 2.0', 'Soil water-holding capacity for the FAO water balance', '~1 km, averaged to 0.25°', 'Static'],
              ['Satellite rainfall and 10–15 day forecasts', 'Short Rains Tracker at monitored sites', 'Site', 'Current season'],
            ]}/>
          </S>
          <S title="Seasonal forecast models" id="about-models">
            <p className="about-intro">
              The Kenya Long Rains outlooks use seven seasonal forecast systems from the Copernicus Climate Change Service (C3S), shown singly and
              combined according to their past skill. The other seasons use ECMWF SEAS5.
            </p>
            <ModelList items={C3S_MODEL_INFO}/>
          </S>
          <S title="Satellite rainfall products" id="about-satellite">
            <p className="about-intro">
              The Short Rains Tracker shows how much rain has fallen at each monitored site since 1 September, from five satellite products downloaded
              every day and placed on the 0.25° grid. Each product is compared with CHIRPS for bias, correlation and rain detection.
            </p>
            <ModelList items={SATELLITE_INFO}/>
          </S>
          <S title="Medium-range weather forecasts" id="about-nwp">
            <p className="about-intro">
              The tracker’s outlook for the next one to two weeks comes from six global weather models, taken each day from the 00 UTC run published by
              each centre. A model that cannot be reached is filled from Open-Meteo. Forecast range is 7 to 16 days depending on the model.
            </p>
            <ModelList items={NWP_INFO}/>
          </S>
          <S title="Reference periods and updates">
            <KV label="Calibration" value="Hindcast years up to 2016: 1981–2016 for the Long Rains (36 years), 1993–2016 for the Short Rains and the Ethiopia seasons (24 years). Terciles, bias correction and probability calibration use these years."/>
            <KV label="Validation" value="Independent years after calibration; 2017–2024 for the Short Rains methods."/>
            <KV label="Observed record" value="CHIRPS 1993–2025 for the Short Rains historical view and the Ethiopia regime diagnostics; 1981 on for the Long Rains."/>
            <KV label="Reference normal" value="WMO standard normal 1991–2020, for climatological context."/>
            <KV label="Grid and land masks" value="0.25° analysis grid; 842 land cells in Kenya and 1,485 in Ethiopia. Ethiopia maps are shown only inside each season’s climatological domain."/>
            <KV label="Updates" value="The Short Rains run with the latest observations and the Short Rains Tracker are refreshed daily. Other seasons are updated when a new forecast is processed."/>
            <KV label="Developers" value="ILRI Climate Services in collaboration with ICPAC, EMI and KMD"/>
            <KV label="Version" value={`v${version}`}/>
          </S>
        </div>
      )}

      {section === 'regimes' && (
        <div className="about-callout" style={{marginBottom:32}}><Info size={20} aria-hidden="true"/><div><strong>Regional coverage</strong>The four rainfall-regime categories shown here apply to Ethiopia. Kenya’s seasonal products use their own regional definitions, including the Long Rains and Short Rains.</div></div>
      )}

      {/* SUB-TAB 1: BLUEPRINT & REGIMES */}
      {section === 'regimes' && (
        <div className="flex flex-col 2xl:flex-row gap-6">
          <div className="w-full 2xl:w-[54%] min-w-0 flex flex-col gap-4">
            <S title="Two-Stage Classification Blueprint">
              <div style={{background:'var(--bg-elevated)', padding:'10px 14px', borderRadius:8, border:'1px solid var(--border-primary)', fontSize:16, lineHeight:1.6, color:'var(--text-secondary)', marginBottom:10}}>
                <strong style={{color:'var(--accent-blue)'}}>Why strict r_H &ge; 1.0 under-detects Type-1 bimodality:</strong> Dunning et al. (2016) establish that annual regimes have <span style={{fontFamily:"'IBM Plex Mono',monospace", color:'var(--accent-text)'}}>r_H = C_2 / C_1 &lt; 1.0</span> and biannual regimes have <span style={{fontFamily:"'IBM Plex Mono',monospace", color:'var(--accent-text)'}}>r_H &ge; 1.0</span>. In the Ethiopian Highlands, Kiremt monsoon rainfall (~220–320 mm/mo) is 3 to 4 times larger than Belg early rains (~70–140 mm/mo). This massive amplitude disparity inflates the annual Fourier fundamental C_1, depressing r_H to 0.40–0.85. A strict r_H &ge; 1.0 threshold misclassifies the entire central/eastern agricultural highlands as unimodal, completely erasing the critical Belg early crop season.
              </div>

              <div style={{display:'flex', flexDirection:'column', gap:8}}>
                <div style={{padding:'8px 12px', background:'var(--bg-surface)', borderRadius:8, border:'1px solid var(--border-primary)'}}>
                  <div style={{fontSize:16, fontWeight:700, color:'var(--bad-text)', marginBottom:2}}>Stage 0: Arid / Marginal Screening</div>
                  <div style={{fontSize:14, color:'var(--text-secondary)', lineHeight:1.5}}>
                    Project-defined screening: <span style={{fontFamily:"'IBM Plex Mono',monospace", color:'var(--bad-text)'}}>P_ann &lt; 200 mm</span> or <span style={{fontFamily:"'IBM Plex Mono',monospace", color:'var(--bad-text)'}}>(P_ann &lt; 300 mm &amp; P_ond &lt; 30 mm)</span>. Excludes 64 hyper-arid pixels (4.3% of Ethiopia) in the Danakil Depression/Afar where low rainfall generates spurious harmonic ratios (informed by Dunning low-rainfall caution).
                  </div>
                </div>

                <div style={{padding:'8px 12px', background:'var(--bg-surface)', borderRadius:8, border:'1px solid var(--border-primary)'}}>
                  <div style={{fontSize:16, fontWeight:700, color:'var(--accent-text)', marginBottom:2}}>Stage 1: Dunning Harmonic Ratio Baseline</div>
                  <div style={{fontSize:14, color:'var(--text-secondary)', lineHeight:1.5}}>
                    Fourier decomposition across 365-day CHIRPS climatology computes annual fundamental C_1 and semi-annual harmonic C_2. Pixels with <span style={{fontFamily:"'IBM Plex Mono',monospace", color:'var(--accent-text)'}}>r_H = C_2 / C_1 &ge; 1.0</span> are designated as candidate biannual zones.
                  </div>
                </div>

                <div style={{padding:'8px 12px', background:'var(--bg-surface)', borderRadius:8, border:'1px solid var(--border-primary)'}}>
                  <div style={{fontSize:16, fontWeight:700, color:'var(--ok-text)', marginBottom:2}}>Stage 2: EMI Climatological Regime Refinement</div>
                  <div style={{fontSize:14, color:'var(--text-secondary)', lineHeight:1.5}}>
                    For transition pixels (r_H &lt; 1.0), local peak timing and water-season detection promote pixels with dual robust peaks:
                    <div style={{fontFamily:"'IBM Plex Mono',monospace", color:'var(--ok-text)', background:'var(--bg-elevated)', padding:'4px 8px', borderRadius:4, marginTop:4}}>
                      Type 1 = [r_H &ge; 0.8 &or; N_peaks &ge; 2] &and; [P_1 &isin; MAM] &and; [P_2 &isin; JJA/JA] &and; [P_FMAM &ge; 50mm] &and; [P_JJAS &ge; 120mm]
                    </div>
                    <div style={{fontFamily:"'IBM Plex Mono',monospace", color:'var(--warn-text)', background:'var(--bg-elevated)', padding:'4px 8px', borderRadius:4, marginTop:4}}>
                      Type 2 = [r_H &ge; 1.0 &or; N_peaks &ge; 2] &and; [P_1 &isin; MAM] &and; [P_2 &isin; SON/OND] &and; [P_JJA &lt; 1.3 &times; P_OND]
                    </div>
                  </div>
                </div>
              </div>
            </S>
          </div>

          <div className="w-full 2xl:w-[46%] min-w-0 flex flex-col gap-4">
            <S title="The Four Objective Climate Regimes">
              <div style={{display:'grid', gridTemplateColumns:'1fr', gap:8}}>
                <div style={{padding:'10px 12px', background:'rgba(2, 132, 199, 0.08)', borderRadius:8, border:'1px solid rgba(2, 132, 199, 0.3)', borderLeft:'4px solid #0284c7'}}>
                  <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:3}}>
                    <span style={{fontSize:17, fontWeight:700, color:'var(--heading)'}}>Regime 1: Western Unimodal</span>
                    <span style={{fontSize:14, fontFamily:"'IBM Plex Mono',monospace", color:'var(--r1-text)'}}>427 px (28.8%)</span>
                  </div>
                  <div style={{fontSize:14, color:'var(--text-secondary)', lineHeight:1.5}}>
                    Single continuous wet season extending from spring to autumn (Feb/Mar to Oct/Nov), peaking Jul–Aug. Gambella, Assosa, Jimma, Bahir Dar, Gondar, Bedele. Operational product: <strong>Annual Wet Season</strong> (426 active px).
                  </div>
                </div>

                <div style={{padding:'10px 12px', background:'rgba(22, 163, 74, 0.08)', borderRadius:8, border:'1px solid rgba(22, 163, 74, 0.3)', borderLeft:'4px solid #16a34a'}}>
                  <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:3}}>
                    <span style={{fontSize:17, fontWeight:700, color:'var(--heading)'}}>Regime 2: Bimodal Type 1 Highlands</span>
                    <span style={{fontSize:14, fontFamily:"'IBM Plex Mono',monospace", color:'var(--r2-text)'}}>416 px (28.0%)</span>
                  </div>
                  <div style={{fontSize:14, color:'var(--text-secondary)', lineHeight:1.5}}>
                    Central, Eastern &amp; Northern Highlands. Belg (FMAM) early rains followed by a June pause, then Kiremt (JJAS) main rains. Addis Ababa, Wollo, Kombolcha, Tigray, Harar, Hawassa. Operational products: <strong>Belg Early Rains</strong> (416 px) and <strong>Kiremt Bimodal Onset</strong> (416 px).
                  </div>
                </div>

                <div style={{padding:'10px 12px', background:'rgba(217, 119, 6, 0.08)', borderRadius:8, border:'1px solid rgba(217, 119, 6, 0.3)', borderLeft:'4px solid #d97706'}}>
                  <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:3}}>
                    <span style={{fontSize:17, fontWeight:700, color:'var(--heading)'}}>Regime 3: Bimodal Type 2 Pastoral Lowlands</span>
                    <span style={{fontSize:14, fontFamily:"'IBM Plex Mono',monospace", color:'var(--warn-text)'}}>578 px (38.9%)</span>
                  </div>
                  <div style={{fontSize:14, color:'var(--text-secondary)', lineHeight:1.5}}>
                    Southern &amp; Southeastern lowlands (Somali, Borana, Guji, South Omo). Equatorial symmetric bimodal; dry summer (JJAS). Operational products: <strong>Spring rains — Gu/Ganna (MAM)</strong> (578 px) and <strong>Autumn rains — Deyr/Hagaya (SON–OND)</strong> (578 px).
                  </div>
                </div>

                <div style={{padding:'10px 12px', background:'rgba(148, 163, 184, 0.08)', borderRadius:8, border:'1px solid rgba(148, 163, 184, 0.3)', borderLeft:'4px solid #94a3b8'}}>
                  <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:3}}>
                    <span style={{fontSize:17, fontWeight:700, color:'var(--heading)'}}>Regime 0: Arid / Marginal</span>
                    <span style={{fontSize:14, fontFamily:"'IBM Plex Mono',monospace", color:'var(--text-meta)'}}>64 px (4.3%)</span>
                  </div>
                  <div style={{fontSize:14, color:'var(--text-secondary)', lineHeight:1.5}}>
                    Danakil Depression and dry Afar lowlands. Non-seasonal hyper-arid desert. Screened out and flagged with: <em>"Project-defined rainfall screening indicates insufficient seasonal rainfall for robust onset/cessation estimation."</em>
                  </div>
                </div>
              </div>
            </S>

            <S title="Operational Mask Arithmetic vs Regime Eligibility">
              <div style={{background:'var(--bg-elevated)', padding:'10px 14px', borderRadius:8, border:'1px solid var(--border-primary)', fontSize:14, lineHeight:1.6, color:'var(--text-secondary)'}}>
                <div style={{fontFamily:"'IBM Plex Mono',monospace", color:'var(--accent-text)', fontWeight:700, marginBottom:4}}>
                  Operational Mask = Regime_Valid &and; Rainfall_Significance &and; DR_Valid &and; Spatial_QC
                </div>
                <div><strong>National JJAS Monsoon Domain:</strong> Regime 1 (427 px) + Regime 2 (416 px) = <strong>843 regime-eligible pixels</strong>.</div>
                <div>After applying secondary thresholds (<span style={{fontFamily:"'IBM Plex Mono',monospace"}}>P_JJAS &ge; 120 mm, R_JJAS &ge; 20%, DR &ge; 60%</span> and connected-component cleanup), exactly 11 peripheral pixels are excluded, leaving <strong>832 active operational pixels (56.0% of Ethiopia land)</strong>.</div>
                <div style={{marginTop:4}}>Belg (416 px), Gu/Ganna (578 px), and Deyr/Hagaya (578 px) 100% satisfy their core agro-climatic secondary thresholds.</div>
              </div>
            </S>
          </div>
        </div>
      )}

      {/* SUB-TAB: ONSET, CESSATION & LGP METHODS (Kenya Short Rains) */}
      {section === 'methods' && (
        <div className="flex flex-col gap-4">
          <S title="Five Onset & Cessation Methods (Kenya Short Rains, OND)">
            <div style={{background:'var(--bg-elevated)', padding:'10px 14px', borderRadius:8, border:'1px solid var(--border-primary)', fontSize:16, lineHeight:1.6, color:'var(--text-secondary)', marginBottom:10}}>
              Pick a method with the <strong>Method</strong> selector above the map (Short Rains season). The maps, probabilities, skill, charts and bulletin all follow it. The methods ask different questions, so their onset, cessation and season length are not interchangeable: Dunning finds the turning points of the season's rainfall, the Agri rules find the first rains a farmer could plant on, and the FAO water balance tracks whether the soil holds enough water for a maize crop.
            </div>
            <Tbl head={['Method','Onset','Cessation','Season length','Data','Runs']} rows={[
              ['Dunning', 'Day after the accumulated rainfall anomaly A(D) reaches its minimum', 'Day A(D) reaches its maximum after onset', 'Cessation − onset', 'CHIRPS v2 · SEAS5 (bias-corrected to CHIRPS v2)', 'All four'],
              ['Agri rule 1', 'Wet day (≥ 1 mm) starting > 20 mm in 3 days; no 7-day dry spell in the next 21 days', 'After a 10-day period with rain < 0.5 × PET, the day a 100 mm soil store is empty', 'Cessation − onset', 'CHIRPS v2 · SEAS5 · Hargreaves PET', 'All four'],
              ['Agri rule 2', '≥ 20 mm in 5 days with ≥ 3 rainy days; no dry spell longer than 7 days in the next 21', 'As rule 1', 'Cessation − onset', 'CHIRPS v2 · SEAS5 · Hargreaves PET', 'All four'],
              ['Agri rule 3', '> 20 mm in 3 days; no dry spell longer than 10 days in the next 30', 'First day of a 10-day period with rain < 0.5 × PET', 'Cessation − onset', 'CHIRPS v2 · SEAS5 · Hargreaves PET', 'All four'],
              ['FAO water balance', 'Agricultural: 10-day rain ≥ 0.5 × ET0 and PAW/TAW ≥ 0.20 for 5 days; no 7-day spell below 0.20 in the next 21', 'Agricultural: 7 days with PAW/TAW < 0.20, ETa/ETc < 0.5 and a 10-day rain deficit', 'Three LGPs, one per definition', 'CHIRPS v3 · ERA5-Land ET0 · SoilGrids · SEAS5 (bias-corrected to CHIRPS v3)', 'Oct 01, Oct 01 + latest obs'],
            ]}/>
            <div style={{fontSize:14, color:'var(--text-muted)', lineHeight:1.5, marginTop:6}}>
              Agri rules 1–3 are adapted from the ICPAC operational definitions; onset is searched 15 Aug – 15 Jan and cessation to 28 Feb (Sep 01 run: to 31 Dec). Dunning searches 1 Sep – 31 Dec. Dry day: &lt; 1 mm.
            </div>
          </S>

          <div className="flex flex-col 2xl:flex-row gap-6">
            <div className="w-full 2xl:w-[48%] min-w-0 flex flex-col gap-4">
              <S title="Forecast Runs (Init Selector)">
                <Tbl head={['Run','Rainfall used','Methods']} rows={[
                  ['Sep 01', 'ECMWF SEAS5 from 1 Sep, to 31 Dec', 'Dunning, Agri rules 1–3'],
                  ['Oct 01', 'ECMWF SEAS5 from 1 Oct, to 28 Feb', 'Dunning, Agri rules 1–3, FAO water balance'],
                  ['Oct 01 + Sep obs', 'Observed CHIRPS for September, then SEAS5 from 1 Oct', 'Dunning, Agri rules 1–3'],
                  ['Oct 01 + latest obs', 'Observed CHIRPS to the latest available day, then SEAS5; refreshed by the daily update', 'Dunning, Agri rules 1–3, FAO water balance'],
                ]}/>
                <div style={{fontSize:14, color:'var(--text-muted)', lineHeight:1.5, marginTop:6}}>
                  25 SEAS5 members, each bias-corrected day by day and cell by cell with empirical quantile mapping (EQM) against CHIRPS. Days before a run's forecast start are observed CHIRPS, in the hindcast years too. Picking a method that the selected run does not have switches to the latest run that has it.
                </div>
              </S>

              <S title="Probabilities, Skill & Missing Dates">
                <KV label="Terciles" value="Early / normal / late (short / normal / long for LGP) from the 33rd and 67th percentiles of the observed record at each cell (CAL 1993–2016): CHIRPS v2 for Dunning and the Agri rules, CHIRPS v3 for FAO."/>
                <KV label="Probabilities" value="Share of members in each tercile, calibrated with the damping factor α fitted on the hindcasts (CAL 1993–2016)."/>
                <KV label="Skill" value="RPSS and hit rate on the independent validation years (VAL 2017–2024). RPSS > 0 beats climatology."/>
                <KV label="No onset / cessation" value="A member with none by the search end counts as later than any date, not as missing, so medians and terciles stay honest in failed seasons. Season length is 0 without onset."/>
                <KV label="Flat terciles (FAO)" value="Where the observed record has no spread (33rd = 67th percentile), no tercile forecast is issued: probabilities and skill are left blank (western Kenya and the coast, where onset falls on the first search day)."/>
              </S>

            </div>

            <div className="w-full 2xl:w-[52%] min-w-0 flex flex-col gap-4">
              <S title="FAO Water Balance: FAO-56 Daily Soil-Water Bucket">
                <Step n="1" title="Reference evapotranspiration  ET0" eq={"ET0 = [0.408 Δ (Rn − G) + γ (900/(T+273)) u2 (es − ea)] / [Δ + γ (1 + 0.34 u2)]"} desc="FAO-56 Penman-Monteith (Eq. 6) from ERA5-Land daily Tmax, Tmin, dewpoint, 2 m wind, solar radiation and surface pressure; G = 0 for daily steps. Forecast days use the ERA5-Land ET0 climatology (1993–2016, ±7-day smoothed), the same for every member."/>
                <Step n="2" title="Crop water need  ETc" eq={"ETc = Kc × ET0"} desc="Maize Kc 0.30 / 1.20 / 0.60 (initial / mid / end), stages 20 / 35 / 40 / 30 days from planting, which is the agricultural onset. Kc_ini applies before it."/>
                <Step n="3" title="Root-zone water  TAW and RAW" eq={"TAW = 1000 (θFC − θWP) Zr        RAW = p × TAW"} desc="θFC and θWP from SoilGrids 2.0 texture and organic carbon via the Saxton & Rawls (2006) pedotransfer equations, Zr = 1.0 m; p = 0.55 adjusted for ETc (FAO-56 Table 22). Kenya mean available water ~100–108 mm per metre."/>
                <Step n="4" title="Water stress  Ks  and actual ET" eq={"Ks = 1 if Dr ≤ RAW, else (TAW − Dr)/(TAW − RAW)        ETa = Ks × ETc"} desc="Dr = TAW − SW is the root-zone depletion (previous day). Ks < 1 means the crop is water-stressed."/>
                <Step n="5" title="Daily bucket" eq={"SW_t = SW_t−1 + P − ETa − runoff − drainage,   0 ≤ SW ≤ TAW"} desc="Starts 1 Aug from ERA5-Land 0–100 cm soil moisture. Water above TAW drains; PAW = SW and PAW/TAW is the plant-available fraction. In a forecast, each member continues the observed bucket with its own rainfall."/>
                <Step n="6" title="Five dates and three season lengths" table={[
                  ['Rainfall onset', 'First wet day from which 10-day rain ≥ 0.5 × ET0'],
                  ['Agricultural onset', 'As above, and PAW/TAW ≥ 0.20 that day and the next 4; rejected as a false start if 7 days fall below 0.20 within 21 days'],
                  ['Rainfall cessation', 'From 1 Nov, rain < 0.5 × ET0 in two consecutive 10-day windows'],
                  ['Agricultural cessation', '7 days with PAW/TAW < 0.20, ETa/ETc < 0.5 and a 10-day rain deficit'],
                  ['Crop-water cessation', 'After the climatological rainfall peak, 21-day rain < 0.5 × ETc with PAW/TAW falling below 0.20'],
                  ['Definition picker', 'Agricultural: agricultural onset → agricultural cessation. Rainfall: rainfall onset → rainfall cessation. Crop-water: agricultural onset → crop-water cessation. LGP = cessation − onset + 1 for each.'],
                ]}/>
                <div style={{fontSize:14, color:'var(--text-muted)', lineHeight:1.5}}>
                  Rainfall cessation usually comes before agricultural cessation, because the soil keeps supplying water after the rains stop. The pixel panel shows the chance that onset or cessation has happened by today and within 7, 14 and 21 days, and the members' PAW/TAW outlook against the 0.20 critical level. Method notes: <span style={{fontFamily:"'IBM Plex Mono',monospace"}}>FAO_WATER_BALANCE_METHOD.md</span>.
                </div>
              </S>

              <S title="FAO Quality Flags (Bitmask)">
                <Tbl head={['Bit','Meaning']} rows={[
                  ['1', 'No rainfall onset'], ['2', 'No agricultural onset'], ['4', 'At least one false onset rejected'],
                  ['8', 'No rainfall cessation'], ['16', 'No agricultural cessation'], ['32', 'No crop-water cessation'],
                  ['64', 'Insufficient input data (> 5% of days missing)'], ['128', 'Incomplete season (data end before 28 Feb)'],
                  ['256', 'Soil parameters unavailable'], ['512', 'Onset on the first search day (15 Aug): the soil is already wet, a season already under way'],
                ]}/>
              </S>
            </div>
          </div>
        </div>
      )}

      {section === 'regimes' && <h3 style={{margin:'8px 0 16px'}}>Regime and season maps, GIS files</h3>}
      {/* SUB-TAB: MAPS & GIS SHAPEFILES */}
      {section === 'regimes' && (
        <div className="w-full flex flex-col gap-5">
          {/* Top Info Banner & Download Shapefiles */}
          <div style={{
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border-primary)',
            borderRadius: 10,
            padding: '14px 18px',
            display: 'flex',
            flexDirection: 'column',
            gap: 12
          }}>
            <div style={{display:'flex', justifyContent:'space-between', alignItems:'flex-start', flexWrap:'wrap', gap:10}}>
              <div>
                <div style={{fontSize:20, fontWeight:800, color:'var(--text-primary)', marginBottom:4}}>
                  Climatological Regimes &amp; Seasonal Domain Shapefiles (Ethiopia Only)
                </div>
                <div style={{fontSize:16, color:'var(--text-secondary)', lineHeight:1.5, maxWidth:720}}>
                  Standard ESRI Shapefiles (.shp, .shx, .dbf, .prj) and GeoJSON (.geojson) files in <strong>WGS 84 (EPSG:4326)</strong> for GIS analysis in QGIS, ArcGIS, Python (GeoPandas), and R.
                  These boundary datasets define the sovereign meteorological domains used in operational onset/cessation tracking.
                </div>
              </div>
              <a
                href={import.meta.env.BASE_URL + 'shapefiles/ethiopia_climate_regimes_and_masks_shp.zip'}
                download="ethiopia_climate_regimes_and_masks_shp.zip"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '8px 16px',
                  borderRadius: 8,
                  background: 'var(--accent-blue)',
                  color: '#ffffff',
                  fontWeight: 700,
                  fontSize: 17,
                  textDecoration: 'none',
                  boxShadow: '0 2px 8px rgba(37, 99, 235, 0.3)',
                  transition: 'all 0.15s ease'
                }}
              >
                <span></span>
                <span>Download Shapefiles Package (.zip, 20 KB)</span>
              </a>
            </div>

            {/* Shapefiles Inventory Table */}
            <div style={{overflowX:'auto', borderTop:'1px solid var(--border-primary)', paddingTop:10}}>
              <table style={{width:'100%', borderCollapse:'collapse', fontSize:14}}>
                <thead>
                  <tr style={{borderBottom:'1px solid var(--border-primary)', background:'var(--bg-surface)'}}>
                    {['Dataset Layer', 'Shapefile (.shp)', 'GeoJSON', 'Pixels', 'Land %', 'Climatological Description'].map(h=>(
                      <th key={h} style={{padding:'5px 8px', textAlign:'left', color:'var(--text-muted)', fontWeight:700, textTransform:'uppercase', fontSize:13}}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[
                    ['Four Objective Regimes', 'ethiopia_four_climate_regimes.shp', 'ethiopia_four_climate_regimes.geojson', '1,485', '100%', 'Complete 4-class partition: Regime 0, 1, 2, 3 (ETHIOPIA ONLY)'],
                    ['Kiremt / Main Rains', 'mask_kiremt_jjas.shp', 'mask_kiremt_jjas.geojson', '832', '56.0%', 'National summer monsoon domain (Regime 1 + Regime 2; P_JJAS ≥ 120 mm)'],
                    ['Belg Early Rains', 'mask_belg_early_rains.shp', 'mask_belg_early_rains.geojson', '416', '28.0%', 'Highlands Type-1 spring rains (Regime 2 only; P_FMAM ≥ 80 mm)'],
                    ['Deyr / Short Rains & Gu', 'mask_deyr_autumn_rains.shp', 'mask_deyr_autumn_rains.geojson', '578', '38.9%', 'Pastoral lowlands biannual domain (Regime 3 only; Somali, Borana, Guji)'],
                    ['Western Extended Season', 'mask_western_annual.shp', 'mask_western_annual.geojson', '426', '28.7%', 'Western unimodal prolonged season (Regime 1 only; Gambella, Assosa, Jimma)'],
                  ].map(([title, shp, geojson, px, pct, desc], i) => (
                    <tr key={shp} style={{borderBottom:'1px solid var(--border-primary)', background: i%2===0?'transparent':'var(--bg-elevated)'}}>
                      <td style={{padding:'5px 8px', color:'var(--text-primary)', fontWeight:700}}>{title}</td>
                      <td style={{padding:'5px 8px', fontFamily:"'IBM Plex Mono',monospace", color:'var(--accent-text)'}}>{shp}</td>
                      <td style={{padding:'5px 8px', fontFamily:"'IBM Plex Mono',monospace", color:'var(--ok-text)'}}>{geojson}</td>
                      <td style={{padding:'5px 8px', fontFamily:"'IBM Plex Mono',monospace", color:'var(--text-primary)'}}>{px}</td>
                      <td style={{padding:'5px 8px', fontFamily:"'IBM Plex Mono',monospace", color:'var(--text-secondary)'}}>{pct}</td>
                      <td style={{padding:'5px 8px', color:'var(--text-secondary)'}}>{desc}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* High-Resolution Maps Grid */}
          <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(min(340px, 100%), 1fr))', gap:16}}>
            {/* Map 1: Four Regimes */}
            <div style={{background:'var(--bg-elevated)', borderRadius:10, border:'1px solid var(--border-primary)', overflow:'hidden', display:'flex', flexDirection:'column'}}>
              <div style={{padding:'10px 14px', borderBottom:'1px solid var(--border-primary)', display:'flex', justifyContent:'space-between', alignItems:'center', background:'var(--bg-surface)'}}>
                <span style={{fontSize:17, fontWeight:700, color:'var(--text-primary)'}}>The Four Objective Climate Regimes</span>
                <span style={{fontSize:14, background:'var(--info-bg)', color:'var(--accent-text)', border:'1px solid var(--info-border)', padding:'2px 6px', borderRadius:4, fontWeight:700}}>ETHIOPIA ONLY</span>
              </div>
              <img src={import.meta.env.BASE_URL + 'figures/ethiopia_four_climate_regimes_map.png'} alt="Four Objective Climate Regimes of Ethiopia" style={{width:'100%', height:'auto', display:'block'}} />
              <div style={{padding:'10px 14px', fontSize:15, color:'var(--text-secondary)', lineHeight:1.5}}>
                <strong>Classification Basis:</strong> Dunning Fourier decomposition (<span style={{fontFamily:"'IBM Plex Mono',monospace", color:'var(--accent-text)'}}>r_H = C_2 / C_1</span>) + EMI local peak-timing rules.
                Partitions Ethiopia into 4 disjoint meteorological domains: Regime 1 (Western Unimodal, 28.7%), Regime 2 (Bimodal Type-1 Highlands, 28.0%), Regime 3 (Bimodal Type-2 Lowlands, 38.9%), and Regime 0 (Arid/Marginal Afar, 4.4%).
              </div>
            </div>

            {/* Diagram: Workflow & Architecture */}
            <div style={{background:'var(--bg-elevated)', borderRadius:10, border:'1px solid var(--border-primary)', overflow:'hidden', display:'flex', flexDirection:'column'}}>
              <div style={{padding:'10px 14px', borderBottom:'1px solid var(--border-primary)', display:'flex', justifyContent:'space-between', alignItems:'center', background:'var(--bg-surface)'}}>
                <span style={{fontSize:17, fontWeight:700, color:'var(--text-primary)'}}>Scientific Architecture &amp; Operational Workflow</span>
                <span style={{fontSize:14, background:'rgba(37, 99, 235, 0.15)', color:'var(--accent-text)', border:'1px solid rgba(37, 99, 235, 0.3)', padding:'2px 6px', borderRadius:4, fontWeight:700}}>END-TO-END PIPELINE</span>
              </div>
              <img src={import.meta.env.BASE_URL + 'figures/scientific_architecture_workflow.png'} alt="Scientific Architecture & Workflow Diagram" style={{width:'100%', height:'auto', display:'block'}} />
              <div style={{padding:'10px 14px', fontSize:15, color:'var(--text-secondary)', lineHeight:1.5}}>
                <strong>Five-Stage Architecture:</strong> Stage 1 (Data Ingestion) &rarr; Stage 2 (Fourier Diagnostics) &rarr; Stage 3 (Regime Partition — Ethiopia Only) &rarr; Stage 4 (Dynamic Domain Masking) &rarr; Stage 5 (Onset/Cessation Anomalous Accumulation Calculation &amp; GIS Products).
              </div>
            </div>

            {/* Map 2: Kiremt JJAS */}
            <div style={{background:'var(--bg-elevated)', borderRadius:10, border:'1px solid var(--border-primary)', overflow:'hidden', display:'flex', flexDirection:'column'}}>
              <div style={{padding:'10px 14px', borderBottom:'1px solid var(--border-primary)', display:'flex', justifyContent:'space-between', alignItems:'center', background:'var(--bg-surface)'}}>
                <span style={{fontSize:17, fontWeight:700, color:'var(--text-primary)'}}>Kiremt / Main Rains Operational Domain (JJAS)</span>
                <span style={{fontSize:14, background:'rgba(2, 132, 199, 0.15)', color:'var(--r1-text)', border:'1px solid rgba(2, 132, 199, 0.3)', padding:'2px 6px', borderRadius:4, fontWeight:700}}>832 PIXELS (56.0%)</span>
              </div>
              <img src={import.meta.env.BASE_URL + 'figures/mask_kiremt_jjas.png'} alt="Kiremt Main Rains Domain" style={{width:'100%', height:'auto', display:'block'}} />
              <div style={{padding:'10px 14px', fontSize:15, color:'var(--text-secondary)', lineHeight:1.5}}>
                <strong>Summer Monsoon Footprint:</strong> Encompasses the Highlands (Regime 2) and Western Unimodal belt (Regime 1). Screened by <span style={{fontFamily:"'IBM Plex Mono',monospace", color:'var(--accent-text)'}}>P_JJAS &ge; 120 mm</span> and <span style={{fontFamily:"'IBM Plex Mono',monospace", color:'var(--accent-text)'}}>r_JJAS &ge; 20%</span>. Eliminates southern/southeastern pastoral lowlands where summer is a cold dry pause.
              </div>
            </div>

            {/* Map 3: Belg Early Rains */}
            <div style={{background:'var(--bg-elevated)', borderRadius:10, border:'1px solid var(--border-primary)', overflow:'hidden', display:'flex', flexDirection:'column'}}>
              <div style={{padding:'10px 14px', borderBottom:'1px solid var(--border-primary)', display:'flex', justifyContent:'space-between', alignItems:'center', background:'var(--bg-surface)'}}>
                <span style={{fontSize:17, fontWeight:700, color:'var(--text-primary)'}}>Belg Early Rains Operational Domain (FMAM)</span>
                <span style={{fontSize:14, background:'rgba(5, 150, 105, 0.15)', color:'var(--ok-text)', border:'1px solid rgba(5, 150, 105, 0.3)', padding:'2px 6px', borderRadius:4, fontWeight:700}}>416 PIXELS (28.0%)</span>
              </div>
              <img src={import.meta.env.BASE_URL + 'figures/mask_belg_early_rains.png'} alt="Belg Early Rains Domain" style={{width:'100%', height:'auto', display:'block'}} />
              <div style={{padding:'10px 14px', fontSize:15, color:'var(--text-secondary)', lineHeight:1.5}}>
                <strong>Central &amp; Eastern Highlands Belg:</strong> Strictly limited to Regime 2 (Type-1 Highlands) where spring rains represent a discrete agricultural cycle followed by a June pause. Western unimodal zone is excluded to avoid artificial cessation dates in June.
              </div>
            </div>

            {/* Map 4: Deyr & Gu Pastoral Lowlands */}
            <div style={{background:'var(--bg-elevated)', borderRadius:10, border:'1px solid var(--border-primary)', overflow:'hidden', display:'flex', flexDirection:'column'}}>
              <div style={{padding:'10px 14px', borderBottom:'1px solid var(--border-primary)', display:'flex', justifyContent:'space-between', alignItems:'center', background:'var(--bg-surface)'}}>
                <span style={{fontSize:17, fontWeight:700, color:'var(--text-primary)'}}>Deyr / Short Rains &amp; Gu Domain (SON–OND &amp; MAM)</span>
                <span style={{fontSize:14, background:'rgba(217, 119, 6, 0.15)', color:'var(--warn-text)', border:'1px solid rgba(217, 119, 6, 0.3)', padding:'2px 6px', borderRadius:4, fontWeight:700}}>578 PIXELS (38.9%)</span>
              </div>
              <img src={import.meta.env.BASE_URL + 'figures/mask_deyr_short_rains.png'} alt="Deyr Autumn and Gu Spring Rains Domain" style={{width:'100%', height:'auto', display:'block'}} />
              <div style={{padding:'10px 14px', fontSize:15, color:'var(--text-secondary)', lineHeight:1.5}}>
                <strong>Bimodal Pastoral Rangelands:</strong> Somali Region, Borana, Guji, and Bale lowlands. Driven by the equatorial biannual cycle (<span style={{fontFamily:"'IBM Plex Mono',monospace", color:'var(--warn-text)'}}>r_H &ge; 1.0</span>) with major Gu/Ganna rains (MAM) and secondary Deyr/Hagaya rains (SON–OND).
              </div>
            </div>

            {/* Map 5: Western Extended Season */}
            <div style={{background:'var(--bg-elevated)', borderRadius:10, border:'1px solid var(--border-primary)', overflow:'hidden', display:'flex', flexDirection:'column'}}>
              <div style={{padding:'10px 14px', borderBottom:'1px solid var(--border-primary)', display:'flex', justifyContent:'space-between', alignItems:'center', background:'var(--bg-surface)'}}>
                <span style={{fontSize:17, fontWeight:700, color:'var(--text-primary)'}}>Western Ethiopia Extended Annual Wet Season</span>
                <span style={{fontSize:14, background:'rgba(99, 102, 241, 0.15)', color:'var(--violet-text)', border:'1px solid rgba(99, 102, 241, 0.3)', padding:'2px 6px', borderRadius:4, fontWeight:700}}>426 PIXELS (28.7%)</span>
              </div>
              <img src={import.meta.env.BASE_URL + 'figures/mask_western_extended_season.png'} alt="Western Ethiopia Extended Annual Wet Season Domain" style={{width:'100%', height:'auto', display:'block'}} />
              <div style={{padding:'10px 14px', fontSize:15, color:'var(--text-secondary)', lineHeight:1.5}}>
                <strong>Single Prolonged Season:</strong> Gambella, Benishangul-Gumuz (Assosa), Jimma, Bedele, Gondar/Bahir Dar western slopes. Rains begin in Feb/Mar, intensify continuously through summer without a June dry break, and end in Oct/Nov.
              </div>
            </div>
          </div>
        </div>
      )}

      {/* SUB-TAB 2: ONSET DETECTION ALGORITHM */}
      {section === 'methods' && (
        <div className="w-full max-w-4xl">
          <S title="Dunning Cumulative Anomaly Algorithm (8 Operational Steps)">
            <Step n="1" title="Climatological Daily Mean  Q_d(i,j)" eq={"Q_d(i,j) = (1/N_cal) x sum_{y in CAL} R_{d,y}(i,j)"} desc="Mean daily precipitation for each calendar DOY d over the calibration years (CAL: 1993–2016 for the Short Rains and Ethiopia seasons, 1981–2016 for the Long Rains)." table={[['Q_d(i,j)','Mean daily precip for DOY d at pixel (i,j)'],['R_{d,y}','Observed daily CHIRPS precip (mm/day) at pixel (i,j), DOY d, year y'],['N_cal','Number of calibration years (24 for 1993–2016)'],['d','DOY restricted to seasonal search window']]}/>
            <Step n="2" title="Window Mean  Q_bar(i,j)  --  the Dunning accumulation baseline" eq={"Q_bar(i,j) = (1/N_win) x sum_{d in Window} Q_d(i,j)"} desc="A single scalar value per pixel -- the long-term average daily rainfall rate across the entire seasonal forecast window. Subtracting it produces anomalies that accumulate positively during wet periods and negatively during dry ones." table={[['Q_bar(i,j)','Scalar window mean -- single value per pixel, not DOY-varying'],['N_win','Length of forecast window in days (e.g., 183 days for JJAS, 135 days for FMAM)']]}/>
            <Step n="3" title="Climatological Accumulated Anomaly  C(d)" eq={"C(d) = sum_{k=d_start}^{d} [ Q_k(i,j) - Q_bar(i,j) ]"} desc="Cumulative sum of daily climatological anomalies from window start to day d. Computed once per pixel over the calibration years." table={[['C(d)','Cumulative daily anomaly up to day d -- the climatological water season curve'],['Q_k(i,j)','Climatological daily mean at DOY k'],['Q_bar(i,j)','Scalar window mean (never re-computed per year)']]}/>
            <Step n="4" title="Climatological Season Bounds  d_s  and  d_e" eq={"d_s = argmin C(d)      d_e = argmax C(d)  [d > d_s]"} desc="Pixel-specific constants from calibration period defining the search window for individual-year event detection." table={[['d_s(i,j)','Climatological season start -- DOY where C(d) reaches its minimum'],['d_e(i,j)','Climatological season end -- DOY where C(d) reaches its maximum after d_s']]}/>
            <Step n="5" title="Individual-Year Accumulated Anomaly  A(D)" eq={"A(D) = sum_{j=d_acc,start}^{D} [ R_{j,y}(i,j) - Q_bar(i,j) ]"} desc="Same accumulation applied to each year or ensemble member individually. Search window clamped around d_s and d_e with +/- delta = 45-50 day buffer." table={[['A(D)','Accumulated precip anomaly for year y from window start to day D'],['R_{j,y}','Observed daily precip at pixel (i,j), DOY j, year y'],['Q_bar(i,j)','Same scalar window mean from Step 2']]}/>
            <Step n="6" title="Onset Detection" eq={"onset_y(i,j) = argmin A(D) + 1"} desc="Onset is the day after A(D) reaches its absolute minimum -- the first day precipitation exceeds Q_bar on a sustained basis. NaN if argmin falls at window boundary." table={[['argmin A(D)','Day of deepest pre-season dry deficit'],['+1','Dunning definition: onset is the day after the minimum']]}/>
            <Step n="7" title="Cessation Detection" eq={"cessation_y(i,j) = argmax A(D)  [D > onset_y]"} desc="The day A(D) reaches its peak after onset. No +1 offset; search restricted to days strictly after onset."/>
            <Step n="8" title="Length of Growing Period (LGP)" eq={"LGP_y(i,j) = cessation_y(i,j) - onset_y(i,j)"} desc="Season length in days. Below 35 days = near-complete failure; below 60 days = below-median season."/>
          </S>
        </div>
      )}

      {/* SUB-TAB 3: 20-SITE AUDITED DIAGNOSTIC AGREEMENT */}
      {section === 'regimes' && (
        <div className="w-full flex flex-col gap-4">
          <S title="Audited 20-Site Representative Diagnostic Consistency Check">
            <div style={{background:'var(--bg-elevated)', padding:'10px 14px', borderRadius:8, border:'1px solid var(--border-primary)', fontSize:16, lineHeight:1.6, color:'var(--text-secondary)', marginBottom:12}}>
              <strong>Sampling Protocol:</strong> To rigorously audit against template or regional curve reuse, every station coordinate was sampled directly from the nearest CHIRPS 0.25° grid cell (<span style={{fontFamily:"'IBM Plex Mono',monospace", color:'var(--accent-text)'}}>latitude, longitude</span> &rarr; grid index <span style={{fontFamily:"'IBM Plex Mono',monospace", color:'var(--accent-text)'}}>i, j</span>). The table below reports genuine, distinct annual rainfall totals, Fourier harmonic amplitudes (C_1, C_2), harmonic ratios (r_H = C_2/C_1), and resulting regime diagnoses. <strong>20/20 representative sites show diagnostic agreement with documented EMI regional climate regimes.</strong>
            </div>

            {/* Filter and Control Bar */}
            <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', flexWrap:'wrap', gap:10, marginBottom:12}}>
              <div style={{display:'flex', alignItems:'center', gap:8, flexWrap:'wrap'}}>
                <button
                  type="button"
                  onClick={() => setExpandedStations(prev => ({ ...prev, gambella: !prev.gambella }))}
                  style={{
                    padding: '5px 12px',
                    borderRadius: 6,
                    fontSize: 16,
                    fontWeight: 700,
                    cursor: 'pointer',
                    background: expandedStations['gambella'] ? 'rgba(56, 189, 248, 0.2)' : 'var(--bg-elevated)',
                    color: expandedStations['gambella'] ? 'var(--r1-text)' : 'var(--text-secondary)',
                    border: '1px solid ' + (expandedStations['gambella'] ? 'var(--r1-text)' : 'var(--border-primary)')
                  }}
                >
                  {expandedStations['gambella'] ? 'Hide Example (Gambella)' : 'Show Example Graph (Gambella)'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    const all = {}
                    AUDITED_STATIONS.forEach(s => { all[s.id] = true })
                    setExpandedStations(all)
                  }}
                  style={{padding: '5px 10px', borderRadius: 6, fontSize: 16, fontWeight: 600, cursor: 'pointer', background: 'var(--bg-elevated)', color: 'var(--text-secondary)', border: '1px solid var(--border-primary)'}}
                >
                  Expand All 20 Graphs
                </button>
                <button
                  type="button"
                  onClick={() => setExpandedStations({})}
                  style={{padding: '5px 10px', borderRadius: 6, fontSize: 16, fontWeight: 600, cursor: 'pointer', background: 'var(--bg-elevated)', color: 'var(--text-secondary)', border: '1px solid var(--border-primary)'}}
                >
                  Collapse All
                </button>
              </div>

              <div style={{display:'flex', alignItems:'center', gap:8, flexWrap:'wrap', minWidth:0, maxWidth:'100%'}}>
                <select
                  value={stationFilter}
                  onChange={e => setStationFilter(e.target.value)}
                  style={{maxWidth: '100%', padding: '4px 10px', borderRadius: 6, fontSize: 16, fontWeight: 600, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', color: 'var(--text-primary)', outline: 'none'}}
                >
                  <option value="all">All Regimes (20 Sites)</option>
                  <option value="1">Regime 1: Western Unimodal (6)</option>
                  <option value="2">Regime 2: Bimodal Type 1 Belg+Kiremt (6)</option>
                  <option value="3">Regime 3: Bimodal Type 2 Gu+Deyr (7)</option>
                  <option value="0">Regime 0: Arid / Marginal (1)</option>
                </select>
                <input
                  type="text"
                  placeholder="Search station..."
                  value={stationSearch}
                  onChange={e => setStationSearch(e.target.value)}
                  style={{padding: '4px 8px', borderRadius: 6, fontSize: 16, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', color: 'var(--text-primary)', outline: 'none', width: 140}}
                />
              </div>
            </div>

            {(() => {
              const filteredStations = AUDITED_STATIONS.filter(st => {
                if (stationFilter === '1' && !st.reg.includes('Regime 1')) return false
                if (stationFilter === '2' && !st.reg.includes('Regime 2')) return false
                if (stationFilter === '3' && !st.reg.includes('Regime 3')) return false
                if (stationFilter === '0' && !st.reg.includes('Regime 0')) return false
                if (stationSearch) {
                  const q = stationSearch.toLowerCase()
                  return st.name.toLowerCase().includes(q) || st.desc.toLowerCase().includes(q)
                }
                return true
              })

              return (
                <div style={{overflowX:'auto'}}>
                  <table style={{width:'100%', borderCollapse:'collapse', fontSize:14}}>
                    <thead>
                      <tr style={{borderBottom:'1px solid var(--border-primary)', background:'var(--bg-surface)'}}>
                        {['Station','Req Coord','Grid Coord','(i, j)','P_ann (mm)','C1','C2','r_H','Assigned Regime','Agreement','Climatological Feature','Profile Graph'].map(h=>(
                          <th key={h} style={{padding:'6px 8px', textAlign:'left', color:'var(--text-muted)', fontWeight:700, letterSpacing:'0.06em', textTransform:'uppercase', whiteSpace:'nowrap'}}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {filteredStations.map((st, i) => {
                        const isExpanded = !!expandedStations[st.id]
                        return (
                          <Fragment key={st.id}>
                            <tr
                              onClick={() => toggleStation(st.id)}
                              style={{
                                borderBottom: isExpanded ? 'none' : '1px solid var(--border-primary)',
                                background: isExpanded ? 'rgba(56, 189, 248, 0.08)' : (i%2 === 0 ? 'transparent' : 'var(--bg-elevated)'),
                                cursor: 'pointer',
                                transition: 'background 0.15s ease'
                              }}
                              title="Click row to expand/collapse rainfall profile graph"
                            >
                              <td style={{padding:'5px 8px', color:'var(--text-primary)', fontWeight:700, whiteSpace:'nowrap'}}>
                                <span style={{marginRight: 5, color: isExpanded ? 'var(--accent-blue)' : 'var(--text-muted)'}}>
                                  {isExpanded ? '▼' : '▶'}
                                </span>
                                {st.name}
                              </td>
                              <td style={{padding:'5px 8px', color:'var(--text-muted)', fontFamily:"'IBM Plex Mono',monospace", whiteSpace:'nowrap'}}>{st.req}</td>
                              <td style={{padding:'5px 8px', color:'var(--text-secondary)', fontFamily:"'IBM Plex Mono',monospace", whiteSpace:'nowrap'}}>{st.grid}</td>
                              <td style={{padding:'5px 8px', color:'var(--accent-text)', fontFamily:"'IBM Plex Mono',monospace", whiteSpace:'nowrap'}}>{st.idx}</td>
                              <td style={{padding:'5px 8px', color:'var(--text-primary)', fontFamily:"'IBM Plex Mono',monospace", fontWeight:600}}>{st.pann}</td>
                              <td style={{padding:'5px 8px', color:'var(--text-secondary)', fontFamily:"'IBM Plex Mono',monospace"}}>{st.c1}</td>
                              <td style={{padding:'5px 8px', color:'var(--text-secondary)', fontFamily:"'IBM Plex Mono',monospace"}}>{st.c2}</td>
                              <td style={{padding:'5px 8px', color: Number(st.rh) >= 1.0 ? 'var(--warn-text)' : 'var(--r1-text)', fontFamily:"'IBM Plex Mono',monospace", fontWeight:700}}>{st.rh}</td>
                              <td style={{padding:'5px 8px', whiteSpace:'nowrap', color: st.reg.includes('Regime 1') ? 'var(--r1-text)' : (st.reg.includes('Regime 2') ? 'var(--r2-text)' : (st.reg.includes('Regime 3') ? 'var(--warn-text)' : 'var(--text-meta)')), fontWeight:600}}>{st.reg}</td>
                              <td style={{padding:'5px 8px', color:'var(--ok-text)', fontWeight:700, whiteSpace:'nowrap'}}>✓ 20/20</td>
                              <td style={{padding:'5px 8px', color:'var(--text-muted)', minWidth:160}}>{st.desc}</td>
                              <td style={{padding:'5px 8px', whiteSpace:'nowrap'}}>
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    toggleStation(st.id)
                                  }}
                                  style={{
                                    padding: '3px 8px',
                                    borderRadius: 6,
                                    fontSize: 14,
                                    fontWeight: 700,
                                    cursor: 'pointer',
                                    background: isExpanded ? 'var(--accent-blue)' : 'var(--bg-elevated)',
                                    color: isExpanded ? '#ffffff' : 'var(--accent-blue)',
                                    border: '1px solid ' + (isExpanded ? 'var(--accent-blue)' : 'var(--border-primary)'),
                                    whiteSpace: 'nowrap'
                                  }}
                                >
                                  {isExpanded ? '▼ Hide Graph' : 'View Graph'}
                                </button>
                              </td>
                            </tr>

                            {/* Collapsible Corresponding Graph Card Under Station */}
                            {isExpanded && (
                              <tr style={{background: 'rgba(15, 23, 42, 0.45)', borderBottom: '2px solid var(--accent-blue)'}}>
                                <td colSpan={12} style={{padding: '12px 16px'}}>
                                  <div style={{
                                    background: 'var(--bg-elevated)',
                                    border: '1px solid var(--border-primary)',
                                    borderRadius: 12,
                                    padding: '14px 16px',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: 12,
                                    boxShadow: '0 10px 25px -5px rgba(0,0,0,0.4)'
                                  }}>
                                    {/* Header badge row */}
                                    <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8}}>
                                      <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
                                        <span style={{fontSize: 18}}></span>
                                        <div>
                                          <span style={{fontSize: 18, fontWeight: 800, color: 'var(--text-primary)'}}>
                                            {st.name} Climatological Rainfall Profile &amp; Harmonic Decomposition
                                          </span>
                                          <span style={{fontSize: 15, color: 'var(--text-muted)', marginLeft: 8}}>
                                            CHIRPS 1993–2025 daily climatology
                                          </span>
                                        </div>
                                      </div>
                                      <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
                                        <span style={{
                                          fontSize: 15,
                                          fontWeight: 800,
                                          padding: '3px 8px',
                                          borderRadius: 6,
                                          background: st.reg.includes('Regime 1') ? 'rgba(56, 189, 248, 0.15)' : (st.reg.includes('Regime 2') ? 'rgba(74, 222, 128, 0.15)' : (st.reg.includes('Regime 3') ? 'rgba(251, 191, 36, 0.15)' : 'rgba(148, 163, 184, 0.15)')),
                                          color: st.reg.includes('Regime 1') ? 'var(--r1-text)' : (st.reg.includes('Regime 2') ? 'var(--r2-text)' : (st.reg.includes('Regime 3') ? 'var(--warn-text)' : 'var(--text-meta)')),
                                          border: '1px solid ' + (st.reg.includes('Regime 1') ? 'rgba(56, 189, 248, 0.4)' : (st.reg.includes('Regime 2') ? 'rgba(74, 222, 128, 0.4)' : (st.reg.includes('Regime 3') ? 'rgba(251, 191, 36, 0.4)' : 'rgba(148, 163, 184, 0.4)'))),
                                        }}>
                                          {st.reg}
                                        </span>
                                        <span style={{background: '#10b981', color: '#fff', fontSize: 14, fontWeight: 800, padding: '2px 7px', borderRadius: 10}}>
                                          ✓ 20/20 Verified
                                        </span>
                                      </div>
                                    </div>

                                    {/* Content Flex: Graph Image + Detailed Metrics */}
                                    <div style={{display: 'flex', flexDirection: 'row', flexWrap: 'wrap', gap: 16, alignItems: 'flex-start'}}>
                                      {/* Left: Plot Image */}
                                      <div style={{flex: '1 1 340px', maxWidth: 440, background: '#ffffff', padding: 8, borderRadius: 10, border: '1px solid var(--border-primary)', boxShadow: '0 4px 16px rgba(0,0,0,0.2)'}}>
                                        <img
                                          src={`${import.meta.env.BASE_URL}figures/stations/${st.id}.png`}
                                          alt={`${st.name} diagnostic plot`}
                                          style={{width: '100%', height: 'auto', display: 'block', borderRadius: 6}}
                                        />
                                        <div style={{marginTop: 6, display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 14, color: '#475569'}}>
                                          <span>Bars: Monthly CHIRPS | Lines: H1, H2, H1+H2 Fit</span>
                                          <a href={`${import.meta.env.BASE_URL}figures/stations/${st.id}.png`} target="_blank" rel="noreferrer" style={{color: '#0284c7', fontWeight: 700, textDecoration: 'none'}}>
                                            Open High-Res ↗
                                          </a>
                                        </div>
                                      </div>

                                      {/* Right: Technical Explanation & Metrics */}
                                      <div style={{flex: '1 1 320px', display: 'flex', flexDirection: 'column', gap: 10}}>
                                        {/* Parameter Cards Grid */}
                                        <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 8}}>
                                          <div style={{padding: '8px 10px', background: 'var(--bg-surface)', border: '1px solid var(--border-primary)', borderRadius: 8}}>
                                            <div style={{fontSize: 13, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em'}}>Annual Rainfall (P_ann)</div>
                                            <div style={{fontSize: 20, fontWeight: 800, color: 'var(--text-primary)', marginTop: 2}}>{st.pann} mm</div>
                                            <div style={{fontSize: 13, color: 'var(--text-faint)'}}>Elevation: {st.elev}</div>
                                          </div>
                                          <div style={{padding: '8px 10px', background: 'var(--bg-surface)', border: '1px solid var(--border-primary)', borderRadius: 8}}>
                                            <div style={{fontSize: 13, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em'}}>Harmonic Ratio (r_H)</div>
                                            <div style={{fontSize: 20, fontWeight: 800, color: Number(st.rh) >= 1.0 ? 'var(--warn-text)' : 'var(--r1-text)', marginTop: 2}}>{st.rh}</div>
                                            <div style={{fontSize: 13, color: 'var(--text-faint)'}}>C2 / C1 Ratio</div>
                                          </div>
                                          <div style={{padding: '8px 10px', background: 'var(--bg-surface)', border: '1px solid var(--border-primary)', borderRadius: 8}}>
                                            <div style={{fontSize: 13, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em'}}>Annual Fundamental (C1)</div>
                                            <div style={{fontSize: 20, fontWeight: 800, color: 'var(--accent-text)', marginTop: 2}}>{st.c1} mm</div>
                                            <div style={{fontSize: 13, color: 'var(--text-faint)'}}>365-Day Cycle</div>
                                          </div>
                                          <div style={{padding: '8px 10px', background: 'var(--bg-surface)', border: '1px solid var(--border-primary)', borderRadius: 8}}>
                                            <div style={{fontSize: 13, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em'}}>Semi-Annual Cycle (C2)</div>
                                            <div style={{fontSize: 20, fontWeight: 800, color: 'var(--bad-text)', marginTop: 2}}>{st.c2} mm</div>
                                            <div style={{fontSize: 13, color: 'var(--text-faint)'}}>182.5-Day Cycle</div>
                                          </div>
                                        </div>

                                        {/* Meteorological Rationale */}
                                        <div style={{padding: '10px 12px', background: 'var(--bg-surface)', border: '1px solid var(--border-primary)', borderRadius: 8, fontSize: 15, lineHeight: 1.6, color: 'var(--text-secondary)'}}>
                                          <div style={{fontWeight: 700, color: 'var(--accent-blue)', marginBottom: 4}}>
                                            Meteorological Harmonic Interpretation:
                                          </div>
                                          <div>
                                            {st.rationale}
                                          </div>
                                          <div style={{marginTop: 6, fontSize: 14, color: 'var(--text-muted)'}}>
                                            <strong>Climatological Feature:</strong> {st.desc}
                                          </div>
                                        </div>

                                        {/* Footnote bar */}
                                        <div style={{padding: '6px 10px', background: 'var(--bg-surface)', border: '1px solid var(--border-primary)', borderRadius: 8, fontSize: 13, color: 'var(--text-faint)', display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                                          <span>Req Coord: <strong style={{color: 'var(--text-secondary)'}}>{st.req}</strong> &rarr; Grid Point: <strong style={{color: 'var(--accent-text)'}}>{st.grid} {st.idx}</strong></span>
                                          <button
                                            type="button"
                                            onClick={() => toggleStation(st.id)}
                                            style={{background: 'transparent', border: 'none', color: 'var(--accent-blue)', cursor: 'pointer', fontSize: 14, fontWeight: 700}}
                                          >
                                            ▲ Collapse Graph
                                          </button>
                                        </div>
                                      </div>
                                    </div>
                                  </div>
                                </td>
                              </tr>
                            )}
                          </Fragment>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )
            })()}
          </S>
        </div>
      )}


      {/* SUB-TAB 4: RISK GAUGES & MODELS */}
      {section === 'performance' && (
        <div className="flex flex-col 2xl:flex-row gap-6">
          <div className="w-full 2xl:w-[50%] min-w-0">
            <S title="Operational Risk Gauge Definitions">
              <GaugeDef name="Late Onset Risk" thresh="DOY 89 ~29 March" derivation="Domain-median of CHIRPS CAL t67_onset (67th percentile, CAL years)" justification="Onset later than the upper tercile boundary -- historically the top third of years. Signals delayed planting risk." strength="Statistically grounded, data-derived"/>
              <GaugeDef name="Early Onset Risk" thresh="DOY 78 ~18 March" derivation="Domain-median of CHIRPS CAL t33_onset (33rd percentile, CAL years)" justification="Onset earlier than the lower tercile boundary -- historically the bottom third of years. Signals premature planting risk." strength="Statistically grounded, data-derived"/>
              <GaugeDef name="Very Short Season (LGP &lt; 35d)" thresh="35 days ~5th-10th pctile" derivation="~5th-10th percentile of CHIRPS CAL LGP distribution." justification="Near-complete season failure. Even 60-day sorghum cannot complete grain fill." strength="Agronomic consensus"/>
              <GaugeDef name="Short Season Risk (LGP &lt; 45d)" thresh="45 days ~25th-30th pctile" derivation="~25th-30th percentile of CHIRPS CAL LGP distribution." justification="Lower bound for short-season maize. Below 45 days unlikely to support maize production." strength="Agronomic literature"/>
              <GaugeDef name="Below-Normal Season (LGP &lt; 60d)" thresh="60 days ~50th pctile" derivation="~50th percentile -- a below-median season." justification="Minimum for medium-season maize (60-75 days). Beans and cowpea also at risk." strength="Agronomic literature"/>
              <GaugeDef name="Season Failure" thresh="P(onset = NaN)" derivation="Fraction of ensemble members where A(D) finds no minimum. CHIRPS background failure ~11%." justification="Most unambiguous risk signal. Forecasts above 20-25% carry meaningful signal above climatological baseline." strength="Directly interpretable"/>
              <GaugeDef name="Max Ensemble Agreement" thresh="max(P_BN, P_NN, P_AN)" derivation="Climatological baseline = 33%. Values above 50% indicate majority agreement." justification="Measures ensemble coherence independently of dominant category." strength="Standard probabilistic practice"/>
            </S>
          </div>

          <div className="w-full 2xl:w-[50%] min-w-0">
            <S title="C3S multi-model ensemble (Long Rains): seven seasonal models">
              <div style={{overflowX:'auto'}}>
                <table style={{width:'100%',borderCollapse:'collapse',fontSize:14}}>
                  <thead><tr style={{borderBottom:'1px solid var(--border-primary)'}}>{['Model','Centre','Members','Onset hit rate'].map(h=>(<th key={h} style={{padding:'5px 8px',textAlign:'left',color:'var(--text-muted)',fontWeight:700,letterSpacing:'0.08em',textTransform:'uppercase',fontSize:13,whiteSpace:'nowrap'}}>{h}</th>))}</tr></thead>
                  <tbody>{[['ECMWF SEAS5','ECMWF','25','0.43'],['UKMO GloSea6','Met Office','25','0.41'],['Meteo-France Sys8','Meteo-France','25','0.42'],['DWD GCFS2.1','DWD','25','0.39'],['CMCC-SPS4','CMCC','25','0.38'],['NCEP CFSv2','NCEP','24','0.37'],['ECCC CanSIPS','ECCC','20','0.36']].map(([n,c,m,h],i)=>(<tr key={n} style={{borderBottom:'1px solid var(--border-primary)',background:i%2===0?'transparent':'var(--bg-elevated)'}}><td style={{padding:'5px 8px',color:'var(--text-primary)',fontWeight:600}}>{n}</td><td style={{padding:'5px 8px',color:'var(--text-secondary)'}}>{c}</td><td style={{padding:'5px 8px',color:'var(--text-secondary)',textAlign:'center'}}>{m}</td><td style={{padding:'5px 8px',color:'var(--text-primary)',fontWeight:600}}>{h}</td></tr>))}</tbody>
                </table>
              </div>
            </S>
          </div>
        </div>
      )}

      {section === 'performance' && (
        <div>
              <S title="FAO Water Balance Validation">
                <Tbl head={['Check','Result']} rows={[
                  ['Hindcast agricultural onset vs observed (VAL 2017–2024)', '68% within ±7 days, 81% within ±14 (Oct 01); 79% / 89% with latest obs'],
                  ['Hindcast agricultural cessation vs observed', '40% within ±7 days, 66% within ±14 (Oct 01)'],
                  ['Hindcast agricultural LGP vs observed', 'r = 0.83, 74% within ±14 days (Oct 01)'],
                  ['RPSS (VAL 2017–2024), agricultural definition', 'Onset +0.43, cessation +0.10, LGP +0.34 (Oct 01); +0.60, +0.15, +0.40 with latest obs'],
                  ['Onsets in the GIEWS maize planting window (Oct–Nov)', 'FAO agricultural 66%, FAO rainfall 64%, Agri rule 1 70% (observed 1993–2025)'],
                  ['Bucket PAW/TAW vs ERA5-Land 0–100 cm wetness', 'r = 0.73 (daily, Aug–Feb)'],
                  ['Dekadal ETa vs WaPOR v3 AETI (Oct–Dec 2018–2025)', 'Bias 0.0 mm/day, r = 0.65'],
                ]}/>
                <div style={{fontSize:14, color:'var(--text-muted)', lineHeight:1.5, marginTop:6}}>
                  Full tables: <span style={{fontFamily:"'IBM Plex Mono',monospace"}}>outputs/fao_wb/validation/validation_report.md</span> (python scripts/fao_validate.py).
                </div>
              </S>

          <S title="Limitations">
            <div className="about-prose">
              <ul>
                <li><strong>Skill varies.</strong> Forecast skill depends on location, season, model, method and forecast start. Check the Forecast performance tab for the place and method you use.</li>
                <li><strong>Median dates are summaries.</strong> The median of the members is not a deterministic event date; read it with the range and the probabilities.</li>
                <li><strong>Daily rainfall estimates.</strong> CHIRPS blends satellite and gauge data; CHIRPS v3 daily values are split from 5-day totals, so single days are approximate. The 5–10 day windows the methods use are less affected.</li>
                <li><strong>Season length is not crop suitability.</strong> Only the FAO water balance models a crop (maize by default), with soil properties from a pedotransfer function, a fixed 1 m root zone, no runoff by default and climatological ET0 in the forecast period.</li>
                <li><strong>Adapted rules.</strong> Agri rules 1–3 are adapted from ICPAC’s operational definitions; they are not ICPAC’s own products.</li>
                <li><strong>Latest observations lag.</strong> Preliminary CHIRPS runs several days behind real time, so “+ latest obs” uses observations up to that day.</li>
                <li><strong>Regional scope.</strong> The four rainfall regimes apply to Ethiopia only.</li>
              </ul>
            </div>
          </S>
        </div>
      )}

      {/* SUB-TAB 5: ARCHITECTURE, WORKFLOW & API */}
      {section === 'technical' && (
        <div className="flex flex-col gap-6">
          {/* General Workflow & Scientific Architecture Details */}
          <div className="flex flex-col 2xl:flex-row gap-6">
            <div className="w-full 2xl:w-[50%] min-w-0 flex flex-col gap-4">
              <S title="End-to-End General Workflow">
                <div style={{background:'var(--bg-elevated)', padding:'12px 14px', borderRadius:8, border:'1px solid var(--border-primary)', fontSize:15, lineHeight:1.6, color:'var(--text-secondary)', display:'flex', flexDirection:'column', gap:8}}>
                  <div>
                    <strong style={{color:'var(--accent-blue)'}}>1. Daily Climatology Ingestion:</strong>
                    <div>33-year daily CHIRPS rainfall records (1993–2025) sampled at 0.25° resolution across Ethiopia (1,485 sovereign land pixels) and Kenya (842 pixels).</div>
                  </div>
                  <div>
                    <strong style={{color:'var(--accent-text)'}}>2. Fourier Harmonic Decomposition (Dunning et al. 2016):</strong>
                    <div>Calculates annual fundamental C_1 (365d) and semi-annual harmonic C_2 (182d). Evaluates harmonic ratio <span style={{fontFamily:"'IBM Plex Mono',monospace"}}>r_H = C_2 / C_1</span> (cutoff = 1.0).</div>
                  </div>
                  <div>
                    <strong style={{color:'var(--ok-text)'}}>3. Climatological Regime Partition (ETHIOPIA ONLY):</strong>
                    <div>Combines harmonic ratio with EMI peak-timing criteria (April vs August vs October) to assign every grid cell to one of the 4 disjoint Ethiopian regimes (Regimes 0, 1, 2, 3).</div>
                  </div>
                  <div>
                    <strong style={{color:'var(--warn-text)'}}>4. Dynamic Operational Domain Masking:</strong>
                    <div>Applies agro-climatic thresholds (P_season &ge; 80–120 mm, Seasonality Ratio &ge; 20%) to create active masks. Ensures metrics are never displayed outside climatologically valid zones.</div>
                  </div>
                  <div>
                    <strong style={{color:'var(--pink-text)'}}>5. Anomalous Accumulation Calculation &amp; Products:</strong>
                    <div>Evaluates Dunning cumulative anomaly curve A(D) for individual years and ensemble hindcasts. Detects onset, cessation, and LGP. Outputs web rasters and GIS Shapefiles.</div>
                  </div>
                  <div>
                    <strong style={{color:'var(--violet-text)'}}>6. Agricultural Rules &amp; FAO Water Balance (Kenya Short Rains):</strong>
                    <div>The same observed record and bias-corrected SEAS5 members also run Agri rules 1–3 (rain thresholds, dry-spell checks, Hargreaves PET) and the FAO-56 soil-water balance (CHIRPS v3, ERA5-Land ET0, SoilGrids). Each gives its own onset, cessation, LGP, tercile probabilities and skill. See <em>Onset, Cessation &amp; LGP Methods</em>.</div>
                  </div>
                </div>
              </S>

              <S title="Why there is no unmasked Ethiopia view">
                <div style={{background:'var(--info-bg)', padding:'14px 18px', borderRadius:10, border:'1px solid var(--info-border)', borderLeft:'4px solid var(--accent-blue)', fontSize:15, lineHeight:1.6, color:'var(--text-secondary)'}}>
                  <strong style={{color:'var(--heading)'}}>Why every map is masked:</strong>
                  <div style={{marginTop:4}}>
                    In previous prototypes, users could toggle an &quot;All Ethiopia&quot; unmasked raster view. However, testing showed that running onset/cessation algorithms across regions where the season does not physically occur generates spurious artifacts:
                  </div>
                  <ul style={{marginTop:4, paddingLeft:14, listStyleType:'disc'}}>
                    <li>Calculating <em>Belg</em> onset in Western Ethiopia detects the start of a prolonged 8-month season, not a discrete Belg agricultural window.</li>
                    <li>Calculating <em>Kiremt</em> in southern/southeastern pastoral lowlands searches for monsoon rain during their coldest, driest months, returning random noise.</li>
                  </ul>
                  <div style={{marginTop:4, fontWeight:600, color:'var(--text-primary)'}}>
                    The unmasked option was therefore removed. Maps are shown only inside the climatological domain of each season.
                  </div>
                </div>
              </S>
            </div>

            <div className="w-full 2xl:w-[50%] min-w-0 flex flex-col gap-4">
              <S title="Technical Stack & Architecture">
                <KV label="Frontend Engine" value="React 18 + Vite + Tailwind CSS + MapLibre GL JS; Inter (text) and IBM Plex Mono (formulas)"/>
                <KV label="Data Visualization" value="Recharts custom SVG plume charts + Taylor diagrams"/>
                <KV label="Backend Engine" value="FastAPI + Uvicorn + NumPy + Xarray + SciPy"/>
                <KV label="Raster Delivery" value="Pre-computed GeoJSON Grid + Cached demo_data.npz (73.2 MB)"/>
                <KV label="GIS Products" value="ESRI Shapefiles (.shp, .shx, .dbf, .prj) + GeoJSON (WGS 84 EPSG:4326)"/>
                <KV label="Hosting / Runtime" value="Uvicorn ASGI port 8765, local/cloud scalable"/>
              </S>

              <S title="REST API Endpoints">
                <KV label="GET /grid" value="Fetch spatial GeoJSON grid filtered by variable, season &amp; regime mask" mono/>
                <KV label="GET /pixel" value="Extract ensemble plumes, A(D) curves &amp; statistics for clicked coordinate" mono/>
                <KV label="GET /chirps_historical" value="Extract 33-year CHIRPS observed onset/cessation time series" mono/>
                <KV label="GET /validation" value="Fetch C3S hindcast skill validation metrics (Hit-Rate, RPSS)" mono/>
                <KV label="GET /health" value="System status, active models loaded, and memory envelope" mono/>
              </S>

              <S title="Institutional Leadership & Contacts">
                <KV label="Project Lead" value="Dr. Teferi Demissie (ILRI)  |  t.demissie@cgiar.org" mono/>
                <KV label="Technical Lead" value="Yonas Mersha (ILRI)  |  y.mersha@cgiar.org" mono/>
                <KV label="Host Institution" value="International Livestock Research Institute (ILRI), Addis Ababa, Ethiopia"/>
                <KV label="Partner Agencies" value="ICPAC, Ethiopian Meteorological Institute (EMI), Kenya Meteorological Department (KMD)"/>
              </S>

              <S title="Recommended Citation">
                <div style={{background:'var(--bg-elevated)', padding:'8px 12px', borderRadius:8, border:'1px solid var(--border-primary)', fontSize:14, lineHeight:1.5, color:'var(--text-secondary)'}}>
                  <div style={{fontFamily:"'IBM Plex Mono',monospace", color:'var(--accent-text)'}}>
                    Demissie, T., Mersha, Y., et al. (2026). Operational Multi-Model Seasonal Climate Forecast System for Onset, Cessation, and Length of Growing Period in Eastern Africa (v{version}). ILRI / ICPAC.
                  </div>
                </div>
              </S>
            </div>
          </div>
        </div>
      )}
       </article>
      </div>
     </div>
    </div>
  )
}
