import { useEffect, useRef, useState, useMemo } from 'react'
import * as mapboxgl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import useDashboardStore from '../store/useDashboardStore'

// MapLibre GL JS -- no token required

// Clean basemap styles (100% free, no API key or watermark required)
const STYLE_DARK  = {
  "version": 8,
  "sources": {
    "esri-dark": {
      "type": "raster",
      "tiles": [
        "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
      ],
      "tileSize": 256,
      "attribution": "(c) Esri, HERE, Garmin, (c) OpenStreetMap contributors"
    }
  },
  "layers": [{ "id": "esri-dark-layer", "type": "raster", "source": "esri-dark" }]
}
const STYLE_LIGHT = {
  "version": 8,
  "sources": {
    "esri-light": {
      "type": "raster",
      "tiles": [
        "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
      ],
      "tileSize": 256,
      "attribution": "(c) Esri, HERE, Garmin, (c) OpenStreetMap contributors"
    }
  },
  "layers": [{ "id": "esri-light-layer", "type": "raster", "source": "esri-light" }]
}
const STYLE_OSM = {
  "version": 8,
  "sources": {
    "osm": {
      "type": "raster",
      "tiles": [
        "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png"
      ],
      "tileSize": 256,
      "attribution": "(c) OpenStreetMap contributors"
    }
  },
  "layers": [{ "id": "osm-layer", "type": "raster", "source": "osm" }]
}
const STYLE_SATELLITE = {
  "version": 8,
  "sources": {
    "esri-satellite": {
      "type": "raster",
      "tiles": [
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
      ],
      "tileSize": 256,
      "attribution": "(c) Esri, Maxar, Earthstar Geographics"
    }
  },
  "layers": [{ "id": "esri-satellite-layer", "type": "raster", "source": "esri-satellite" }]
}
const STYLE_TOPO = {
  "version": 8,
  "sources": {
    "esri-topo": {
      "type": "raster",
      "tiles": [
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}"
      ],
      "tileSize": 256,
      "attribution": "(c) Esri, USGS, NOAA"
    }
  },
  "layers": [{ "id": "esri-topo-layer", "type": "raster", "source": "esri-topo" }]
}
const BASEMAPS = {
  light:     { style: STYLE_LIGHT,     label: 'Light' },
  dark:      { style: STYLE_DARK,      label: 'Dark' },
  osm:       { style: STYLE_OSM,       label: 'OpenStreetMap' },
  satellite: { style: STYLE_SATELLITE, label: 'Satellite' },
  topo:      { style: STYLE_TOPO,      label: 'Topographic' },
}

// -- Monitored Farm Sites ---------------------------------------------------
export const MONITORED_SITES = [
  { site_name: "Kapiti Research Station Farm",   lat: -1.63209, lon: 37.1479, county: "Machakos",   desc: "ILRI Research Farm" },
  { site_name: "KALRO Kiboko, Makueni Farm",     lat: -2.21046, lon: 37.7190, county: "Makueni",    desc: "KALRO Dryland Station" },
  { site_name: "El Karama Sahiwals Farm",         lat: -2.38710, lon: 37.4851, county: "Kajiado",    desc: "Livestock Breeding Farm" },
  { site_name: "LiveMo LTD, Memerush, Kajiado",  lat: -2.38726, lon: 37.4850, county: "Kajiado",    desc: "Commercial Pastoral Ranch" },
  { site_name: "Genco LTD Maralal Samburu Farm", lat:  0.92730, lon: 36.5690, county: "Samburu",    desc: "Northern Pastoral Hub" },
  { site_name: "Genco LTD Tana River Farm",      lat: -2.21314, lon: 40.0517, county: "Tana River", desc: "Coast Rangeland Site" },
]

const SITES_GEOJSON = {
  type: 'FeatureCollection',
  features: MONITORED_SITES.map(s => ({
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
    properties: {
      site_name: s.site_name,
      short_name: s.site_name.replace(' Farm', '').replace(' Station', '').split(',')[0].slice(0, 15),
      lat: s.lat,
      lon: s.lon,
      county: s.county,
      desc: s.desc
    }
  }))
}

// Strip obsolete or non-standard CRS from GeoJSON to prevent MapLibre parsing issues
function cleanGeoJSON(data) {
  if (!data) return null
  try {
    const copy = JSON.parse(JSON.stringify(data))
    if (copy.crs) delete copy.crs
    return copy
  } catch(_) {
    return data
  }
}



// -- Colour scales ----------------------------------------------------------
const CS = {
  onset_med:    { s:[50,65,75,85,95,105,120],    c:['#1a9850','#66bd63','#a6d96a','#ffffbf','#fdae61','#f46d43','#d73027'], label:'Ensemble onset P50 (DOY)' },
  onset_anom:   { s:[-20,-10,-5,0,5,10,20],      c:['#1a9850','#66bd63','#a6d96a','#ffffbf','#fdae61','#f46d43','#d73027'], label:'Onset anomaly (days)' },
  onset_spread: { s:[0,5,10,15,20,25],            c:['#f7fbff','#c6dbef','#9ecae1','#4292c6','#2171b5','#084594'],           label:'Onset spread (days)' },
  cess_med:     { s:[100,115,125,135,145,155,170], c:['#1a9850','#66bd63','#a6d96a','#ffffbf','#fdae61','#f46d43','#d73027'], label:'Ensemble cessation P50 (DOY)' },
  cess_anom:    { s:[-20,-10,-5,0,5,10,20],      c:['#1a9850','#66bd63','#a6d96a','#ffffbf','#fdae61','#f46d43','#d73027'], label:'Cessation anomaly (days)' },
  cess_spread:  { s:[0,5,10,15,20,25],            c:['#f7fbff','#c6dbef','#9ecae1','#4292c6','#2171b5','#084594'],           label:'Cessation spread (days)' },
  lgp_med:      { s:[20,30,40,50,60,70,90],       c:['#d73027','#f46d43','#fdae61','#ffffbf','#a6d96a','#66bd63','#1a9850'], label:'Season length P50 (days)' },
  lgp_anom:     { s:[-20,-10,-5,0,5,10,20],      c:['#d73027','#f46d43','#fdae61','#ffffbf','#a6d96a','#66bd63','#1a9850'], label:'Season length anomaly (days)' },
  lgp_spread:   { s:[0,5,10,15,20,25],            c:['#f7fbff','#c6dbef','#9ecae1','#4292c6','#2171b5','#084594'],           label:'Season length spread (days)' },
  prob_bn:      { s:[0.2,0.27,0.33,0.4,0.5,0.6], c:['#ffffcc','#c7e9b4','#7fcdbb','#41b6c4','#2c7fb8','#253494'],           label:'P(Below Normal)' },
  prob_nn:      { s:[0.2,0.27,0.33,0.4,0.5,0.6], c:['#f7f7f7','#d9d9d9','#bdbdbd','#969696','#636363','#252525'],            label:'P(Near Normal)' },
  prob_an:      { s:[0.2,0.27,0.33,0.4,0.5,0.6], c:['#ffffcc','#fee391','#fec44f','#fe9929','#d95f0e','#993404'],            label:'P(Above Normal)' },
  failure:      { s:[0,0.05,0.1,0.2,0.3,0.5],    c:['#f7f7f7','#cccccc','#969696','#636363','#252525','#000000'],            label:'P(Season failure)' },
  // Multi-model median (same scale as onset_med etc -- already defined above)
  // multimodel id aliases so legend works for MULTI_LAYERS
  // (onset_med, cess_med, lgp_med already exist)
  // Skill-weighted ensemble layers
  onset_hr_w:    { s:[50,65,75,85,95,105,120],    c:['#1a9850','#66bd63','#a6d96a','#ffffbf','#fdae61','#f46d43','#d73027'], label:'Onset P50 HR-Weighted (DOY)' },
  cess_hr_w:     { s:[100,115,125,135,145,155,170],c:['#1a9850','#66bd63','#a6d96a','#ffffbf','#fdae61','#f46d43','#d73027'], label:'Cessation P50 HR-Weighted (DOY)' },
  lgp_hr_w:      { s:[20,30,40,50,60,70,90],       c:['#d73027','#f46d43','#fdae61','#ffffbf','#a6d96a','#66bd63','#1a9850'], label:'Season Length HR-Weighted (days)' },
  onset_rpss_w:  { s:[50,65,75,85,95,105,120],    c:['#1a9850','#66bd63','#a6d96a','#ffffbf','#fdae61','#f46d43','#d73027'], label:'Onset P50 RPSS-Weighted (DOY)' },
  cess_rpss_w:   { s:[100,115,125,135,145,155,170],c:['#1a9850','#66bd63','#a6d96a','#ffffbf','#fdae61','#f46d43','#d73027'], label:'Cessation P50 RPSS-Weighted (DOY)' },
  lgp_rpss_w:    { s:[20,30,40,50,60,70,90],       c:['#d73027','#f46d43','#fdae61','#ffffbf','#a6d96a','#66bd63','#1a9850'], label:'Season Length RPSS-Weighted (days)' },
  // Probabilistic tab keyed by PROB_LAYERS id
  p_onset_bn:   { s:[0.2,0.27,0.33,0.4,0.5,0.6], c:['#ffffcc','#c7e9b4','#7fcdbb','#41b6c4','#2c7fb8','#253494'],           label:'P(BN) Onset' },
  p_onset_nn:   { s:[0.2,0.27,0.33,0.4,0.5,0.6], c:['#f7f7f7','#d9d9d9','#bdbdbd','#969696','#636363','#252525'],            label:'P(NN) Onset' },
  p_onset_an:   { s:[0.2,0.27,0.33,0.4,0.5,0.6], c:['#ffffcc','#fee391','#fec44f','#fe9929','#d95f0e','#993404'],            label:'P(AN) Onset' },
  p_cess_bn:    { s:[0.2,0.27,0.33,0.4,0.5,0.6], c:['#ffffcc','#c7e9b4','#7fcdbb','#41b6c4','#2c7fb8','#253494'],           label:'P(BN) Cessation' },
  p_cess_nn:    { s:[0.2,0.27,0.33,0.4,0.5,0.6], c:['#f7f7f7','#d9d9d9','#bdbdbd','#969696','#636363','#252525'],            label:'P(NN) Cessation' },
  p_cess_an:    { s:[0.2,0.27,0.33,0.4,0.5,0.6], c:['#ffffcc','#fee391','#fec44f','#fe9929','#d95f0e','#993404'],            label:'P(AN) Cessation' },
  p_lgp_bn:     { s:[0.2,0.27,0.33,0.4,0.5,0.6], c:['#ffffcc','#c7e9b4','#7fcdbb','#41b6c4','#2c7fb8','#253494'],           label:'P(BN) Season Length' },
  p_lgp_nn:     { s:[0.2,0.27,0.33,0.4,0.5,0.6], c:['#f7f7f7','#d9d9d9','#bdbdbd','#969696','#636363','#252525'],            label:'P(NN) Season Length' },
  p_lgp_an:     { s:[0.2,0.27,0.33,0.4,0.5,0.6], c:['#ffffcc','#fee391','#fec44f','#fe9929','#d95f0e','#993404'],            label:'P(AN) Season Length' },
  p_failure:    { s:[0,0.05,0.1,0.2,0.3,0.5],    c:['#f7f7f7','#cccccc','#969696','#636363','#252525','#000000'],            label:'P(Season Failure)' },
  chirps_p50_onset: { s:[50,65,75,85,95,105,120],     c:['#1a9850','#66bd63','#a6d96a','#ffffbf','#fdae61','#f46d43','#d73027'], label:'CHIRPS Onset P50 (DOY)' },
  chirps_p50_cess:  { s:[100,115,125,135,145,155,170], c:['#1a9850','#66bd63','#a6d96a','#ffffbf','#fdae61','#f46d43','#d73027'], label:'CHIRPS Cessation P50 (DOY)' },
  chirps_p50_lgp:   { s:[20,30,40,50,60,70,90],        c:['#d73027','#f46d43','#fdae61','#ffffbf','#a6d96a','#66bd63','#1a9850'], label:'CHIRPS Season Length P50 (days)' },
  chirps_spread:    { s:[0,5,10,15,20,25,30],           c:['#f7fbff','#c6dbef','#9ecae1','#6baed6','#3182bd','#08519c','#03256c'], label:'Ensemble Spread IQR (days)' },
  bias:             { s:[-20,-10,-5,0,5,10,20],         c:['#1a9850','#66bd63','#a6d96a','#ffffbf','#fdae61','#f46d43','#d73027'], label:'Model Bias vs CHIRPS (days)' },
  detection_rate:   { s:[0,0.6,0.7,0.8,0.85,0.9,1.0],  c:['#d73027','#f46d43','#fdae61','#ffffbf','#a6d96a','#66bd63','#1a9850'], label:'Detection Rate (fraction)' },
  // Validation skill map colour scales
  v_rpss_onset:  { s:[-0.2,-0.1,0,0.1,0.2,0.3,0.4], c:['#d73027','#f46d43','#fdae61','#ffffbf','#a6d96a','#66bd63','#1a9850'], label:'RPSS Onset (val period)' },
  v_rpss_cess:   { s:[-0.2,-0.1,0,0.1,0.2,0.3,0.4], c:['#d73027','#f46d43','#fdae61','#ffffbf','#a6d96a','#66bd63','#1a9850'], label:'RPSS Cessation (val period)' },
  v_rpss_lgp:    { s:[-0.2,-0.1,0,0.1,0.2,0.3,0.4], c:['#d73027','#f46d43','#fdae61','#ffffbf','#a6d96a','#66bd63','#1a9850'], label:'RPSS Season Length (val period)' },
  v_hr_onset:    { s:[0.2,0.27,0.33,0.4,0.5,0.6,0.7], c:['#d73027','#f46d43','#fdae61','#ffffbf','#a6d96a','#66bd63','#1a9850'], label:'Hit Rate Onset (val period)' },
  v_hr_cess:     { s:[0.2,0.27,0.33,0.4,0.5,0.6,0.7], c:['#d73027','#f46d43','#fdae61','#ffffbf','#a6d96a','#66bd63','#1a9850'], label:'Hit Rate Cessation (val period)' },
  v_hr_lgp:      { s:[0.2,0.27,0.33,0.4,0.5,0.6,0.7], c:['#d73027','#f46d43','#fdae61','#ffffbf','#a6d96a','#66bd63','#1a9850'], label:'Hit Rate Season Length (val period)' },
  v_alpha_onset: { s:[0.3,0.5,0.7,0.9,1.1,1.3,1.5],   c:['#d73027','#f46d43','#fdae61','#ffffbf','#a6d96a','#66bd63','#1a9850'], label:'Alpha Onset (val period)' },
  v_alpha_cess:  { s:[0.3,0.5,0.7,0.9,1.1,1.3,1.5],   c:['#d73027','#f46d43','#fdae61','#ffffbf','#a6d96a','#66bd63','#1a9850'], label:'Alpha Cessation (val period)' },
  v_alpha_lgp:   { s:[0.3,0.5,0.7,0.9,1.1,1.3,1.5],   c:['#d73027','#f46d43','#fdae61','#ffffbf','#a6d96a','#66bd63','#1a9850'], label:'Alpha Season Length (val period)' },
  // HIST layer colour scales (keyed by HIST_LAYER id)
  h_onset_p50:  { s:[50,65,75,85,95,105,120],     c:['#1a9850','#66bd63','#a6d96a','#ffffbf','#fdae61','#f46d43','#d73027'], label:'Onset P50 (DOY)' },
  h_cess_p50:   { s:[100,115,125,135,145,155,170], c:['#1a9850','#66bd63','#a6d96a','#ffffbf','#fdae61','#f46d43','#d73027'], label:'Cessation P50 (DOY)' },
  h_lgp_p50:    { s:[20,30,40,50,60,70,90],        c:['#d73027','#f46d43','#fdae61','#ffffbf','#a6d96a','#66bd63','#1a9850'], label:'Season Length P50 (days)' },
  h_onset_spr:  { s:[0,5,10,15,20,25],             c:['#f7fbff','#c6dbef','#9ecae1','#4292c6','#2171b5','#084594'],          label:'Onset Spread (days)' },
  h_cess_spr:   { s:[0,5,10,15,20,25],             c:['#f7fbff','#c6dbef','#9ecae1','#4292c6','#2171b5','#084594'],          label:'Cessation Spread (days)' },
  h_lgp_spr:    { s:[0,5,10,15,20,25],             c:['#f7fbff','#c6dbef','#9ecae1','#4292c6','#2171b5','#084594'],          label:'Season Length Spread (days)' },
  h_onset_bias: { s:[-20,-10,-5,0,5,10,20],        c:['#1a9850','#66bd63','#a6d96a','#ffffbf','#fdae61','#f46d43','#d73027'], label:'Onset Bias: model vs CHIRPS (days)' },
  h_cess_bias:  { s:[-20,-10,-5,0,5,10,20],        c:['#1a9850','#66bd63','#a6d96a','#ffffbf','#fdae61','#f46d43','#d73027'], label:'Cessation Bias: model vs CHIRPS (days)' },
  h_lgp_bias:   { s:[-20,-10,-5,0,5,10,20],        c:['#d73027','#f46d43','#fdae61','#ffffbf','#a6d96a','#66bd63','#1a9850'], label:'Season Length Bias (days)' },
  h_onset_det:  { s:[0.5,0.6,0.7,0.8,0.9,0.95,1.0], c:['#d73027','#f46d43','#fdae61','#ffffbf','#a6d96a','#66bd63','#1a9850'], label:'Detection Rate: Onset (fraction)' },
  h_cess_det:   { s:[0.5,0.6,0.7,0.8,0.9,0.95,1.0], c:['#d73027','#f46d43','#fdae61','#ffffbf','#a6d96a','#66bd63','#1a9850'], label:'Detection Rate: Cessation (fraction)' },
  h_lgp_det:    { s:[0.5,0.6,0.7,0.8,0.9,0.95,1.0], c:['#d73027','#f46d43','#fdae61','#ffffbf','#a6d96a','#66bd63','#1a9850'], label:'Detection Rate: Season Length (fraction)' },
}

// Default layers (forecast / probabilistic / multi-model tabs)
// Grouped for 4-column dropdown (Onset / Cessation / Season Length per row)
const LAYERS = [
  // Equal weighted (Median)

  // Ensemble Median
  { id:'onset_med',    label:'Onset Median',       group:'Median',   variable:'onset',     layer:'median'  },
  { id:'cess_med',     label:'Cessation Median',   group:'Median',   variable:'cessation', layer:'median'  },
  { id:'lgp_med',      label:'Season Length Median', group:'Median', variable:'lgp',       layer:'median'  },
  // Anomaly
  { id:'onset_anom',   label:'Onset Anomaly',      group:'Anomaly',  variable:'onset',     layer:'anomaly' },
  { id:'cess_anom',    label:'Cessation Anomaly',  group:'Anomaly',  variable:'cessation', layer:'anomaly' },
  { id:'lgp_anom',     label:'Season Length Anomaly', group:'Anomaly', variable:'lgp',     layer:'anomaly' },
]

// Probabilistic-only layers -- shown only when activeTab === 'probabilistic'
const PROB_LAYERS = [
  { id:'p_onset_bn',  label:'P(BN) Onset',          variable:'onset',     layer:'prob_bn', group:'BN' },
  { id:'p_onset_nn',  label:'P(NN) Onset',           variable:'onset',     layer:'prob_nn', group:'NN' },
  { id:'p_onset_an',  label:'P(AN) Onset',           variable:'onset',     layer:'prob_an', group:'AN' },
  { id:'p_cess_bn',   label:'P(BN) Cessation',       variable:'cessation', layer:'prob_bn', group:'BN' },
  { id:'p_cess_nn',   label:'P(NN) Cessation',       variable:'cessation', layer:'prob_nn', group:'NN' },
  { id:'p_cess_an',   label:'P(AN) Cessation',       variable:'cessation', layer:'prob_an', group:'AN' },
  { id:'p_lgp_bn',    label:'P(BN) Season Length',   variable:'lgp',       layer:'prob_bn', group:'BN' },
  { id:'p_lgp_nn',    label:'P(NN) Season Length',   variable:'lgp',       layer:'prob_nn', group:'NN' },
  { id:'p_lgp_an',    label:'P(AN) Season Length',   variable:'lgp',       layer:'prob_an', group:'AN' },
  { id:'p_failure',   label:'P(Season Failure)',      variable:'onset',     layer:'failure', group:'Failure' },
]

// Multi-model tab layers -- median, anomaly + skill-weighted variants
const MULTI_LAYERS = [
  { id:'onset_med',    label:'Onset Median (Equal)',       variable:'onset',     layer:'median',        group:'Equal'   },
  { id:'cess_med',     label:'Cessation Median (Equal)',   variable:'cessation', layer:'median',        group:'Equal'   },
  { id:'lgp_med',      label:'Season Len Median (Equal)',  variable:'lgp',       layer:'median',        group:'Equal'   },
  { id:'onset_hr_w',   label:'Onset HR-Weighted',          variable:'onset',     layer:'hr_weighted',   group:'HR-Wt'   },
  { id:'cess_hr_w',    label:'Cessation HR-Weighted',      variable:'cessation', layer:'hr_weighted',   group:'HR-Wt'   },
  { id:'lgp_hr_w',     label:'Season Len HR-Weighted',     variable:'lgp',       layer:'hr_weighted',   group:'HR-Wt'   },
  { id:'onset_rpss_w', label:'Onset RPSS-Weighted',        variable:'onset',     layer:'rpss_weighted', group:'RPSS-Wt' },
  { id:'cess_rpss_w',  label:'Cessation RPSS-Weighted',    variable:'cessation', layer:'rpss_weighted', group:'RPSS-Wt' },
  { id:'lgp_rpss_w',   label:'Season Len RPSS-Weighted',   variable:'lgp',       layer:'rpss_weighted', group:'RPSS-Wt' },
]

// Validation-only layers -- shown only when activeTab === 'validation'
const VAL_LAYERS = [
  { id:'v_rpss_onset',  label:'RPSS Onset',         variable:'onset',     layer:'rpss_val',    group:'RPSS'   },
  { id:'v_rpss_cess',   label:'RPSS Cessation',      variable:'cessation', layer:'rpss_val',    group:'RPSS'   },
  { id:'v_rpss_lgp',    label:'RPSS Season Length',  variable:'lgp',       layer:'rpss_val',    group:'RPSS'   },
  { id:'v_hr_onset',    label:'Hit Rate Onset',      variable:'onset',     layer:'hitrate_val', group:'HR'     },
  { id:'v_hr_cess',     label:'Hit Rate Cessation',  variable:'cessation', layer:'hitrate_val', group:'HR'     },
  { id:'v_hr_lgp',      label:'Hit Rate Season Len', variable:'lgp',       layer:'hitrate_val', group:'HR'     },
  { id:'v_alpha_onset', label:'Alpha Onset',         variable:'onset',     layer:'alpha',       group:'Alpha'  },
  { id:'v_alpha_cess',  label:'Alpha Cessation',     variable:'cessation', layer:'alpha',       group:'Alpha'  },
  { id:'v_alpha_lgp',   label:'Alpha Season Len',    variable:'lgp',       layer:'alpha',       group:'Alpha'  },
]

// Historical-only layers (shown only when activeTab === 'historical')
const HIST_LAYERS = [
  { id:'h_onset_p50',  label:'Median Onset',       variable:'onset',     layer:'median',         group:'Median' },
  { id:'h_cess_p50',   label:'Median Cessation',   variable:'cessation', layer:'median',         group:'Median' },
  { id:'h_lgp_p50',    label:'Median Season Len',  variable:'lgp',       layer:'median',         group:'Median' },
  { id:'h_onset_spr',  label:'Spread Onset',       variable:'onset',     layer:'spread',         group:'Spread' },
  { id:'h_cess_spr',   label:'Spread Cessation',   variable:'cessation', layer:'spread',         group:'Spread' },
  { id:'h_lgp_spr',    label:'Spread Season Len',  variable:'lgp',       layer:'spread',         group:'Spread' },
  { id:'h_onset_bias', label:'Bias Onset',         variable:'onset',     layer:'bias',           group:'Bias'   },
  { id:'h_cess_bias',  label:'Bias Cessation',     variable:'cessation', layer:'bias',           group:'Bias'   },
  { id:'h_lgp_bias',   label:'Bias Season Len',    variable:'lgp',       layer:'bias',           group:'Bias'   },
  { id:'h_onset_det',  label:'Det. Rate Onset',    variable:'onset',     layer:'detection_rate', group:'Det.'   },
  { id:'h_cess_det',   label:'Det. Rate Cessation',variable:'cessation', layer:'detection_rate', group:'Det.'   },
  { id:'h_lgp_det',    label:'Det. Rate Season Len',variable:'lgp',      layer:'detection_rate', group:'Det.'   },
]

// -- Country map views -------------------------------------------------------
// bounds: [[west,south],[east,north]]. `available` gates real forecast data --
// Ethiopia's processed onset/cessation/LGP outputs are not produced yet, only
// Kenya's, so its map is a recenter-only preview until that pipeline lands.
const COUNTRY_VIEWS = {
  kenya:    { label:'Kenya',    bounds:[[33.5,-5],[42.5,5]],     available:true  },
  ethiopia: { label:'Ethiopia', bounds:[[32.9,3.4],[48.0,14.9]], available:false },
}

function doyToDate(doy, year=2026) {
  if (!doy||isNaN(doy)) return ''
  try { return new Date(year,0,Math.round(doy)).toLocaleDateString('en-GB',{day:'2-digit',month:'short'}) }
  catch { return '' }
}

// -- Nearest-neighbour raster (one pixel per grid cell) ---------------------
function h2r(hex){ return [parseInt(hex.slice(1,3),16),parseInt(hex.slice(3,5),16),parseInt(hex.slice(5,7),16)] }
function v2rgb(v,scale){
  const{s,c}=scale,rgbs=c.map(h2r)
  if(v==null||isNaN(v)) return null
  if(v<=s[0]) return rgbs[0]; if(v>=s[s.length-1]) return rgbs[s.length-1]
  for(let i=0;i<s.length-1;i++){
    if(v>=s[i]&&v<=s[i+1]){const t=(v-s[i])/(s[i+1]-s[i]);return rgbs[i].map((x,j)=>Math.round(x+t*(rgbs[i+1][j]-x)))}
  }
  return rgbs[rgbs.length-1]
}

function buildRaster(gridData, scale) {
  if (!gridData?.features?.length) return null
  const latSet=new Set(),lonSet=new Set(),raw={}
  for(const f of gridData.features){
    const{lat,lon,map_val}=f.properties; if(map_val==null) continue
    latSet.add(lat); lonSet.add(lon); raw[lat+','+lon]=map_val
  }
  const lats=[...latSet].sort((a,b)=>b-a),lons=[...lonSet].sort((a,b)=>a-b)
  const nL=lats.length,nO=lons.length; if(!nL||!nO) return null
  const cH=nL>1?lats[0]-lats[1]:0.25,cW=nO>1?lons[1]-lons[0]:0.25
  const LMXA=lats[0]+cH*.5,LMNA=lats[nL-1]-cH*.5,OMNA=lons[0]-cW*.5,OMXA=lons[nO-1]+cW*.5
  const canvas=document.createElement('canvas'); canvas.width=nO; canvas.height=nL
  const ctx=canvas.getContext('2d'),img=ctx.createImageData(nO,nL),d=img.data
  for(let i=0;i<nL;i++){
    for(let j=0;j<nO;j++){
      const v=raw[lats[i]+','+lons[j]],idx=(i*nO+j)*4
      if(v==null){d[idx+3]=0;continue}
      const rgb=v2rgb(v,scale)
      if(!rgb){d[idx+3]=0;continue}
      d[idx]=rgb[0];d[idx+1]=rgb[1];d[idx+2]=rgb[2];d[idx+3]=210
    }
  }
  ctx.putImageData(img,0,0)
  return {dataUrl:canvas.toDataURL(),coords:[[OMNA,LMXA],[OMXA,LMXA],[OMXA,LMNA],[OMNA,LMNA]]}
}

function fmtTip(props, L) {
  if (!props) return null
  const lines = [], mv = props.map_val
  L = L ?? ''

  // Determine variable from layer id prefix
  const isOnset = L.includes('onset') || L.startsWith('onset')
  const isCess  = L.includes('cess')  || L.startsWith('cess')
  const isLGP   = L.includes('lgp')   || L.startsWith('lgp')
  const varLabel = isOnset ? 'Onset' : isCess ? 'Cessation' : 'Season Length'
  const isDOY    = !isLGP

  if (mv != null) {
    // P50 / median layers
    if (L.includes('p50') || L.includes('med')) {
      const d = isDOY ? doyToDate(mv) : null
      const val = isDOY
        ? 'DOY ' + mv.toFixed(0) + (d ? '  (' + d + ')' : '')
        : mv.toFixed(0) + ' days'
      lines.push(varLabel + ' P50: ' + val)

    // Anomaly / bias layers
    } else if (L.includes('anom') || L.includes('bias')) {
      const sign = mv >= 0 ? '+' : ''
      const tag  = L.includes('bias') ? ' (model bias vs CHIRPS)' : ' (vs CHIRPS CAL mean)'
      lines.push(varLabel + ' anomaly: ' + sign + mv.toFixed(1) + 'd' + tag)

    // Spread layers
    } else if (L.includes('spr') || L.includes('spread')) {
      lines.push(varLabel + ' ensemble spread: ' + mv.toFixed(1) + 'd (P10-P90)')

    // Detection rate
    } else if (L.includes('det') || L.includes('detection')) {
      lines.push(varLabel + ' detection rate: ' + (mv * 100).toFixed(0) + '%')

    // Probability layers
    } else if (L.includes('prob_bn') || L === 'prob_bn') {
      lines.push('P(Below Normal): ' + (mv * 100).toFixed(0) + '%')
    } else if (L.includes('prob_an') || L === 'prob_an') {
      lines.push('P(Above Normal): ' + (mv * 100).toFixed(0) + '%')
    } else if (L.includes('failure') || L === 'failure') {
      lines.push('P(Season Failure): ' + (mv * 100).toFixed(0) + '%')
    } else if (L === 'prob_nn' || L.includes('prob_nn')) {
      lines.push(varLabel + ' P(Near Normal): ' + (mv * 100).toFixed(0) + '%')
    } else if (L === 'rpss_val' || L.includes('rpss')) {
      const sign = mv >= 0 ? '+' : ''
      lines.push(varLabel + ' RPSS: ' + sign + mv.toFixed(3) + (mv > 0 ? ' (skill above climatology)' : ' (below climatology)'))
    } else if (L === 'hitrate_val' || L.includes('hr')) {
      lines.push(varLabel + ' Hit Rate: ' + (mv * 100).toFixed(0) + '%  (ref: 33%)')
    } else if (L === 'alpha') {
      lines.push(varLabel + ' Alpha: ' + mv.toFixed(3))
    } else {
      // Fallback: show raw value
      lines.push(varLabel + ': ' + mv.toFixed(2))
    }
  } else {
    lines.push('No data at this pixel')
  }

  // CHIRPS CAL reference for onset/cessation/lgp layers
  if (props.chirps_on != null && isOnset) {
    const d = doyToDate(props.chirps_on)
    lines.push('CHIRPS CAL onset: DOY ' + Math.round(props.chirps_on) + (d ? '  (' + d + ')' : ''))
  }
  if (props.chirps_cs != null && isCess) {
    const d = doyToDate(props.chirps_cs)
    lines.push('CHIRPS CAL cess: DOY ' + Math.round(props.chirps_cs) + (d ? '  (' + d + ')' : ''))
  }
  if (props.chirps_lgp != null && isLGP) {
    lines.push('CHIRPS CAL LGP: ' + Math.round(props.chirps_lgp) + 'd')
  }

  // Grid coordinates
  if (props.lat != null) {
    lines.push('Grid: ' + Number(props.lat).toFixed(3) + 'N,  ' + Number(props.lon).toFixed(3) + 'E')
  }
  return lines
}

function Legend({scaleId}){
  const s=CS[scaleId]; if(!s) return null
  return(
    <div style={{background:'var(--bg-surface)',
                 border:'1px solid var(--border-primary)',borderRadius:8,padding:8,minWidth:140,backdropFilter:'blur(6px)'}}>
      <p style={{fontSize:9,color:'var(--text-muted)',marginBottom:4,textAlign:'center'}}>{s.label}</p>
      <div style={{display:'flex',borderRadius:3,overflow:'hidden',height:10,marginBottom:4}}>
        {s.c.map((c,i)=><div key={i} style={{flex:1,background:c}}/>)}
      </div>
      <div style={{display:'flex',justifyContent:'space-between',fontSize:8,color:'var(--text-faint)'}}>
        <span>{s.s[0]}</span><span>{s.s[Math.floor(s.s.length/2)]}</span><span>{s.s[s.s.length-1]}</span>
      </div>
    </div>
  )
}

function setupLayers(map, darkMode, onDone) {
  const beforeId=(()=>{
    for(const id of ['admin-0-boundary-bg','admin-0-boundary','water']){
      try{if(map.getLayer(id))return id}catch(_){}
    }
    return undefined
  })()
  if(darkMode){
    try{map.setPaintProperty('background','background-color','#0a0f1a')}catch(_){}
    try{map.setPaintProperty('water','fill-color','#0d1520')}catch(_){}
  }
  if(!map.getSource('forecast-raster')){
    map.addSource('forecast-raster',{type:'image',
      url:'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7',
      coordinates:[[33.5,5],[42.5,5],[42.5,-5],[33.5,-5]]})
    map.addLayer({id:'forecast-img',type:'raster',source:'forecast-raster',
      paint:{'raster-opacity':0.85,'raster-resampling':'nearest'}},beforeId)
  }
  if(!map.getSource('forecast-hits')){
    map.addSource('forecast-hits',{type:'geojson',data:{type:'FeatureCollection',features:[]}})
    map.addLayer({id:'forecast-hits-fill',type:'fill',source:'forecast-hits',paint:{'fill-color':'#000000','fill-opacity':0.001}})
  }
  if(!map.getSource('boundary-admin1')){
    map.addSource('boundary-admin1',{type:'geojson',data:{type:'FeatureCollection',features:[]}})
    map.addLayer({id:'boundary-admin1-line',type:'line',source:'boundary-admin1',
      layout:{visibility:'none'},
      paint:{
        'line-color': darkMode ? '#94a3b8' : '#475569',
        'line-width': 1.4,
        'line-dasharray': [3, 2],
        'line-opacity': 0.9
      }})
  }
  if(!map.getSource('boundary-admin0')){
    map.addSource('boundary-admin0',{type:'geojson',data:{type:'FeatureCollection',features:[]}})
    map.addLayer({id:'boundary-admin0-line',type:'line',source:'boundary-admin0',
      layout:{visibility:'visible'},
      paint:{
        'line-color': darkMode ? '#38bdf8' : '#0f172a',
        'line-width': 2.4,
        'line-opacity': 0.95
      }})
  }
  if(!map.getSource('monitored-farm-sites')){
    map.addSource('monitored-farm-sites', {type:'geojson', data: SITES_GEOJSON})
    map.addLayer({
      id: 'monitored-farm-sites-halo',
      type: 'circle',
      source: 'monitored-farm-sites',
      paint: {
        'circle-radius': 11,
        'circle-color': '#10b981',
        'circle-opacity': 0.28,
        'circle-stroke-color': '#059669',
        'circle-stroke-width': 1.5,
      }
    })
    map.addLayer({
      id: 'monitored-farm-sites-point',
      type: 'circle',
      source: 'monitored-farm-sites',
      paint: {
        'circle-radius': 6.5,
        'circle-color': '#10b981',
        'circle-stroke-color': '#ffffff',
        'circle-stroke-width': 2.2,
      }
    })
    map.addLayer({
      id: 'monitored-farm-sites-label',
      type: 'symbol',
      source: 'monitored-farm-sites',
      layout: {
        'text-field': ['get', 'short_name'],
        'text-size': 10,
        'text-offset': [0, 1.3],
        'text-anchor': 'top',
        'text-font': ['Open Sans Bold', 'Arial Unicode MS Bold'],
      },
      paint: {
        'text-color': darkMode ? '#f1f5f9' : '#0f172a',
        'text-halo-color': darkMode ? '#0f172a' : '#ffffff',
        'text-halo-width': 2,
      }
    })
  }
  if(!map.getSource('selected')){
    map.addSource('selected',{type:'geojson',data:{type:'FeatureCollection',features:[]}})
    map.addLayer({id:'selected-dot',type:'circle',source:'selected',
      paint:{'circle-radius':9,'circle-color':'#ef4444','circle-stroke-color':'#ffffff','circle-stroke-width':2.5}})
  }
  if(onDone) onDone()
}

// Apply cached boundary GeoJSON + visibility to a live map (called after
// initial setup, after basemap style swaps, and on toggle/country change).
function applyBoundaryLayers(map, boundaryData, showAdmin0, showAdmin1, darkMode){
  if(!map) return
  if(boundaryData?.admin0 && map.getSource('boundary-admin0')){
    try{ map.getSource('boundary-admin0').setData(cleanGeoJSON(boundaryData.admin0)) }
    catch(e){ console.warn('[boundaries] admin0 setData failed', e) }
  }
  if(boundaryData?.admin1 && map.getSource('boundary-admin1')){
    try{ map.getSource('boundary-admin1').setData(cleanGeoJSON(boundaryData.admin1)) }
    catch(e){ console.warn('[boundaries] admin1 setData failed', e) }
  }
  try{
    if(map.getLayer('boundary-admin0-line')){
      map.setLayoutProperty('boundary-admin0-line','visibility',showAdmin0?'visible':'none')
      map.setPaintProperty('boundary-admin0-line','line-color',darkMode?'#38bdf8':'#0f172a')
    }
  }catch(e){ console.warn('[boundaries] admin0 visibility failed', e) }
  try{
    if(map.getLayer('boundary-admin1-line')){
      map.setLayoutProperty('boundary-admin1-line','visibility',showAdmin1?'visible':'none')
      map.setPaintProperty('boundary-admin1-line','line-color',darkMode?'#94a3b8':'#475569')
    }
  }catch(e){ console.warn('[boundaries] admin1 visibility failed', e) }
}

// -- Main: gridData arrives as prop from App.jsx ---------------------------
export default function MapPanel({darkMode=false, selectedModel='', gridData=null, onLayerChange, activeTab='', country='kenya'}) {
  const mapContainer = useRef(null)
  const mapRef       = useRef(null)
  const darkRef      = useRef(darkMode)
  const countryRef   = useRef(country)
  const mapReadyRef  = useRef(false)
  const countryView  = COUNTRY_VIEWS[country] ?? COUNTRY_VIEWS.kenya
  const rasterRef    = useRef(null)
  const currentStyleRef = useRef(null)  // tracks what style is loaded: prevents spurious setStyle
  const [mapReady,   setMapReady]    = useState(false)
  const [basemapId,  setBasemapId]   = useState(darkMode?'dark':'light')
  const [showBasemaps, setShowBasemaps] = useState(false)
  const basemapRef   = useRef(basemapId)
  const [showAdmin0, setShowAdmin0]  = useState(true)
  const [showAdmin1, setShowAdmin1]  = useState(false)
  const [showBoundaries, setShowBoundaries] = useState(false)
  const showAdmin0Ref = useRef(showAdmin0)
  const showAdmin1Ref = useRef(showAdmin1)
  const boundaryDataRef = useRef({country:null, admin0:null, admin1:null})
  const [boundaryVersion, setBoundaryVersion] = useState(0)
  const [activeLayer,setActiveLayer] = useState(
    activeTab==='validation'?'v_rpss_onset':
    activeTab==='historical'?'h_onset_p50':
    activeTab==='probabilistic'?'p_onset_bn':
    activeTab==='multimodel'?'onset_med':
    'onset_anom'
  )
  const [showLayers, setShowLayers]  = useState(false)
  const prevTabRef = useRef(activeTab)
  // Auto-switch layer list when tab changes -- fires on mount too
  useEffect(() => {
    if (prevTabRef.current === activeTab) return
    prevTabRef.current = activeTab
    if (activeTab === 'historical') {
      const cfg = HIST_LAYERS[0]
      setActiveLayer(cfg.id)
      if (onLayerChange) onLayerChange({variable: cfg.variable, layer: cfg.layer})
    } else if (activeTab === 'multimodel') {
      const cfg = MULTI_LAYERS[0]
      setActiveLayer(cfg.id); if (onLayerChange) onLayerChange({variable:cfg.variable,layer:cfg.layer})
    } else if (activeTab === 'validation') {
      const cfg = VAL_LAYERS[0]
      setActiveLayer(cfg.id)
      if (onLayerChange) onLayerChange({variable: cfg.variable, layer: cfg.layer})
    } else {
      const cfg = LAYERS[0]
      setActiveLayer(cfg.id)
      if (onLayerChange) onLayerChange({variable: cfg.variable, layer: cfg.layer})
    }
  }, [activeTab])
  const [tooltip,    setTooltip]     = useState(null)

  const setSelectedSite = useDashboardStore(s=>s.setSelectedSite)
  const selectedSite    = useDashboardStore(s=>s.selectedSite)
  // Active layer list: strict tab-based selection
  const ALL_LAYERS = (
    activeTab === 'validation'    ? VAL_LAYERS :
    activeTab === 'historical'    ? HIST_LAYERS :
    activeTab === 'probabilistic' ? PROB_LAYERS :
    activeTab === 'multimodel'    ? MULTI_LAYERS :
    LAYERS
  )
  const layerCfg = ALL_LAYERS.find(l => l.id === activeLayer) ?? ALL_LAYERS[0]

  // Notify App when layer changes so App can refetch grid
  const handleLayerChange = (layerId) => {
    const allL = (
      activeTab === 'validation'    ? VAL_LAYERS :
      activeTab === 'historical'    ? HIST_LAYERS :
      activeTab === 'probabilistic' ? PROB_LAYERS :
      activeTab === 'multimodel'    ? MULTI_LAYERS :
      LAYERS
    )
    const cfg = allL.find(l=>l.id===layerId)??allL[0]
    setActiveLayer(layerId)
    setShowLayers(false)
    if(onLayerChange) onLayerChange({variable:cfg.variable, layer:cfg.layer})
  }

  // Build raster
  const [raster, setRaster] = useState(null)
  useEffect(()=>{
    console.log('[Raster build] gridData:', gridData?.features?.length, 'activeLayer:', activeLayer)
    const csKey2 = activeLayer.startsWith('h_') ? (
        activeLayer.includes('p50')  ? (activeLayer.includes('onset')?'onset_med':activeLayer.includes('cess')?'cess_med':'lgp_med')
      : activeLayer.includes('spr')  ? 'onset_spread'
      : activeLayer.includes('bias') ? 'bias'
      : activeLayer.includes('det')  ? 'detection_rate'
      : activeLayer) : activeLayer
    const scale=CS[csKey2]; if(!gridData||!scale){ console.log('[Raster build] SKIP - no data/scale'); return }
    const r = buildRaster(gridData,scale)
    console.log('[Raster build] result:', r ? 'OK dataUrl len='+r.dataUrl.length : 'NULL')
    if(r) setRaster(r)
  },[gridData,activeLayer])

  // -- Map init ----------------------------------------------------------
  useEffect(()=>{
    if(mapRef.current||!mapContainer.current) return
    const initialStyle = BASEMAPS[basemapRef.current].style
    currentStyleRef.current = initialStyle
    const map=new mapboxgl.Map({
      container:mapContainer.current,
      style:initialStyle,
      center:[37.9,0.0],zoom:5.4,minZoom:3,maxZoom:12
    })
    map.fitBounds(countryView.bounds,{padding:30,duration:0})
    map.addControl(new mapboxgl.NavigationControl({showCompass:false}),'top-right')
    map.addControl(new mapboxgl.ScaleControl({unit:'metric'}),'bottom-right')
    map.on('load',()=>{
      if(mapReadyRef.current) return   // guard double-fire
      setupLayers(map, darkRef.current, ()=>{
        console.log('[Map init] setupLayers complete')
        mapReadyRef.current = true
        // Apply any raster that arrived before map was ready
        if(rasterRef.current){
          const r = rasterRef.current
          try{
            map.getSource('forecast-raster')?.updateImage({url:r.dataUrl, coordinates:r.coords})
            setTimeout(()=>{try{map.setPaintProperty('forecast-img','raster-resampling','nearest');map.triggerRepaint()}catch(_){}},60)
            console.log('[Map init] raster applied from cache')
          }catch(e){ console.warn('init raster apply failed:',e) }
        }
        try{ map.setPaintProperty('forecast-img','raster-opacity',COUNTRY_VIEWS[countryRef.current]?.available?0.85:0) }catch(_){}
        applyBoundaryLayers(map, boundaryDataRef.current, showAdmin0Ref.current, showAdmin1Ref.current, darkRef.current)
        setMapReady(true)
      })
    })

    const handleMapClick = (e) => {
      if(!COUNTRY_VIEWS[countryRef.current]?.available) return

      // 1. Monitored farm site clicked
      try {
        const siteFeatures = map.queryRenderedFeatures(e.point, {
          layers: ['monitored-farm-sites-point', 'monitored-farm-sites-halo', 'monitored-farm-sites-label']
        })
        if (siteFeatures && siteFeatures.length > 0) {
          const p = siteFeatures[0].properties ?? {}
          const sName = p.site_name || 'Monitored Farm'
          const lat = Number(p.lat)
          const lon = Number(p.lon)
          setSelectedSite({ site_name: sName, lat, lon })
          return
        }
      } catch(_) {}

      // 2. Forecast grid cell clicked
      try {
        const gridFeatures = map.queryRenderedFeatures(e.point, {
          layers: ['forecast-hits-fill']
        })
        if (gridFeatures && gridFeatures.length > 0) {
          const p = gridFeatures[0].properties ?? {}
          const lat = typeof p.lat === 'number' ? p.lat : parseFloat(e.lngLat.lat.toFixed(3))
          const lon = typeof p.lon === 'number' ? p.lon : parseFloat(e.lngLat.lng.toFixed(3))
          const site_name = `${Math.abs(lat).toFixed(3)}°${lat >= 0 ? 'N' : 'S'}, ${Math.abs(lon).toFixed(3)}°E`
          setSelectedSite({ site_name, lat, lon })
          return
        }
      } catch(_) {}

      // 3. Fallback: Any click within Kenya bounds
      const { lng, lat } = e.lngLat
      if (lat >= -5.0 && lat <= 5.0 && lng >= 33.0 && lng <= 42.5) {
        const rLat = parseFloat(lat.toFixed(3))
        const rLon = parseFloat(lng.toFixed(3))
        const site_name = `${Math.abs(rLat).toFixed(3)}°${rLat >= 0 ? 'N' : 'S'}, ${Math.abs(rLon).toFixed(3)}°E`
        setSelectedSite({ site_name, lat: rLat, lon: rLon })
      }
    }

    const handleMouseMove = (e) => {
      if(!COUNTRY_VIEWS[countryRef.current]?.available) return

      // Check farm sites first
      try {
        const siteFeatures = map.queryRenderedFeatures(e.point, {
          layers: ['monitored-farm-sites-point', 'monitored-farm-sites-halo']
        })
        if (siteFeatures && siteFeatures.length > 0) {
          map.getCanvas().style.cursor = 'pointer'
          const p = siteFeatures[0].properties ?? {}
          setTooltip({
            x: e.point.x,
            y: e.point.y,
            isSite: true,
            site: p
          })
          return
        }
      } catch(_) {}

      // Check forecast grid
      try {
        const gridFeatures = map.queryRenderedFeatures(e.point, {
          layers: ['forecast-hits-fill']
        })
        if (gridFeatures && gridFeatures.length > 0) {
          map.getCanvas().style.cursor = 'crosshair'
          setTooltip({
            x: e.point.x,
            y: e.point.y,
            isSite: false,
            props: gridFeatures[0].properties ?? {}
          })
          return
        }
      } catch(_) {}

      map.getCanvas().style.cursor = ''
      setTooltip(null)
    }

    const handleMouseLeave = () => {
      map.getCanvas().style.cursor = ''
      setTooltip(null)
    }

    map.on('click', handleMapClick)
    map.on('mousemove', handleMouseMove)
    map.on('mouseleave', handleMouseLeave)
    window.__map = map
    window.__boundaryDataRef = boundaryDataRef
    mapRef.current=map
    return()=>{map.remove();mapRef.current=null;mapReadyRef.current=false;setMapReady(false)}
  },[])

  // -- Theme switch: only auto-follows the app theme while the user hasn't --
  // manually picked a non-theme basemap (osm/satellite/topo). Once they do,
  // toggling dark/light mode elsewhere in the app no longer yanks it back.
  useEffect(()=>{
    darkRef.current=darkMode
    setBasemapId(prev=>(prev==='dark'||prev==='light')?(darkMode?'dark':'light'):prev)
  },[darkMode])

  // -- Basemap switch: only call setStyle when URL actually changes --------
  // Using URL comparison is robust to React StrictMode double-invoke:
  // the map already has the correct style so currentStyleRef === targetStyle - skip
  useEffect(()=>{
    basemapRef.current=basemapId
    const map=mapRef.current; if(!map) return
    const targetStyle=BASEMAPS[basemapId].style
    if(currentStyleRef.current===targetStyle) return   // already correct, don't wipe sources
    currentStyleRef.current=targetStyle
    mapReadyRef.current=false; setMapReady(false); setTooltip(null)
    map.setStyle(targetStyle)
    map.once('style.load',()=>{
      setupLayers(map,darkRef.current,()=>{
        mapReadyRef.current=true; setMapReady(true)
        // Re-apply cached raster after style reload
        if(rasterRef.current){
          try{
            map.getSource('forecast-raster')?.updateImage({
              url:rasterRef.current.dataUrl,coordinates:rasterRef.current.coords
            })
            setTimeout(()=>{try{map.setPaintProperty('forecast-img','raster-resampling','nearest')}catch(_){}},50)
          }catch(_){}
        }
        try{ map.setPaintProperty('forecast-img','raster-opacity',COUNTRY_VIEWS[countryRef.current]?.available?0.85:0) }catch(_){}
        applyBoundaryLayers(map, boundaryDataRef.current, showAdmin0Ref.current, showAdmin1Ref.current, darkRef.current)
      })
    })
  },[basemapId])

  // -- Cache raster and apply immediately if map is ready -----------------
  // If map not ready yet, the setupLayers callback will pick it up from rasterRef
  useEffect(()=>{
    if(!raster) return
    rasterRef.current = raster
    const map = mapRef.current
    if(!map || !mapReadyRef.current) return
    const source = map.getSource('forecast-raster')
    if(!source){ console.warn('[raster effect] source not found: will apply on next setupLayers'); return }
    try{
      source.updateImage({url:raster.dataUrl, coordinates:raster.coords})
      setTimeout(()=>{try{map.setPaintProperty('forecast-img','raster-resampling','nearest');map.triggerRepaint()}catch(_){}},60)
      console.log('[raster effect] applied OK')
    }catch(e){ console.warn('[raster effect] failed:',e) }
  },[raster])

  // -- Fetch country/admin boundary GeoJSON when country changes ----------
  useEffect(()=>{
    const prefix = country==='ethiopia' ? 'eth' : 'ke'
    if(boundaryDataRef.current.country===prefix) return   // already cached
    let cancelled=false
    Promise.all([
      fetch(`/boundaries/${prefix}_admin0.geojson`).then(r=>r.ok?r.json():null),
      fetch(`/boundaries/${prefix}_admin1.geojson`).then(r=>r.ok?r.json():null),
    ]).then(([admin0,admin1])=>{
      if(cancelled) return
      boundaryDataRef.current = {country:prefix, admin0, admin1}
      setBoundaryVersion(v=>v+1)
    }).catch(e=>console.warn('[boundaries] fetch failed:',e))
    return ()=>{cancelled=true}
  },[country])

  // -- Apply boundary data/visibility whenever either becomes ready --------
  // Guards against the race where the (fast, local) GeoJSON fetch resolves
  // before the (slower, external-tile-dependent) map finishes its own load.
  useEffect(()=>{
    showAdmin0Ref.current=showAdmin0
    showAdmin1Ref.current=showAdmin1
    const map=mapRef.current; if(!map||!mapReadyRef.current) return
    applyBoundaryLayers(map, boundaryDataRef.current, showAdmin0, showAdmin1, darkRef.current)
  },[showAdmin0,showAdmin1,mapReady,boundaryVersion,darkMode])

  // Log when gridData prop changes
  useEffect(()=>{
    console.log('[MapPanel] gridData prop changed:', gridData?.features?.length, 'features')
  },[gridData])

  // -- Update hit polygons -----------------------------------------------
  useEffect(()=>{
    const map=mapRef.current; if(!map||!mapReadyRef.current||!gridData) return
    try{map.getSource('forecast-hits')?.setData(gridData)}catch(_){}
  },[gridData,mapReady])

  // -- Country switch: recenter map + hide forecast raster when unavailable --
  useEffect(()=>{
    countryRef.current = country
    const map=mapRef.current; if(!map) return
    map.fitBounds(countryView.bounds,{padding:30,duration:800})
    setTooltip(null)
    if(!mapReadyRef.current) return
    try{ map.setPaintProperty('forecast-img','raster-opacity',countryView.available?0.85:0) }catch(_){}
  },[country])

  // -- Selected site -----------------------------------------------------
  useEffect(()=>{
    const map=mapRef.current; if(!map||!mapReady) return
    const fc=selectedSite
      ?{type:'FeatureCollection',features:[{type:'Feature',geometry:{type:'Point',coordinates:[selectedSite.lon,selectedSite.lat]},properties:{}}]}
      :{type:'FeatureCollection',features:[]}
    try{map.getSource('selected')?.setData(fc)}catch(_){}
  },[selectedSite,mapReady])

  const tipLines=tooltip?fmtTip(tooltip.props,activeLayer):null
  const brd='1px solid var(--border-primary)'

  return (
    <div style={{position:'relative',display:'flex',flexDirection:'column',height:'100%',overflow:'visible',borderRadius:12,background:'var(--bg-surface)',border:brd}}>
      <div ref={mapContainer} style={{flex:1,width:'100%',borderRadius:12,overflow:'hidden',position:'relative'}}/>


      {/* Layer switcher */}
      <div style={{position:'absolute',inset:0,zIndex:20,pointerEvents:'none',borderRadius:12,overflow:'hidden'}}>

        {!countryView.available && (
          <div style={{position:'absolute',top:14,left:'50%',transform:'translateX(-50%)',pointerEvents:'none',
                       display:'flex',flexDirection:'column',alignItems:'center',gap:4,textAlign:'center',
                       background:'var(--bg-elevated)',border:brd,borderRadius:10,padding:'10px 18px',
                       backdropFilter:'blur(6px)',maxWidth:260}}>
            <span style={{fontSize:10,fontWeight:700,letterSpacing:'0.08em',textTransform:'uppercase',color:'var(--accent-blue)'}}>
              {countryView.label} forecasts coming soon
            </span>
            <span style={{fontSize:9,color:'var(--text-secondary)',lineHeight:1.5}}>
              The onset / cessation / season-length pipeline for {countryView.label} is still being processed.
              Map shown for reference only.
            </span>
          </div>
        )}

        {/* Layer picker -- top-left */}
        {countryView.available && (
        <div style={{position:'absolute',top:8,left:8,pointerEvents:'auto'}}>

        <button onClick={()=>setShowLayers(v=>!v)}
          style={{display:'flex',alignItems:'center',gap:6,padding:'5px 10px',borderRadius:8,fontSize:10,cursor:'pointer',backdropFilter:'blur(4px)',background:'var(--bg-elevated)',border:brd,color:'var(--text-secondary)'}}>
          <span style={{fontSize:9,fontWeight:700,color:'var(--text-muted)'}}>LAYERS</span>
          <span style={{fontSize:9,maxWidth:110,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap',color:'var(--accent-blue)'}}>{layerCfg.label}</span>
          <span style={{fontSize:8,color:'var(--text-faint)'}}>v</span>
        </button>
        {showLayers && (
          activeTab === 'probabilistic' ? (
            <div style={{marginTop:4,borderRadius:8,boxShadow:'0 8px 24px rgba(0,0,0,0.35)',
                         background:'var(--bg-elevated)',border:brd,padding:'10px',minWidth:280}}>
              <div style={{display:'grid',gridTemplateColumns:'90px 1fr 1fr 1fr',gap:4,marginBottom:4}}>
                <div/>
                {['BN','NN','AN'].map(g=>(
                  <div key={g} style={{fontSize:8,fontWeight:700,textTransform:'uppercase',
                                       letterSpacing:'0.08em',color:'var(--accent-blue)',
                                       textAlign:'center',padding:'2px 0'}}>{g}</div>
                ))}
              </div>
              {[
                {row:'Onset',      ids:['p_onset_bn','p_onset_nn','p_onset_an']},
                {row:'Cessation',  ids:['p_cess_bn', 'p_cess_nn', 'p_cess_an']},
                {row:'Season Len', ids:['p_lgp_bn',  'p_lgp_nn',  'p_lgp_an']},
              ].map(({row,ids})=>(
                <div key={row} style={{display:'grid',gridTemplateColumns:'90px 1fr 1fr 1fr',gap:4,marginBottom:4}}>
                  <div style={{fontSize:9,color:'var(--text-muted)',display:'flex',alignItems:'center',
                               paddingLeft:2,fontWeight:600}}>{row}</div>
                  {ids.map(id=>{
                    const l=PROB_LAYERS.find(x=>x.id===id)
                    if(!l) return <div key={id}/>
                    const active=l.id===activeLayer
                    return (
                      <button key={id} onClick={()=>handleLayerChange(id)}
                        style={{padding:'5px 4px',borderRadius:5,fontSize:9,cursor:'pointer',
                                textAlign:'center',border:'1px solid '+(active?'var(--accent-blue)':'var(--border-primary)'),
                                background:active?'var(--accent-blue)':'var(--bg-surface)',
                                color:active?'#fff':'var(--text-secondary)',fontWeight:active?700:400}}>
                        {l.group}
                      </button>
                    )
                  })}
                </div>
              ))}
              {(()=>{
                const l=PROB_LAYERS.find(x=>x.id==='p_failure')
                const active=activeLayer==='p_failure'
                return l?<button onClick={()=>handleLayerChange('p_failure')}
                  style={{width:'100%',marginTop:4,padding:'5px 8px',borderRadius:5,fontSize:9,
                          cursor:'pointer',textAlign:'center',
                          border:'1px solid '+(active?'var(--accent-blue)':'var(--border-primary)'),
                          background:active?'var(--accent-blue)':'var(--bg-surface)',
                          color:active?'#fff':'var(--text-secondary)',fontWeight:active?700:400}}>
                  P(Season Failure)</button>:null
              })()}
            </div>
          ) : activeTab !== 'historical' && activeTab !== 'validation' ? (
            <div style={{marginTop:4,borderRadius:8,boxShadow:'0 8px 24px rgba(0,0,0,0.35)',
                         background:'var(--bg-elevated)',border:brd,padding:'10px',minWidth:280}}>
              <div style={{display:'grid',gridTemplateColumns:'80px 1fr 1fr',gap:3,marginBottom:4}}>
                <div/>
                {['Median','Anomaly'].map(g=>(

                  <div key={g} style={{fontSize:8,fontWeight:700,textTransform:'uppercase',
                                       letterSpacing:'0.08em',color:'var(--accent-blue)',
                                       textAlign:'center',padding:'2px 0'}}>{g}</div>
                ))}
              </div>
              {[
                {row:'Onset',      ids:['onset_med','onset_anom']},
                {row:'Cessation',  ids:['cess_med','cess_anom']},
                {row:'Season Len', ids:['lgp_med','lgp_anom']},
              ].map(({row,ids})=>(
                <div key={row} style={{display:'grid',gridTemplateColumns:'90px 1fr 1fr',gap:4,marginBottom:4}}>
                  <div style={{fontSize:9,color:'var(--text-muted)',display:'flex',alignItems:'center',
                               paddingLeft:2,fontWeight:600}}>{row}</div>
                  {ids.map(id=>{
                    const l=ALL_LAYERS.find(x=>x.id===id)
                    if(!l) return <div key={id}/>
                    const active=l.id===activeLayer
                    return (
                      <button key={id} onClick={()=>handleLayerChange(id)}
                        style={{padding:'5px 4px',borderRadius:5,fontSize:9,cursor:'pointer',
                                textAlign:'center',border:'1px solid '+(active?'var(--accent-blue)':'var(--border-primary)'),
                                background:active?'var(--accent-blue)':'var(--bg-surface)',
                                color:active?'#fff':'var(--text-secondary)',fontWeight:active?700:400}}>
                        {l.group?.slice(0,3)??id}
                      </button>
                    )
                  })}
                </div>
              ))}
            </div>
          ) : activeTab === 'multimodel' ? (
            /* Multi-model: 3x3 grid -- Equal/HR-Wt/RPSS-Wt x Onset/Cess/Season */
            <div style={{marginTop:4,borderRadius:8,boxShadow:'0 8px 24px rgba(0,0,0,0.35)',
                         background:'var(--bg-elevated)',border:brd,padding:'10px',minWidth:290}}>
              <div style={{display:'grid',gridTemplateColumns:'90px 1fr 1fr 1fr',gap:4,marginBottom:4}}>
                <div/>
                {['Equal','HR-Wt','RPSS-Wt'].map(g=>(
                  <div key={g} style={{fontSize:8,fontWeight:700,textTransform:'uppercase',
                                       letterSpacing:'0.08em',color:'var(--accent-blue)',
                                       textAlign:'center',padding:'2px 0'}}>{g}</div>
                ))}
              </div>
              {[
                {row:'Onset',      ids:['onset_med','onset_hr_w','onset_rpss_w']},
                {row:'Cessation',  ids:['cess_med', 'cess_hr_w', 'cess_rpss_w']},
                {row:'Season Len', ids:['lgp_med',  'lgp_hr_w',  'lgp_rpss_w']},
              ].map(({row,ids})=>(
                <div key={row} style={{display:'grid',gridTemplateColumns:'90px 1fr 1fr 1fr',gap:4,marginBottom:4}}>
                  <div style={{fontSize:9,color:'var(--text-muted)',display:'flex',alignItems:'center',
                               paddingLeft:2,fontWeight:600}}>{row}</div>
                  {ids.map(id=>{
                    const l=MULTI_LAYERS.find(x=>x.id===id)
                    if(!l) return <div key={id}/>
                    const active=l.id===activeLayer
                    return (
                      <button key={id} onClick={()=>handleLayerChange(id)}
                        style={{padding:'5px 4px',borderRadius:5,fontSize:9,cursor:'pointer',
                                textAlign:'center',border:'1px solid '+(active?'var(--accent-blue)':'var(--border-primary)'),
                                background:active?'var(--accent-blue)':'var(--bg-surface)',
                                color:active?'#fff':'var(--text-secondary)',fontWeight:active?700:400}}>
                        {l.group}
                      </button>
                    )
                  })}
                </div>
              ))}
            </div>
          ) : activeTab === 'validation' ? (
            <div style={{marginTop:4,borderRadius:8,boxShadow:'0 8px 24px rgba(0,0,0,0.35)',
                         background:'var(--bg-elevated)',border:brd,padding:'10px',minWidth:280}}>
              <div style={{display:'grid',gridTemplateColumns:'90px 1fr 1fr 1fr',gap:4,marginBottom:4}}>
                <div/>
                {['RPSS','HR','Alpha'].map(g=>(
                  <div key={g} style={{fontSize:8,fontWeight:700,textTransform:'uppercase',
                                       letterSpacing:'0.08em',color:'var(--accent-blue)',
                                       textAlign:'center',padding:'2px 0'}}>{g}</div>
                ))}
              </div>
              {[
                {row:'Onset',      ids:['v_rpss_onset','v_hr_onset','v_alpha_onset']},
                {row:'Cessation',  ids:['v_rpss_cess', 'v_hr_cess', 'v_alpha_cess']},
                {row:'Season Len', ids:['v_rpss_lgp',  'v_hr_lgp',  'v_alpha_lgp']},
              ].map(({row,ids})=>(
                <div key={row} style={{display:'grid',gridTemplateColumns:'90px 1fr 1fr 1fr',gap:4,marginBottom:4}}>
                  <div style={{fontSize:9,color:'var(--text-muted)',display:'flex',alignItems:'center',
                               paddingLeft:2,fontWeight:600}}>{row}</div>
                  {ids.map(id=>{
                    const l=VAL_LAYERS.find(x=>x.id===id)
                    if(!l) return <div key={id}/>
                    const active=l.id===activeLayer
                    return (
                      <button key={id} onClick={()=>handleLayerChange(id)}
                        style={{padding:'5px 4px',borderRadius:5,fontSize:9,cursor:'pointer',
                                textAlign:'center',border:'1px solid '+(active?'var(--accent-blue)':'var(--border-primary)'),
                                background:active?'var(--accent-blue)':'var(--bg-surface)',
                                color:active?'#fff':'var(--text-secondary)',fontWeight:active?700:400}}>
                        {l.group}
                      </button>
                    )
                  })}
                </div>
              ))}
            </div>
          ) : activeTab === 'historical' ? (
            <div style={{marginTop:4,borderRadius:8,boxShadow:'0 8px 24px rgba(0,0,0,0.35)',
                         background:'var(--bg-elevated)',border:brd,padding:'10px',minWidth:310}}>
              <div style={{display:'grid',gridTemplateColumns:'90px 1fr 1fr 1fr 1fr',gap:4,marginBottom:4}}>
                <div/>
                {['Median','Spread','Bias','Det.'].map(g=>(
                  <div key={g} style={{fontSize:8,fontWeight:700,textTransform:'uppercase',
                                       letterSpacing:'0.08em',color:'var(--accent-blue)',
                                       textAlign:'center',padding:'2px 0'}}>{g}</div>
                ))}
              </div>
              {[
                {row:'Onset',      ids:['h_onset_p50','h_onset_spr','h_onset_bias','h_onset_det']},
                {row:'Cessation',  ids:['h_cess_p50', 'h_cess_spr', 'h_cess_bias', 'h_cess_det']},
                {row:'Season Len', ids:['h_lgp_p50',  'h_lgp_spr',  'h_lgp_bias',  'h_lgp_det']},
              ].map(({row,ids})=>(
                <div key={row} style={{display:'grid',gridTemplateColumns:'90px 1fr 1fr 1fr 1fr',gap:4,marginBottom:4}}>
                  <div style={{fontSize:9,color:'var(--text-muted)',display:'flex',alignItems:'center',
                               paddingLeft:2,fontWeight:600}}>{row}</div>
                  {ids.map(id=>{
                    const l=HIST_LAYERS.find(x=>x.id===id)
                    if(!l) return <div key={id}/>
                    const active=l.id===activeLayer
                    return (
                      <button key={id} onClick={()=>handleLayerChange(id)}
                        style={{padding:'5px 4px',borderRadius:5,fontSize:9,cursor:'pointer',
                                textAlign:'center',border:'1px solid '+(active?'var(--accent-blue)':'var(--border-primary)'),
                                background:active?'var(--accent-blue)':'var(--bg-surface)',
                                color:active?'#fff':'var(--text-secondary)',fontWeight:active?700:400}}>
                        {l.group}
                      </button>
                    )
                  })}
                </div>
              ))}
            </div>
          ) : null
        )}
        </div>
        )}

        {/* Farm Quick Selector -- top-right (next to MapLibre nav controls) */}
        {countryView.available && (
          <div style={{position:'absolute',top:8,right:44,pointerEvents:'auto'}}>
            <select
              value={MONITORED_SITES.some(s=>s.site_name===selectedSite?.site_name) ? selectedSite.site_name : ''}
              onChange={(e) => {
                const site = MONITORED_SITES.find(s => s.site_name === e.target.value)
                if (site) {
                  setSelectedSite({ site_name: site.site_name, lat: site.lat, lon: site.lon })
                  mapRef.current?.flyTo({ center: [site.lon, site.lat], zoom: 7.5, duration: 800 })
                }
              }}
              style={{padding:'5px 10px',borderRadius:8,fontSize:10,cursor:'pointer',
                      backdropFilter:'blur(4px)',background:'var(--bg-elevated)',border:brd,
                      color:'var(--text-secondary)',fontWeight:600,outline:'none'}}>
              <option value="">🎯 Monitored Farms ({MONITORED_SITES.length})...</option>
              {MONITORED_SITES.map(s => (
                <option key={s.site_name} value={s.site_name}>
                  {s.site_name.replace(' Farm', '')} ({s.county})
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Selected Site Indicator Badge -- top-left underneath layer dropdown */}
        {selectedSite && countryView.available && (
          <div style={{position:'absolute',top:38,left:8,pointerEvents:'auto',
                       display:'flex',alignItems:'center',gap:6,padding:'4px 9px',
                       borderRadius:6,fontSize:9,background:'var(--bg-elevated)',
                       border:brd,backdropFilter:'blur(4px)',boxShadow:'0 2px 8px rgba(0,0,0,0.2)'}}>
            <span style={{width:6,height:6,borderRadius:'50%',background:'#ef4444'}}/>
            <span style={{color:'var(--text-muted)',fontWeight:700}}>ACTIVE:</span>
            <span style={{color:'var(--text-primary)',fontWeight:600,maxWidth:160,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>
              {selectedSite.site_name}
            </span>
            <span style={{color:'var(--text-faint)'}}>
              ({selectedSite.lat.toFixed(2)}°, {selectedSite.lon.toFixed(2)}°)
            </span>
          </div>
        )}

        {/* Colour legend -- bottom-right */}
        {countryView.available && (
        <div style={{position:'absolute',bottom:8,right:8,pointerEvents:'auto'}}>
          <Legend scaleId={activeLayer}/>
        </div>
        )}

        {/* Basemap picker -- bottom-left */}
        <div style={{position:'absolute',bottom:8,left:8,pointerEvents:'auto'}}>
          <button onClick={()=>setShowBasemaps(v=>!v)}
            style={{display:'flex',alignItems:'center',gap:6,padding:'5px 10px',borderRadius:8,fontSize:10,cursor:'pointer',backdropFilter:'blur(4px)',background:'var(--bg-elevated)',border:brd,color:'var(--text-secondary)'}}>
            <span style={{fontSize:9,fontWeight:700,color:'var(--text-muted)'}}>MAP</span>
            <span style={{fontSize:9,color:'var(--accent-blue)'}}>{BASEMAPS[basemapId].label}</span>
            <span style={{fontSize:8,color:'var(--text-faint)'}}>v</span>
          </button>
          {showBasemaps && (
            <div style={{position:'absolute',bottom:'100%',left:0,marginBottom:4,borderRadius:8,
                         boxShadow:'0 8px 24px rgba(0,0,0,0.35)',background:'var(--bg-elevated)',
                         border:brd,padding:6,minWidth:140}}>
              {Object.entries(BASEMAPS).map(([id,{label}])=>{
                const active=id===basemapId
                return (
                  <button key={id} onClick={()=>{setBasemapId(id);setShowBasemaps(false)}}
                    style={{display:'block',width:'100%',padding:'6px 8px',borderRadius:5,fontSize:10,
                            cursor:'pointer',textAlign:'left',marginBottom:2,
                            border:'1px solid '+(active?'var(--accent-blue)':'transparent'),
                            background:active?'var(--accent-blue)':'transparent',
                            color:active?'#fff':'var(--text-secondary)',fontWeight:active?700:400}}>
                    {label}
                  </button>
                )
              })}
            </div>
          )}
        </div>

        {/* Boundary toggles -- bottom-left, next to basemap picker */}
        <div style={{position:'absolute',bottom:8,left:110,pointerEvents:'auto',display:'flex',gap:5}}>
          <button onClick={()=>setShowAdmin0(v=>!v)}
            title="Toggle Kenya National Border"
            style={{display:'flex',alignItems:'center',gap:5,padding:'5px 9px',borderRadius:8,fontSize:9,cursor:'pointer',
                    backdropFilter:'blur(4px)',
                    background: showAdmin0 ? (darkMode ? 'rgba(56,189,248,0.2)' : '#e0f2fe') : 'var(--bg-elevated)',
                    border: '1px solid ' + (showAdmin0 ? 'var(--accent-blue)' : 'var(--border-primary)'),
                    color: showAdmin0 ? 'var(--accent-blue)' : 'var(--text-secondary)',
                    fontWeight: showAdmin0 ? 700 : 500}}>
            <span style={{width:6,height:6,borderRadius:'50%',background:showAdmin0?'var(--accent-blue)':'var(--text-faint)'}}/>
            BORDER: {showAdmin0 ? 'ON' : 'OFF'}
          </button>
          <button onClick={()=>setShowAdmin1(v=>!v)}
            title="Toggle County / District Boundaries"
            style={{display:'flex',alignItems:'center',gap:5,padding:'5px 9px',borderRadius:8,fontSize:9,cursor:'pointer',
                    backdropFilter:'blur(4px)',
                    background: showAdmin1 ? (darkMode ? 'rgba(16,185,129,0.2)' : '#d1fae5') : 'var(--bg-elevated)',
                    border: '1px solid ' + (showAdmin1 ? '#10b981' : 'var(--border-primary)'),
                    color: showAdmin1 ? (darkMode ? '#34d399' : '#059669') : 'var(--text-secondary)',
                    fontWeight: showAdmin1 ? 700 : 500}}>
            <span style={{width:6,height:6,borderRadius:'50%',background:showAdmin1?'#10b981':'var(--text-faint)'}}/>
            COUNTIES: {showAdmin1 ? 'ON' : 'OFF'}
          </button>
        </div>

        {/* Hover tooltip -- follows cursor over monitored farm sites and forecast grid */}
        {tooltip && (
          <div style={{position:'absolute',left:tooltip.x+14,top:tooltip.y+14,
                       background:'var(--bg-elevated)',border:brd,borderRadius:8,
                       padding:'8px 12px',maxWidth:260,boxShadow:'0 8px 24px rgba(0,0,0,0.4)',
                       zIndex:30}}>
            {tooltip.isSite ? (
              <div>
                <div style={{fontSize:11,fontWeight:800,color:'#10b981',marginBottom:3,display:'flex',alignItems:'center',gap:4}}>
                  <span>📍</span> {tooltip.site.site_name}
                </div>
                <div style={{fontSize:9,color:'var(--text-secondary)',marginBottom:2}}>
                  County: <strong style={{color:'var(--text-primary)'}}>{tooltip.site.county}</strong>  •  {tooltip.site.desc}
                </div>
                <div style={{fontSize:8,color:'var(--text-faint)',marginTop:4,borderTop:'1px solid var(--border-primary)',paddingTop:3}}>
                  {Number(tooltip.site.lat).toFixed(3)}°N, {Number(tooltip.site.lon).toFixed(3)}°E  •  <span style={{color:'var(--accent-blue)',fontWeight:600}}>Click to load forecast</span>
                </div>
              </div>
            ) : tipLines ? (
              tipLines.map((line,i)=>(
                <div key={i} style={{fontSize:9,color:i===0?'var(--accent-blue)':'var(--text-secondary)',
                                      fontWeight:i===0?700:400,whiteSpace:'nowrap',
                                      marginBottom:i<tipLines.length-1?2:0}}>
                  {line}
                </div>
              ))
            ) : null}
          </div>
        )}
      </div>
    </div>
  )
}
