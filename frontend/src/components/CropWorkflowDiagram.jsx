import React from 'react'

// The crop engine's workflow (CROP_ENGINE.md): inputs → daily crop weather per member → the two crop models →
// the Crop outlook tab and its scenarios, with verification of the results and calibration of the parameters.
// Drawn in the page's theme colours; wider than a phone, so it scrolls inside its own box.

const W = 1040, H = 700
const LINE = 19

const TONE = {
  input: 'var(--accent-blue)', weather: 'var(--violet-text)', model: 'var(--ok-text)',
  product: 'var(--warn-text)', check: 'var(--pink-text)',
}

// a box sized to its lines: title, then one line per entry ('' for a gap)
const boxH = n => 40 + n * LINE

function Box({ x, y, w, h, title, lines, tone, strong }) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h ?? boxH(lines.length)} rx={8} style={{ fill: 'var(--bg-elevated)', stroke: 'var(--border-primary)' }} strokeWidth={1} />
      <rect x={x} y={y} width={5} height={h ?? boxH(lines.length)} rx={2} style={{ fill: TONE[tone] }} />
      <text x={x + 16} y={y + 24} style={{ fill: 'var(--heading)', fontSize: 15, fontWeight: strong ? 700 : 600 }}>{title}</text>
      {lines.map((l, i) => (
        <text key={i} x={x + 16} y={y + 45 + i * LINE} style={{ fill: 'var(--text-secondary)', fontSize: 13 }}>{l}</text>
      ))}
    </g>
  )
}

function Arrow({ d, dashed }) {
  return <path d={d} fill="none" style={{ stroke: 'var(--text-meta)' }} strokeWidth={1.5}
               strokeDasharray={dashed ? '5 4' : undefined} markerEnd="url(#cw-arrow)" />
}

function Label({ x, y, children, anchor = 'start', weight = 400, size = 12 }) {
  return <text x={x} y={y} textAnchor={anchor} style={{ fill: 'var(--text-meta)', fontSize: size, fontWeight: weight, letterSpacing: weight > 400 ? 0.4 : 0 }}>{children}</text>
}

export default function CropWorkflowDiagram() {
  const c1 = 20, c2 = 290, c3 = 540, c4 = 800, bw = 232, top = 42, gap = 12
  // 1 inputs, stacked
  const inputs = [
    { title: 'Rain', lines: ['CHIRPS v2 observed', 'SEAS5, sub-seasonal and', 'weather-model members'] },
    { title: 'Temperature, sun, air', lines: ['ERA5-Land at the site, then', 'the sub-seasonal model’s,', 'then SEAS5 (bias-corrected)'] },
    { title: 'Soil', lines: ['SoilGrids layers to 200 cm', 'ERA5-Land water on 1 Aug'] },
    { title: 'Sowing date', lines: ['Agri rule 1 onset', 'FAO agricultural onset', 're-sown after a false start'] },
  ]
  let y = top
  const placed = inputs.map(b => { const p = { ...b, y, h: boxH(b.lines.length) }; y += p.h + gap; return p })
  const bottom = y - gap                                   // the lowest input box's bottom edge
  const span = bottom - top
  const half = (span - gap) / 2
  const band = bottom + 74                                 // the calibration and verification boxes
  const bandH = boxH(4)
  return (
    <div style={{ overflowX: 'auto', border: '1px solid var(--border-primary)', borderRadius: 10, background: 'var(--bg-surface)', padding: 8 }}>
      <svg viewBox={`0 0 ${W} ${band + bandH + 70}`} role="img" aria-labelledby="cw-title cw-desc" style={{ width: '100%', minWidth: 860, height: 'auto', display: 'block' }}>
        <title id="cw-title">Crop engine workflow</title>
        <desc id="cw-desc">Rain, temperature, radiation, soil and sowing dates are assembled into daily weather for every forecast
          member; AquaCrop grows the published outlook and WOFOST the same members for comparison; the Crop outlook tab and the
          management scenarios show the results; the hindcast, county yields and the engine comparison check them, and calibration
          against trials sets the models' parameters.</desc>
        <defs>
          <marker id="cw-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" style={{ fill: 'var(--text-meta)' }} />
          </marker>
        </defs>

        <Label x={c1} y={26} weight={600} size={13}>1  INPUTS</Label>
        <Label x={c2} y={26} weight={600} size={13}>2  CROP WEATHER</Label>
        <Label x={c3} y={26} weight={600} size={13}>3  CROP MODELS</Label>
        <Label x={c4} y={26} weight={600} size={13}>4  PRODUCTS</Label>

        {placed.map(b => <Box key={b.title} x={c1} y={b.y} w={bw} h={b.h} tone="input" title={b.title} lines={b.lines} />)}

        <Box x={c2} y={top} w={214} h={span} tone="weather" strong title="Daily weather" lines={[
          'every member, 1 Aug – 31 Mar', '', 'observed to the last day,', 'then the forecast run,', 'SEAS5 to 28 Feb, March', '',
          'ET0: the platform’s FAO-56,', 'then its climatology × the', 'member’s Penman-Monteith', 'ratio', '', 'the source of every day,', 'checked before any run']} />

        <Box x={c3} y={top} w={bw} h={half} tone="model" strong title="AquaCrop-OSPy 3.1.0" lines={['the published outlook', 'canopy and water stress', 'biomass = WP* · Tr / ET0', 'yield = biomass × HI', 'irrigation, mulch, ridges', '(in the scenarios)']} />
        <Box x={c3} y={top + half + gap} w={bw} h={half} tone="model" title="WOFOST 7.2 (PCSE)" lines={['second model, shown', 'beside AquaCrop', '(maize and sorghum)', 'light interception and', 'photosynthesis (AMAX)', 'yield = storage organs']} />

        <Box x={c4} y={top} w={220} h={half} tone="product" strong title="Crop outlook tab" lines={['per site, crop and rule:', 'yield (8 in 10 members)', 'chance of failure', 'both models side by side', 'against the observed-', 'weather crop 1993–2025']} />
        <Box x={c4} y={top + half + gap} w={220} h={half} tone="product" title="Management scenarios" lines={['the same members,', 'one choice changed:', 'sowing date, density,', 'soil water on 1 Aug,', 'irrigation, mulch,', 'tied ridges or pits']} />

        {/* flows: inputs → weather → models → products */}
        {placed.map(b => <Arrow key={b.title} d={`M${c1 + bw} ${b.y + b.h / 2} L${c2 - 4} ${top + span / 2 + (b.y + b.h / 2 - top - span / 2) * 0.35}`} />)}
        <Arrow d={`M${c2 + 214} ${top + half / 2} L${c3 - 4} ${top + half / 2}`} />
        <Arrow d={`M${c2 + 214} ${top + half + gap + half / 2} L${c3 - 4} ${top + half + gap + half / 2}`} />
        <Arrow d={`M${c3 + bw} ${top + half / 2} L${c4 - 4} ${top + half / 2}`} />
        <Arrow d={`M${c3 + bw} ${top + half - 20} L${c4 - 4} ${top + half + gap + 30}`} />
        <Arrow d={`M${c3 + bw} ${top + half + gap + 30} L${c4 - 4} ${top + half - 20}`} />

        {/* 5 verification and calibration */}
        <Label x={c1} y={band - 14} weight={600} size={13}>5  VERIFICATION AND CALIBRATION</Label>
        <Box x={c1} y={band} w={235} h={bandH} tone="check" title="Hindcast 1993–2016" lines={['1 Oct SEAS5 runs, 25 members,', 'against the observed-weather', 'crop and the season-length', 'forecast; both sowing rules']} />
        <Box x={273} y={band} w={235} h={bandH} tone="check" title="County yields" lines={['HarvestStat Short Rains', 'maize, 1993–2025: forecast,', 'observed-weather crop and', 'season length against them']} />
        <Box x={526} y={band} w={235} h={bandH} tone="check" title="Engine comparison" lines={['AquaCrop against WOFOST', 'on 1,188 observed seasons:', 'rank agreement, failure,', 'days to harvest']} />
        <Box x={779} y={band} w={241} h={bandH} tone="check" strong title="Calibration" lines={['Kiboko and Embu trials:', 'phenology, AquaCrop HI0;', 'WOFOST AMAXTB (maize: Duma', '43; sorghum: AquaCrop’s level)']} />

        <Arrow d={`M${c3 + 70} ${bottom + 4} L${c3 + 70} ${band - 4}`} />
        <Label x={c3 + 78} y={bottom + 34}>results</Label>
        <Arrow d={`M${c4 + 120} ${band} L${c4 + 120} ${bottom + 30} L${c3 + bw - 40} ${bottom + 30} L${c3 + bw - 40} ${bottom + 4}`} dashed />
        <Label x={c4 + 128} y={bottom + 48}>parameters</Label>

        <Label x={c1} y={band + bandH + 30}>
          Daily: the weather, the outlook and both sowing rules for every forecast run. Weekly: the scenarios. On demand: the verification
        </Label>
        <Label x={c1} y={band + bandH + 50}>
          and the calibration, whose parameters (dashed) go into the models. WOFOST grows the same maize and sorghum members, shown beside AquaCrop.
        </Label>
      </svg>
    </div>
  )
}
