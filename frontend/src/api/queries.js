import { useQuery } from '@tanstack/react-query'

const rawBase = import.meta.env.VITE_API_BASE || (typeof window !== 'undefined' && (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') ? 'http://127.0.0.1:8765' : '/api')
export const API_BASE = rawBase.replace(/\/+$/, '')

// -- Fetch helpers ---------------------------------------------------------

async function fetchJSON(path) {
  const cleanPath = path.startsWith('/') ? path : `/${path}`
  const url = `${API_BASE}${cleanPath}`
  const res = await fetch(url)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`API ${res.status}: ${text}`)
  }
  const contentType = res.headers.get('content-type') || ''
  if (!contentType.includes('application/json')) {
    throw new Error(`Expected JSON from API at ${url} but received ${contentType}. Check VITE_API_BASE.`)
  }
  return res.json()
}

// -- Query hooks -----------------------------------------------------------

/** GET /health */
export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => fetchJSON('/health'),
    refetchInterval: 30_000,
  })
}

/** GET /models -- list all loaded models with metadata, filtered by season */
export function useModels(season = 'long_rains') {
  return useQuery({
    queryKey: ['models', season],
    queryFn: () => fetchJSON(`/models?season=${encodeURIComponent(season || 'long_rains')}`),
    staleTime: 60_000,
  })
}

/** GET /chirps -- CHIRPS CAL domain-mean climatology */
export function useChirps() {
  return useQuery({
    queryKey: ['chirps'],
    queryFn: () => fetchJSON('/chirps'),
    staleTime: Infinity,
  })
}

/**
 * GET /pixel?lat=&lon=&season=&model=  -- full per-model stats for a site
 * Only fires when site is selected.
 */
export function usePixelStats(site, season = 'long_rains', model = '') {
  return useQuery({
    queryKey: ['pixel', site?.lat, site?.lon, season, model],
    queryFn: () => {
      const q = new URLSearchParams({
        lat: String(site.lat),
        lon: String(site.lon),
        season: season || 'long_rains',
      })
      if (model) q.set('model', model)
      return fetchJSON(`/pixel?${q.toString()}`)
    },
    enabled: !!site,
    staleTime: 5 * 60_000,   // 5 min
  })
}

/**
 * GET /grid?variable=&layer=&season=&model=  -- GeoJSON for Mapbox fill layer
 * Cached for the session -- expensive to recompute.
 */
export function useGrid(variable, layer, enabled = true, model = "", season = "long_rains") {
  return useQuery({
    queryKey: ['grid', variable, layer, model, season],
    queryFn: () => {
      const q = new URLSearchParams({
        variable,
        layer,
        season: season || 'long_rains',
      })
      if (model) q.set('model', model)
      return fetchJSON(`/grid?${q.toString()}`)
    },
    enabled,
    staleTime: 0,              // always refetch when queryKey changes (model/layer/season switch)
    gcTime:    5 * 60_000,    // cache stays 5 min for back-navigation
    refetchOnWindowFocus: false,
  })
}

/** GET /taylor -- Taylor diagram data */
export function useTaylor() {
  return useQuery({
    queryKey: ['taylor'],
    queryFn: () => fetchJSON('/taylor'),
    staleTime: Infinity,
  })
}

/** GET /sites -- registered sites list */
export function useSites() {
  return useQuery({
    queryKey: ['sites'],
    queryFn: () => fetchJSON('/sites'),
    staleTime: 60_000,
  })
}

/** GET /chirps_historical -- full CHIRPS time series + stats for a pixel */
export function useChirpsHistorical(site, season = 'long_rains') {
  const lat = site?.lat ?? -1.62
  const lon = site?.lon ?? 37.12
  return useQuery({
    queryKey: ['chirps_historical', lat, lon, season],
    queryFn: () => fetchJSON(`/chirps_historical?lat=${lat}&lon=${lon}&season=${season}`),
    staleTime: 10 * 60 * 1000,
    enabled: true,
  })
}

/** GET /validation -- domain-mean probs per VAL year per model */
export function useValidation() {
  return useQuery({
    queryKey: ['validation'],
    queryFn: () => fetchJSON('/validation'),
    staleTime: Infinity,
  })
}

/**
 * POST /bulletin -- generate and download publication bulletin (PDF or PNG)
 */
export async function downloadBulletin({ site_name, lat, lon, fmt = 'pdf', bulletin_type = 'multi', model_name = 'ECMWF SEAS5', season = 'long_rains', year = 2026 }) {
  const cleanFmt = fmt.toLowerCase() === 'png' ? 'png' : 'pdf'
  const url = `${API_BASE}/bulletin`

  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      site_name: site_name || `Location_${Number(lat).toFixed(3)}_${Number(lon).toFixed(3)}`,
      lat: Number(lat),
      lon: Number(lon),
      fmt: cleanFmt,
      bulletin_type: bulletin_type || (season === 'short_rains' ? 'single' : 'multi'),
      model_name: model_name || 'ECMWF SEAS5',
      season: season || 'long_rains',
      year: Number(year) || 2026,
    }),
  })

  if (!res.ok) {
    let errDetail = ''
    try {
      const errJson = await res.json()
      errDetail = errJson.detail || JSON.stringify(errJson)
    } catch {
      errDetail = await res.text()
    }
    throw new Error(errDetail || `Server error (${res.status})`)
  }

  const blob = await res.blob()
  const disposition = res.headers.get('content-disposition') || ''
  let filename = `bulletin_mm_${(site_name || 'site').replace(/[^a-zA-Z0-9_-]/g, '_')}_MAM2026.${cleanFmt}`
  const match = disposition.match(/filename="?([^";]+)"?/)
  if (match && match[1]) {
    filename = match[1].trim()
  }

  const blobUrl = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = blobUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => window.URL.revokeObjectURL(blobUrl), 2000)

  return { filename, size: blob.size }
}

