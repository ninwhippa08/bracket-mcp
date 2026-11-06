"""Bracket Analysis MCP server (stdio).

Five tools for a rectangular cantilever bracket (fixed wall, end point load):
  original (HW4): bending_stress, tip_deflection, safety_check
  new (HW5):      validate_fea_result, mesh_convergence_check
plus one read-only resource, materials://library.

The server only validates inputs and does deterministic math. Choosing tools, converting the
user's units, and explaining results are the MCP client's (LLM's) job.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from bracket_mcp import core

mcp = MCPServer(
    name="bracket-analysis",
    version="1.0.0",
    instructions=(
        "Closed-form checks for a rectangular cantilever bracket (fixed at the wall, point load at the free end). "
        "Units: force N, length mm, stress MPa. Convert user units before calling. Every number you report must "
        "come from a tool result; always relay the 'warnings' list. Use validate_fea_result after an ANSYS run "
        "and mesh_convergence_check before trusting any FEA stress or deflection."
    ),
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

# ----------------------------------------------------------------------------- typed inputs

Material = Annotated[
    Literal[tuple(core.MATERIALS)],  # type: ignore[valid-type]
    Field(description="Bracket material (one of the 15 presets; see resource materials://library)."),
]
ForceN = Annotated[float, Field(gt=0, le=1e6, description="Tip point load F [N], 0 < F <= 1e6.")]
LengthMM = Annotated[float, Field(gt=0, le=5000, description="Arm length L from wall to load [mm], 0 < L <= 5000.")]
WidthMM = Annotated[float, Field(gt=0, le=1000, description="Width b, perpendicular to the load [mm], 0 < b <= 1000.")]
ThickMM = Annotated[float, Field(gt=0, le=1000, description="Thickness h, in the load direction [mm], 0 < h <= 1000.")]


# ----------------------------------------------------------------------------- structured outputs

class StressResult(BaseModel):
    material: str
    max_stress_MPa: float = Field(description="Nominal max bending stress at the wall [MPa].")
    yield_MPa: float
    location: str
    warnings: list[str]


class DeflectionResult(BaseModel):
    material: str
    tip_deflection_mm: float = Field(description="Tip deflection [mm] (Euler-Bernoulli).")
    deflection_to_length_percent: float = Field(description="delta / L [%]; small-deflection limit is 5%.")
    warnings: list[str]


class SafetyResult(BaseModel):
    material: str
    max_stress_MPa: float
    yield_MPa: float
    safety_factor: float = Field(description="Sy / sigma_max [-].")
    required_SF: float
    passes: bool
    warnings: list[str]


class Check(BaseModel):
    quantity: str
    expected: float = Field(description="Closed-form expectation, same units as the quantity.")
    fea: float = Field(description="Value read from the FEA model.")
    fea_to_expected_ratio: float
    difference_percent: float
    status: str = Field(description="agrees (<=5%), check (5-15%), mismatch (>15%); for peak stress: "
                                    "below_nominal, near_nominal (<=1.3x), elevated_corner (<=3x), likely_singularity.")
    expected_bending_only: float | None = None
    expected_shear_part: float | None = None
    probe_distance_mm: float | None = None


class ValidationResult(BaseModel):
    material: str
    verdict: Literal["consistent_with_beam_theory", "plausible_check_details", "setup_error_likely"]
    checks: list[Check]
    likely_causes: list[str]
    assumptions: list[str]
    warnings: list[str]


class MeshLevel(BaseModel):
    element_size_mm: float
    result: float


class ConvergenceResult(BaseModel):
    behavior: Literal["monotonic", "oscillatory", "diverging", "converged_identical"]
    meshes_used_fine_to_coarse: list[MeshLevel]
    refinement_ratios: list[float] = Field(description="[r21, r32] = coarser size / finer size.")
    change_fine_two_percent: float | None = Field(description="|f2 - f1| / |f1| between the two finest meshes [%].")
    observed_order: float | None = Field(description="Observed order of convergence p (monotonic only).")
    extrapolated_value: float | None = Field(description="Richardson-extrapolated (mesh-independent) estimate.")
    gci_fine_percent: float | None = Field(description="Grid Convergence Index of the finest mesh [%] (Fs = 1.25).")
    converged: bool
    recommendation: str
    notes: list[str]


def _run(fn, **kwargs):
    """Turn domain errors from core into MCP tool errors (isError: true) with a readable message."""
    try:
        return fn(**kwargs)
    except ValueError as exc:
        raise ToolError(f"Invalid input: {exc}") from exc


# ----------------------------------------------------------------------------- resource

@mcp.resource("materials://library", name="material_library", mime_type="application/json",
              description="The 15 preset materials: E [GPa], yield strength [MPa], density [g/cm^3], plastic flag.")
def material_library() -> str:
    return json.dumps({n: {"E_GPa": E, "yield_MPa": Sy, "density_g_cm3": rho, "plastic": p}
                       for n, (E, Sy, rho, p) in core.MATERIALS.items()}, indent=2)


# ----------------------------------------------------------------------------- original tools (HW4)

@mcp.tool(title="Bending stress at the wall", annotations=READ_ONLY)
def bending_stress(material: Material, F_N: ForceN, L_mm: LengthMM, b_mm: WidthMM, h_mm: ThickMM) -> StressResult:
    """Nominal maximum bending stress of a cantilever bracket: sigma = 6FL/(bh^2) at the top/bottom surface of the
    fixed end. Assumes Euler-Bernoulli beam, linear-elastic isotropic material, ideal fixed wall, Kt = 1.
    Valid when L/h >= 10 and sigma < yield (warnings are returned otherwise)."""
    return StressResult(**_run(core.bending_stress, material=material, F_N=F_N, L_mm=L_mm, b_mm=b_mm, h_mm=h_mm))


@mcp.tool(title="Tip deflection", annotations=READ_ONLY)
def tip_deflection(material: Material, F_N: ForceN, L_mm: LengthMM, b_mm: WidthMM, h_mm: ThickMM) -> DeflectionResult:
    """Tip deflection of a cantilever bracket under an end load: delta = FL^3/(3EI) = 4FL^3/(E b h^3).
    Shear deformation neglected, small deflection. Valid when L/h >= 10 and delta/L <= 5%."""
    return DeflectionResult(**_run(core.tip_deflection, material=material, F_N=F_N, L_mm=L_mm, b_mm=b_mm, h_mm=h_mm))


@mcp.tool(title="Safety factor against yield", annotations=READ_ONLY)
def safety_check(
    material: Material, F_N: ForceN, L_mm: LengthMM, b_mm: WidthMM, h_mm: ThickMM,
    required_SF: Annotated[float, Field(ge=1, le=10, description="Required safety factor [-], 1 <= SF <= 10.")],
) -> SafetyResult:
    """Static safety factor SF = Sy / sigma_max and pass/fail against the required SF.
    Static yield of a ductile material on nominal stress only: no fatigue, no stress concentration."""
    return SafetyResult(**_run(core.safety_check, material=material, F_N=F_N, L_mm=L_mm, b_mm=b_mm, h_mm=h_mm,
                               required_SF=required_SF))


# ----------------------------------------------------------------------------- new tools (HW5)

@mcp.tool(title="Validate an ANSYS result against beam theory", annotations=READ_ONLY)
def validate_fea_result(
    material: Material, F_N: ForceN, L_mm: LengthMM, b_mm: WidthMM, h_mm: ThickMM,
    fea_tip_deflection_mm: Annotated[float, Field(gt=0, le=1e4, description="Max total deformation at the tip from FEA [mm].")],
    fea_peak_stress_MPa: Annotated[float, Field(gt=0, le=1e6, description="Max equivalent (von Mises) stress from FEA [MPa].")],
    fea_probe_stress_MPa: Annotated[float | None, Field(gt=0, le=1e6, description="Optional: bending/von Mises stress on the top surface at a probe point away from the wall [MPa].")] = None,
    probe_distance_mm: Annotated[float | None, Field(gt=0, le=5000, description="Distance of the probe point from the wall [mm], 0 < x < L. Required with fea_probe_stress_MPa.")] = None,
    fea_reaction_force_N: Annotated[float | None, Field(le=1e6, description="Optional: total reaction force at the fixed support from FEA [N].")] = None,
) -> ValidationResult:
    """Sanity-check an FEA (e.g. ANSYS Mechanical) result for the cantilever bracket. Compares reaction force,
    tip deflection (with Timoshenko shear correction) and stress at a probe point with closed-form values, and
    classifies the wall peak stress (stress concentration / singularity). Returns a verdict, each check with
    expected vs FEA values, and likely setup causes for any mismatch (units, load, support, element type).
    It does not prove the model is right; it flags results that cannot be right."""
    return ValidationResult(**_run(
        core.validate_fea_result, material=material, F_N=F_N, L_mm=L_mm, b_mm=b_mm, h_mm=h_mm,
        fea_tip_deflection_mm=fea_tip_deflection_mm, fea_peak_stress_MPa=fea_peak_stress_MPa,
        fea_probe_stress_MPa=fea_probe_stress_MPa, probe_distance_mm=probe_distance_mm,
        fea_reaction_force_N=fea_reaction_force_N))


@mcp.tool(title="Mesh convergence (GCI) check", annotations=READ_ONLY)
def mesh_convergence_check(
    element_sizes_mm: Annotated[list[Annotated[float, Field(gt=0, le=1000)]],
                                Field(min_length=3, max_length=8, description="Element size of each mesh [mm], 3-8 levels, all different (any order).")],
    results: Annotated[list[float], Field(min_length=3, max_length=8, description="The same FEA quantity (e.g. tip deflection [mm] or stress [MPa]) for each mesh, in the same order as element_sizes_mm.")],
    target_gci_percent: Annotated[float, Field(gt=0, le=50, description="Acceptable discretization uncertainty [%], default 5.")] = 5.0,
) -> ConvergenceResult:
    """Decide whether an FEA result is mesh-independent. Uses the three finest meshes to compute the observed order
    of convergence, a Richardson-extrapolated value and the Grid Convergence Index (Roache; Celik et al. 2008).
    Detects oscillating results and results that grow under refinement (stress singularity at a sharp corner)."""
    return ConvergenceResult(**_run(core.mesh_convergence_check, element_sizes_mm=element_sizes_mm,
                                    results=results, target_gci_percent=target_gci_percent))


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
