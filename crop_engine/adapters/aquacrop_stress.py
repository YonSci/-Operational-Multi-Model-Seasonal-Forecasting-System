"""
Soil fertility stress, weed competition and soil salinity for AquaCrop-OSPy 3.1.0, ported from FAO AquaCrop 7.3
(KU Leuven, BSD-3; Fortran source github.com/KUL-RSDA/AquaCrop, read at commit 12328f8). AquaCrop-OSPy has none of
the three; this module adds them to its daily step by wrapping seven of its functions (install()), active only for a
model run that sets a Context (aquacrop_adapter._sow with a task's "fertility", "weeds" or "salinity").

Soil fertility stress (AquaCrop's semi-quantitative approach). A stress level SF (%) gives, through the crop's four
response shapes (KsAny, global.f90 CropStressParametersSoilFertility), reductions of the canopy growth coefficient
(RedCGC %), of the maximum canopy (RedCCX %), of water productivity (RedWP %) and a decline of the canopy during
mid-season (CDecline, % of cover per day, here per GDD: × the days per GDD of the season's own decline window). The
time to full canopy is recomputed (TimeToMaxCanopySF, capping RedCGC and RedCCX so the canopy closes by mid-flowering
or senescence). In the canopy: CGC and CCx reduced; from full canopy to senescence the cover is capped by the
stressed no-water-stress curve minus CDecline/100 × (t - L12SF)^2 / (L123 - L12SF); after senescence the decline
continues under the same cap. Water productivity: reduced by RedWP × (SumKci/SumKcTopStress)^2, SumKci the season's
running Tr/ET0, until SumKci reaches the season's unstressed Kc sum × (1 - SF/100), then by RedWP. Each day the
stress level is readjusted from the crop's biomass so far against its unstressed biomass (simul.f90 1109-1160): a
season already short of water does not lose its biomass to fertility a second time. The stress-biomass regression
this needs (preparefertilitysalinity.f90) and the season's Kc sum come from a reference season run in Python
(reference_season), soil water left out as AquaCrop's Bnormalized does, over the member's own daily GDD (AquaCrop's
GDD mode with the simulation's climate as reference). Response shapes: AquaCrop's generic crop (DEFAULT.CRO: 2.16,
0.79, 1.67, 1.67); no crop-specific calibration exists for these varieties.

Weed competition (global.f90 CCmultiplierWeed, GetWeedRC; simul.f90 DetermineBiomassAndYield). The weeds' relative
cover RC (% of the total canopy at canopy closure, changing by DeltaRC % through mid-season) expands the total
canopy: CCx, CCo and CDC × fWeed (none under fertility stress, as AquaCrop); the total canopy transpires and shades
the soil, and the crop gets the share of transpiration CCw* / CCtot* (its cover, CCtot × (1 - RC/100), in AquaCrop's
CC* form): its biomass grows from that share only.

Soil salinity. Salt (g/m2) per soil compartment, carried by OSPy's own water fluxes: irrigation water at ECw, capillary
rise from a water table at ECgw, drained water at the compartment's mixed concentration (capped at the solubility, 100
g/L), compartments below the water table set to ECgw, and AquaCrop's daily diffusion between neighbouring
compartments (its salt mobility of the compartment's wettest active cell, SaltDiff 20 %). Rain carries none. ECe and
ECsw from salt mass and water content as AquaCrop's (ECeComp, ECswComp; 0.64 g/L per dS/m). Simplified from
AquaCrop: no salt cells inside a compartment (incoming water mixes with all of it; AquaCrop's fine pores exchange
slowly, so its ECe answers each event more slowly; the long-run levels are alike), no upward transport with
evaporation. The stress, as AquaCrop's: the root zone's ECe gives KsSalt (linear from ECemin to ECemax); its running
mean over the canopy days gives the CCx reduction through the crop's salinity regression (calibrated by the
reference season, preparefertilitysalinity.f90 519-741), and from it the reductions of CGC, the canopy's decline
(CCsaltDistortion 25 %) and the stomata (RedKsSto); the soil water's ECsw closes the stomata further each day
(AdjustedKsStoToECsw, ResponseECsw 100 %), as AquaCrop 7's calculate_transpiration: a cap on the root zone's
transpiration, each compartment's own limit, and what one compartment holds back taken from the others up to the cap. Combined with fertility: the larger reduction of each, RedWP from
fertility, RedKsSto from salinity. Crop tolerance (ECemin, ECemax, dS/m): FAO Irrigation and Drainage Paper 29
(Ayers and Westcot 1985, Table 4; Maas and Hoffman 1977): the threshold ECe and the ECe at zero yield.
"""
import copy
import math

import numpy as np

EQUIV = 0.64                     # g/L of salt per dS/m
SALT_SOLUB = 100.0               # g/L
SALT_DIFF = 20.0                 # % (AquaCrop's default)
FERT_SHAPES = {"CGC": 2.16, "CCX": 0.79, "WP": 1.67, "CDecline": 1.67}     # AquaCrop's generic crop (DEFAULT.CRO)
SALT_TOLERANCE = {"MaizeGDD": (1.7, 10.0), "SorghumGDD": (6.8, 13.0), "DryBeanGDD": (1.0, 6.3)}   # FAO 29
CC_SALT_DISTORTION = 25.0
RESPONSE_ECSW = 100.0
WEED_SHAPE = -0.01               # AquaCrop's default shape of the total canopy's expansion
SF_MAX = 99
ETO_REF = 5.0
EPS = 1.19e-7


# ── AquaCrop's helpers (global.f90) ─────────────────────────────────────────────────────────────────────────────────
def ks_any(w, p_ul, p_ll, shape):
    if p_ll - p_ul < 1e-4:
        p_ul = p_ll - 1e-4
    p = (w - p_ul) / (p_ll - p_ul)
    if p <= EPS:
        return 1.0
    if p >= 1.0:
        return 0.0
    s = 0.01 if round(10 * shape) == 0 else shape
    return min(1.0, max(0.0, 1 - (math.exp(p * s) - 1) / (math.exp(s) - 1)))


def cc_at_time(t, cco, cgc, ccx):
    cc = cco * math.exp(cgc * t)
    if cc > ccx / 2:
        cc = ccx - 0.25 * (ccx / cco) * ccx * math.exp(-cgc * t)
    return max(0.0, min(cc, ccx))


def time_to_reach(cc_to_reach, cco, ccx, cgc, l0):
    """DaysToReachCCwithGivenCGC (in the crop's time unit, here GDD)."""
    if cco > cc_to_reach or cco >= ccx or cgc <= 0:
        return l0
    cc_to_reach = min(cc_to_reach, 0.98 * ccx)
    if cc_to_reach <= ccx / 2:
        L = math.log(cc_to_reach / cco) / cgc
    else:
        L = math.log((0.25 * ccx * ccx / cco) / (ccx - cc_to_reach)) / cgc
    return l0 + round(L)


def fert_params(sf, shapes=FERT_SHAPES):
    """CropStressParametersSoilFertility: stress level sf (%) → RedCGC, RedCCX, RedWP (%), CDecline (% per day)."""
    r = lambda s: 1 - ks_any(sf / 100.0, 0.0, 1.0, s)                    # noqa: E731
    return {"RedCGC": round(100 * r(shapes["CGC"])), "RedCCX": round(100 * r(shapes["CCX"])),
            "RedWP": round(100 * r(shapes["WP"])), "CDecline": r(shapes["CDecline"]), "RedKsSto": 0}


def time_to_max_canopy_sf(c, red_cgc, red_ccx, sf):
    """TimeToMaxCanopySF (GDD): the time to full canopy under the reductions, which it may lower (RedCGC) or raise
    (RedCCX) so the canopy closes by mid-flowering (determinate) or senescence → (L12SF, RedCGC, RedCCX)."""
    if sf == 0 or (red_ccx == 0 and red_cgc == 0):
        return c["MaxCanopy"], red_cgc, red_ccx

    def l12(rg, rx):
        ccx = (1 - rx / 100.0) * c["CCx"]
        return time_to_reach(0.98 * ccx, c["CC0"], ccx, c["CGC"] * (1 - rg / 100.0), c["Emergence"])
    lmax = c["HIstart"] + round(c["Flowering"] / 2) if c["Determinant"] else c["Senescence"]
    L = l12(red_cgc, red_ccx)
    while L > lmax and red_cgc > 0:
        red_cgc -= 1
        L = l12(red_cgc, red_ccx)
    while L > lmax and (1 - red_ccx / 100.0) * c["CCx"] > 0.10 and red_ccx <= 50:
        red_ccx += 1
        L = l12(red_cgc, red_ccx)
    return L, red_cgc, red_ccx


def salt_params(ccx_red, c, distortion=CC_SALT_DISTORTION):
    """CropStressParametersSoilSalinity (tempprocessing.f90): a CCx reduction (%) → RedCGC, RedCCX, RedKsSto (%) and
    CDecline (% per GDD), in GDD with AquaCrop's calendar-branch smooth start."""
    cco, ccx, cgc = c["CC0"], c["CCx"], c["CGC"]
    L12, L123 = c["MaxCanopy"], c["Senescence"]
    out = {"RedCCX": ccx_red, "RedWP": 0, "RedKsSto": ccx_red, "RedCGC": 0, "CDecline": 0.0}
    if ccx_red == 0:
        return out
    w = 1.5 ** ccx_red / 1.5 ** 10 if ccx_red < 10 else 1.0
    l12_double, l12ss_max = L12, L12
    if not (cco > 0.98 * ccx or cco >= ccx):
        l12_double = math.log((0.25 * ccx ** 2 / cco) / (ccx - 0.98 * ccx)) / cgc
        if l12_double > EPS:
            ccx_adj = 0.90 * ccx * (1 - ccx_red / 100.0)
            g = lambda L: math.log((0.25 * ccx_adj ** 2 / cco) / (ccx_adj - 0.98 * ccx_adj)) / L   # noqa: E731
            cgc_max = g(l12_double)
            l12ss_max = L12 + (L123 - L12) / 2
            if c["Determinant"] and l12ss_max > c["HIstart"] + round(c["Flowering"] / 2):
                l12ss_max = c["HIstart"] + round(c["Flowering"] / 2)
            cgc_min = g(l12ss_max) if l12ss_max > l12_double else cgc_max
            cgc_adj = cgc_max - (cgc_max - cgc_min) * w * (distortion / 100.0)
            out["RedCGC"] = max(0, round(100 * (cgc - cgc_adj) / cgc))
    ccx_adj = 0.98 * ccx * (1 - ccx_red / 100.0)
    l12ss = l12ss_max - (l12ss_max - l12_double) * (distortion / 100.0)
    if L123 > l12ss and distortion > 0:
        ccx_final = max(cco, ccx_adj - w * (0.5 * distortion / 100.0) * (ccx_adj - cco))
        out["CDecline"] = max(min(1.0, 100 * (ccx_adj - ccx_final) / (L123 - l12ss)), 0.001)
    else:
        out["CDecline"] = 0.001
    return out


def ks_salinity(ece, ecemin, ecemax):
    """KsSalinity with shape 0 (linear)."""
    if ece <= ecemin:
        return 1.0
    if ece >= ecemax:
        return 0.0
    return 1 - (ece - ecemin) / (ecemax - ecemin)


def adjusted_ks_sto(ecemin, ecemax, ece, ecsw, ecsw_fc, wrel, b, ks_in, response=RESPONSE_ECSW):
    """AdjustedKsStoToECsw: the stomata closed further by the soil water's salt."""
    if response <= 0 or wrel <= EPS:
        return ks_in
    rel = ecsw - (ecsw_fc - ece) + (response - 100) * wrel
    if ecemin < rel < ecemax:
        ss = (1 - ks_any(rel, ecemin, ecemax, 3.0)) * 100
        return float(np.clip(1 - (b[0] + b[1] * ss + b[2] * ss * ss) / 100.0, 0, ks_in))
    return 0.0 if rel >= ecemax else ks_in


def cc_multiplier_weed(rc, ccx, shape=WEED_SHAPE):
    if rc > 0 and 0.001 < ccx < 0.9999:
        if rc >= 100:
            return 1 / ccx
        f = 1 - (1 - 1 / ccx) * (math.exp(shape * rc / 100.0) - 1) / (math.exp(shape) - 1)
        return min(f, 1 / ccx)
    return 1.0


# ── the reference season (AquaCrop's Bnormalized, no soil water) ────────────────────────────────────────────────────
def stressed_cc(t, c, red_cgc, red_ccx, cdecline_g, l12sf):
    """CCiNoWaterStressSF in GDD: the canopy without water stress under the reductions (CDecline per GDD)."""
    if t < c["Emergence"] or t > c["Maturity"]:
        return 0.0
    cgc, ccx = c["CGC"] * (1 - red_cgc / 100.0), c["CCx"] * (1 - red_ccx / 100.0)
    L0, L123 = c["Emergence"], c["Senescence"]
    if t < L123:
        cc = cc_at_time(t - L0, c["CC0"], cgc, ccx)
        if t > l12sf and l12sf < L123 and cdecline_g > 0:
            cc = max(0.0, cc - (cdecline_g / 100.0) * (t - l12sf) ** 2 / (L123 - l12sf))
        return cc
    top = cc_at_time(L123 - L0, c["CC0"], cgc, ccx)
    bis = top - (cdecline_g / 100.0) * (t - l12sf) ** 2 / max(L123 - l12sf, 1e-6) if l12sf < L123 else top
    top = top - (cdecline_g / 100.0) * (L123 - l12sf) if l12sf < L123 else top
    if bis < 0 or top < 0.001:
        return 0.0
    cdc = c["CDC"] * (top + 2.29) / (c["CCx"] + 2.29)
    cc = top * (1 - 0.05 * (math.exp((t - L123) * 3.33 * cdc / (top + 2.29)) - 1))
    return max(0.0, min(cc, bis))


def days_per_gdd(cg, a, b):
    """Days per GDD over the season's window [a, b] (GDD after sowing) of the daily cumulative GDD cg."""
    if b <= a:
        return 0.0
    n = int(np.sum((cg > a) & (cg <= b)))
    return n / (b - a) if n else 0.0


def reference_season(c, cg, red, sf_kc_top=None):
    """Bnormalized over the member's days (cg: cumulative GDD after sowing per day): ETo 5, Tpot = Kcb × CC* × ETo,
    biomass Σ WP × Tpot/ETo with the fertility WP ramp (red["RedWP"]) or the salinity stomata (red["RedKsSto"])
    → (biomass, Σ Tpot/ETo)."""
    l12sf, cdec = red.get("L12SF", c["MaxCanopy"]), red["CDecline"] * days_per_gdd(cg, red.get("L12SF", c["MaxCanopy"]), c["Senescence"])
    cc = np.array([stressed_cc(t, c, red["RedCGC"], red["RedCCX"], cdec, l12sf) for t in cg])
    ccs = np.clip(1.72 * cc - cc ** 2 + 0.3 * cc ** 3, 0, 1)
    kc = c["Kcb"] * ccs * (cg <= c["Maturity"])
    skc = np.cumsum(kc)
    wp = np.where(cg >= c["HIstart"], c["WP"] * c["WPy"] / 100.0, c["WP"])
    if red.get("RedWP", 0) > 0 and sf_kc_top:
        ramp = np.where(skc < sf_kc_top, 1 - red["RedWP"] / 100.0 * (skc / sf_kc_top) ** 2, 1 - red["RedWP"] / 100.0)
        wp = wp * ramp
    wp = wp * (1 - red.get("RedKsSto", 0) / 100.0)
    return float(np.sum(wp * kc)), float(skc[-1]) if len(skc) else 0.0


def fertility_regression(c, cg):
    """The stress-biomass relationship (preparefertilitysalinity.f90 StressBiomassRelationship): stress level =
    b0 + b1 × Brel% + b2 × Brel%² over 11 levels; and the unstressed season's Kc sum."""
    base = dict(fert_params(0), L12SF=c["MaxCanopy"])
    b0, kc_top = reference_season(c, cg, base)
    bio, lev = [], []
    for sf in range(0, 101, 10):
        p = fert_params(sf)
        p["L12SF"], p["RedCGC"], p["RedCCX"] = time_to_max_canopy_sf(c, p["RedCGC"], p["RedCCX"], sf)
        b, _ = reference_season(c, cg, p, sf_kc_top=(1 - sf / 100.0) * kc_top)
        bio.append(100 * b / b0 if b0 > 0 else 0.0)
        lev.append(sf)
    coef = np.polyfit(bio, lev, 2)
    return (float(coef[2]), float(coef[1]), float(coef[0])), kc_top


def salinity_regression(c, cg, distortion=CC_SALT_DISTORTION):
    """CCx reduction = b0 + b1 × SaltStress + b2 × SaltStress² (preparefertilitysalinity.f90 519-741)."""
    b0, _ = reference_season(c, cg, dict(fert_params(0), L12SF=c["MaxCanopy"]))
    red_l, loss = [], []
    for r in range(0, 100, 10):
        p = salt_params(r, c, distortion)
        ccx = c["CCx"] * (1 - p["RedCCX"] / 100.0)
        p["L12SF"] = time_to_reach(0.98 * ccx, c["CC0"], ccx, c["CGC"] * (1 - p["RedCGC"] / 100.0), c["Emergence"])
        b, _ = reference_season(c, cg, p)
        red_l.append(r)
        loss.append(100 - 100 * b / b0 if b0 > 0 else 100.0)
    coef = np.polyfit(loss, red_l, 2)
    return float(coef[2]), float(coef[1]), float(coef[0])


def brel_of_stress(sf, b):
    """The target relative biomass of a stress level (run.f90 3873-3892) → fraction."""
    bio_low, str_low = 100, 0.0
    while True:
        bio_top, str_top = bio_low, str_low
        bio_low -= 1
        str_low = b[0] + b[1] * bio_low + b[2] * bio_low ** 2
        if str_low >= sf or bio_low <= 0 or str_low >= 99.99:
            break
    if str_low >= 99.99:
        str_low = 100.0
    frac = bio_top if abs(str_low - str_top) < 0.001 else bio_top - (sf - str_top) / (str_low - str_top)
    return frac / 100.0


# ── salt mobility (Calculate_Saltmobility, ActiveCells) ─────────────────────────────────────────────────────────────
def salt_cells(th_s, th_fc, ksat):
    """Per compartment: number of cells SCP1, their upper limit UL, cell size Dx and mobility Mobil[1..SCP1]."""
    scp1 = 11 if ksat <= 112 else max(2, round(1.6 + 1000 / ksat))
    sc = scp1 - 1
    ul = th_s * sc / (sc + 2)
    dx = ul / sc
    mix = SALT_DIFF / 100.0
    ul_pct, macro = 100 * ul, round(100 * th_fc)
    cel_max = scp1 if macro > ul_pct else max(1, round(macro / ul_pct * sc))
    a, b = (2 * mix, 10 ** (10 * (0.5 - mix))) if mix < 0.5 else (2 * (1 - mix), 10 ** (10 * (mix - 0.5)))
    mob = np.ones(scp1 + 1)
    for i in range(1, cel_max):
        x = i / (cel_max - 1) if cel_max > 1 else 1.0
        if mix == 0:
            mob[i] = 0.0
        elif mix < 0.5:
            mob[i] = (a * b ** x - a) / (a * b - a)
        elif mix == 0.5:
            mob[i] = x
        elif mix < 1:
            mob[i] = 1 - (a * b ** (1 - x) - a) / (a * b - a)
    return scp1, ul, dx, mob


def active_cell(th, scp1, ul, dx):
    return max(1, min(scp1, math.ceil(th / dx - 1e-9))) if th <= ul else scp1


# ── a model run's state ─────────────────────────────────────────────────────────────────────────────────────────────
class Context:
    """One AquaCrop-OSPy run's settings and state (module doc). fertility: {"stress_pct"} or {"stress_pct_by_crop":
    {AquaCrop crop: level}}; weeds: {"rc_pct",
    "delta_rc_pct"}; salinity: {"ecw", "ecgw", "ece_initial"} (dS/m; ecgw with the task's water table)."""

    def __init__(self, crop_key, cg, fertility=None, weeds=None, salinity=None):
        self.crop_key, self.cg = crop_key, np.asarray(cg, float)
        fert = fertility or {}
        by_crop = fert.get("stress_pct_by_crop")                 # a calibrated level per crop (aquacrop_fertility.yaml)
        self.sf0 = int(round(float(by_crop.get(crop_key, 0) if by_crop else fert.get("stress_pct", 0))))
        self.rc = float((weeds or {}).get("rc_pct", 0.0))
        self.drc = float((weeds or {}).get("delta_rc_pct", 0.0))
        self.sal = salinity or None
        self.salt = None                         # salt per compartment (g/m2), from the season's start
        self.ready = False

    # season start (the first canopy call: the crop's parameters are final)
    def start(self, crop, prof, newcond):
        g = lambda k: float(getattr(crop, k))                                  # noqa: E731
        self.c = {k: g(k) for k in ("CGC", "CCx", "CC0", "CDC", "Emergence", "MaxCanopy", "Senescence", "Maturity",
                                    "HIstart", "Flowering", "WP", "WPy", "Kcb")}
        self.c["Determinant"] = bool(crop.Determinant)
        self.orig = {k: getattr(crop, k) for k in ("CGC", "CCx", "CC0", "CDC")}
        # weeds: total canopy (none under fertility stress, as AquaCrop)
        self.fweed = 1.0 if (self.sf0 > 0 or self.rc <= 0) else cc_multiplier_weed(self.rc, self.c["CCx"])
        self.ccx_tot, self.cco_tot = self.fweed * self.c["CCx"], self.fweed * self.c["CC0"]
        self.cdc_tot = self.c["CDC"] * (self.fweed * self.c["CCx"] + 2.29) / (self.c["CCx"] + 2.29)
        # fertility
        self.sf, self.sf_prev, self.sum_kci, self.bio_tot = self.sf0, self.sf0, 0.0, 0.0
        self.bfert, self.kc_top, self.frac = (0.0, 0.0, 0.0), 0.0, 1.0
        if self.sf0 > 0:
            self.bfert, self.kc_top = fertility_regression(self.c, self.cg)
            self.frac = brel_of_stress(self.sf0, self.bfert)
        self.kc_top_stress = self.kc_top * self.frac
        # salinity
        self.salt = None
        self.nrd, self.salt_stress_prev, self.ks_salt = 0, 0.0, 1.0
        if self.sal:
            self.ecemin, self.ecemax = SALT_TOLERANCE[self.crop_key]
            self.bsalt = salinity_regression(self.c, self.cg)
            self.cells = [salt_cells(prof.th_s[i], prof.th_fc[i], prof.Ksat[i]) for i in range(len(prof.dz))]
            ece0 = float(self.sal.get("ece_initial", 0.0))
            self.salt = np.array([ece0 * EQUIV * prof.th_s[i] * 1000 * prof.dz[i] for i in range(len(prof.dz))])
        self.red = self._reductions()
        self.ready = True

    # today's reductions
    def _reductions(self):
        f = fert_params(self.sf) if self.sf > 0 else {"RedCGC": 0, "RedCCX": 0, "RedWP": 0, "CDecline": 0.0, "RedKsSto": 0}
        s = {"RedCGC": 0, "RedCCX": 0, "CDecline": 0.0, "RedKsSto": 0}
        ss = self.salt_stress_today()
        if self.salt is not None and ss > 0.1:
            red = round(self.bsalt[0] + self.bsalt[1] * ss + self.bsalt[2] * ss * ss)
            if red >= 0:
                red = 100 if (red > 100 or ss >= 99.9) else red
                s = salt_params(int(red), self.c)
        r = {"RedWP": f["RedWP"], "RedKsSto": s["RedKsSto"], "RedCGC": max(f["RedCGC"], s["RedCGC"]),
             "RedCCX": max(f["RedCCX"], s["RedCCX"]), "CDecline": max(f["CDecline"], s["CDecline"])}
        # AquaCrop recomputes the time to full canopy for the fertility class only: with salinity alone it stays
        # the crop's (TimeToMaxCanopySF with ClassSF = StressSFadjNEW = 0)
        r["L12SF"], r["RedCGC"], r["RedCCX"] = time_to_max_canopy_sf(self.c, r["RedCGC"], r["RedCCX"], self.sf)
        r["CDecline_g"] = r["CDecline"] * days_per_gdd(self.cg, r["L12SF"], self.c["Senescence"])
        return r

    def salt_stress_today(self):
        if self.salt is None or self.nrd < 1:
            return 0.0
        return (self.nrd * self.salt_stress_prev + 100 * (1 - self.ks_salt)) / (self.nrd + 1)

    @property
    def active(self):
        return self.sf0 > 0 or self.rc > 0 or self.sal is not None

    # weeds
    def weed_rc(self, t):
        rc = self.rc
        if rc > 0 and self.drc != 0 and t > self.red["L12SF"]:
            L12, L123 = self.red["L12SF"], self.c["Senescence"]
            rc = rc * (1 + self.drc / 100.0) if t >= L123 else rc * (1 + self.drc / 100.0 * (t - L12) / (L123 - L12))
        return float(np.clip(rc, 0, 100))

    # salinity in the root zone
    def root_zone(self, prof, th, zr):
        if self.salt is None or zr <= 0:
            return None
        cum, ece, ecsw, ecsw_fc, wrel = 0.0, 0.0, 0.0, 0.0, 0.0
        for i, dz in enumerate(prof.dz):
            f = 1.0 if cum + dz <= zr else max(0.0, zr - cum) / dz
            w = f * dz / zr
            m = 1000 * dz
            ece += w * min(self.salt[i] / (m * prof.th_s[i]), SALT_SOLUB) / EQUIV
            ecsw += w * min(self.salt[i] / (m * max(th[i], 1e-6)), SALT_SOLUB) / EQUIV
            ecsw_fc += w * min(self.salt[i] / (m * prof.th_fc[i]), SALT_SOLUB) / EQUIV
            wrel += w * float(np.clip((prof.th_fc[i] - th[i]) / max(prof.th_fc[i] - prof.th_wp[i], 1e-6), 0, 1))
            cum += dz
            if cum >= zr:
                break
        return ece, ecsw, ecsw_fc, wrel


_CTX = []                       # the active Context of this process (one model run at a time)
_STEP = {}                      # per-day scratch: water before drainage, irrigation


def activate(ctx):
    _CTX.clear()
    _CTX.append(ctx)


def deactivate():
    _CTX.clear()
    _STEP.clear()


def current():
    return _CTX[0] if _CTX else None


# ── the wrappers ────────────────────────────────────────────────────────────────────────────────────────────────────
_INSTALLED = []


def install():
    """Wrap AquaCrop-OSPy's daily step (idempotent, per process). Without an active Context every wrapper is the
    original function."""
    if _INSTALLED:
        return
    import aquacrop.timestep.run_single_timestep as rst
    o = {k: getattr(rst, k) for k in ("drainage", "irrigation", "capillary_rise", "canopy_cover", "transpiration",
                                       "groundwater_inflow", "biomass_accumulation")}

    def drainage(prof, th, th_fc_adj):
        x = current()
        if x is not None and x.ready and x.salt is not None:
            _STEP["th_pre"] = np.array(th, float).copy()
        return o["drainage"](prof, th, th_fc_adj)

    def irrigation(*a, **k):
        out = o["irrigation"](*a, **k)
        x = current()
        if x is not None and x.salt is not None:
            _STEP["irr"] = float(out[-1])
        return out

    def capillary_rise(prof, n_layer, fshape_cr, newcond, flux_out, wt):
        x = current()
        if x is None or not x.ready or x.salt is None:
            return o["capillary_rise"](prof, n_layer, fshape_cr, newcond, flux_out, wt)
        th_post = np.array(newcond.th, float).copy()
        newcond, cr = o["capillary_rise"](prof, n_layer, fshape_cr, newcond, flux_out, wt)
        _route_salt(x, prof, th_post, np.array(newcond.th, float), np.asarray(flux_out, float))
        return newcond, cr

    def canopy_cover(crop, prof, z_top, cond, gdd, et0, gs):
        x = current()
        if x is None or not gs:
            return o["canopy_cover"](crop, prof, z_top, cond, gdd, et0, gs)
        if not x.ready:
            x.start(crop, prof, cond)
        _STEP["cond"] = cond                                           # the day's state, for the biomass step
        if not x.active:
            return o["canopy_cover"](crop, prof, z_top, cond, gdd, et0, gs)
        rz = x.root_zone(prof, cond.th, float(cond.z_root))
        if rz is not None:
            x.ks_salt = ks_salinity(rz[0], x.ecemin, x.ecemax)
        x.red = x._reductions()
        ns = copy.copy(cond)
        o["canopy_cover"](crop, prof, z_top, ns, gdd, et0, gs)        # no stress: the potential canopy
        r, c = x.red, x.c
        ccx_sf = x.ccx_tot * (1 - r["RedCCX"] / 100.0)
        t = float(cond.gdd_cum - cond.delayed_gdds)
        L12, L123 = r["L12SF"], c["Senescence"]
        if t >= L123 and L12 < L123:
            cond.ccx_act = min(cond.ccx_act, max(0.0, ccx_sf - r["CDecline_g"] / 100.0 * (L123 - L12)))
        crop.CGC = x.orig["CGC"] * (1 - r["RedCGC"] / 100.0)
        crop.CCx, crop.CC0 = ccx_sf, x.cco_tot
        crop.CDC = x.cdc_tot * (ccx_sf + 2.29) / (x.ccx_tot + 2.29)
        try:
            cond = o["canopy_cover"](crop, prof, z_top, cond, gdd, et0, gs)
        finally:
            for k, v in x.orig.items():
                setattr(crop, k, v)
        if c["Emergence"] <= t and L12 < L123 and t > L12:
            if t < L123:
                cap = stressed_cc(t, dict(c, CCx=x.ccx_tot, CC0=x.cco_tot, CDC=x.cdc_tot), r["RedCGC"], r["RedCCX"],
                                  r["CDecline_g"], L12)
                cond.canopy_cover = min(cond.canopy_cover, cap)
            else:
                bis = ccx_sf - r["CDecline_g"] / 100.0 * (t - L12) ** 2 / (L123 - L12)
                cond.canopy_cover = 0.0 if bis < 0 else min(cond.canopy_cover, bis)
            if round(1000 * cond.canopy_cover) <= 0 and cond.canopy_cover_ns > 0 and t > c["Emergence"]:
                cond.canopy_cover, cond.crop_dead = 0.0, True
        cc = cond.canopy_cover
        cond.canopy_cover_adj = max(0.0, 1.72 * cc - cc ** 2 + 0.3 * cc ** 3)
        for k in ("canopy_cover_ns", "ccx_act_ns", "ccx_w_ns"):
            if hasattr(ns, k):
                setattr(cond, k, getattr(ns, k))
        return cond

    def transpiration(prof, n_comp, z_top, crop, irr_method, net_irr_smt, cond, et0, co2, gs, gdd):
        th0 = np.array(cond.th, float).copy()
        tr, tr_ns, tr_pot, cond, irr_net = o["transpiration"](prof, n_comp, z_top, crop, irr_method, net_irr_smt,
                                                              cond, et0, co2, gs, gdd)
        x = current()
        if x is None or not x.ready or x.salt is None or tr <= 0 or irr_method == 4:
            return tr, tr_ns, tr_pot, cond, irr_net
        rz = x.root_zone(prof, th0, float(cond.z_root))
        if rz is None:
            return tr, tr_ns, tr_pot, cond, irr_net
        # 1. the root zone's cap (AquaCrop's TpotMAX = RedFactECsw × Tpot): the stomata of the whole root zone
        ks_w = min(1.0, tr / tr_pot) if tr_pot > 0 else 1.0
        sto = 1 - x.red["RedKsSto"] / 100.0
        osm = adjusted_ks_sto(x.ecemin, x.ecemax, rz[0], rz[1], rz[2], rz[3], x.bsalt, ks_in=1.0)
        cap = tr * min(1.0, sto, osm / max(ks_w, 1e-6))
        # 2. each compartment's own limit (AquaCrop's alfa: AdjustedKsStoToECsw of the compartment's ECe and ECsw, on
        # its water-stress Ks × (1 - RedKsSto)): its extraction × alfa / Ks, Ks as AquaCrop-OSPy's KsComp
        took = np.maximum(th0 - np.array(cond.th, float), 0.0)
        m = 1000 * np.asarray(prof.dz, float)
        f_comp = np.ones(len(took))
        for i in np.nonzero(took > 0)[0]:
            ks = _ks_comp(crop, prof, th0, i, et0)
            if ks <= 0:
                continue
            ece = min(x.salt[i] / (m[i] * prof.th_s[i]), SALT_SOLUB) / EQUIV
            ecsw = min(x.salt[i] / (m[i] * max(th0[i], 1e-6)), SALT_SOLUB) / EQUIV
            ecsw_fc = min(x.salt[i] / (m[i] * prof.th_fc[i]), SALT_SOLUB) / EQUIV
            wrel = float(np.clip((prof.th_fc[i] - th0[i]) / max(prof.th_fc[i] - prof.th_wp[i], 1e-6), 0, 1))
            alfa = adjusted_ks_sto(x.ecemin, x.ecemax, ece, ecsw, ecsw_fc, wrel, x.bsalt, ks_in=sto * ks)
            f_comp[i] = min(1.0, alfa / ks)
        # 3. AquaCrop's redistribution: what one compartment's stomata hold back is taken from the others, up to the
        # root zone's cap: the cap's water shared out by the compartments' salt-limited extraction, each at most its
        # water above the wilting point
        weight = took * f_comp * m
        target = min(cap, tr)
        if weight.sum() <= 0 or took.sum() <= 0 or target >= tr - 1e-9 and np.all(f_comp >= 1):
            return tr, tr_ns, tr_pot, cond, irr_net
        avail = np.maximum(th0 - np.asarray(prof.th_wp, float), 0.0) * m
        new = np.zeros(len(took))
        left, open_ = target, weight > 0
        for _ in range(len(took)):
            if left <= 1e-9 or not open_.any():
                break
            share = left * weight * open_ / float(np.sum(weight * open_))
            add = np.minimum(share, avail - new)
            new += add
            left -= float(add.sum())
            open_ = open_ & (avail - new > 1e-9)
        cond.th = th0 - new / m                                     # every compartment's water as AquaCrop leaves it
        tr = float(new.sum())
        return tr, tr_ns, tr_pot, cond, irr_net

    def groundwater_inflow(prof, cond):
        cond, gw_in = o["groundwater_inflow"](prof, cond)
        x = current()
        if x is not None and x.ready and x.salt is not None and getattr(cond, "wt_in_soil", False):
            ecgw = float(x.sal.get("ecgw", 0.0))
            for i in range(len(prof.dz)):
                if prof.zMid[i] >= float(cond.z_gw):
                    x.salt[i] = ecgw * EQUIV * prof.th_s[i] * 1000 * prof.dz[i]
        return cond, gw_in

    def biomass_accumulation(crop, dap, delayed_cds, hi_ref, pct_lag, b, b_ns, tr, tr_pot_ns, et0, gs):
        b1, b1_ns = o["biomass_accumulation"](crop, dap, delayed_cds, hi_ref, pct_lag, b, b_ns, tr, tr_pot_ns, et0, gs)
        x = current()
        if x is None or not x.ready or not x.active or not gs:
            return b1, b1_ns
        cond = _STEP.get("cond")
        db = b1 - b
        f_wp = 1.0
        rwp = x.red["RedWP"]
        if et0 > 0:
            if rwp > 0 and x.kc_top_stress > 0:
                if x.sum_kci / x.kc_top_stress < 1 - EPS:
                    x.sum_kci += tr / et0
                    if x.sum_kci > 0:
                        f_wp = 1 - rwp / 100.0 * (x.sum_kci / x.kc_top_stress) ** 2
                else:
                    f_wp = 1 - rwp / 100.0
            else:
                x.sum_kci += tr / et0
        f_crop = 1.0
        if cond is not None and x.rc > 0 and round(cond.canopy_cover * 10000) > 0:
            cc = cond.canopy_cover
            rc = x.weed_rc(float(cond.gdd_cum - cond.delayed_gdds))
            ccw = cc * (1 - rc / 100.0)
            star = float(np.clip(1.72 * cc - cc ** 2 + 0.3 * cc ** 3, 0, 1))
            wstar = ccw + (star - cc) if ccw > 0.0001 else 0.0
            f_crop = 0.0 if star <= 0.0001 else wstar / star
        x.bio_tot += db * max(f_wp, 0.0)
        out = b + db * max(f_wp, 0.0) * f_crop
        if cond is not None:
            _after_day(x, cond, b1_ns)
        return out, b1_ns

    rst.drainage, rst.irrigation, rst.capillary_rise = drainage, irrigation, capillary_rise
    rst.canopy_cover, rst.transpiration = canopy_cover, transpiration
    rst.groundwater_inflow, rst.biomass_accumulation = groundwater_inflow, biomass_accumulation
    _INSTALLED.append(o)


def _ks_comp(crop, prof, th, i, et0):
    """AquaCrop-OSPy's stomatal water-stress coefficient of compartment i (transpiration.py's KsComp)."""
    p_up = crop.p_up[1]
    if crop.ETadj == 1:
        p_up = p_up + (0.04 * (5 - et0)) * (np.log10(10 - 9 * p_up))
    taw = prof.th_fc[i] - prof.th_wp[i]
    if th[i] >= prof.th_fc[i] - taw * p_up:
        return 1.0
    if th[i] <= prof.th_wp[i]:
        return 0.0
    wrel = (prof.th_fc[i] - th[i]) / taw
    prel = (wrel - crop.p_up[1]) / (crop.p_lo[1] - crop.p_up[1])
    if prel <= 0:
        return 1.0
    if prel >= 1:
        return 0.0
    s = crop.fshape_w[1]
    return float(np.clip(1 - (np.exp(prel * s) - 1) / (np.exp(s) - 1), 0, 1))


def _route_salt(x, prof, th_post, th_cr, flux_out):
    """The day's salt transport (module doc): irrigation salt into the top, drainage at the mixed concentration,
    capillary rise's salt, diffusion between neighbours."""
    th_pre = _STEP.pop("th_pre", th_post)
    irr = _STEP.pop("irr", 0.0)
    m = 1000 * np.asarray(prof.dz, float)
    w_pre, w_post = th_pre * m, th_post * m
    s_in = EQUIV * float(x.sal.get("ecw", 0.0)) * irr
    for i in range(len(m)):
        w_in = max(0.0, w_post[i] - w_pre[i] + flux_out[i])
        conc = min((x.salt[i] + s_in) / max(w_pre[i] + w_in, 1e-6), SALT_SOLUB)
        s_out = min(flux_out[i] * conc, x.salt[i] + s_in)
        x.salt[i] = x.salt[i] + s_in - s_out
        s_in = s_out
    cr = np.maximum(th_cr - th_post, 0.0) * m
    x.salt += EQUIV * float(x.sal.get("ecgw", 0.0)) * cr
    th = th_cr
    for i in range(len(m) - 1):                                   # diffusion between neighbours (AquaCrop's step 5)
        sm = []
        for k in (i, i + 1):
            scp1, ul, dx, mob = x.cells[k]
            sm.append(mob[active_cell(th[k], scp1, ul, dx)] / 4.0)
        mm1, mm2 = th[i] * m[i], th[i + 1] * m[i + 1]
        if mm1 <= 0 or mm2 <= 0:
            continue
        e1, e2 = x.salt[i] / (mm1 * EQUIV), x.salt[i + 1] / (mm2 * EQUIV)
        emix = (e1 * mm1 + e2 * mm2) / (mm1 + mm2)
        ds = min(abs((emix - e1) * sm[0] * mm1 * EQUIV), abs((emix - e2) * sm[1] * mm2 * EQUIV))
        if e1 > e2:
            ds = min(ds, x.salt[i])
            x.salt[i] -= ds
            x.salt[i + 1] += ds
        elif e2 > e1:
            ds = min(ds, x.salt[i + 1])
            x.salt[i + 1] -= ds
            x.salt[i] += ds


def _after_day(x, cond, b_unlim):
    """End of day: the salinity stress's running mean, the fertility stress readjusted (module doc)."""
    if x.salt is not None:
        if cond.canopy_cover > 0:
            x.salt_stress_prev = x.salt_stress_today()
            x.nrd += 1
    if x.sf0 > 0 and b_unlim > 0.001:
        bio_adj = 100 * (x.frac + (x.frac - x.bio_tot / b_unlim))
        if bio_adj >= 100:
            s = 0
        elif bio_adj <= EPS:
            s = SF_MAX
        else:
            s = round(x.bfert[0] + x.bfert[1] * bio_adj + x.bfert[2] * bio_adj ** 2)
            if s < 0:
                s = x.sf0
            s = min(s, SF_MAX)
        s = min(s, x.sf0)
        t = float(cond.gdd_cum - cond.delayed_gdds)
        if x.c["Determinant"] and t > x.c["HIstart"] + round(x.c["Flowering"] / 2):
            s = min(max(s, x.sf_prev), x.sf0)
        x.sf_prev = x.sf = int(s)
        x.kc_top_stress = (1 - x.sf / 100.0) * x.kc_top
