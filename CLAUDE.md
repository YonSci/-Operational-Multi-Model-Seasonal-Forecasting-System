# Kenya MAM v3.0.0 — Claude Code Configuration

## Project Overview

Operational probabilistic MAM (March–April–May) onset / cessation / LGP forecasting
system for Kenya. Full-stack: React 18 + Vite 8 (OXC parser) frontend + FastAPI backend.

**Owner:** Yonas Mersha (ILRI Climate Services) · y.mersha@cgiar.org
**Project Lead:** Dr. Teferi Demissie · t.demissie@cgiar.org
**Version:** v3.0.0 · April 2026

---

## Directory Structure

```
onset-kenya/
├── CLAUDE.md                    ← you are here
├── .claude/settings.json        ← Claude Code permissions
├── .env                         ← copy from docker/.env.example (not committed)
├── vercel.json                  ← Vercel SPA + /api proxy config
├── skill_weighted_ensemble.py   ← Stage 8 notebook cells for skill weighting
│
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── index.html
│   └── src/
│       ├── App.jsx              ← ALL tab components (1500+ lines)
│       ├── main.jsx
│       ├── index.css            ← CSS variables (dark + light mode)
│       ├── api/queries.js       ← TanStack Query hooks
│       ├── store/useDashboardStore.js
│       └── components/
│           └── MapPanel.jsx     ← Map + 5 tab-specific layer systems (800 lines)
│
├── backend/
│   ├── main.py                  ← FastAPI app
│   ├── mam_loader.py            ← All data loading (620 lines)
│   ├── requirements.txt
│   └── kenya_api/
│       ├── __init__.py
│       ├── grid.py              ← GET /grid (MUST match mam_loader valid_layers)
│       ├── pixel.py             ← GET /pixel /chirps /taylor /chirps_historical /validation
│       ├── models.py            ← GET /models
│       ├── sites.py             ← GET /sites
│       └── bulletin.py          ← GET /bulletin
│
└── docker/
    ├── Dockerfile.backend
    ├── Dockerfile.frontend
    ├── Dockerfile.huggingface   ← Single container for HF Spaces (port 7860)
    ├── docker-compose.yml
    ├── nginx.conf
    ├── requirements.txt
    ├── .env.example
    ├── .dockerignore
    ├── deploy.sh
    └── test_deployment.py
```

---

## Tech Stack

### Frontend
- **React 18** with JavaScript (`.jsx`)
- **Vite 8** with OXC parser (strict — see OXC Rules below)
- **Mapbox GL JS** (`mapbox-gl`) for interactive maps — token required
- **Recharts** for charts (ADPlume, PrecipPlume, HistoricalTimeSeries)
- **Zustand** for state (`selectedSite`, `activeModels`)
- **TanStack Query** for server state and caching
- **Tailwind CSS** for utility classes
- **shadcn/ui** components where needed

### Backend
- **FastAPI** + **uvicorn** — port 8765
- **xarray** + **netCDF4** + **numpy** for NetCDF data loading
- **Python 3.11**

### Deployment
- **Docker** (backend + nginx frontend)
- Free options: ngrok tunnel, Hugging Face Spaces, Vercel + ngrok

---

## Development Commands

```bash
# Install frontend dependencies
cd frontend && npm install

# Start frontend dev server (port 5173)
cd frontend && npm run dev

# Start backend dev server (port 8765)
cd backend && uvicorn main:app --reload --port 8765

# Build frontend for production
cd frontend && npm run build

# Docker: build and start
docker compose -f docker/docker-compose.yml --env-file .env up -d --build

# Docker: view backend logs
docker logs mam_backend -f

# Docker: test deployment
python docker/test_deployment.py

# Run setup from scratch
python setup.py
```

---

## CRITICAL: OXC Parser Rules

Vite 8 uses OXC (Rust-based) which is stricter than Babel. These rules apply to ALL `.jsx` and `.js` files.

### Rule 1 — NO non-ASCII characters anywhere
Box-drawing (`─ ┬`), em-dashes (`—`), en-dashes (`–`), `©`, `▾` and any Unicode > 127
are **rejected** even inside JS comments. Use ASCII only:
- `—` → `--`
- `─` → `-`
- `©` → `(c)`
- `▾` → `v`

**Scan for violations:**
```bash
python3 -c "
import sys
f = sys.argv[1]
raw = open(f,'rb').read()
bad = [(i+1,l[:60]) for i,l in enumerate(raw.split(b'\n')) if any(b>127 for b in l)]
[print(f'Line {ln}: {l}') for ln,l in bad]
print('Clean' if not bad else f'{len(bad)} violations')
" frontend/src/components/MapPanel.jsx
```

### Rule 2 — Single JSX expression inside `&&()`
```jsx
// WRONG — two siblings inside ()
{flag && (
  {/* comment */}
  {condition ? <A/> : <B/>}
)}

// CORRECT
{flag && (condition ? <A/> : <B/>)}
```

### Rule 3 — No reserved words as object shorthand keys in JSX props
```jsx
// WRONG — 'col' is reserved in some contexts
onClick={() => ({col: v})}

// CORRECT
onClick={() => ({column: v})}
```

### Rule 4 — Recharts dot and tooltip props
```jsx
// WRONG
<Line dot={<CustomDot/>}/>
<Tooltip content={({active}) => {...}}/>

// CORRECT
<Line dot={(p) => <CustomDot {...p}/>}/>
<Tooltip labelFormatter={...} formatter={...}/>
```

---

## Backend: Adding a New Grid Layer

**Both files must be updated or requests return HTTP 400:**

```python
# 1. mam_loader.py — add to valid-layer check AND add elif block
if layer not in ("anomaly", "spread", ..., "your_new_layer"):
    raise ValueError(...)

elif layer == "your_new_layer":
    out   = np.where(lm, computed_values, np.nan).astype(np.float32)
    units = "description"

# 2. grid.py — add to valid_layers set (separate from mam_loader)
valid_layers = {"anomaly", "spread", ..., "your_new_layer"}
```

### Current valid layers (16)
`anomaly` `spread` `median` `prob_bn` `prob_nn` `prob_an` `failure`
`chirps_p50` `chirps_spread` `bias` `detection_rate`
`rpss_val` `hitrate_val` `alpha` `hr_weighted` `rpss_weighted`

---

## MapPanel: Tab-Specific Layer Arrays

| Tab | Array | Default layer | Dropdown layout |
|---|---|---|---|
| `forecast` | `LAYERS` | `onset_anom` | 3×5 grid |
| `probabilistic` | `PROB_LAYERS` | `p_onset_bn` | 3×3 + failure row |
| `multimodel` | `MULTI_LAYERS` | `onset_med` | 3×3 grid |
| `validation` | `VAL_LAYERS` | `v_rpss_onset` | 3×3 grid |
| `historical` | `HIST_LAYERS` | `h_onset_p50` | 3×4 grid |

**When adding a new layer:** update CS colour scale object, layer array, and if new backend layer — update both `mam_loader.py` AND `grid.py`.

**Map overlay pattern** (prevents `overflow:hidden` from clipping absolute children):
```jsx
<div style={{position:'relative', overflow:'hidden'}}>   // outer
  <div ref={mapContainer}/>                              // canvas
  <div style={{position:'absolute', inset:0,             // overlay wrapper
               zIndex:20, pointerEvents:'none'}}>
    <div style={{position:'absolute', top:8, left:8,     // layer picker
                 pointerEvents:'auto'}}>...</div>
    <div style={{position:'absolute', bottom:8, right:8, // legend
                 pointerEvents:'auto'}}>...</div>
  </div>
</div>
```

---

## Skill-Weighted Ensemble

```js
// safeNum — handles both null/undefined AND NaN (unlike ?? which only handles null/undefined)
const safeNum = (v, fallback=0) => (v == null || isNaN(v)) ? fallback : v

// HR weights
const hrRaw = safeNum(ms.hr_on, 1/3) + safeNum(ms.hr_cs, 1/3) + safeNum(ms.hr_lgp, 1/3)

// RPSS weights (clip negatives to 0)
const rpssRaw = Math.max(0, safeNum(ms.rpss_on, 0)) + ...
```

If all weights show 13% (equal) — `hitrate_cal` / `rpss_val` NetCDF files are missing.
Check: `outputs_{model}_v3/hitrate_cal_onset.nc` and `rpss_val_onset.nc`

---

## Environment Variables

| Variable | File | Required | Default |
|---|---|---|---|
| `VITE_MAPBOX_TOKEN` | `frontend/.env` | Yes | — |
| `DATA_DIR` | `.env` | Yes | — |
| `OP_YEAR` | `.env` | No | 2026 |
| `LOAD_BC_DAILY` | `.env` | No | 1 |
| `BASE_DIR` | Docker env | Yes (Docker) | reads from DATA_DIR |

**`LOAD_BC_DAILY=0`** skips bc_daily loading — drops RAM from 4-8 GB to ~500 MB
but disables the A(D) Plume chart (Forecasting and Multi-Model tabs).

---

## CSS Variables

Always use CSS variables — never hardcode colours. Light/dark mode switches via `html.light` class toggle.

| Variable | Purpose |
|---|---|
| `--bg-base` | Page background |
| `--bg-surface` | Cards |
| `--bg-elevated` | Dropdown headers |
| `--accent-blue` | Primary interactive |
| `--text-primary` `--text-secondary` `--text-muted` `--text-faint` | Text hierarchy |
| `--border-primary` | Card borders |
| `--gauge-track` | Progress bar background |
| `--chart-grid` `--chart-axis` `--chart-tooltip-bg` | Recharts elements |

---

## Known Bugs & Fixes

See `SKILL.md` references/bugs.md for full list. Critical ones:

1. **NaN ?? fallback** → use `safeNum(v, fb)` — `??` doesn't catch NaN
2. **Both layer whitelists** → always update `grid.py` AND `mam_loader.py`
3. **configure() env vars** → defaults evaluated at call time, not import time
4. **OXC non-ASCII** → scan all JSX/JS files before committing
5. **overflow:hidden clips legend** → use inset:0 overlay wrapper pattern

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Status + model count |
| GET | `/models` | All loaded models metadata |
| GET | `/grid` | GeoJSON spatial map layer |
| GET | `/pixel` | Full pixel stats (all models) |
| GET | `/chirps` | CHIRPS climatological curve |
| GET | `/chirps_historical` | CHIRPS time series + trend |
| GET | `/taylor` | Taylor diagram stats |
| GET | `/validation` | Domain-mean probs per VAL year |
| GET | `/sites` | Monitoring site locations |
| GET | `/bulletin` | Trigger bulletin generation |

---

## Data Directory Structure

```
DATA_DIR/  (mounted at /data in Docker)
├── outputs_ECMWF_SEAS5_v3/
│   ├── onset_doy.nc
│   ├── cessation_doy.nc
│   ├── lgp_days.nc
│   ├── bc_daily_all.nc          ← large, set LOAD_BC_DAILY=0 to skip
│   ├── probs_damped_onset.nc
│   ├── hitrate_cal_onset.nc     ← needed for HR-weighted ensemble
│   ├── rpss_val_onset.nc        ← needed for RPSS-weighted ensemble
│   └── alpha_onset.nc
├── outputs_UKMO_GloSea6_v3/     ← same structure for all 8 models
├── outputs_Meteo-France_Sys8_v3/
├── outputs_DWD_GCFS2.1_v3/
├── outputs_CMCC-SPS4_v3/
├── outputs_NCEP_CFSv2_v3/
├── outputs_ECCC_CanSIPS_v3/
├── outputs_BOM_ACCESS-S2_v3/
└── CHIRPS/                      ← CHIRPS v2.0 observations
```
