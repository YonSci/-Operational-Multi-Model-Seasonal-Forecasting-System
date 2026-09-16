import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

"""
main.py  —  Kenya MAM Dashboard FastAPI app.
Run:    uvicorn main:app --reload --port 8000
Docs:   http://localhost:8080/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import mam_loader as dl

from kenya_api import models, pixel, grid, sites, bulletin


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n" + "=" * 60)
    print("  Kenya MAM Dashboard  -  starting up")
    print(f"  mam_loader: {dl.__file__}")
    print("=" * 60)
    dl.configure()   # uses defaults from mam_loader (BASE_DIR etc.)
    try:
        dl.load()
        print("=" * 60)
        print("  API ready  ->  http://localhost:8080/docs")
        print("=" * 60 + "\n")
    except Exception as exc:
        # Keep API alive so frontend can run; data endpoints return 503 until data is fixed.
        print("=" * 60)
        print("  API started with data loader warning")
        print(f"  {type(exc).__name__}: {exc}")
        print("  Data endpoints will return 503 until BASE_DIR points to valid outputs.")
        print("=" * 60 + "\n")
    yield
    print("Shutting down.")


app = FastAPI(
    title       = "Kenya MAM Climate Dashboard API",
    description = "REST API for Kenya MAM onset / cessation / LGP forecasts.",
    version     = "1.0.0",
    lifespan    = lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(models.router,   prefix="/models",  tags=["Models"])
app.include_router(pixel.router,    prefix="",         tags=["Pixel"])
app.include_router(grid.router,     prefix="/grid",    tags=["Grid"])
app.include_router(sites.router,    prefix="/sites",   tags=["Sites"])
app.include_router(bulletin.router, prefix="",         tags=["Bulletin"])


@app.get("/", tags=["Health"])
def root():
    return {
        "status"       : "ok",
        "models_loaded": len(dl.get_state().get("MODELS", {})) if dl.is_loaded() else 0,
        "docs"         : "/docs",
    }

@app.get("/health", tags=["Health"])
def health():
    if not dl.is_loaded():
        return {"status": "starting", "data_loaded": False}
    s = dl.get_state()
    lm = s["lm"]
    import numpy as np, warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        on_mean = round(float(np.nanmean(s["chirps_clim"]["onset"][lm])), 1)
    return {
        "status"       : "ok",
        "data_loaded"  : True,
        "models_loaded": len(s.get("MODELS", {})),
        "model_names"  : list(s.get("MODELS", {}).keys()),
        "chirps_onset_mean_doy": on_mean,
        "demo_mode"    : s.get("demo_mode", False),
        "version"      : "v1.0.6-debug",
    }

@app.get("/debug_bulletin", tags=["Health"])
def debug_bulletin():
    import traceback, tempfile, gc
    logs = []
    def log(msg):
        try:
            import resource
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            logs.append(f"{msg} [RSS: {rss/1024:.1f} MB]")
        except Exception:
            logs.append(msg)

    log("Step 0: Start")
    try:
        from bulletin_singlemodel_v1 import generate_single_model_bulletin
        log("Step 1: Imported generate_single_model_bulletin")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            log("Step 2: Created temp dir")
            png = generate_single_model_bulletin(
                "KALRO Kiboko, Makueni Farm", -2.21046, 37.719,
                model_name="ECMWF SEAS5 (Sep)",
                out_dir=tmpdir, dpi=100,
                season="short_rains", f_year=2026
            )
            log(f"Step 3: Generated PNG: {png} ({os.path.getsize(png)/1024:.1f} KB)")
            
            pdf = png.replace(".png", ".pdf")
            from kenya_api.bulletin import _png_to_pdf
            _png_to_pdf(png, pdf, "KALRO Kiboko", dpi=100)
            log(f"Step 4: Converted to PDF: {pdf} ({os.path.getsize(pdf)/1024:.1f} KB)")
            
        log("Step 5: Done")
        return {"status": "ok", "logs": logs}
    except Exception as e:
        return {"status": "error", "error": str(e), "traceback": traceback.format_exc(), "logs": logs}
