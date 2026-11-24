// Farm status: Normal, Watch, Attention or Insufficient data, from the signals published for the farm's main
// forecast cell and, when the user has checked it, the farm's own Sentinel-2 view. Plain rules, each with its
// reason; no signal is invented when its data are missing. The thresholds are listed in RULES for the panel.

export const LEVELS = { attention: 3, watch: 2, normal: 1 }
export const STATUS_LABEL = { attention: 'Attention', watch: 'Watch', normal: 'Normal', insufficient: 'Insufficient data' }

export const RULES = [
  ['Rain since 1 Oct (CHIRPS)', 'Watch under 75% of normal; Attention under 50%.'],
  ['Crop outlook (AquaCrop, DSSAT)', 'Watch when a model\'s chance of crop failure is at least 15 points above its normal; Attention when both are, and both are 50% or more.'],
  ['Cropland greenness in the cell (Sentinel-2, last 16 days)', 'Watch at 1 standard deviation below the past years; Attention at 1.5 below and less green than in all but at most one past year.'],
  ['The farm itself (Sentinel-2, when checked)', 'Watch when a quarter of the farm is much less green than the rest; Attention when the farm is 0.1 NDVI below its past years\' median and less green than in all but at most one of them.'],
]

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const n = v => (v === '' || v == null || Number.isNaN(Number(v)) ? null : Number(v))
const pct = v => `${Math.round(v * 100)}%`

// {status, signals: [{name, level, text}], used: number of signals with data}
export function farmStatus({ grid, aq, ds, veg, sat }) {
  const sig = []
  const rain = n(grid?.chirps_pct_normal)
  if (rain != null) {
    sig.push({ name: 'Rain so far', level: rain < 50 ? 'attention' : rain < 75 ? 'watch' : 'normal',
               text: `Rain since 1 Oct is ${Math.round(rain)}% of normal in the cell.` })
  }
  const models = [['AquaCrop', aq], ['DSSAT', ds]].filter(([, c]) => c && n(c.p_failure) != null)
  if (models.length) {
    const high = models.filter(([, c]) => c.p_failure >= (c.normal_p_failure ?? 0) + 0.15)
    const level = high.length === models.length && models.length === 2 && models.every(([, c]) => c.p_failure >= 0.5) ? 'attention'
      : high.length ? 'watch' : 'normal'
    sig.push({ name: 'Crop outlook', level,
               text: models.map(([m, c]) => `${m} ${pct(c.p_failure)} chance of failure (normal ${pct(c.normal_p_failure ?? 0)})`).join('; ') + '.' })
  }
  const z = n(veg?.z)
  if (z != null) {
    const lower = n(veg.lower_years), yrs = n(veg.years)
    const level = z <= -1.5 && lower != null && lower <= 1 ? 'attention' : z <= -1 ? 'watch' : 'normal'
    sig.push({ name: 'Cropland greenness in the cell', level,
               text: `Cropland NDVI ${Number(veg.ndvi).toFixed(2)} against ${Number(veg.base_mean).toFixed(2)} in past years (${z > 0 ? '+' : ''}${z.toFixed(1)} SD; greener than in ${lower} of ${yrs}).` })
  }
  if (sat?.latest && !sat.latest.none && sat.latest.ndvi) {
    const L = sat.latest
    const got = (sat.past ?? []).filter(p => !p.none && p.ndvi)
    let level = L.low != null && L.low >= 0.25 ? 'watch' : 'normal'
    const [, mo, d] = L.date.split('-').map(Number)
    let text = `Farm NDVI ${L.ndvi.mean.toFixed(2)} on ${d} ${MON[mo - 1]}`
    if (got.length >= 3) {
      const s = got.map(p => p.ndvi.mean).sort((a, b) => a - b)
      const med = s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2
      const lower = got.filter(p => L.ndvi.mean > p.ndvi.mean).length
      if (L.ndvi.mean - med <= -0.1 && lower <= 1) level = 'attention'
      text += `; past years' median ${med.toFixed(2)}, greener than in ${lower} of ${got.length}`
    }
    if (L.low != null && L.low >= 0.25) text += `; ${pct(L.low)} of the farm much less green than the rest`
    sig.push({ name: 'The farm (satellite)', level, text: text + '.' })
  }
  const worst = sig.reduce((w, s) => (LEVELS[s.level] > LEVELS[w] ? s.level : w), 'normal')
  // one signal that is fine is too little to call the farm normal; a warning from one signal still stands
  const status = !sig.length || (sig.length < 2 && worst === 'normal') ? 'insufficient' : worst
  return { status, signals: sig, used: sig.length }
}
