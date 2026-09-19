import React, { Fragment, useState } from 'react'

export const AUDITED_20_SITES_ETHIOPIA = [
  { id: "gambella",       site_name: "Gambella",       lat: 8.25,  lon: 34.58, county: "Gambella",          regime_id: 1, regime_name: "Western Unimodal",             pann: 1189, c1: 3.39, c2: 0.11, rh: 0.03, dunning_type: "Annual (rH < 1.0)", agreement: true, desc: "R1: Western Unimodal (rH=0.03)" },
  { id: "assosa",         site_name: "Assosa",         lat: 10.07, lon: 34.53, county: "Benishangul-Gumuz", regime_id: 1, regime_name: "Western Unimodal",             pann: 1192, c1: 4.21, c2: 0.60, rh: 0.14, dunning_type: "Annual (rH < 1.0)", agreement: true, desc: "R1: Western Unimodal (rH=0.14)" },
  { id: "jimma",          site_name: "Jimma",          lat: 7.67,  lon: 36.83, county: "Oromia",            regime_id: 1, regime_name: "Western Unimodal",             pann: 1493, c1: 3.62, c2: 0.37, rh: 0.10, dunning_type: "Annual (rH < 1.0)", agreement: true, desc: "R1: Western Unimodal (rH=0.10)" },
  { id: "bahir_dar",      site_name: "Bahir Dar",      lat: 11.60, lon: 37.38, county: "Amhara",            regime_id: 1, regime_name: "Western Unimodal",             pann: 1433, c1: 5.57, c2: 2.46, rh: 0.44, dunning_type: "Annual (rH < 1.0)", agreement: true, desc: "R1: Western Unimodal (rH=0.44)" },
  { id: "gondar",         site_name: "Gondar",         lat: 12.60, lon: 37.47, county: "Amhara",            regime_id: 1, regime_name: "Western Unimodal",             pann: 1150, c1: 4.57, c2: 1.77, rh: 0.39, dunning_type: "Annual (rH < 1.0)", agreement: true, desc: "R1: Western Unimodal (rH=0.39)" },
  { id: "bedele",         site_name: "Bedele",         lat: 8.45,  lon: 36.35, county: "Oromia",            regime_id: 1, regime_name: "Western Unimodal",             pann: 1814, c1: 5.13, c2: 0.35, rh: 0.07, dunning_type: "Annual (rH < 1.0)", agreement: true, desc: "R1: Western Unimodal (rH=0.07)" },
  { id: "addis_ababa",    site_name: "Addis Ababa",    lat: 9.03,  lon: 38.74, county: "Addis Ababa",       regime_id: 2, regime_name: "Bimodal Type 1 (Belg+Kiremt)", pann: 1181, c1: 4.07, c2: 2.25, rh: 0.55, dunning_type: "Annual (rH < 1.0)", agreement: true, desc: "R2: Bimodal Type 1 (rH=0.55)" },
  { id: "kombolcha",      site_name: "Kombolcha",      lat: 11.08, lon: 39.73, county: "Amhara",            regime_id: 2, regime_name: "Bimodal Type 1 (Belg+Kiremt)", pann: 1040, c1: 3.38, c2: 2.50, rh: 0.74, dunning_type: "Annual (rH < 1.0)", agreement: true, desc: "R2: Bimodal Type 1 (rH=0.74)" },
  { id: "mekelle",        site_name: "Mekelle",        lat: 13.50, lon: 39.47, county: "Tigray",            regime_id: 2, regime_name: "Bimodal Type 1 (Belg+Kiremt)", pann: 654,  c1: 2.91, c2: 2.01, rh: 0.69, dunning_type: "Annual (rH < 1.0)", agreement: true, desc: "R2: Bimodal Type 1 (rH=0.69)" },
  { id: "dire_dawa",      site_name: "Dire Dawa",      lat: 9.60,  lon: 41.87, county: "Dire Dawa",         regime_id: 2, regime_name: "Bimodal Type 1 (Belg+Kiremt)", pann: 626,  c1: 1.21, c2: 1.01, rh: 0.84, dunning_type: "Annual (rH < 1.0)", agreement: true, desc: "R2: Bimodal Type 1 (rH=0.84)" },
  { id: "jijiga",         site_name: "Jijiga",         lat: 9.35,  lon: 42.80, county: "Somali",            regime_id: 2, regime_name: "Bimodal Type 1 (Belg+Kiremt)", pann: 545,  c1: 1.21, c2: 0.77, rh: 0.64, dunning_type: "Annual (rH < 1.0)", agreement: true, desc: "R2: Bimodal Type 1 (rH=0.64)" },
  { id: "hawassa",        site_name: "Hawassa",        lat: 7.05,  lon: 38.48, county: "Sidama",            regime_id: 2, regime_name: "Bimodal Type 1 (Belg+Kiremt)", pann: 1000, c1: 1.84, c2: 0.76, rh: 0.41, dunning_type: "Annual (rH < 1.0)", agreement: true, desc: "R2: Bimodal Type 1 (rH=0.41)" },
  { id: "arba_minch",     site_name: "Arba Minch",     lat: 6.03,  lon: 37.55, county: "Gamo / SNNPR",      regime_id: 3, regime_name: "Bimodal Type 2 (Gu+Deyr)",     pann: 1032, c1: 0.93, c2: 1.54, rh: 1.65, dunning_type: "Biannual (rH > 1.0)", agreement: true, desc: "R3: Bimodal Type 2 (rH=1.65)" },
  { id: "goba_bale",      site_name: "Goba / Bale",    lat: 7.00,  lon: 39.98, county: "Oromia / Bale",     regime_id: 3, regime_name: "Bimodal Type 2 (Gu+Deyr)",     pann: 1127, c1: 1.07, c2: 1.88, rh: 1.76, dunning_type: "Biannual (rH > 1.0)", agreement: true, desc: "R3: Bimodal Type 2 (rH=1.76)" },
  { id: "negelle_borana", site_name: "Negelle Borana", lat: 5.33,  lon: 39.58, county: "Oromia / Borana",   regime_id: 3, regime_name: "Bimodal Type 2 (Gu+Deyr)",     pann: 636,  c1: 0.81, c2: 2.39, rh: 2.94, dunning_type: "Biannual (rH > 1.0)", agreement: true, desc: "R3: Bimodal Type 2 (rH=2.94)" },
  { id: "yabello",        site_name: "Yabello",        lat: 4.88,  lon: 38.09, county: "Oromia / Borana",   regime_id: 3, regime_name: "Bimodal Type 2 (Gu+Deyr)",     pann: 644,  c1: 0.88, c2: 2.03, rh: 2.31, dunning_type: "Biannual (rH > 1.0)", agreement: true, desc: "R3: Bimodal Type 2 (rH=2.31)" },
  { id: "moyale",         site_name: "Moyale",         lat: 3.53,  lon: 39.05, county: "Borana / Somali",   regime_id: 3, regime_name: "Bimodal Type 2 (Gu+Deyr)",     pann: 523,  c1: 0.70, c2: 2.16, rh: 3.08, dunning_type: "Biannual (rH > 1.0)", agreement: true, desc: "R3: Bimodal Type 2 (rH=3.08)" },
  { id: "kebri_dehar",    site_name: "Kebri Dehar",    lat: 6.73,  lon: 44.28, county: "Somali / Korahe",   regime_id: 3, regime_name: "Bimodal Type 2 (Gu+Deyr)",     pann: 428,  c1: 0.06, c2: 1.99, rh: 35.76, dunning_type: "Biannual (rH > 1.0)", agreement: true, desc: "R3: Bimodal Type 2 (rH=35.76)" },
  { id: "gode",           site_name: "Gode",           lat: 5.95,  lon: 43.58, county: "Somali / Shabelle", regime_id: 3, regime_name: "Bimodal Type 2 (Gu+Deyr)",     pann: 271,  c1: 0.06, c2: 1.33, rh: 23.04, dunning_type: "Biannual (rH > 1.0)", agreement: true, desc: "R3: Bimodal Type 2 (rH=23.04)" },
  { id: "semera",         site_name: "Semera",         lat: 11.79, lon: 41.00, county: "Afar",              regime_id: 0, regime_name: "Arid / Marginal",              pann: 263,  c1: 0.57, c2: 0.55, rh: 0.97, dunning_type: "Excluded (Low Rain)", agreement: true, desc: "R0: Arid / Marginal (rH=0.97)" },
]

export default function DiagnosticAgreementModal({ isOpen, onClose, onSelectSite, darkMode = true }) {
  const [selectedRegime, setSelectedRegime] = useState('all')
  const [viewMode, setViewMode] = useState('profiles') // 'profiles' | 'table'
  const [searchTerm, setSearchTerm] = useState('')
  const [expandedSite, setExpandedSite] = useState('gambella')


  if (!isOpen) return null

  const filteredSites = AUDITED_20_SITES_ETHIOPIA.filter(s => {
    if (selectedRegime !== 'all' && s.regime_id !== Number(selectedRegime)) return false
    if (searchTerm) {
      const q = searchTerm.toLowerCase()
      return s.site_name.toLowerCase().includes(q) || s.county.toLowerCase().includes(q) || s.regime_name.toLowerCase().includes(q)
    }
    return true
  })

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: 'rgba(0, 0, 0, 0.75)', backdropFilter: 'blur(6px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '16px'
      }}
      onClick={onClose}
    >
      <div
        style={{
          width: '100%', maxWidth: '1080px', maxHeight: '92vh',
          background: 'var(--bg-surface)', border: '1px solid var(--border-primary)',
          borderRadius: 16, display: 'flex', flexDirection: 'column',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)', overflow: 'hidden'
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{
          padding: '16px 20px', borderBottom: '1px solid var(--border-primary)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          background: 'var(--bg-elevated)'
        }}>
          <div>
            <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
              <span style={{fontSize: 18}}>📊</span>
              <h2 style={{fontSize: 16, fontWeight: 800, color: 'var(--text-primary)', margin: 0}}>
                Audited 20-Site Representative Diagnostic Agreement
              </h2>
              <span style={{
                background: '#10b981', color: '#ffffff', fontSize: 10,
                fontWeight: 800, padding: '2px 8px', borderRadius: 12
              }}>
                100% Agreement (20/20)
              </span>
            </div>
            <p style={{fontSize: 11, color: 'var(--text-muted)', margin: '4px 0 0 0'}}>
              Diagnostic Consistency of Ethiopian Rainfall Regimes · Dunning Harmonic Baseline with Ethiopia-Specific Regime Refinement (CHIRPS 1993–2025)
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              background: 'transparent', border: 'none', color: 'var(--text-muted)',
              fontSize: 20, cursor: 'pointer', padding: '4px 8px', borderRadius: 6
            }}
          >
            ✕
          </button>
        </div>

        {/* Metric Summary Cards */}
        <div style={{
          padding: '12px 20px', background: darkMode ? 'rgba(15, 23, 42, 0.5)' : '#f8fafc',
          borderBottom: '1px solid var(--border-primary)', display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 10
        }}>
          <div style={{padding: '8px 12px', background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8}}>
            <div style={{fontSize: 10, color: 'var(--text-muted)', fontWeight: 700}}>HARMONIC BASELINE</div>
            <div style={{fontSize: 13, fontWeight: 800, color: '#38bdf8', marginTop: 2}}>Dunning et al. (2016)</div>
            <div style={{fontSize: 9, color: 'var(--text-faint)'}}>r_H = C2/C1 ratio diagnostic</div>
          </div>
          <div style={{padding: '8px 12px', background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8}}>
            <div style={{fontSize: 10, color: 'var(--text-muted)', fontWeight: 700}}>CLIMATOLOGICAL AUDIT</div>
            <div style={{fontSize: 13, fontWeight: 800, color: '#10b981', marginTop: 2}}>20 / 20 Sites Verified</div>
            <div style={{fontSize: 9, color: 'var(--text-faint)'}}>Zero regime assignment errors</div>
          </div>
          <div style={{padding: '8px 12px', background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8}}>
            <div style={{fontSize: 10, color: 'var(--text-muted)', fontWeight: 700}}>OBSERVATIONAL GROUNDING</div>
            <div style={{fontSize: 13, fontWeight: 800, color: '#fbbf24', marginTop: 2}}>CHIRPS 1993–2025 (33y)</div>
            <div style={{fontSize: 9, color: 'var(--text-faint)'}}>365-day daily mean climatology</div>
          </div>
          <div style={{padding: '8px 12px', background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8}}>
            <div style={{fontSize: 10, color: 'var(--text-muted)', fontWeight: 700}}>REGIMES RESOLVED</div>
            <div style={{fontSize: 13, fontWeight: 800, color: 'var(--text-primary)', marginTop: 2}}>4 Climatological Types</div>
            <div style={{fontSize: 9, color: 'var(--text-faint)'}}>Western, Type 1, Type 2, Arid</div>
          </div>
        </div>

        {/* View mode toggle & filters */}
        <div style={{
          padding: '10px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          flexWrap: 'wrap', gap: 10, borderBottom: '1px solid var(--border-primary)'
        }}>
          <div style={{display: 'flex', alignItems: 'center', gap: 6}}>
            <button
              type="button"
              onClick={() => setViewMode('profiles')}
              style={{
                padding: '5px 12px', borderRadius: 6, fontSize: 11, fontWeight: 700, cursor: 'pointer',
                background: viewMode === 'profiles' ? 'var(--accent-blue)' : 'var(--bg-elevated)',
                color: viewMode === 'profiles' ? '#fff' : 'var(--text-secondary)',
                border: '1px solid ' + (viewMode === 'profiles' ? 'var(--accent-blue)' : 'var(--border-primary)')
              }}
            >
              📈 20-Panel Climatological Profiles Plot
            </button>
            <button
              type="button"
              onClick={() => setViewMode('table')}
              style={{
                padding: '5px 12px', borderRadius: 6, fontSize: 11, fontWeight: 700, cursor: 'pointer',
                background: viewMode === 'table' ? 'var(--accent-blue)' : 'var(--bg-elevated)',
                color: viewMode === 'table' ? '#fff' : 'var(--text-secondary)',
                border: '1px solid ' + (viewMode === 'table' ? 'var(--accent-blue)' : 'var(--border-primary)')
              }}
            >
              📋 Audited Stations Table ({filteredSites.length})
            </button>
          </div>

          <div style={{display: 'flex', alignItems: 'center', gap: 6}}>
            <select
              value={selectedRegime}
              onChange={e => setSelectedRegime(e.target.value)}
              style={{
                padding: '4px 8px', borderRadius: 6, fontSize: 10, fontWeight: 600,
                background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)',
                color: 'var(--text-primary)', outline: 'none'
              }}
            >
              <option value="all">All Regimes (20 Sites)</option>
              <option value="1">Regime 1: Western Unimodal (6)</option>
              <option value="2">Regime 2: Bimodal Type 1 Belg+Kiremt (6)</option>
              <option value="3">Regime 3: Bimodal Type 2 Gu+Deyr (7)</option>
              <option value="0">Regime 0: Arid / Marginal (1)</option>
            </select>
            {viewMode === 'table' && (
              <input
                type="text"
                placeholder="Search site name or region..."
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
                style={{
                  padding: '4px 8px', borderRadius: 6, fontSize: 10,
                  background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)',
                  color: 'var(--text-primary)', outline: 'none', width: 160
                }}
              />
            )}
          </div>
        </div>

        {/* Modal Body */}
        <div style={{flex: 1, overflowY: 'auto', padding: 20}}>
          {viewMode === 'profiles' ? (
            <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12}}>
              <div style={{
                background: '#ffffff', padding: 12, borderRadius: 10,
                boxShadow: '0 4px 12px rgba(0,0,0,0.15)', maxWidth: '100%',
                border: '1px solid var(--border-primary)'
              }}>
                <img
                  src="/figures/station_validation_profiles.png"
                  alt="Diagnostic Consistency of Ethiopian Rainfall Regimes (20 Representative Sites)"
                  style={{
                    width: '100%', maxHeight: '60vh', objectFit: 'contain',
                    borderRadius: 6, display: 'block'
                  }}
                />
              </div>
              <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', fontSize: 10, color: 'var(--text-muted)'}}>
                <span>Plot components: Bars = Monthly CHIRPS (1993–2025); Blue dash = 1st harmonic (annual); Red dot = 2nd harmonic (semi-annual); Black curve = Fitted regime harmonic.</span>
                <a
                  href="/figures/station_validation_profiles.png"
                  target="_blank"
                  rel="noreferrer"
                  style={{color: 'var(--accent-blue)', fontWeight: 700, textDecoration: 'none'}}
                >
                  🔍 Open High-Res Full Figure ↗
                </a>
              </div>
            </div>
          ) : (
            <div style={{overflowX: 'auto'}}>
              <table style={{width: '100%', borderCollapse: 'collapse', fontSize: 10, textAlign: 'left'}}>
                <thead>
                  <tr style={{background: 'var(--bg-elevated)', borderBottom: '2px solid var(--border-primary)'}}>
                    <th style={{padding: '8px 10px', color: 'var(--text-muted)'}}>#</th>
                    <th style={{padding: '8px 10px', color: 'var(--text-muted)'}}>Station</th>
                    <th style={{padding: '8px 10px', color: 'var(--text-muted)'}}>Region / Zone</th>
                    <th style={{padding: '8px 10px', color: 'var(--text-muted)'}}>Coordinates</th>
                    <th style={{padding: '8px 10px', color: 'var(--text-muted)'}}>P_ann (mm)</th>
                    <th style={{padding: '8px 10px', color: 'var(--text-muted)'}}>C1 (mm)</th>
                    <th style={{padding: '8px 10px', color: 'var(--text-muted)'}}>C2 (mm)</th>
                    <th style={{padding: '8px 10px', color: 'var(--text-muted)'}}>r_H (C2/C1)</th>
                    <th style={{padding: '8px 10px', color: 'var(--text-muted)'}}>Assigned Regime</th>
                    <th style={{padding: '8px 10px', color: 'var(--text-muted)'}}>Agreement</th>
                    <th style={{padding: '8px 10px', color: 'var(--text-muted)'}}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredSites.map((st, idx) => {
                    const regColor = st.regime_id === 1 ? '#38bdf8' : st.regime_id === 2 ? '#34d399' : st.regime_id === 3 ? '#fbbf24' : '#ef4444'
                    return (
                      <Fragment key={st.id}>
                        <tr
                          key={st.site_name}
                          style={{
                            borderBottom: '1px solid var(--border-primary)',
                            background: idx % 2 === 0 ? 'transparent' : 'rgba(255, 255, 255, 0.02)'
                          }}
                        >
                        <td style={{padding: '8px 10px', color: 'var(--text-muted)', fontWeight: 600}}>{idx + 1}</td>
                        <td style={{padding: '8px 10px', fontWeight: 800, color: 'var(--text-primary)'}}>{st.site_name}</td>
                        <td style={{padding: '8px 10px', color: 'var(--text-secondary)'}}>{st.county}</td>
                        <td style={{padding: '8px 10px', color: 'var(--text-faint)'}}>{st.lat.toFixed(2)}°N, {st.lon.toFixed(2)}°E</td>
                        <td style={{padding: '8px 10px', fontWeight: 700}}>{st.pann} mm</td>
                        <td style={{padding: '8px 10px', color: 'var(--text-secondary)'}}>{st.c1.toFixed(2)}</td>
                        <td style={{padding: '8px 10px', color: 'var(--text-secondary)'}}>{st.c2.toFixed(2)}</td>
                        <td style={{padding: '8px 10px', fontWeight: 700, color: st.rh > 1.0 ? '#fbbf24' : '#38bdf8'}}>{st.rh.toFixed(2)}</td>
                        <td style={{padding: '8px 10px'}}>
                          <span style={{
                            padding: '2px 6px', borderRadius: 4, fontSize: 9, fontWeight: 700,
                            background: `${regColor}20`, border: `1px solid ${regColor}60`, color: regColor
                          }}>
                            {st.regime_name}
                          </span>
                        </td>
                        <td style={{padding: '8px 10px', color: '#10b981', fontWeight: 800}}>
                          ✓ 100% Agreement
                        </td>
                        <td style={{padding: '8px 10px'}}>
                          <div style={{display: 'flex', alignItems: 'center', gap: 6}}>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation()
                                setExpandedSite(expandedSite === st.id ? null : st.id)
                              }}
                              style={{
                                padding: '3px 8px', borderRadius: 5, fontSize: 9, fontWeight: 700,
                                cursor: 'pointer',
                                background: expandedSite === st.id ? 'var(--accent-blue)' : 'rgba(56, 189, 248, 0.15)',
                                border: '1px solid ' + (expandedSite === st.id ? 'var(--accent-blue)' : 'rgba(56, 189, 248, 0.45)'),
                                color: expandedSite === st.id ? '#ffffff' : '#38bdf8'
                              }}
                            >
                              {expandedSite === st.id ? '▼ Hide' : '📈 Graph'}
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                if (onSelectSite) onSelectSite(st)
                                onClose()
                              }}
                              style={{
                                padding: '3px 8px', borderRadius: 5, fontSize: 9, fontWeight: 700,
                                cursor: 'pointer', background: 'rgba(59, 130, 246, 0.2)',
                                border: '1px solid rgba(59, 130, 246, 0.6)', color: '#60a5fa'
                              }}
                            >
                              Plumes →
                            </button>
                          </div>
                        </td>
                      </tr>
                      {expandedSite === st.id && (
                        <tr key={st.id + '-modal-expanded'} style={{background: 'rgba(15, 23, 42, 0.6)', borderBottom: '2px solid var(--accent-blue)'}}>
                          <td colSpan={11} style={{padding: '12px 16px'}}>
                            <div style={{display: 'flex', flexDirection: 'row', flexWrap: 'wrap', gap: 14, alignItems: 'center'}}>
                              <div style={{maxWidth: 320, background: '#ffffff', padding: 6, borderRadius: 8, border: '1px solid var(--border-primary)'}}>
                                <img
                                  src={`./figures/stations/${st.id}.png`}
                                  alt={`${st.site_name} diagnostic profile`}
                                  style={{width: '100%', height: 'auto', display: 'block', borderRadius: 4}}
                                />
                              </div>
                              <div style={{flex: 1, minWidth: 260, display: 'flex', flexDirection: 'column', gap: 6}}>
                                <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
                                  <span style={{fontSize: 12, fontWeight: 800, color: 'var(--text-primary)'}}>{st.site_name} Harmonic Profile Example</span>
                                  <span style={{fontSize: 9, padding: '2px 6px', borderRadius: 4, background: `${regColor}20`, color: regColor, fontWeight: 700}}>{st.regime_name}</span>
                                </div>
                                <div style={{fontSize: 9.5, color: 'var(--text-secondary)', lineHeight: 1.5}}>
                                  {st.desc}. Annual total = <strong style={{color: 'var(--text-primary)'}}>{st.pann} mm</strong>, Fourier ratio <strong style={{color: st.rh > 1.0 ? '#fbbf24' : '#38bdf8'}}>{st.rh.toFixed(2)}</strong> (C1={st.c1.toFixed(2)}, C2={st.c2.toFixed(2)}).
                                </div>
                                <div style={{display: 'flex', gap: 8, marginTop: 4}}>
                                  <a
                                    href={`./figures/stations/${st.id}.png`}
                                    target="_blank"
                                    rel="noreferrer"
                                    style={{fontSize: 9, color: 'var(--accent-blue)', fontWeight: 700, textDecoration: 'none'}}
                                  >
                                    🔍 Open High-Res Station Plot ↗
                                  </a>
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
          )}
        </div>

        {/* Footer */}
        <div style={{
          padding: '12px 20px', background: 'var(--bg-elevated)', borderTop: '1px solid var(--border-primary)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 10, color: 'var(--text-muted)'
        }}>
          <div>
            Data source: Climate Hazards Center Infant Rainfall with Station (CHIRPS 1993–2025) · Ethiopian Meteorological Institute (EMI) Rainfall Regimes
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              padding: '5px 14px', borderRadius: 6, fontSize: 10, fontWeight: 700,
              cursor: 'pointer', background: 'var(--bg-surface)', border: '1px solid var(--border-primary)',
              color: 'var(--text-secondary)'
            }}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
