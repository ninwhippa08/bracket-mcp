"""Pure engineering calculations for the bracket MCP server (no MCP code here).

Model: rectangular cantilever bracket (width b, thickness h, length L), fixed at the wall,
point load F at the free end. Units everywhere: N, mm, MPa (= N/mm^2), E in GPa, density g/cm^3.

The three original tools (bending_stress, tip_deflection, safety_check) are carried over
unchanged from HW4. The two new tools (validate_fea_result, mesh_convergence_check) help a
beginner decide whether an ANSYS result can be trusted.
"""

from __future__ import annotations

import math

# name: (E [GPa], yield strength [MPa], density [g/cm^3], is_plastic)
# Typical room-temperature handbook/datasheet values; check the supplier datasheet for real designs.
MATERIALS: dict[str, tuple[float, float, float, bool]] = {
    "A36 steel": (200.0, 250.0, 7.85, False),
    "1018 steel (cold drawn)": (205.0, 370.0, 7.87, False),
    "4140 steel (normalized)": (205.0, 655.0, 7.85, False),
    "304 stainless (annealed)": (193.0, 215.0, 8.00, False),
    "316 stainless (annealed)": (193.0, 205.0, 8.00, False),
    "Al 6061-T6": (68.9, 276.0, 2.70, False),
    "Al 6063-T6": (68.9, 214.0, 2.70, False),
    "Al 5052-H32": (70.3, 193.0, 2.68, False),
    "Al 7075-T6": (71.7, 503.0, 2.81, False),
    "Ti-6Al-4V (annealed)": (113.8, 880.0, 4.43, False),
    "Ductile iron 65-45-12": (169.0, 310.0, 7.10, False),
    "Nylon PA6 (dry)": (2.8, 70.0, 1.14, True),
    "ABS": (2.3, 40.0, 1.05, True),
    "Polycarbonate (PC)": (2.4, 62.0, 1.20, True),
    "PEEK": (3.6, 100.0, 1.30, True),
}

# Poisson's ratio, used only for the shear-deformation (Timoshenko) correction in validate_fea_result.
POISSON = {name: (0.35 if plastic else 0.33 if name.startswith(("Al", "Ti")) else 0.29)
           for name, (_, _, _, plastic) in MATERIALS.items()}


def get_material(material: str) -> tuple[str, tuple[float, float, float, bool]]:
    """Exact or unique case-insensitive partial match ("6061" -> "Al 6061-T6")."""
    key = material.strip().lower()
    for name, props in MATERIALS.items():
        if key == name.lower():
            return name, props
    matches = [n for n in MATERIALS if key and key in n.lower()]
    if len(matches) == 1:
        return matches[0], MATERIALS[matches[0]]
    raise ValueError(f"Unknown or ambiguous material '{material}'. Options: {list(MATERIALS)}")


def _check_positive(**values: float) -> None:
    for name, v in values.items():
        if not (v > 0 and math.isfinite(v)):
            raise ValueError(f"{name} must be a positive, finite number (got {v}).")


def _warnings(name: str, L_mm: float, h_mm: float, stress: float | None = None,
              deflection: float | None = None) -> list[str]:
    E, Sy, rho, plastic = MATERIALS[name]
    w = []
    if L_mm / h_mm < 10:
        w.append(f"L/h = {L_mm / h_mm:.1f} < 10: bracket is not slender, beam theory underestimates "
                 "deflection (shear matters). Use FEA.")
    if stress is not None and stress >= Sy:
        w.append(f"Stress {stress:.1f} MPa >= yield {Sy:.0f} MPa: material yields, linear-elastic "
                 "results are not valid.")
    if deflection is not None and deflection / L_mm > 0.05:
        w.append(f"Deflection is {100 * deflection / L_mm:.1f}% of L (> 5%): small-deflection "
                 "assumption is breaking down.")
    if plastic:
        w.append(f"{name} is a plastic: it creeps under sustained load and its E and strength drop with "
                 "temperature (and humidity for nylon). Treat results as short-term, room-temperature only.")
    return w


def _sigma(F, L, b, h):
    return 6 * F * L / (b * h**2)


def _delta(F, L, b, h, E_GPa):
    return 4 * F * L**3 / (E_GPa * 1000 * b * h**3)


# --------------------------------------------------------------------------- original HW4 tools

def bending_stress(material: str, F_N: float, L_mm: float, b_mm: float, h_mm: float) -> dict:
    """sigma_max = 6FL/(bh^2) at the top/bottom surface of the fixed end."""
    _check_positive(F_N=F_N, L_mm=L_mm, b_mm=b_mm, h_mm=h_mm)
    name, (E, Sy, rho, p) = get_material(material)
    sigma = _sigma(F_N, L_mm, b_mm, h_mm)
    return {"material": name, "max_stress_MPa": round(sigma, 3), "yield_MPa": Sy,
            "location": "top/bottom surface at the fixed end",
            "warnings": _warnings(name, L_mm, h_mm, stress=sigma)}


def tip_deflection(material: str, F_N: float, L_mm: float, b_mm: float, h_mm: float) -> dict:
    """delta = FL^3/(3EI) = 4FL^3/(E b h^3)."""
    _check_positive(F_N=F_N, L_mm=L_mm, b_mm=b_mm, h_mm=h_mm)
    name, (E, Sy, rho, p) = get_material(material)
    delta = _delta(F_N, L_mm, b_mm, h_mm, E)
    sigma = _sigma(F_N, L_mm, b_mm, h_mm)
    return {"material": name, "tip_deflection_mm": round(delta, 4),
            "deflection_to_length_percent": round(100 * delta / L_mm, 3),
            "warnings": _warnings(name, L_mm, h_mm, stress=sigma, deflection=delta)}


def safety_check(material: str, F_N: float, L_mm: float, b_mm: float, h_mm: float,
                 required_SF: float) -> dict:
    """SF = Sy / sigma_max, compared with a required safety factor (static yield only)."""
    _check_positive(F_N=F_N, L_mm=L_mm, b_mm=b_mm, h_mm=h_mm)
    if not required_SF >= 1:
        raise ValueError(f"required_SF must be >= 1 (got {required_SF}).")
    name, (E, Sy, rho, p) = get_material(material)
    sigma = _sigma(F_N, L_mm, b_mm, h_mm)
    sf = Sy / sigma
    w = _warnings(name, L_mm, h_mm, stress=sigma)
    w.append("SF covers static yielding only. Cyclic loads need a fatigue check, and holes/fillets add a "
             "stress concentration Kt.")
    return {"material": name, "max_stress_MPa": round(sigma, 3), "yield_MPa": Sy,
            "safety_factor": round(sf, 3), "required_SF": required_SF, "passes": sf >= required_SF,
            "warnings": w}


# --------------------------------------------------------------------------- new tool 1

# Agreement bands for |FEA - expected| / expected.
AGREE_TOL = 0.05   # within 5 %: agrees
CHECK_TOL = 0.15   # 5-15 %: plausible but look closer; above 15 %: mismatch


def _compare(label: str, expected: float, fea: float) -> dict:
    ratio = fea / expected
    diff = 100 * (ratio - 1)
    if abs(ratio - 1) <= AGREE_TOL:
        status = "agrees"
    elif abs(ratio - 1) <= CHECK_TOL:
        status = "check"
    else:
        status = "mismatch"
    return {"quantity": label, "expected": round(expected, 4), "fea": fea,
            "fea_to_expected_ratio": round(ratio, 4), "difference_percent": round(diff, 2),
            "status": status}


def _unit_hint(ratio: float) -> str | None:
    for factor, text in ((1000, "x1000"), (0.001, "/1000"), (1e6, "x1e6"), (1e-6, "/1e6"),
                         (9.81, "x9.81 (kgf vs N?)"), (1 / 9.81, "/9.81 (kgf vs N?)")):
        if abs(ratio / factor - 1) < 0.15:
            return f"FEA value is about {text} the expected value: check units (mm vs m, MPa vs Pa, N vs kN)."
    return None


def validate_fea_result(material: str, F_N: float, L_mm: float, b_mm: float, h_mm: float,
                        fea_tip_deflection_mm: float, fea_peak_stress_MPa: float,
                        fea_probe_stress_MPa: float | None = None, probe_distance_mm: float | None = None,
                        fea_reaction_force_N: float | None = None) -> dict:
    """Compare ANSYS results for the cantilever bracket against closed-form expectations.

    Checks (each only if its input is given):
      1. Reaction force at the fixed support vs the applied load (catches wrong load/units/support).
      2. Tip deflection vs Euler-Bernoulli + Timoshenko shear correction (deflection is a global
         quantity, insensitive to the corner singularity, so it is the most reliable check).
      3. Bending stress at a probe point away from the wall vs sigma(x) = 6F(L-x)/(bh^2).
      4. Peak stress at the wall vs nominal: a peak well above nominal is expected (stress
         concentration / mesh singularity at the sharp re-entrant corner) and must NOT be read
         as the design stress without a mesh-convergence study.
    """
    _check_positive(F_N=F_N, L_mm=L_mm, b_mm=b_mm, h_mm=h_mm,
                    fea_tip_deflection_mm=fea_tip_deflection_mm, fea_peak_stress_MPa=fea_peak_stress_MPa)
    name, (E, Sy, rho, plastic) = get_material(material)
    nu = POISSON[name]
    G = E * 1000 / (2 * (1 + nu))                       # MPa
    kappa = 5 / 6                                       # shear coefficient, rectangle
    d_bend = _delta(F_N, L_mm, b_mm, h_mm, E)
    d_shear = F_N * L_mm / (kappa * G * b_mm * h_mm)
    sigma_nom = _sigma(F_N, L_mm, b_mm, h_mm)

    checks, causes = [], []

    if fea_reaction_force_N is not None:
        c = _compare("reaction_force_N", F_N, abs(fea_reaction_force_N))
        checks.append(c)
        if c["status"] != "agrees":
            causes.append("Reaction force does not match the applied load: the load magnitude, direction or "
                          "units are wrong, or another support is carrying part of the load.")

    c = _compare("tip_deflection_mm", d_bend + d_shear, fea_tip_deflection_mm)
    c["expected_bending_only"] = round(d_bend, 4)
    c["expected_shear_part"] = round(d_shear, 4)
    checks.append(c)
    if c["status"] != "agrees":
        if c["fea_to_expected_ratio"] < 1:
            causes.append("FEA is stiffer than beam theory: check E (GPa vs MPa), that the load is at the free end, "
                          "and that only the wall face is fixed. Coarse linear (non-midside-node) elements also "
                          "make a bending model too stiff.")
        else:
            causes.append("FEA is more flexible than beam theory: check E, the thickness direction (b and h "
                          "swapped?), and whether the support is a true fixed support. A real flange/bolt "
                          "support is also more flexible than the ideal wall.")

    if fea_probe_stress_MPa is not None:
        if probe_distance_mm is None or not 0 < probe_distance_mm < L_mm:
            raise ValueError("probe_distance_mm (distance from the wall) is required with fea_probe_stress_MPa "
                             f"and must satisfy 0 < x < L = {L_mm} mm.")
        expected = 6 * F_N * (L_mm - probe_distance_mm) / (b_mm * h_mm**2)
        c = _compare("probe_bending_stress_MPa", expected, fea_probe_stress_MPa)
        c["probe_distance_mm"] = probe_distance_mm
        checks.append(c)
        if probe_distance_mm < h_mm:
            causes.append(f"Probe is {probe_distance_mm} mm from the wall (< h = {h_mm} mm), inside the zone "
                          "disturbed by the support; probe at least one thickness away from the wall.")
        elif c["status"] != "agrees":
            causes.append("Stress away from the wall disagrees with beam theory: check that you read normal "
                          "stress along the length (or von Mises on the top surface), the load, and units.")

    peak_ratio = fea_peak_stress_MPa / sigma_nom
    if peak_ratio < 1 - AGREE_TOL:
        peak_status = "below_nominal"
        causes.append("Peak stress is below the nominal bending stress, which should not happen at the wall: "
                      "check load magnitude, units, and the result type (e.g. a stress component instead of the maximum).")
    elif peak_ratio <= 1.3:
        peak_status = "near_nominal"
    elif peak_ratio <= 3:
        peak_status = "elevated_corner"
    else:
        peak_status = "likely_singularity"
    checks.append({"quantity": "peak_stress_MPa", "expected": round(sigma_nom, 3), "fea": fea_peak_stress_MPa,
                   "fea_to_expected_ratio": round(peak_ratio, 3), "difference_percent": round(100 * (peak_ratio - 1), 2),
                   "status": peak_status})
    if peak_status in ("elevated_corner", "likely_singularity"):
        causes.append(f"Peak stress is {peak_ratio:.1f}x nominal. At a sharp fixed corner this is a stress "
                      "concentration or a mesh singularity: refine the mesh 3 times and run mesh_convergence_check "
                      "on the peak. If it keeps rising, it is a singularity; use the probe stress or add the real fillet.")

    for chk in checks:
        hint = _unit_hint(chk["fea_to_expected_ratio"])
        if hint and chk["status"] not in ("agrees", "near_nominal"):
            causes.insert(0, f"{chk['quantity']}: {hint}")

    primary = [c for c in checks if c["quantity"] != "peak_stress_MPa"]
    if any(c["status"] == "mismatch" for c in primary) or peak_status == "below_nominal":
        verdict = "setup_error_likely"
    elif any(c["status"] == "check" for c in primary):
        verdict = "plausible_check_details"
    else:
        verdict = "consistent_with_beam_theory"

    w = _warnings(name, L_mm, h_mm, stress=sigma_nom, deflection=d_bend)
    if fea_peak_stress_MPa >= Sy:
        w.append(f"FEA peak {fea_peak_stress_MPa} MPa >= yield {Sy:.0f} MPa: a linear FEA result above yield "
                 "is not physical; local yielding or a singularity, not necessarily failure.")
    return {"material": name, "verdict": verdict, "checks": checks, "likely_causes": causes,
            "assumptions": ["rectangular cantilever, end point load, ideal fixed wall",
                            f"Timoshenko shear correction with kappa = 5/6, nu = {nu}",
                            f"tolerances: agrees <= {AGREE_TOL:.0%}, check <= {CHECK_TOL:.0%}"],
            "warnings": w}


# --------------------------------------------------------------------------- new tool 2

def mesh_convergence_check(element_sizes_mm: list[float], results: list[float],
                           target_gci_percent: float = 5.0) -> dict:
    """Grid Convergence Index (Roache; procedure of Celik et al., 2008, J. Fluids Eng. 130(7)).

    Uses the three finest meshes. phi1 = finest. Works with non-constant refinement ratios by
    solving for the observed order p with fixed-point iteration.
    """
    if len(element_sizes_mm) != len(results):
        raise ValueError("element_sizes_mm and results must have the same length.")
    if not 3 <= len(element_sizes_mm) <= 8:
        raise ValueError("Give between 3 and 8 mesh levels (at least 3 are needed for an observed order).")
    _check_positive(**{f"element_sizes_mm[{i}]": v for i, v in enumerate(element_sizes_mm)})
    if not all(math.isfinite(r) for r in results):
        raise ValueError("results must be finite numbers.")
    if not 0 < target_gci_percent <= 50:
        raise ValueError("target_gci_percent must be in (0, 50].")

    pairs = sorted(zip(element_sizes_mm, results))      # finest first
    sizes = [s for s, _ in pairs]
    if len(set(sizes)) != len(sizes):
        raise ValueError("Element sizes must all be different.")
    (h1, f1), (h2, f2), (h3, f3) = pairs[:3]
    r21, r32 = h2 / h1, h3 / h2
    e21, e32 = f2 - f1, f3 - f2

    notes = []
    if min(r21, r32) < 1.3:
        notes.append(f"Refinement ratios {r21:.2f} and {r32:.2f}: Celik et al. recommend > 1.3 between levels "
                     "so the change is larger than numerical noise.")

    base = {"meshes_used_fine_to_coarse": [{"element_size_mm": h, "result": f} for h, f in pairs[:3]],
            "refinement_ratios": [round(r21, 3), round(r32, 3)],
            "change_fine_two_percent": round(100 * abs(e21 / f1), 3) if f1 else None}

    if abs(e21) < 1e-12 * max(1.0, abs(f1)):
        return {**base, "behavior": "converged_identical", "observed_order": None, "extrapolated_value": f1,
                "gci_fine_percent": 0.0, "converged": True,
                "recommendation": "The two finest meshes give the same value; the result is mesh-independent.",
                "notes": notes}
    if abs(e32) < 1e-12 * max(1.0, abs(f2)):
        raise ValueError("The two coarsest meshes give identical results but the finest differs; "
                         "the data are not consistent with convergence. Check the result extraction.")

    ratio = e32 / e21
    if ratio < 0:
        lo, hi = min(f1, f2, f3), max(f1, f2, f3)
        return {**base, "behavior": "oscillatory", "observed_order": None, "extrapolated_value": None,
                "gci_fine_percent": round(100 * (hi - lo) / 2 / abs(f1), 3) if f1 else None,
                "converged": False,
                "recommendation": "Results oscillate between refinements. Report the band as an uncertainty "
                                  "estimate, or refine further with a consistent element type and growth rate.",
                "notes": notes}
    if abs(e21) > abs(e32):
        return {**base, "behavior": "diverging", "observed_order": None, "extrapolated_value": None,
                "gci_fine_percent": None, "converged": False,
                "recommendation": "The result changes MORE as the mesh gets finer. For a peak stress at a sharp "
                                  "corner this is a stress singularity: the value will never converge. Read stress "
                                  "away from the corner, model the real fillet radius, or use deflection instead.",
                "notes": notes}

    s = 1.0  # monotonic
    p = abs(math.log(abs(ratio))) / math.log(r21)
    for _ in range(200):
        q = math.log((r21**p - s) / (r32**p - s))
        p_new = abs(math.log(abs(ratio)) + q) / math.log(r21)
        if abs(p_new - p) < 1e-10:
            break
        p = p_new
    p = p_new
    fext = (r21**p * f1 - f2) / (r21**p - 1)
    gci = 1.25 * abs(e21 / f1) / (r21**p - 1) * 100 if f1 else float("inf")
    converged = gci <= target_gci_percent
    if p < 0.5:
        notes.append(f"Observed order p = {p:.2f} is very low; the meshes may not be in the asymptotic range "
                     "(or the quantity is near a singularity). Treat the GCI with caution.")
    elif p > 4:
        notes.append(f"Observed order p = {p:.2f} is unusually high for a 2nd-order FE stress; the three "
                     "results may be converging by coincidence. Add a fourth, finer mesh.")
    rec = (f"GCI {gci:.2f}% <= target {target_gci_percent}%: the finest mesh is adequate for this quantity."
           if converged else
           f"GCI {gci:.2f}% > target {target_gci_percent}%: refine the mesh further where this result is read.")
    return {**base, "behavior": "monotonic", "observed_order": round(p, 3),
            "extrapolated_value": round(fext, 6), "gci_fine_percent": round(gci, 3),
            "converged": converged, "recommendation": rec, "notes": notes}
