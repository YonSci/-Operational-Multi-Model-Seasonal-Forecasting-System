// Farm boundaries in the browser: read a GeoJSON or KML file, check it, and work out a farm's area, centre and the
// 0.25-degree forecast cells it overlaps (with the share of the farm in each). Nothing here leaves the browser.

export const CELL_DEG = 0.25
export const MAX_HA = 10000            // larger areas: use "Explain an area" (a farm panel per 0.25-degree cell makes no sense)
const MIN_M2 = 100
const MAX_VERTICES = 5000
const R = 6371008.8                    // mean Earth radius (m)
const rad = d => d * Math.PI / 180

// -- Shapes ------------------------------------------------------------------------------------------------------
// A farm's geometry is a GeoJSON Polygon or MultiPolygon in longitude/latitude (WGS84). polygons() lists its
// polygons as arrays of rings, the first ring the outline, the others holes.
export const polygons = g => (g?.type === 'Polygon' ? [g.coordinates] : g?.type === 'MultiPolygon' ? g.coordinates : [])

const closeRing = ring => {
  const r = ring.map(p => [Number(p[0]), Number(p[1])])
  if (r.length && (r[0][0] !== r[r.length - 1][0] || r[0][1] !== r[r.length - 1][1])) r.push([r[0][0], r[0][1]])
  return r
}

// Area of a ring on the sphere (m2): Chamberlain and Duquette (2007), as in geojson-area and turf
function ringArea(ring) {
  const n = ring.length
  if (n < 4) return 0
  let a = 0
  for (let i = 0; i < n - 1; i++) {
    const p1 = ring[i], p2 = ring[(i + 1) % (n - 1)], p3 = ring[(i + 2) % (n - 1)]
    a += (rad(p3[0]) - rad(p1[0])) * Math.sin(rad(p2[1]))
  }
  return Math.abs(a * R * R / 2)
}

export function areaM2(g) {
  return polygons(g).reduce((s, poly) => s + Math.max(0, ringArea(poly[0]) - poly.slice(1).reduce((h, r) => h + ringArea(r), 0)), 0)
}

export function bounds(g) {
  let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity
  for (const poly of polygons(g)) for (const [x, y] of poly[0]) { w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y) }
  return [w, s, e, n]
}

// Planar shoelace area (signed) and centroid in a local frame: x = lon * cos(lat0), y = lat. Fine at farm scale.
function planar(ring, k) {
  let a = 0, cx = 0, cy = 0
  for (let i = 0; i < ring.length - 1; i++) {
    const x0 = ring[i][0] * k, y0 = ring[i][1], x1 = ring[i + 1][0] * k, y1 = ring[i + 1][1]
    const c = x0 * y1 - x1 * y0
    a += c; cx += (x0 + x1) * c; cy += (y0 + y1) * c
  }
  return { a: a / 2, cx, cy }
}

// The area-weighted centre [lon, lat] (holes taken out)
export function centroid(g) {
  const b = bounds(g)
  const k = Math.cos(rad((b[1] + b[3]) / 2))
  let A = 0, X = 0, Y = 0
  for (const poly of polygons(g)) {
    poly.forEach((ring, i) => {
      const p = planar(ring, k)
      const sgn = (i === 0 ? 1 : -1) * Math.sign(p.a || 1)
      A += sgn * p.a; X += sgn * p.cx; Y += sgn * p.cy
    })
  }
  if (!A) return [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]
  return [X / (6 * A) / k, Y / (6 * A)]
}

// Sutherland-Hodgman: a ring clipped to the rectangle [w, s, e, n] (the rectangle is convex, so the area of the
// result is right even where the clipped ring touches itself along the edge)
function clipRing(ring, [w, s, e, n]) {
  const edges = [
    [p => p[0] >= w, (a, b) => [w, a[1] + (b[1] - a[1]) * (w - a[0]) / (b[0] - a[0])]],
    [p => p[0] <= e, (a, b) => [e, a[1] + (b[1] - a[1]) * (e - a[0]) / (b[0] - a[0])]],
    [p => p[1] >= s, (a, b) => [a[0] + (b[0] - a[0]) * (s - a[1]) / (b[1] - a[1]), s]],
    [p => p[1] <= n, (a, b) => [a[0] + (b[0] - a[0]) * (n - a[1]) / (b[1] - a[1]), n]],
  ]
  let pts = ring.slice(0, -1)
  for (const [inside, cut] of edges) {
    if (!pts.length) break
    const out = []
    for (let i = 0; i < pts.length; i++) {
      const cur = pts[i], prev = pts[(i + pts.length - 1) % pts.length]
      if (inside(cur)) {
        if (!inside(prev)) out.push(cut(prev, cur))
        out.push(cur)
      } else if (inside(prev)) out.push(cut(prev, cur))
    }
    pts = out
  }
  return pts.length >= 3 ? [...pts, pts[0]] : []
}

const centre = v => Math.floor(v / CELL_DEG) * CELL_DEG + CELL_DEG / 2
export const cellId = (lat, lon) => `g${+lat.toFixed(3)}_${+lon.toFixed(3)}`
export const cellKey = (lat, lon) => `${lat.toFixed(3)},${lon.toFixed(3)}`

// The 0.25-degree cells the farm overlaps: [{lat, lon (centre), id, share (0-1 of the farm), ha, km2 (cell area)}],
// largest share first
export function farmCells(g) {
  const b = bounds(g)
  const k = Math.cos(rad((b[1] + b[3]) / 2))
  const planarArea = rings => rings.reduce((s, r, i) => s + (i === 0 ? 1 : -1) * Math.abs(planar(r, k).a), 0)
  const total = polygons(g).reduce((s, poly) => s + Math.max(0, planarArea(poly)), 0)
  const ha = areaM2(g) / 1e4
  const out = []
  if (!total) return out
  for (let lat = centre(b[1]); lat < b[3] + CELL_DEG / 2; lat += CELL_DEG) {
    for (let lon = centre(b[0]); lon < b[2] + CELL_DEG / 2; lon += CELL_DEG) {
      const box = [lon - CELL_DEG / 2, lat - CELL_DEG / 2, lon + CELL_DEG / 2, lat + CELL_DEG / 2]
      let a = 0
      for (const poly of polygons(g)) {
        const rings = poly.map(r => clipRing(r, box))
        if (rings[0].length) a += Math.max(0, planarArea(rings.filter((r, i) => i === 0 || r.length)))
      }
      const share = a / total
      if (share > 1e-6) {
        const la = +lat.toFixed(3), lo = +lon.toFixed(3)
        const km2 = (R * rad(CELL_DEG)) * (R * rad(CELL_DEG) * Math.cos(rad(la))) / 1e6
        out.push({ lat: la, lon: lo, id: cellId(la, lo), share, ha: share * ha, km2 })
      }
    }
  }
  const s = out.reduce((t, c) => t + c.share, 0) || 1          // rounding at shared edges
  return out.map(c => ({ ...c, share: c.share / s, ha: c.share / s * ha })).sort((x, y) => y.share - x.share)
}

// -- Checks --------------------------------------------------------------------------------------------------------
// The geometry, cleaned (closed rings, 2-D positions), or an Error saying what is wrong with it
export function checkGeometry(g) {
  if (!g || !['Polygon', 'MultiPolygon'].includes(g.type)) return new Error('The boundary must be a polygon.')
  const polys = polygons(g).map(poly => poly.map(closeRing))
  let nv = 0
  for (const poly of polys) {
    if (!poly.length || poly[0].length < 4) return new Error('A farm outline needs at least three corners.')
    for (const ring of poly) {
      nv += ring.length
      for (const [x, y] of ring) {
        if (!Number.isFinite(x) || !Number.isFinite(y)) return new Error('The boundary has a position that is not a number.')
        if (Math.abs(x) > 180 || Math.abs(y) > 90)
          return new Error('The coordinates are not longitude and latitude. Save the boundary in WGS84 (EPSG:4326) and try again.')
      }
    }
  }
  if (nv > MAX_VERTICES) return new Error(`The boundary has ${nv} corners; at most ${MAX_VERTICES} are supported. Simplify it and try again.`)
  const geom = polys.length === 1 ? { type: 'Polygon', coordinates: polys[0] } : { type: 'MultiPolygon', coordinates: polys }
  const m2 = areaM2(geom)
  if (m2 < MIN_M2) return new Error('The boundary encloses almost no area.')
  if (m2 / 1e4 > MAX_HA)
    return new Error(`The boundary covers ${Math.round(m2 / 1e4).toLocaleString()} ha. Farms up to ${MAX_HA.toLocaleString()} ha are supported; ` +
                     'for a larger area use "Explain an area".')
  return geom
}

// -- Files ---------------------------------------------------------------------------------------------------------
// GeoJSON (Feature, FeatureCollection or a bare geometry) -> [{name, geometry}], one per (multi)polygon feature
function fromGeoJSON(j) {
  const feats = j?.type === 'FeatureCollection' ? j.features ?? [] : j?.type === 'Feature' ? [j] : j?.type ? [{ type: 'Feature', geometry: j, properties: {} }] : []
  const out = []
  for (const f of feats) {
    const g = f?.geometry
    if (!g) continue
    const name = f.properties?.name ?? f.properties?.Name ?? f.properties?.NAME ?? ''
    if (g.type === 'Polygon' || g.type === 'MultiPolygon') out.push({ name: String(name), geometry: g })
    else if (g.type === 'GeometryCollection') {
      const polys = (g.geometries ?? []).flatMap(x => polygons(x))
      if (polys.length) out.push({ name: String(name), geometry: { type: 'MultiPolygon', coordinates: polys } })
    }
  }
  return out
}

const kmlCoords = el => (el?.textContent ?? '').trim().split(/\s+/).filter(Boolean).map(t => t.split(',').slice(0, 2).map(Number))
const byTag = (el, tag) => Array.from(el.getElementsByTagNameNS('*', tag))

// KML -> [{name, geometry}], one per placemark with polygons
function fromKML(text) {
  const doc = new DOMParser().parseFromString(text, 'application/xml')
  if (doc.getElementsByTagName('parsererror').length) throw new Error('The KML file could not be read.')
  const out = []
  for (const pm of byTag(doc, 'Placemark')) {
    const polys = byTag(pm, 'Polygon').map(p => {
      const outer = byTag(p, 'outerBoundaryIs')[0]
      const ring = outer ? kmlCoords(byTag(outer, 'coordinates')[0]) : []
      const holes = byTag(p, 'innerBoundaryIs').map(ib => kmlCoords(byTag(ib, 'coordinates')[0]))
      return [ring, ...holes]
    }).filter(p => p[0].length)
    if (!polys.length) continue
    const name = Array.from(pm.children).find(c => c.localName === 'name')?.textContent?.trim() ?? ''
    out.push({ name, geometry: polys.length === 1 ? { type: 'Polygon', coordinates: polys[0] } : { type: 'MultiPolygon', coordinates: polys } })
  }
  return out
}

// A dropped or chosen file -> {farms: [{name, geometry}], errors: [string]}
export async function readFarmFile(file) {
  const name = file.name.toLowerCase()
  if (name.endsWith('.kmz')) throw new Error('KMZ files are zipped; open the file in Google Earth and save it as KML, then upload the KML.')
  if (name.endsWith('.shp') || name.endsWith('.zip')) throw new Error('Shapefiles are not supported; save the boundary as GeoJSON or KML.')
  if (file.size > 5e6) throw new Error('The file is larger than 5 MB; a farm boundary should be much smaller.')
  const text = await file.text()
  let found
  if (name.endsWith('.kml') || /^\s*<\?xml|^\s*<kml/i.test(text)) found = fromKML(text)
  else {
    let j
    try { j = JSON.parse(text) } catch { throw new Error('The file is neither GeoJSON nor KML.') }
    found = fromGeoJSON(j)
  }
  if (!found.length) throw new Error('No polygon was found in the file. A farm boundary must be a polygon, not points or lines.')
  const farms = [], errors = []
  found.forEach((f, i) => {
    const g = checkGeometry(f.geometry)
    const label = f.name || `${file.name.replace(/\.[^.]+$/, '')}${found.length > 1 ? ` ${i + 1}` : ''}`
    if (g instanceof Error) errors.push(`${label}: ${g.message}`)
    else farms.push({ name: label, geometry: g })
  })
  return { farms, errors }
}

// -- Storage (this browser only) -------------------------------------------------------------------------------------
const STORE_KEY = 'cai-farms'
export const loadFarms = () => {
  try {
    const l = JSON.parse(localStorage.getItem(STORE_KEY) ?? '[]')
    return Array.isArray(l) ? l.filter(f => f?.id && f.geometry && !(checkGeometry(f.geometry) instanceof Error)) : []
  } catch { return [] }
}
export const saveFarms = list => { try { localStorage.setItem(STORE_KEY, JSON.stringify(list)) } catch { /* storage blocked: kept for this visit */ } }
export const newFarmId = () => `f${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`

export function downloadFarm(f) {
  const fc = { type: 'FeatureCollection', features: [{ type: 'Feature', properties: { name: f.name }, geometry: f.geometry }] }
  const url = URL.createObjectURL(new Blob([JSON.stringify(fc)], { type: 'application/geo+json' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `${(f.name || 'farm').replace(/[^\w.-]+/g, '_')}.geojson`
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
