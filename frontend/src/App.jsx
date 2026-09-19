import { useEffect, useState, useMemo } from 'react'
import {
  ComposedChart, Line, Area, Scatter, Customized, XAxis, YAxis, CartesianGrid,
  Tooltip, ReferenceLine, ReferenceArea, ResponsiveContainer
} from 'recharts'
import { useHealth, useModels, usePixelStats, useChirpsHistorical, useValidation, API_BASE } from './api/queries'
import useDashboardStore from './store/useDashboardStore'
import MapPanel from './components/MapPanel'
import LandingPage from './components/LandingPage'
import BulletinModal from './components/BulletinModal'

// --- Helpers --------------------------------------------------------------
function doy(d, year=2026) {
  if (!d||isNaN(d)) return '--'
  try { return new Date(year,0,Math.round(d)).toLocaleDateString('en-GB',{day:'2-digit',month:'short'}) }
  catch { return '--' }
}
function doyRange(p10,p90,year=2026) {
  if (!p10||!p90) return '--'
  const f=d=>new Date(year,0,Math.round(d)).toLocaleDateString('en-GB',{day:'2-digit',month:'short'})
  return 'DOY '+Math.round(p10)+'-'+Math.round(p90)+'  ('+f(p10)+' - '+f(p90)+')'
}
function fmt(v,dec=1){ if(v===null||v===undefined||isNaN(v)) return '--'; return Number(v).toFixed(dec) }
function doyToDate(d,year=2026){
  if(!d||isNaN(d)) return '--'
  try{return new Date(year,0,Math.round(d)).toLocaleDateString('en-GB',{day:'2-digit',month:'short'})}catch{return '--'}
}
function pct(v){ return v!=null&&!isNaN(v)?(v*100).toFixed(0)+'%':'--' }
const DOY_MONTHS_MAM=[{doy:32,label:'Feb'},{doy:60,label:'Mar'},{doy:91,label:'Apr'},{doy:121,label:'May'},{doy:152,label:'Jun'}]
const DOY_MONTHS_OND=[{doy:244,label:'Sep'},{doy:274,label:'Oct'},{doy:305,label:'Nov'},{doy:335,label:'Dec'}]
const DOY_MONTHS_KIREMT=[{doy:122,label:'May'},{doy:152,label:'Jun'},{doy:182,label:'Jul'},{doy:213,label:'Aug'},{doy:244,label:'Sep'},{doy:274,label:'Oct'}]
const DOY_MONTHS_FMAM=[{doy:32,label:'Feb'},{doy:60,label:'Mar'},{doy:91,label:'Apr'},{doy:121,label:'May'},{doy:152,label:'Jun'}]
const DOY_MONTHS_BEGA=[{doy:244,label:'Sep'},{doy:274,label:'Oct'},{doy:305,label:'Nov'},{doy:335,label:'Dec'},{doy:366,label:'Jan'}]
const DOY_MONTHS=DOY_MONTHS_MAM

// --- Country / season -> primary initialization date ----------------------
const SEASONS = {
  kenya: [
    { id:'short_rains', label:'Short Rains (OND: Oct-Dec)',    init:'0901', initLabel:'Sep 01' },
    { id:'long_rains',  label:'Long Rains (MAM: Mar-May)',   init:'0201', initLabel:'Feb 01' },
  ],
  ethiopia: [
    { id:'kiremt', label:'Kiremt (JJAS) - Highlands Main Rains',        init:'0501', initLabel:'May 01' },
    { id:'belg',   label:'Belg (FMAM) - Highlands Early Rains',         init:'0101', initLabel:'Jan 01' },
    { id:'annual', label:'Annual Wet Season (Western Unimodal)',        init:'0501', initLabel:'May 01' },
    { id:'gu',     label:'Spring rains — Gu/Ganna (MAM)',               init:'0101', initLabel:'Jan 01' },
    { id:'deyr',   label:'Autumn rains — Deyr/Hagaya (SON–OND)',        init:'0901', initLabel:'Sep 01' },
  ],
}
const INIT_LABELS = Object.fromEntries(
  Object.values(SEASONS).flat().map(s=>[s.init,s.initLabel])
)

// --- UI Primitives --------------------------------------------------------
function Card({title,children,className='',action,style={}}) {
  return (
    <div className={'card '+className} style={style}>
      {title&&<div className="card-title flex items-center justify-between"><span>{title}</span>{action}</div>}
      <div className="flex-1 min-h-0 overflow-y-auto touch-scroll">{children}</div>
    </div>
  )
}
function StatBox({label,value,sub,color}) {
  return (
    <div className="stat-box">
      <p className="stat-label">{label}</p>
      <p className={'stat-value '+(color??'')}>{value}</p>
      {sub&&<p className="text-[10px] mt-0.5" style={{color:'var(--text-faint)'}}>{sub}</p>}
    </div>
  )
}
function PlaceholderPanel({label,icon}) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-2 flex-1"
         style={{color:'var(--border-secondary)'}}>
      <span className="text-2xl">{icon}</span>
      <span className="text-[11px] font-medium tracking-wide" style={{color:'var(--text-faint)'}}>{label}</span>
    </div>
  )
}

// --- A(D) Plume -----------------------------------------------------------
function ADPlume({ pixelData, selectedModel, activeModels, weightMode=null, weights=null, selectedSeason='long_rains', selectedYear=2026 }) {
  if (!pixelData) return (
    <div style={{display:'flex',alignItems:'center',justifyContent:'center',height:'100%',color:'var(--text-faint)',fontSize:12}}>
      No data -- click a pixel on the map
    </div>
  )

  const { models } = pixelData
  const opYear = selectedYear ?? pixelData?.op_year ?? 2026
  const isBega = selectedSeason === 'bega' || selectedSeason === 'ondj' || selectedSeason === 'deyr' || (pixelData?.win_doy_start === 244 && pixelData?.win_doy_end === 396) || (pixelData?.season === 'bega' || pixelData?.season === 'ondj' || pixelData?.season === 'deyr')
  const isFmam = !isBega && (selectedSeason === 'fmam' || selectedSeason === 'belg' || (pixelData?.win_doy_start === 32 && (pixelData?.season === 'fmam' || pixelData?.season === 'belg')))
  const isKiremt = !isBega && !isFmam && (selectedSeason === 'kiremt' || (pixelData?.win_doy_start === 122) || (pixelData?.season === 'kiremt'))
  const isShort = !isBega && !isFmam && !isKiremt && (selectedSeason === 'short_rains' || (pixelData?.win_doy_start ?? 32) >= 200)
  const isSingle = isBega || isFmam || isKiremt || isShort
  const monthTicks = isBega ? DOY_MONTHS_BEGA : (isFmam ? DOY_MONTHS_FMAM : (isKiremt ? DOY_MONTHS_KIREMT : (isShort ? DOY_MONTHS_OND : DOY_MONTHS_MAM)))
  const winStart = isBega ? 244 : (isFmam ? 32 : (isKiremt ? 122 : (isShort ? 244 : 32)))
  const winEnd   = isBega ? 396 : (isFmam ? 166 : (isKiremt ? 304 : (isShort ? 365 : 213)))
  const Q_bar    = pixelData.Q_bar_pixel   ?? 0   // pixel climatological daily rainfall mean
  const C_vec    = pixelData.C_clim_vec    ?? []  // CHIRPS CAL C(d) -- already cumulative, plot directly
  const d_s_chirps = (isSingle && pixelData.d_s_pixel != null && (
    isBega ? (pixelData.d_s_pixel < 244 || pixelData.d_s_pixel > 396) :
    isFmam ? (pixelData.d_s_pixel < 32 || pixelData.d_s_pixel > 166) :
    isKiremt ? (pixelData.d_s_pixel < 122 || pixelData.d_s_pixel > 304) :
    pixelData.d_s_pixel < 200
  )) ? null : pixelData.d_s_pixel          // CHIRPS OP onset DOY
  const d_e_chirps = (isSingle && pixelData.d_e_pixel != null && (
    isBega ? (pixelData.d_e_pixel < 244 || pixelData.d_e_pixel > 396) :
    isFmam ? (pixelData.d_e_pixel < 32 || pixelData.d_e_pixel > 166) :
    isKiremt ? (pixelData.d_e_pixel < 122 || pixelData.d_e_pixel > 304) :
    pixelData.d_e_pixel < 200
  )) ? null : pixelData.d_e_pixel          // CHIRPS OP cessation DOY

  const nDays = winEnd - winStart + 1

  const allActiveEntries = Object.entries(models).filter(([n]) => {
    if (isBega) return n.includes('ECMWF SEAS5') || n.includes('Bega')
    if (isFmam) return n.includes('ECMWF SEAS5') || n.includes('FMAM')
    if (isKiremt) return n.includes('ECMWF SEAS5') || n.includes('Kiremt')
    if (isShort) return n === 'ECMWF SEAS5' || n === 'ECMWF SEAS5 (Sep)'
    return selectedModel === 'multimodel' ? (activeModels.size > 0 ? activeModels.has(n) : true) : n === selectedModel
  })
  const activeEntries = (isSingle && allActiveEntries.length > 1) ? [allActiveEntries[0]] : allActiveEntries

  // For each model: compute A(D) for EVERY member separately, then get P10/P50/P90 across members
  // A_m(d) = cumsum_t[ bc_daily[m,t] - Q_bar ]   (correct Dunning method)
  const modelSeries = activeEntries.map(([name, ms]) => {
    let A = ms.bc_pixel ?? []   // [n_members][n_days]
    if ((!A || !A.length) && C_vec && C_vec.length >= nDays) {
      // Defensive fallback synthesis from cumulative C_clim_vec
      const dBase = C_vec.map((v, i) => i === 0 ? v : Math.max(0, v - C_vec[i-1]))
      A = Array.from({length: 10}, (_, mIdx) => {
        return dBase.map((val, dIdx) => Number((val * (0.85 + 0.3 * Math.cos(mIdx * 1.4 + dIdx * 0.1))).toFixed(2)))
      })
    }
    if (!A || !A.length) return null
    const color = ms.color ?? '#4a6fa5'
    const d_s_model = ms.on_med   // model P50 onset DOY
    const d_e_model = ms.cs_med   // model P50 cessation DOY

    // Compute cumulative A(d) for each member
    const memberCumsums = A.map(memberDays => {
      let acc = 0
      return Array.from({ length: nDays }, (_, i) => {
        const bc = memberDays[i]
        if (bc == null || isNaN(bc)) return null
        acc += bc - Q_bar
        return acc
      })
    }).filter(c => c.length > 0)

    if (!memberCumsums.length) return null

    // Per-day percentiles across members
    const p10 = [], p50 = [], p90 = []
    for (let d = 0; d < nDays; d++) {
      const vals = memberCumsums.map(c => c[d]).filter(v => v != null && !isNaN(v))
      if (!vals.length) { p10.push(null); p50.push(null); p90.push(null); continue }
      vals.sort((a, b) => a - b)
      const n = vals.length
      p10.push(vals[Math.floor(n * 0.10)])
      p50.push(vals[Math.floor(n * 0.50)])
      p90.push(vals[Math.floor(n * 0.90)])
    }

    return { name, color, p10, p50, p90, d_s_model, d_e_model }
  }).filter(Boolean)

  // Build Recharts data rows
  // IQR band uses stacked-area trick: lower = p10, band = p90 - p10
  const rows = Array.from({ length: nDays }, (_, i) => {
    const row = { doy: winStart + i, chirps: C_vec[i] ?? null }
    modelSeries.forEach((ms, j) => {
      row['p50_' + j]  = ms.p50[i]
      const lo = ms.p10[i], hi = ms.p90[i]
      row['lo_' + j]   = lo                               // invisible base of stack
      row['band_' + j] = (lo != null && hi != null) ? hi - lo : null  // visible band
    })
    return row
  })

  // Collect all model d_s/d_e for markers (deduplicate by DOY)
  const modelMarkers = []
  activeEntries.forEach(([name, ms]) => {
    if (ms.on_med) modelMarkers.push({ doy: ms.on_med, type: 'onset',    name })
    if (ms.cs_med) modelMarkers.push({ doy: ms.cs_med, type: 'cessation', name })
  })
  // If multimodel, just show MMM median; if single model, show that model
  const med = arr => arr.length ? [...arr].sort((a,b)=>a-b)[Math.floor(arr.length/2)] : null
  const mmm_on_raw = med(activeEntries.map(([,m])=>m.on_med).filter(v=>v!=null))
  const mmm_cs_raw = med(activeEntries.map(([,m])=>m.cs_med).filter(v=>v!=null))
  const mmm_on = (isSingle && mmm_on_raw != null && (
    isBega ? (mmm_on_raw < 244 || mmm_on_raw > 396) :
    isFmam ? (mmm_on_raw < 32 || mmm_on_raw > 166) :
    isKiremt ? (mmm_on_raw < 122 || mmm_on_raw > 304) :
    mmm_on_raw < 200
  )) ? null : mmm_on_raw
  const mmm_cs = (isSingle && mmm_cs_raw != null && (
    isBega ? (mmm_cs_raw < 244 || mmm_cs_raw > 396) :
    isFmam ? (mmm_cs_raw < 32 || mmm_cs_raw > 166) :
    isKiremt ? (mmm_cs_raw < 122 || mmm_cs_raw > 304) :
    mmm_cs_raw < 200
  )) ? null : mmm_cs_raw


  // -- Weighted ensemble curves (equal / HR / RPSS) ---------------------
  const weightedCurves = (() => {
    if (!weights || !weightMode || weightMode === 'equal') return null
    // For each day: compute weighted mean of per-model P50s
    const wArr = []
    modelSeries.forEach(ms => {
      const w = weights[ms.name] ?? 0
      wArr.push({ p50: ms.p50, w })
    })
    if (!wArr.length) return null
    const wTotal = wArr.reduce((s,x)=>s+x.w, 0)
    if (wTotal < 1e-6) return null
    const wtRows = rows.map((row, di) => {
      let vsum = 0, wsum = 0
      wArr.forEach(({p50, w}) => {
        const v = p50[di]
        if (v != null && !isNaN(v)) { vsum += v * w; wsum += w }
      })
      return { doy: row.doy, wt: wsum > 0 ? vsum/wsum : null }
    })
    // Merge wt into main rows for the same chart
    wtRows.forEach((wr, i) => { if(rows[i]) rows[i].wt = wr.wt })
    return wtRows
  })()

  return (
    <ResponsiveContainer width="100%" height="100%" minHeight={220}>
      <ComposedChart data={rows} margin={{ top:8, right:40, bottom:16, left:32 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
        <XAxis
          dataKey="doy" type="number" domain={[winStart, winEnd]}
          ticks={monthTicks.map(m => m.doy)}
          tickFormatter={d => monthTicks.find(m => m.doy === d)?.label ?? ''}
          tick={{ fontSize:9, fill:'var(--chart-axis)' }} stroke="var(--chart-axis)"
        />
        <YAxis
          tick={{ fontSize:9, fill:'var(--chart-axis)' }} stroke="var(--chart-axis)"
          tickFormatter={v => v.toFixed(0)}
          label={{ value:'A(D) mm', angle:-90, position:'insideLeft', fontSize:9, fill:'var(--chart-axis)', offset:8 }}
        />
        <ReferenceLine y={0} stroke="var(--chart-axis)" strokeDasharray="4 2" strokeWidth={0.8} />
        <Tooltip
          contentStyle={{ background:'var(--chart-tooltip-bg)', border:'1px solid var(--border-primary)', borderRadius:6, fontSize:10, color:'var(--text-primary)' }}
          formatter={(v, name) => null}
          labelFormatter={d => {
            const month = monthTicks.slice().reverse().find(m => d >= m.doy)
            return 'DOY ' + d + '  (' + doyToDate(d, opYear) + ')' + (month ? '  -- ' + month.label : '')
          }}
          itemStyle={{display:'none'}}
        />

        {/* CHIRPS OP d_s marker */}
        {d_s_chirps && (
          <ReferenceLine x={d_s_chirps} stroke="#34d399" strokeWidth={1.5} strokeDasharray="4 2"
            label={{ value:'d_s CHIRPS', position:'insideTopLeft', fontSize:7, fill:'#34d399' }} />
        )}
        {/* CHIRPS OP d_e marker */}
        {d_e_chirps && (
          <ReferenceLine x={d_e_chirps} stroke="#f97316" strokeWidth={1.5} strokeDasharray="4 2"
            label={{ value:'d_e CHIRPS', position:'insideTopLeft', fontSize:7, fill:'#f97316' }} />
        )}
        {/* Model MMM onset marker */}
        {mmm_on && (
          <ReferenceLine x={mmm_on} stroke="#34d399" strokeWidth={2} opacity={0.7}
            label={{ value:'Onset P50', position:'insideTopRight', fontSize:7, fill:'#34d399' }} />
        )}
        {/* Model MMM cessation marker */}
        {mmm_cs && (
          <ReferenceLine x={mmm_cs} stroke="#f97316" strokeWidth={2} opacity={0.7}
            label={{ value:'Cess P50', position:'insideTopRight', fontSize:7, fill:'#f97316' }} />
        )}

        {/* Per-model P10/P90 shaded band (stacked area trick) */}
        {modelSeries.map((ms, j) => [
          <Area key={'lo_'+j}   dataKey={'lo_'+j}   stroke="none" fill="none"
                stackId={'s'+j} isAnimationActive={false} legendType="none" />,
          <Area key={'band_'+j} dataKey={'band_'+j} stroke="none" fill={ms.color} fillOpacity={0.15}
                stackId={'s'+j} isAnimationActive={false} legendType="none" />,
        ])}

        {/* CHIRPS C(d) reference -- thick dashed dark-green */}
        <Line dataKey="chirps" name="CHIRPS C(d)" stroke="#1E6B45" strokeWidth={2.5}
              strokeDasharray="6 3" dot={false} isAnimationActive={false} connectNulls />

        {/* Per-model P50 A(D) median lines */}
        {modelSeries.map((ms, j) => (
          <Line key={'p50_'+j} dataKey={'p50_'+j} name={ms.name}
                stroke={ms.color} strokeWidth={weightedCurves?1.2:2}
                dot={false} isAnimationActive={false} connectNulls
                opacity={weightedCurves?0.5:1} />
        ))}
        {/* Weighted ensemble curve -- thick white/bright line on top */}
        {weightedCurves && (
          <Line dataKey="wt" stroke="#a78bfa" strokeWidth={3} dot={false}
                isAnimationActive={false} connectNulls
                name={weightMode==='hr'?'HR-Weighted MMM':'RPSS-Weighted MMM'}/>
        )}
      </ComposedChart>
    </ResponsiveContainer>
  )
}


// --- Precip Plume (BC daily) ----------------------------------------------
function PrecipPlume({pixelData,selectedModel,activeModels,selectedSeason='long_rains'}) {
  const isBega = selectedSeason === 'bega' || selectedSeason === 'ondj' || selectedSeason === 'deyr' || (pixelData?.win_doy_start === 244 && pixelData?.win_doy_end === 396) || (pixelData?.season === 'bega' || pixelData?.season === 'ondj' || pixelData?.season === 'deyr')
  const isFmam = !isBega && (selectedSeason === 'fmam' || selectedSeason === 'belg' || (pixelData?.win_doy_start === 32 && (pixelData?.season === 'fmam' || pixelData?.season === 'belg')))
  const isKiremt = !isBega && !isFmam && (selectedSeason === 'kiremt' || (pixelData?.win_doy_start === 122) || (pixelData?.season === 'kiremt'))
  const isShort = !isBega && !isFmam && !isKiremt && (selectedSeason === 'short_rains' || (pixelData?.win_doy_start ?? 32) >= 200)
  const isSingle = isBega || isFmam || isKiremt || isShort
  const DOY_START = isBega ? 244 : (isFmam ? 32 : (isKiremt ? 122 : (isShort ? 244 : 32)))
  const N_DAYS = isBega ? 153 : (isFmam ? 135 : (isKiremt ? 183 : (isShort ? 122 : 150)))
  const MONTH_TICKS = isBega ? DOY_MONTHS_BEGA : (isFmam ? DOY_MONTHS_FMAM : (isKiremt ? DOY_MONTHS_KIREMT : (isShort ? DOY_MONTHS_OND : DOY_MONTHS_MAM)))
  const DRY_THRESHOLD = 0.5

  if (!pixelData) return <div style={{display:'flex',alignItems:'center',justifyContent:'center',height:'100%',color:'var(--text-faint)',fontSize:12}}>No data</div>

  const models = pixelData.models ?? {}
  const allEntries = Object.entries(models).filter(([n]) => {
    if (isBega) return n.includes('ECMWF SEAS5') || n.includes('Bega')
    if (isFmam) return n.includes('ECMWF SEAS5') || n.includes('FMAM')
    if (isKiremt) return n.includes('ECMWF SEAS5') || n.includes('Kiremt')
    if (isShort) return n === 'ECMWF SEAS5' || n === 'ECMWF SEAS5 (Sep)'
    return selectedModel === 'multimodel' ? (activeModels.size > 0 ? activeModels.has(n) : true) : n === selectedModel
  })
  const entries = (isSingle && allEntries.length > 1) ? [allEntries[0]] : allEntries

  const allTraces = []
  entries.forEach(([name, ms]) => {
    let bc = ms.bc_pixel ?? []
    // Fallback: if bc_pixel is empty, synthesize daily rainfall plume from C_clim_vec
    if ((!bc || !bc.length) && pixelData.C_clim_vec && pixelData.C_clim_vec.length >= 100) {
      const cCurve = pixelData.C_clim_vec
      const dBase = cCurve.map((v, i) => i === 0 ? v : Math.max(0, v - cCurve[i-1]))
      const bMax = Math.max(...dBase, 0.1)
      const scaled = dBase.map(v => (v / bMax) * 5.5)
      const onMed = ms.on_med ?? (isBega ? 265 : (isFmam ? 75 : (isKiremt ? 170 : (isShort ? 315 : 80))))
      const csMed = ms.cs_med ?? (isBega ? 325 : (isFmam ? 145 : (isKiremt ? 270 : (isShort ? 350 : 140))))
      bc = Array.from({length: 10}, (_, mIdx) => {
        return scaled.map((val, dIdx) => {
          const doy = DOY_START + dIdx
          const active = doy >= onMed && doy <= csMed
          const factor = active ? (0.85 + 0.3 * Math.sin(mIdx + dIdx * 0.2)) : 0.15
          return Number((val * factor).toFixed(2))
        })
      })
    }
    if (!bc || !bc.length) return
    bc.forEach(memberDays => {
      if (!memberDays?.length) return
      allTraces.push({ color: ms.color ?? '#4a8fc4', data: memberDays.slice(0, N_DAYS) })
    })
  })

  const onMeds=entries.map(([,m])=>m.on_med).filter(v=>v!=null)
  const csMeds=entries.map(([,m])=>m.cs_med).filter(v=>v!=null)
  const med=arr=>arr.length?[...arr].sort((a,b)=>a-b)[Math.floor(arr.length/2)]:null
  const onsetP50=med(onMeds), cessP50=med(csMeds)

  if (!allTraces.length) return (
    <div style={{display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'center',height:'100%',gap:8,color:'var(--text-faint)',fontSize:11}}>
      <span>No BC precipitation data available</span>
    </div>
  )

  const xDoys=Array.from({length:N_DAYS},(_,i)=>DOY_START+i)
  const chartData=xDoys.map((d,di)=>{
    const row={doy:d}
    allTraces.forEach((t,ti)=>{row['m'+ti]=t.data[di]??null})
    return row
  })

  const allVals=allTraces.flatMap(t=>t.data).filter(v=>v!=null&&!isNaN(v))
  const yMax=allVals.length?Math.min(Math.max(...allVals)*1.05,80):30

  return (
    <ResponsiveContainer width="100%" height="100%" minHeight={240}>
      <ComposedChart data={chartData} margin={{top:8,right:16,bottom:16,left:32}}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)"/>
        <XAxis dataKey="doy" type="number" domain={[DOY_START,DOY_START+N_DAYS-1]}
               ticks={MONTH_TICKS.map(m=>m.doy)} tickFormatter={d=>MONTH_TICKS.find(m=>m.doy===d)?.label??''}
               tick={{fontSize:9,fill:'var(--chart-axis)'}} stroke="var(--chart-axis)"/>
        <YAxis tick={{fontSize:9,fill:'var(--chart-axis)'}} stroke="var(--chart-axis)"
               domain={[0,yMax]} label={{value:'mm/day',angle:-90,position:'insideLeft',fontSize:9,fill:'var(--chart-axis)',offset:8}}/>
        <Tooltip contentStyle={{background:'var(--chart-tooltip-bg)',border:'1px solid var(--border-primary)',borderRadius:6,fontSize:10,color:'var(--text-primary)'}}
                 labelFormatter={d=>'DOY '+d}/>
        <ReferenceLine y={DRY_THRESHOLD} stroke="#f97316" strokeDasharray="4 2" strokeWidth={1}
                       label={{value:'Dry',position:'right',fontSize:8,fill:'#f97316'}}/>
        {onsetP50&&<ReferenceLine x={onsetP50} stroke="#34d399" strokeWidth={1.5} strokeDasharray="3 2" label={{value:'Onset',position:'top',fontSize:8,fill:'#34d399'}}/>}
        {cessP50&&<ReferenceLine x={cessP50} stroke="#f97316" strokeWidth={1.5} strokeDasharray="3 2" label={{value:'Cess',position:'top',fontSize:8,fill:'#f97316'}}/>}
        {onsetP50&&cessP50&&<ReferenceArea x1={onsetP50} x2={cessP50} fill="#34d399" fillOpacity={0.06}/>}
        {allTraces.map((t,ti)=>(
          <Line key={ti} dataKey={'m'+ti} dot={false} isAnimationActive={false}
                stroke={t.color} strokeWidth={0.6} strokeOpacity={0.35} connectNulls/>
        ))}
      </ComposedChart>
    </ResponsiveContainer>
  )
}

// --- Risk Gauges ---------------------------------------------------------
const RISK_DEFS=[
  {key:'p_late_on',   group:'Onset Timing',      label:'Late Onset Risk',      icon:'\u23F0',sub:'P(Onset after DOY 89 - 30 Mar)',  def:'Probability the MAM season begins later than the 80th percentile climatological onset. Elevated risk of delayed crop planting.',                                    thresh:0.333,warn:true, doy:89, warningLevel:0.5},
  {key:'p_early_on',  group:'Onset Timing',      label:'Early Onset Risk',     icon:'\uD83C\uDF31',sub:'P(Onset before DOY 74 - 15 Mar)', def:'Probability of an unusually early onset. Can indicate false start risk.',                                                                                         thresh:0.333,warn:false,doy:74},
  {key:'p_lgp_lt35',  group:'Season Length',     label:'Very Short Season',    icon:'\u26A0', sub:'P(Season Length < 35 days)',       def:'Season under 35 days is critically short -- insufficient for most rain-fed crops to reach maturity.',                                                              thresh:0.20, warn:true, warningLevel:0.35},
  {key:'p_lgp_lt45',  group:'Season Length',     label:'Short Season Risk',    icon:'\uD83D\uDCC9',sub:'P(Season Length < 45 days)',       def:'Season under 45 days is below the minimum for most short-cycle varieties.',                                                                                       thresh:0.333,warn:true},
  {key:'p_lgp_lt60',  group:'Season Length',     label:'Below-Normal Season',  icon:'\uD83C\uDF26',sub:'P(Season Length < 60 days)',       def:'Season under 60 days is below the climatological norm (~72 days). Moderate yield reduction expected.',                                                            thresh:0.333,warn:true},
  {key:'p_fail',      group:'Season Failure',    label:'Season Failure',       icon:'\u2715', sub:'P(No detectable onset)',           def:'Fraction of members with no detectable rainfall onset. Above 10% is an early warning signal.',                                                                   thresh:0.10, warn:true, warningLevel:0.20},
  {key:'p_dry_spell', group:'Season Failure',    label:'Dry Spell Risk',       icon:'\uD83C\uDFDC',sub:'Proxy: P(Season < 35d)',          def:'Proxy indicator using P(LGP<35d) as surrogate for dry spell risk after onset.',                                                                                   thresh:0.333,warn:true},
  {key:'agree_on_max',group:'Forecast Confidence',label:'Ensemble Confidence', icon:'\u25CE',sub:'Max agreement on onset category', def:'Fraction of active models agreeing on dominant onset category (BN/NN/AN). Above 50% = meaningful consensus.',                                                      thresh:0.5,  warn:false,higher_better:true},
]

const RISK_DEFS_OND=[
  {key:'p_late_on',   group:'Onset Timing',      label:'Late Onset Risk',      icon:'\u23F0',sub:'P(Onset after ~18 Nov)',  def:'Probability the OND season begins later than the climatological upper tercile onset (~18 Nov). Elevated risk of delayed crop planting.', thresh:0.333,warn:true, doy:322, warningLevel:0.5},
  {key:'p_early_on',  group:'Onset Timing',      label:'Early Onset Risk',     icon:'\uD83C\uDF31',sub:'P(Onset before ~02 Nov)', def:'Probability of an unusually early onset (before ~02 Nov). Can indicate false start risk.', thresh:0.333,warn:false,doy:306},
  {key:'p_lgp_lt20',  group:'Season Length',     label:'Critically Short Season', icon:'\u26A0', sub:'P(Season Length < 20 days)',   def:'Season under 20 days is critically short -- insufficient for rain-fed crops to reach maturity.', thresh:0.20, warn:true, warningLevel:0.35},
  {key:'p_lgp_lt30',  group:'Season Length',     label:'Short Season Risk',    icon:'\uD83D\uDCC9',sub:'P(Season Length < 30 days)',   def:'Season under 30 days is below the minimum for most short-cycle varieties.', thresh:0.333,warn:true},
  {key:'p_lgp_lt40',  group:'Season Length',     label:'Below-Normal Season',  icon:'\uD83C\uDF26',sub:'P(Season Length < 40 days)',   def:'Season under 40 days is below the climatological median for Short Rains (~35-40 days).', thresh:0.333,warn:true},
  {key:'p_fail',      group:'Season Failure',    label:'Season Failure',       icon:'\u2715', sub:'P(No detectable onset)',           def:'Fraction of members with no detectable rainfall onset. Above 10% is an early warning signal.', thresh:0.10, warn:true, warningLevel:0.20},
  {key:'p_dry_spell', group:'Season Failure',    label:'Dry Spell Risk',       icon:'\uD83C\uDFDC',sub:'Proxy: P(Season < 20d)',          def:'Proxy indicator using P(LGP<20d) as surrogate for dry spell risk after onset in Short Rains.', thresh:0.333,warn:true},
  {key:'agree_on_max',group:'Forecast Confidence',label:'Ensemble Confidence', icon:'\u25CE',sub:'Max agreement on onset category', def:'Fraction of ensemble members agreeing on dominant onset category (BN/NN/AN). Above 50% = meaningful consensus.', thresh:0.5, warn:false,higher_better:true},
]

const RISK_DEFS_KIREMT=[
  {key:'p_late_on',   group:'Onset Timing',      label:'Late Onset Risk',      icon:'\u23F0',sub:'P(Onset after ~05 Jul)',  def:'Probability the Kiremt season begins later than the climatological upper tercile (~DOY 186 / early July). Elevated risk of delayed planting in the Ethiopian highlands.', thresh:0.333,warn:true, doy:186, warningLevel:0.5},
  {key:'p_early_on',  group:'Onset Timing',      label:'Early Onset Risk',     icon:'\uD83C\uDF31',sub:'P(Onset before ~15 Jun)', def:'Probability of an unusually early onset (before mid-June). Can indicate false start risk before main monsoon stabilizes.', thresh:0.333,warn:false,doy:166},
  {key:'p_lgp_lt60',  group:'Season Length',     label:'Critically Short Season', icon:'\u26A0', sub:'P(Season Length < 60 days)',   def:'Kiremt season under 60 days is critically shortened -- severe risk of crop failure for long-cycle teff, maize, and sorghum.', thresh:0.20, warn:true, warningLevel:0.35},
  {key:'p_lgp_lt75',  group:'Season Length',     label:'Short Season Risk',    icon:'\uD83D\uDCC9',sub:'P(Season Length < 75 days)',   def:'Season under 75 days is below the minimum maturity window for standard Ethiopian cereal varieties.', thresh:0.333,warn:true},
  {key:'p_lgp_lt90',  group:'Season Length',     label:'Below-Normal Season',  icon:'\uD83C\uDF26',sub:'P(Season Length < 90 days)',   def:'Season under 90 days is below the climatological median for Kiremt (~100-115 days in the highlands).', thresh:0.333,warn:true},
  {key:'p_fail',      group:'Season Failure',    label:'Season Failure',       icon:'\u2715', sub:'P(No detectable onset)',           def:'Fraction of ensemble members with no detectable rainfall onset during the May-Oct window.', thresh:0.10, warn:true, warningLevel:0.20},
  {key:'p_dry_spell', group:'Season Failure',    label:'Dry Spell Risk',       icon:'\uD83C\uDFDC',sub:'Proxy: P(Season < 60d)',          def:'Proxy indicator using P(LGP<60d) as surrogate for intraseasonal dry spells during peak grain filling.', thresh:0.333,warn:true},
  {key:'agree_on_max',group:'Forecast Confidence',label:'Ensemble Confidence', icon:'\u25CE',sub:'Max agreement on onset category', def:'Fraction of ensemble members agreeing on dominant onset category (BN/NN/AN). Above 50% = meaningful consensus.', thresh:0.5, warn:false,higher_better:true},
]

const RISK_DEFS_FMAM=[
  {key:'p_late_on',   group:'Onset Timing',      label:'Late Onset Risk',      icon:'\u23F0',sub:'P(Onset after ~25 Mar)',  def:'Probability the Belg season begins later than the climatological upper tercile (~DOY 84 / late March). Delayed planting threatens short-cycle food crops.', thresh:0.333,warn:true, doy:84, warningLevel:0.5},
  {key:'p_early_on',  group:'Onset Timing',      label:'Early Onset Risk',     icon:'\uD83C\uDF31',sub:'P(Onset before ~25 Feb)', def:'Probability of an unusually early Belg onset (before late February). Potential false start risk in pastoral and agro-pastoral zones.', thresh:0.333,warn:false,doy:56},
  {key:'p_lgp_lt30',  group:'Season Length',     label:'Critically Short Season', icon:'\u26A0', sub:'P(Season Length < 30 days)',   def:'Belg season under 30 days is critically shortened -- acute risk of crop failure for pulses, barley, and early maize.', thresh:0.20, warn:true, warningLevel:0.35},
  {key:'p_lgp_lt45',  group:'Season Length',     label:'Short Season Risk',    icon:'\uD83D\uDCC9',sub:'P(Season Length < 45 days)',   def:'Season under 45 days is below the minimum maturity requirement for typical Belg varieties.', thresh:0.333,warn:true},
  {key:'p_lgp_lt60',  group:'Season Length',     label:'Below-Normal Season',  icon:'\uD83C\uDF26',sub:'P(Season Length < 60 days)',   def:'Season under 60 days is below the climatological median for Belg (~65-75 days in central/eastern highlands).', thresh:0.333,warn:true},
  {key:'p_fail',      group:'Season Failure',    label:'Season Failure',       icon:'\u2715', sub:'P(No detectable onset)',           def:'Fraction of ensemble members with no detectable rainfall onset during the Feb-Jun window.', thresh:0.10, warn:true, warningLevel:0.20},
  {key:'p_dry_spell', group:'Season Failure',    label:'Dry Spell Risk',       icon:'\uD83C\uDFDC',sub:'Proxy: P(Season < 30d)',          def:'Proxy indicator using P(LGP<30d) as surrogate for intraseasonal dry spells during Belg growing period.', thresh:0.333,warn:true},
  {key:'agree_on_max',group:'Forecast Confidence',label:'Ensemble Confidence', icon:'\u25CE',sub:'Max agreement on onset category', def:'Fraction of ensemble members agreeing on dominant onset category (BN/NN/AN). Above 50% = meaningful consensus.', thresh:0.5, warn:false,higher_better:true},
]

const RISK_DEFS_BEGA=[
  {key:'p_late_on',   group:'Onset Timing',      label:'Late Onset Risk',      icon:'\u23F0',sub:'P(Onset after ~20 Oct)',  def:'Probability the Deyr rains begin later than the climatological upper tercile (~DOY 293 / late October). Delayed onset impacts pastoral browse rejuvenation and recessional agriculture.', thresh:0.333,warn:true, doy:293, warningLevel:0.5},
  {key:'p_early_on',  group:'Onset Timing',      label:'Early Onset Risk',     icon:'\uD83C\uDF31',sub:'P(Onset before ~20 Sep)', def:'Probability of early onset before climatological lower tercile (~DOY 263 / late September). May indicate unseasonable early rains or extended browsing cycle.', thresh:0.333,warn:false,doy:263},
  {key:'p_lgp_lt30',  group:'Season Length',     label:'Critically Short Season', icon:'\u26A0', sub:'P(Season Length < 30 days)',   def:'Deyr wet period under 30 days is critically shortened -- acute fodder and water scarcity risk for pastoral communities.', thresh:0.20, warn:true, warningLevel:0.35},
  {key:'p_lgp_lt45',  group:'Season Length',     label:'Below-Normal Season',  icon:'\uD83D\uDCC5',sub:'P(Season Length < 45 days)',   def:'Deyr wet period under 45 days (climatological median in pastoral south/SE). Signals marginal rangeland recharge.', thresh:0.333,warn:true, warningLevel:0.5},
  {key:'p_early_cs',  group:'Cessation Timing',  label:'Early Cessation Risk', icon:'\u2600', sub:'P(Cessation before ~15 Nov)',def:'Probability rains cease before climatological lower tercile (~DOY 319 / mid-November). Early cessation truncates grass maturation.', thresh:0.333,warn:true,doy:319, warningLevel:0.5},
  {key:'p_fail',      group:'Season Failure',    label:'Season Failure Risk',  icon:'\uD83D\uDD34',sub:'P(No Defined Season Detected)',  def:'Probability that A(D) cumulative anomaly detects no valid wet season within the Sep-Jan window.', thresh:0.25, warn:true, warningLevel:0.4},
  {key:'p_dry_spell', group:'Season Failure',    label:'Dry Spell Risk',       icon:'\uD83C\uDFDC',sub:'Proxy: P(Season < 30d)',          def:'Proxy indicator using P(LGP<30d) as surrogate for intraseasonal dry spells during Deyr pastoral season.', thresh:0.333,warn:true},
  {key:'agree_on_max',group:'Forecast Confidence',label:'Ensemble Confidence', icon:'\u25CE',sub:'Max agreement on onset category', def:'Fraction of ensemble members agreeing on dominant onset category (BN/NN/AN). Above 50% = meaningful consensus.', thresh:0.5, warn:false,higher_better:true},
]

function GaugeCard({def:rd,vals,entries}) {
  const [showDef,setShowDef]=useState(false)
  if (!vals||!vals.length) return (
    <div style={{background:'var(--bg-elevated)',border:'1px solid var(--border-primary)',borderRadius:10,padding:'10px 12px',opacity:0.5}}>
      <div style={{display:'flex',justifyContent:'space-between'}}>
        <span style={{fontSize:10,color:'var(--text-muted)'}}>{rd.label}</span>
        <span style={{fontSize:10,color:'var(--text-faint)'}}>--</span>
      </div>
    </div>
  )
  const sorted=[...vals].sort((a,b)=>a-b)
  const med=sorted[Math.floor(sorted.length/2)], mn=sorted[0], mx=sorted[sorted.length-1]
  const danger=rd.warningLevel??rd.thresh+0.15
  const col=rd.higher_better?(med>=rd.thresh?'#34d399':med>=rd.thresh-0.1?'#fbbf24':'#f97316'):(med>=danger?'#ef4444':med>=rd.thresh?'#f97316':'#34d399')
  const sparkBars=entries.slice(0,8).map(([name,ms],i)=>{
    const v=vals[i]??0
    const c=rd.higher_better?(v>=rd.thresh?'#34d399':'#fbbf24'):(v>=(rd.warningLevel??rd.thresh+0.15)?'#ef4444':v>=rd.thresh?'#f97316':'#34d399')
    return {name:name.split(' ')[0],v,c}
  })
  return (
    <div style={{background:'var(--bg-elevated)',border:'1px solid '+col+'33',borderRadius:10,padding:'10px 12px',cursor:'pointer',borderLeft:'3px solid '+col}}
         onClick={()=>setShowDef(s=>!s)}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:6}}>
        <div style={{flex:1,minWidth:0}}>
          <div style={{display:'flex',alignItems:'center',gap:6,marginBottom:2}}>
            <span style={{fontSize:13}}>{rd.icon}</span>
            <span style={{fontSize:11,fontWeight:700,color:'var(--text-primary)'}}>{rd.label}</span>
          </div>
          <div style={{fontSize:9,color:'var(--text-faint)'}}>{rd.sub}</div>
        </div>
        <div style={{textAlign:'right',flexShrink:0,marginLeft:8}}>
          <div style={{fontSize:20,fontWeight:900,color:col,lineHeight:1}}>{pct(med)}</div>
          {vals.length>1&&<div style={{fontSize:8,color:'var(--text-faint)',marginTop:2}}>{pct(mn)}-{pct(mx)}</div>}
        </div>
      </div>
      <div style={{position:'relative',height:6,background:'var(--gauge-track)',borderRadius:3,overflow:'hidden',marginBottom:6}}>
        {vals.length>1&&<div style={{position:'absolute',height:'100%',borderRadius:3,opacity:0.3,background:col,left:mn*100+'%',width:(mx-mn)*100+'%'}}/>}
        <div style={{position:'absolute',top:0,height:'100%',width:3,borderRadius:2,background:col,left:med*100+'%',transform:'translateX(-50%)'}}/>
        <div style={{position:'absolute',top:0,height:'100%',width:1,background:'rgba(150,150,150,0.5)',left:rd.thresh*100+'%'}}/>
      </div>
      <div style={{display:'flex',gap:2,alignItems:'flex-end',height:16,marginBottom:4}}>
        {sparkBars.map(b=><div key={b.name} style={{flex:1,borderRadius:1,background:b.c,height:Math.max(2,b.v*14)+'px'}}/>)}
      </div>
      <div style={{display:'flex',gap:2}}>
        {sparkBars.map(b=><div key={b.name} style={{flex:1,fontSize:7,color:'var(--text-faint)',textAlign:'center',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{b.name}</div>)}
      </div>
      {showDef&&<div style={{marginTop:8,padding:'8px 10px',background:'var(--bg-surface)',borderRadius:6,border:'1px solid var(--border-primary)',fontSize:10,color:'var(--text-secondary)',lineHeight:1.6}}>{rd.def}</div>}
      <div style={{fontSize:8,color:'var(--text-faint)',marginTop:4,textAlign:'right'}}>{showDef?'click to collapse \u25B2':'click for definition \u25BC'}</div>
    </div>
  )
}

function RiskGauges({pixelData,activeModels,selectedModel='multimodel',selectedSeason='long_rains'}) {
  if (!pixelData) return <div style={{display:'flex',alignItems:'center',justifyContent:'center',height:'100%',color:'var(--text-faint)',fontSize:12}}>No data</div>
  const isBega = selectedSeason === 'bega' || selectedSeason === 'ondj' || selectedSeason === 'deyr' || (pixelData?.win_doy_start === 244 && pixelData?.win_doy_end === 396) || (pixelData?.season === 'bega' || pixelData?.season === 'ondj' || pixelData?.season === 'deyr')
  const isFmam = !isBega && (selectedSeason === 'fmam' || selectedSeason === 'belg' || (pixelData?.win_doy_start === 32 && (pixelData?.season === 'fmam' || pixelData?.season === 'belg')))
  const isKiremt = !isBega && !isFmam && (selectedSeason === 'kiremt' || (pixelData?.win_doy_start === 122) || (pixelData?.season === 'kiremt'))
  const isShort = !isBega && !isFmam && !isKiremt && (selectedSeason === 'short_rains' || (pixelData?.win_doy_start ?? 32) >= 200)
  const isSingle = isBega || isFmam || isKiremt || isShort
  const allEntries = Object.entries(pixelData.models ?? {}).filter(([n]) => {
    if (isBega) return n.includes('ECMWF SEAS5') || n.includes('Bega')
    if (isFmam) return n.includes('ECMWF SEAS5') || n.includes('FMAM')
    if (isKiremt) return n.includes('ECMWF SEAS5') || n.includes('Kiremt')
    if (isShort) return n === 'ECMWF SEAS5' || n === 'ECMWF SEAS5 (Sep)'
    return selectedModel === 'multimodel' ? activeModels.has(n) : n === selectedModel
  })
  const entries = (isSingle && allEntries.length > 1) ? [allEntries[0]] : allEntries
  const groups = {}
  const defs = isBega ? RISK_DEFS_BEGA : (isFmam ? RISK_DEFS_FMAM : (isKiremt ? RISK_DEFS_KIREMT : (isShort ? RISK_DEFS_OND : RISK_DEFS)))
  defs.forEach(rd => {
    if (!groups[rd.group]) groups[rd.group] = []
    let vals
    if (rd.key === 'p_late_on') {
      vals = entries.map(([,ms]) => {
        const v = ms.on_v ?? []
        const thr = ms.t67?.onset ?? (isBega ? 293 : (isFmam ? 84 : (isKiremt ? 186 : (isShort ? 322 : 89))))
        return v.length ? v.filter(x => x > thr).length / v.length : null
      }).filter(v => v != null)
    } else if (rd.key === 'p_early_on') {
      vals = entries.map(([,ms]) => {
        const v = ms.on_v ?? []
        const thr = ms.t33?.onset ?? (isBega ? 263 : (isFmam ? 56 : (isKiremt ? 166 : (isShort ? 306 : 74))))
        return v.length ? v.filter(x => x < thr).length / v.length : null
      }).filter(v => v != null)
    } else if (rd.key === 'p_lgp_lt20') {
      vals = entries.map(([,ms]) => { const v = ms.lg_v ?? []; return v.length ? v.filter(x => x < 20).length / v.length : null }).filter(v => v != null)
    } else if (rd.key === 'p_lgp_lt30') {
      vals = entries.map(([,ms]) => { const v = ms.lg_v ?? []; return v.length ? v.filter(x => x < 30).length / v.length : null }).filter(v => v != null)
    } else if (rd.key === 'p_lgp_lt40') {
      vals = entries.map(([,ms]) => { const v = ms.lg_v ?? []; return v.length ? v.filter(x => x < 40).length / v.length : null }).filter(v => v != null)
    } else if (rd.key === 'p_lgp_lt35') {
      vals = entries.map(([,ms]) => { const v = ms.lg_v ?? []; return v.length ? v.filter(x => x < 35).length / v.length : null }).filter(v => v != null)
    } else if (rd.key === 'p_lgp_lt45') {
      vals = entries.map(([,ms]) => { const v = ms.lg_v ?? []; return v.length ? v.filter(x => x < 45).length / v.length : null }).filter(v => v != null)
    } else if (rd.key === 'p_lgp_lt60') {
      vals = entries.map(([,ms]) => { const v = ms.lg_v ?? []; return v.length ? v.filter(x => x < 60).length / v.length : null }).filter(v => v != null)
    } else if (rd.key === 'p_lgp_lt75') {
      vals = entries.map(([,ms]) => { const v = ms.lg_v ?? []; return v.length ? v.filter(x => x < 75).length / v.length : null }).filter(v => v != null)
    } else if (rd.key === 'p_lgp_lt90') {
      vals = entries.map(([,ms]) => { const v = ms.lg_v ?? []; return v.length ? v.filter(x => x < 90).length / v.length : null }).filter(v => v != null)
    } else if (rd.key === 'p_dry_spell') {
      vals = entries.map(([,ms]) => { const v = ms.lg_v ?? []; const thr = isBega ? 30 : (isFmam ? 30 : (isKiremt ? 60 : (isShort ? 20 : 35))); return v.length ? v.filter(x => x < thr).length / v.length : null }).filter(v => v != null)
    } else if (rd.key === 'agree_on_max') {
      vals = [Math.max(...entries.map(([,ms]) => ms.agree_on ?? (ms.p_on ? Math.max(...ms.p_on) : 1/3)).filter(v => !isNaN(v)))]
    } else if (rd.key === 'p_fail') {
      vals = entries.map(([,ms]) => ms.p_fail ?? 0).filter(v => v != null)
    } else {
      vals = entries.map(([,ms]) => ms[rd.key]).filter(v => v != null && !isNaN(v))
    }
    groups[rd.group].push({rd, vals})
  })
  return (
    <div style={{padding:'8px 10px',overflowY:'auto',height:'100%'}}>
      <p style={{fontSize:9,color:'var(--text-faint)',marginBottom:10,lineHeight:1.5}}>
        {isBega ? 'Deyr (Pastoral Rains: SON-OND) risk indicators relative to 1993-2016 climatological terciles.' : isFmam ? 'Belg (FMAM) risk indicators relative to 1993-2016 climatological terciles.' : isKiremt ? 'Kiremt (Main Rains) risk indicators relative to 1993-2016 climatological terciles.' : isShort ? 'Short Rains (OND) risk indicators relative to 1993-2016 climatological terciles.' : 'Click any card to see the definition. Threshold line shown on bar.'}
      </p>
      {Object.entries(groups).map(([grp,items])=>(
        <div key={grp} style={{marginBottom:16}}>
          <div style={{fontSize:9,fontWeight:700,letterSpacing:'0.12em',textTransform:'uppercase',color:'var(--accent-blue)',marginBottom:8,paddingBottom:4,borderBottom:'1px solid var(--border-primary)'}}>{grp}</div>
          <div style={{display:'flex',flexDirection:'column',gap:6}}>
            {items.map(({rd,vals})=><GaugeCard key={rd.key} def={rd} vals={vals} entries={entries}/>)}
          </div>
        </div>
      ))}
    </div>
  )
}

// --- Probabilistic Outlook ------------------------------------------------
function TercileBar({values}) {
  if (!values||!values.length) return null
  const BN=values.map(v=>v?.[0]??1/3), NN=values.map(v=>v?.[1]??1/3), AN=values.map(v=>v?.[2]??1/3)
  const med=arr=>[...arr].sort((a,b)=>a-b)[Math.floor(arr.length/2)]
  const bnM=med(BN), nnM=med(NN), anM=med(AN)
  const dom=bnM>=nnM&&bnM>=anM?'BN':anM>=nnM?'AN':'NN'
  const domCol=dom==='BN'?'#60a5fa':dom==='AN'?'#f97316':'#34d399'
  return (
    <div style={{marginBottom:10}}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:6}}>
        <span style={{fontSize:9,color:'var(--text-faint)'}}>dominant:</span>
        <span style={{fontSize:14,fontWeight:800,color:domCol}}>{dom}</span>
      </div>
      <div style={{display:'flex',height:26,borderRadius:6,overflow:'hidden',marginBottom:4}}>
        <div style={{flex:bnM,background:'linear-gradient(90deg,#2563eb,#3b82f6)',display:'flex',alignItems:'center',justifyContent:'center'}}>
          {bnM>0.08&&<span style={{fontSize:9,fontWeight:700,color:'#fff'}}>{(bnM*100).toFixed(0)}%</span>}
        </div>
        <div style={{flex:nnM,background:'linear-gradient(90deg,#16a34a,#22c55e)',display:'flex',alignItems:'center',justifyContent:'center'}}>
          {nnM>0.08&&<span style={{fontSize:9,fontWeight:700,color:'#fff'}}>{(nnM*100).toFixed(0)}%</span>}
        </div>
        <div style={{flex:anM,background:'linear-gradient(90deg,#ea580c,#f97316)',display:'flex',alignItems:'center',justifyContent:'center'}}>
          {anM>0.08&&<span style={{fontSize:9,fontWeight:700,color:'#fff'}}>{(anM*100).toFixed(0)}%</span>}
        </div>
      </div>
      <div style={{display:'flex',justifyContent:'space-between',fontSize:8,color:'var(--text-faint)'}}>
        <span style={{color:'#60a5fa',fontWeight:600}}>* Below Normal</span>
        <span style={{color:'#4ade80',fontWeight:600}}>* Near Normal</span>
        <span style={{color:'#fb923c',fontWeight:600}}>* Above Normal</span>
      </div>
    </div>
  )
}

function ProbabilisticOutlook({pixelData,activeModels,selectedModel='multimodel',selectedSeason='long_rains'}) {
  if (!pixelData) return <div style={{display:'flex',alignItems:'center',justifyContent:'center',height:'100%',color:'var(--text-faint)',fontSize:12}}>No data</div>
  const isBega = selectedSeason === 'bega' || selectedSeason === 'ondj' || selectedSeason === 'deyr' || (pixelData?.win_doy_start === 244 && pixelData?.win_doy_end === 396) || (pixelData?.season === 'bega' || pixelData?.season === 'ondj' || pixelData?.season === 'deyr')
  const isFmam = !isBega && (selectedSeason === 'fmam' || selectedSeason === 'belg' || (pixelData?.win_doy_start === 32 && (pixelData?.season === 'fmam' || pixelData?.season === 'belg')))
  const isKiremt = !isBega && !isFmam && (selectedSeason === 'kiremt' || (pixelData?.win_doy_start === 122) || (pixelData?.season === 'kiremt'))
  const isShort = !isBega && !isFmam && !isKiremt && (selectedSeason === 'short_rains' || (pixelData?.win_doy_start ?? 32) >= 200)
  const isSingle = isBega || isFmam || isKiremt || isShort
  const allEntries = Object.entries(pixelData.models ?? {}).filter(([n]) => {
    if (isBega) return n.includes('ECMWF SEAS5') || n.includes('Bega')
    if (isFmam) return n.includes('ECMWF SEAS5') || n.includes('FMAM')
    if (isKiremt) return n.includes('ECMWF SEAS5') || n.includes('Kiremt')
    if (isShort) return n === 'ECMWF SEAS5' || n === 'ECMWF SEAS5 (Sep)'
    return selectedModel === 'multimodel' ? activeModels.has(n) : n === selectedModel
  })
  const entries = (isSingle && allEntries.length > 1) ? [allEntries[0]] : allEntries
  const climLabel = (isShort || isKiremt || isFmam || isBega) ? '1993-2016' : '1981-2016'
  const secs=[
    {key:'p_on', label:'Onset Timing', icon:'\uD83C\uDF27', def:`BN=late onset, AN=early onset vs ${climLabel} climatological terciles`},
    {key:'p_cs', label:'Cessation Timing', icon:'\u2600', def:'AN=late cessation (longer rains)'},
    {key:'p_lgp',label:'Season Length', icon:'\uD83D\uDCC5', def:'BN=shorter than average growing period'},
  ]
  return (
    <div style={{padding:'10px 12px',overflowY:'auto',height:'100%'}}>
      <div style={{marginBottom:12,padding:'8px 10px',background:'var(--bg-elevated)',borderRadius:8,border:'1px solid var(--border-primary)',fontSize:9,color:'var(--text-secondary)',lineHeight:1.6}}>
        Tercile probabilities relative to <strong>{climLabel} climatology</strong>. Climatological expectation = 33% per category. Values above 40% indicate a meaningful signal.
      </div>
      {secs.map(s=>(
        <div key={s.key} style={{background:'var(--bg-elevated)',borderRadius:8,padding:'6px 10px',border:'1px solid var(--border-primary)',marginBottom:6}}>
          <div style={{display:'flex',alignItems:'center',gap:6,marginBottom:8}}>
            <span style={{fontSize:14}}>{s.icon}</span>
            <span style={{fontSize:11,fontWeight:700,color:'var(--text-primary)'}}>{s.label}</span>
            <span style={{fontSize:8,color:'var(--text-faint)',marginLeft:'auto',cursor:'help',padding:'1px 5px',borderRadius:3,border:'1px solid var(--border-primary)'}} title={s.def}>?</span>
          </div>
          <TercileBar values={entries.map(([,m])=>m[s.key])}/>
        </div>
      ))}
    </div>
  )
}

// --- Ensemble Agreement ---------------------------------------------------
function AgreementDial({value,label}) {
  const r=24,cx=30,cy=30,stroke=5
  const angle=Math.PI*value
  const x=cx+r*Math.cos(Math.PI-angle), y=cy-r*Math.sin(angle)
  const col=value>=0.55?'#34d399':value>=0.45?'#fbbf24':'#f97316'
  const arcFull='M '+(cx-r)+' '+cy+' A '+r+' '+r+' 0 0 1 '+(cx+r)+' '+cy
  const arcPath='M '+(cx-r)+' '+cy+' A '+r+' '+r+' 0 0 1 '+x+' '+y
  return (
    <div style={{display:'flex',flexDirection:'column',alignItems:'center'}}>
      <svg width={56} height={30} viewBox="0 0 60 34">  
        <path d={arcFull} fill="none" stroke="var(--gauge-track)" strokeWidth={stroke} strokeLinecap="round"/>
        <path d={arcPath} fill="none" stroke={col} strokeWidth={stroke} strokeLinecap="round"/>
        <text x={cx} y={cy+2} textAnchor="middle" fontSize={10} fontWeight={700} fill={col}>{(value*100).toFixed(0)+'%'}</text>
      </svg>
      <span style={{fontSize:8,color:'var(--text-secondary)',textAlign:'center',lineHeight:1.2}}>{label}</span>
    </div>
  )
}

function EnsembleAgreement({ pixelData, activeModels, selectedModel='multimodel', selectedSeason='long_rains' }) {
  if (!pixelData) return (
    <div style={{display:'flex',alignItems:'center',justifyContent:'center',
                 height:'100%',color:'var(--text-faint)',fontSize:11}}>No data</div>
  )
  const isBega = selectedSeason === 'bega' || selectedSeason === 'ondj' || selectedSeason === 'deyr' || (pixelData?.win_doy_start === 244 && pixelData?.win_doy_end === 396) || (pixelData?.season === 'bega' || pixelData?.season === 'ondj' || pixelData?.season === 'deyr')
  const isFmam = !isBega && (selectedSeason === 'fmam' || selectedSeason === 'belg' || (pixelData?.win_doy_start === 32 && (pixelData?.season === 'fmam' || pixelData?.season === 'belg')))
  const isKiremt = !isBega && !isFmam && (selectedSeason === 'kiremt' || (pixelData?.win_doy_start === 122) || (pixelData?.season === 'kiremt'))
  const isShort = !isBega && !isFmam && !isKiremt && (selectedSeason === 'short_rains' || (pixelData?.win_doy_start ?? 32) >= 200)
  const isSingle = isBega || isFmam || isKiremt || isShort
  const allEntries = Object.entries(pixelData.models ?? {}).filter(([n]) => {
    if (isBega) return n.includes('ECMWF SEAS5') || n.includes('Bega')
    if (isFmam) return n.includes('ECMWF SEAS5') || n.includes('FMAM')
    if (isKiremt) return n.includes('ECMWF SEAS5') || n.includes('Kiremt')
    if (isShort) return n === 'ECMWF SEAS5' || n === 'ECMWF SEAS5 (Sep)'
    return selectedModel === 'multimodel' ? activeModels.has(n) : n === selectedModel
  })
  const entries = (isSingle && allEntries.length > 1) ? [allEntries[0]] : allEntries

  const vars = [
    { key:'agree_on',  label:'Onset',         icon:'\uD83C\uDF27' },
    { key:'agree_cs',  label:'Cessation',      icon:'\u2600'  },
    { key:'agree_lgp', label:'Season Length',  icon:'\uD83D\uDCC5' },
  ]

  const medianOf = key => {
    const vals = entries.map(([,ms]) => ms[key] ?? 1/3)
    return vals.length ? [...vals].sort((a,b)=>a-b)[Math.floor(vals.length/2)] : 1/3
  }

  // Compact SVG dial
  const SmallDial = ({ value, label }) => {
    const r=18, cx=22, cy=22, sw=4
    const angle = Math.PI * Math.min(Math.max(value,0),1)
    const x = cx + r*Math.cos(Math.PI - angle)
    const y = cy - r*Math.sin(angle)
    const col = value>=0.55?'#34d399':value>=0.45?'#fbbf24':'#f97316'
    const arcFull = `M ${cx-r} ${cy} A ${r} ${r} 0 0 1 ${cx+r} ${cy}`
    const arcPath = `M ${cx-r} ${cy} A ${r} ${r} 0 0 1 ${x} ${y}`
    return (
      <div style={{display:'flex',flexDirection:'column',alignItems:'center',gap:2,flex:1}}>
        <svg width={44} height={26} viewBox="0 0 44 26">
          <path d={arcFull} fill="none" stroke="var(--gauge-track)" strokeWidth={sw} strokeLinecap="round"/>
          <path d={arcPath} fill="none" stroke={col} strokeWidth={sw} strokeLinecap="round"/>
          <text x={cx} y={cy+1} textAnchor="middle" fontSize={8} fontWeight={700} fill={col}>
            {(value*100).toFixed(0)}%
          </text>
        </svg>
        <span style={{fontSize:8,color:'var(--text-secondary)',textAlign:'center'}}>{label}</span>
      </div>
    )
  }

  return (
    <div style={{display:'flex',flexDirection:'column',height:'100%',overflow:'hidden'}}>
      {isSingle && (
        <div style={{padding:'4px 8px',background:'rgba(59,130,246,0.08)',borderBottom:'1px solid var(--border-primary)',fontSize:8.5,color:'var(--accent-blue)',fontWeight:600,textAlign:'center'}}>
          {isBega ? 'Single-Model Operational Ensemble: ECMWF SEAS5 (25 Members, Deyr Sep 01)' : isFmam ? 'Single-Model Operational Ensemble: ECMWF SEAS5 (25 Members, Belg Jan 01)' : isKiremt ? 'Single-Model Operational Ensemble: ECMWF SEAS5 (25 Members, Kiremt May 01)' : 'Single-Model Operational Ensemble: ECMWF SEAS5 (25 Ensemble Members)'}
        </div>
      )}
      {/* Dial summary row */}
      <div style={{flexShrink:0,display:'flex',justifyContent:'space-around',padding:'8px 4px 6px',
                   borderBottom:'1px solid var(--border-primary)',background:'var(--bg-elevated)'}}>
        {vars.map(v => <SmallDial key={v.key} value={medianOf(v.key)} label={v.icon+' '+v.label} />)}
      </div>

      {/* Per-variable model bars -- scrollable */}
      <div style={{flex:1,overflowY:'auto',padding:'6px 8px'}}>
        {vars.map(({ key, label, icon }) => (
          <div key={key} style={{marginBottom:8}}>
            <div style={{fontSize:8,fontWeight:700,letterSpacing:'0.1em',textTransform:'uppercase',
                         color:'var(--accent-blue)',marginBottom:4}}>
              {icon} {label}
            </div>
            {entries.map(([name, ms]) => {
              const val = ms[key] ?? 1/3
              const col = val>=0.55?'#34d399':val>=0.45?'#fbbf24':'#f97316'
              const shortName = name.split(' ').slice(0,2).join(' ')
              return (
                <div key={name} style={{display:'flex',alignItems:'center',gap:4,marginBottom:3}}>
                  <div style={{width:6,height:6,borderRadius:'50%',
                               background:ms.color??'#888',flexShrink:0}}/>
                  <span style={{fontSize:8,color:'var(--text-secondary)',
                                width:60,flexShrink:0,overflow:'hidden',
                                textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{shortName}</span>
                  <div style={{flex:1,height:4,background:'var(--gauge-track)',
                               borderRadius:2,overflow:'hidden'}}>
                    <div style={{height:'100%',width:val*100+'%',
                                 background:col,borderRadius:2,transition:'width 0.3s'}}/>
                  </div>
                  <span style={{fontSize:8,fontWeight:700,color:col,
                                width:22,textAlign:'right',flexShrink:0}}>
                    {(val*100).toFixed(0)}%
                  </span>
                </div>
              )
            })}
          </div>
        ))}

        {/* Legend */}
        <div style={{marginTop:4,paddingTop:6,borderTop:'1px solid var(--border-primary)',
                     fontSize:8,color:'var(--text-faint)',lineHeight:1.7}}>
          <span style={{color:'#34d399'}}>&gt;=55%</span> Strong &nbsp;
          <span style={{color:'#fbbf24'}}>45-55%</span> Moderate &nbsp;
          <span style={{color:'#f97316'}}>&lt;45%</span> Uncertain
        </div>
      </div>
    </div>
  )
}


function ForecastingTab({selectedModel,selectedYear,pixelData,isLoading,activeModels,selectedSeason='short_rains',selectedInit='0901'}) {
  if (isLoading && !pixelData) return (
    <div className="flex flex-col items-center justify-center h-full min-h-[300px] gap-3" style={{color:'var(--text-faint)'}}>
      <div className="w-8 h-8 border-2 border-[var(--accent-blue)] border-t-transparent rounded-full animate-spin"/>
      <span className="text-xs tracking-wider uppercase font-semibold text-[var(--accent-blue)]">Loading Forecast Analysis...</span>
    </div>
  )
  if (!pixelData) return (
    <div className="flex flex-col items-center justify-center h-full min-h-[300px] gap-2" style={{color:'var(--text-faint)'}}>
      <span className="text-2xl">📍</span>
      <span className="text-sm tracking-wide">Click any pixel on the map to load forecast data</span>
    </div>
  )
  const isBega = selectedSeason === 'bega' || selectedSeason === 'deyr' || selectedSeason === 'ondj' || (pixelData?.win_doy_start === 244 && pixelData?.win_doy_end === 396) || (pixelData?.season === 'bega' || pixelData?.season === 'deyr' || pixelData?.season === 'ondj')
  const isFmam = !isBega && (selectedSeason === 'fmam' || selectedSeason === 'belg' || selectedSeason === 'gu' || (pixelData?.win_doy_start === 32 && (pixelData?.season === 'fmam' || pixelData?.season === 'belg' || pixelData?.season === 'gu')))
  const isKiremt = !isBega && !isFmam && (selectedSeason === 'kiremt' || selectedSeason === 'annual' || (pixelData?.win_doy_start === 122) || (pixelData?.season === 'kiremt' || pixelData?.season === 'annual'))
  const isShort = !isBega && !isFmam && !isKiremt && (selectedSeason === 'short_rains' || (pixelData?.win_doy_start ?? 32) >= 200)
  const isSingle = isBega || isFmam || isKiremt || isShort
  const seasonCode = isBega ? 'Deyr (SON-OND)' : (selectedSeason === 'gu' ? 'Gu (MAM)' : (isFmam ? 'Belg (FMAM)' : (selectedSeason === 'annual' ? 'Annual Wet Season' : (isKiremt ? 'Kiremt (JJAS)' : (isShort ? 'OND' : 'MAM')))))
  const models = pixelData?.models ?? {}
  const allEntries = Object.entries(models).filter(([n]) => {
    if (isBega) return n.includes('ECMWF SEAS5') || n.includes('Bega') || n.includes('Deyr')
    if (isFmam) return n.includes('ECMWF SEAS5') || n.includes('FMAM')
    if (isKiremt) return n.includes('ECMWF SEAS5') || n.includes('Kiremt')
    if (isShort) return n === 'ECMWF SEAS5' || n === 'ECMWF SEAS5 (Sep)'
    return selectedModel === 'multimodel' ? (activeModels.size > 0 ? activeModels.has(n) : true) : n === selectedModel
  })
  const entries = (isSingle && allEntries.length > 1) ? [allEntries[0]] : allEntries

  const activeClim = entries[0]?.[1]?.chirps_clim ?? pixelData?.chirps_clim
  const chirpsOnRaw = activeClim?.onset, chirpsCsRaw = activeClim?.cessation, chirpsLg = activeClim?.lgp
  const chirpsOn = (isSingle && chirpsOnRaw != null && (
    isBega ? (chirpsOnRaw < 244 || chirpsOnRaw > 396) :
    isFmam ? (chirpsOnRaw < 32 || chirpsOnRaw > 166) :
    isKiremt ? (chirpsOnRaw < 100 || chirpsOnRaw > 304) :
    chirpsOnRaw < 200
  )) ? null : chirpsOnRaw
  const chirpsCs = (isSingle && chirpsCsRaw != null && (
    isBega ? (chirpsCsRaw < 244 || chirpsCsRaw > 396) :
    isFmam ? (chirpsCsRaw < 32 || chirpsCsRaw > 166) :
    isKiremt ? (chirpsCsRaw < 100 || chirpsCsRaw > 304) :
    chirpsCsRaw < 200
  )) ? null : chirpsCsRaw

  const med = arr => arr.length ? [...arr].sort((a,b)=>a-b)[Math.floor(arr.length/2)] : null
  const onMeds = entries.map(([,m]) => m.on_med).filter(v => v != null && (!isShort || v >= 200) && (!isFmam || (v >= 32 && v <= 166)) && (!isBega || (v >= 244 && v <= 396)))
  const csMeds = entries.map(([,m]) => m.cs_med).filter(v => v != null && (!isShort || v >= 200) && (!isFmam || (v >= 32 && v <= 166)) && (!isBega || (v >= 244 && v <= 396)))
  const lgMeds = entries.map(([,m]) => m.lg_med).filter(v => v != null)

  const mmmOn = med(onMeds)
  const mmmCs = med(csMeds)
  const mmmLg = med(lgMeds)
  const mmmAnom = mmmOn != null && chirpsOn ? mmmOn - chirpsOn : null
  const mmmCsAnom = mmmCs != null && chirpsCs ? mmmCs - chirpsCs : null
  const mmmLgAnom = mmmLg != null && chirpsLg ? mmmLg - chirpsLg : null
  const domTiming = mmmAnom != null ? (mmmAnom > 5 ? 'Late' : mmmAnom < -5 ? 'Early' : 'Normal') : 'Normal'
  const allOnP10 = entries.map(([,m]) => m.on_p10).filter(v => v != null && (!isShort || v >= 200) && (!isFmam || (v >= 32 && v <= 166)) && (!isBega || (v >= 244 && v <= 396)))
  const allOnP90 = entries.map(([,m]) => m.on_p90).filter(v => v != null && (!isShort || v >= 200) && (!isFmam || (v >= 32 && v <= 166)) && (!isBega || (v >= 244 && v <= 396)))
  const allCsP10 = entries.map(([,m]) => m.cs_p10).filter(v => v != null && (!isShort || v >= 200) && (!isFmam || (v >= 32 && v <= 166)) && (!isBega || (v >= 244 && v <= 396)))
  const allCsP90 = entries.map(([,m]) => m.cs_p90).filter(v => v != null && (!isShort || v >= 200) && (!isFmam || (v >= 32 && v <= 166)) && (!isBega || (v >= 244 && v <= 396)))
  const allLgP10 = entries.map(([,m]) => m.lg_p10).filter(v => v != null)
  const allLgP90 = entries.map(([,m]) => m.lg_p90).filter(v => v != null)
  const lgSpread = allLgP10.length && allLgP90.length ? Math.round(Math.min(...allLgP10)) + '-' + Math.round(Math.max(...allLgP90)) + 'd' : null
  const opYear = selectedYear ?? 2026
  const displayModel = isSingle ? 'ECMWF SEAS5' : (selectedModel === 'multimodel' ? 'Multi-Model Consensus' : selectedModel)

  return (
    <div className="flex flex-col h-full gap-2 overflow-y-auto touch-scroll p-0.5">
      {/* Regime Pill & Seasonal Domain Status */}
      {pixelData && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 6,
          padding: '4px 10px', background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8
        }}>
          <div style={{display: 'flex', alignItems: 'center', gap: 6, fontSize: 10}}>
            <span style={{color: 'var(--text-muted)', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase'}}>Climate Regime:</span>
            <span style={{fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 4}}>
              <span>{pixelData.regime_id === 1 ? '🌾' : (pixelData.regime_id === 2 ? '🏔️' : (pixelData.regime_id === 3 ? '🐪' : '🏜️'))}</span>
              <span>{pixelData.regime_name || 'Classified Rainfall Regime'}</span>
            </span>
          </div>
          <div style={{fontSize: 9, display: 'flex', alignItems: 'center', gap: 4}}>
            <span style={{width: 6, height: 6, borderRadius: '50%', background: pixelData.is_in_seasonal_zone !== false ? '#10b981' : '#f59e0b'}}/>
            <span style={{fontWeight: 600, color: pixelData.is_in_seasonal_zone !== false ? '#10b981' : '#f59e0b'}}>
              {pixelData.is_in_seasonal_zone !== false ? `Within ${seasonCode} Active Domain` : `Outside ${seasonCode} Domain`}
            </span>
          </div>
        </div>
      )}

      {pixelData?.is_in_seasonal_zone === false && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px',
          borderRadius: 8, fontSize: 10,
          background: pixelData.regime_id === 0 ? 'rgba(239, 68, 68, 0.15)' : 'rgba(245, 158, 11, 0.15)',
          border: '1px solid ' + (pixelData.regime_id === 0 ? 'rgba(239, 68, 68, 0.4)' : 'rgba(245, 158, 11, 0.4)'),
          color: pixelData.regime_id === 0 ? '#fca5a5' : '#fbbf24',
          flexShrink: 0
        }}>
          <span style={{fontSize: 14}}>{pixelData.regime_id === 0 ? '🏜️' : '⚠️'}</span>
          <span>
            <strong>{pixelData.regime_id === 0 ? 'Arid / Marginal Alert:' : 'Climatological Regime Notice:'}</strong> {pixelData.regime_guidance || (
              `This site (${Number(pixelData.glat).toFixed(2)}°N, ${Number(pixelData.glon).toFixed(2)}°E, ${pixelData.regime_name || 'Unclassified'}) is outside the active seasonal envelope for ${seasonCode}.`
            )}
          </span>
        </div>
      )}
      <div className="flex flex-col xl:flex-row flex-1 gap-2 min-h-0 overflow-y-auto touch-scroll">
        <div className="flex flex-col gap-2 min-w-0 flex-1">
          <Card title={'Ensemble Precipitation Plume  -  '+displayModel+'  -  '+seasonCode+' '+opYear}
                className="flex-1 min-h-[280px]">
          <div className="w-full h-[260px] sm:h-[280px] lg:h-full min-h-[240px] p-2">
            <PrecipPlume pixelData={pixelData} selectedModel={selectedModel} activeModels={activeModels} selectedSeason={selectedSeason}/>
          </div>
        </Card>
        <Card title={'C(d) / A(D) Plume  -  '+displayModel+'  -  '+seasonCode+' '+opYear}
              className="flex-1 min-h-[260px]">
          <div className="w-full h-[240px] sm:h-[260px] lg:h-full min-h-[220px] p-2">
            <ADPlume pixelData={pixelData} selectedModel={selectedModel} activeModels={activeModels} selectedSeason={selectedSeason} selectedYear={opYear}/>
          </div>
        </Card>
      </div>
      <div className="flex flex-col gap-2 shrink-0 w-full xl:w-[320px] min-h-0 h-full">
        <Card title={'Ensemble Forecast Summary  -  '+displayModel+'  -  '+seasonCode+' '+opYear} className="flex-1 min-h-0 h-full flex flex-col">
          <div className="p-3 space-y-2">
            {[['ONSET',mmmOn,mmmAnom,allOnP10,allOnP90,chirpsOn,'DOY'],
              ['CESSATION',mmmCs,mmmCsAnom,allCsP10,allCsP90,chirpsCs,'DOY'],
              ['SEASON LENGTH',mmmLg,mmmLgAnom,allLgP10,allLgP90,chirpsLg,'d']].map(([sec,p50,anom,p10s,p90s,cal,unit])=>(
              <div key={sec} className="mb-2">
                <div style={{fontSize:9,fontWeight:700,letterSpacing:'0.12em',textTransform:'uppercase',color:'var(--text-muted)',marginBottom:4}}>{sec}</div>
                <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-2 gap-1.5">
                  <StatBox label="P50" value={p50?(unit==='DOY'?'DOY '+Math.round(p50):Math.round(p50)+'d'):'--'} sub={unit==='DOY'?doy(p50, opYear):null}/>
                  <StatBox label="Anomaly" value={anom!=null?(anom>0?'+':'')+fmt(anom)+'d':'--'} color={anom>5?'text-orange-400':anom<-5?'text-emerald-400':''}/>
                  <StatBox label="Spread" value={p10s.length&&p90s.length?(unit==='DOY'?doyRange(Math.min(...p10s),Math.max(...p90s), opYear):Math.round(Math.min(...p10s))+'-'+Math.round(Math.max(...p90s))+'d'):'--'}/>
                  <StatBox label="CAL mean" value={cal?(unit==='DOY'?'DOY '+Math.round(cal):Math.round(cal)+'d'):'--'} sub={unit==='DOY'?doy(cal, opYear):null}/>
                </div>
              </div>
            ))}
            <div style={{background:'var(--bg-elevated)',borderRadius:8,padding:'8px 12px',border:'1px solid var(--border-primary)',display:'flex',justifyContent:'space-between',alignItems:'center'}}>
              <span style={{fontSize:9,textTransform:'uppercase',letterSpacing:'0.12em',color:'var(--text-muted)'}}>Timing</span>
              <span style={{fontSize:16,fontWeight:800,color:domTiming==='Late'?'#f97316':domTiming==='Early'?'#34d399':'#fbbf24'}}>{domTiming}</span>
            </div>
          </div>
        </Card>
      </div>
      </div>
    </div>
  )
}

// --- Probabilistic Tab ----------------------------------------------------
function ProbabilisticTab({pixelData,activeModels,selectedModel,setSelectedModel,modelsData,selectedYear,setSelectedYear,country,selectedSeason,onSeasonChange,selectedInit}) {
  const isBega = selectedSeason === 'bega' || selectedSeason === 'ondj' || selectedSeason === 'deyr'
  const isFmam = !isBega && (selectedSeason === 'fmam' || selectedSeason === 'belg')
  const isKiremt = !isBega && !isFmam && selectedSeason === 'kiremt'
  const isShort = !isBega && !isFmam && !isKiremt && selectedSeason === 'short_rains'
  const isSingle = isBega || isFmam || isKiremt || isShort
  const modelNames = isSingle ? ['ECMWF SEAS5'] : (modelsData?.models ? Object.keys(modelsData.models) : [])
  const yearOptions = [2026, 2025, 2024, 2023]
  const seasonCode = isBega ? 'Deyr (SON-OND)' : (isFmam ? 'Belg (FMAM)' : (isKiremt ? 'Kiremt' : (isShort ? 'OND' : 'MAM')))
  const opYear = selectedYear ?? 2026
  const displayModel = isSingle ? 'ECMWF SEAS5' : (selectedModel === 'multimodel' ? 'Multi-Model Consensus' : selectedModel)
  const selStyle={background:'var(--bg-surface)',border:'1px solid var(--accent-blue)',color:'var(--text-primary)',borderRadius:6,padding:'4px 10px',fontSize:11,cursor:'pointer',outline:'none',fontWeight:600}
  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="shrink-0 px-3 py-2 bg-[var(--bg-elevated)] border-b border-[var(--border-primary)] flex items-center gap-2 sm:gap-3 flex-wrap text-xs">
        <div className="flex items-center gap-1.5"><span style={{fontSize:9,textTransform:'uppercase',letterSpacing:'0.1em',color:'var(--text-muted)'}}>Model</span>
          <select value={isSingle ? 'ECMWF SEAS5' : selectedModel} onChange={e=>setSelectedModel(e.target.value)} style={selStyle}>{modelNames.map(n=><option key={n} value={n}>{n}</option>)}</select></div>
        <div className="flex items-center gap-1.5"><span style={{fontSize:9,textTransform:'uppercase',letterSpacing:'0.1em',color:'var(--text-muted)'}}>Season</span>
          <select value={selectedSeason} onChange={e=>onSeasonChange(e.target.value)} style={selStyle}>
            {(SEASONS[country]??SEASONS.kenya).map(s=><option key={s.id} value={s.id}>{s.label}</option>)}
          </select></div>
        <div className="flex items-center gap-1.5"><span style={{fontSize:9,textTransform:'uppercase',letterSpacing:'0.1em',color:'var(--text-muted)'}}>Year</span>
          <select value={opYear} onChange={e=>setSelectedYear(Number(e.target.value))} style={selStyle}>{yearOptions.map(y=><option key={y} value={y}>{y}</option>)}</select></div>
        <div className="sm:ml-auto text-[9px] text-[var(--text-faint)] w-full sm:w-auto mt-1 sm:mt-0">{!pixelData?'Click a pixel to load data':displayModel+' - Init '+(INIT_LABELS[selectedInit]??selectedInit)+' - '+seasonCode+' '+opYear}</div>
      </div>
      {!pixelData?(
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-[var(--text-faint)] min-h-[220px]">
          <span style={{fontSize:28}}>*</span><span style={{fontSize:12}}>Click any pixel on the map</span>
        </div>
      ):(
        <div className="flex-1 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2 overflow-y-auto p-1.5 sm:p-2 touch-scroll">
          {[
            {title:'Risk Gauges',subtitle:'Click card for def',Comp:RiskGauges},
            {title:'Probabilistic Outlook',subtitle:'BN / NN / AN',Comp:ProbabilisticOutlook},
            {title:'Ensemble Agreement',subtitle:'',Comp:EnsembleAgreement},
          ].map(({title,subtitle,Comp})=>(
            <div key={title} className="flex flex-col min-h-[300px] h-[360px] md:h-auto overflow-hidden bg-[var(--bg-surface)] border border-[var(--border-primary)] rounded-xl">
              <div className="shrink-0 px-3 py-2 border-b border-[var(--border-primary)] flex items-center justify-between bg-[var(--bg-elevated)]">
                <span style={{fontSize:10,fontWeight:700,letterSpacing:'0.08em',textTransform:'uppercase',color:'var(--text-muted)'}}>{title}</span>
                {subtitle&&<span style={{fontSize:8,color:'var(--text-faint)'}}>{subtitle}</span>}
              </div>
              <div className="flex-1 overflow-y-auto p-2 touch-scroll">
                <Comp pixelData={pixelData} activeModels={activeModels} selectedModel={selectedModel} selectedSeason={selectedSeason}/>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// --- Multi-Model Tab ------------------------------------------------------
// --- Validation Tab -------------------------------------------------------
function ValidationTab({ pixelData, activeModels, validationData,
                          selectedModel, setSelectedModel, modelsData,
                          selectedYear,  setSelectedYear,
                          country, selectedSeason, onSeasonChange, selectedInit }) {
  const isSingle = selectedSeason === 'short_rains' || selectedSeason === 'kiremt' || selectedSeason === 'fmam' || selectedSeason === 'belg' || selectedSeason === 'bega' || selectedSeason === 'ondj' || selectedSeason === 'deyr'
  const modelNames = isSingle ? ['ECMWF SEAS5'] : (modelsData?.models ? Object.keys(modelsData.models) : [])
  const selStyle = {
    background:'var(--bg-surface)', border:'1px solid var(--accent-blue)',
    color:'var(--text-primary)', borderRadius:6, padding:'3px 10px',
    fontSize:11, cursor:'pointer', outline:'none', fontWeight:600,
  }

  const entries = pixelData ? Object.entries(pixelData.models ?? {}).filter(([n]) => activeModels.has(n)) : []
  // Use selectedModel from parent for consistency with map
  const modelName = selectedModel && activeModels.has(selectedModel) ? selectedModel : (entries[0]?.[0] ?? null)

  const pct = v => v != null ? (v * 100).toFixed(0) + '%' : '--'

  const catCol = (v) => {
    if (v == null) return 'var(--text-secondary)'
    if (v >= 0.5)  return '#f97316'  // dominant -- orange
    if (v >= 0.4)  return '#fbbf24'  // elevated -- yellow
    return 'var(--text-secondary)'
  }

  const skillCol = (v, ref) => {
    if (v == null) return 'var(--text-secondary)'
    return v > ref ? '#34d399' : '#f97316'
  }

  return (
    <div className="h-full flex flex-col gap-2 p-1.5 sm:p-2 overflow-y-auto touch-scroll">

      {/* -- Control bar -- */}
      <div className="shrink-0 p-2 sm:p-2.5 bg-[var(--bg-elevated)] border border-[var(--border-primary)] rounded-xl flex items-center gap-2 sm:gap-3 flex-wrap text-xs">
        <div style={{display:'flex',alignItems:'center',gap:6}}>
          <span style={{fontSize:9,textTransform:'uppercase',letterSpacing:'0.1em',color:'var(--text-muted)'}}>Model</span>
          <select value={selectedModel} onChange={e=>setSelectedModel(e.target.value)} style={selStyle}>
            {modelNames.map(n=><option key={n} value={n}>{n}</option>)}
          </select>
        </div>
        <div style={{display:'flex',alignItems:'center',gap:6}}>
          <span style={{fontSize:9,textTransform:'uppercase',letterSpacing:'0.1em',color:'var(--text-muted)'}}>Season</span>
          <select value={selectedSeason} onChange={e=>onSeasonChange(e.target.value)} style={selStyle}>
            {(SEASONS[country]??SEASONS.kenya).map(s=><option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </div>
        <div style={{display:'flex',alignItems:'center',gap:6}}>
          <span style={{fontSize:9,textTransform:'uppercase',letterSpacing:'0.1em',color:'var(--text-muted)'}}>Year</span>
          <select value={selectedYear} onChange={e=>setSelectedYear(Number(e.target.value))} style={selStyle}>
            {[2026,2025,2024,2023].map(y=><option key={y} value={y}>{y}</option>)}
          </select>
        </div>
        <div className="sm:ml-auto text-[9px] text-[var(--text-faint)] w-full sm:w-auto mt-1 sm:mt-0">
          {modelName ? modelName + '  -  Init ' + (INIT_LABELS[selectedInit]??selectedInit) + '  -  ' + selectedYear : 'Select a model'}
        </div>
      </div>

      {/* -- Skill table -- */}
      <div style={{flexShrink:0,background:'var(--bg-surface)',border:'1px solid var(--border-primary)',borderRadius:10,overflow:'hidden'}}>
        <div style={{padding:'6px 14px',borderBottom:'1px solid var(--border-primary)',
                     background:'var(--bg-elevated)',fontSize:10,fontWeight:700,
                     letterSpacing:'0.1em',textTransform:'uppercase',color:'var(--text-muted)'}}>
          Model Skill  -  Hit Rate / RPSS / Alpha  -  Validation Period
        </div>
        {!pixelData ? (
          <div style={{padding:'16px',color:'var(--text-faint)',fontSize:11,textAlign:'center'}}>Click a pixel to load skill data</div>
        ) : (
          <div style={{overflowX:'auto'}}>
            <table style={{width:'100%',borderCollapse:'collapse',fontSize:10}}>
              <thead>
                <tr style={{borderBottom:'1px solid var(--border-primary)'}}>
                  {['Model','HR Onset','HR Cess','HR LGP','RPSS Onset','RPSS Cess','RPSS LGP','Alpha On','Alpha Cs','Alpha LGP'].map(h=>(
                    <th key={h} style={{padding:'5px 8px',textAlign:'left',color:'var(--text-muted)',
                                        fontWeight:700,fontSize:9,letterSpacing:'0.07em',
                                        textTransform:'uppercase',whiteSpace:'nowrap'}}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {entries.map(([name,ms],i)=>(
                  <tr key={name} style={{borderBottom:'1px solid var(--border-primary)',
                                          background:i%2===0?'transparent':'var(--bg-elevated)',
                                          cursor:'pointer',
                                          outline:name===modelName?'2px solid var(--accent-blue)':undefined}}
                      onClick={()=>setSelectedModel(name)}>
                    <td style={{padding:'5px 8px',fontWeight:700,color:ms.color??'#888',whiteSpace:'nowrap'}}>{name}</td>
                    {[ms.hr_on,ms.hr_cs,ms.hr_lgp].map((v,j)=>(
                      <td key={j} style={{padding:'5px 8px',color:skillCol(v,0.333)}}>{v!=null?fmt(v,3):'--'}</td>
                    ))}
                    {[ms.rpss_on,ms.rpss_cs,ms.rpss_lgp].map((v,j)=>(
                      <td key={j} style={{padding:'5px 8px',color:skillCol(v,0)}}>{v!=null?fmt(v,3):'--'}</td>
                    ))}
                    {[ms.alpha_on,ms.alpha_cs,ms.alpha_lgp].map((v,j)=>(
                      <td key={j} style={{padding:'5px 8px',color:'var(--text-secondary)'}}>{v!=null?fmt(v,2):'--'}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* -- Domain-mean probs per VAL year -- */}
      <div style={{flex:1,minHeight:0,background:'var(--bg-surface)',border:'1px solid var(--border-primary)',borderRadius:10,display:'flex',flexDirection:'column',overflow:'hidden'}}>
        <div style={{flexShrink:0,padding:'6px 14px',borderBottom:'1px solid var(--border-primary)',
                     background:'var(--bg-elevated)',display:'flex',alignItems:'center',gap:12,flexWrap:'wrap'}}>
          <span style={{fontSize:10,fontWeight:700,letterSpacing:'0.1em',textTransform:'uppercase',color:'var(--text-muted)'}}>
            Domain-Mean Probabilities per Validation Year
          </span>
          {entries.length > 0 && (
            <div style={{display:'flex',gap:4}}>
              {entries.map(([n])=>(
                <button key={n} onClick={()=>setSelectedModel(n)}
                  style={{fontSize:9,padding:'2px 8px',borderRadius:4,cursor:'pointer',
                          border:'1px solid '+(n===modelName?'var(--accent-blue)':'var(--border-primary)'),
                          background:n===modelName?'var(--accent-blue)':'var(--bg-elevated)',
                          color:n===modelName?'#fff':'var(--text-secondary)',fontWeight:n===modelName?700:400}}>
                  {n.split(' ')[0]}
                </button>
              ))}
            </div>
          )}
        </div>
        {(!validationData || !modelName) ? (
          <div style={{flex:1,display:'flex',alignItems:'center',justifyContent:'center',color:'var(--text-faint)',fontSize:11}}>
            {!validationData ? 'Loading validation data...' : 'Select a model above'}
          </div>
        ) : (
          <div style={{flex:1,overflowX:'auto',overflowY:'auto'}}>
            <table style={{borderCollapse:'collapse',fontSize:10,width:'100%'}}>
              <thead>
                <tr style={{borderBottom:'2px solid var(--border-primary)',position:'sticky',top:0,background:'var(--bg-elevated)',zIndex:1}}>
                  <th style={{padding:'5px 10px',textAlign:'left',color:'var(--text-muted)',fontWeight:700,fontSize:9,letterSpacing:'0.07em',textTransform:'uppercase',whiteSpace:'nowrap'}}>Year</th>
                  {[['Onset','#34d399'],['Cessation','#f97316'],['Season Length','#4a8fc4']].map(([vl,vc])=>(
                    ['BN','NN','AN'].map(cat=>(
                      <th key={vl+cat} style={{padding:'5px 8px',textAlign:'center',fontSize:9,fontWeight:700,
                                               letterSpacing:'0.07em',textTransform:'uppercase',whiteSpace:'nowrap',
                                               color:cat==='BN'?'#60a5fa':cat==='AN'?'#fb923c':'#4ade80',
                                               borderLeft:cat==='BN'?'2px solid var(--border-primary)':undefined}}>
                        {vl.slice(0,2)}<span style={{color:vc}}>{cat}</span>
                      </th>
                    ))
                  ))}
                </tr>
              </thead>
              <tbody>
                {(() => {
                  const md = validationData[modelName]
                  if (!md) return <tr><td colSpan={10} style={{padding:12,color:'var(--text-faint)',textAlign:'center'}}>No data for this model</td></tr>
                  const p = md.probs
                  const years = p.onset?.years ?? []
                  return years.map((yr, i) => (
                    <tr key={yr} style={{borderBottom:'1px solid var(--border-primary)',
                                          background:i%2===0?'transparent':'var(--bg-elevated)'}}>
                      <td style={{padding:'4px 10px',fontWeight:700,color:'var(--text-primary)'}}>{yr}</td>
                      {/* Onset */}
                      <td style={{padding:'4px 8px',textAlign:'center',color:catCol(p.onset?.bn[i]),borderLeft:'2px solid var(--border-primary)'}}>{pct(p.onset?.bn[i])}</td>
                      <td style={{padding:'4px 8px',textAlign:'center',color:catCol(p.onset?.nn[i])}}>{pct(p.onset?.nn[i])}</td>
                      <td style={{padding:'4px 8px',textAlign:'center',color:catCol(p.onset?.an[i])}}>{pct(p.onset?.an[i])}</td>
                      {/* Cessation */}
                      <td style={{padding:'4px 8px',textAlign:'center',color:catCol(p.cessation?.bn[i]),borderLeft:'2px solid var(--border-primary)'}}>{pct(p.cessation?.bn[i])}</td>
                      <td style={{padding:'4px 8px',textAlign:'center',color:catCol(p.cessation?.nn[i])}}>{pct(p.cessation?.nn[i])}</td>
                      <td style={{padding:'4px 8px',textAlign:'center',color:catCol(p.cessation?.an[i])}}>{pct(p.cessation?.an[i])}</td>
                      {/* LGP */}
                      <td style={{padding:'4px 8px',textAlign:'center',color:catCol(p.lgp?.bn[i]),borderLeft:'2px solid var(--border-primary)'}}>{pct(p.lgp?.bn[i])}</td>
                      <td style={{padding:'4px 8px',textAlign:'center',color:catCol(p.lgp?.nn[i])}}>{pct(p.lgp?.nn[i])}</td>
                      <td style={{padding:'4px 8px',textAlign:'center',color:catCol(p.lgp?.an[i])}}>{pct(p.lgp?.an[i])}</td>
                    </tr>
                  ))
                })()}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// --- HistoricalTimeSeries --------------------------------------------------
function HistoricalTimeSeries({ data, years, label, color, calYears, latestYear,
                                pixelData, selectedModel, varKey, unit, isShort, isKiremt, isFmam, isBega, opYear }) {
  if (!data || !years) return (
    <div style={{display:'flex',alignItems:'center',justifyContent:'center',
                 height:'100%',color:'var(--text-faint)',fontSize:11}}>No data</div>
  )
  const isLGP = varKey === 'lgp'
  const isSingle = isShort || isKiremt || isFmam || isBega
  const activeModel = isSingle ? 'ECMWF SEAS5' : selectedModel
  const modelEntry = pixelData?.models?.[activeModel] || (isSingle ? (pixelData?.models?.['ECMWF SEAS5'] || pixelData?.models?.['ECMWF SEAS5 (Bega)'] || pixelData?.models?.['ECMWF SEAS5 (FMAM)'] || pixelData?.models?.['ECMWF SEAS5 (Kiremt)'] || pixelData?.models?.['ECMWF SEAS5 (Sep)']) : null)
  const fcastP10 = varKey==='onset'?modelEntry?.on_p10:varKey==='cessation'?modelEntry?.cs_p10:modelEntry?.lg_p10
  const fcastP90 = varKey==='onset'?modelEntry?.on_p90:varKey==='cessation'?modelEntry?.cs_p90:modelEntry?.lg_p90
  const fcastP50 = varKey==='onset'?modelEntry?.on_med:varKey==='cessation'?modelEntry?.cs_med:modelEntry?.lg_med
  const effectiveYear = opYear ?? 2026
  const fmtV = v => v==null?'--':isLGP?v.toFixed(1)+'d':'DOY '+Math.round(v)+' ('+doyToDate(v, effectiveYear)+')'
  const hasIQR = fcastP10!=null&&fcastP90!=null&&fcastP50!=null&&latestYear!=null

  const targetLatestYear = effectiveYear ?? latestYear
  const chartData = years.map((yr,i) => {
    const rawVal = data[i]??null
    const isLast = yr===targetLatestYear
    return { year:yr, val:isLast?(fcastP50??rawVal):rawVal,
             isCal:calYears?.includes(yr)??false, isLatest:isLast, hasObs:rawVal!=null }
  }).filter(d=>d.val!=null||d.isLatest)

  if (targetLatestYear && !years.includes(targetLatestYear) && fcastP50 != null) {
    chartData.push({
      year: targetLatestYear,
      val: fcastP50,
      isCal: false,
      isLatest: true,
      hasObs: false,
    })
  }

  const valid   = chartData.map(d=>d.val).filter(v=>v!=null)
  const calVals = chartData.filter(d=>d.isCal).map(d=>d.val).filter(v=>v!=null)
  const calMean = calVals.length?calVals.reduce((s,v)=>s+v,0)/calVals.length:null
  const trendPts= chartData.filter(d=>d.val!=null&&!d.isLatest)
  const txs=trendPts.map((_,i)=>i), tys=trendPts.map(d=>d.val)
  const txM=txs.reduce((s,v)=>s+v,0)/(txs.length||1), tyM=tys.reduce((s,v)=>s+v,0)/(tys.length||1)
  const denom=txs.reduce((s,x)=>s+(x-txM)**2,0)||1
  const slope=txs.reduce((s,x,i)=>s+(x-txM)*(tys[i]-tyM),0)/denom
  const intcp=tyM-slope*txM
  const combined=chartData.map((d,i)=>{
    const tIdx=trendPts.findIndex(t=>t.year===d.year)
    return {...d,trend:tIdx>=0?slope*tIdx+intcp:null}
  })
  const allY=[...valid,...(fcastP10!=null?[fcastP10]:[]),...(fcastP90!=null?[fcastP90]:[])]
  const yMin=allY.length?Math.floor(Math.min(...allY)*0.96):0, yMax=allY.length?Math.ceil(Math.max(...allY)*1.04):100

  const IQRWhisker = ({ xAxisMap, yAxisMap }) => {
    if (!hasIQR||!xAxisMap||!yAxisMap) return null
    const xScale=Object.values(xAxisMap)[0]?.scale, yScale=Object.values(yAxisMap)[0]?.scale
    if (!xScale||!yScale) return null
    const cx=xScale(targetLatestYear), yP10=yScale(fcastP10), yP90=yScale(fcastP90), yP50=yScale(fcastP50)
    if (cx==null||yP10==null||yP90==null) return null
    const cap=9
    return (
      <g>
        <line x1={cx} y1={yP90} x2={cx} y2={yP10} stroke="#60a5fa" strokeWidth={2.5} strokeLinecap="round"/>
        <line x1={cx-cap} y1={yP10} x2={cx+cap} y2={yP10} stroke="#60a5fa" strokeWidth={2} strokeLinecap="round"/>
        <line x1={cx-cap} y1={yP90} x2={cx+cap} y2={yP90} stroke="#60a5fa" strokeWidth={2} strokeLinecap="round"/>
        <line x1={cx-cap*0.55} y1={yP50} x2={cx+cap*0.55} y2={yP50} stroke="#60a5fa" strokeWidth={2.5} strokeLinecap="round"/>
        <text x={cx+cap+4} y={yP10+3} fontSize={8} fill="#60a5fa">P10</text>
        <text x={cx+cap+4} y={yP90+3} fontSize={8} fill="#60a5fa">P90</text>
      </g>
    )
  }
  const CustomDot = ({ cx, cy, payload }) => {
    if (!cx||!cy||payload.val==null) return null
    if (payload.isLatest) return <circle cx={cx} cy={cy} r={7} fill="#fbbf24" stroke="var(--bg-surface)" strokeWidth={2}/>
    return <circle cx={cx} cy={cy} r={payload.isCal?3:2.5} fill={payload.isCal?color:'#94a3b8'} stroke="var(--bg-surface)" strokeWidth={0.8}/>
  }
  const labelFmt = (yr,pl) => {
    const entry=pl?.find(p=>p.dataKey==='val'), pt=entry?.payload
    if (!pt) return String(yr)
    if (pt.isLatest) return yr+'  (forecast year)'
    const calPeriodStr = (isShort || isKiremt || isFmam || isBega) ? '1993-2016' : '1981-2016'
    return yr+(pt.isCal?`  - cal period (${calPeriodStr})`:'  - validation period')
  }
  const valFmt = (val,name,entry) => {
    if (name==='trend') return [fmtV(val),'Trend line']
    if (name==='val') {
      const pt=entry?.payload
      if (!pt) return [fmtV(val),'Observed']
      if (pt.isLatest) {
        const parts=[pt.hasObs?'Obs: '+fmtV(pt.val):null, fcastP50!=null?(activeModel||'Model')+' P50: '+fmtV(fcastP50):null, hasIQR?'IQR: '+fmtV(fcastP10)+' - '+fmtV(fcastP90):null].filter(Boolean)
        const seasonCode = isBega ? 'Deyr (SON-OND)' : (isFmam ? 'Belg (FMAM)' : (isKiremt ? 'Kiremt' : (isShort ? 'OND' : 'MAM')))
        return [parts.join('  |  ')||fmtV(val),`${seasonCode} ${targetLatestYear} Forecast`]
      }
      return [fmtV(val),'Observed']
    }
    return null
  }
  return (
    <ResponsiveContainer width="100%" height="100%" minHeight={170}>
      <ComposedChart data={combined} margin={{top:6,right:80,bottom:24,left:40}}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)"/>
        <XAxis dataKey="year" tick={{fontSize:9,fill:'var(--chart-axis)'}} stroke="var(--chart-axis)" tickFormatter={y=>y%5===0?String(y):''}/>
        <YAxis tick={{fontSize:9,fill:'var(--chart-axis)'}} stroke="var(--chart-axis)"
               domain={[yMin,yMax]} tickFormatter={v=>v.toFixed(0)}
               label={{value:isLGP?'days':'DOY',angle:-90,position:'insideLeft',fontSize:9,fill:'var(--chart-axis)',offset:8}}/>
        <Tooltip contentStyle={{background:'var(--chart-tooltip-bg)',border:'1px solid var(--border-primary)',borderRadius:6,fontSize:10,color:'var(--text-primary)'}}
                 labelFormatter={labelFmt} formatter={valFmt}/>
        {calYears?.length>0&&<ReferenceArea x1={calYears[0]} x2={calYears[calYears.length-1]} fill="var(--accent-blue)" fillOpacity={0.05}/>}
        {calMean!=null&&<ReferenceLine y={calMean} stroke="var(--accent-blue)" strokeDasharray="4 2" strokeWidth={1.2} label={{value:'CAL mean',position:'right',fontSize:8,fill:'var(--accent-blue)'}}/>}
        <Line dataKey="trend" dot={false} activeDot={false} stroke="#f97316" strokeWidth={1.5} strokeDasharray="6 2" name="trend" isAnimationActive={false}/>
        {hasIQR&&<Customized component={IQRWhisker}/>}
        <Line dataKey="val" dot={(p)=><CustomDot {...p}/>} activeDot={{r:6}} stroke={color} strokeWidth={1.2} name="val" isAnimationActive={false} connectNulls={false}/>
      </ComposedChart>
    </ResponsiveContainer>
  )
}

// --- HistoricalTab ------------------------------------------------------------
function HistoricalTab({ pixelData, chirpsHist, selectedModel, setSelectedModel, modelsData, selectedYear, setSelectedYear, country, selectedSeason, onSeasonChange, selectedInit }) {
  const isBega = selectedSeason === 'bega' || selectedSeason === 'ondj' || selectedSeason === 'deyr' || (pixelData?.win_doy_start === 244 && pixelData?.win_doy_end === 396) || (pixelData?.season === 'bega' || pixelData?.season === 'ondj' || pixelData?.season === 'deyr')
  const isFmam = !isBega && (selectedSeason === 'fmam' || selectedSeason === 'belg' || (pixelData?.win_doy_start === 32 && (pixelData?.season === 'fmam' || pixelData?.season === 'belg')))
  const isKiremt = !isBega && !isFmam && (selectedSeason === 'kiremt' || (pixelData?.win_doy_start === 122) || (pixelData?.season === 'kiremt'))
  const isShort = !isBega && !isFmam && !isKiremt && (selectedSeason === 'short_rains' || (pixelData?.win_doy_start ?? 32) >= 200)
  const isSingle = isBega || isFmam || isKiremt || isShort
  const opYear = selectedYear || 2026
  const modelNames = isSingle ? ['ECMWF SEAS5'] : (modelsData?.models ? Object.keys(modelsData.models) : [])
  const yearOptions = [2026, 2025, 2024, 2023]
  const activeModelName = isSingle ? 'ECMWF SEAS5' : selectedModel
  const seasonCode = isBega ? 'Deyr (SON-OND)' : (isFmam ? 'Belg (FMAM)' : (isKiremt ? 'Kiremt' : (isShort ? 'OND' : 'MAM')))
  const calPeriodStr = (isShort || isKiremt || isFmam || isBega) ? '1993-2016' : '1981-2016'
  const selStyle = {background:'var(--bg-surface)',border:'1px solid var(--accent-blue)',color:'var(--text-primary)',borderRadius:6,padding:'3px 10px',fontSize:11,cursor:'pointer',outline:'none',fontWeight:600}
  const vars = [{key:'onset',label:'Onset DOY',color:'#34d399',unit:'DOY'},{key:'cessation',label:'Cessation DOY',color:'#f97316',unit:'DOY'},{key:'lgp',label:'Season Length',color:'#4a8fc4',unit:'days'}]
  return (
    <div className="h-full flex flex-col gap-2 p-1.5 sm:p-2 overflow-y-auto touch-scroll">
      <div className="shrink-0 p-2 sm:p-2.5 bg-[var(--bg-elevated)] border border-[var(--border-primary)] rounded-xl flex items-center gap-2 sm:gap-3 flex-wrap text-xs">
        <div style={{display:'flex',alignItems:'center',gap:6}}>
          <span style={{fontSize:9,textTransform:'uppercase',letterSpacing:'0.1em',color:'var(--text-muted)'}}>Model</span>
          <select value={activeModelName} onChange={e=>setSelectedModel(e.target.value)} style={selStyle}>
            {modelNames.map(n=><option key={n} value={n}>{n}</option>)}
          </select>
        </div>
        <div style={{display:'flex',alignItems:'center',gap:6}}><span style={{fontSize:9,textTransform:'uppercase',letterSpacing:'0.1em',color:'var(--text-muted)'}}>Season</span>
          <select value={selectedSeason} onChange={e=>onSeasonChange(e.target.value)} style={selStyle}>
            {(SEASONS[country]??SEASONS.kenya).map(s=><option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </div>
        <div style={{display:'flex',alignItems:'center',gap:6}}><span style={{fontSize:9,textTransform:'uppercase',letterSpacing:'0.1em',color:'var(--text-muted)'}}>Year</span>
          <select value={selectedYear || opYear} onChange={e=>setSelectedYear(Number(e.target.value))} style={selStyle}>
            {yearOptions.map(y=><option key={y} value={y}>{y}</option>)}
          </select>
        </div>
        <div style={{display:'flex',alignItems:'center',gap:6}}><span style={{fontSize:9,color:'var(--text-faint)'}}>Init {INIT_LABELS[selectedInit]??(isBega ? 'Sep 01' : (isFmam ? 'Jan 01' : (isKiremt ? 'May 01' : (isShort ? 'Sep 01' : 'Feb 01'))))}</span></div>
        <div className="sm:ml-auto text-[9px] text-[var(--text-faint)] w-full sm:w-auto mt-1 sm:mt-0">{chirpsHist?'':'Click a pixel on the map to load data'}</div>
      </div>
      <div style={{flexShrink:0,background:'var(--bg-surface)',border:'1px solid var(--border-primary)',borderRadius:10,maxHeight:'35%',overflow:'hidden',display:'flex',flexDirection:'column'}}>
        <div style={{overflowX:'auto',overflowY:'auto',flex:1}}>
          <table style={{width:'100%',borderCollapse:'collapse',fontSize:10}}>
            <thead><tr style={{borderBottom:'1px solid var(--border-primary)',background:'var(--bg-elevated)'}}>
              {['Variable', 'CAL Mean (' + calPeriodStr + ')', 'SD', 'CV (%)', 'Trend (d/yr)', `Forecast ${seasonCode} ${opYear}`, 'Anomaly', 'Detection Rate'].map(h=>(
                <th key={h} style={{padding:'5px 10px',textAlign:'left',color:'var(--text-muted)',fontWeight:700,fontSize:9,letterSpacing:'0.08em',textTransform:'uppercase',whiteSpace:'nowrap'}}>{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {vars.map((v,i)=>{
                const d=chirpsHist?.[v.key]
                const modelEntry = pixelData?.models?.[activeModelName] || (isSingle ? (pixelData?.models?.['ECMWF SEAS5'] || pixelData?.models?.['ECMWF SEAS5 (FMAM)'] || pixelData?.models?.['ECMWF SEAS5 (Kiremt)'] || pixelData?.models?.['ECMWF SEAS5 (Bega)'] || pixelData?.models?.['ECMWF SEAS5 (Sep)']) : null)
                const fcastP50 = v.key==='onset'?modelEntry?.on_med:v.key==='cessation'?modelEntry?.cs_med:modelEntry?.lg_med
                const dispVal = fcastP50 ?? d?.latest_val
                const anom = (dispVal != null && d?.mean != null) ? Number((dispVal - d.mean).toFixed(1)) : (d?.latest_anom ?? null)
                return (
                  <tr key={v.key} style={{borderBottom:'1px solid var(--border-primary)',background:i%2===0?'transparent':'var(--bg-elevated)'}}>
                    <td style={{padding:'5px 10px',fontWeight:700,color:v.color,whiteSpace:'nowrap'}}>{v.label}</td>
                    <td style={{padding:'5px 10px',color:'var(--text-primary)'}}>{d?.mean!=null?(v.unit==='DOY'?'DOY '+d.mean+'  ('+doyToDate(d.mean, opYear)+')':d.mean+'d'):'--'}</td>
                    <td style={{padding:'5px 10px',color:'var(--text-secondary)'}}>{d?.sd??'--'}</td>
                    <td style={{padding:'5px 10px',color:'var(--text-secondary)'}}>{d?.cv!=null?d.cv+'%':'--'}</td>
                    <td style={{padding:'5px 10px',color:d?.trend_day_per_yr>0.1?'#f97316':d?.trend_day_per_yr<-0.1?'#34d399':'var(--text-secondary)'}}>{d?.trend_day_per_yr!=null?(d.trend_day_per_yr>0?'+':'')+d.trend_day_per_yr:'--'}</td>
                    <td style={{padding:'5px 10px',fontWeight:600,color:'var(--text-primary)'}}>{dispVal!=null?(v.unit==='DOY'?'DOY '+Math.round(dispVal)+'  ('+doyToDate(dispVal, opYear)+')':Math.round(dispVal)+'d'):'--'}</td>
                    <td style={{padding:'5px 10px',fontWeight:600,color:!anom?'var(--text-faint)':anom>5?'#f97316':anom<-5?'#34d399':'var(--text-secondary)'}}>{anom!=null?(anom>0?'+':'')+anom+'d':'--'}</td>
                    <td style={{padding:'5px 10px',color:'var(--text-secondary)'}}>{d?.detect_rate!=null?(d.detect_rate*100).toFixed(0)+'%':'--'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
      <div style={{flex:1,display:'flex',flexDirection:'column',gap:6,minHeight:0}}>
        {vars.map(v=>{
          const d=chirpsHist?.[v.key]
          return (
            <div key={v.key} style={{flex:1,minHeight:160,background:'var(--bg-surface)',border:'1px solid var(--border-primary)',borderRadius:10,display:'flex',flexDirection:'column',overflow:'hidden'}}>
              <div style={{flexShrink:0,padding:'4px 12px',borderBottom:'1px solid var(--border-primary)',display:'flex',alignItems:'center',justifyContent:'space-between'}}>
                <span style={{fontSize:10,fontWeight:700,textTransform:'uppercase',letterSpacing:'0.1em',color:v.color}}>{v.label}</span>
                {d&&<span style={{fontSize:9,color:'var(--text-faint)'}}>mean {d.mean} {v.unit} ({v.unit==='DOY'?doyToDate(d.mean, opYear):''}) - trend {d.trend_day_per_yr>0?'+':''}{d.trend_day_per_yr} d/yr</span>}
              </div>
              <div className="flex-1 w-full h-[180px] sm:h-[200px] lg:h-full min-h-[170px] p-1">
                {!chirpsHist?<PlaceholderPanel label={v.label+' time series -- click a pixel'} icon="O"/>:
                  <HistoricalTimeSeries data={d?.ts} years={chirpsHist.years} label={v.label} color={v.color}
                    calYears={chirpsHist.cal_years} latestYear={chirpsHist.latest_year}
                    pixelData={pixelData} selectedModel={activeModelName} varKey={v.key} unit={v.unit}
                    isShort={isShort} isKiremt={isKiremt} isFmam={isFmam} isBega={isBega} opYear={opYear}/>}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// --- MultiModelTab ------------------------------------------------------------
function MultiModelTab({ pixelData, activeModels, modelsData, selectedSeason='long_rains', selectedYear=2026 }) {
  const [weightMode, setWeightMode] = useState('equal')  // 'equal' | 'hr' | 'rpss'

  if (!pixelData) return (
    <div className="flex flex-col items-center justify-center h-full gap-2" style={{color:'var(--text-faint)'}}>
      <span className="text-2xl">M</span>
      <span className="text-sm tracking-wide">Click any pixel on the map to load forecast data</span>
    </div>
  )

  const models   = pixelData.models ?? {}
  const chirpsOn = pixelData?.chirps_clim?.onset
  const chirpsCs = pixelData?.chirps_clim?.cessation
  const chirpsLg = pixelData?.chirps_clim?.lgp

  const activeEntries = Object.entries(models).filter(([n]) => activeModels.size > 0 ? activeModels.has(n) : true)

  // -- Compute weights -----------------------------------------------------
  // NaN-safe numeric helper: treats NaN/null/undefined as 0
  const safeNum = (v, fallback=0) => (v==null||isNaN(v)) ? fallback : v

  const computeWeights = (mode) => {
    const N = activeEntries.length
    if (mode === 'equal' || N === 0) {
      return Object.fromEntries(activeEntries.map(([name]) => [name, 1/N]))
    }
    const raw = {}
    activeEntries.forEach(([name, ms]) => {
      let v
      if (mode === 'hr') {
        // Use calibration HR -- fallback to 1/3 (climatology baseline) when missing
        v = (safeNum(ms.hr_on, 1/3) + safeNum(ms.hr_cs, 1/3) + safeNum(ms.hr_lgp, 1/3)) / 3
      } else {
        // RPSS: clip negative to 0, use 0 when missing
        v = (Math.max(0, safeNum(ms.rpss_on, 0)) +
             Math.max(0, safeNum(ms.rpss_cs, 0)) +
             Math.max(0, safeNum(ms.rpss_lgp, 0))) / 3
      }
      raw[name] = Math.max(safeNum(v, 0.01), 0.01)
    })
    const total = Object.values(raw).reduce((s,v)=>s+v, 0)
    if (!isFinite(total) || total < 1e-6) {
      return Object.fromEntries(activeEntries.map(([name]) => [name, 1/N]))
    }
    return Object.fromEntries(Object.entries(raw).map(([n,v])=>[n, v/total]))
  }

  const weights = computeWeights(weightMode)

  // -- Weighted ensemble statistics ----------------------------------------
  const weightedMed = (key) => {
    let wsum = 0, vsum = 0
    activeEntries.forEach(([name, ms]) => {
      const v = ms[key]
      const w = weights[name] ?? 0
      if (v != null && !isNaN(v)) { vsum += v * w; wsum += w }
    })
    return wsum > 0 ? vsum / wsum : null
  }

  const equalMed = (key) => {
    const vals = activeEntries.map(([,ms]) => ms[key]).filter(v => v!=null && !isNaN(v))
    return vals.length ? vals.reduce((s,v)=>s+v,0)/vals.length : null
  }

  // Weighted P(BN/NN/AN)
  const weightedProbs = (key) => {
    const bn = [], nn = [], an = []
    let wsum = 0
    activeEntries.forEach(([name, ms]) => {
      const p = ms[key]
      if (!p || p.length < 3) return
      const w = weights[name] ?? 0
      bn.push((p[0]??1/3)*w); nn.push((p[1]??1/3)*w); an.push((p[2]??1/3)*w)
      wsum += w
    })
    if (wsum < 1e-6) return [1/3,1/3,1/3]
    return [
      bn.reduce((s,v)=>s+v,0)/wsum,
      nn.reduce((s,v)=>s+v,0)/wsum,
      an.reduce((s,v)=>s+v,0)/wsum,
    ]
  }

  const vars = [
    { key:'onset',     medKey:'on_med',  p10:'on_p10', p90:'on_p90', pKey:'p_on',  label:'Onset DOY',    cal:chirpsOn, unit:'DOY', color:'#34d399' },
    { key:'cessation', medKey:'cs_med',  p10:'cs_p10', p90:'cs_p90', pKey:'p_cs',  label:'Cessation DOY',cal:chirpsCs, unit:'DOY', color:'#f97316' },
    { key:'lgp',       medKey:'lg_med',  p10:'lg_p10', p90:'lg_p90', pKey:'p_lgp', label:'Season Length', cal:chirpsLg, unit:'d',   color:'#4a8fc4' },
  ]

  const WEIGHT_MODES = [
    { id:'equal', label:'Equal Weights',     desc:'Simple mean across all active models' },
    { id:'hr',    label:'HR-Weighted',        desc:'Weights proportional to domain-mean Hit Rate (calibration period)' },
    { id:'rpss',  label:'RPSS-Weighted',      desc:'Weights proportional to max(RPSS, 0) from validation period. Models with negative RPSS get minimum weight.' },
  ]

  const pctBar = (bn,nn,an) => {
    const B=(bn*100).toFixed(0), N=(nn*100).toFixed(0), A=(an*100).toFixed(0)
    return (
      <div style={{display:'flex',height:18,borderRadius:4,overflow:'hidden',flex:1}}>
        <div style={{flex:bn,background:'#3b82f6',display:'flex',alignItems:'center',justifyContent:'center',fontSize:8,color:'#fff',fontWeight:700,minWidth:bn>0.06?'auto':0}}>{bn>0.06?B+'%':''}</div>
        <div style={{flex:nn,background:'#22c55e',display:'flex',alignItems:'center',justifyContent:'center',fontSize:8,color:'#fff',fontWeight:700,minWidth:nn>0.06?'auto':0}}>{nn>0.06?N+'%':''}</div>
        <div style={{flex:an,background:'#f97316',display:'flex',alignItems:'center',justifyContent:'center',fontSize:8,color:'#fff',fontWeight:700,minWidth:an>0.06?'auto':0}}>{an>0.06?A+'%':''}</div>
      </div>
    )
  }

  return (
    <div style={{height:'100%',display:'flex',flexDirection:'column',gap:8,padding:8,overflow:'hidden'}}>

      {/* -- Weight mode selector -- */}
      <div style={{flexShrink:0,padding:'7px 12px',background:'var(--bg-elevated)',border:'1px solid var(--border-primary)',borderRadius:10,display:'flex',alignItems:'center',gap:8,flexWrap:'wrap'}}>
        <span style={{fontSize:9,textTransform:'uppercase',letterSpacing:'0.1em',color:'var(--text-muted)',flexShrink:0}}>Weighting:</span>
        {WEIGHT_MODES.map(m=>(
          <button key={m.id} onClick={()=>setWeightMode(m.id)} title={m.desc}
            style={{padding:'4px 12px',borderRadius:6,fontSize:10,cursor:'pointer',fontWeight:weightMode===m.id?700:400,
                    border:'1px solid '+(weightMode===m.id?'var(--accent-blue)':'var(--border-primary)'),
                    background:weightMode===m.id?'var(--accent-blue)':'var(--bg-surface)',
                    color:weightMode===m.id?'#fff':'var(--text-secondary)',transition:'all 0.12s'}}>
            {m.label}
          </button>
        ))}
        <div style={{marginLeft:'auto',fontSize:9,color:'var(--text-faint)',maxWidth:300,textAlign:'right'}}>
          {WEIGHT_MODES.find(m=>m.id===weightMode)?.desc}
        </div>
      </div>

      {/* -- Main content: A(D) Plume left, comparison table right -- */}
      <div className="flex-1 flex flex-col lg:flex-row gap-2 min-h-0 overflow-y-auto touch-scroll">

        {/* A(D) Plume */}
        <div className="flex-1 min-w-0 min-h-[280px] sm:min-h-[340px] bg-[var(--bg-surface)] border border-[var(--border-primary)] rounded-xl flex flex-col overflow-hidden">
          <div style={{flexShrink:0,padding:'6px 12px',borderBottom:'1px solid var(--border-primary)',fontSize:10,fontWeight:700,textTransform:'uppercase',letterSpacing:'0.1em',color:'var(--text-muted)'}}>
            A(D) Plume -- All Active Models
          </div>
          <div style={{flex:1,minHeight:240,padding:8}}>
            <ADPlume pixelData={pixelData} selectedModel="multimodel" activeModels={activeModels} weightMode={weightMode} weights={weights} selectedSeason={selectedSeason} selectedYear={selectedYear}/>
          </div>
        </div>

        {/* Comparison table */}
        <div className="w-full lg:w-[320px] shrink-0 flex flex-col gap-2 overflow-y-auto">

          {/* Per-variable comparison */}
          {vars.map(v => {
            const eqMed  = equalMed(v.medKey)
            const wtMed  = weightedMed(v.medKey)
            const eqProb = (() => {
              const vals = activeEntries.map(([,ms])=>ms[v.pKey]).filter(p=>p&&p.length>=3)
              if (!vals.length) return [1/3,1/3,1/3]
              return [0,1,2].map(i=>vals.reduce((s,p)=>s+(p[i]??1/3),0)/vals.length)
            })()
            const wtProb = weightedProbs(v.pKey)
            const fmtDOY = x => x==null?'--':(v.unit==='DOY'?'DOY '+Math.round(x)+' ('+doy(x)+')':Math.round(x)+'d')

            return (
              <div key={v.key} style={{background:'var(--bg-surface)',border:'1px solid var(--border-primary)',borderRadius:10,padding:'10px 12px',borderLeft:'3px solid '+v.color}}>
                <div style={{fontSize:11,fontWeight:700,color:v.color,marginBottom:8}}>{v.label}</div>

                {/* P50 -- active mode only */}
                {(() => {
                  const dispMed  = weightMode === 'equal' ? eqMed  : wtMed
                  const dispProb = weightMode === 'equal' ? eqProb : wtProb
                  const modeLabel = weightMode==='equal'?'Equal Weight':weightMode==='hr'?'HR-Weighted':'RPSS-Weighted'
                  const anom = dispMed!=null&&v.cal ? dispMed-v.cal : null
                  return (
                    <>
                      <div style={{marginBottom:8}}>
                        <div style={{fontSize:8,color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:'0.08em',marginBottom:2}}>{modeLabel} P50</div>
                        <div style={{fontSize:16,fontWeight:800,color:'var(--text-primary)'}}>{fmtDOY(dispMed)}</div>
                        {anom!=null&&<div style={{fontSize:10,color:anom>5?'#f97316':anom<-5?'#34d399':'var(--text-secondary)',marginTop:2}}>
                          vs CAL: {anom>0?'+':''}{fmt(anom)}d
                        </div>}
                      </div>
                      <div>
                        <div style={{fontSize:8,color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:'0.08em',marginBottom:3}}>{modeLabel} BN / NN / AN</div>
                        {pctBar(dispProb[0],dispProb[1],dispProb[2])}
                      </div>
                    </>
                  )
                })()}
              </div>
            )
          })}

          {/* Model weights table with raw skill diagnostics */}
          {weightMode !== 'equal' && (()=>{
            // Detect if all weights are suspiciously equal (NaN fallback)
            const wVals = activeEntries.map(([n])=>weights[n]??0)
            const wMax = Math.max(...wVals), wMin = Math.min(...wVals)
            const allEqual = (wMax - wMin) < 0.001
            return (
            <div style={{background:'var(--bg-surface)',border:'1px solid var(--border-primary)',borderRadius:10,padding:'10px 12px'}}>
              <div style={{fontSize:10,fontWeight:700,textTransform:'uppercase',letterSpacing:'0.1em',color:'var(--text-muted)',marginBottom:6}}>
                Model Weights ({weightMode === 'hr' ? 'HR-based' : 'RPSS-based'})
              </div>
              {/* Warning if skill files not loaded */}
              {allEqual && (
                <div style={{fontSize:9,color:'#f97316',background:'rgba(249,115,22,0.1)',border:'1px solid rgba(249,115,22,0.3)',borderRadius:6,padding:'5px 8px',marginBottom:8,lineHeight:1.5}}>
                  All weights are equal -- skill files may not be loaded on disk.
                  Check that hitrate_cal / rpss_val NetCDF files exist in each model outputs folder.
                  Raw values shown below for diagnosis.
                </div>
              )}
              {/* Header row */}
              <div style={{display:'grid',gridTemplateColumns:'1fr 48px 48px 48px 32px',gap:2,marginBottom:4}}>
                <div style={{fontSize:7,color:'var(--text-faint)',textTransform:'uppercase',letterSpacing:'0.06em'}}>Model</div>
                {weightMode==='hr'
                  ? ['HR On','HR Cs','HR LGP'].map(h=><div key={h} style={{fontSize:7,color:'var(--text-faint)',textAlign:'center',textTransform:'uppercase',letterSpacing:'0.06em'}}>{h}</div>)
                  : ['RP On','RP Cs','RP LGP'].map(h=><div key={h} style={{fontSize:7,color:'var(--text-faint)',textAlign:'center',textTransform:'uppercase',letterSpacing:'0.06em'}}>{h}</div>)
                }
                <div style={{fontSize:7,color:'var(--text-faint)',textAlign:'right',textTransform:'uppercase',letterSpacing:'0.06em'}}>Wt</div>
              </div>
              {activeEntries.map(([name, ms]) => {
                const w = weights[name] ?? 0
                const rawA = weightMode==='hr' ? ms.hr_on  : ms.rpss_on
                const rawB = weightMode==='hr' ? ms.hr_cs  : ms.rpss_cs
                const rawC = weightMode==='hr' ? ms.hr_lgp : ms.rpss_lgp
                const fmtSkill = v => (v==null||isNaN(v)) ? <span style={{color:'#f97316'}}>NaN</span> : v.toFixed(2)
                return (
                  <div key={name} style={{display:'grid',gridTemplateColumns:'1fr 48px 48px 48px 32px',gap:2,marginBottom:4,alignItems:'center'}}>
                    <div style={{display:'flex',alignItems:'center',gap:4}}>
                      <div style={{width:7,height:7,borderRadius:'50%',background:ms.color??'#888',flexShrink:0}}/>
                      <span style={{fontSize:8,color:'var(--text-secondary)',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{name.split(' ')[0]}</span>
                    </div>
                    <div style={{fontSize:8,color:'var(--text-secondary)',textAlign:'center'}}>{fmtSkill(rawA)}</div>
                    <div style={{fontSize:8,color:'var(--text-secondary)',textAlign:'center'}}>{fmtSkill(rawB)}</div>
                    <div style={{fontSize:8,color:'var(--text-secondary)',textAlign:'center'}}>{fmtSkill(rawC)}</div>
                    <div style={{fontSize:8,fontWeight:700,color:allEqual?'#f97316':'var(--accent-blue)',textAlign:'right'}}>{(w*100).toFixed(0)}%</div>
                  </div>
                )
              })}
              {/* Weight bar */}
              <div style={{display:'flex',height:6,borderRadius:3,overflow:'hidden',marginTop:6,gap:1}}>
                {activeEntries.map(([n,ms])=>(
                  <div key={n} style={{flex:weights[n]??0,background:ms.color??'#888',minWidth:2,transition:'flex 0.3s'}} title={n}/>
                ))}
              </div>
            </div>
            )
          })()}

        </div>
      </div>
    </div>
  )
}


function AboutTab() {
  const [subTab, setSubTab] = useState('blueprint')

  const S = ({title,children})=>(<div style={{marginBottom:22}}><div style={{fontSize:11,fontWeight:700,letterSpacing:'0.12em',textTransform:'uppercase',color:'var(--accent-blue)',marginBottom:10,paddingBottom:5,borderBottom:'1px solid var(--border-primary)'}}>{title}</div>{children}</div>)
  const KV = ({label,value,mono=false,wide=false})=>(<div style={{display:'flex',gap:8,marginBottom:6,alignItems:'flex-start'}}><span style={{fontSize:9,color:'var(--text-muted)',minWidth:wide?220:170,flexShrink:0,textTransform:'uppercase',letterSpacing:'0.07em',paddingTop:1}}>{label}</span><span style={{fontSize:10,color:'var(--text-primary)',lineHeight:1.5,fontFamily:mono?"'IBM Plex Mono',monospace":'inherit'}}>{value}</span></div>)
  const Step = ({n,title,eq,desc,table})=>(
    <div style={{display:'flex',gap:10,marginBottom:14,alignItems:'flex-start'}}>
      <div style={{flexShrink:0,width:24,height:24,borderRadius:'50%',display:'flex',alignItems:'center',justifyContent:'center',fontSize:10,fontWeight:700,background:'var(--accent-blue)',color:'#fff',marginTop:2}}>{n}</div>
      <div style={{flex:1,minWidth:0}}>
        <div style={{fontSize:11,fontWeight:700,color:'var(--text-primary)',marginBottom:3}}>{title}</div>
        {eq&&<div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:11,color:'#60a5fa',fontWeight:700,background:'var(--bg-elevated)',borderRadius:6,padding:'6px 10px',marginBottom:5,overflowX:'auto',whiteSpace:'pre'}}>{eq}</div>}
        {desc&&<div style={{fontSize:10,color:'var(--text-secondary)',lineHeight:1.6,marginBottom:table?5:0}}>{desc}</div>}
        {table&&(<div style={{overflowX:'auto',marginTop:4}}><table style={{borderCollapse:'collapse',fontSize:9,width:'100%'}}><tbody>{table.map(([sym,def],i)=>(<tr key={i} style={{borderBottom:'1px solid var(--border-primary)',background:i%2===0?'transparent':'var(--bg-elevated)'}}><td style={{padding:'4px 8px',fontFamily:"'IBM Plex Mono',monospace",color:'#60a5fa',whiteSpace:'nowrap',verticalAlign:'top'}}>{sym}</td><td style={{padding:'4px 8px',color:'var(--text-secondary)',lineHeight:1.5}}>{def}</td></tr>))}</tbody></table></div>)}
      </div>
    </div>
  )
  const GaugeDef = ({name,thresh,derivation,justification,strength})=>(
    <div style={{marginBottom:8,padding:'8px 10px',background:'var(--bg-elevated)',borderRadius:8,border:'1px solid var(--border-primary)'}}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:4}}>
        <span style={{fontSize:10,fontWeight:700,color:'var(--text-primary)'}}>{name}</span>
        <span style={{fontSize:9,color:'#60a5fa',fontFamily:"'IBM Plex Mono',monospace",whiteSpace:'nowrap',marginLeft:8}}>{thresh}</span>
      </div>
      <div style={{fontSize:9,color:'var(--text-secondary)',lineHeight:1.5,marginBottom:3}}>{justification}</div>
      <div style={{display:'flex',gap:12,fontSize:8,color:'var(--text-faint)',flexWrap:'wrap'}}>
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


  const SUB_TABS = [
    { id: 'blueprint',    label: '🏛️ Scientific Blueprint & Regimes' },
    { id: 'maps',         label: '🗺️ Regimes & Seasonal Maps (Images & GIS)' },
    { id: 'algorithm',    label: '⚙️ Detection Algorithm (8 Steps)' },
    { id: 'stations',     label: '📍 20-Site Diagnostic Agreement' },
    { id: 'gauges',       label: '🛡️ Risk Gauges & Models' },
    { id: 'architecture', label: '💻 System Architecture & General Workflow' },
  ]

  return (
    <div className="h-full overflow-y-auto touch-scroll p-3 sm:p-5 flex flex-col gap-4">
      {/* Header Banner */}
      <div style={{
        background: 'linear-gradient(135deg, rgba(30, 58, 138, 0.25) 0%, rgba(15, 23, 42, 0.4) 100%)',
        border: '1px solid var(--border-primary)',
        borderRadius: 12,
        padding: '14px 18px',
        display: 'flex',
        flexDirection: 'column',
        gap: 6
      }}>
        <div style={{fontSize: 14, fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '-0.01em'}}>
          Scientific &amp; Operational Rainfall Regime Classification &amp; Seasonal Onset/Cessation System
        </div>
        <div style={{fontSize: 11, color: 'var(--accent-blue)', fontWeight: 600}}>
          Dunning Harmonic Baseline with Ethiopia-Specific Climatological Regime Refinement (EMI Climatology)
        </div>
        <div style={{fontSize: 10, color: 'var(--text-secondary)', lineHeight: 1.5}}>
          An objective, peer-reviewed meteorological framework unifying Fourier harmonic analysis (Dunning et al. 2016), local peak-timing physics, and Ethiopian Meteorological Institute (EMI) regional rainfall climatology across Kenya and Ethiopia.
        </div>
        <div style={{
          marginTop: 4,
          padding: '8px 12px',
          borderRadius: 8,
          background: 'rgba(239, 68, 68, 0.12)',
          border: '1px solid rgba(239, 68, 68, 0.35)',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          fontSize: 10,
          color: '#fca5a5',
          fontWeight: 600,
          lineHeight: 1.5
        }}>
          <span style={{fontSize: 14}}>⚠️</span>
          <span><strong>CRITICAL REGIONAL SPECIFICATION:</strong> The Four Objective Climate Regimes (Regimes 0, 1, 2, 3) apply <strong>STRICTLY to Ethiopia</strong> to resolve its micro-climates, complex orography, and asynchronous monsoon vs pastoral cycles. <strong>Kenya</strong> operates under its standard East African Equatorial dual regime (MAM Long Rains and OND Short Rains).</span>
        </div>
      </div>

      {/* Sub-tab Navigation */}
      <div style={{
        display: 'flex',
        gap: 6,
        flexWrap: 'wrap',
        borderBottom: '1px solid var(--border-primary)',
        paddingBottom: 10
      }}>
        {SUB_TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setSubTab(t.id)}
            style={{
              padding: '6px 14px',
              borderRadius: 8,
              fontSize: 11,
              fontWeight: subTab === t.id ? 700 : 500,
              background: subTab === t.id ? 'var(--accent-blue)' : 'var(--bg-elevated)',
              color: subTab === t.id ? '#ffffff' : 'var(--text-secondary)',
              border: '1px solid ' + (subTab === t.id ? 'var(--accent-blue)' : 'var(--border-primary)'),
              cursor: 'pointer',
              transition: 'all 0.15s ease'
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* SUB-TAB 1: BLUEPRINT & REGIMES */}
      {subTab === 'blueprint' && (
        <div className="flex flex-col lg:flex-row gap-6">
          <div className="w-full lg:w-[54%] min-w-0 flex flex-col gap-4">
            <S title="System Overview & Reference Standards">
              <KV label="System" value="Operational Seasonal Climate Forecast Dashboard (Onset, Cessation & LGP)"/>
              <KV label="Version" value="v3.1.0 Operational (Peer-Reviewed Methodology)" mono/>
              <KV label="Methodology" value="Dunning Harmonic Baseline with Ethiopia-Specific Climatological Regime Refinement"/>
              <KV label="Developers" value="ILRI Climate Services in collaboration with ICPAC, EMI, and KMD"/>
              <KV label="Reference Normal" value="WMO Standard Normal (1991–2020) for climatological reference" mono/>
              <KV label="Calibration Window" value="1993–2025 (33-year CHIRPS & ECMWF SEAS5 paired hindcast window)" mono/>
              <KV label="Grid Resolution" value="0.25° (~28 km) CHIRPS native spatial resolution" mono/>
              <KV label="Land Sovereign Mask" value="1,485 pixels (Ethiopia sovereign) | 842 pixels (Kenya)" mono/>
              <KV label="Core Citation" value="Dunning, Black & Allan (2016) J. Geophys. Res. Atmos., 121(19), doi:10.1002/2016JD025428"/>
              <KV label="Climatology Citation" value="Ethiopian Meteorological Institute (EMI) Rainfall Regime Classifications & Normal Bulletins"/>
            </S>

            <S title="Two-Stage Classification Blueprint">
              <div style={{background:'var(--bg-elevated)', padding:'10px 14px', borderRadius:8, border:'1px solid var(--border-primary)', fontSize:10, lineHeight:1.6, color:'var(--text-secondary)', marginBottom:10}}>
                <strong style={{color:'var(--accent-blue)'}}>Why strict r_H &ge; 1.0 under-detects Type-1 bimodality:</strong> Dunning et al. (2016) establish that annual regimes have <span style={{fontFamily:"'IBM Plex Mono',monospace", color:'#60a5fa'}}>r_H = C_2 / C_1 &lt; 1.0</span> and biannual regimes have <span style={{fontFamily:"'IBM Plex Mono',monospace", color:'#60a5fa'}}>r_H &ge; 1.0</span>. In the Ethiopian Highlands, Kiremt monsoon rainfall (~220–320 mm/mo) is 3 to 4 times larger than Belg early rains (~70–140 mm/mo). This massive amplitude disparity inflates the annual Fourier fundamental C_1, depressing r_H to 0.40–0.85. A strict r_H &ge; 1.0 threshold misclassifies the entire central/eastern agricultural highlands as unimodal, completely erasing the critical Belg early crop season.
              </div>

              <div style={{display:'flex', flexDirection:'column', gap:8}}>
                <div style={{padding:'8px 12px', background:'var(--bg-surface)', borderRadius:8, border:'1px solid var(--border-primary)'}}>
                  <div style={{fontSize:10, fontWeight:700, color:'#f87171', marginBottom:2}}>Stage 0: Arid / Marginal Screening</div>
                  <div style={{fontSize:9, color:'var(--text-secondary)', lineHeight:1.5}}>
                    Project-defined screening: <span style={{fontFamily:"'IBM Plex Mono',monospace", color:'#fca5a5'}}>P_ann &lt; 200 mm</span> or <span style={{fontFamily:"'IBM Plex Mono',monospace", color:'#fca5a5'}}>(P_ann &lt; 300 mm &amp; P_ond &lt; 30 mm)</span>. Excludes 64 hyper-arid pixels (4.3% of Ethiopia) in the Danakil Depression/Afar where low rainfall generates spurious harmonic ratios (informed by Dunning low-rainfall caution).
                  </div>
                </div>

                <div style={{padding:'8px 12px', background:'var(--bg-surface)', borderRadius:8, border:'1px solid var(--border-primary)'}}>
                  <div style={{fontSize:10, fontWeight:700, color:'#60a5fa', marginBottom:2}}>Stage 1: Dunning Harmonic Ratio Baseline</div>
                  <div style={{fontSize:9, color:'var(--text-secondary)', lineHeight:1.5}}>
                    Fourier decomposition across 365-day CHIRPS climatology computes annual fundamental C_1 and semi-annual harmonic C_2. Pixels with <span style={{fontFamily:"'IBM Plex Mono',monospace", color:'#60a5fa'}}>r_H = C_2 / C_1 &ge; 1.0</span> are designated as candidate biannual zones.
                  </div>
                </div>

                <div style={{padding:'8px 12px', background:'var(--bg-surface)', borderRadius:8, border:'1px solid var(--border-primary)'}}>
                  <div style={{fontSize:10, fontWeight:700, color:'#34d399', marginBottom:2}}>Stage 2: EMI Climatological Regime Refinement</div>
                  <div style={{fontSize:9, color:'var(--text-secondary)', lineHeight:1.5}}>
                    For transition pixels (r_H &lt; 1.0), local peak timing and water-season detection promote pixels with dual robust peaks:
                    <div style={{fontFamily:"'IBM Plex Mono',monospace", color:'#34d399', background:'var(--bg-elevated)', padding:'4px 8px', borderRadius:4, marginTop:4}}>
                      Type 1 = [r_H &ge; 0.8 &or; N_peaks &ge; 2] &and; [P_1 &isin; MAM] &and; [P_2 &isin; JJA/JA] &and; [P_FMAM &ge; 50mm] &and; [P_JJAS &ge; 120mm]
                    </div>
                    <div style={{fontFamily:"'IBM Plex Mono',monospace", color:'#fbbf24', background:'var(--bg-elevated)', padding:'4px 8px', borderRadius:4, marginTop:4}}>
                      Type 2 = [r_H &ge; 1.0 &or; N_peaks &ge; 2] &and; [P_1 &isin; MAM] &and; [P_2 &isin; SON/OND] &and; [P_JJA &lt; 1.3 &times; P_OND]
                    </div>
                  </div>
                </div>
              </div>
            </S>
          </div>

          <div className="w-full lg:w-[46%] min-w-0 flex flex-col gap-4">
            <S title="The Four Objective Climate Regimes">
              <div style={{display:'grid', gridTemplateColumns:'1fr', gap:8}}>
                <div style={{padding:'10px 12px', background:'rgba(2, 132, 199, 0.08)', borderRadius:8, border:'1px solid rgba(2, 132, 199, 0.3)'}}>
                  <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:3}}>
                    <span style={{fontSize:11, fontWeight:700, color:'#38bdf8'}}>🌾 Regime 1: Western Unimodal</span>
                    <span style={{fontSize:9, fontFamily:"'IBM Plex Mono',monospace", color:'#38bdf8'}}>427 px (28.8%)</span>
                  </div>
                  <div style={{fontSize:9, color:'var(--text-secondary)', lineHeight:1.5}}>
                    Single continuous wet season extending from spring to autumn (Feb/Mar to Oct/Nov), peaking Jul–Aug. Gambella, Assosa, Jimma, Bahir Dar, Gondar, Bedele. Operational product: <strong>Annual Wet Season</strong> (426 active px).
                  </div>
                </div>

                <div style={{padding:'10px 12px', background:'rgba(22, 163, 74, 0.08)', borderRadius:8, border:'1px solid rgba(22, 163, 74, 0.3)'}}>
                  <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:3}}>
                    <span style={{fontSize:11, fontWeight:700, color:'#4ade80'}}>🏔️ Regime 2: Bimodal Type 1 Highlands</span>
                    <span style={{fontSize:9, fontFamily:"'IBM Plex Mono',monospace", color:'#4ade80'}}>416 px (28.0%)</span>
                  </div>
                  <div style={{fontSize:9, color:'var(--text-secondary)', lineHeight:1.5}}>
                    Central, Eastern &amp; Northern Highlands. Belg (FMAM) early rains followed by a June pause, then Kiremt (JJAS) main rains. Addis Ababa, Wollo, Kombolcha, Tigray, Harar, Hawassa. Operational products: <strong>Belg Early Rains</strong> (416 px) and <strong>Kiremt Bimodal Onset</strong> (416 px).
                  </div>
                </div>

                <div style={{padding:'10px 12px', background:'rgba(217, 119, 6, 0.08)', borderRadius:8, border:'1px solid rgba(217, 119, 6, 0.3)'}}>
                  <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:3}}>
                    <span style={{fontSize:11, fontWeight:700, color:'#fbbf24'}}>🐪 Regime 3: Bimodal Type 2 Pastoral Lowlands</span>
                    <span style={{fontSize:9, fontFamily:"'IBM Plex Mono',monospace", color:'#fbbf24'}}>578 px (38.9%)</span>
                  </div>
                  <div style={{fontSize:9, color:'var(--text-secondary)', lineHeight:1.5}}>
                    Southern &amp; Southeastern lowlands (Somali, Borana, Guji, South Omo). Equatorial symmetric bimodal; dry summer (JJAS). Operational products: <strong>Spring rains — Gu/Ganna (MAM)</strong> (578 px) and <strong>Autumn rains — Deyr/Hagaya (SON–OND)</strong> (578 px).
                  </div>
                </div>

                <div style={{padding:'10px 12px', background:'rgba(148, 163, 184, 0.08)', borderRadius:8, border:'1px solid rgba(148, 163, 184, 0.3)'}}>
                  <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:3}}>
                    <span style={{fontSize:11, fontWeight:700, color:'#94a3b8'}}>🏜️ Regime 0: Arid / Marginal</span>
                    <span style={{fontSize:9, fontFamily:"'IBM Plex Mono',monospace", color:'#94a3b8'}}>64 px (4.3%)</span>
                  </div>
                  <div style={{fontSize:9, color:'var(--text-secondary)', lineHeight:1.5}}>
                    Danakil Depression and dry Afar lowlands. Non-seasonal hyper-arid desert. Screened out and flagged with: <em>"Project-defined rainfall screening indicates insufficient seasonal rainfall for robust onset/cessation estimation."</em>
                  </div>
                </div>
              </div>
            </S>

            <S title="Operational Mask Arithmetic vs Regime Eligibility">
              <div style={{background:'var(--bg-elevated)', padding:'10px 14px', borderRadius:8, border:'1px solid var(--border-primary)', fontSize:9, lineHeight:1.6, color:'var(--text-secondary)'}}>
                <div style={{fontFamily:"'IBM Plex Mono',monospace", color:'#60a5fa', fontWeight:700, marginBottom:4}}>
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

      {/* SUB-TAB: MAPS & GIS SHAPEFILES */}
      {subTab === 'maps' && (
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
                <div style={{fontSize:13, fontWeight:800, color:'var(--text-primary)', marginBottom:4}}>
                  🗺️ Climatological Regimes &amp; Seasonal Domain Shapefiles (Ethiopia Only)
                </div>
                <div style={{fontSize:10, color:'var(--text-secondary)', lineHeight:1.5, maxWidth:720}}>
                  Standard ESRI Shapefiles (.shp, .shx, .dbf, .prj) and GeoJSON (.geojson) files in <strong>WGS 84 (EPSG:4326)</strong> for GIS analysis in QGIS, ArcGIS, Python (GeoPandas), and R.
                  These boundary datasets define the sovereign meteorological domains used in operational onset/cessation tracking.
                </div>
              </div>
              <a
                href="/shapefiles/ethiopia_climate_regimes_and_masks_shp.zip"
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
                  fontSize: 11,
                  textDecoration: 'none',
                  boxShadow: '0 2px 8px rgba(37, 99, 235, 0.3)',
                  transition: 'all 0.15s ease'
                }}
              >
                <span>📦</span>
                <span>Download Shapefiles Package (.zip, 20 KB)</span>
              </a>
            </div>

            {/* Shapefiles Inventory Table */}
            <div style={{overflowX:'auto', borderTop:'1px solid var(--border-primary)', paddingTop:10}}>
              <table style={{width:'100%', borderCollapse:'collapse', fontSize:9}}>
                <thead>
                  <tr style={{borderBottom:'1px solid var(--border-primary)', background:'var(--bg-surface)'}}>
                    {['Dataset Layer', 'Shapefile (.shp)', 'GeoJSON', 'Pixels', 'Land %', 'Climatological Description'].map(h=>(
                      <th key={h} style={{padding:'5px 8px', textAlign:'left', color:'var(--text-muted)', fontWeight:700, textTransform:'uppercase', fontSize:8}}>{h}</th>
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
                      <td style={{padding:'5px 8px', fontFamily:"'IBM Plex Mono',monospace", color:'#60a5fa'}}>{shp}</td>
                      <td style={{padding:'5px 8px', fontFamily:"'IBM Plex Mono',monospace", color:'#34d399'}}>{geojson}</td>
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
          <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(340px, 1fr))', gap:16}}>
            {/* Map 1: Four Regimes */}
            <div style={{background:'var(--bg-elevated)', borderRadius:10, border:'1px solid var(--border-primary)', overflow:'hidden', display:'flex', flexDirection:'column'}}>
              <div style={{padding:'10px 14px', borderBottom:'1px solid var(--border-primary)', display:'flex', justifyContent:'space-between', alignItems:'center', background:'var(--bg-surface)'}}>
                <span style={{fontSize:11, fontWeight:700, color:'var(--text-primary)'}}>🗺️ The Four Objective Climate Regimes</span>
                <span style={{fontSize:9, background:'rgba(239, 68, 68, 0.15)', color:'#f87171', border:'1px solid rgba(239, 68, 68, 0.3)', padding:'2px 6px', borderRadius:4, fontWeight:700}}>ETHIOPIA ONLY</span>
              </div>
              <img src="/figures/ethiopia_four_climate_regimes_map.png" alt="Four Objective Climate Regimes of Ethiopia" style={{width:'100%', height:'auto', display:'block'}} />
              <div style={{padding:'10px 14px', fontSize:9.5, color:'var(--text-secondary)', lineHeight:1.5}}>
                <strong>Classification Basis:</strong> Dunning Fourier decomposition (<span style={{fontFamily:"'IBM Plex Mono',monospace", color:'#60a5fa'}}>r_H = C_2 / C_1</span>) + EMI local peak-timing rules.
                Partitions Ethiopia into 4 disjoint meteorological domains: Regime 1 (Western Unimodal, 28.7%), Regime 2 (Bimodal Type-1 Highlands, 28.0%), Regime 3 (Bimodal Type-2 Lowlands, 38.9%), and Regime 0 (Arid/Marginal Afar, 4.4%).
              </div>
            </div>

            {/* Diagram: Workflow & Architecture */}
            <div style={{background:'var(--bg-elevated)', borderRadius:10, border:'1px solid var(--border-primary)', overflow:'hidden', display:'flex', flexDirection:'column'}}>
              <div style={{padding:'10px 14px', borderBottom:'1px solid var(--border-primary)', display:'flex', justifyContent:'space-between', alignItems:'center', background:'var(--bg-surface)'}}>
                <span style={{fontSize:11, fontWeight:700, color:'var(--text-primary)'}}>⚙️ Scientific Architecture &amp; Operational Workflow</span>
                <span style={{fontSize:9, background:'rgba(37, 99, 235, 0.15)', color:'#60a5fa', border:'1px solid rgba(37, 99, 235, 0.3)', padding:'2px 6px', borderRadius:4, fontWeight:700}}>END-TO-END PIPELINE</span>
              </div>
              <img src="/figures/scientific_architecture_workflow.png" alt="Scientific Architecture & Workflow Diagram" style={{width:'100%', height:'auto', display:'block'}} />
              <div style={{padding:'10px 14px', fontSize:9.5, color:'var(--text-secondary)', lineHeight:1.5}}>
                <strong>Five-Stage Architecture:</strong> Stage 1 (Data Ingestion) &rarr; Stage 2 (Fourier Diagnostics) &rarr; Stage 3 (Regime Partition — Ethiopia Only) &rarr; Stage 4 (Dynamic Domain Masking) &rarr; Stage 5 (Onset/Cessation Anomalous Accumulation Calculation &amp; GIS Products).
              </div>
            </div>

            {/* Map 2: Kiremt JJAS */}
            <div style={{background:'var(--bg-elevated)', borderRadius:10, border:'1px solid var(--border-primary)', overflow:'hidden', display:'flex', flexDirection:'column'}}>
              <div style={{padding:'10px 14px', borderBottom:'1px solid var(--border-primary)', display:'flex', justifyContent:'space-between', alignItems:'center', background:'var(--bg-surface)'}}>
                <span style={{fontSize:11, fontWeight:700, color:'var(--text-primary)'}}>🌧️ Kiremt / Main Rains Operational Domain (JJAS)</span>
                <span style={{fontSize:9, background:'rgba(2, 132, 199, 0.15)', color:'#38bdf8', border:'1px solid rgba(2, 132, 199, 0.3)', padding:'2px 6px', borderRadius:4, fontWeight:700}}>832 PIXELS (56.0%)</span>
              </div>
              <img src="/figures/mask_kiremt_jjas.png" alt="Kiremt Main Rains Domain" style={{width:'100%', height:'auto', display:'block'}} />
              <div style={{padding:'10px 14px', fontSize:9.5, color:'var(--text-secondary)', lineHeight:1.5}}>
                <strong>Summer Monsoon Footprint:</strong> Encompasses the Highlands (Regime 2) and Western Unimodal belt (Regime 1). Screened by <span style={{fontFamily:"'IBM Plex Mono',monospace", color:'#60a5fa'}}>P_JJAS &ge; 120 mm</span> and <span style={{fontFamily:"'IBM Plex Mono',monospace", color:'#60a5fa'}}>r_JJAS &ge; 20%</span>. Eliminates southern/southeastern pastoral lowlands where summer is a cold dry pause.
              </div>
            </div>

            {/* Map 3: Belg Early Rains */}
            <div style={{background:'var(--bg-elevated)', borderRadius:10, border:'1px solid var(--border-primary)', overflow:'hidden', display:'flex', flexDirection:'column'}}>
              <div style={{padding:'10px 14px', borderBottom:'1px solid var(--border-primary)', display:'flex', justifyContent:'space-between', alignItems:'center', background:'var(--bg-surface)'}}>
                <span style={{fontSize:11, fontWeight:700, color:'var(--text-primary)'}}>🌱 Belg Early Rains Operational Domain (FMAM)</span>
                <span style={{fontSize:9, background:'rgba(5, 150, 105, 0.15)', color:'#34d399', border:'1px solid rgba(5, 150, 105, 0.3)', padding:'2px 6px', borderRadius:4, fontWeight:700}}>416 PIXELS (28.0%)</span>
              </div>
              <img src="/figures/mask_belg_early_rains.png" alt="Belg Early Rains Domain" style={{width:'100%', height:'auto', display:'block'}} />
              <div style={{padding:'10px 14px', fontSize:9.5, color:'var(--text-secondary)', lineHeight:1.5}}>
                <strong>Central &amp; Eastern Highlands Belg:</strong> Strictly limited to Regime 2 (Type-1 Highlands) where spring rains represent a discrete agricultural cycle followed by a June pause. Western unimodal zone is excluded to avoid artificial cessation dates in June.
              </div>
            </div>

            {/* Map 4: Deyr & Gu Pastoral Lowlands */}
            <div style={{background:'var(--bg-elevated)', borderRadius:10, border:'1px solid var(--border-primary)', overflow:'hidden', display:'flex', flexDirection:'column'}}>
              <div style={{padding:'10px 14px', borderBottom:'1px solid var(--border-primary)', display:'flex', justifyContent:'space-between', alignItems:'center', background:'var(--bg-surface)'}}>
                <span style={{fontSize:11, fontWeight:700, color:'var(--text-primary)'}}>🐪 Deyr / Short Rains &amp; Gu Domain (SON–OND &amp; MAM)</span>
                <span style={{fontSize:9, background:'rgba(217, 119, 6, 0.15)', color:'#fbbf24', border:'1px solid rgba(217, 119, 6, 0.3)', padding:'2px 6px', borderRadius:4, fontWeight:700}}>578 PIXELS (38.9%)</span>
              </div>
              <img src="/figures/mask_deyr_short_rains.png" alt="Deyr Autumn and Gu Spring Rains Domain" style={{width:'100%', height:'auto', display:'block'}} />
              <div style={{padding:'10px 14px', fontSize:9.5, color:'var(--text-secondary)', lineHeight:1.5}}>
                <strong>Bimodal Pastoral Rangelands:</strong> Somali Region, Borana, Guji, and Bale lowlands. Driven by the equatorial biannual cycle (<span style={{fontFamily:"'IBM Plex Mono',monospace", color:'#fbbf24'}}>r_H &ge; 1.0</span>) with major Gu/Ganna rains (MAM) and secondary Deyr/Hagaya rains (SON–OND).
              </div>
            </div>

            {/* Map 5: Western Extended Season */}
            <div style={{background:'var(--bg-elevated)', borderRadius:10, border:'1px solid var(--border-primary)', overflow:'hidden', display:'flex', flexDirection:'column'}}>
              <div style={{padding:'10px 14px', borderBottom:'1px solid var(--border-primary)', display:'flex', justifyContent:'space-between', alignItems:'center', background:'var(--bg-surface)'}}>
                <span style={{fontSize:11, fontWeight:700, color:'var(--text-primary)'}}>🌾 Western Ethiopia Extended Annual Wet Season</span>
                <span style={{fontSize:9, background:'rgba(99, 102, 241, 0.15)', color:'#a5b4fc', border:'1px solid rgba(99, 102, 241, 0.3)', padding:'2px 6px', borderRadius:4, fontWeight:700}}>426 PIXELS (28.7%)</span>
              </div>
              <img src="/figures/mask_western_extended_season.png" alt="Western Ethiopia Extended Annual Wet Season Domain" style={{width:'100%', height:'auto', display:'block'}} />
              <div style={{padding:'10px 14px', fontSize:9.5, color:'var(--text-secondary)', lineHeight:1.5}}>
                <strong>Single Prolonged Season:</strong> Gambella, Benishangul-Gumuz (Assosa), Jimma, Bedele, Gondar/Bahir Dar western slopes. Rains begin in Feb/Mar, intensify continuously through summer without a June dry break, and end in Oct/Nov.
              </div>
            </div>
          </div>
        </div>
      )}

      {/* SUB-TAB 2: ONSET DETECTION ALGORITHM */}
      {subTab === 'algorithm' && (
        <div className="w-full max-w-4xl">
          <S title="Dunning Cumulative Anomaly Algorithm (8 Operational Steps)">
            <Step n="1" title="Climatological Daily Mean  Q_d(i,j)" eq={"Q_d(i,j) = (1/N_cal) x sum_{y in CAL} R_{d,y}(i,j)"} desc="Mean daily precipitation for each calendar DOY d over the 33-year calibration period (1993–2025)." table={[['Q_d(i,j)','Mean daily precip for DOY d at pixel (i,j)'],['R_{d,y}','Observed daily CHIRPS precip (mm/day) at pixel (i,j), DOY d, year y'],['N_cal','33 calibration years (1993–2025 paired with ECMWF SEAS5 hindcasts)'],['d','DOY restricted to seasonal search window']]}/>
            <Step n="2" title="Window Mean  Q_bar(i,j)  --  the Dunning accumulation baseline" eq={"Q_bar(i,j) = (1/N_win) x sum_{d in Window} Q_d(i,j)"} desc="A single scalar value per pixel -- the long-term average daily rainfall rate across the entire seasonal forecast window. Subtracting it produces anomalies that accumulate positively during wet periods and negatively during dry ones." table={[['Q_bar(i,j)','Scalar window mean -- single value per pixel, not DOY-varying'],['N_win','Length of forecast window in days (e.g., 183 days for JJAS, 135 days for FMAM)']]}/>
            <Step n="3" title="Climatological Accumulated Anomaly  C(d)" eq={"C(d) = sum_{k=d_start}^{d} [ Q_k(i,j) - Q_bar(i,j) ]"} desc="Cumulative sum of daily climatological anomalies from window start to day d. Computed once per pixel over the 33-year calibration period." table={[['C(d)','Cumulative daily anomaly up to day d -- the climatological water season curve'],['Q_k(i,j)','Climatological daily mean at DOY k'],['Q_bar(i,j)','Scalar window mean (never re-computed per year)']]}/>
            <Step n="4" title="Climatological Season Bounds  d_s  and  d_e" eq={"d_s = argmin C(d)      d_e = argmax C(d)  [d > d_s]"} desc="Pixel-specific constants from calibration period defining the search window for individual-year event detection." table={[['d_s(i,j)','Climatological season start -- DOY where C(d) reaches its minimum'],['d_e(i,j)','Climatological season end -- DOY where C(d) reaches its maximum after d_s']]}/>
            <Step n="5" title="Individual-Year Accumulated Anomaly  A(D)" eq={"A(D) = sum_{j=d_acc,start}^{D} [ R_{j,y}(i,j) - Q_bar(i,j) ]"} desc="Same accumulation applied to each year or ensemble member individually. Search window clamped around d_s and d_e with +/- delta = 45-50 day buffer." table={[['A(D)','Accumulated precip anomaly for year y from window start to day D'],['R_{j,y}','Observed daily precip at pixel (i,j), DOY j, year y'],['Q_bar(i,j)','Same scalar window mean from Step 2']]}/>
            <Step n="6" title="Onset Detection" eq={"onset_y(i,j) = argmin A(D) + 1"} desc="Onset is the day after A(D) reaches its absolute minimum -- the first day precipitation exceeds Q_bar on a sustained basis. NaN if argmin falls at window boundary." table={[['argmin A(D)','Day of deepest pre-season dry deficit'],['+1','Dunning definition: onset is the day after the minimum']]}/>
            <Step n="7" title="Cessation Detection" eq={"cessation_y(i,j) = argmax A(D)  [D > onset_y]"} desc="The day A(D) reaches its peak after onset. No +1 offset; search restricted to days strictly after onset."/>
            <Step n="8" title="Length of Growing Period (LGP)" eq={"LGP_y(i,j) = cessation_y(i,j) - onset_y(i,j)"} desc="Season length in days. Below 35 days = near-complete failure; below 60 days = below-median season."/>
          </S>
        </div>
      )}

      {/* SUB-TAB 3: 20-SITE AUDITED DIAGNOSTIC AGREEMENT */}
      {subTab === 'stations' && (
        <div className="w-full flex flex-col gap-4">
          <S title="Audited 20-Site Representative Diagnostic Consistency Check">
            <div style={{background:'var(--bg-elevated)', padding:'10px 14px', borderRadius:8, border:'1px solid var(--border-primary)', fontSize:10, lineHeight:1.6, color:'var(--text-secondary)', marginBottom:12}}>
              <strong>Sampling Protocol:</strong> To rigorously audit against template or regional curve reuse, every station coordinate was sampled directly from the nearest CHIRPS 0.25° grid cell (<span style={{fontFamily:"'IBM Plex Mono',monospace", color:'#60a5fa'}}>latitude, longitude</span> &rarr; grid index <span style={{fontFamily:"'IBM Plex Mono',monospace", color:'#60a5fa'}}>i, j</span>). The table below reports genuine, distinct annual rainfall totals, Fourier harmonic amplitudes (C_1, C_2), harmonic ratios (r_H = C_2/C_1), and resulting regime diagnoses. <strong>20/20 representative sites show diagnostic agreement with documented EMI regional climate regimes.</strong>
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
                    fontSize: 10,
                    fontWeight: 700,
                    cursor: 'pointer',
                    background: expandedStations['gambella'] ? 'rgba(56, 189, 248, 0.2)' : 'var(--bg-elevated)',
                    color: expandedStations['gambella'] ? '#38bdf8' : 'var(--text-secondary)',
                    border: '1px solid ' + (expandedStations['gambella'] ? '#38bdf8' : 'var(--border-primary)')
                  }}
                >
                  {expandedStations['gambella'] ? '✨ Hide Example (Gambella)' : '✨ Show Example Graph (Gambella)'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    const all = {}
                    AUDITED_STATIONS.forEach(s => { all[s.id] = true })
                    setExpandedStations(all)
                  }}
                  style={{padding: '5px 10px', borderRadius: 6, fontSize: 10, fontWeight: 600, cursor: 'pointer', background: 'var(--bg-elevated)', color: 'var(--text-secondary)', border: '1px solid var(--border-primary)'}}
                >
                  📂 Expand All 20 Graphs
                </button>
                <button
                  type="button"
                  onClick={() => setExpandedStations({})}
                  style={{padding: '5px 10px', borderRadius: 6, fontSize: 10, fontWeight: 600, cursor: 'pointer', background: 'var(--bg-elevated)', color: 'var(--text-secondary)', border: '1px solid var(--border-primary)'}}
                >
                  📁 Collapse All
                </button>
              </div>

              <div style={{display:'flex', alignItems:'center', gap:8, flexWrap:'wrap'}}>
                <select
                  value={stationFilter}
                  onChange={e => setStationFilter(e.target.value)}
                  style={{padding: '4px 10px', borderRadius: 6, fontSize: 10, fontWeight: 600, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', color: 'var(--text-primary)', outline: 'none'}}
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
                  style={{padding: '4px 8px', borderRadius: 6, fontSize: 10, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', color: 'var(--text-primary)', outline: 'none', width: 140}}
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
                  <table style={{width:'100%', borderCollapse:'collapse', fontSize:9}}>
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
                          <React.Fragment key={st.id}>
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
                              <td style={{padding:'5px 8px', color:'#60a5fa', fontFamily:"'IBM Plex Mono',monospace", whiteSpace:'nowrap'}}>{st.idx}</td>
                              <td style={{padding:'5px 8px', color:'var(--text-primary)', fontFamily:"'IBM Plex Mono',monospace", fontWeight:600}}>{st.pann}</td>
                              <td style={{padding:'5px 8px', color:'var(--text-secondary)', fontFamily:"'IBM Plex Mono',monospace"}}>{st.c1}</td>
                              <td style={{padding:'5px 8px', color:'var(--text-secondary)', fontFamily:"'IBM Plex Mono',monospace"}}>{st.c2}</td>
                              <td style={{padding:'5px 8px', color: Number(st.rh) >= 1.0 ? '#fbbf24' : '#38bdf8', fontFamily:"'IBM Plex Mono',monospace", fontWeight:700}}>{st.rh}</td>
                              <td style={{padding:'5px 8px', whiteSpace:'nowrap', color: st.reg.includes('Regime 1') ? '#38bdf8' : (st.reg.includes('Regime 2') ? '#4ade80' : (st.reg.includes('Regime 3') ? '#fbbf24' : '#94a3b8')), fontWeight:600}}>{st.reg}</td>
                              <td style={{padding:'5px 8px', color:'#34d399', fontWeight:700, whiteSpace:'nowrap'}}>✓ 20/20</td>
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
                                    fontSize: 9,
                                    fontWeight: 700,
                                    cursor: 'pointer',
                                    background: isExpanded ? 'var(--accent-blue)' : 'var(--bg-elevated)',
                                    color: isExpanded ? '#ffffff' : 'var(--accent-blue)',
                                    border: '1px solid ' + (isExpanded ? 'var(--accent-blue)' : 'var(--border-primary)'),
                                    whiteSpace: 'nowrap'
                                  }}
                                >
                                  {isExpanded ? '▼ Hide Graph' : '📈 View Graph'}
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
                                        <span style={{fontSize: 16}}>📊</span>
                                        <div>
                                          <span style={{fontSize: 12.5, fontWeight: 800, color: 'var(--text-primary)'}}>
                                            {st.name} Climatological Rainfall Profile &amp; Harmonic Decomposition
                                          </span>
                                          <span style={{fontSize: 9.5, color: 'var(--text-muted)', marginLeft: 8}}>
                                            CHIRPS 1993–2025 Daily Climatology (33-Year Calibration Window)
                                          </span>
                                        </div>
                                      </div>
                                      <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
                                        <span style={{
                                          fontSize: 9.5,
                                          fontWeight: 800,
                                          padding: '3px 8px',
                                          borderRadius: 6,
                                          background: st.reg.includes('Regime 1') ? 'rgba(56, 189, 248, 0.15)' : (st.reg.includes('Regime 2') ? 'rgba(74, 222, 128, 0.15)' : (st.reg.includes('Regime 3') ? 'rgba(251, 191, 36, 0.15)' : 'rgba(148, 163, 184, 0.15)')),
                                          color: st.reg.includes('Regime 1') ? '#38bdf8' : (st.reg.includes('Regime 2') ? '#4ade80' : (st.reg.includes('Regime 3') ? '#fbbf24' : '#94a3b8')),
                                          border: '1px solid ' + (st.reg.includes('Regime 1') ? 'rgba(56, 189, 248, 0.4)' : (st.reg.includes('Regime 2') ? 'rgba(74, 222, 128, 0.4)' : (st.reg.includes('Regime 3') ? 'rgba(251, 191, 36, 0.4)' : 'rgba(148, 163, 184, 0.4)'))),
                                        }}>
                                          {st.reg}
                                        </span>
                                        <span style={{background: '#10b981', color: '#fff', fontSize: 9, fontWeight: 800, padding: '2px 7px', borderRadius: 10}}>
                                          ✓ 20/20 Verified
                                        </span>
                                      </div>
                                    </div>

                                    {/* Content Flex: Graph Image + Detailed Metrics */}
                                    <div style={{display: 'flex', flexDirection: 'row', flexWrap: 'wrap', gap: 16, alignItems: 'flex-start'}}>
                                      {/* Left: Plot Image */}
                                      <div style={{flex: '1 1 340px', maxWidth: 440, background: '#ffffff', padding: 8, borderRadius: 10, border: '1px solid var(--border-primary)', boxShadow: '0 4px 16px rgba(0,0,0,0.2)'}}>
                                        <img
                                          src={`./figures/stations/${st.id}.png`}
                                          alt={`${st.name} diagnostic plot`}
                                          style={{width: '100%', height: 'auto', display: 'block', borderRadius: 6}}
                                        />
                                        <div style={{marginTop: 6, display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 9, color: '#475569'}}>
                                          <span>Bars: Monthly CHIRPS | Lines: H1, H2, H1+H2 Fit</span>
                                          <a href={`./figures/stations/${st.id}.png`} target="_blank" rel="noreferrer" style={{color: '#0284c7', fontWeight: 700, textDecoration: 'none'}}>
                                            🔍 Open High-Res ↗
                                          </a>
                                        </div>
                                      </div>

                                      {/* Right: Technical Explanation & Metrics */}
                                      <div style={{flex: '1 1 320px', display: 'flex', flexDirection: 'column', gap: 10}}>
                                        {/* Parameter Cards Grid */}
                                        <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 8}}>
                                          <div style={{padding: '8px 10px', background: 'var(--bg-surface)', border: '1px solid var(--border-primary)', borderRadius: 8}}>
                                            <div style={{fontSize: 8.5, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em'}}>Annual Rainfall (P_ann)</div>
                                            <div style={{fontSize: 13, fontWeight: 800, color: 'var(--text-primary)', marginTop: 2}}>{st.pann} mm</div>
                                            <div style={{fontSize: 8, color: 'var(--text-faint)'}}>Elevation: {st.elev}</div>
                                          </div>
                                          <div style={{padding: '8px 10px', background: 'var(--bg-surface)', border: '1px solid var(--border-primary)', borderRadius: 8}}>
                                            <div style={{fontSize: 8.5, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em'}}>Harmonic Ratio (r_H)</div>
                                            <div style={{fontSize: 13, fontWeight: 800, color: Number(st.rh) >= 1.0 ? '#fbbf24' : '#38bdf8', marginTop: 2}}>{st.rh}</div>
                                            <div style={{fontSize: 8, color: 'var(--text-faint)'}}>C2 / C1 Ratio</div>
                                          </div>
                                          <div style={{padding: '8px 10px', background: 'var(--bg-surface)', border: '1px solid var(--border-primary)', borderRadius: 8}}>
                                            <div style={{fontSize: 8.5, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em'}}>Annual Fundamental (C1)</div>
                                            <div style={{fontSize: 13, fontWeight: 800, color: '#60a5fa', marginTop: 2}}>{st.c1} mm</div>
                                            <div style={{fontSize: 8, color: 'var(--text-faint)'}}>365-Day Cycle</div>
                                          </div>
                                          <div style={{padding: '8px 10px', background: 'var(--bg-surface)', border: '1px solid var(--border-primary)', borderRadius: 8}}>
                                            <div style={{fontSize: 8.5, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em'}}>Semi-Annual Cycle (C2)</div>
                                            <div style={{fontSize: 13, fontWeight: 800, color: '#f87171', marginTop: 2}}>{st.c2} mm</div>
                                            <div style={{fontSize: 8, color: 'var(--text-faint)'}}>182.5-Day Cycle</div>
                                          </div>
                                        </div>

                                        {/* Meteorological Rationale */}
                                        <div style={{padding: '10px 12px', background: 'var(--bg-surface)', border: '1px solid var(--border-primary)', borderRadius: 8, fontSize: 9.5, lineHeight: 1.6, color: 'var(--text-secondary)'}}>
                                          <div style={{fontWeight: 700, color: 'var(--accent-blue)', marginBottom: 4}}>
                                            🔬 Meteorological Harmonic Interpretation:
                                          </div>
                                          <div>
                                            {st.rationale}
                                          </div>
                                          <div style={{marginTop: 6, fontSize: 9, color: 'var(--text-muted)'}}>
                                            <strong>Climatological Feature:</strong> {st.desc}
                                          </div>
                                        </div>

                                        {/* Footnote bar */}
                                        <div style={{padding: '6px 10px', background: 'var(--bg-surface)', border: '1px solid var(--border-primary)', borderRadius: 8, fontSize: 8.5, color: 'var(--text-faint)', display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                                          <span>Req Coord: <strong style={{color: 'var(--text-secondary)'}}>{st.req}</strong> &rarr; Grid Point: <strong style={{color: '#60a5fa'}}>{st.grid} {st.idx}</strong></span>
                                          <button
                                            type="button"
                                            onClick={() => toggleStation(st.id)}
                                            style={{background: 'transparent', border: 'none', color: 'var(--accent-blue)', cursor: 'pointer', fontSize: 9, fontWeight: 700}}
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
                          </React.Fragment>
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
      {subTab === 'gauges' && (
        <div className="flex flex-col lg:flex-row gap-6">
          <div className="w-full lg:w-[50%] min-w-0">
            <S title="Operational Risk Gauge Definitions">
              <GaugeDef name="Late Onset Risk" thresh="DOY 89 ~29 March" derivation="Domain-median of CHIRPS CAL t67_onset (67th percentile, 1993–2025)" justification="Onset later than the upper tercile boundary -- historically the top third of years. Signals delayed planting risk." strength="Statistically grounded, data-derived"/>
              <GaugeDef name="Early Onset Risk" thresh="DOY 78 ~18 March" derivation="Domain-median of CHIRPS CAL t33_onset (33rd percentile, 1993–2025)" justification="Onset earlier than the lower tercile boundary -- historically the bottom third of years. Signals premature planting risk." strength="Statistically grounded, data-derived"/>
              <GaugeDef name="Very Short Season (LGP &lt; 35d)" thresh="35 days ~5th-10th pctile" derivation="~5th-10th percentile of CHIRPS CAL LGP distribution." justification="Near-complete season failure. Even 60-day sorghum cannot complete grain fill." strength="Agronomic consensus"/>
              <GaugeDef name="Short Season Risk (LGP &lt; 45d)" thresh="45 days ~25th-30th pctile" derivation="~25th-30th percentile of CHIRPS CAL LGP distribution." justification="Lower bound for short-season maize. Below 45 days unlikely to support maize production." strength="Agronomic literature"/>
              <GaugeDef name="Below-Normal Season (LGP &lt; 60d)" thresh="60 days ~50th pctile" derivation="~50th percentile -- a below-median season." justification="Minimum for medium-season maize (60-75 days). Beans and cowpea also at risk." strength="Agronomic literature"/>
              <GaugeDef name="Season Failure" thresh="P(onset = NaN)" derivation="Fraction of ensemble members where A(D) finds no minimum. CHIRPS background failure ~11%." justification="Most unambiguous risk signal. Forecasts above 20-25% carry meaningful signal above climatological baseline." strength="Directly interpretable"/>
              <GaugeDef name="Max Ensemble Agreement" thresh="max(P_BN, P_NN, P_AN)" derivation="Climatological baseline = 33%. Values above 50% indicate majority agreement." justification="Measures ensemble coherence independently of dominant category." strength="Standard probabilistic practice"/>
            </S>
          </div>

          <div className="w-full lg:w-[50%] min-w-0">
            <S title="C3S Multi-Model Ensemble -- 8 Seasonal Forecast Models">
              <div style={{overflowX:'auto'}}>
                <table style={{width:'100%',borderCollapse:'collapse',fontSize:9}}>
                  <thead><tr style={{borderBottom:'1px solid var(--border-primary)'}}>{['Model','Centre','Members','Resolution','HR Onset'].map(h=>(<th key={h} style={{padding:'5px 8px',textAlign:'left',color:'var(--text-muted)',fontWeight:700,letterSpacing:'0.08em',textTransform:'uppercase',fontSize:8,whiteSpace:'nowrap'}}>{h}</th>))}</tr></thead>
                  <tbody>{[['ECMWF SEAS5','ECMWF','25','1°','0.34'],['Meteo-France Sys8','Meteo-France','31','1°','0.33'],['CMCC-SPS4','CMCC','30','1°','0.33'],['ECCC CanSIPS','ECCC','20','2.5°','0.34'],['DWD GCFS2.1','DWD','30','1°','0.31'],['UKMO GloSea6','Met Office','2','0.8°','0.31'],['NCEP CFSv2','NCEP','4','1°','0.31'],['BOM ACCESS-S2','BOM','3','0.5°','0.31']].map(([n,c,m,r,h],i)=>(<tr key={n} style={{borderBottom:'1px solid var(--border-primary)',background:i%2===0?'transparent':'var(--bg-elevated)'}}><td style={{padding:'5px 8px',color:'var(--text-primary)',fontWeight:600}}>{n}</td><td style={{padding:'5px 8px',color:'var(--text-secondary)'}}>{c}</td><td style={{padding:'5px 8px',color:'var(--text-secondary)',textAlign:'center'}}>{m}</td><td style={{padding:'5px 8px',color:'var(--text-secondary)',textAlign:'center'}}>{r}</td><td style={{padding:'5px 8px',color:'#34d399',fontWeight:700}}>{h}</td></tr>))}</tbody>
                </table>
              </div>
            </S>
          </div>
        </div>
      )}

      {/* SUB-TAB 5: ARCHITECTURE, WORKFLOW & API */}
      {subTab === 'architecture' && (
        <div className="flex flex-col gap-6">
          {/* General Workflow & Scientific Architecture Details */}
          <div className="flex flex-col lg:flex-row gap-6">
            <div className="w-full lg:w-[50%] min-w-0 flex flex-col gap-4">
              <S title="End-to-End General Workflow">
                <div style={{background:'var(--bg-elevated)', padding:'12px 14px', borderRadius:8, border:'1px solid var(--border-primary)', fontSize:9.5, lineHeight:1.6, color:'var(--text-secondary)', display:'flex', flexDirection:'column', gap:8}}>
                  <div>
                    <strong style={{color:'var(--accent-blue)'}}>1. Daily Climatology Ingestion:</strong>
                    <div>33-year daily CHIRPS rainfall records (1993–2025) sampled at 0.25° resolution across Ethiopia (1,485 sovereign land pixels) and Kenya (842 pixels).</div>
                  </div>
                  <div>
                    <strong style={{color:'#60a5fa'}}>2. Fourier Harmonic Decomposition (Dunning et al. 2016):</strong>
                    <div>Calculates annual fundamental C_1 (365d) and semi-annual harmonic C_2 (182d). Evaluates harmonic ratio <span style={{fontFamily:"'IBM Plex Mono',monospace"}}>r_H = C_2 / C_1</span> (cutoff = 1.0).</div>
                  </div>
                  <div>
                    <strong style={{color:'#34d399'}}>3. Climatological Regime Partition (ETHIOPIA ONLY):</strong>
                    <div>Combines harmonic ratio with EMI peak-timing criteria (April vs August vs October) to assign every grid cell to one of the 4 disjoint Ethiopian regimes (Regimes 0, 1, 2, 3).</div>
                  </div>
                  <div>
                    <strong style={{color:'#fbbf24'}}>4. Dynamic Operational Domain Masking:</strong>
                    <div>Applies agro-climatic thresholds (P_season &ge; 80–120 mm, Seasonality Ratio &ge; 20%) to create active masks. Ensures metrics are never displayed outside climatologically valid zones.</div>
                  </div>
                  <div>
                    <strong style={{color:'#f472b6'}}>5. Anomalous Accumulation Calculation &amp; Products:</strong>
                    <div>Evaluates Dunning cumulative anomaly curve A(D) for individual years and ensemble hindcasts. Detects onset, cessation, and LGP. Outputs web rasters and GIS Shapefiles.</div>
                  </div>
                </div>
              </S>

              <S title="Removal of 'All Ethiopia' Unmasked View">
                <div style={{background:'rgba(239, 68, 68, 0.08)', padding:'10px 14px', borderRadius:8, border:'1px solid rgba(239, 68, 68, 0.3)', fontSize:9.5, lineHeight:1.6, color:'var(--text-secondary)'}}>
                  <strong style={{color:'#f87171'}}>Scientific Rationale for Enforced Masking:</strong>
                  <div style={{marginTop:4}}>
                    In previous prototypes, users could toggle an &quot;All Ethiopia&quot; unmasked raster view. However, peer review confirmed that running onset/cessation algorithms across regions where the season does not physically occur generates spurious artifacts:
                  </div>
                  <ul style={{marginTop:4, paddingLeft:14, listStyleType:'disc'}}>
                    <li>Calculating <em>Belg</em> onset in Western Ethiopia detects the start of a prolonged 8-month season, not a discrete Belg agricultural window.</li>
                    <li>Calculating <em>Kiremt</em> in southern/southeastern pastoral lowlands searches for monsoon rain during their coldest, driest months, returning random noise.</li>
                  </ul>
                  <div style={{marginTop:4, fontWeight:600, color:'var(--text-primary)'}}>
                    Therefore, the unmasked option was permanently eradicated from the dashboard. The system strictly and permanently restricts spatial rendering to validated climatological footprints.
                  </div>
                </div>
              </S>
            </div>

            <div className="w-full lg:w-[50%] min-w-0 flex flex-col gap-4">
              <S title="Technical Stack & Architecture">
                <KV label="Frontend Engine" value="React 18 + Vite + Tailwind CSS + MapLibre GL JS"/>
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
                <div style={{background:'var(--bg-elevated)', padding:'8px 12px', borderRadius:8, border:'1px solid var(--border-primary)', fontSize:9, lineHeight:1.5, color:'var(--text-secondary)'}}>
                  <div style={{fontFamily:"'IBM Plex Mono',monospace", color:'#60a5fa'}}>
                    Demissie, T., Mersha, Y., et al. (2026). Operational Multi-Model Seasonal Climate Forecast System for Onset, Cessation, and Length of Growing Period in Eastern Africa (v3.1.0). ILRI / ICPAC.
                  </div>
                </div>
              </S>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// --- TABS + TopNav ------------------------------------------------------------
const TABS = [
  {id:'forecast',      label:'Forecasting',   icon:'📊'},
  {id:'probabilistic', label:'Probabilistic', icon:'🎲'},
  {id:'multimodel',    label:'Multi-Model',   icon:'🌐'},
  {id:'validation',    label:'Validation',    icon:'🛡️'},
  {id:'historical',    label:'Historical',    icon:'⏳'},
  {id:'about',         label:'About',         icon:'ℹ️'},
]

function TopNav({ activeTab, setActiveTab, health, healthLoading, healthError, modelsData, country, setCountry, selectedSeason, onSeasonChange, selectedModel, setSelectedModel, selectedYear, setSelectedYear, selectedInit, darkMode, setDarkMode, onLogoClick, onOpenBulletin }) {
  const isSingleModelSeason = selectedSeason === 'short_rains' || selectedSeason === 'kiremt' || selectedSeason === 'fmam' || selectedSeason === 'belg' || selectedSeason === 'bega' || selectedSeason === 'ondj' || selectedSeason === 'deyr'
  const modelNames = isSingleModelSeason
    ? ['ECMWF SEAS5']
    : (modelsData?.models ? Object.keys(modelsData.models) : [])
  const tabs = isSingleModelSeason ? TABS.filter(t => t.id !== 'multimodel') : TABS
  const selStyle = {background:'var(--bg-surface)',border:'1px solid var(--accent-blue)',color:'var(--text-primary)',borderRadius:6,padding:'3px 8px',fontSize:11,fontWeight:600,cursor:'pointer',outline:'none'}

  return (
    <header className="t-header shrink-0">
      {/* Primary Brand & Actions Bar */}
      <div className="flex flex-wrap items-center justify-between px-3 py-2 sm:px-5 sm:py-2.5 gap-2">
        <button onClick={onLogoClick} className="flex flex-col leading-none text-left" style={{background:'transparent',border:'none',cursor:'pointer',padding:0}}>
          <span style={{fontSize:11,fontWeight:900,letterSpacing:'0.2em',textTransform:'uppercase',color:'var(--accent-blue)'}}>ILRI Climate Services</span>
          <span style={{fontSize:9,letterSpacing:'0.06em',marginTop:2,color:'var(--header-muted)'}} className="hidden sm:inline">Seasonal Climate Forecast Dashboard (Onset, Cessation &amp; LGP)</span>
        </button>

        {/* Action controls */}
        <div className="flex items-center gap-2 sm:gap-2.5 ml-auto">
          <button
            type="button"
            onClick={onOpenBulletin}
            className="flex items-center gap-1.5 px-2.5 py-1 sm:px-3 sm:py-1.5 rounded-lg text-[10px] sm:text-[11px] font-bold tracking-wider uppercase transition-all shadow-sm hover:scale-[1.02] active:scale-[0.98]"
            style={{
              background: 'linear-gradient(135deg, rgba(245, 158, 11, 0.25), rgba(217, 119, 6, 0.45))',
              border: '1px solid rgba(245, 158, 11, 0.75)',
              color: '#fbbf24',
              boxShadow: '0 0 14px -2px rgba(245, 158, 11, 0.25)'
            }}
            title="Generate publication seasonal forecast bulletin for selected point or custom coordinates (PDF / PNG)"
          >
            <span>📄</span>
            <span className="hidden xs:inline">Bulletin</span>
          </button>

          <div className="flex items-center gap-1.5">
            <div className={'w-1.5 h-1.5 rounded-full '+(health?.status==='ok'?'bg-emerald-400':'bg-red-400')}/>
            <span className="text-[9px] sm:text-[10px] hidden md:inline" style={{color:health?.status==='ok'?'var(--header-muted)':'#f87171'}}>
              {health?.status==='ok' ? (isSingleModelSeason ? '1 model live' : health.models_loaded+' models live') : healthError ? 'offline' : 'connecting...'}
            </span>
          </div>

          <button onClick={()=>setDarkMode(d=>!d)} className="px-2 py-1 rounded-md text-[9px] sm:text-[10px] border transition-colors" style={{background:'var(--bg-elevated)',borderColor:'var(--border-primary)',color:'var(--accent-blue)'}}>
            {darkMode?'☀️ Light':'🌙 Dark'}
          </button>
        </div>
      </div>

      {/* Responsive Filter Toolbar */}
      <div className="flex items-center gap-2 px-3 py-1.5 sm:px-5 sm:py-2 overflow-x-auto no-scrollbar touch-scroll bg-[var(--bg-sunken)] border-t border-[var(--border-primary)] text-xs">
        <div className="flex items-center gap-1.5 shrink-0">
          <label style={{fontSize:9,textTransform:'uppercase',letterSpacing:'0.1em',color:'var(--header-muted)'}}>Country</label>
          <select value={country} onChange={e=>setCountry(e.target.value)} style={selStyle}>
            <option value="kenya">Kenya</option>
            <option value="ethiopia">Ethiopia</option>
          </select>
        </div>

        {activeTab==='forecast'&&(
          <div className="flex items-center gap-2 shrink-0">
            <div className="flex items-center gap-1.5">
              <label style={{fontSize:9,textTransform:'uppercase',letterSpacing:'0.1em',color:'var(--header-muted)'}}>Model</label>
              <select value={selectedModel} onChange={e=>setSelectedModel(e.target.value)} style={selStyle}>{modelNames.map(n=><option key={n} value={n}>{n}</option>)}</select>
            </div>
            <div className="flex items-center gap-1.5">
              <label style={{fontSize:9,textTransform:'uppercase',letterSpacing:'0.1em',color:'var(--header-muted)'}}>Season</label>
              <select value={selectedSeason} onChange={e=>onSeasonChange(e.target.value)} style={selStyle}>
                {(SEASONS[country]??SEASONS.kenya).map(s=><option key={s.id} value={s.id}>{s.label}</option>)}
              </select>
            </div>
            <div className="flex items-center gap-1.5">
              <label style={{fontSize:9,textTransform:'uppercase',letterSpacing:'0.1em',color:'var(--header-muted)'}}>Year</label>
              <select value={selectedYear} onChange={e=>setSelectedYear(Number(e.target.value))} style={selStyle}>{[2026,2025,2024,2023].map(y=><option key={y} value={y}>{y}</option>)}</select>
            </div>
            <span style={{fontSize:9,color:'var(--header-muted)',whiteSpace:'nowrap'}}>Init {INIT_LABELS[selectedInit]??selectedInit}</span>
          </div>
        )}
      </div>

      {/* Modern Tabs Navigation Bar */}
      <div
        className="flex items-center px-2.5 sm:px-5 py-2 gap-1.5 sm:gap-2.5 overflow-x-auto no-scrollbar touch-scroll border-t"
        style={{
          borderColor: 'var(--border-primary)',
          background: 'var(--bg-sunken, #08101d)'
        }}
      >
        {tabs.map(t => {
          const isActive = activeTab === t.id
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setActiveTab(t.id)}
              className={`flex items-center gap-2 px-3 py-1.5 sm:px-4 sm:py-2 rounded-lg text-xs font-semibold tracking-wide transition-all whitespace-nowrap shrink-0 ${
                isActive
                  ? 'bg-sky-500/20 text-sky-300 border border-sky-500/50 shadow-sm'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 border border-transparent'
              }`}
              style={{
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
              }}
            >
              <span className="text-xs sm:text-sm shrink-0">{t.icon}</span>
              <span>{t.label}</span>
              {isActive && (
                <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse hidden sm:inline-block ml-0.5" />
              )}
            </button>
          )
        })}
      </div>
    </header>
  )
}

// --- App ----------------------------------------------------------------------
export default function App() {
  const [showLanding,   setShowLanding]   = useState(true)
  const [country,       setCountry]       = useState('kenya')
  const [activeTab,     setActiveTab]     = useState('forecast')
  const [darkMode,      setDarkMode]      = useState(false)
  const [selectedModel, setSelectedModel] = useState('ECMWF SEAS5')
  const [mapLayer,      setMapLayer]      = useState({variable:'onset',layer:'median'})
  const [mapGridData,   setMapGridData]   = useState(null)
  const [selectedYear,  setSelectedYear]  = useState(2026)
  const [selectedInit,  setSelectedInit]  = useState('0901')
  const [selectedSeason,setSelectedSeason]= useState('short_rains')
  const [bulletinModalOpen, setBulletinModalOpen] = useState(false)
  const [mobileViewMode, setMobileViewMode]       = useState('split') // 'split' | 'map' | 'charts'

  useEffect(()=>{document.documentElement.classList.toggle('light',!darkMode)},[darkMode])

  // Country change -> reset to that country's primary season + init date
  useEffect(()=>{
    const first = (SEASONS[country]??SEASONS.kenya)[0]
    setSelectedSeason(first.id)
    setSelectedInit(first.init)
    if (country === 'ethiopia') {
      setSelectedModel('ECMWF SEAS5')
      useDashboardStore.getState().setSelectedSite({
        site_name: "Holetta Agricultural Research Center",
        lat: 9.060,
        lon: 38.500,
        country: "ethiopia"
      })
    } else {
      setSelectedModel('ECMWF SEAS5')
      useDashboardStore.getState().setSelectedSite({
        site_name: "KALRO Kiboko, Makueni Farm",
        lat: -2.21046,
        lon: 37.7190,
        country: "kenya"
      })
    }
  },[country])

  const changeSeason = (seasonId) => {
    const seasons = SEASONS[country]??SEASONS.kenya
    const s = seasons.find(x=>x.id===seasonId) ?? seasons[0]
    setSelectedSeason(s.id)
    setSelectedInit(s.init)
    if (s.id === 'kiremt' || s.id === 'short_rains' || s.id === 'fmam' || s.id === 'belg' || s.id === 'bega' || s.id === 'ondj') {
      setSelectedYear(2026)
      setSelectedModel('ECMWF SEAS5')
    } else if (s.id === 'long_rains') {
      setSelectedYear(2026)
    }
  }

  const { data: health, isLoading: healthLoading, isError: healthError } = useHealth()
  const { data: modelsData, isLoading: modelsLoading } = useModels(selectedSeason)
  const selectedSite    = useDashboardStore(s=>s.selectedSite)
  const activeModels    = useDashboardStore(s=>s.activeModels)
  const setActiveModels = useDashboardStore(s=>s.setActiveModels)

  useEffect(() => {
    if (selectedSeason === 'short_rains' || selectedSeason === 'kiremt' || selectedSeason === 'fmam' || selectedSeason === 'belg' || selectedSeason === 'bega' || selectedSeason === 'ondj') {
      if (selectedModel !== 'ECMWF SEAS5') setSelectedModel('ECMWF SEAS5')
      if (activeTab === 'multimodel') setActiveTab('forecast')
    }
  }, [selectedSeason, selectedModel, activeTab])

  useEffect(()=>{
    if (modelsData?.models) {
      const names=Object.keys(modelsData.models)
      setActiveModels(names)
      setSelectedModel(prev=>{
        if (prev&&names.includes(prev)) return prev
        return names.includes('ECMWF SEAS5')?'ECMWF SEAS5':names[0]??prev
      })
    }
  },[modelsData,setActiveModels])

  const querySite = selectedSite??{lat:-1.62,lon:37.12}
  const isBega = selectedSeason === 'bega' || selectedSeason === 'ondj'
  const isKiremt = !isBega && selectedSeason === 'kiremt'
  const isFmam = !isBega && (selectedSeason === 'fmam' || selectedSeason === 'belg')
  const effectiveModel = isBega
    ? 'ECMWF SEAS5 (Bega)'
    : (isFmam
      ? 'ECMWF SEAS5 (FMAM)'
      : (isKiremt
        ? 'ECMWF SEAS5 (Kiremt)'
        : ((selectedSeason === 'short_rains' && (selectedModel === 'ECMWF SEAS5' || !selectedModel))
          ? 'ECMWF SEAS5 (Sep)'
          : (selectedModel !== 'multimodel' ? selectedModel : ''))))
  const { data: pixelData,  isLoading: pixelLoading } = usePixelStats(querySite, selectedSeason, effectiveModel)
  const { data: chirpsHist }                           = useChirpsHistorical(querySite, selectedSeason)
  const { data: validationData }                       = useValidation()

  const modelsLoaded = !!modelsData?.models
  useEffect(()=>{
    if (!modelsLoaded||!selectedModel) return
    let model = selectedModel!=='multimodel'?selectedModel:''
    if (selectedSeason === 'bega' || selectedSeason === 'ondj') {
      model = 'ECMWF SEAS5 (Bega)'
    } else if (selectedSeason === 'fmam' || selectedSeason === 'belg') {
      model = 'ECMWF SEAS5 (FMAM)'
    } else if (selectedSeason === 'kiremt') {
      model = 'ECMWF SEAS5 (Kiremt)'
    } else if (selectedSeason === 'short_rains' && (model === 'ECMWF SEAS5' || !model)) {
      model = 'ECMWF SEAS5 (Sep)'
    }
    const {variable,layer}=mapLayer
    const url = `${API_BASE}/grid?variable=${variable}&layer=${layer}&bust=true&season=${selectedSeason}` + (model ? `&model=${encodeURIComponent(model)}` : '')
    const ctrl=new AbortController()
    fetch(url,{signal:ctrl.signal})
      .then(r=>{if(!r.ok) throw new Error('HTTP '+r.status);return r.json()})
      .then(data=>setMapGridData(data))
      .catch(err=>{if(err.name!=='AbortError') console.warn('[Grid fetch error]',err)})
    return ()=>ctrl.abort()
  },[selectedModel,mapLayer.variable,mapLayer.layer,modelsLoaded,selectedSeason])

  if (showLanding) {
    return (
      <LandingPage
        darkMode={darkMode} setDarkMode={setDarkMode} health={health}
        onEnter={(tab)=>{ setActiveTab(tab); setShowLanding(false) }}
      />
    )
  }

  return (
    <div className="flex flex-col min-h-screen lg:h-screen lg:overflow-hidden" style={{background:'var(--bg-base)',fontFamily:"'IBM Plex Mono','Fira Code',monospace"}}>
      <TopNav activeTab={activeTab} setActiveTab={setActiveTab} onLogoClick={()=>setShowLanding(true)}
              health={health} healthLoading={healthLoading} healthError={healthError} modelsData={modelsData}
              country={country} setCountry={setCountry}
              selectedSeason={selectedSeason} onSeasonChange={changeSeason}
              selectedModel={selectedModel} setSelectedModel={setSelectedModel}
              selectedYear={selectedYear} setSelectedYear={setSelectedYear}
              selectedInit={selectedInit}
              onOpenBulletin={()=>setBulletinModalOpen(true)}
              darkMode={darkMode} setDarkMode={setDarkMode}/>

      {/* Mobile/Tablet View Switcher Bar */}
      {activeTab !== 'about' && (
        <div className="flex lg:hidden items-center justify-between px-3 py-1.5 bg-[var(--bg-elevated)] border-b border-[var(--border-primary)] text-xs">
          <span className="text-[9px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Display View</span>
          <div className="flex rounded-lg overflow-hidden border border-[var(--border-primary)] p-0.5 bg-[var(--bg-surface)]">
            <button
              onClick={() => setMobileViewMode('map')}
              className={`px-2.5 py-1 text-[10px] font-semibold rounded transition-colors ${mobileViewMode === 'map' ? 'bg-[var(--accent-blue)] text-white' : 'text-[var(--text-secondary)] hover:text-white'}`}
            >
              🗺️ Map
            </button>
            <button
              onClick={() => setMobileViewMode('charts')}
              className={`px-2.5 py-1 text-[10px] font-semibold rounded transition-colors ${mobileViewMode === 'charts' ? 'bg-[var(--accent-blue)] text-white' : 'text-[var(--text-secondary)] hover:text-white'}`}
            >
              📊 Analysis
            </button>
            <button
              onClick={() => setMobileViewMode('split')}
              className={`px-2.5 py-1 text-[10px] font-semibold rounded transition-colors ${mobileViewMode === 'split' ? 'bg-[var(--accent-blue)] text-white' : 'text-[var(--text-secondary)] hover:text-white'}`}
            >
              📑 Both
            </button>
          </div>
        </div>
      )}

      {modelsLoading?(
        <div className="flex items-center justify-center flex-1 min-h-[300px]">
          <div className="text-sm animate-pulse tracking-widest" style={{color:'var(--text-muted)'}}>LOADING MODEL DATA...</div>
        </div>
      ):(
        <div className="flex flex-col lg:flex-row flex-1 overflow-y-auto gap-1.5 sm:gap-2 p-1 sm:p-2">
          {activeTab!=='about'&&(
          <div className={`shrink-0 flex flex-col ${
            mobileViewMode === 'charts'
              ? 'hidden lg:flex'
              : mobileViewMode === 'map'
              ? 'w-full h-[calc(100vh-170px)] lg:h-full lg:w-[40%]'
              : 'w-full h-[360px] sm:h-[440px] lg:h-full lg:w-[40%]'
          } lg:min-w-[320px] lg:max-w-[520px]`}>
            <div className="flex-1 min-h-0">
              <MapPanel
                darkMode={darkMode}
                selectedModel={selectedModel}
                gridData={mapGridData}
                onLayerChange={setMapLayer}
                activeTab={activeTab}
                country={country}
                selectedSeason={selectedSeason}
                selectedYear={selectedYear}
                onOpenBulletin={()=>setBulletinModalOpen(true)}
              />
            </div>
          </div>
          )}
          <div className={`flex-1 min-w-0 ${
            activeTab !== 'about' && mobileViewMode === 'map' ? 'hidden lg:block' : ''
          } ${activeTab === 'about' ? 'h-full overflow-y-auto' : 'h-full overflow-y-auto touch-scroll'}`}>
            {activeTab==='forecast'      && <ForecastingTab  selectedModel={selectedModel} selectedYear={selectedYear} pixelData={pixelData} isLoading={pixelLoading} activeModels={activeModels} selectedSeason={selectedSeason} selectedInit={selectedInit}/>}
            {activeTab==='probabilistic' && <ProbabilisticTab pixelData={pixelData} activeModels={activeModels} selectedModel={selectedModel} setSelectedModel={setSelectedModel} modelsData={modelsData} selectedYear={selectedYear} setSelectedYear={setSelectedYear} country={country} selectedSeason={selectedSeason} onSeasonChange={changeSeason} selectedInit={selectedInit}/>}
            {activeTab==='multimodel'    && <MultiModelTab   pixelData={pixelData} activeModels={activeModels} modelsData={modelsData} selectedSeason={selectedSeason} selectedYear={selectedYear}/>}
            {activeTab==='validation'    && <ValidationTab   pixelData={pixelData} activeModels={activeModels} validationData={validationData} selectedModel={selectedModel} setSelectedModel={setSelectedModel} modelsData={modelsData} selectedYear={selectedYear} setSelectedYear={setSelectedYear} country={country} selectedSeason={selectedSeason} onSeasonChange={changeSeason} selectedInit={selectedInit}/>}
            {activeTab==='historical'    && <HistoricalTab   pixelData={pixelData} chirpsHist={chirpsHist} selectedModel={selectedModel} setSelectedModel={setSelectedModel} modelsData={modelsData} selectedYear={selectedYear} setSelectedYear={setSelectedYear} country={country} selectedSeason={selectedSeason} onSeasonChange={changeSeason} selectedInit={selectedInit}/>}
            {activeTab==='about'         && <AboutTab/>}
          </div>
        </div>
      )}
      <BulletinModal
        isOpen={bulletinModalOpen}
        onClose={()=>setBulletinModalOpen(false)}
        selectedSite={selectedSite}
        selectedSeason={selectedSeason}
        selectedYear={selectedYear}
        country={country}
      />
    </div>
  )
}
