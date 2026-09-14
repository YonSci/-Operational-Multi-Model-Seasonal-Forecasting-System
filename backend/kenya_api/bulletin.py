"""POST /bulletin  |  GET /export"""
import os, io, csv, tempfile, warnings
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
import mam_loader as dl

router = APIRouter()

_BULLETIN_SCRIPT = os.path.join(
    os.path.dirname(__file__), "..", "..", "bulletin_multimodel_v1.py"
)

class BulletinRequest(BaseModel):
    site_name: str; lat: float; lon: float; fmt: str = "png"

@router.post("/bulletin")
def generate_bulletin(req: BulletinRequest):
    """Generate a multi-model bulletin PNG/PDF for the requested site."""
    if not dl.is_loaded():
        raise HTTPException(503, "Data not yet loaded.")
    site_name = req.site_name.strip() if req.site_name and req.site_name.strip() else f"Location_{req.lat:.3f}_{req.lon:.3f}"
    fmt = req.fmt.lower().strip()
    if fmt not in ("png", "pdf"):
        raise HTTPException(400, "fmt must be png or pdf")

    s = dl.get_state()

    with tempfile.TemporaryDirectory() as tmpdir:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
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
            "HAS_CARTOPY": _has_cartopy(),
            "os": os, "np": np,
            "plt": plt, "gridspec": gridspec,
            "mpatches": mpatches, "mpl": mpl,
        }
        try:
            with open(_BULLETIN_SCRIPT, encoding="utf-8") as f: bsrc = f.read()
            cut = len(bsrc)
            for marker in ["# BATCH RUN", "\nfor s in SITES:"]:
                pos = bsrc.find(marker)
                if pos > 0: cut = pos; break
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                exec(compile(bsrc[:cut], _BULLETIN_SCRIPT, "exec"), g)
            def _hline(ax, y, color, lw=1.0, ls="-", x0=0.0, x1=1.0):
                ax.plot([x0,x1],[y,y],color=color,lw=lw,ls=ls,
                        transform=ax.transAxes,clip_on=False,zorder=10)
            g["_hline"] = _hline
            fn = g.get("generate_mm_bulletin")
            if fn is None:
                raise RuntimeError("generate_mm_bulletin not found in bulletin script")
            png_path = fn(site_name, float(req.lat), float(req.lon))
        except Exception as e:
            import traceback
            raise HTTPException(500, f"Bulletin error: {e}\n{traceback.format_exc()}")

        out_path  = png_path
        media     = "image/png"; suffix = ".png"
        if fmt == "pdf":
            out_path = png_path.replace(".png",".pdf")
            _png_to_pdf(png_path, out_path, site_name)
            media = "application/pdf"; suffix = ".pdf"

        safe = site_name.replace(" ","_").replace(",","").replace("/","-")
        fname = f"bulletin_mm_{safe}_MAM{dl._OP_YEAR}{suffix}"
        with open(out_path,"rb") as f: content = f.read()

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

def _png_to_pdf(png_path, pdf_path, title):
    from reportlab.lib.pagesizes import A3
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as _rl
    from PIL import Image as _PIL
    _PIL.MAX_IMAGE_PIXELS = None
    pw,ph=A3; mg=10*mm
    img=_PIL.open(png_path); iw,ih=img.size
    scale=min((pw-2*mg)/(iw/150*72),(ph-2*mg)/(ih/150*72))
    dw=iw/150*72*scale; dh=ih/150*72*scale
    xo=mg+((pw-2*mg)-dw)/2; yo=mg+((ph-2*mg)-dh)/2
    c=_rl.Canvas(pdf_path,pagesize=(pw,ph))
    c.setTitle(title); c.setAuthor("ICPAC / ILRI Climate Services")
    c.drawImage(png_path,xo,yo,width=dw,height=dh,preserveAspectRatio=True,mask="auto")
    c.save()


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
