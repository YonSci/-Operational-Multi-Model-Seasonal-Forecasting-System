// Crop health for a farm from Sentinel-2 L2A, read in the browser. Scenes come from the Earth Search STAC catalogue
// (Element 84, AWS Open Data); the bands are cloud-optimised GeoTIFFs on AWS, so only the tiles over the farm are
// downloaded (HTTP range requests). Per scene: the scene classification (SCL, about 30 kB) first, to skip views
// where clouds cover the farm, then red, NIR, blue and SWIR for NDVI, EVI and NDMI.
import { fromUrl } from 'geotiff'
import { polygons } from './farmGeo.js'

const STAC = 'https://earth-search.aws.element84.com/v1/search'
const COLLECTION = 'sentinel-2-l2a'
export const CLEAR_MIN = 0.6           // a view counts when at least this share of the farm is clear
const CLEAR_SCL = new Set([4, 5, 6, 7]) // vegetation, bare soil, water, unclassified; not clouds, shadows, snow, no data
const MAX_PX = 400                     // the analysis grid is coarsened (overviews) to at most this many pixels across

// -- UTM (WGS84), Snyder (1987) ------------------------------------------------------------------------------------
const A = 6378137, F = 1 / 298.257223563, E2 = F * (2 - F), EP2 = E2 / (1 - E2), K0 = 0.9996
const D2R = Math.PI / 180
const zoneOf = epsg => ({ zone: epsg % 100, south: Math.floor(epsg / 100) === 327 })
export function toUTM(lon, lat, epsg) {
  const { zone, south } = zoneOf(epsg)
  const phi = lat * D2R, lam = lon * D2R, lam0 = ((zone - 1) * 6 - 180 + 3) * D2R
  const s = Math.sin(phi), c = Math.cos(phi), t = Math.tan(phi)
  const N = A / Math.sqrt(1 - E2 * s * s), T = t * t, C = EP2 * c * c, Aa = c * (lam - lam0)
  const e4 = E2 * E2, e6 = e4 * E2
  const M = A * ((1 - E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi - (3 * E2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * Math.sin(2 * phi)
                 + (15 * e4 / 256 + 45 * e6 / 1024) * Math.sin(4 * phi) - (35 * e6 / 3072) * Math.sin(6 * phi))
  const x = K0 * N * (Aa + (1 - T + C) * Aa ** 3 / 6 + (5 - 18 * T + T * T + 72 * C - 58 * EP2) * Aa ** 5 / 120) + 500000
  const y = K0 * (M + N * t * (Aa * Aa / 2 + (5 - T + 9 * C + 4 * C * C) * Aa ** 4 / 24 + (61 - 58 * T + T * T + 600 * C - 330 * EP2) * Aa ** 6 / 720))
  return [x, south ? y + 10000000 : y]
}
export function fromUTM(x, y, epsg) {
  const { zone, south } = zoneOf(epsg)
  const lam0 = ((zone - 1) * 6 - 180 + 3) * D2R
  const e4 = E2 * E2, e6 = e4 * E2, e1 = (1 - Math.sqrt(1 - E2)) / (1 + Math.sqrt(1 - E2))
  const mu = (south ? y - 10000000 : y) / K0 / (A * (1 - E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256))
  const p1 = mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * Math.sin(2 * mu) + (21 * e1 * e1 / 16 - 55 * e1 ** 4 / 32) * Math.sin(4 * mu)
           + (151 * e1 ** 3 / 96) * Math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * Math.sin(8 * mu)
  const s = Math.sin(p1), c = Math.cos(p1), t = Math.tan(p1)
  const N1 = A / Math.sqrt(1 - E2 * s * s), T1 = t * t, C1 = EP2 * c * c, R1 = A * (1 - E2) / (1 - E2 * s * s) ** 1.5
  const D = (x - 500000) / (N1 * K0)
  const phi = p1 - (N1 * t / R1) * (D * D / 2 - (5 + 3 * T1 + 10 * C1 - 4 * C1 * C1 - 9 * EP2) * D ** 4 / 24
                                    + (61 + 90 * T1 + 298 * C1 + 45 * T1 * T1 - 252 * EP2 - 3 * C1 * C1) * D ** 6 / 720)
  const lam = lam0 + (D - (1 + 2 * T1 + C1) * D ** 3 / 6 + (5 - 2 * C1 + 28 * T1 - 3 * C1 * C1 + 8 * EP2 + 24 * T1 * T1) * D ** 5 / 120) / c
  return [lam / D2R, phi / D2R]
}

// -- Catalogue -----------------------------------------------------------------------------------------------------
// Reflectance = DN * scale + offset. From processing baseline 04.00 ESA adds 1000 to the DNs (offset -0.1); Earth
// Search has already taken it out of the files where earthsearch:boa_offset_applied is true, though raster:bands
// still lists the -0.1 of the original product: there the offset is 0.
const band = (it, k) => {
  const a = it.assets?.[k]
  const rb = a?.['raster:bands']?.[0] ?? {}
  const offset = it.properties?.['earthsearch:boa_offset_applied'] ? 0 : (rb.offset ?? 0)
  return a ? { href: a.href, scale: rb.scale ?? 1e-4, offset } : null
}

// Scenes over the farm between two dates (ISO days), newest first; only scenes whose tile covers the whole farm
export async function searchScenes(geometry, bbox, from, to, signal) {
  const body = { collections: [COLLECTION], intersects: geometry, datetime: `${from}T00:00:00Z/${to}T23:59:59Z`, limit: 100,
                 query: { 'eo:cloud_cover': { lt: 95 } }, sortby: [{ field: 'properties.datetime', direction: 'desc' }] }
  const r = await fetch(STAC, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal })
  if (!r.ok) throw new Error(`the Sentinel-2 catalogue answered HTTP ${r.status}`)
  const j = await r.json()
  return (j.features ?? [])
    .filter(it => it.bbox && it.bbox[0] <= bbox[0] && it.bbox[1] <= bbox[1] && it.bbox[2] >= bbox[2] && it.bbox[3] >= bbox[3])
    .map(it => ({ id: it.id, date: it.properties.datetime.slice(0, 10), cloud: it.properties['eo:cloud_cover'],
                  epsg: it.properties['proj:epsg'] ?? Number(String(it.properties['proj:code'] ?? '').split(':')[1]),
                  red: band(it, 'red'), nir: band(it, 'nir'), blue: band(it, 'blue'), swir: band(it, 'swir16'), scl: band(it, 'scl') }))
    .filter(s => s.epsg && s.red && s.nir && s.scl)
    // a tile reprocessed by ESA appears twice on a date (..._0_L2A, ..._1_L2A): keep the newer processing
    .filter((s, i, all) => !all.some(o => o !== s && o.date === s.date && o.id.slice(0, -6) === s.id.slice(0, -6) && o.id > s.id))
}

// -- Reading windows -------------------------------------------------------------------------------------------------
const tiffs = new Map()
const openTiff = href => {
  if (!tiffs.has(href)) tiffs.set(href, fromUrl(href, { allowFullFile: false }).catch(e => { tiffs.delete(href); throw e }))
  return tiffs.get(href)
}

// The overview of a band whose pixel is closest to (not finer than) the target size, its grid, and the window over
// [minE, minN, maxE, maxN] (with a pixel of margin)
async function readWindow(href, box, target) {
  const tiff = await openTiff(href)
  const full = await tiff.getImage(0)
  const [x0, y0] = full.getOrigin()
  const n = await tiff.getImageCount()
  let img = full, res = full.getResolution()[0]
  for (let i = 1; i < n; i++) {
    const im = await tiff.getImage(i)
    const r = full.getResolution()[0] * full.getWidth() / im.getWidth()
    if (r <= target + 1e-6) { img = im; res = r }
  }
  const c0 = Math.max(0, Math.floor((box[0] - x0) / res) - 1), c1 = Math.min(img.getWidth(), Math.ceil((box[2] - x0) / res) + 1)
  const r0 = Math.max(0, Math.floor((y0 - box[3]) / res) - 1), r1 = Math.min(img.getHeight(), Math.ceil((y0 - box[1]) / res) + 1)
  if (c1 <= c0 || r1 <= r0) throw new Error('the farm is outside this scene')
  const [data] = await img.readRasters({ window: [c0, r0, c1, r1], samples: [0] })
  return { data, x0: x0 + c0 * res, y0: y0 - r0 * res, res, w: c1 - c0, h: r1 - r0 }
}
// value of a window at a point (nearest pixel), or 0 (no data) outside it
const at = (g, E, N) => {
  const c = Math.floor((E - g.x0) / g.res), r = Math.floor((g.y0 - N) / g.res)
  return c >= 0 && r >= 0 && c < g.w && r < g.h ? g.data[r * g.w + c] : 0
}

// The farm in the scene's UTM zone: rings, and its bounding box
function farmUTM(geometry, epsg) {
  const polys = polygons(geometry).map(p => p.map(r => r.map(([lon, lat]) => toUTM(lon, lat, epsg))))
  let b = [Infinity, Infinity, -Infinity, -Infinity]
  for (const p of polys) for (const [x, y] of p[0]) b = [Math.min(b[0], x), Math.min(b[1], y), Math.max(b[2], x), Math.max(b[3], y)]
  return { polys, box: b }
}
function inRing(x, y, ring) {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j]
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside
  }
  return inside
}
const inFarm = (x, y, polys) => polys.some(p => inRing(x, y, p[0]) && !p.slice(1).some(h => inRing(x, y, h)))

// The analysis grid (10 m, coarser for large farms) and which of its pixels lie in the farm
function farmGrid(f) {
  const span = Math.max(f.box[2] - f.box[0], f.box[3] - f.box[1])
  let target = 10
  while (span / target > MAX_PX) target *= 2
  return target
}

const quantile = (s, q) => { if (!s.length) return null; const i = (s.length - 1) * q, lo = Math.floor(i); return s[lo] + (s[Math.min(lo + 1, s.length - 1)] - s[lo]) * (i - lo) }

// The share of the farm that is clear in a scene (SCL only), with the grid used
export async function clearShare(scene, geometry, signal) {
  if (signal?.aborted) throw new DOMException('aborted', 'AbortError')
  const f = farmUTM(geometry, scene.epsg)
  const target = farmGrid(f)
  const scl = await readWindow(scene.scl.href, f.box, Math.max(20, target))
  let n = 0, ok = 0
  const step = Math.min(scl.res, target)
  for (let N = f.box[3] - step / 2; N > f.box[1]; N -= step) {
    for (let E = f.box[0] + step / 2; E < f.box[2]; E += step) {
      if (!inFarm(E, N, f.polys)) continue
      n++
      if (CLEAR_SCL.has(at(scl, E, N))) ok++
    }
  }
  return n ? ok / n : 0
}

// NDVI (and with full=true EVI, NDMI) over the farm's clear pixels in a scene, and an RGBA image of NDVI for the map
export async function readScene(scene, geometry, { full = true, signal } = {}) {
  if (signal?.aborted) throw new DOMException('aborted', 'AbortError')
  const f = farmUTM(geometry, scene.epsg)
  const target = farmGrid(f)
  const want = [['red', scene.red, target], ['nir', scene.nir, target], ['scl', scene.scl, Math.max(20, target)]]
  if (full && scene.blue) want.push(['blue', scene.blue, target])
  if (full && scene.swir) want.push(['swir', scene.swir, Math.max(20, target)])
  const got = Object.fromEntries(await Promise.all(want.map(async ([k, b, t]) => [k, await readWindow(b.href, f.box, t)])))
  const g = got.red
  const refl = (k, E, N) => { const v = at(got[k], E, N); return v === 0 ? NaN : v * scene[k].scale + scene[k].offset }
  const ndvi = new Float32Array(g.w * g.h).fill(NaN)
  const inside = new Uint8Array(g.w * g.h)
  const vals = { ndvi: [], evi: [], ndmi: [] }
  let nFarm = 0
  for (let r = 0; r < g.h; r++) {
    for (let c = 0; c < g.w; c++) {
      const E = g.x0 + (c + 0.5) * g.res, N = g.y0 - (r + 0.5) * g.res
      if (!inFarm(E, N, f.polys)) continue
      const i = r * g.w + c
      inside[i] = 1; nFarm++
      if (!CLEAR_SCL.has(at(got.scl, E, N))) continue
      const R = refl('red', E, N), NIR = refl('nir', E, N)
      if (!(R >= 0 && NIR >= 0) || R + NIR <= 0) continue
      const v = (NIR - R) / (NIR + R)
      ndvi[i] = v; vals.ndvi.push(v)
      if (got.blue) { const B = refl('blue', E, N), d = NIR + 6 * R - 7.5 * B + 1; if (B >= 0 && d > 0) { const e = 2.5 * (NIR - R) / d; if (e > -1 && e < 1.5) vals.evi.push(e) } }
      if (got.swir) { const S = refl('swir', E, N); if (S >= 0 && NIR + S > 0) vals.ndmi.push((NIR - S) / (NIR + S)) }
    }
  }
  const stat = a => { const s = [...a].sort((x, y) => x - y); return s.length ? { mean: s.reduce((t, v) => t + v, 0) / s.length, p10: quantile(s, 0.1), p50: quantile(s, 0.5), p90: quantile(s, 0.9), n: s.length } : null }
  const out = { date: scene.date, id: scene.id, res: g.res, clear: nFarm ? vals.ndvi.length / nFarm : 0, pixels: nFarm,
                ndvi: stat(vals.ndvi), evi: stat(vals.evi), ndmi: stat(vals.ndmi) }
  // weaker patches: clear pixels below 75% of the farm's median NDVI (only where the farm is green enough to tell)
  const med = out.ndvi?.p50
  out.low = med != null && med >= 0.3 ? vals.ndvi.filter(v => v < 0.75 * med).length / vals.ndvi.length : null
  out.image = ndviImage(g, ndvi, inside, scene.epsg)
  return out
}

// NDVI colours: bare soil brown -> sparse yellow -> green; cloudy farm pixels grey; outside the farm transparent
const RAMP = [[0, [166, 97, 26]], [0.2, [223, 194, 125]], [0.4, [230, 230, 110]], [0.6, [120, 198, 121]], [0.8, [35, 132, 67]], [1, [0, 90, 50]]]
export const NDVI_RAMP = RAMP
function colour(v) {
  if (v <= RAMP[0][0]) return RAMP[0][1]
  for (let k = 1; k < RAMP.length; k++) {
    if (v <= RAMP[k][0]) {
      const [a, ca] = RAMP[k - 1], [b, cb] = RAMP[k], t = (v - a) / (b - a)
      return ca.map((x, j) => Math.round(x + (cb[j] - x) * t))
    }
  }
  return RAMP[RAMP.length - 1][1]
}
function ndviImage(g, ndvi, inside, epsg) {
  if (typeof document === 'undefined') return null
  const cv = document.createElement('canvas')
  cv.width = g.w; cv.height = g.h
  const ctx = cv.getContext('2d')
  const im = ctx.createImageData(g.w, g.h)
  for (let i = 0; i < g.w * g.h; i++) {
    if (!inside[i]) continue
    const v = ndvi[i]
    const [r, gg, b] = Number.isFinite(v) ? colour(v) : [150, 150, 150]
    im.data.set([r, gg, b, Number.isFinite(v) ? 235 : 160], i * 4)
  }
  ctx.putImageData(im, 0, 0)
  const x1 = g.x0 + g.w * g.res, y1 = g.y0 - g.h * g.res
  return { url: cv.toDataURL('image/png'),
           coordinates: [fromUTM(g.x0, g.y0, epsg), fromUTM(x1, g.y0, epsg), fromUTM(x1, y1, epsg), fromUTM(g.x0, y1, epsg)] }
}

// -- The two checks the panel offers ---------------------------------------------------------------------------------
const isoDay = d => d.toISOString().slice(0, 10)
const addDays = (iso, n) => { const d = new Date(`${iso}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return isoDay(d) }

// The newest view of the last `days` days in which the farm is clear. progress({checked, total, cloudy}) as it goes.
export async function latestHealth(geometry, bbox, { days = 60, today = isoDay(new Date()), maxChecks = 10, progress, signal } = {}) {
  const scenes = await searchScenes(geometry, bbox, addDays(today, -days), today, signal)
  const tried = []
  for (const s of scenes.slice(0, maxChecks)) {
    progress?.({ checked: tried.length, total: Math.min(maxChecks, scenes.length) })
    const share = await clearShare(s, geometry, signal)
    tried.push({ date: s.date, clear: share })
    if (share >= CLEAR_MIN) {
      const r = await readScene(s, geometry, { full: true, signal })
      return { ...r, tried, scenes: scenes.length, from: addDays(today, -days), to: today }
    }
  }
  return { none: true, tried, scenes: scenes.length, from: addDays(today, -days), to: today }
}

// NDVI in the same weeks (date +- window days) of each of the past `years` years (the years are fetched together)
export async function pastYears(geometry, bbox, date, { years = 5, window = 12, maxChecks = 4, progress, signal } = {}) {
  const y0 = Number(date.slice(0, 4)), md = date.slice(4)
  let done = 0
  const one = async y => {
    const mid = `${y}${md}`
    const scenes = (await searchScenes(geometry, bbox, addDays(mid, -window), addDays(mid, window), signal))
      .sort((a, b) => Math.abs(new Date(a.date) - new Date(mid)) - Math.abs(new Date(b.date) - new Date(mid)) || a.cloud - b.cloud)
    let found = null
    for (const s of scenes.filter(s => s.cloud < 80).slice(0, maxChecks)) {
      if (await clearShare(s, geometry, signal) >= CLEAR_MIN) { found = await readScene(s, geometry, { full: false, signal }); break }
    }
    progress?.({ done: ++done, total: years })
    return found ? { year: y, date: found.date, ndvi: found.ndvi, clear: found.clear } : { year: y, none: true }
  }
  return Promise.all(Array.from({ length: years }, (_, k) => one(y0 - k - 1)))
}
