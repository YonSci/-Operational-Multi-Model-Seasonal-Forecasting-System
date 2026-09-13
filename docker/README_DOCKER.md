# Kenya MAM Dashboard — Docker Deployment

## Prerequisites
- Docker Desktop (Windows/Mac) or Docker Engine + Compose plugin (Linux)
- Mapbox account and public token
- Pipeline output directory with NetCDF files

## Project layout expected by Docker

```
onset-kenya/
├── backend/             ← FastAPI source (from this repo)
│   ├── main.py
│   ├── mam_loader.py
│   ├── kenya_api/
│   └── requirements.txt  ← copy from docker/requirements.txt
├── frontend/            ← React source
│   ├── src/
│   ├── public/
│   ├── package.json
│   └── vite.config.js
├── docker/
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   ├── nginx.conf
│   ├── docker-compose.yml
│   ├── .env.example
│   └── requirements.txt
└── outputs_{model}_v3/  ← your pipeline data (mounted read-only)
```

## Quick start

```bash
# 1. Copy env file and fill in your values
cp docker/.env.example .env
# Edit .env: set DATA_DIR and VITE_MAPBOX_TOKEN

# 2. Build and start
docker compose -f docker/docker-compose.yml --env-file .env up -d --build

# 3. Open browser
http://localhost
```

## Environment variables (.env)

| Variable | Required | Description |
|---|---|---|
| `DATA_DIR` | Yes | Absolute path to pipeline output dir on host |
| `VITE_MAPBOX_TOKEN` | Yes | Mapbox public token for map tiles |
| `OP_YEAR` | No (default: 2026) | Operational forecast year |

## Data directory structure

The `DATA_DIR` should contain your model output folders:

```
DATA_DIR/
├── outputs_ECMWF_SEAS5_v3/
├── outputs_UKMO_GloSea6_v3/
├── outputs_Meteo-France_Sys8_v3/
├── outputs_DWD_GCFS2.1_v3/
├── outputs_CMCC-SPS4_v3/
├── outputs_NCEP_CFSv2_v3/
├── outputs_ECCC_CanSIPS_v3/
├── outputs_BOM_ACCESS-S2_v3/
└── CHIRPS/              ← CHIRPS observations
```

## Useful commands

```bash
# View backend logs
docker logs mam_backend -f

# View frontend logs  
docker logs mam_frontend -f

# Restart backend only (after updating data)
docker restart mam_backend

# Stop everything
docker compose -f docker/docker-compose.yml down

# Rebuild after code changes
docker compose -f docker/docker-compose.yml --env-file .env up -d --build
```

## Ports

| Port | Service |
|---|---|
| `80` | Dashboard (nginx, serves frontend + proxies API) |
| `8765` | FastAPI backend (direct access for debugging) |

## Performance notes

- First startup takes 60-90 seconds while the backend loads all NetCDF data into memory.
- The frontend waits for the backend health check before starting (`depends_on: service_healthy`).
- NetCDF data is mounted read-only — restart the backend container to reload new forecast data.
- The backend runs a single uvicorn worker to avoid duplicating the in-memory data cache.
