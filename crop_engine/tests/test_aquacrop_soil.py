"""AquaCrop's soil from the SoilGrids layers: layers on the compartments' boundaries and coarse fragments
(aquacrop_adapter.make_soil). python -m pytest crop_engine/tests"""
import numpy as np
import pytest

from crop_engine.adapters import aquacrop_adapter as aq
from crop_engine.data.soil import Layer

SOILGRIDS = [Layer(0, 5, 46, 34, 1.5, 5.6, 0.32, 0.20), Layer(5, 15, 46, 34, 1.4, 6.0, 0.31, 0.20),
             Layer(15, 30, 43, 39, 1.2, 7.4, 0.33, 0.21), Layer(30, 60, 38, 44, 1.0, 9.7, 0.35, 0.22),
             Layer(60, 100, 37, 44, 0.8, 15.9, 0.32, 0.21), Layer(100, 200, 38, 43, 0.6, 20.5, 0.30, 0.20)]


def test_layers_on_compartment_boundaries():
    a = aq.aligned_layers(SOILGRIDS)
    assert [(L.top_cm, L.bottom_cm) for L in a] == [(0, 10), (10, 30), (30, 60), (60, 100), (100, 200)]
    assert a[0].cfvo == pytest.approx((5.6 + 6.0) / 2)                       # 0-5 and 5-10 cm, equal weights
    assert a[1].clay == pytest.approx((34 * 5 + 39 * 15) / 20)                # 10-15 and 15-30 cm
    assert a[-1].sand == 38 and a[-1].cfvo == 20.5


def test_every_layer_gets_its_compartments():
    """AquaCrop-OSPy dropped the 0-5 cm layer (thinner than a compartment) and gave 1-2 m the 60-100 cm layer."""
    p = aq.make_soil(SOILGRIDS).profile
    assert p.Layer.tolist() == [1, 2, 2, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 5, 5]
    assert aq.make_soil(SOILGRIDS).nLayer == 5


def test_coarse_fragments_take_water_out():
    from aquacrop import Soil
    fine = [Layer(L.top_cm, L.bottom_cm, L.sand, L.clay, L.om, 0.0, L.theta_fc, L.theta_wp) for L in SOILGRIDS]
    stony, clean = aq.make_soil(SOILGRIDS).profile, aq.make_soil(fine).profile
    ratio = stony.th_fc.values / clean.th_fc.values
    assert ratio[-1] == pytest.approx(1 - 0.205, abs=0.005)                   # 100-200 cm: 20.5 % stones
    assert ratio[0] == pytest.approx(1 - 0.058, abs=0.005)
    assert np.allclose(stony.Ksat.values, clean.Ksat.values)                  # conductivity: the texture's
    wp, fc, sat, ksat = Soil("custom", dz=[0.1]).calculate_soil_hydraulic_properties(0.38, 0.43, 0.6)
    assert clean.th_fc.values[-1] == pytest.approx(fc, abs=0.002)
