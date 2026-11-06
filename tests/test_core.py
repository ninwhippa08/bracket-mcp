"""Hand checks and verification cases for the engineering math (no MCP involved)."""

import math

import pytest

from bracket_mcp import core

# HW4 hand check: Al 6061-T6, F = 500 N, L = 100 mm, b = 20 mm, h = 10 mm.
HAND = dict(material="Al 6061-T6", F_N=500, L_mm=100, b_mm=20, h_mm=10)
I = 20 * 10**3 / 12
HAND_DEFLECTION = 500 * 100**3 / (3 * 68900 * I)  # 1.4514 mm


def test_original_tools_match_hand_calculation():
    assert core.bending_stress(**HAND)["max_stress_MPa"] == pytest.approx(150.0, abs=1e-3)
    assert core.tip_deflection(**HAND)["tip_deflection_mm"] == pytest.approx(HAND_DEFLECTION, abs=1e-4)
    sf = core.safety_check(**HAND, required_SF=1.5)
    assert sf["safety_factor"] == pytest.approx(276 / 150, abs=1e-3)
    assert sf["passes"] is True
    assert core.bending_stress(**HAND)["warnings"] == []  # L/h = 10, below yield, metal


def test_original_tools_reject_bad_inputs():
    with pytest.raises(ValueError):
        core.bending_stress("Al 6061-T6", -500, 100, 20, 10)
    with pytest.raises(ValueError):
        core.safety_check(**HAND, required_SF=0.5)
    with pytest.raises(ValueError):
        core.tip_deflection("carbon fiber", 500, 100, 20, 10)


def _fea_from_theory(**overrides):
    """Build an 'ideal' FEA result equal to the closed-form expectation, then apply overrides."""
    name, (E, Sy, rho, p) = core.get_material(HAND["material"])
    G = E * 1000 / (2 * (1 + core.POISSON[name]))
    d = HAND_DEFLECTION + 500 * 100 / (5 / 6 * G * 20 * 10)
    args = dict(HAND, fea_tip_deflection_mm=d, fea_peak_stress_MPa=150 * 1.2,
                fea_probe_stress_MPa=6 * 500 * (100 - 30) / (20 * 10**2), probe_distance_mm=30,
                fea_reaction_force_N=-500)
    args.update(overrides)
    return args


def test_validate_consistent_model():
    r = core.validate_fea_result(**_fea_from_theory())
    assert r["verdict"] == "consistent_with_beam_theory"
    assert all(c["status"] in ("agrees", "near_nominal") for c in r["checks"])


def test_validate_flags_unit_error_in_modulus():
    # E entered 1000x too high (GPa typed as MPa the other way) -> deflection 1000x too small.
    r = core.validate_fea_result(**_fea_from_theory(fea_tip_deflection_mm=HAND_DEFLECTION / 1000))
    assert r["verdict"] == "setup_error_likely"
    assert any("/1000" in c for c in r["likely_causes"])


def test_validate_flags_singularity_peak_but_not_setup_error():
    r = core.validate_fea_result(**_fea_from_theory(fea_peak_stress_MPa=150 * 4.5))
    peak = next(c for c in r["checks"] if c["quantity"] == "peak_stress_MPa")
    assert peak["status"] == "likely_singularity"
    assert r["verdict"] == "consistent_with_beam_theory"  # global checks still agree
    assert any("mesh_convergence_check" in c for c in r["likely_causes"])


def test_validate_requires_probe_distance():
    with pytest.raises(ValueError):
        core.validate_fea_result(**_fea_from_theory(probe_distance_mm=None))
    with pytest.raises(ValueError):
        core.validate_fea_result(**_fea_from_theory(probe_distance_mm=150))  # beyond L


@pytest.mark.parametrize("sizes", [[4, 2, 1], [3, 2, 1.5], [1.5, 3, 2]])
def test_gci_recovers_known_order_and_limit(sizes):
    # Synthetic second-order data: phi(h) = 100 + 5 h^2 -> p = 2, extrapolated value = 100.
    results = [100 + 5 * h**2 for h in sizes]
    r = core.mesh_convergence_check(sizes, results)
    assert r["behavior"] == "monotonic"
    assert r["observed_order"] == pytest.approx(2.0, abs=1e-6)
    assert r["extrapolated_value"] == pytest.approx(100.0, abs=1e-6)
    h1, h2 = sorted(sizes)[:2]
    f1 = 100 + 5 * h1**2
    expected_gci = 1.25 * abs((5 * h2**2 - 5 * h1**2) / f1) / ((h2 / h1) ** 2 - 1) * 100
    assert r["gci_fine_percent"] == pytest.approx(expected_gci, abs=1e-3)


def test_gci_detects_singularity_and_oscillation():
    # Peak stress at a sharp corner grows faster as the mesh is refined.
    div = core.mesh_convergence_check([4, 2, 1], [210, 260, 340])
    assert div["behavior"] == "diverging" and div["converged"] is False
    osc = core.mesh_convergence_check([4, 2, 1], [150, 148, 151])
    assert osc["behavior"] == "oscillatory" and osc["converged"] is False


def test_gci_rejects_bad_inputs():
    with pytest.raises(ValueError):
        core.mesh_convergence_check([2, 1], [1.0, 1.1])
    with pytest.raises(ValueError):
        core.mesh_convergence_check([2, 2, 1], [1.0, 1.1, 1.2])
    with pytest.raises(ValueError):
        core.mesh_convergence_check([2, 1, 0.5], [1.0, math.nan, 1.2])
