import React, { Fragment, useEffect, useRef, useState } from 'react'
import { Info, Database, CalendarRange, Map as MapIcon, ShieldCheck, FileCode2, ChevronRight, ExternalLink, Copy, Check } from 'lucide-react'
import { version } from '../../package.json'
import CropWorkflowDiagram from './CropWorkflowDiagram'

// Public method documents (main branch). `updated` is the date of the last commit to each file on main.
const REPO_BLOB = 'https://github.com/YonSci/-Operational-Multi-Model-Seasonal-Forecasting-System/blob/main/'
const DOCS = {
  fao:    { file: 'FAO_WATER_BALANCE_METHOD.md',         updated: '2026-11-03' },
  readme: { file: 'README.md',                           updated: '2026-11-03' },
  octRun: { file: 'ECMWF_SEAS5_OCTOBER_PIPELINE.md',     updated: '2026-10-28' },
  kiremt: { file: 'ECMWF_SEAS5_ETHIOPIA_KIREMT_PIPELINE.md', updated: '2026-09-17' },
  crop:   { file: 'CROP_ENGINE.md',                      updated: '2026-11-06' },
}
const docUrl = (doc, anchor) => REPO_BLOB + doc.file + (anchor ? '#' + anchor : '')
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const fmtDate = iso => { const [y, m, d] = iso.split('-').map(Number); return `${d} ${MONTHS[m - 1]} ${y}` }
const docMeta = doc => `${doc.file} · updated ${fmtDate(doc.updated)}`

// Official dataset pages and the scientific reference
const EXT = {
  chirps:    'https://www.chc.ucsb.edu/data/chirps',
  era5land:  'https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land',
  soilgrids: 'https://soilgrids.org',
  c3s:       'https://cds.climate.copernicus.eu/datasets/seasonal-original-single-levels',
  dunning:   'https://doi.org/10.1002/2016JD025428',
}
const DUNNING_REF = 'Dunning, C. M., Black, E. C. L., & Allan, R. P. (2016). The onset and cessation of seasonal rainfall over Africa. Journal of Geophysical Research: Atmospheres, 121, 11,405–11,424.'
const CITATION = `Demissie, T., Mersha, Y., et al. (2026). Operational Multi-Model Seasonal Climate Forecast System for Onset, Cessation, and Length of Growing Period in Eastern Africa (v${version}). ILRI / ICPAC.`

// Seasonal forecast systems combined for the Kenya Long Rains (About > Data & coverage).
// Names follow the platform's model labels (backend/mam_loader.py); members are those used on the platform.
// `hr` is the Long Rains onset hit rate (About > Performance & limitations).
const C3S_MODELS = [
  { system: 'ECMWF SEAS5',           centre: 'European Centre for Medium-Range Weather Forecasts (ECMWF)',                  members: '25', hindcast: '1981–2016', hr: '0.43', vsChance: '+0.10' },
  { system: 'UKMO GloSea6',          centre: 'Met Office, United Kingdom (UKMO)',                                          members: '25', hindcast: '1993–2016', hr: '0.41', vsChance: '+0.08' },
  { system: 'Meteo-France System 8', centre: 'Météo-France',                                                               members: '25', hindcast: '1993–2016', hr: '0.42', vsChance: '+0.09' },
  { system: 'DWD GCFS2.1',           centre: 'Deutscher Wetterdienst, Germany (DWD)',                                      members: '25', hindcast: '1993–2016', hr: '0.39', vsChance: '+0.06' },
  { system: 'CMCC SPS4',             centre: 'Euro-Mediterranean Center on Climate Change, Italy (CMCC)',                  members: '25', hindcast: '1993–2016', hr: '0.38', vsChance: '+0.05' },
  { system: 'NCEP CFSv2',            centre: 'NOAA National Centers for Environmental Prediction, United States (NCEP)',   members: '24', hindcast: '1993–2016', hr: '0.37', vsChance: '+0.04' },
  { system: 'ECCC CanSIPS',          centre: 'Environment and Climate Change Canada (ECCC)',                               members: '20', hindcast: '1993–2016', hr: '0.36', vsChance: '+0.03' },
]
// Near real-time rainfall tracking inputs (see public/tracker/data/products.csv for the live latency of each)
const TRACKER_ROLE = 'Rainfall since 1 September at monitored sites; compared with CHIRPS for bias, correlation and rain detection'
const SATELLITE_INFO = [
  { name: 'CHIRPS 2.0', provider: 'UC Santa Barbara Climate Hazards Center', resolution: '0.05°, used at 0.25°', latency: 'Preliminary ~2–5 days; final ~3 weeks after the month',
    method: 'Satellite infrared rainfall blended with rain-gauge reports, 1981 to present',
    use: 'Reference for the whole platform: climatology, bias correction and verification. Preliminary daily files fill the days after the last complete month' },
  { name: 'ARC2', provider: 'NOAA Climate Prediction Center (FEWS NET)', resolution: '0.1°', latency: '~1–2 days',
    method: 'Africa Rainfall Climatology version 2: Meteosat infrared cloud-top temperatures merged with daily rain-gauge reports', use: TRACKER_ROLE },
  { name: 'TAMSAT v3.1', provider: 'University of Reading', resolution: '0.0375°', latency: '~2–5 days',
    method: 'Meteosat thermal-infrared cold-cloud duration, calibrated against historical gauges; Africa only', use: TRACKER_ROLE },
  { name: 'PDIR-Now', provider: 'UC Irvine Center for Hydrometeorology and Remote Sensing', resolution: '0.04°', latency: '~1 day',
    method: 'Rainfall estimated from infrared imagery by a neural network (PERSIANN family); near-global; no gauge correction', use: TRACKER_ROLE },
  { name: 'IMERG Late and Early (V07)', provider: 'NASA Global Precipitation Measurement (GPM)', resolution: '0.1°', latency: 'Early ~1 day; Late ~1–2 days',
    method: 'Passive-microwave rainfall from the GPM satellite constellation, gaps filled from infrared. The Late run includes more microwave overpasses; the Early run is issued sooner', use: TRACKER_ROLE },
]
const SATELLITE_FIELDS = [['provider', 'Provider'], ['resolution', 'Resolution'], ['latency', 'Latency'], ['method', 'Method'], ['use', 'Used for']]
const NWP_INFO = [
  { name: 'ECMWF IFS (HRES)', provider: 'ECMWF', resolution: '0.25°', range: '15 days', source: 'ECMWF open data', notes: 'Deterministic global forecast' },
  { name: 'ECMWF ensemble (ENS)', provider: 'ECMWF', resolution: '0.25°', range: '15 days', notes: '51 members. The maps show the member median; the chances of planting rains use the 50 perturbed members' },
  { name: 'GFS', provider: 'NOAA National Centers for Environmental Prediction', resolution: '0.25°', range: '16 days', notes: 'US Global Forecast System' },
  { name: 'GDPS (GEM)', provider: 'Environment and Climate Change Canada', resolution: '15 km', range: '10 days', notes: 'Global Deterministic Prediction System, run with the GEM model' },
  { name: 'ICON', provider: 'Deutscher Wetterdienst (DWD)', resolution: '13 km', range: '7.5 days', source: 'DWD open-data server', notes: 'ICOsahedral Nonhydrostatic global model' },
  { name: 'UKMO Global', provider: 'Met Office', resolution: '10 km', range: '7 days', source: 'AWS open data', notes: 'Unified Model global deterministic forecast' },
]
const NWP_FIELDS = [['provider', 'Provider'], ['resolution', 'Resolution'], ['range', 'Forecast range'], ['source', 'Data source'], ['notes', 'Notes']]

// ── Presentational helpers (module level so that re-renders keep <details> state) ──
const Scope = ({ children }) => (<p className="about-scope"><span className="about-scope-key">Applies to</span><span>{children}</span></p>)
const S = ({title,children,id,scope})=>(<section id={id} className="about-block"><h3>{title}</h3>{scope && <Scope>{scope}</Scope>}{children}</section>)
const Disclosure = ({ title, scope, children }) => (
  <details className="about-disclosure">
    <summary><ChevronRight className="about-disclosure-chevron" size={18} aria-hidden="true" /><span>{title}</span></summary>
    <div className="about-disclosure-body">{scope && <Scope>{scope}</Scope>}{children}</div>
  </details>
)
const ExtLink = ({ href, children }) => (<a className="about-extlink" href={href} target="_blank" rel="noopener noreferrer">{children}<ExternalLink size={14} aria-hidden="true" /><span className="sr-only"> (opens in a new tab)</span></a>)
const DocLinks = ({ children }) => (<ul className="about-doclinks">{children}</ul>)
const DocLink = ({ action, title, href, meta }) => (
  <li className="about-doclink">
    <a href={href} target="_blank" rel="noopener noreferrer">
      <span className="about-doclink-action">{action}<ExternalLink size={15} aria-hidden="true" /></span>
      <span className="about-doclink-title">{title}</span>
      {meta && <span className="about-doclink-meta">{meta}</span>}
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  </li>
)
const SpecList = ({ items, fields }) => (
  <div className="about-specs">{items.map(it => (
    <div key={it.name} className="about-spec">
      <h4>{it.name}</h4>
      <dl>{fields.filter(([k]) => it[k]).map(([k, label]) => (<div key={k}><dt>{label}</dt><dd>{it[k]}</dd></div>))}</dl>
    </div>))}
  </div>
)
const Tbl = ({head,rows})=>(<div style={{overflowX:'auto'}}><table style={{width:'100%',borderCollapse:'collapse',fontSize:15}}><thead><tr style={{borderBottom:'2px solid var(--border-primary)'}}>{head.map(h=>(<th key={h} scope="col" style={{padding:'8px 10px',textAlign:'left',color:'var(--text-meta)',fontWeight:600,fontSize:14,whiteSpace:'nowrap'}}>{h}</th>))}</tr></thead><tbody>{rows.map((r,i)=>(<tr key={i} style={{borderBottom:'1px solid var(--border-primary)'}}>{r.map((c,j)=>(<td key={j} style={{padding:'10px',color:j===0?'var(--heading)':'var(--text-body)',fontWeight:j===0?600:400,lineHeight:1.6,verticalAlign:'top',minWidth:j===0?140:120}}>{c}</td>))}</tr>))}</tbody></table></div>)
const KV = ({label,value,wide=false})=>(<div style={{display:'flex',flexWrap:'wrap',gap:'2px 16px',padding:'10px 0',borderBottom:'1px solid var(--border-primary)'}}><span style={{flex:`0 0 ${wide?240:200}px`,fontSize:14,fontWeight:600,color:'var(--text-meta)',lineHeight:1.6,fontFamily:label.startsWith('GET ')?"'IBM Plex Mono',monospace":'inherit'}}>{label}</span><span style={{flex:'1 1 320px',minWidth:0,fontSize:16,color:'var(--text-body)',lineHeight:1.65}}>{value}</span></div>)
const Step = ({n,title,eq,desc,table})=>(
  <div style={{display:'flex',gap:14,marginBottom:24,alignItems:'flex-start'}}>
    <div style={{flexShrink:0,width:30,height:30,borderRadius:'50%',display:'flex',alignItems:'center',justifyContent:'center',fontSize:14,fontWeight:700,background:'var(--btn-primary)',color:'#fff',marginTop:1}}>{n}</div>
    <div style={{flex:1,minWidth:0}}>
      <h4 style={{fontSize:18,fontWeight:600,color:'var(--heading)',margin:'0 0 6px',lineHeight:1.4}}>{title}</h4>
      {eq&&<div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:15,color:'var(--heading)',background:'var(--bg-elevated)',border:'1px solid var(--border-primary)',borderRadius:8,padding:'10px 14px',marginBottom:8,overflowX:'auto',whiteSpace:'pre'}}>{eq}</div>}
      {desc&&<p style={{fontSize:16,color:'var(--text-body)',lineHeight:1.7,margin:table?'0 0 8px':0}}>{desc}</p>}
      {table&&(<div style={{overflowX:'auto',marginTop:4}}><table style={{borderCollapse:'collapse',fontSize:15,width:'100%'}}>
        {table.some(r=>r.length>2)&&<thead><tr style={{borderBottom:'1px solid var(--border-primary)'}}>{['Term','Meaning','Unit'].map(h=><th key={h} style={{padding:'5px 10px',textAlign:'left',fontSize:13,fontWeight:600,color:'var(--text-meta)'}}>{h}</th>)}</tr></thead>}
        <tbody>{table.map(([sym,def,unit],i)=>(<tr key={i} style={{borderBottom:'1px solid var(--border-primary)'}}><td style={{padding:'7px 10px',fontFamily:"'IBM Plex Mono',monospace",fontSize:14,color:'var(--accent-text)',whiteSpace:'nowrap',verticalAlign:'top'}}>{sym}</td><td style={{padding:'7px 10px',color:'var(--text-body)',lineHeight:1.6}}>{def}</td>{unit!==undefined&&<td style={{padding:'7px 10px',color:'var(--text-body)',whiteSpace:'nowrap',verticalAlign:'top'}}>{unit}</td>}</tr>))}</tbody></table></div>)}
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

// Recommended citation with a copy button: Clipboard API, then execCommand, then select the text for a manual copy
function CopyCitation({ text }) {
  const [status, setStatus] = useState('idle')
  const textRef = useRef(null)
  const timer = useRef(null)
  useEffect(() => () => clearTimeout(timer.current), [])
  const legacyCopy = () => {
    try {
      const ta = document.createElement('textarea')
      ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.top = '0'; ta.style.opacity = '0'
      document.body.appendChild(ta); ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      return ok
    } catch { return false }
  }
  const selectText = () => {
    const el = textRef.current, sel = window.getSelection?.()
    if (!el || !sel) return
    const range = document.createRange(); range.selectNodeContents(el); sel.removeAllRanges(); sel.addRange(range)
  }
  const copy = async () => {
    let ok = false
    try { if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(text); ok = true } } catch { ok = false }
    if (!ok) ok = legacyCopy()
    if (!ok) selectText()
    setStatus(ok ? 'copied' : 'failed')
    clearTimeout(timer.current)
    if (ok) timer.current = setTimeout(() => setStatus('idle'), 3000)
  }
  return (
    <div className="about-cite">
      <p ref={textRef} className="about-cite-text">{text}</p>
      <div className="about-cite-actions">
        <button type="button" className="about-btn" data-state={status} onClick={copy}>
          {status === 'copied' ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
          {status === 'copied' ? 'Copied' : 'Copy citation'}
        </button>
        <span className="about-cite-status" role="status" aria-live="polite">
          {status === 'copied' ? 'Citation copied to the clipboard.' : status === 'failed' ? 'Copying is not available here. The citation is selected; press Ctrl+C (⌘C on a Mac) to copy it.' : ''}
        </span>
      </div>
    </div>
  )
}

export default function AboutTab({ initial, section: sectionProp, onSectionChange }) {
  const [section, setSection] = useState(sectionProp ?? initial?.section ?? 'overview')
  const scrollRef = React.useRef(null)
  useEffect(() => { if (sectionProp && sectionProp !== section) setSection(sectionProp) }, [sectionProp])
  const go = id => { setSection(id); onSectionChange?.(id); scrollRef.current?.scrollTo({ top: 0 }) }
  // Opened from a landing-page card: jump to the block it points at
  useEffect(() => { if (initial?.anchor) document.getElementById(initial.anchor)?.scrollIntoView({ block: 'start' }) }, [])

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
        <p className="about-lede">The Onset–Cessation–SL Forecast System (OCL-FS) helps users explore the timing and uncertainty of rainfall seasons in Kenya and Ethiopia.</p>
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
          <h3 id="about-timescales">Forecast timescales and rainfall tracking</h3>
          <p>
            Forecasts cover three timescales, from the whole season ahead to the next one to two weeks, and near real-time rainfall tracking shows
            the rain that has already fallen. Choose the timescale with the Forecast selector in the Forecast tab. For the Kenya Short Rains the
            sub-seasonal and medium-range forecasts are joined to the seasonal forecast, so all three give onset, end of rains and season length
            with every method (see Forecast runs with weather forecasts under <Link to="methods">Forecast methods</Link>).
          </p>
          <Tbl head={['Timescale','Range','Models and data','What it gives','Where']} rows={[
            ['Seasonal', 'The whole season, from forecast starts months ahead', 'ECMWF SEAS5; seven C3S models for the Kenya Long Rains',
             'Onset, cessation and season length with probabilities and skill, for every country and season', 'Forecast tab › Seasonal'],
            ['Sub-seasonal', 'Weeks 2–6 (to about 46 days)', 'ECMWF ENS + extended range; NOAA GEFS 35-day',
             'The forecast joined to the seasonal forecast: onset, end of rains and season length with every method; a new run every day', 'Forecast tab › Sub-seasonal forecasts (Kenya Short Rains)'],
            ['Medium-range', '7–16 days', 'ECMWF IFS (HRES), ECMWF ENS, GFS, GDPS, ICON, UKMO Global',
             'Daily rainfall maps, and the forecast joined to the seasonal forecast with every method; a new run every day', 'Forecast tab › Medium-range forecasts (Kenya Short Rains)'],
            ['Near real-time rainfall tracking', 'Rain so far, one to five days behind real time', 'CHIRPS preliminary, ARC2, TAMSAT, PDIR-Now, IMERG; the medium-range models for the outlook',
             'Rain since 1 September at monitored sites, checked against CHIRPS, with the next 7–16 days', 'Near real-time rainfall tracking tab (Kenya Short Rains)'],
          ]}/>
          <p>
            Data sources are listed under <Link to="data">Data &amp; coverage</Link>: satellite rainfall products and medium-range weather forecasts.
          </p>

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
          <S title="Countries and seasons" id="about-seasons" scope="Kenya and Ethiopia · all seasons · 0.25° grid">
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
          <S title="Datasets" scope="Kenya and Ethiopia · all seasons · 0.25° grid">
            <Tbl head={['Dataset','Used for','Resolution','Period']} rows={[
              ['CHIRPS v2 daily rainfall', 'Observed onset, cessation and season length; terciles; bias correction of the forecasts', '0.25°', '1981 on (Long Rains), 1993 on (other seasons)'],
              ['CHIRPS v3 daily rainfall', 'FAO water balance: observations, terciles and its own bias correction', '0.05°, averaged to 0.25°', '1993 on'],
              ['ECMWF SEAS5 and C3S seasonal models', 'Seasonal forecasts and hindcasts (25 members for SEAS5); forecast temperature and March rain of the crop outlook (SEAS5 1 Oct runs to 31 Mar, bias-corrected to ERA5-Land and CHIRPS)', 'Regridded to 0.25°', 'SEAS5 hindcasts from 1981 (Long Rains) or 1993; other C3S models from 1993'],
              ['ERA5-Land', 'FAO-56 reference evapotranspiration (ET0) and starting soil moisture; site temperature, solar radiation, humidity and wind of the crop outlook', '0.1°, averaged to 0.25° (crop sites: the 0.1° cell)', '1993 on'],
              ['SoilGrids 2.0', 'Soil water-holding capacity for the FAO water balance', '~1 km, averaged to 0.25°', 'Static'],
              ['Satellite rainfall and 10–15 day forecasts', 'Near real-time rainfall tracking at monitored sites; sub-seasonal and medium-range forecasts', 'Site', 'Current season'],
            ]}/>
            <h4 className="about-subhead">Open dataset documentation</h4>
            <DocLinks>
              <DocLink action="Open dataset documentation" title="CHIRPS daily rainfall (v2 and v3)" href={EXT.chirps} meta="UC Santa Barbara Climate Hazards Center" />
              <DocLink action="Open dataset documentation" title="ERA5-Land reanalysis" href={EXT.era5land} meta="Copernicus Climate Data Store" />
              <DocLink action="Open dataset documentation" title="SoilGrids 2.0" href={EXT.soilgrids} meta="soilgrids.org" />
              <DocLink action="Open dataset documentation" title="C3S seasonal forecasts, single levels (incl. ECMWF SEAS5)" href={EXT.c3s} meta="Copernicus Climate Data Store" />
            </DocLinks>
          </S>
          <S title="Seasonal forecast models" id="about-models" scope="Kenya · Long Rains · forecast start 1 Feb · seven C3S models">
            <p className="about-intro">
              The Kenya Long Rains outlooks use seven seasonal forecast systems from the Copernicus Climate Change Service (C3S), shown singly and
              combined according to their past skill. The other seasons use ECMWF SEAS5.
            </p>
            <dl className="about-facts">
              <div><dt>Products used</dt><dd>Daily precipitation, bias-corrected to CHIRPS with empirical quantile mapping on the 0.25° grid</dd></div>
              <div><dt>Forecast start</dt><dd>1 February (Kenya Long Rains)</dd></div>
              <div><dt>Official source</dt><dd><ExtLink href={EXT.c3s}>C3S seasonal forecast data on single levels</ExtLink> (Copernicus Climate Data Store)</dd></div>
            </dl>
            <Tbl head={['System (as named on this platform)','Forecasting centre','Members used','Hindcast period']}
              rows={C3S_MODELS.map(m => [m.system, m.centre, m.members, m.hindcast])}/>
            <p className="about-note">
              System names are the labels used in the dashboard’s model selector. The C3S dataset page lists the forecast systems that each centre
              provides.
            </p>
          </S>
          <S title="Satellite rainfall products" id="about-satellite" scope="Kenya · Near real-time rainfall tracking · monitored sites · from 1 Sep">
            <p className="about-intro">
              Near real-time rainfall tracking shows how much rain has fallen at each monitored site since 1 September, from five satellite products downloaded
              every day and placed on the 0.25° grid. Each product is compared with CHIRPS for bias, correlation and rain detection.
            </p>
            <SpecList items={SATELLITE_INFO} fields={SATELLITE_FIELDS}/>
          </S>
          <S title="Medium-range weather forecasts" id="about-nwp" scope="Kenya · Near real-time rainfall tracking and Forecast tab › Medium-range forecasts · next 7–16 days">
            <p className="about-intro">
              The outlook for the next one to two weeks in near real-time rainfall tracking comes from six global weather models, taken each day from the 00 UTC run published by
              each centre. A model that cannot be reached is filled from Open-Meteo. Forecast range is 7 to 16 days depending on the model. In the
              Forecast tab each model's daily run is also joined to the seasonal forecast, so onset, end of rains and season length can be read
              with every method (see Forecast runs with weather forecasts under Methods).
            </p>
            <SpecList items={NWP_INFO} fields={NWP_FIELDS}/>
          </S>
          <S title="Reference periods and updates" scope="Kenya and Ethiopia · all seasons">
            <KV label="Calibration" value="Hindcast years up to 2016: 1981–2016 for the Long Rains (36 years), 1993–2016 for the Short Rains and the Ethiopia seasons (24 years). Terciles, bias correction and probability calibration use these years."/>
            <KV label="Validation" value="Independent years after calibration; 2017–2024 for the Short Rains methods."/>
            <KV label="Observed record" value="CHIRPS 1993–2025 for the Short Rains historical view and the Ethiopia regime diagnostics; 1981 on for the Long Rains."/>
            <KV label="Reference normal" value="WMO standard normal 1991–2020, for climatological context."/>
            <KV label="Grid and land masks" value="0.25° analysis grid; 842 land cells in Kenya and 1,485 in Ethiopia. Ethiopia maps are shown only inside each season’s climatological domain."/>
            <KV label="Updates" value="The Short Rains run with the latest observations, the sub-seasonal and medium-range forecast runs and near real-time rainfall tracking are refreshed daily. Other seasons are updated when a new forecast is processed."/>
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
            <S title="Two-Stage Classification Blueprint" scope="Ethiopia · rainfall regimes · CHIRPS 1993–2025 daily climatology">
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
            <S title="The Four Objective Climate Regimes" scope="Ethiopia · 0.25° grid · 1,485 land cells">
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

            <S title="Operational Mask Arithmetic vs Regime Eligibility" scope="Ethiopia · Kiremt (JJAS) monsoon domain">
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

      {section === 'regimes' && <><h3 style={{margin:'8px 0 16px'}}>Regime and season maps, GIS files</h3><Scope>Ethiopia · 0.25° grid · season domains</Scope></>}
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

      {/* SUB-TAB 3: 20-SITE AUDITED DIAGNOSTIC AGREEMENT */}
      {section === 'regimes' && (
        <div className="w-full flex flex-col gap-4">
          <S title="Audited 20-Site Representative Diagnostic Consistency Check" scope="Ethiopia · 20 sites · CHIRPS 1993–2025 daily climatology">
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

      {section === 'methods' && (
        <div>
          <p className="about-intro">
            The Kenya Short Rains can be estimated with five methods; the Long Rains and the Ethiopia seasons use the Dunning method. The methods ask
            different questions, so their onset, cessation and season length are not interchangeable. For the Short Rains, pick a method with
            the <strong>Method</strong> selector above the map: the maps, probabilities, skill, charts and bulletin all follow it.
          </p>

          <section className="about-block">
            <h3>The three approaches in plain language</h3>
            <div className="about-explain">
              <div className="about-explain-card">
                <span className="about-explain-kicker">Dunning</span>
                <h4>Rainfall pattern</h4>
                <p>
                  Adds up, day by day, how far rainfall is above or below the usual daily amount for the season at that place. The season starts on the
                  day after this running total stops falling and starts climbing, and ends when it stops climbing. It marks the turning points of the
                  season’s rainfall, not the day a crop can be planted.
                </p>
                <p className="about-explain-meta">Used for every season in Kenya and Ethiopia.</p>
                <div className="about-explain-links">
                  <ExtLink href={docUrl(DOCS.readme, 'scientific-methodology')}>Read the method</ExtLink>
                  <ExtLink href={EXT.dunning}>View the scientific reference</ExtLink>
                </div>
              </div>
              <div className="about-explain-card">
                <span className="about-explain-kicker">Agri rules 1–3</span>
                <h4>Planting-rain rules</h4>
                <p>
                  Look for the first rains heavy enough to plant on that are not followed by a long dry spell. The three rules differ in how much rain
                  they need over how many days and in how long a dry spell they allow afterwards. The season ends when rain stays well below the
                  evaporative demand.
                </p>
                <p className="about-explain-meta">Kenya Short Rains. Adapted from ICPAC’s operational definitions.</p>
                <div className="about-explain-links">
                  <ExtLink href={docUrl(DOCS.octRun)}>Read the method</ExtLink>
                </div>
              </div>
              <div className="about-explain-card">
                <span className="about-explain-kicker">FAO water balance</span>
                <h4>Crop and soil water</h4>
                <p>
                  Keeps a daily account of the water in a maize crop’s root zone: rain fills it, the crop and the soil draw it down. The season starts
                  when the rains are steady and the soil holds enough water for the crop, and ends when the crop runs short of water.
                </p>
                <p className="about-explain-meta">Kenya Short Rains, 1 October runs. Gives three season lengths, one per definition.</p>
                <div className="about-explain-links">
                  <ExtLink href={docUrl(DOCS.fao)}>Read the method</ExtLink>
                </div>
              </div>
            </div>
          </section>

          <section className="about-block">
            <h3>Thresholds, equations and configurations</h3>
            <p className="about-note" style={{marginTop:0, marginBottom:16}}>Select a heading to show or hide the details.</p>

            <Disclosure title="Onset and cessation rules of the five methods" scope="Kenya · Short Rains (OND) · Dunning, Agri rules 1–3, FAO water balance">
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
            </Disclosure>

            <Disclosure title="Forecast runs (Forecast tab)" scope="Kenya · Short Rains · ECMWF SEAS5, 25 members">
                <Tbl head={['Run','Rainfall used','Methods']} rows={[
                  ['Sep 01', 'ECMWF SEAS5 from 1 Sep, to 31 Dec', 'Dunning, Agri rules 1–3'],
                  ['Oct 01', 'ECMWF SEAS5 from 1 Oct, to 28 Feb', 'Dunning, Agri rules 1–3, FAO water balance'],
                  ['Oct 01 + Sep obs', 'Observed CHIRPS for September, then SEAS5 from 1 Oct', 'Dunning, Agri rules 1–3'],
                  ['Oct 01 + latest obs', 'Observed CHIRPS to the latest available day, then SEAS5; refreshed by the daily update', 'Dunning, Agri rules 1–3, FAO water balance'],
                ]}/>
                <div style={{fontSize:14, color:'var(--text-muted)', lineHeight:1.5, marginTop:6}}>
                  25 SEAS5 members, each bias-corrected day by day and cell by cell with empirical quantile mapping (EQM) against CHIRPS. Days before a run's forecast start are observed CHIRPS, in the hindcast years too. Picking a method that the selected run does not have switches to the latest run that has it.
                </div>
                <div style={{fontSize:14, color:'var(--text-muted)', lineHeight:1.5, marginTop:6}}>
                  <strong>Issued runs keep their original correction.</strong> On 1 Nov 2026 the quantile mapping was fixed so that, where SEAS5 has more wet days than CHIRPS, the surplus days become dry: before, they kept a trace of rain (over land, 26 Oct – 31 Dec, the corrected members had rain on 70% of days against 26% in CHIRPS; now 26%). Rain above 1 mm, seasonal totals (−2%) and onset and cessation skill barely changed. The Sep 01, Oct 01 and Oct 01 + Sep obs runs (Dunning and Agri rules) are shown as issued, with the earlier correction. The runs refreshed daily (Oct 01 + latest obs, the forecast runs with weather forecasts) and the FAO water balance use the fixed correction.
                </div>
            </Disclosure>

            <Disclosure title="Forecast runs with weather forecasts (Forecast tab › Sub-seasonal and Medium-range)" scope="Kenya · Short Rains · one run per model and day · experimental">
                <div style={{fontSize:14, color:'var(--text-muted)', lineHeight:1.5, marginBottom:6}}>
                  Each run takes the 25 members of Oct 01 + latest obs and joins one weather model's forecast from its run date: observed CHIRPS to the
                  latest available day, then the days before the run from the ECMWF extended-range run started that day (lead day 1), then the
                  model's forecast, then each SEAS5 member to the end of the season. Every method (Dunning, Agri rules 1–3, FAO water balance) is
                  run on the joined rainfall for 2026; terciles, the calibration of the probabilities and the skill are those of Oct 01 + latest
                  obs, whose hindcasts the runs share. Each day's run of each model is kept, so earlier runs can be compared (Forecast run).
                </div>
                <Tbl head={['Model','Forecast joined in','Members']} rows={[
                  ['ECMWF ENS + extended range (Sub-seasonal)', 'ECMWF ENS days 1–15 (open data, 0.25°), then the ECMWF extended range to day 46 (dynamical.org, 1.5°)', 'ENS member k → member k; 25 of the 100 extended-range members, matched to the SEAS5 members by rank of rainfall'],
                  ['NOAA GEFS 35-day (Sub-seasonal)', 'NOAA GEFS to day 35 (dynamical.org, 0.25°)', '25 of the 31 members, matched by rank of rainfall'],
                  ['ECMWF ENS (Medium-range)', 'ECMWF ENS days 1–15', 'ENS member k → member k'],
                  ['ECMWF IFS (HRES), GFS, GDPS, ICON, UKMO Global (Medium-range)', 'The model’s 00 UTC run, 7–16 days (0.5° cells)', 'The same forecast in every member'],
                ]}/>
                <div style={{fontSize:14, color:'var(--text-muted)', lineHeight:1.5, marginTop:6}}>
                  Bias correction against CHIRPS: the ECMWF extended range by lead with ECMWF’s extended-range reforecasts (20 past years); all other
                  forecasts provisionally with the SEAS5 quantile mapping for the same day. The FAO water balance keeps its own CHIRPS v3-corrected
                  SEAS5 members and takes the weather forecasts on the days they cover. These runs have not yet been tested on past seasons. Before
                  3 Nov 2026 the ECMWF ENS + extended-range run (Dunning and Agri rules only) was a separate experimental run; the archive was rebuilt
                  from the forecasts on disk with the observations of the time (to 25 Oct).
                </div>
                <div style={{fontSize:14, color:'var(--text-muted)', lineHeight:1.5, marginTop:6}}>
                  A day the daily update misses is filled in afterwards, up to six days back: ECMWF ENS from ECMWF’s cloud copies of its open data,
                  GEFS from dynamical.org, and the medium-range models from Open-Meteo’s archive of past runs (each day’s 00 UTC run as issued; the
                  value at the 0.5° cell centre rather than the mean over the cell, so slightly different from a direct download). Filled this way:
                  27, 29 and 30 Oct for the medium-range models, and UKMO Global on 1 Nov.
                </div>
            </Disclosure>

            <Disclosure title="Probabilities, skill and missing dates" scope="Kenya · Short Rains · CAL 1993–2016 · VAL 2017–2024">
                <KV label="Terciles" value="Early / normal / late (short / normal / long for LGP) from the 33rd and 67th percentiles of the observed record at each cell (CAL 1993–2016): CHIRPS v2 for Dunning and the Agri rules, CHIRPS v3 for FAO."/>
                <KV label="Probabilities" value="Share of members in each tercile, calibrated with the damping factor α fitted on the hindcasts (CAL 1993–2016)."/>
                <KV label="Skill" value="RPSS and hit rate on the independent validation years (VAL 2017–2024). RPSS > 0 beats climatology."/>
                <KV label="No onset / cessation" value="A member with none by the search end counts as later than any date, not as missing, so medians and terciles stay honest in failed seasons. Season length is 0 without onset."/>
                <KV label="Flat terciles (FAO)" value="Where the observed record has no spread (33rd = 67th percentile), no tercile forecast is issued: probabilities and skill are left blank (western Kenya and the coast, where onset falls on the first search day)."/>
            </Disclosure>

            <Disclosure title="Dunning cumulative anomaly: the eight steps" scope="Kenya and Ethiopia · all seasons · Dunning · CAL 1981–2016 (Long Rains), 1993–2016 (other seasons)">
            <Step n="1" title="Climatological Daily Mean  Q_d(i,j)" eq={"Q_d(i,j) = (1/N_cal) x sum_{y in CAL} R_{d,y}(i,j)"} desc="Mean daily precipitation for each calendar DOY d over the calibration years (CAL: 1993–2016 for the Short Rains and Ethiopia seasons, 1981–2016 for the Long Rains)." table={[['Q_d(i,j)','Mean daily precip for DOY d at pixel (i,j)','mm/day'],['R_{d,y}','Observed daily CHIRPS precip at pixel (i,j), DOY d, year y','mm/day'],['N_cal','Number of calibration years (24 for 1993–2016, 36 for 1981–2016)','years'],['CAL','The calibration years','—'],['d','DOY restricted to seasonal search window','day of year'],['(i,j)','Pixel row and column on the 0.25° grid','—']]}/>
            <Step n="2" title="Window Mean  Q_bar(i,j)  --  the Dunning accumulation baseline" eq={"Q_bar(i,j) = (1/N_win) x sum_{d in Window} Q_d(i,j)"} desc="A single scalar value per pixel -- the long-term average daily rainfall rate across the entire seasonal forecast window. Subtracting it produces anomalies that accumulate positively during wet periods and negatively during dry ones." table={[['Q_bar(i,j)','Scalar window mean -- single value per pixel, not DOY-varying','mm/day'],['N_win','Length of forecast window in days (e.g., 183 days for JJAS, 135 days for FMAM)','days'],['Q_d(i,j)','Climatological daily mean of step 1','mm/day']]}/>
            <Step n="3" title="Climatological Accumulated Anomaly  C(d)" eq={"C(d) = sum_{k=d_start}^{d} [ Q_k(i,j) - Q_bar(i,j) ]"} desc="Cumulative sum of daily climatological anomalies from window start to day d. Computed once per pixel over the calibration years." table={[['C(d)','Cumulative daily anomaly up to day d -- the climatological water season curve','mm'],['Q_k(i,j)','Climatological daily mean at DOY k','mm/day'],['Q_bar(i,j)','Scalar window mean (never re-computed per year)','mm/day'],['k, d_start','Day of the sum, and the first day of the search window','day of year']]}/>
            <Step n="4" title="Climatological Season Bounds  d_s  and  d_e" eq={"d_s = argmin C(d)      d_e = argmax C(d)  [d > d_s]"} desc="Pixel-specific constants from calibration period defining the search window for individual-year event detection." table={[['d_s(i,j)','Climatological season start -- DOY where C(d) reaches its minimum','day of year'],['d_e(i,j)','Climatological season end -- DOY where C(d) reaches its maximum after d_s','day of year'],['C(d)','Climatological accumulated anomaly of step 3','mm']]}/>
            <Step n="5" title="Individual-Year Accumulated Anomaly  A(D)" eq={"A(D) = sum_{j=d_acc,start}^{D} [ R_{j,y}(i,j) - Q_bar(i,j) ]"} desc="Same accumulation applied to each year or ensemble member individually. Search window clamped around d_s and d_e with +/- delta = 45-50 day buffer." table={[['A(D)','Accumulated precip anomaly for year y from window start to day D','mm'],['R_{j,y}','Observed daily precip at pixel (i,j), DOY j, year y','mm/day'],['Q_bar(i,j)','Same scalar window mean from Step 2','mm/day'],['D, j, d_acc,start','Day reached, day of the sum, and the first day of the year’s search window','day of year']]}/>
            <Step n="6" title="Onset Detection" eq={"onset_y(i,j) = argmin A(D) + 1"} desc="Onset is the day after A(D) reaches its absolute minimum -- the first day precipitation exceeds Q_bar on a sustained basis. NaN if argmin falls at window boundary." table={[['onset_y(i,j)','Onset date of year y (or ensemble member) at pixel (i,j)','day of year'],['argmin A(D)','Day of deepest pre-season dry deficit','day of year'],['+1','Dunning definition: onset is the day after the minimum','day']]}/>
            <Step n="7" title="Cessation Detection" eq={"cessation_y(i,j) = argmax A(D)  [D > onset_y]"} desc="The day A(D) reaches its peak after onset. No +1 offset; search restricted to days strictly after onset." table={[['cessation_y(i,j)','Cessation date of year y: the day the accumulated anomaly A(D) peaks after onset','day of year'],['A(D)','Accumulated anomaly of step 5','mm'],['onset_y','Onset of step 6','day of year']]}/>
              <Step n="8" title="Length of Growing Period (LGP)" eq={"LGP_y(i,j) = cessation_y(i,j) - onset_y(i,j)"} desc="Season length in days. The Kenya Long Rains risk gauges treat below 35 days as near-complete failure and below 60 days as a below-median season." table={[['LGP_y(i,j)','Length of growing period of year y','days'],['cessation_y, onset_y','Cessation (step 7) and onset (step 6) dates','day of year']]}/>
            </Disclosure>

            <Disclosure title="FAO water balance: the FAO-56 daily soil-water bucket" scope="Kenya · Short Rains · FAO water balance · maize · ET0 climatology 1993–2016">
                <Step n="1" title="Reference evapotranspiration  ET0" eq={"ET0 = [0.408 Δ (Rn − G) + γ (900/(T+273)) u2 (es − ea)] / [Δ + γ (1 + 0.34 u2)]"} desc="FAO-56 Penman-Monteith (Eq. 6) from ERA5-Land daily Tmax, Tmin, dewpoint, 2 m wind, solar radiation and surface pressure; G = 0 for daily steps. Forecast days use the ERA5-Land ET0 climatology (1993–2016, ±7-day smoothed), the same for every member." table={[['ET0','Reference evapotranspiration of a well-watered grass surface','mm/day'],['Δ','Slope of the saturation vapour pressure curve at T','kPa/°C'],['Rn','Net radiation at the surface','MJ/m²/day'],['G','Soil heat flux (0 for daily steps)','MJ/m²/day'],['γ','Psychrometric constant (from the surface pressure)','kPa/°C'],['T','Mean daily air temperature at 2 m','°C'],['u2','Wind speed at 2 m','m/s'],['es, ea','Saturation vapour pressure (mean of es at Tmax and Tmin) and actual vapour pressure (from the dewpoint)','kPa'],['0.408','Converts energy to evaporated water (1 / latent heat of vaporisation)','mm·m²/MJ'],['900, 0.34','FAO-56 coefficients of the grass reference surface for a daily step','K·mm·s³/(Mg·day), s/m'],['273','Converts °C to K','K']]}/>
                <Step n="2" title="Crop water need  ETc" eq={"ETc = Kc × ET0"} desc="Maize Kc 0.30 / 1.20 / 0.60 (initial / mid / end), stages 20 / 35 / 40 / 30 days from planting, which is the agricultural onset. Kc_ini applies before it." table={[['ETc','Crop evapotranspiration without water stress','mm/day'],['Kc','Crop coefficient of the day’s growth stage','—'],['ET0','Reference evapotranspiration of step 1','mm/day']]}/>
                <Step n="3" title="Root-zone water  TAW and RAW" eq={"TAW = 1000 (θFC − θWP) Zr        RAW = p × TAW"} desc="θFC and θWP from SoilGrids 2.0 texture and organic carbon via the Saxton & Rawls (2006) pedotransfer equations, Zr = 1.0 m; p = 0.55 adjusted for ETc (FAO-56 Table 22). Kenya mean available water ~100–108 mm per metre." table={[['TAW','Total available water of the root zone','mm'],['θFC, θWP','Volumetric water content at field capacity and at the wilting point','m³/m³'],['Zr','Rooting depth','m'],['1000','Converts m of water to mm','mm/m'],['RAW','Readily available water: what the crop uses before it is stressed','mm'],['p','Fraction of TAW the crop can use without stress','—']]}/>
                <Step n="4" title="Water stress  Ks  and actual ET" eq={"Ks = 1 if Dr ≤ RAW, else (TAW − Dr)/(TAW − RAW)        ETa = Ks × ETc"} desc="Dr = TAW − SW is the root-zone depletion (previous day). Ks < 1 means the crop is water-stressed." table={[['Ks','Water stress coefficient (1: no stress, 0: no transpiration)','—'],['Dr','Root-zone depletion at the end of the previous day, TAW − SW','mm'],['TAW, RAW','Total and readily available water of step 3','mm'],['ETa','Actual evapotranspiration','mm/day'],['ETc','Crop evapotranspiration of step 2','mm/day']]}/>
                <Step n="5" title="Daily bucket" eq={"SW_t = SW_t−1 + P − ETa − runoff − drainage,   0 ≤ SW ≤ TAW"} desc="Starts 1 Aug from ERA5-Land 0–100 cm soil moisture. Water above TAW drains; PAW = SW and PAW/TAW is the plant-available fraction. In a forecast, each member continues the observed bucket with its own rainfall." table={[['SW_t','Plant-available water in the root zone at the end of day t','mm'],['SW_t−1','The same at the end of the previous day','mm'],['P','Rainfall of the day','mm'],['ETa','Actual evapotranspiration of the day (step 4)','mm'],['runoff, drainage','Water lost at the surface and below the root zone (above TAW) that day','mm'],['TAW','Total available water (step 3)','mm']]}/>
                <Step n="6" title="Five dates and three season lengths" table={[
                  ['Rainfall onset', 'First wet day from which 10-day rain ≥ 0.5 × ET0'],
                  ['Agricultural onset', 'As above, and PAW/TAW ≥ 0.20 that day and the next 4; rejected as a false start if 7 days fall below 0.20 within 21 days'],
                  ['Rainfall cessation', 'From 1 Nov, rain < 0.5 × ET0 in two consecutive 10-day windows'],
                  ['Agricultural cessation', '7 days with PAW/TAW < 0.20, ETa/ETc < 0.5 and a 10-day rain deficit'],
                  ['Crop-water cessation', 'After the climatological rainfall peak, 21-day rain < 0.5 × ETc with PAW/TAW falling below 0.20'],
                  ['Definition picker', 'Agricultural: agricultural onset → agricultural cessation. Rainfall: rainfall onset → rainfall cessation. Crop-water: agricultural onset → crop-water cessation. LGP = cessation − onset + 1 for each.'],
                ]}/>
              <div style={{fontSize:14, color:'var(--text-muted)', lineHeight:1.5, marginBottom:12}}>
                Rainfall cessation usually comes before agricultural cessation, because the soil keeps supplying water after the rains stop. The pixel panel shows the chance that onset or cessation has happened by today and within 7, 14 and 21 days, and the members' PAW/TAW outlook against the 0.20 critical level.
              </div>
              <p className="about-explain-links" style={{margin:'0 0 12px'}}>
                <ExtLink href={docUrl(DOCS.fao)}>Read the method</ExtLink>
                <span className="about-doclink-meta">{docMeta(DOCS.fao)} · platform v{version}</span>
              </p>
            </Disclosure>

            <Disclosure title="FAO quality flags (bitmask)" scope="Kenya · Short Rains · FAO water balance">
                <Tbl head={['Bit','Meaning']} rows={[
                  ['1', 'No rainfall onset'], ['2', 'No agricultural onset'], ['4', 'At least one false onset rejected'],
                  ['8', 'No rainfall cessation'], ['16', 'No agricultural cessation'], ['32', 'No crop-water cessation'],
                  ['64', 'Insufficient input data (> 5% of days missing)'], ['128', 'Incomplete season (data end before 28 Feb)'],
                  ['256', 'Soil parameters unavailable'], ['512', 'Onset on the first search day (15 Aug): the soil is already wet, a season already under way'],
                ]}/>
            </Disclosure>
          </section>
        </div>
      )}

      {section === 'performance' && (
        <div>
          <p className="about-intro">
            How well the forecasts did on past seasons, compared with a simple baseline, and where the evidence comes from. Skill maps for every place,
            season and method are in the Forecast performance tab.
          </p>

          <S title="What was evaluated">
            <div className="about-prose">
              <p>
                <strong>Hindcasts</strong>: the forecast systems re-run for past years with the same bias correction and the same onset and cessation
                method as the live forecast. Their results are compared with the same dates computed from observed CHIRPS rainfall.
              </p>
              <ul>
                <li><strong>Tercile probabilities</strong> of early, normal or late onset and cessation, and of a short, normal or long season, scored with the ranked probability skill score (RPSS).</li>
                <li><strong>Hit rate</strong>: how often the most likely tercile was the one observed.</li>
                <li><strong>Dates and season lengths</strong> (FAO water balance): the share of hindcast dates within ±7 and ±14 days of the observed date, and their correlation.</li>
                <li><strong>Independent cross-checks</strong> (FAO water balance): ERA5-Land soil wetness, WaPOR actual evapotranspiration and the GIEWS maize planting window.</li>
              </ul>
            </div>
          </S>

          <S title="Where, when and for which method">
            <Tbl head={['Country and season','Methods','Forecast system and start','Calibration (CAL)','Validation (VAL)']} rows={[
              ['Kenya, Long Rains (MAM)', 'Dunning', 'Seven C3S models, 1 Feb', '1981–2016 (SEAS5); 1993–2016 (other models)', 'Independent years after calibration'],
              ['Kenya, Short Rains (OND)', 'Dunning, Agri rules 1–3, FAO water balance', 'ECMWF SEAS5, 1 Sep and 1 Oct (with and without observed rainfall)', '1993–2016', '2017–2024'],
              ['Ethiopia: Kiremt, Belg, annual wet season, Gu/Ganna, Deyr/Hagaya', 'Dunning, inside each season’s regime domain', 'ECMWF SEAS5, 1 Jan, 1 May or 1 Sep', '1993–2016', '2017–2024'],
            ]}/>
          </S>

          <S title="Performance compared with climatology">
            <div className="about-baseline">
              <div><strong>RPSS: skill against climatology</strong>Climatology always gives each tercile a one-in-three chance. RPSS above 0 means the forecast probabilities beat it; 0 means no better; below 0 means worse.</div>
              <div><strong>Hit rate: against chance</strong>Picking a tercile at random is right about one time in three (0.33). A hit rate above 0.33 is better than chance.</div>
            </div>

            <h4 className="about-subhead">Long Rains onset: hit rate by model</h4>
            <Scope>Kenya · Long Rains · Dunning · onset · CAL 1981–2016 (SEAS5), 1993–2016 (other models)</Scope>
            <Tbl head={['System','Onset hit rate','Above chance (0.33) by']}
              rows={C3S_MODELS.map(m => [m.system, m.hr, m.vsChance])}/>
            <p className="about-note">All seven models are above the chance level, by small margins (0.03 to 0.10).</p>

            <h4 className="about-subhead">Short Rains: FAO water balance</h4>
            <Scope>Kenya · Short Rains · FAO water balance · Oct 01 start · VAL 2017–2024 (other periods as stated)</Scope>
            <Tbl head={['Check','Result']} rows={[
              ['RPSS (VAL 2017–2024), agricultural definition', 'Onset +0.43, cessation +0.10, LGP +0.34 (Oct 01); +0.60, +0.15, +0.40 with latest obs. All above 0: better than climatology'],
              ['Hindcast agricultural onset vs observed (VAL 2017–2024)', '68% within ±7 days, 81% within ±14 (Oct 01); 79% / 89% with latest obs'],
              ['Hindcast agricultural cessation vs observed', '40% within ±7 days, 66% within ±14 (Oct 01)'],
              ['Hindcast agricultural LGP vs observed', 'r = 0.83, 74% within ±14 days (Oct 01)'],
              ['Onsets in the GIEWS maize planting window (Oct–Nov)', 'FAO agricultural 66%, FAO rainfall 64%, Agri rule 1 70% (observed 1993–2025)'],
              ['Bucket PAW/TAW vs ERA5-Land 0–100 cm wetness', 'r = 0.73 (daily, Aug–Feb)'],
              ['Dekadal ETa vs WaPOR v3 AETI (Oct–Dec 2018–2025)', 'Bias 0.0 mm/day, r = 0.65'],
            ]}/>
            <p className="about-note">
              For the Short Rains Dunning method, the Agri rules and the Ethiopia seasons, RPSS and hit-rate maps on the validation years are in the
              Forecast performance tab.
            </p>
          </S>

          <S title="Main limitations">
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

          <S title="Detailed validation and method documents">
            <div className="about-prose" style={{marginBottom:16}}>
              <p>
                For a particular place, season and method, open the <strong>Forecast performance</strong> tab: it maps the hit rate, RPSS and
                calibration factor for the validation period. The documents below are on the platform’s public GitHub repository (main branch).
                Platform version v{version}.
              </p>
            </div>
            <DocLinks>
              <DocLink action="View the validation summary" title="FAO water balance: validation comparisons A–F" href={docUrl(DOCS.fao, 'validation')} meta={docMeta(DOCS.fao)} />
              <DocLink action="Read the method" title="FAO water balance: onset, cessation and length of growing period" href={docUrl(DOCS.fao)} meta={docMeta(DOCS.fao)} />
              <DocLink action="Read the method" title="Dunning detection, bias correction and tercile probabilities" href={docUrl(DOCS.readme, 'scientific-methodology')} meta={docMeta(DOCS.readme)} />
              <DocLink action="Read the method" title="Kenya Short Rains, 1 October run and Agri rules 1–3" href={docUrl(DOCS.octRun)} meta={docMeta(DOCS.octRun)} />
              <DocLink action="View the scientific reference" title="Dunning, Black & Allan (2016), J. Geophys. Res. Atmos., 121, 11,405–11,424" href={EXT.dunning} meta="doi.org/10.1002/2016JD025428" />
            </DocLinks>
          </S>

          <S title="How to read the risk gauges" scope="Kenya · Long Rains · Dunning · CAL 1981–2016">
            <p className="about-intro" style={{marginBottom:16}}>
              The risk gauges appear when you select a location on the map. The thresholds below are those of the Kenya Long Rains; the other seasons
              use their own thresholds, shown under each gauge.
            </p>
              <GaugeDef name="Late Onset Risk" thresh="DOY 89 ~29 March" derivation="Domain-median of CHIRPS CAL t67_onset (67th percentile, CAL years)" justification="Onset later than the upper tercile boundary -- historically the top third of years. Signals delayed planting risk." strength="Statistically grounded, data-derived"/>
              <GaugeDef name="Early Onset Risk" thresh="DOY 78 ~18 March" derivation="Domain-median of CHIRPS CAL t33_onset (33rd percentile, CAL years)" justification="Onset earlier than the lower tercile boundary -- historically the bottom third of years. Signals premature planting risk." strength="Statistically grounded, data-derived"/>
              <GaugeDef name="Very Short Season (LGP &lt; 35d)" thresh="35 days ~5th-10th pctile" derivation="~5th-10th percentile of CHIRPS CAL LGP distribution." justification="Near-complete season failure. Even 60-day sorghum cannot complete grain fill." strength="Agronomic consensus"/>
              <GaugeDef name="Short Season Risk (LGP &lt; 45d)" thresh="45 days ~25th-30th pctile" derivation="~25th-30th percentile of CHIRPS CAL LGP distribution." justification="Lower bound for short-season maize. Below 45 days unlikely to support maize production." strength="Agronomic literature"/>
              <GaugeDef name="Below-Normal Season (LGP &lt; 60d)" thresh="60 days ~50th pctile" derivation="~50th percentile -- a below-median season." justification="Minimum for medium-season maize (60-75 days). Beans and cowpea also at risk." strength="Agronomic literature"/>
              <GaugeDef name="Season Failure" thresh="P(onset = NaN)" derivation="Fraction of ensemble members where A(D) finds no minimum. CHIRPS background failure ~11%." justification="Most unambiguous risk signal. Forecasts above 20-25% carry meaningful signal above climatological baseline." strength="Directly interpretable"/>
              <GaugeDef name="Max Ensemble Agreement" thresh="max(P_BN, P_NN, P_AN)" derivation="Climatological baseline = 33%. Values above 50% indicate majority agreement." justification="Measures ensemble coherence independently of dominant category." strength="Standard probabilistic practice"/>
          </S>
        </div>
      )}

      {/* SUB-TAB 5: ARCHITECTURE, WORKFLOW & API */}
      {section === 'technical' && (
        <div className="flex flex-col gap-6">
          {/* General Workflow & Scientific Architecture Details */}
          <div className="flex flex-col 2xl:flex-row gap-6">
            <div className="w-full 2xl:w-[50%] min-w-0 flex flex-col gap-4">
              <S title="End-to-End General Workflow" scope="Kenya and Ethiopia · CHIRPS 1993–2025 · 0.25° grid">
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
                    <div>The same observed record and bias-corrected SEAS5 members also run Agri rules 1–3 (rain thresholds, dry-spell checks, Hargreaves PET) and the FAO-56 soil-water balance (CHIRPS v3, ERA5-Land ET0, SoilGrids). Each gives its own onset, cessation, LGP, tercile probabilities and skill. See <Link to="methods">Forecast methods</Link>.</div>
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


              <S title="Recommended citation">
                <CopyCitation text={CITATION}/>
              </S>

              <S title="Method documents and references">
                <p className="about-docmeta">Public GitHub repository, main branch · platform v{version}</p>
                <DocLinks>
                  <DocLink action="Read the method" title="Platform overview and scientific methodology" href={docUrl(DOCS.readme)} meta={docMeta(DOCS.readme)} />
                  <DocLink action="Read the method" title="FAO water balance" href={docUrl(DOCS.fao)} meta={docMeta(DOCS.fao)} />
                  <DocLink action="Read the method" title="Ethiopia Kiremt operational pipeline" href={docUrl(DOCS.kiremt)} meta={docMeta(DOCS.kiremt)} />
                  <DocLink action="Read the method" title="Crop outlook engine (AquaCrop-OSPy)" href={docUrl(DOCS.crop)} meta={docMeta(DOCS.crop)} />
                  <DocLink action="View the scientific reference" title={DUNNING_REF} href={EXT.dunning} meta="doi.org/10.1002/2016JD025428" />
                </DocLinks>
              </S>
            </div>
          </div>

          <S title="Crop engine workflow" id="about-crop-workflow" scope="Kenya · Short Rains crop outlook · 6 monitored sites · maize, sorghum, bean · every forecast member">
            <p style={{fontSize:16,color:'var(--text-body)',lineHeight:1.7,margin:'0 0 14px'}}>
              The crop outlook grows each crop in every member of every forecast run, at every monitored site, sown by each planting rule. The steps
              below run daily inside the platform’s update; the scenarios weekly; the calibration and the verification on demand, and their results
              set the models’ parameters and say how far the outlook can be trusted.
            </p>
            <CropWorkflowDiagram />
            <Tbl head={['Step', 'What happens', 'Code']} rows={[
              ['1 Inputs', 'Observed CHIRPS v2 rain to the last day and the forecast run’s rain members (SEAS5 bias-corrected to CHIRPS, sub-seasonal and weather models joined in front of it); ERA5-Land temperature at the site (Open-Meteo) and its solar radiation, humidity and wind (Google Earth Engine); the sub-seasonal models’ own temperature (ECMWF extended range, GEFS) at the sites; SoilGrids layers and the ERA5-Land soil water on 1 Aug; the sowing date of each member by Agri rule 1 and by the FAO agricultural onset.', 'crop_engine/data/'],
              ['2 Crop weather', 'One daily file per run: 1 Aug – 31 Mar for every member, with the source of every day (observed, forecast, SEAS5, climatology). The sub-seasonal runs take their own model’s temperature in its range, then SEAS5; SEAS5 temperature, radiation, humidity and wind are corrected to the site’s ERA5-Land record; ET0 is the platform’s FAO-56 ET0, then its climatology scaled by each member’s weather. The file is checked (no gaps, value ranges, Tmin ≤ Tmax, source codes) before any crop runs.', 'data/weather.py, data/seas5.py, data/s2s_temperature.py'],
              ['3 Crop models', 'AquaCrop-OSPy grows the published outlook; WOFOST 7.2 grows the same maize and sorghum members as a second model, shown beside it, so the dependence on the model can be seen. A member sown on a false start is re-sown once at its next sowing opportunity.', 'adapters/aquacrop_adapter.py, adapters/wofost_adapter.py'],
              ['4 Products', 'The Crop outlook tab: yields, chance of failure and sowing opportunity per site, crop and rule, against the same crop grown in the observed weather of 1993–2025, with WOFOST’s result beside AquaCrop’s. The management scenarios: the same members with one choice changed.', 'run_outlook.py, run_scenarios.py, dashboard.py'],
              ['5 Calibration and verification', 'Calibration against trials at KALRO Kiboko and Embu (phenology, AquaCrop’s harvest index, WOFOST’s photosynthesis: maize to Duma 43, sorghum to AquaCrop’s level); the hindcast of the 1 Oct SEAS5 runs 1993–2016 against the observed-weather crop and the season-length forecast; county Short Rains maize yields; and AquaCrop against WOFOST on 1,188 observed seasons.', 'calibration/, hindcast.py, compare_engines.py'],
            ]}/>
          </S>

          <S title="Crop yield model: AquaCrop-OSPy 3.1.0" id="about-aquacrop" scope="Kenya · Short Rains crop outlook · registered sites · 1 Aug – 31 Mar · every forecast member">
            <p style={{fontSize:16,color:'var(--text-body)',lineHeight:1.7,margin:'0 0 16px'}}>
              The crop outlook does not re-implement AquaCrop. For each site, variety, planting rule and forecast member, the crop engine prepares
              the inputs, scales a few crop parameters and runs FAO’s AquaCrop through the open-source AquaCrop-OSPy 3.1.0 package. Every daily crop
              and soil process below is computed by the package; page numbers refer to the FAO AquaCrop reference manual.
            </p>

            <h4 className="about-subhead">Inputs</h4>
            <Tbl head={['Input', 'Value used']} rows={[
              ['Weather', 'Daily minimum and maximum temperature, rain and reference evapotranspiration (ET0) of one member, 1 Aug to 31 Mar: ERA5-Land to its latest day, then the ECMWF SEAS5 temperature of that member, bias-corrected to ERA5-Land by lead day, with the ET0 climatology scaled by that member’s weather (see Crop weather below). ET0 is floored at 0.1 mm because AquaCrop divides by it.'],
              ['Soil', 'Layers from texture (sand, clay, organic matter; SoilGrids) through the package’s pedotransfer functions.'],
              ['Initial soil water', 'θ = θwp + f · (θfc − θwp) at every depth on 1 Aug, with f from the ERA5-Land soil water, as in the FAO water balance.'],
              ['Crop', 'AquaCrop’s thermal-time crop files MaizeGDD, SorghumGDD and DryBeanGDD, with the adjustments below.'],
              ['Management', 'The outlook is rain-fed, on bare soil with free surface runoff and no groundwater table. The management scenarios add supplementary or full irrigation, mulch and tied ridges (no surface runoff) through AquaCrop’s own irrigation and field-management options (see Management scenarios below).'],
              ['CO₂', 'The package default: the Mauna Loa record and its projection, at the simulated year’s concentration.'],
            ]}/>

            <h4 className="about-subhead" style={{marginTop:24}}>Daily processes computed by AquaCrop</h4>
            <Step n="1" title="Thermal time (GDD, method 3; pp. 19–20)"
              eq={"Tx = min(max(Tmax, Tbase), Tupp)      Tn = min(Tmin, Tupp)\nGDD = max((Tx + Tn) / 2, Tbase) − Tbase"}
              desc="Every crop stage (emergence, flowering, senescence, maturity) is a GDD threshold. Maize and sorghum: Tbase 8 °C, Tupp 30 °C; bean: 9 °C and 30 °C." table={[['Tmax, Tmin','Daily maximum and minimum air temperature','°C'],['Tbase, Tupp','Base and upper temperature of crop development','°C'],['Tx, Tn','Maximum and minimum temperature limited to that range','°C'],['GDD','Growing degree days of the day (thermal time)','°C·day']]}/>
            <Step n="2" title="Soil hydraulic properties (Saxton & Rawls 2006)"
              eq={"λ = 1 / [(ln 1500 − ln 33) / (ln θfc − ln θwp)]\nKsat = 1930 · (θs − θfc)^(3 − λ) · 24        (mm/day)\nτ = 0.0866 · Ksat^0.35"}
              desc="Wilting point θwp, field capacity θfc and saturation θs come from texture and organic matter; τ is the drainage coefficient." table={[['λ','Pore-size distribution index of the soil','—'],['1500, 33','Matric potential at the wilting point and at field capacity','kPa'],['θwp, θfc, θs','Volumetric water content at the wilting point, field capacity and saturation','m³/m³'],['Ksat','Saturated hydraulic conductivity (1930 · … in mm/h, × 24)','mm/day'],['τ','Drainage coefficient: share of the water above field capacity that drains in a day','—']]}/>
            <Step n="3" title="Drainage, runoff and infiltration"
              eq={"Δθ/Δt = τ · (θs − θfc) · (e^(θ − θfc) − 1) / (e^(θs − θfc) − 1)"}
              desc="Water above field capacity drains at this rate, capped by each layer’s Ksat. Surface runoff uses the USDA curve number (61 for these soils, adjusted daily for the wetness of the top 0.3 m); infiltration fills the profile from the top. Capillary rise is inactive without a groundwater table." table={[['Δθ/Δt','Drainage rate of a soil layer: the fall in its water content per day (× the layer’s thickness in mm gives mm/day)','m³/m³ per day'],['θ','Volumetric water content of the layer','m³/m³'],['θs, θfc','Water content at saturation and at field capacity','m³/m³'],['τ','Drainage coefficient of step 2','—'],['e','Base of the natural logarithm (2.718)','—']]}/>
            <Step n="4" title="Canopy cover (pp. 39–45)"
              eq={"CCo = PlantPop × SeedSize × 10⁻⁸\nCC  = CCo · e^(CGC·t)                          while CC ≤ CCx / 2\nCC  = CCx − 0.25 · (CCx² / CCo) · e^(−CGC·t)      above CCx / 2\nCC  = CCact · [1 − 0.05 · (e^(3.33·CDC·t / (CCx + 2.29)) − 1)]      after senescence"}
              desc="t is thermal time; CCact is the canopy reached before decline. Maize at 44,444 plants/ha starts at CCo ≈ 0.003. Water stress slows canopy expansion (Ks,exp) and brings senescence forward (Ks,sen)." table={[['CCo','Initial canopy cover, at 90 % emergence','fraction (0–1)'],['PlantPop','Plant population','plants/ha'],['SeedSize','Soil surface covered by one seedling','cm²/plant'],['10⁻⁸','Converts cm² to ha (1 ha = 10⁸ cm²)','ha/cm²'],['CC','Green canopy cover','fraction (0–1)'],['CGC','Canopy growth coefficient','per °C·day'],['t','Thermal time since emergence (in the last line: since senescence began)','°C·day'],['CCx','Maximum canopy cover','fraction (0–1)'],['CDC','Canopy decline coefficient','per °C·day'],['CCact','Canopy cover reached when the decline starts','fraction (0–1)'],['0.25, 0.05, 3.33, 2.29','AquaCrop’s fixed shape constants','—']]}/>
            <Step n="5" title="Water stress coefficients (pp. 9–13)"
              eq={"p    = p_std + 0.04 · (5 − ET0) · log10(10 − 9 · p_std)\nDrel = (Dr / TAW − p_up) / (p_lo − p_up)\nKs   = 1 − (e^(Drel · fshape) − 1) / (e^(fshape) − 1)"}
              desc="Dr is the root-zone depletion and TAW the total available water. Separate thresholds give the coefficients for canopy expansion, stomatal closure, early senescence and pollination; the thresholds move with evaporative demand." table={[['p','Depletion threshold adjusted for the day’s evaporative demand','fraction of TAW'],['p_std','The crop file’s threshold at an ET0 of 5 mm/day','fraction of TAW'],['ET0','Reference evapotranspiration','mm/day'],['Drel','Relative depletion between the two thresholds','fraction (0–1)'],['Dr','Root-zone depletion','mm'],['TAW','Total available water of the root zone','mm'],['p_up, p_lo','Upper threshold (stress starts) and lower threshold (stress is complete)','fraction of TAW'],['fshape','Shape factor of the stress curve','—'],['Ks','Stress coefficient (1: no stress, 0: full stress)','—']]}/>
            <Step n="6" title="Soil evaporation (pp. 68–80)"
              eq={"EsPot = Kex · (1 − CC*) · ET0"}
              desc="Reduced further under a dead or late canopy. Stage 1 is limited by energy until the readily evaporable water is used; in stage 2 evaporation falls with the relative wetness of the surface layer." table={[['EsPot','Potential soil evaporation','mm/day'],['Kex','Maximum soil evaporation coefficient (1.1)','—'],['CC*','Canopy cover adjusted for micro-advection','fraction (0–1)'],['ET0','Reference evapotranspiration','mm/day']]}/>
            <Step n="7" title="Transpiration (pp. 82–91)"
              eq={"TrPot = Kcb · CC* · ET0 · KsCold\nTr    = Σ compartments  Ks,sto · Sx · root fraction   (≤ TrPot)"}
              desc="Kcb (1.05 for maize) declines with canopy age and with CO₂ above the reference. KsCold reduces transpiration on days with little thermal time. Actual transpiration is root uptake, compartment by compartment, reduced by stomatal water stress and by waterlogging." table={[['TrPot','Potential crop transpiration','mm/day'],['Kcb','Crop transpiration coefficient at full canopy','—'],['CC*','Canopy cover adjusted for micro-advection','fraction (0–1)'],['ET0','Reference evapotranspiration','mm/day'],['KsCold','Cold stress coefficient','0–1'],['Tr','Actual transpiration: root uptake summed over the soil compartments','mm/day'],['Ks,sto','Stomatal water stress coefficient (also reduced by waterlogging)','0–1'],['Sx','Maximum root water extraction in a compartment (× its thickness in mm gives mm/day)','m³/m³ per day'],['root fraction','Share of the roots in the compartment','—']]}/>
            <Step n="8" title="Biomass (pp. 98–108)"
              eq={"dB = WP* · fCO2 · (Tr / ET0)"}
              desc="AquaCrop’s core equation. WP* is the normalised water productivity (33.7 g/m² for maize and sorghum, 15 for bean), reduced during yield formation by WPy where the crop file sets it; fCO2 is the CO₂ fertilisation factor. A parallel no-stress biomass, from TrPot instead of Tr, gives the yield potential." table={[['dB','Above-ground biomass produced in the day (100 g/m² = 1 t/ha)','g/m² per day'],['WP*','Normalised water productivity: biomass per unit of Tr/ET0 summed over the days','g/m²'],['fCO2','CO₂ fertilisation factor','—'],['Tr','Actual transpiration','mm/day'],['ET0','Reference evapotranspiration','mm/day']]}/>
            <Step n="9" title="Harvest index (pp. 110–126)"
              eq={"HIref  = HIini · HI0 / (HIini + (HI0 − HIini) · e^(−k·t)),  then a linear rise to HI0\nHI_adj = f_pre · f_post · min(HIref, f_pol · HI0)"}
              desc="HIref starts at the HIstart threshold. For grain crops it is adjusted for water stress before flowering (f_pre), for heat, cold or water stress at pollination (f_pol; maize: heat from 40 °C, cold below 10 °C), and for stress during grain filling (f_post)." table={[['HIref','Reference harvest index on the day','fraction (0–1)'],['HIini','Initial harvest index at the start of yield formation','fraction (0–1)'],['HI0','Reference harvest index of the variety','fraction (0–1)'],['k','Harvest-index growth coefficient','per day'],['t','Time since the start of yield formation','days'],['HI_adj','Harvest index adjusted for stress','fraction (0–1)'],['f_pre, f_pol, f_post','Adjustments for stress before flowering, at pollination and during grain filling','—']]}/>
            <Step n="10" title="Yield, roots and root-zone water"
              eq={"Dry yield = B × HI_adj"}
              desc="Yield potential is the same product with the no-stress biomass. Roots deepen from Zmin to Zmax with thermal time, more slowly under water stress, and the root-zone depletion and TAW are updated for the next day." table={[['Dry yield','Grain (or seed) dry yield','t/ha'],['B','Above-ground biomass at maturity (the sum of dB; 100 g/m² = 1 t/ha)','t/ha'],['HI_adj','Adjusted harvest index of step 9','fraction (0–1)']]}/>

            <h4 className="about-subhead">What the crop engine adds</h4>
            <Step n="A" title="Phenology scaled to the variety’s maturity"
              eq={"f = maturity_days × (21 − Tbase) / Maturity_GDD\nstage thresholds × f        CGC, CDC ÷ f"}
              desc="The variety matures in its stated number of days at a mean of 21 °C, and the canopy keeps its shape. Early maize (115 days): f = 0.88; medium maize (142 days): 1.09; sorghum (100 days): 0.74; bean (75 days): 0.69. A warmer season accumulates thermal time faster, so the crop matures sooner." table={[['f','Scaling factor of the crop file’s thermal times for the variety','—'],['maturity_days','The variety’s stated days to maturity','days'],['21','Reference mean temperature at which the variety takes maturity_days','°C'],['Tbase','Base temperature of crop development','°C'],['Maturity_GDD','Thermal time to maturity in the crop file','°C·day'],['stage thresholds','Thermal time to emergence, flowering, senescence and maturity','°C·day'],['CGC, CDC','Canopy growth and decline coefficients','per °C·day']]}/>
            <Step n="B" title="Calibrated parameters"
              desc="Maize: plant population 44,444 per ha, CCx 0.75 and HI0 0.324, calibrated at KALRO Kiboko (AquaCrop’s defaults are 75,000, 0.96 and 0.48). Sorghum: 66,667 per ha, CCx 0.75, HI0 0.30. Bean: AquaCrop’s defaults apart from phenology."/>
            <Step n="C" title="Outcome of each member"
              desc="Before AquaCrop runs, thermal time from sowing to 31 Mar (the same method 3) must reach maturity, or the member counts as too late. After the run: ok when harvest falls within 3 days of the expected maturity; failed establishment when the crop died before its canopy reached 5 %; died otherwise. A stress day is one with transpiration below half its potential (with potential ≥ 0.5 mm). After a failed establishment the member is re-sown once at its next sowing opportunity, while the variety can still mature."/>

            <h4 className="about-subhead">Not represented</h4>
            <p style={{fontSize:16,color:'var(--text-body)',lineHeight:1.7,margin:0}}>
              Groundwater and capillary rise, salinity and weeds are not used, and irrigation, mulch and runoff control only in the scenarios. Soil fertility
              stress is not modelled by AquaCrop-OSPy 3.1.0; its effect is absorbed in the calibrated CCx and HI0. Radiation and humidity act only
              through ET0, in the soil evaporation, transpiration and Tr/ET0 terms.
            </p>
          </S>

          <S title="Crop weather: sub-seasonal and SEAS5 temperature, radiation, humidity, wind and ET0" id="about-crop-weather" scope="Kenya · Short Rains crop outlook · ECMWF SEAS5 1 Oct runs, lead days 1–182 (1 Oct – 31 Mar) · ECMWF extended range and GEFS runs, days 1–46 and 1–35">
            <p style={{fontSize:16,color:'var(--text-body)',lineHeight:1.7,margin:'0 0 16px'}}>
              After the last ERA5-Land day each member takes its own SEAS5 weather, corrected to the site’s ERA5-Land record over the calibration
              years 1993–2016 (a past run leaves its own year out). Member k of the temperature, radiation, humidity and wind is member k of the rain,
              so a dry member is also its own warm, sunny member.
            </p>
            <Step n="1" title="Temperature: mean bias by lead day"
              eq={"bias(d, site) = S15[ mean_years( mean_members T_SEAS5 ) − T_ERA5-Land ](d)\nT_k(d) = T_SEAS5,k(d) − bias(d, site)        Tmin ≤ Tmax"}
              desc="S15 is a ±15-day running mean over the lead days. The forecast’s anomaly and its member spread are kept. Kiboko: SEAS5 is 1.0–1.2 °C too cool in Tmax and 2.3–2.5 °C in Tmin; Kapiti 2.8–3.5 °C too warm in Tmax." table={[['bias(d, site)','Mean temperature error of SEAS5 at the site on day d of the forecast','°C'],['d','Day of the forecast (lead day from the 1 Oct start)','days'],['S15[…]','±15-day running mean over the lead days','—'],['mean_years, mean_members','Mean over the calibration years 1993–2016 and over the hindcast members','—'],['T_SEAS5, T_ERA5-Land','Daily maximum or minimum air temperature at 2 m of SEAS5 and of ERA5-Land','°C'],['T_k(d)','Corrected temperature of forecast member k on day d','°C']]}/>
            <Step n="2" title="Radiation, vapour pressure and wind: a ratio by lead day"
              eq={"r(d, site) = S15[ mean_years X_ERA5-Land ](d) / S15[ mean_years mean_members X_SEAS5 ](d)      0.5 ≤ r ≤ 2\nX_k(d) = X_SEAS5,k(d) × r(d, site)"}
              desc="X is the daily solar radiation (from the accumulated surface downward radiation), the vapour pressure at the 2 m dewpoint (FAO-56 Eq. 14) and the 2 m wind (10 m speed × 0.748, Eq. 47). The dewpoint and wind are 00 UTC values; the ratio absorbs that offset with the model’s own bias and keeps every value positive." table={[['r(d, site)','Ratio correcting SEAS5 at the site on day d (kept within 0.5–2)','—'],['X','Daily solar radiation Rs, vapour pressure e or 2 m wind u2','MJ/m²/day, hPa, m/s'],['S15[…]','±15-day running mean over the lead days','—'],['X_k(d)','Corrected value of member k on day d','as X']]}/>
            <Step n="3" title="ET0 on SEAS5 days"
              eq={"ET0_k(d) = ET0_clim(d) × clip( PM(T_k, e_k, u2_k, Rs_k) / PM(T_clim, e_clim, u2_clim, Rs_clim), 0.5, 1.5 )\nwithout SEAS5 radiation:  ET0_k(d) = ET0_clim(d) × clip( HG(T_k) / HG(T_clim), 0.7, 1.3 )"}
              desc="PM is FAO-56 Penman-Monteith (Eq. 6) and HG the Hargreaves equation (Eq. 52), in which the radiation cancels; ET0_clim is the platform’s ERA5-Land ET0 climatology for the season day. The ratio carries the member’s anomaly onto the platform’s own ET0, so the crop models and the FAO water balance see the same evaporative demand. Until at least 10 calibration years of SEAS5 radiation are on disk the run uses the Hargreaves ratio and says so." table={[['ET0_k(d)','Reference evapotranspiration of member k on day d','mm/day'],['ET0_clim(d)','The site’s ERA5-Land ET0 climatology (1993–2016) for that day of the season','mm/day'],['PM(…), HG(…)','FAO-56 Penman-Monteith (Eq. 6) and Hargreaves (Eq. 52) ET0','mm/day'],['T, e, u2, Rs','Air temperature, vapour pressure, 2 m wind and solar radiation (member k or climatology)','°C, kPa, m/s, MJ/m²/day'],['clip(x, a, b)','x kept between a and b','—']]}/>
            <Step n="4" title="March rain"
              desc="SEAS5 member k’s lead days 152–182, quantile-mapped to CHIRPS per site and day (the CHIRPS pool: the calibration years’ days within ±15 days), as the Agri rules’ January–February."/>
            <Step n="5" title="Sub-seasonal temperature (s2s-ecmwf and s2s-gefs runs)"
              eq={"bias(L, site) = S3[ mean_runs( mean_members T_model ) − T_ERA5-Land ](L)        L: lead day\nT_k(d) = T_model,m(k)(d) − bias(d − run, site)        Tmin ≤ Tmax        then SEAS5 after the model’s last day"}
              desc="T_model is the daily maximum or minimum of the ECMWF extended range (101 members to day 46, 1.5°) or GEFS (31 members to day 35, 0.25°) at the site’s nearest cell, from the same dynamical.org archives as the rain; m(k) is the member the rain join paired with rain member k. S3 is a ±3-day running mean over the lead. Training: 155 ECMWF runs (2026) and 171 GEFS runs (Aug–Dec 2020–2025). The biases are steady with lead: GEFS within 4 °C, ECMWF up to +11 °C at Genco Maralal, whose 1.5° cell lies far below the site. ET0 on these days: the climatology × the member’s Penman-Monteith ratio with its own radiation, humidity and wind (step 6), else its Hargreaves ratio." table={[['bias(L, site)','Mean temperature error of the model at the site on lead day L','°C'],['L','Lead day (1: the run’s start day); d − run is the lead of day d','days'],['S3[…]','±3-day running mean over the lead days','—'],['mean_runs, mean_members','Mean over the training runs and over each run’s members','—'],['T_model, T_ERA5-Land','Daily maximum or minimum air temperature at 2 m of the ECMWF extended range or GEFS, and of ERA5-Land','°C'],['m(k)','The model member paired with rain member k','—'],['T_k(d)','Corrected temperature of member k on day d','°C']]}/>
            
            <p style={{fontSize:16,color:'var(--text-body)',lineHeight:1.7,margin:0}}>
              The site series were checked against the platform’s ERA5-Land ET0: FAO-56 ET0 computed from them correlates 0.99–1.00 with it at
              every site over 8,027 days, mean difference 0.08–0.22 mm/day (a 0.1° point against a 0.25° cell mean).
            </p>
          </S>

          <S title="Second crop model: WOFOST 7.2 (PCSE 6.0.13)" id="about-wofost" scope="Kenya · Short Rains · maize and sorghum (WOFOST has no dry bean) · shown beside AquaCrop in the Crop outlook tab">
            <p style={{fontSize:16,color:'var(--text-body)',lineHeight:1.7,margin:'0 0 16px'}}>
              WOFOST (Wageningen) is a light-driven crop model: growth comes from intercepted radiation and leaf photosynthesis, reduced by water
              stress, where AquaCrop’s comes from transpired water. The crop engine runs the Python Crop Simulation Environment’s water-limited
              WOFOST 7.2 with the classic water balance (Wofost72_WLP_CWB) on exactly AquaCrop’s inputs: the same members, soil, 1 Aug water,
              sowing and re-sowing. Every daily process below is computed by PCSE. Since November 2026 it grows every forecast run’s maize and
              sorghum members, and the Crop outlook tab shows its yield, failure, maturity and harvest beside AquaCrop’s: where the two disagree,
              the outlook depends on the model as much as on the weather.
            </p>
            <Step n="1" title="Development stage"
              eq={"DVS: 0 at emergence (after TSUMEM °C·d above TBASEM), 1 at flowering, 2 at maturity\ndDVS/dt = DTSMTB(T) / TSUM1   (DVS < 1)        DTSMTB(T) / TSUM2   (DVS ≥ 1)"}
              desc="DTSMTB is the crop’s effective-temperature table (maize: 0 °C·d below 8 °C, rising to 22 at 30 °C)." table={[['DVS','Development stage: 0 at emergence, 1 at flowering, 2 at maturity','—'],['TSUMEM','Thermal time from sowing to emergence','°C·day'],['TBASEM','Base temperature for emergence','°C'],['DTSMTB(T)','Effective temperature of the day, from the crop’s table at the day’s mean temperature T','°C·day per day'],['T','Daily mean air temperature','°C'],['TSUM1, TSUM2','Thermal time from emergence to flowering and from flowering to maturity','°C·day'],['dDVS/dt','Daily rate of development','per day']]}/>
            <Step n="2" title="Gross assimilation"
              eq={"A_leaf = AMAX · (1 − e^(−EFF · I_abs / AMAX))         I_abs: light absorbed per leaf layer\nA_gross = ∫ day ∫ canopy A_leaf  (3-point Gaussian over depth and hour, LAI and KDIF)  × Tmin and T reductions"}
              desc="AMAX is AMAXTB(DVS) × AMAXTB_scale, the maximum leaf CO₂ assimilation; EFF the light-use efficiency of single leaves; direct and diffuse light come from the day’s solar radiation and the canopy’s extinction coefficient." table={[['A_leaf','Gross CO₂ assimilation of a leaf layer','kg CO₂/ha leaf/h'],['AMAX','Maximum leaf CO₂ assimilation at light saturation','kg CO₂/ha leaf/h'],['EFF','Light-use efficiency of single leaves','kg CO₂/ha/h per J/m²/s'],['I_abs','Photosynthetically active radiation absorbed per leaf area','J/m² leaf/s'],['A_gross','Daily gross CO₂ assimilation of the canopy','kg CO₂/ha/day'],['LAI','Leaf area index','m² leaf/m² ground'],['KDIF','Extinction coefficient of the canopy for diffuse light','—']]}/>
            <Step n="3" title="Water limitation (classic water balance)"
              eq={"TRAMX = CFET · ET0 · (1 − e^(−0.75 · KDIF · LAI))\nTRA = TRAMX · min(1, (SM − SMW) / ((1 − p) · (SMFCF − SMW)))      p from DEPNR and ET0\nA_gross,water = A_gross × TRA / TRAMX"}
              desc="One root zone, deepening with the crop to its maximum rooting depth; soil evaporation from ES0 under the open canopy, percolation limited by SOPE and KSUB." table={[['TRAMX','Maximum transpiration of the canopy (PCSE works in cm/day: × 10 for mm/day)','cm/day'],['CFET','Correction factor of transpiration rate','—'],['ET0','Reference evapotranspiration','cm/day'],['KDIF, LAI','Extinction coefficient for diffuse light and leaf area index','—'],['TRA','Actual transpiration','cm/day'],['SM','Volumetric water content of the root zone','cm³/cm³'],['SMW, SMFCF','Water content at the wilting point and at field capacity','cm³/cm³'],['p, DEPNR','Soil water depletion fraction, from the crop group number DEPNR and ET0','—'],['A_gross,water','Gross assimilation reduced for water stress','kg CO₂/ha/day']]}/>
            <Step n="4" title="Respiration, conversion and partitioning"
              eq={"dW = CVF · (A_gross,water · 30/44 − R_m)          R_m: maintenance respiration of each organ, Q10 = 2\ndW_roots = FRTB(DVS) · dW,   rest above ground: leaves FLTB, stems FSTB, storage organs FOTB (DVS)"}
              desc="CVF is the conversion efficiency of assimilates into dry matter. Leaf area grows with leaf weight (specific leaf area) and dies with age (SPAN) and water stress." table={[['dW','Daily dry-matter growth of the crop','kg/ha/day'],['CVF','Conversion efficiency of assimilates into dry matter','kg dry matter/kg CH₂O'],['30/44','Converts CO₂ to carbohydrate (molar masses of CH₂O and CO₂)','kg CH₂O/kg CO₂'],['R_m','Maintenance respiration of the living organs','kg CH₂O/ha/day'],['Q10','Increase of maintenance respiration per 10 °C','—'],['dW_roots','Daily growth of the roots','kg/ha/day'],['FRTB, FLTB, FSTB, FOTB','Shares of the growth going to roots, leaves, stems and storage organs, by DVS','—']]}/>
            <Step n="5" title="Yield"
              eq={"yield = TWSO   (total dry weight of storage organs at maturity)"}
              desc="WOFOST has no harvest index: grain is what the partitioning puts into storage organs from flowering." table={[['yield','Grain dry yield (shown in t/ha: kg/ha ÷ 1000)','kg/ha'],['TWSO','Total dry weight of the storage organs at maturity','kg/ha']]}/>

            <h4 className="about-subhead">What the crop engine sets</h4>
            <Tbl head={['', 'Value used']} rows={[
              ['Crops', 'WOFOST’s tropical sets of Van Heemst (1988): Maize_VanHeemst_1988 and Sorghum_VanHeemst_1988. There is no dry-bean set, so the bean stays AquaCrop-only.'],
              ['Phenology', 'TSUM1 and TSUM2 (their ratio kept) scaled so the variety matures in its stated days at 21 °C: AquaCrop’s calibrated targets, so the maize classes carry the Kiboko phenology calibration. A variety’s flowering_days, when set, fixes TSUM1 apart (as AquaCrop’s HIstart).'],
              ['Yield level', 'Maize: AMAXTB × 0.511, so medium maize under full irrigation at Kiboko (sown every 14 days, 1 Jun – 31 Jul 2012) yields Duma 43’s 7.76 t/ha, the trial AquaCrop’s HI0 was fitted to. WOFOST’s own table gives 11.2 t/ha. Early maize shares the factor: 6.2 t/ha against the Katumani check’s 3.0 and the IITA 2013 median of 4.5 (upper bounds, as AquaCrop’s 6.5). Sorghum: AMAXTB × 0.75, so WOFOST’s no-water-stress sorghum at Kiboko (sown every 14 days from 20 Oct 2012) equals AquaCrop’s, 4.97 t/ha (WOFOST’s own table: 5.73): no irrigated Gadam trial exists, so the two engines share the sorghum level. Fertilised Gadam yielded 4.86–5.39 t/ha that season at KARI Kampi ya Mawe, 40 km away (Mwadalu et al. 2022).'],
              ['Evaporative demand', 'ET0 is the platform’s FAO-56 ET0, as AquaCrop’s; PCSE’s open-water and bare-soil evaporation (modified Penman E0, ES0) are scaled by the day’s ratio of that ET0 to PCSE’s own.'],
              ['Soil', 'SoilGrids wilting point and field capacity averaged over the top 100 cm, saturation and conductivity (Saxton & Rawls 2006) for the percolation limits, the 200 cm profile as rooting limit, the ERA5-Land fraction of available water on 1 Aug.'],
              ['Outcome', 'As AquaCrop’s. WOFOST’s crop survives drought (its leaves die back), so a crop that never reaches 5 % cover counts as failed establishment, one whose leaves all die before DVS 1.9, or that matures with no grain, as died.'],
            ]}/>

            <h4 className="about-subhead" style={{marginTop:24}}>AquaCrop and WOFOST on the same 1,188 observed seasons (1993–2025)</h4>
            <Tbl head={['Site', 'Early maize: median t/ha, AquaCrop / WOFOST', 'Failure rate', 'r of sown seasons', 'Sorghum: median t/ha', 'Failure rate']} rows={[
              ['El Karama', '3.19 / 2.94', '30 % / 9 %', '0.70', '1.90 / 5.11', '36 % / 3 %'],
              ['Genco Maralal', '3.15 / 1.02', '30 % / 36 %', '0.47', '1.62 / 2.92', '36 % / 9 %'],
              ['Genco Tana River', '0.45 / 0.21', '52 % / 64 %', '0.32', '0.15 / 0.84', '52 % / 46 %'],
              ['KALRO Kiboko', '0.80 / 0.86', '48 % / 39 %', '0.78', '0.92 / 1.65', '48 % / 15 %'],
              ['Kapiti', '0.86 / 0.96', '36 % / 36 %', '0.80', '0.74 / 1.92', '42 % / 24 %'],
              ['Livemo Memerush', '0.07 / 0.40', '55 % / 55 %', '0.87', '0.07 / 0.86', '58 % / 33 %'],
            ]}/>
            <p style={{fontSize:16,color:'var(--text-body)',lineHeight:1.7,margin:'12px 0 0'}}>
              FAO agricultural onset sowing, every season counted (a failure or no sowing as zero). With the maize yield level calibrated, the
              two models agree on maize at most sites: the rank correlation of the sown seasons’ yields is 0.27–0.89 and they agree on failure or
              not in 64–94 % of seasons. WOFOST yields less at cool Genco Maralal (1,780 m), where its slower development pushes grain filling
              into the dry season, and more for sorghum, whose yield level was then WOFOST’s own (now matched to AquaCrop’s). Where AquaCrop’s
              seedlings die in a dry spell after sowing, WOFOST’s crop only slows: that is most of the difference in failure rates.
            </p>

            <h4 className="about-subhead" style={{marginTop:24}}>Water balance: WOFOST’s multi-layer balance, tested and not adopted</h4>
            <p style={{fontSize:16,color:'var(--text-body)',lineHeight:1.7,margin:0}}>
              WOFOST 7.3’s multi-layer water balance was run on the SoilGrids layers (each layer’s retention anchored at its own field capacity
              and wilting point, Saxton & Rawls 2006) over the 1993–2025 seasons. It makes WOFOST’s maize drier than AquaCrop’s, failing in
              70–85 % of the seasons at Kiboko, Kapiti and Livemo (AquaCrop 36–55 %, WOFOST’s one-zone balance 36–55 %), and leaves Tana River
              as it was. The outlook keeps the one-zone balance; WOFOST 7.3 with it gives exactly 7.2’s results.
            </p>

            <h4 className="about-subhead" style={{marginTop:24}}>Sorghum: flowering apart from maturity, tested and not adopted</h4>
            <p style={{fontSize:16,color:'var(--text-body)',lineHeight:1.7,margin:0}}>
              Both engines now accept a variety’s days to flowering apart from its days to maturity. Fitted to Gadam at the University of Embu farm
              (Long Rains 2020: flowering 65.3, maturity 97.7 days), the class would become 85 days with flowering at 59, matching both. It is not
              used: at Kiboko that crop matures in 71 days for Short Rains sowings, below the 75–90 days the variety catalogues give, and its
              no-water-stress yield falls from 4.97 to 4.14 t/ha, below the fertilised Gadam yields measured nearby. The class keeps 100 days
              (84 at Kiboko), whose flowering already matches Embu’s.
            </p>

            <h4 className="about-subhead" style={{marginTop:24}}>WOFOST in the outlook: the 1 Oct 2026 seasonal run (observations to 5 Nov)</h4>
            <Tbl head={['Site', 'Early maize: yield if sown, AquaCrop / WOFOST', 'Failure if sown', 'Sorghum: yield if sown', 'Failure if sown']} rows={[
              ['El Karama', '1.1 / 1.1', '36 % / 28 %', '0.7 / 3.1', '48 % / 8 %'],
              ['Genco Maralal', '0.0 / 0.4', '65 % / 59 %', '0.0 / 1.0', '62 % / 38 %'],
              ['Genco Tana River', '1.6 / 0.1', '0 % / 100 %', '0.7 / 0.2', '0 % / 100 %'],
              ['KALRO Kiboko', '3.2 / 2.3', '24 % / 12 %', '3.3 / 3.2', '24 % / 8 %'],
              ['Kapiti', '5.7 / 3.1', '12 % / 20 %', '4.1 / 4.4', '20 % / 8 %'],
              ['Livemo Memerush', '1.4 / 1.1', '44 % / 28 %', '1.2 / 2.1', '44 % / 24 %']
            ]}/>
            <p style={{fontSize:16,color:'var(--text-body)',lineHeight:1.7,margin:'12px 0 0'}}>
              FAO agricultural onset sowing; failure if sown is a yield below 0.5 t/ha. The two models agree within 0.3 t/ha on early maize at
              El Karama and Livemo and on sorghum at Kiboko and Kapiti, and WOFOST fails less almost everywhere, because its seedlings
              slow in a dry spell where AquaCrop’s die. At Genco Tana River WOFOST’s crops sown on 3 Sep hardly grow: the soil starts
              almost dry (5 % of its available water on 1 Aug) and only 4 mm falls in the next 16 days; WOFOST’s stunted seedlings never
              rebuild their leaf area, while AquaCrop’s canopy grows again with the rain. With rain every day the same WOFOST crop yields
              3.8 t/ha. WOFOST’s multi-layer water balance does no better there. There, this season, the outlook depends on the model.
              Each model also has its own simulated past seasons (WOFOST grown in the observed weather of 1993–2025), shown in the tab
              beside AquaCrop’s.
            </p>
          </S>

          <S title="Management scenarios" id="about-scenarios" scope="Kenya · Short Rains · seasonal (SEAS5) run · every site, crop, rule and member · refreshed weekly">
            <p style={{fontSize:16,color:'var(--text-body)',lineHeight:1.7,margin:'0 0 16px'}}>
              The seasonal run’s crops are grown again in the same weather members with one choice changed. The outlook itself is re-simulated first,
              unchanged, as a control: if any member’s yield differs from the outlook by more than 0.05 t/ha, the scenarios are not written.
            </p>
            <Tbl head={['Group', 'Scenarios', 'How AquaCrop applies it']} rows={[
              ['Sowing date', '14 days earlier, 14 or 28 days later', 'Each member’s sowing date shifted; a member with no onset stays unsown.'],
              ['Calendar sowing', '15 Oct, 1 Nov, 15 Nov', 'Every member sown on that date, rain or not.'],
              ['Plant density', '× 0.67, × 1.2', 'AquaCrop-OSPy sets only the initial canopy from it (CCo = plant population × seed size); the maximum canopy calibrated at Kiboko does not change.'],
              ['Initial soil water', 'Wilting point, field capacity on 1 Aug', 'In place of the ERA5-Land fraction.'],
              ['Water management', 'Supplementary irrigation, up to 100 mm a season', 'IrrigationManagement method 1: irrigate whenever root-zone water falls below 30 % of its available water from sowing to flowering (SMT 30, 30, 30, 0 % by growth stage), at most 25 mm a day and 100 mm a season reaching the soil (about 130 mm drawn from a pan or tank at 75 % efficiency). The cap is on net water: with a lower application efficiency and a cap, AquaCrop-OSPy 3.1.0 ended every Genco Tana River member’s season early.'],
              ['', 'Full irrigation', 'Method 1 with SMT 70 % throughout and no seasonal cap: the yield with water no longer limiting.'],
              ['', 'Mulch, 50 % residue cover', 'FieldMngt: mulches on 50 % of the surface, soil evaporation there × 0.5.'],
              ['', 'Tied ridges or pits (no surface runoff)', 'FieldMngt with surface runoff fully inhibited: the rain infiltrates where it falls, as tied ridges or zai pits make it. Not AquaCrop’s bunds, which pond the rain over the whole field like a rice paddy: the waterlogged topsoil stopped most members’ crops at Kapiti, Kiboko and Livemo.'],
            ]}/>
            <h4 className="about-subhead" style={{marginTop:24}}>First results: early maize, FAO onset sowing, 1 Oct 2026 run (observations to 5 Nov)</h4>
            <Tbl head={['Site', 'Outlook (rain-fed)', 'Supplementary irrigation, 100 mm', 'Full irrigation', 'Mulch', 'Tied ridges or pits']} rows={[
              ['El Karama', '1.1 (40 %)', '5.3 (12 %)', '7.6 (0 %), 325 mm', '2.4 (28 %)', '1.6 (32 %)'],
              ['Genco Maralal', '0.0 (76 %)', '0.6 (48 %)', '7.4 (32 %), 414 mm', '0.0 (68 %)', '0.0 (68 %)'],
              ['Genco Tana River', '1.6 (0 %)', '1.9 (0 %)', '5.1 (0 %), 330 mm', '1.7 (0 %)', '1.8 (0 %)'],
              ['KALRO Kiboko', '3.2 (24 %)', '5.5 (8 %)', '5.9 (0 %), 205 mm', '4.3 (16 %)', '3.8 (20 %)'],
              ['Kapiti', '5.7 (12 %)', '7.5 (0 %)', '7.7 (0 %), 273 mm', '5.9 (8 %)', '6.2 (8 %)'],
              ['Livemo Memerush', '1.4 (44 %)', '4.9 (16 %)', '6.0 (0 %), 308 mm', '2.2 (44 %)', '1.7 (44 %)'],
            ]}/>
            <p style={{fontSize:16,color:'var(--text-body)',lineHeight:1.7,margin:'12px 0 0'}}>
              Median yield over all members in t/ha, with the chance of crop failure in brackets; full irrigation with the median water applied.
              In this season 100 mm of supplementary water raises early maize by 0.3–4.2 t/ha and cuts the chance of failure by up to 28 points;
              the water-unlimited yield needs 205–414 mm. Mulch adds up to 1.3 t/ha and tied ridges up to 0.6. At Genco Maralal even full
              irrigation leaves a third of the members failing: there the crop sown on the FAO onset is too late or too cold, not too dry.
              These are one season’s forecast, not general responses.
            </p>
            <p style={{fontSize:16,color:'var(--text-body)',lineHeight:1.7,margin:'12px 0 0'}}>
              The amounts (100 mm of water, half the soil under residues, no runoff from ridges) are the engine’s assumptions. A questionnaire
              asks the managers of the six sites what farmers near them actually do, and the scenarios will be set to their answers:{' '}
              <a href="https://docs.google.com/forms/d/e/1FAIpQLSeSm0ZhEjV3MhBCayBJEdrwtgLh2iBfyzd-b90o56vXo9B9vw/viewform" target="_blank" rel="noreferrer" style={{color:'var(--accent-text)'}}>the online form</a> or{' '}
              <a href="docs/crop_scenario_questions_for_partners.pdf" target="_blank" rel="noreferrer" style={{color:'var(--accent-text)'}}>the questions (PDF)</a>,
              both also linked from the Crop outlook tab.
            </p>
          </S>

          <S title="Hindcast verification" id="about-crop-hindcast" scope="Kenya · Short Rains · ECMWF SEAS5 1 Oct runs, 25 members · 1993–2016 (county yields: maize, 1993–2025)">
            <p style={{fontSize:16,color:'var(--text-body)',lineHeight:1.7,margin:'0 0 16px'}}>
              Does the crop outlook tell good seasons from bad ones, and does it say more than the season-length forecast the platform already gives?
              Each past 1 Oct forecast is rebuilt as it would have been issued: observed weather to 30 Sep, then SEAS5 member k (rain bias-corrected
              to CHIRPS), March from another year’s observed March, each member sown on its own forecast onset. Its crop is scored against the same
              crop grown in that season’s observed weather.
            </p>
            <Step n="1" title="Scores"
              eq={"r       = Spearman( median_k yield_k(y) ,  yield_observed weather(y) )      over the years y\nAUC     = ROC area of P(failure) for the observed-weather failures       failure: yield < 0.5 t/ha (bean 0.2)\nRPSS    = 1 − RPS / RPS_climatology        (leave-one-out terciles; not where a third of the seasons failed)"}
              desc="The baselines are the same scores of the platform’s own season-length (LGP), Oct–Dec rain and onset forecasts read as yield predictors. Seasons already sown before 1 Oct are known, not forecast, so every score is also given over the seasons not sown by 1 Oct." table={[['r','Spearman rank correlation over the hindcast years (1: same ranking)','—'],['median_k yield_k(y)','Median yield over the forecast members k of year y','t/ha'],['yield_observed weather(y)','Yield of the crop grown in the observed weather of year y','t/ha'],['y','Hindcast year','year'],['AUC','Area under the ROC curve of the failure forecasts (0.5: no skill, 1: perfect)','—'],['P(failure)','Share of the members whose crop fails','fraction (0–1)'],['RPSS','Ranked probability skill score of the tercile forecasts (0: no better than climatology, 1: perfect)','—'],['RPS, RPS_climatology','Ranked probability score of the forecast and of the climatological forecast','—']]}/>
            <Tbl head={['Question', 'Result']} rows={[
              ['Agri rule 1 sowing, 1993–2016', 'Skilful for early maize, sorghum and bean at every site (r 0.13–0.70 over the seasons not sown by 1 Oct, failure ROC area 0.61–0.93), but on a par with the season-length forecast rather than better: better at El Karama and Genco Maralal, level at Kiboko and Kapiti, worse at Genco Tana River and Livemo.'],
              ['FAO agricultural onset sowing', 'More seasons succeed (6–17 of 24), so medium maize can be scored. The same conclusion: Livemo early maize r 0.63 against 0.51 for season length, Kapiti bean 0.41 against 0.24; Genco Tana River 0.40 against 0.63, Kiboko 0.51 against 0.62.'],
              ['SEAS5 temperature in place of climatology', 'Over 16 years and both rules (46 cells) the rank correlation changes by 0.0 on average (12 better, 12 worse) and the failure ROC area by +0.002: yield ranks follow the rain, not the temperature. SEAS5 temperature stays in the outlook for its effect on development.'],
              ['County Short Rains maize yields, 1993–2025', 'HarvestStat county yields against the maize forecast, the observed-weather crop and the season-length forecast over 12–16 years. Genco Tana River: forecast r 0.68–0.69, better than season length (0.54–0.56) and the observed-weather crop (0.31–0.51), the only value clearly above noise. Kapiti 0.24–0.41, Livemo 0.13–0.23, Kiboko and El Karama about 0, for all three. A county average mixes sowing dates, varieties, soils and inputs one site’s crop does not have; sorghum and bean have at most two county Short Rains years.'],
            ]}/>
            <p style={{fontSize:16,color:'var(--text-body)',lineHeight:1.7,margin:'12px 0 0'}}>
              With 24 seasons and 1–17 successes per cell, differences of 0.1–0.2 in r are within sampling noise. The reference is a simulation, so
              these scores measure how well the forecast weather reproduces the crop the model grows in the real weather, not yield accuracy.
            </p>
          </S>
        </div>
      )}
       </article>
      </div>
     </div>
    </div>
  )
}
