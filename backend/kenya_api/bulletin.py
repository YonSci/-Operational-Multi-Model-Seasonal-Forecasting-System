"""POST /bulletin  |  GET /export"""
import os, io, csv, tempfile, warnings
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
import mam_loader as dl

router = APIRouter()

def _find_bulletin_script():
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "bulletin_multimodel_v1.py"),
        os.path.join(os.path.dirname(__file__), "..", "..", "bulletin_multimodel_v1.py"),
        os.path.join(os.getcwd(), "backend", "bulletin_multimodel_v1.py"),
        os.path.join(os.getcwd(), "bulletin_multimodel_v1.py"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return os.path.abspath(c)
    return os.path.abspath(candidates[0])

_COMPILED_BULLETIN = None

def _get_compiled_bulletin():
    global _COMPILED_BULLETIN
    if _COMPILED_BULLETIN is not None:
        return _COMPILED_BULLETIN
    script_path = _find_bulletin_script()
    if not os.path.isfile(script_path):
        raise FileNotFoundError(f"Bulletin generator script not found at {script_path}")
    with open(script_path, encoding="utf-8") as f:
        bsrc = f.read()
    cut = len(bsrc)
    for marker in ["# BATCH RUN", "\nfor s in SITES:"]:
        pos = bsrc.find(marker)
        if pos > 0:
            cut = pos
            break
    _COMPILED_BULLETIN = compile(bsrc[:cut], script_path, "exec")
    return _COMPILED_BULLETIN

class BulletinRequest(BaseModel):
    site_name: str
    lat: float
    lon: float
    fmt: str = "png"
    bulletin_type: str = "multi"   # "multi" or "single"
    model_name: str = "ECMWF SEAS5"
    season: str = "long_rains"
    year: int = 2025

@router.post("/bulletin")
def generate_bulletin(req: BulletinRequest):
    """Generate a seasonal forecast bulletin PNG/PDF (Multi-Model or Single-Model) for the requested site."""
    if not dl.is_loaded():
        raise HTTPException(503, "Data not yet loaded.")
    site_name = req.site_name.strip() if req.site_name and req.site_name.strip() else f"Location_{req.lat:.3f}_{req.lon:.3f}"
    fmt = req.fmt.lower().strip()
    if fmt not in ("png", "pdf"):
        raise HTTPException(400, "fmt must be png or pdf")
    
    s = dl.get_state()
    is_short = (req.season == "short_rains") or ("Sep" in (req.model_name or "")) or (req.year == 2025 and req.season != "long_rains")
    btype = "single" if is_short else (req.bulletin_type.lower().strip() if req.bulletin_type else "multi")
    req_model = "ECMWF SEAS5 (Sep)" if (is_short and "ECMWF SEAS5 (Sep)" in s["MODELS"]) else (req.model_name or "ECMWF SEAS5")

    import gc
    gc.collect()

    with tempfile.TemporaryDirectory() as tmpdir:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        safe = site_name.replace(" ", "_").replace(",", "").replace("/", "-")
        safe_model = req_model.replace(" ", "_").replace(",", "").replace("/", "-").replace("(", "").replace(")", "")

        if btype == "single":
            try:
                try:
                    from bulletin_singlemodel_v1 import generate_single_model_bulletin
                except ImportError:
                    import sys
                    for p in [
                        os.path.dirname(__file__),
                        os.path.join(os.path.dirname(__file__), ".."),
                        os.path.join(os.path.dirname(__file__), "..", ".."),
                        os.getcwd(),
                    ]:
                        if p not in sys.path:
                            sys.path.insert(0, p)
                    from bulletin_singlemodel_v1 import generate_single_model_bulletin

                png_path = generate_single_model_bulletin(
                    site_name, float(req.lat), float(req.lon),
                    model_name=req_model,
                    out_dir=tmpdir, dpi=100,
                    season="short_rains" if is_short else "long_rains"
                )
                plt.close("all")
                gc.collect()
            except Exception as e:
                plt.close("all")
                import traceback
                raise HTTPException(500, f"Single-model bulletin error: {e}\n{traceback.format_exc()}")
            fname_prefix = f"bulletin_{safe_model}_{safe}"
        else:
            import matplotlib.gridspec as gridspec
            import matplotlib.patches as mpatches
            import matplotlib as mpl

            g = {
                "MODELS": s["MODELS"], "chirps_clim": s["chirps_clim"],
                "chirps_onset_doy": s["onset_doy"],
                "chirps_cessation_doy": s["cessation_doy"],
                "chirps_lgp_days": s["lgp_days"],
                "C_clim": s["C_clim"], "Q_bar": s["Q_bar"],
                "d_s": s["d_s"], "d_e": s["d_e"],
                "t33_onset": s["t33_onset"], "t67_onset": s["t67_onset"],
                "t33_cess": s["t33_cess"],   "t67_cess": s["t67_cess"],
                "t33_lgp": s["t33_lgp"],     "t67_lgp": s["t67_lgp"],
                "target_lat": s["target_lat"], "target_lon": s["target_lon"],
                "n_lat": s["n_lat"], "n_lon": s["n_lon"], "lm": s["lm"],
                "chirps_years": s["chirps_years"], "cal_idx": s["cal_idx"],
                "CAL_YEARS": dl.CAL_YEARS, "OP_YEAR": dl._OP_YEAR,
                "WIN_DOY_START": dl.WIN_DOY_START, "WIN_DOY_END": dl.WIN_DOY_END,
                "BULLETIN_DIR": tmpdir,
                "BULLETIN_DPI": 100,
                "HAS_CARTOPY": _has_cartopy(),
                "os": os, "np": np,
                "plt": plt, "gridspec": gridspec,
                "mpatches": mpatches, "mpl": mpl,
            }
            try:
                compiled = _get_compiled_bulletin()
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    exec(compiled, g)
                def _hline(ax, y, color, lw=1.0, ls="-", x0=0.0, x1=1.0):
                    ax.plot([x0,x1],[y,y],color=color,lw=lw,ls=ls,
                            transform=ax.transAxes,clip_on=False,zorder=10)
                g["_hline"] = _hline
                fn = g.get("generate_mm_bulletin")
                if fn is None:
                    raise RuntimeError("generate_mm_bulletin not found in bulletin script")
                png_path = fn(site_name, float(req.lat), float(req.lon))
                plt.close("all")
                del g
                gc.collect()
            except Exception as e:
                plt.close("all")
                import traceback
                raise HTTPException(500, f"Multi-model bulletin error: {e}\n{traceback.format_exc()}")
            fname_prefix = f"bulletin_mm_{safe}"

        out_path  = png_path
        media     = "image/png"; suffix = ".png"
        if fmt == "pdf":
            out_path = png_path.replace(".png", ".pdf")
            _png_to_pdf(png_path, out_path, site_name, dpi=100)
            media = "application/pdf"; suffix = ".pdf"

        season_tag = "OND2025" if is_short else f"MAM{dl._OP_YEAR}"
        fname = f"{fname_prefix}_{season_tag}{suffix}"
        with open(out_path, "rb") as f: content = f.read()

    gc.collect()
    return Response(
        content=content,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        }
    )


def _has_cartopy():
    try: import cartopy; return True
    except ImportError: return False

def _png_to_pdf(png_path, pdf_path, title, dpi=100):
    import gc
    gc.collect()
    from reportlab.lib.pagesizes import A3
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as _rl
    from PIL import Image as _PIL
    _PIL.MAX_IMAGE_PIXELS = None
    pw, ph = A3
    mg = 10 * mm
    with _PIL.open(png_path) as img:
        iw, ih = img.size
        scale = min((pw - 2 * mg) / (iw / dpi * 72), (ph - 2 * mg) / (ih / dpi * 72))
        dw = (iw / dpi * 72) * scale
        dh = (ih / dpi * 72) * scale
        xo = mg + ((pw - 2 * mg) - dw) / 2
        yo = mg + ((ph - 2 * mg) - dh) / 2
    c = _rl.Canvas(pdf_path, pagesize=(pw, ph))
    c.setTitle(title)
    c.setAuthor("ICPAC / ILRI Climate Services")
    c.drawImage(png_path, xo, yo, width=dw, height=dh, preserveAspectRatio=True, mask="auto")
    c.save()
    gc.collect()


@router.get("/export")
def export_csv(
    lat : float = Query(...), lon: float = Query(...),
    name: str   = Query("site"),
):
    """Download CHIRPS historical + OP-year ensemble percentiles as CSV."""
    if not dl.is_loaded():
        raise HTTPException(503, "Data not yet loaded.")

    px    = dl.get_pixel_stats(lat, lon)
    pi,pj = px["pi"], px["pj"]
    s     = dl.get_state()
    years = s["chirps_years"][s["cal_idx"]]

    model_names = list(s["MODELS"].keys())
    header = (["year","chirps_onset","chirps_cessation","chirps_lgp"]
              + [f"{n}_on_med"  for n in model_names]
              + [f"{n}_on_p10"  for n in model_names]
              + [f"{n}_on_p90"  for n in model_names]
              + [f"{n}_lgp_med" for n in model_names])

    def _fmt(v):
        if v is None: return ""
        import math
        return "" if math.isnan(float(v)) else f"{float(v):.1f}"

    rows = []
    for i, yr in enumerate(years):
        c_on  = s["onset_doy"][s["cal_idx"][i], pi, pj]
        c_cs  = s["cessation_doy"][s["cal_idx"][i], pi, pj]
        c_lgp = s["lgp_days"][s["cal_idx"][i], pi, pj]
        row   = [yr, _fmt(c_on), _fmt(c_cs), _fmt(c_lgp)]
        for col in ["on_med","on_p10","on_p90","lg_med"]:
            for n in model_names:
                row.append(_fmt(px["models"].get(n,{}).get(col)))
        rows.append(row)

    buf = io.StringIO()
    csv.writer(buf).writerows([header] + rows)
    safe  = name.replace(" ","_").replace(",","").replace("/","-")
    fname = f"climate_{safe}_MAM{dl._OP_YEAR}.csv"
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})
