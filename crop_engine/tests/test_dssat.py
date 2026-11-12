"""The DSSAT adapter's file writers and output readers (adapters/dssat_adapter.py), without running DSSAT."""
import datetime as dt
import hashlib
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from crop_engine.adapters import dssat_adapter as ds
from crop_engine.data.soil import Layer

REF = Path(__file__).resolve().parent / "reference"

LAYERS = [Layer(0, 5, 45, 25, 2.0, 5, 0.28, 0.14), Layer(5, 15, 44, 26, 1.8, 5, 0.28, 0.14),
          Layer(15, 30, 42, 28, 1.5, 6, 0.29, 0.15), Layer(30, 60, 40, 30, 1.0, 6, 0.30, 0.16),
          Layer(60, 100, 40, 32, 0.8, 8, 0.31, 0.17), Layer(100, 200, 40, 33, 0.6, 8, 0.31, 0.18)]


def _col(header, name):
    """The 0-based index of the last character of a column name in a DSSAT header line."""
    return header.index(name) + len(name) - 1


def test_weather_file_columns_and_units():
    dates = pd.date_range("2026-12-30", periods=4)
    txt = ds.weather_file("W0012602", -2.21, 37.72, 975, dates, [0, 12.5, 0, 3], [30, 31, 29, 28], [17, 18, 19, 30],
                          [22, 20, 21, 19], [16.0, 17.0, 18.0, 19.0], [2.0, 1.5, 1.0, 3.0])
    lines = txt.splitlines()
    head = next(ln for ln in lines if ln.startswith("@DATE"))
    rows = lines[lines.index(head) + 1:]
    assert [r[:5] for r in rows] == ["26364", "26365", "27001", "27002"]       # YYDDD across the new year
    r = rows[1]
    for name, val in (("SRAD", "20.0"), ("RAIN", "12.5"), ("WIND", "130"), ("VAPR", "1.70")):
        assert r[:_col(head, name) + 1].split()[-1] == val                     # right-aligned under its name
    assert rows[3][:_col(head, "TMIN") + 1].split()[-1] == "28.0"             # Tmin above Tmax: clipped to it
    st = lines[lines.index("@ INSI      LAT     LONG  ELEV   TAV   AMP REFHT WNDHT") + 1]
    assert st.split()[0] == "W001" and st.split()[1] == "-2.210"


def test_station_name_is_the_weather_file_naming():
    assert ds.station(7, pd.date_range("2026-08-01", "2027-03-31")) == "W0072602"


def test_soil_file_layers_and_roots():
    txt = ds.soil_file("CESOIL0001", -2.21, 37.72, LAYERS, root_depth_cm=150)
    lines = txt.splitlines()
    assert lines[2].startswith("*CESOIL0001  ")
    head = next(ln for ln in lines if ln.startswith("@  SLB"))
    rows = lines[lines.index(head) + 1:]
    assert len(rows) == 7                                                   # 100–200 cm split at the rooting depth
    get = lambda r, n: r[:_col(head, n) + 1].split()[-1]                      # noqa: E731
    assert [get(r, "SLB") for r in rows] == ["5", "15", "30", "60", "100", "150", "200"]
    assert get(rows[0], "SLLL") == "0.140" and get(rows[0], "SDUL") == "0.280"
    assert get(rows[0], "SRGF") == "1.000" and get(rows[6], "SRGF") == "0.000"   # below the 1.5 m rooting depth
    assert 0 < float(get(rows[3], "SRGF")) < 1
    assert all(float(get(r, "SSAT")) > float(get(r, "SDUL")) for r in rows)
    assert get(rows[0], "SLOC") == f"{2.0 / 1.724:.2f}"


def test_experiment_file_one_treatment_per_member():
    plant = [dt.date(2026, 10, 29), dt.date(2026, 11, 7)]
    txt = ds.experiment_file("CE000001", "MZ", "KY0014", "CESOIL0001", dt.date(2026, 8, 1), plant,
                             ["W0012602", "W0022602"], [(5, 0.2), (15, 0.21)], 4.4, dt.date(2027, 3, 30))
    lines = txt.splitlines()
    th = lines.index("@N R O C TNAME.................... CU FL SA IC MP MI MF MR MC MT ME MH SM")
    t2 = lines[th + 2]
    head = lines[th]
    assert t2[:_col(head, "FL") + 1].split()[-1] == "2" and t2[:_col(head, "MP") + 1].split()[-1] == "2"
    assert t2[:_col(head, "IC") + 1].split()[-1] == "1" and t2[:_col(head, "SM") + 1].split()[-1] == "1"
    fh = next(ln for ln in lines if ln.startswith("@L ID_FIELD"))
    f2 = lines[lines.index(fh) + 2]
    assert f2[12:20] == "W0022602" and "CESOIL0001" in f2
    ph = next(ln for ln in lines if ln.startswith("@P PDATE"))
    p1 = lines[lines.index(ph) + 1]
    assert p1[3:8] == "26302" and p1[:_col(ph, "PPOP") + 1].split()[-1] == "4.4"
    assert " 1 GE              1     1     S 26213" in txt and " 1 HA              0 27089" in txt
    assert " 1 OP              Y     N" in txt                                 # water-limited: no nitrogen balance


def test_cultivar_override_keeps_the_columns(tmp_path):
    f = tmp_path / "MZCER048.CUL"
    f.write_text("*MAIZE CULTIVAR COEFFICIENTS\n!comment\n"
                 "@VAR#  VRNAME.......... EXPNO   ECO#    P1    P2    P5    G2    G3 PHINT\n"
                 "KY0014 KATUMANICOMPI        . IB0001 238.6 0.500 654.0 450.0 10.50 75.00\n"
                 "KY0018 KATUMANICOMP-II      . IB0001 125.0 0.500 660.0 450.0 10.50 75.00\n", encoding="latin-1")
    out = ds.cultivar_file(f, "KY0014", {"P1": 200.0, "G2": 612.345})
    base, custom = out.splitlines()[-2:]
    assert base.startswith("KY0014") and custom.startswith("CE0001 crop engine")
    assert len(custom) == len(base)
    assert custom[-36:].split() == ["200.0", "0.500", "654.0", "612.3", "10.50", "75.00"]
    eco = base.index("IB0001")
    assert custom[:eco] == ("CE0001 " + "crop engine".ljust(16) + base[23:])[:eco]    # name in its 16 columns
    with pytest.raises(ValueError):
        ds.cultivar_file(f, "XX9999", {})
    with pytest.raises(ValueError):
        ds.cultivar_file(f, "KY0014", {"G9": 1.0})


def test_summary_reader_on_dssats_own_output():
    # DSSAT's reference maize experiment UFGA8201 (six treatments), its Summary.OUT as DSSAT 4.8 wrote it: fixed
    # columns, text columns with spaces (the treatment names)
    s = ds.read_summary((REF / "dssat_UFGA8201_Summary.OUT").read_text(encoding="latin-1"))
    assert set(s) == {1, 2, 3, 4, 5, 6}
    assert [s[k]["HWAM"] for k in (1, 4)] == ["2334", "11856"] and s[4]["MDAT"] == "1982185" and s[4]["LAIX"] == "4.6"
    assert s[1]["PDAT"] == "1982057" and s[1]["EDAT"] == "1982068" and s[3]["IRCM"] == "264"


def test_plantgro_reader_and_outcomes():
    last = dt.date(2027, 3, 30)
    row = lambda **k: {"PDAT": "2026302", "EDAT": "2026308", "ADAT": "-99", "MDAT": "-99", "HDAT": "2027089",   # noqa: E731
                       "HWAM": "0", "CWAM": "0", "LAIX": "0.0", **k}
    s = {1: row(ADAT="2026365", MDAT="2027040", HDAT="2027040", HWAM="4321", CWAM="9876", LAIX="2.9"),
         2: row(PDAT="2026311", EDAT="-99", CWAM="12"), 3: row(PDAT="2026311", EDAT="2026316", CWAM="2100", LAIX="1.2")}
    grow = ("*DSSAT Cropping System Model Ver. 4.8\n\n*RUN   1        : M1\n"
            "@YEAR DOY   DAS   DAP   L#SD   GSTD  LAID\n 2026 302    89     0    0.0      0  0.00\n 2026 340   127    38    9.0      2  2.50\n"
            " 2027  40   192   103   15.0      6  0.40\n\n*RUN   2        : M2\n"
            "@YEAR DOY   DAS   DAP   L#SD   GSTD  LAID\n 2026 311    98     0    0.0      0  0.00\n\n*RUN   3        : M3\n"
            "@YEAR DOY   DAS   DAP   L#SD   GSTD  LAID\n 2026 340   127    29    9.0      2  1.20\n 2027  89   241    143   15.0      6  0.90\n")
    g = ds.read_plantgro(grow)
    assert set(g) == {1, 2, 3} and g[1].lai.max() == 2.5 and g[1].date.iloc[-1] == pd.Timestamp("2027-02-09")
    o1, o2, o3 = (ds.outcome(s[k], g[k], last) for k in (1, 2, 3))
    assert o1["status"] == "ok" and o1["yield_t_ha"] == 4.321 and o1["harvest"] == "2027-02-09"
    assert o2["status"] == "failed_establishment" and o2["yield_t_ha"] == 0.0
    assert o3["status"] == "too_late"                                         # alive, not mature at the season's end
    assert ds.outcome({**s[3], "HDAT": "2027010"}, g[3].iloc[:1], last)["status"] == "died"


def test_install_checks_the_wheel_hash(tmp_path, monkeypatch):
    w = tmp_path / "fake.whl"
    with zipfile.ZipFile(w, "w") as z:
        z.writestr("DSSATTools/bin/" + ds.EXE.name, b"x")
        z.writestr("DSSATTools/dssat-csm-os/Data/Genotype/MZCER048.CUL", "cul")
    monkeypatch.setattr(ds, "HOME", tmp_path / "dssat")
    with pytest.raises(RuntimeError, match="SHA-256"):
        ds.install(w, log=lambda m: None)
    monkeypatch.setitem(ds.WHEEL, "sha256", hashlib.sha256(w.read_bytes()).hexdigest())
    monkeypatch.setattr(ds, "EXE", tmp_path / "dssat" / "bin" / ds.EXE.name)
    monkeypatch.setattr(ds, "DATA", tmp_path / "dssat" / "Data")
    ds.install(w, log=lambda m: None)
    assert ds.installed() and (ds.DATA / "Genotype" / "MZCER048.CUL").read_text() == "cul"
    assert ds.available({"aquacrop_crop": "MaizeGDD", "dssat": {"cultivar": "KY0014"}})
    assert not ds.available({"aquacrop_crop": "MaizeGDD"})                    # no cultivar chosen
    assert np.isclose(ds.ESTABLISHED_LAI, 0.0855, atol=1e-3)


def test_cultivars_file_names_every_variety():
    from crop_engine import config as C
    import yaml
    vs = yaml.safe_load(C.VARIETIES_FILE.read_text(encoding="utf-8"))["varieties"]
    cv = ds.cultivars()
    assert set(cv) == set(vs)
    got = ds.attach({k: dict(v) for k, v in vs.items()})
    assert got["maize_early"]["dssat"]["cultivar"] == "KY0018" and "dssat" not in vs["maize_early"]


@pytest.mark.skipif(not ds.installed(), reason="DSSAT is not installed (python -m crop_engine.adapters.dssat_adapter --install)")
def test_dssat_grows_a_watered_and_a_dry_member():
    # the program itself: two members of one task, one watered every day, one with no rain after sowing
    from crop_engine import run_outlook as ro
    _, vs = ro.load_varieties(["maize_early"])
    v = ds.attach(vs)["maize_early"]
    dates = pd.date_range("2026-08-01", "2027-03-31")
    T = len(dates)
    rain = np.zeros((2, T))
    rain[0, 85:] = 4.0                                                     # member 1: 4 mm a day from late October
    rain[1, 85:90] = 15.0                                                  # member 2: a sowing rain, then nothing
    task = {"dates": dates.values, "rain": rain, "tmax": np.full(T, 29.0), "tmin": np.full(T, 17.0),
            "et0": np.full(T, 5.0), "rad": np.full(T, 21.0), "vap": np.full(T, 16.0), "wind2": np.full(T, 2.0),
            "source": np.zeros(T), "planting": [dt.date(2026, 10, 28)] * 2, "resow": [[], []], "variety": v,
            "layers": LAYERS, "initial_frac": 0.3, "lat": -2.21, "lon": 37.72, "elev": 975}
    wet, dry = ds.simulate(task)
    assert wet["status"] == "ok" and wet["yield_t_ha"] > 2.0 and wet["harvest"] < "2027-03-01"
    assert dry["status"] in ("died", "failed_establishment") or dry["yield_t_ha"] < wet["yield_t_ha"] / 4
    assert wet["sowings"] == 1 and len(wet["_canopy"]) == len(range(0, T, ds.CANOPY_STEP))


def test_nitrogen_files():
    plant = [dt.date(2026, 10, 29)]
    txt = ds.experiment_file("CE000001", "MZ", "KY0018", "CESOIL0001", dt.date(2026, 8, 1), plant, ["W0012602"],
                             [(5, 0.2), (60, 0.21)], 4.4, dt.date(2027, 3, 30),
                             nitrogen={"rate_kg_ha": 50, "split": [(0, 0.4), (30, 0.6)]})
    lines = txt.splitlines()
    head = lines[lines.index("@N R O C TNAME.................... CU FL SA IC MP MI MF MR MC MT ME MH SM")]
    t1 = lines[lines.index(head) + 1]
    assert t1[:_col(head, "MF") + 1].split()[-1] == "1" and t1[:_col(head, "MI") + 1].split()[-1] == "0"
    assert " 1 OP              Y     Y     N" in txt and " 1 MA              R     N     D     N     A" in txt
    fert = [ln for ln in lines if ln.startswith(" 1 ") and ds.UREA in ln]
    assert [ln.split()[1] for ln in fert] == ["0", "30"] and [ln.split()[5] for ln in fert] == ["20", "30"]
    ic = lines[lines.index("@C  ICBL  SH2O  SNH4  SNO3") + 1:][:2]
    assert ic[0].split()[3:] == [f"{ds.INIT_NH4:.1f}", f"{ds.INIT_NO3:.1f}"] and float(ic[1].split()[4]) == ds.INIT_NO3 / 2
    none = ds.experiment_file("CE000001", "BN", "IB0014", "CESOIL0001", dt.date(2026, 8, 1), plant, ["W0012602"],
                              [(5, 0.2)], 13.2, dt.date(2027, 3, 30), nitrogen={"rate_kg_ha": 0})
    assert " 1 OP              Y     Y     Y" in none and "*FERTILIZERS" not in none    # the bean fixes N; no urea
    assert " 1 OP              Y     N     N" in ds.experiment_file(
        "CE000001", "MZ", "KY0018", "CESOIL0001", dt.date(2026, 8, 1), plant, ["W0012602"], [(5, 0.2)], 4.4,
        dt.date(2027, 3, 30))                                                 # water-limited: no nitrogen balance
    sol = ds.soil_file("CESOIL0001", -2.21, 37.72, LAYERS, 150, nitrogen=True, organic_n_factor=0.5).splitlines()
    head = next(ln for ln in sol if ln.startswith("@  SLB"))
    r0 = sol[sol.index(head) + 1]
    assert r0[:_col(head, "SLNI") + 1].split()[-1] == f"{2.0 / 1.724 / ds.C_TO_N * 0.5:.3f}"
    plain = ds.soil_file("CESOIL0001", -2.21, 37.72, LAYERS, 150).splitlines()
    assert plain[plain.index(head) + 1][:_col(head, "SLNI") + 1].split()[-1] == "-99"
    assert 0 < ds.soil_settings()["organic_n_factor"] <= 1


def test_dssat_hash_and_varieties(monkeypatch):
    from crop_engine import run_outlook as ro
    from crop_engine.data.sites import registered_sites
    sites = registered_sites()
    h = ro.dssat_hash(["rule1"], sites)
    assert h == ro.dssat_hash(["rule1"], sites) and h != ro.dssat_hash(["rule1", "fao-agricultural"], sites)
    _, vs = ro.load_varieties()
    monkeypatch.setattr(ds, "installed", lambda: False)
    assert ro.dssat_varieties(vs) == []                                    # not installed: no DSSAT variety
    monkeypatch.setattr(ds, "installed", lambda: True)
    assert set(ro.dssat_varieties(vs)) == {"maize_early", "maize_medium", "sorghum", "bean"}
