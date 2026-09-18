import React, { useState, useEffect } from 'react'
import { downloadBulletin } from '../api/queries'

const PRESET_FARMS_KENYA = [
  { site_name: 'KALRO Kiboko, Makueni Farm', lat: -2.21046, lon: 37.7190 },
  { site_name: 'Kapiti Research Station Farm', lat: -1.63209, lon: 37.1479 },
  { site_name: 'El Karama Sahiwals Farm', lat: -2.3871, lon: 37.4851 },
  { site_name: 'Genco LTD Maralal Samburu Farm', lat: 0.9273, lon: 36.5690 },
  { site_name: 'Genco LTD Tana River Farm', lat: -2.21314, lon: 40.0517 },
  { site_name: 'LiveMo LTD, Memerush, Kajiado Farm', lat: -2.38726, lon: 37.4850 },
]

const PRESET_FARMS_ETHIOPIA = [
  { site_name: 'Holetta Agricultural Research Center', lat: 9.060, lon: 38.500 },
  { site_name: 'Debre Zeit Agricultural Research Center', lat: 8.720, lon: 38.980 },
  { site_name: 'Melkassa Agricultural Research Center', lat: 8.410, lon: 39.310 },
  { site_name: 'Bako Agricultural Research Center', lat: 9.130, lon: 37.050 },
  { site_name: 'Hawassa Agricultural Research Center', lat: 7.060, lon: 38.500 },
  { site_name: 'Yabello Pastoral Research Station', lat: 4.880, lon: 38.080 },
  { site_name: 'Kobo Agricultural Sub-Center', lat: 12.150, lon: 39.630 },
]

const FORECAST_MODELS = [
  { id: 'ECMWF SEAS5', name: 'ECMWF SEAS5', tag: '51 ens members (MAM)', centre: 'European Centre' },
  { id: 'UKMO GloSea6', name: 'UKMO GloSea6', tag: '42 ens members', centre: 'UK Met Office' },
  { id: 'Meteo-France Sys8', name: 'Météo-France Sys8', tag: '51 ens members', centre: 'Météo-France' },
  { id: 'DWD GCFS2.1', name: 'DWD GCFS2.1', tag: '50 ens members', centre: 'Deutscher Wetterdienst' },
  { id: 'CMCC-SPS4', name: 'CMCC-SPS4', tag: '50 ens members', centre: 'Euro-Med Centre' },
  { id: 'NCEP CFSv2', name: 'NCEP CFSv2', tag: '32 ens members', centre: 'NOAA / NCEP' },
  { id: 'ECCC CanSIPS', name: 'ECCC CanSIPS', tag: '20 ens members', centre: 'Environment Canada' },
]

const SHORT_RAINS_MODELS = [
  { id: 'ECMWF SEAS5', name: 'ECMWF SEAS5 (System 51)', tag: '25 ens members (OND)', centre: 'European Centre' },
]

const KIREMT_MODELS = [
  { id: 'ECMWF SEAS5', name: 'ECMWF SEAS5 (System 51)', tag: '25 ens members (Kiremt May 01)', centre: 'European Centre' },
]

const FMAM_MODELS = [
  { id: 'ECMWF SEAS5', name: 'ECMWF SEAS5 (System 51)', tag: '25 ens members (Belg Jan 01)', centre: 'European Centre' },
]

const BEGA_MODELS = [
  { id: 'ECMWF SEAS5', name: 'ECMWF SEAS5 (System 51)', tag: '25 ens members (Deyr Sep 01)', centre: 'European Centre' },
]

export default function BulletinModal({ isOpen, onClose, selectedSite, selectedSeason = 'short_rains', selectedYear = 2026, country = 'kenya' }) {
  const isBega = selectedSeason === 'bega' || selectedSeason === 'deyr' || selectedSeason === 'ondj'
  const isEthiopia = country === 'ethiopia' || isBega || selectedSeason === 'kiremt' || selectedSeason === 'fmam' || selectedSeason === 'belg'
  const isFmam = !isBega && (selectedSeason === 'fmam' || selectedSeason === 'belg')
  const isKiremt = !isBega && !isFmam && (selectedSeason === 'kiremt' || (country === 'ethiopia' && selectedSeason !== 'bega' && selectedSeason !== 'fmam'))
  const isShort = !isEthiopia && selectedSeason === 'short_rains'
  const isSingle = isEthiopia || isShort
  const [siteName, setSiteName] = useState(isEthiopia ? 'Holetta Agricultural Research Center' : 'KALRO Kiboko, Makueni Farm')
  const [lat, setLat] = useState(isEthiopia ? 9.060 : -2.21046)
  const [lon, setLon] = useState(isEthiopia ? 38.500 : 37.7190)
  const [bulletinType, setBulletinType] = useState(isSingle ? 'single' : 'multi')
  const [selectedModel, setSelectedModel] = useState('ECMWF SEAS5')
  const [fmt, setFmt] = useState('pdf')
  const [isGenerating, setIsGenerating] = useState(false)
  const [progressMsg, setProgressMsg] = useState('')
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)

  const activePresets = isEthiopia ? PRESET_FARMS_ETHIOPIA : PRESET_FARMS_KENYA
  const activeModelsList = isBega ? BEGA_MODELS : (isFmam ? FMAM_MODELS : (isKiremt ? KIREMT_MODELS : (isShort ? SHORT_RAINS_MODELS : FORECAST_MODELS)))

  useEffect(() => {
    if (isSingle) {
      setBulletinType('single')
      setSelectedModel('ECMWF SEAS5')
    }
  }, [isSingle])

  // Initialize or update fields when selectedSite changes or modal opens
  useEffect(() => {
    if (isOpen && selectedSite) {
      const sName = selectedSite.name || selectedSite.site_name || `Point (${Number(selectedSite.lat).toFixed(3)}, ${Number(selectedSite.lon).toFixed(3)})`
      setSiteName(sName)
      setLat(Number(selectedSite.lat))
      setLon(Number(selectedSite.lon))
      setError(null)
      setSuccess(null)
    }
  }, [isOpen, selectedSite])

  if (!isOpen) return null

  const handleSyncMapPoint = () => {
    if (selectedSite) {
      setSiteName(selectedSite.name || selectedSite.site_name || `Map Point (${Number(selectedSite.lat).toFixed(3)}, ${Number(selectedSite.lon).toFixed(3)})`)
      setLat(Number(selectedSite.lat))
      setLon(Number(selectedSite.lon))
      setError(null)
      setSuccess(null)
    }
  }

  const handleSelectPreset = (farm) => {
    setSiteName(farm.site_name)
    setLat(farm.lat)
    setLon(farm.lon)
    setError(null)
    setSuccess(null)
  }

  const handleGenerate = async (e) => {
    e.preventDefault()
    setError(null)
    setSuccess(null)

    const parsedLat = parseFloat(lat)
    const parsedLon = parseFloat(lon)

    if (isNaN(parsedLat) || isNaN(parsedLon)) {
      setError('Please provide valid numerical coordinates for Latitude and Longitude.')
      return
    }

    if (isEthiopia) {
      if (parsedLat < 3.0 || parsedLat > 15.0 || parsedLon < 33.0 || parsedLon > 48.0) {
        setError('Note: Coordinates appear outside the Ethiopia domain (3.0° to 15.0°N, 33.0° to 48.0°E). The model will match the nearest land boundary pixel.')
      }
    } else {
      if (parsedLat < -5.5 || parsedLat > 5.5 || parsedLon < 33.0 || parsedLon > 42.5) {
        setError('Note: Coordinates appear outside the Kenya / East Africa domain (-5.5° to 5.5°N, 33.0° to 42.5°E). The model will match the nearest land boundary pixel.')
      }
    }

    setIsGenerating(true)
    setProgressMsg(
      bulletinType === 'single'
        ? `Extracting ${selectedModel} ensemble members & pixel climatology...`
        : 'Extracting multi-model ensemble & timing statistics...'
    )

    const msgTimer1 = setTimeout(() => {
      setProgressMsg(
        bulletinType === 'single'
          ? `Rendering ${selectedModel} precipitation plume, tercile outlooks & 44-yr time series...`
          : 'Rendering multi-model plume, probabilistic terciles & risk panels...'
      )
    }, 2500)

    const msgTimer2 = setTimeout(() => {
      setProgressMsg(fmt === 'pdf' ? 'Assembling high-resolution A3 PDF bulletin...' : 'Rendering 100 DPI publication graphic...')
    }, 5500)

    try {
      const result = await downloadBulletin({
        site_name: siteName || `Location_${parsedLat.toFixed(3)}_${parsedLon.toFixed(3)}`,
        lat: parsedLat,
        lon: parsedLon,
        fmt,
        bulletin_type: isSingle ? 'single' : bulletinType,
        model_name: isSingle ? 'ECMWF SEAS5' : selectedModel,
        season: isBega ? 'bega' : (isFmam ? 'fmam' : (isKiremt ? 'kiremt' : (selectedSeason || (isShort ? 'short_rains' : 'long_rains')))),
        year: Number(selectedYear) || 2026,
      })
      clearTimeout(msgTimer1)
      clearTimeout(msgTimer2)
      setSuccess(`Downloaded ${result.filename} (${(result.size / 1024).toFixed(0)} KB)`)
    } catch (err) {
      clearTimeout(msgTimer1)
      clearTimeout(msgTimer2)
      console.error('[Bulletin generation error]', err)
      setError(err?.response?.data?.detail || err.message || 'Bulletin generation failed. Check server logs.')
    } finally {
      setIsGenerating(false)
      setProgressMsg('')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-slate-950/80 backdrop-blur-sm animate-fadeIn">
      <div
        className="relative w-full max-w-2xl bg-slate-900 border border-slate-700/80 rounded-2xl shadow-2xl overflow-hidden flex flex-col"
        style={{
          fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
        }}
      >
        {/* Modal Header */}
        <div className="flex items-center justify-between px-4 py-3 sm:px-6 sm:py-4 border-b" style={{ borderColor: 'var(--border-primary, rgba(255,255,255,0.08))', background: 'var(--bg-elevated, #0f1f38)' }}>
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg flex items-center justify-center text-amber-400 font-bold border border-amber-500/30 shrink-0" style={{ background: 'rgba(245, 158, 11, 0.1)' }}>
              📄
            </div>
            <div>
              <h3 className="text-xs sm:text-sm font-bold tracking-wide uppercase text-slate-100 flex items-center gap-2 flex-wrap">
                Generate Seasonal Forecast Bulletin
                <span className="text-[9px] sm:text-[10px] px-2 py-0.5 rounded-full font-mono bg-amber-500/20 text-amber-300 border border-amber-500/30">
                  {isFmam ? `Belg ${selectedYear || 2026}` : isKiremt ? `Kiremt ${selectedYear || 2026}` : (isShort ? `OND ${selectedYear || 2025}` : `MAM ${selectedYear || 2026}`)}
                </span>
              </h3>
              <p className="text-[10px] sm:text-[11px] text-slate-400">Official ILRI publication template • Onset, Cessation &amp; LGP</p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={isGenerating}
            className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors text-lg shrink-0"
          >
            ×
          </button>
        </div>

        {/* Modal Body / Form */}
        <form onSubmit={handleGenerate} className="p-4 sm:p-6 space-y-4 max-h-[86vh] overflow-y-auto touch-scroll">
          {/* Bulletin Type (Multi-Model vs Single Model) */}
          <div>
            <label className="block text-[10px] font-bold tracking-wider text-slate-400 uppercase mb-1.5">
              Select Bulletin Type
            </label>
            {isSingle ? (
              <div className="p-3 rounded-xl border border-amber-500/60 bg-amber-500/10 flex items-center justify-between">
                <div>
                  <div className="text-xs font-bold text-slate-100 flex items-center gap-1.5">
                    Single-Model Operational Forecast
                    <span className="text-[9px] px-1.5 py-0.2 rounded bg-blue-400/20 text-blue-300 font-mono">ILRI PDF</span>
                  </div>
                  <div className="text-[10px] text-slate-400 mt-0.5">
                    {isBega
                      ? `Deyr Pastoral Rains (Oct-Dec ${selectedYear || 2026}) official forecast based on ECMWF SEAS5 System 51 (25 ensemble members, Sep 01 init)`
                      : isFmam
                      ? `Belg (Feb-May ${selectedYear || 2026}) official forecast based on ECMWF SEAS5 System 51 (25 ensemble members, Jan 01 init)`
                      : isKiremt
                      ? `Kiremt (Jun-Sep ${selectedYear || 2026}) official forecast based on ECMWF SEAS5 System 51 (25 ensemble members, May 01 init)`
                      : `Short Rains (OND ${selectedYear || 2026}) official forecast based on ECMWF SEAS5 System 51 (25 ensemble members)`}
                  </div>
                </div>
                <span className="text-[10px] px-2 py-0.5 rounded font-mono bg-amber-500/20 text-amber-300 border border-amber-500/40">
                  Active Season
                </span>
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                <label
                  className={`flex items-start gap-2.5 p-3 rounded-xl border cursor-pointer transition-all ${
                    bulletinType === 'multi'
                      ? 'bg-amber-500/10 border-amber-500/60 shadow-sm'
                      : 'bg-slate-900/50 border-slate-800 hover:border-slate-700'
                  }`}
                >
                  <input
                    type="radio"
                    name="bulletin-type"
                    value="multi"
                    checked={bulletinType === 'multi'}
                    onChange={() => setBulletinType('multi')}
                    className="mt-0.5 accent-amber-500"
                  />
                  <div>
                    <div className="text-xs font-bold text-slate-100 flex items-center gap-1.5">
                      Multi-Model Consensus
                      <span className="text-[9px] px-1.5 py-0.2 rounded bg-amber-400/20 text-amber-300 font-mono">Full (7 Models)</span>
                    </div>
                    <div className="text-[10px] text-slate-400 mt-0.5 leading-snug">
                      Combined 7-model multi-model ensemble forecast with Equal / HR / RPSS weighting options.
                    </div>
                  </div>
                </label>

                <label
                  className={`flex items-start gap-2.5 p-3 rounded-xl border cursor-pointer transition-all ${
                    bulletinType === 'single'
                      ? 'bg-amber-500/10 border-amber-500/60 shadow-sm'
                      : 'bg-slate-900/50 border-slate-800 hover:border-slate-700'
                  }`}
                >
                  <input
                    type="radio"
                    name="bulletin-type"
                    value="single"
                    checked={bulletinType === 'single'}
                    onChange={() => setBulletinType('single')}
                    className="mt-0.5 accent-amber-500"
                  />
                  <div>
                    <div className="text-xs font-bold text-slate-100 flex items-center gap-1.5">
                      Single-Model Diagnostic
                      <span className="text-[9px] px-1.5 py-0.2 rounded bg-blue-400/20 text-blue-300 font-mono">Individual</span>
                    </div>
                    <div className="text-[10px] text-slate-400 mt-0.5 leading-snug">
                      Detailed diagnostic bulletin focusing specifically on one chosen operational centre.
                    </div>
                  </div>
                </label>
              </div>
            )}
          </div>

          {/* Model Selector */}
          {(bulletinType === 'single' || isSingle) && (
            <div className="bg-blue-950/20 border border-blue-800/40 p-3.5 rounded-xl space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-[10px] font-bold tracking-wider text-blue-300 uppercase flex items-center gap-1.5">
                  <span>🛰️</span> Select Forecast System Model
                </label>
                <span className="text-[10px] text-slate-400">
                  {isFmam ? '1 Available Model for Belg (Jan 01 Init)' : isKiremt ? '1 Available Model for Kiremt (May 01 Init)' : (isShort ? '1 Available Model for OND' : '7 WMO GPC Models')}
                </span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                {activeModelsList.map(m => {
                  const isSelected = selectedModel === m.id
                  return (
                    <button
                      key={m.id}
                      type="button"
                      onClick={() => setSelectedModel(m.id)}
                      className={`px-2.5 py-2 rounded-lg text-left border transition-all flex items-center justify-between ${
                        isSelected
                          ? 'bg-amber-500/20 border-amber-500/60 text-amber-200'
                          : 'bg-slate-900/70 border-slate-800 text-slate-300 hover:border-slate-700 hover:bg-slate-800/50'
                      }`}
                    >
                      <div>
                        <div className="text-xs font-semibold leading-tight">{m.name}</div>
                        <div className="text-[9px] text-slate-400">{m.centre}</div>
                      </div>
                      <span className="text-[9px] px-1.5 py-0.5 rounded font-mono bg-slate-800 text-slate-300 border border-slate-700">
                        {m.tag}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {/* Farm Preset Quick Selector */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-[10px] font-bold tracking-wider text-slate-400 uppercase">
                {isEthiopia ? 'Monitored Ethiopian Research Centers' : 'Monitored Farm Site Presets'}
              </label>
              {selectedSite && (
                <button
                  type="button"
                  onClick={handleSyncMapPoint}
                  className="text-[10px] font-semibold text-amber-400 hover:text-amber-300 flex items-center gap-1 transition-colors"
                >
                  <span>📍</span> Use Selected Map Point
                </button>
              )}
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
              {activePresets.map(farm => {
                const isSelected = Math.abs(lat - farm.lat) < 0.001 && Math.abs(lon - farm.lon) < 0.001
                return (
                  <button
                    key={farm.site_name}
                    type="button"
                    onClick={() => handleSelectPreset(farm)}
                    className={`px-2.5 py-1.5 rounded-lg text-left text-[10px] font-medium border transition-all truncate ${
                      isSelected
                        ? 'bg-amber-500/20 text-amber-300 border-amber-500/50 shadow-sm'
                        : 'bg-slate-900/60 text-slate-300 border-slate-700/50 hover:border-slate-600 hover:bg-slate-800/50'
                    }`}
                    title={farm.site_name}
                  >
                    {farm.site_name.replace(' Farm', '').replace(' Agricultural Research Center', '')}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Coordinates & Custom Site Name Input */}
          <div className="bg-slate-900/40 p-4 rounded-xl border border-slate-800/80 space-y-3">
            <div>
              <label className="block text-[10px] font-bold tracking-wider text-slate-400 uppercase mb-1">
                Site / Farm Name (Printed in Bulletin Header)
              </label>
              <input
                type="text"
                value={siteName}
                onChange={e => setSiteName(e.target.value)}
                placeholder={isEthiopia ? 'e.g. Holetta Agricultural Research Center' : 'e.g. KALRO Kiboko, Makueni Farm'}
                className="w-full px-3 py-2 text-xs rounded-lg bg-slate-950/80 border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-amber-500 transition-colors font-mono"
                required
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[10px] font-bold tracking-wider text-slate-400 uppercase mb-1">
                  Latitude (°N)
                </label>
                <input
                  type="number"
                  step="any"
                  value={lat}
                  onChange={e => setLat(e.target.value)}
                  placeholder={isEthiopia ? '9.060' : '-2.210'}
                  className="w-full px-3 py-2 text-xs rounded-lg bg-slate-950/80 border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-amber-500 transition-colors font-mono"
                  required
                />
              </div>
              <div>
                <label className="block text-[10px] font-bold tracking-wider text-slate-400 uppercase mb-1">
                  Longitude (°E)
                </label>
                <input
                  type="number"
                  step="any"
                  value={lon}
                  onChange={e => setLon(e.target.value)}
                  placeholder={isEthiopia ? '38.500' : '37.719'}
                  className="w-full px-3 py-2 text-xs rounded-lg bg-slate-950/80 border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-amber-500 transition-colors font-mono"
                  required
                />
              </div>
            </div>
            <p className="text-[10px] text-slate-400 italic">
              * The backend automatically matches this point to the nearest 0.25° grid pixel (~10-15 km resolution) and extracts historical CHIRPS climatology.
            </p>
          </div>

          {/* Document Format Toggle */}
          <div>
            <label className="block text-[10px] font-bold tracking-wider text-slate-400 uppercase mb-1.5">
              Document Export Format
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label
                className={`flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-all ${
                  fmt === 'pdf'
                    ? 'bg-amber-500/10 border-amber-500/60 shadow-sm'
                    : 'bg-slate-900/50 border-slate-800 hover:border-slate-700'
                }`}
              >
                <input
                  type="radio"
                  name="bulletin-format"
                  value="pdf"
                  checked={fmt === 'pdf'}
                  onChange={() => setFmt('pdf')}
                  className="mt-0.5 text-amber-500 focus:ring-amber-500"
                />
                <div>
                  <div className="text-xs font-bold text-slate-100 flex items-center gap-1.5">
                    PDF Document
                    <span className="text-[9px] px-1.5 py-0.2 rounded bg-amber-400/20 text-amber-300 font-mono">A3 Printable</span>
                  </div>
                  <div className="text-[10px] text-slate-400 mt-0.5">High-definition vector layout with 10mm margins</div>
                </div>
              </label>

              <label
                className={`flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-all ${
                  fmt === 'png'
                    ? 'bg-amber-500/10 border-amber-500/60 shadow-sm'
                    : 'bg-slate-900/50 border-slate-800 hover:border-slate-700'
                }`}
              >
                <input
                  type="radio"
                  name="bulletin-format"
                  value="png"
                  checked={fmt === 'png'}
                  onChange={() => setFmt('png')}
                  className="mt-0.5 text-amber-500 focus:ring-amber-500"
                />
                <div>
                  <div className="text-xs font-bold text-slate-100 flex items-center gap-1.5">
                    PNG Image
                    <span className="text-[9px] px-1.5 py-0.2 rounded bg-blue-400/20 text-blue-300 font-mono">150 DPI</span>
                  </div>
                  <div className="text-[10px] text-slate-400 mt-0.5">Digital raster graphic for slides & reports</div>
                </div>
              </label>
            </div>
          </div>

          {/* Feedback messages */}
          {error && (
            <div className="p-3 rounded-xl bg-red-950/40 border border-red-800/60 text-red-300 text-xs flex items-start gap-2">
              <span className="text-sm">⚠️</span>
              <div className="flex-1">{error}</div>
            </div>
          )}

          {success && (
            <div className="p-3 rounded-xl bg-emerald-950/40 border border-emerald-800/60 text-emerald-300 text-xs flex items-center gap-2">
              <span className="text-sm">✓</span>
              <div className="flex-1 font-mono text-[11px]">{success}</div>
            </div>
          )}

          {/* Submit / Generate Button */}
          <div className="pt-2">
            <button
              type="submit"
              disabled={isGenerating}
              className={`w-full py-3 px-4 rounded-xl text-xs font-bold tracking-wider uppercase transition-all flex items-center justify-center gap-2 ${
                isGenerating
                  ? 'bg-amber-600/50 text-amber-200 cursor-not-allowed border border-amber-500/30'
                  : 'bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-400 hover:to-amber-500 text-slate-950 shadow-lg shadow-amber-500/20 active:scale-[0.99] border border-amber-400'
              }`}
            >
              {isGenerating ? (
                <>
                  <svg className="animate-spin h-4 w-4 text-amber-200" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  <span>{progressMsg || 'Generating Bulletin...'}</span>
                </>
              ) : (
                <>
                  <span>Download Bulletin ({fmt.toUpperCase()})</span>
                  <span>↓</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
