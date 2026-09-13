import { useQuery } from '@tanstack/react-query'

const rawBase = import.meta.env.VITE_API_BASE || '/api'
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

/** GET /models -- list all loaded models with metadata */
export function useModels() {
  return useQuery({
    queryKey: ['models'],
    queryFn: () => fetchJSON('/models'),
    staleTime: Infinity,   // model list never changes during a session
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
 * GET /pixel?lat=&lon=  -- full per-model stats for a site
 * Only fires when site is selected.
 */
export function usePixelStats(site) {
  return useQuery({
    queryKey: ['pixel', site?.lat, site?.lon],
    queryFn: () => fetchJSON(`/pixel?lat=${site.lat}&lon=${site.lon}`),
    enabled: !!site,
    staleTime: 5 * 60_000,   // 5 min
  })
}

/**
 * GET /grid?variable=&layer=  -- GeoJSON for Mapbox fill layer
 * Cached for the session -- expensive to recompute.
 */
export function useGrid(variable, layer, enabled = true, model = "") {
  return useQuery({
    queryKey: ['grid', variable, layer, model],
    queryFn: () => fetchJSON(`/grid?variable=${variable}&layer=${layer}${model ? '&model='+encodeURIComponent(model) : ''}`),
    enabled,
    staleTime: 0,              // always refetch when queryKey changes (model/layer switch)
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
export function useChirpsHistorical(site) {
  const lat = site?.lat ?? -1.62
  const lon = site?.lon ?? 37.12
  return useQuery({
    queryKey: ['chirps_historical', lat, lon],
    queryFn: () => fetchJSON(`/chirps_historical?lat=${lat}&lon=${lon}`),
    staleTime: Infinity,
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
