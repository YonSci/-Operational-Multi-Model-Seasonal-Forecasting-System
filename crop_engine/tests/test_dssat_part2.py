"""DSSAT part 2 (crop_engine.adapters.dssat_adapter): the irrigation methods and seasonal cap, bunds, the water table,
manure, tillage, the phosphorus tier and pest damage as written into DSSAT's files, and the nitrogen levels' extras.
python -m pytest crop_engine/tests"""
import datetime as dt

from crop_engine import run_nitrogen as rn
from crop_engine.adapters import dssat_adapter as ds
from crop_engine.calibration.dssat import LOAM

P = [dt.date(2026, 10, 20), dt.date(2026, 11, 1)]
ARGS = ("CE000001", "MZ", "KY0018", "CESOIL0001", dt.date(2026, 8, 1), P, ["W0012601", "W0012602"],
        [(30, 0.2), (200, 0.2)], 4.4, dt.date(2027, 3, 30))


def test_capped_and_scheduled_irrigation():
    cap = ds.experiment_file(*ARGS, irrigation=dict(irrigation_method=1, SMT=[30, 30, 30, 0], MaxIrrSeason=100, start_stage=2))
    assert " AVWAT IFREQ" in cap and "   100     0" in cap and " 1 MA              R     A" in cap
    assert " 1 IR             30    30   100" in cap                      # the threshold of the starting stage
    sched = ds.experiment_file(*ARGS, irrigation=dict(schedule_das=[[0, 25], [20, 30]]))
    assert " 1 MA              R     R" in sched
    assert " 1 26293 IR001    25" in sched and " 2 26305 IR001    25" in sched   # each member from its own sowing
    assert " 2 26325 IR001    30" in sched
    drip = ds.experiment_file(*ARGS, irrigation=dict(irrigation_method=5, depth=3))
    assert drip.count(" IR001     3") == 2 * ds.SCHEDULE_DAYS
    plain = ds.experiment_file(*ARGS)
    assert "AVWAT" not in plain and "*IRRIGATION AND WATER MANAGEMENT" not in plain


def test_bunds_and_the_water_table():
    b = ds.experiment_file(*ARGS, bund_mm=100)
    assert " 1 26213 IR009   100" in b and " 1 MA              R     R" in b
    wt = ds.water_table_spec({"monthly_m": {8: 3.0, 12: 1.5}}, dt.date(2026, 8, 1), dt.date(2027, 3, 30))
    assert wt["initial_cm"] == 300 and (dt.date(2026, 12, 15), 150.0) in wt["ops"]
    txt = ds.experiment_file(*ARGS, water_table=wt)
    assert "   300" in txt.split("@C  ICBL")[0] and "IR007   150" in txt


def test_manure_tillage_phosphorus_and_pests():
    nit = {"rate_kg_ha": 0, "manure_t_ha": 2.5, "manure_n_pct": 2.0, "manure_p_pct": 0.36, "tillage": True,
           "soil_p_mg_kg": 4}
    txt = ds.experiment_file(*ARGS, nitrogen=nit)
    assert " 1 26293 RE003  2500  2.00  0.36" in txt and " 2 26305 TI003    15" in txt
    assert " 1 OP              Y     Y     N     Y     N     N     N     Y" in txt     # PHOSP and TILL on
    assert " 1 MA              R     N     N     R" in txt                              # manure on reported dates
    sol = ds.soil_file("CESOIL0001", -2.2, 37.7, LOAM, 150, nitrogen=True, soil_p_mg_kg=4)
    assert "IB001 SA001 IB001" in sol and "@  SLB  SLPX  SLKE" in sol
    assert "   4.0   -99" in sol and "   2.0   -99" in sol                              # half below 30 cm
    t = ds.pest_file("CE000001", "MZ", P, {"total_pct": 20, "days": 21, "from_das": 21})
    assert "@TRNO  DATE  PLAD" in t and "    1 26314  1.06" in t and "    2 26326  1.06" in t


def test_nitrogen_levels_carry_their_extras():
    levels, split, reported, _ = rn.settings()
    assert {"fym", "n25_low_p", "n25_p_mean", "n25_plough"} <= set(levels)
    t = {"variety": {"aquacrop_crop": "MaizeGDD"}}
    lv = rn.with_nitrogen(t, "x", levels["fym"], split)["nitrogen"]
    assert lv["manure_t_ha"] == 2.5 and lv["rate_kg_ha"] == 0
    assert rn.grows({"crops": ["MaizeGDD"]}, {"aquacrop_crop": "MaizeGDD"})
    assert not rn.grows({"crops": ["MaizeGDD"]}, {"aquacrop_crop": "DryBeanGDD"})
    # every site has its farmers' practice from the surveys, as its "reported" level
    assert set(reported) == {"kalro_kiboko_makueni_farm", "kapiti_research_station_farm", "el_karama_sahiwals_farm",
                             "livemo_ltd_memerush_kajiado", "genco_ltd_maralal_samburu_farm", "genco_ltd_tana_river_farm"}
    assert rn.site_levels("livemo_ltd_memerush_kajiado", levels, reported)["reported"]["rate_kg_ha"] == 0
