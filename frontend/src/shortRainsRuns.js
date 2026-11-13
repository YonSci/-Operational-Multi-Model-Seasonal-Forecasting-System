// Kenya Short Rains forecast runs, oldest first: the dashboard's run selector, its freshness notice and the landing
// page's preview all take the newest published one from here, so they always show the same run.
// Oct runs appear only when the backend has them.
export const SHORT_RAINS_INITS = [
  { init: '0901', initLabel: 'Sep 01', model: 'ECMWF SEAS5 (Sep)' },
  { init: '1001', initLabel: 'Oct 01', model: 'ECMWF SEAS5 (Oct)' },
  { init: '1001o', initLabel: 'Oct 01 + Sep obs', model: 'ECMWF SEAS5 (Oct+Obs)' },
  { init: '1001ol', initLabel: 'Oct 01 + latest obs', model: 'ECMWF SEAS5 (Oct+Obs latest)' },
  // latest obs, then ECMWF ENS (days 1-15) and extended range (to day 46), then SEAS5 (blend_subseasonal.py)
  { init: '1001w', initLabel: 'Oct 01 + obs + weather forecasts (experimental)', model: 'ECMWF SEAS5 (Oct+Obs+S2S)', experimental: true },
]

export const hasModel = (modelsData, name) =>
  Object.entries(modelsData?.models ?? {}).some(([k, m]) => k === name || m?.raw_name === name)

// The newest Short Rains run the backend has published (the experimental blend is an alternative, not a newer run)
export const latestShortRainsInit = modelsData =>
  SHORT_RAINS_INITS.filter(i => !i.experimental && (i.init === '0901' || hasModel(modelsData, i.model))).at(-1)
