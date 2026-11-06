# Demo transcript: bracket-analysis MCP server
Recorded 2026-11-06 11:09 with the official MCP Python client over stdio (`python.exe -m bracket_mcp.server`).

## tools/list

| tool | inputs (required*) |
|---|---|
| `bending_stress` | material*, F_N*, L_mm*, b_mm*, h_mm* |
| `tip_deflection` | material*, F_N*, L_mm*, b_mm*, h_mm* |
| `safety_check` | material*, F_N*, L_mm*, b_mm*, h_mm*, required_SF* |
| `validate_fea_result` | material*, F_N*, L_mm*, b_mm*, h_mm*, fea_tip_deflection_mm*, fea_peak_stress_MPa*, fea_probe_stress_MPa, probe_distance_mm, fea_reaction_force_N |
| `mesh_convergence_check` | element_sizes_mm*, results*, target_gci_percent |

## 1. Original tool: safety_check

**Request** `tools/call` → `safety_check`
```json
{
  "material": "Al 6061-T6",
  "F_N": 500,
  "L_mm": 100,
  "b_mm": 20,
  "h_mm": 10,
  "required_SF": 2.0
}
```

**Response** (isError: false)
```json
{
  "material": "Al 6061-T6",
  "max_stress_MPa": 150.0,
  "yield_MPa": 276.0,
  "safety_factor": 1.84,
  "required_SF": 2.0,
  "passes": false,
  "warnings": [
    "SF covers static yielding only. Cyclic loads need a fatigue check, and holes/fillets add a stress concentration Kt."
  ]
}
```

## 2. New tool: validate_fea_result (ANSYS run of the same bracket)

**Request** `tools/call` → `validate_fea_result`
```json
{
  "material": "Al 6061-T6",
  "F_N": 500,
  "L_mm": 100,
  "b_mm": 20,
  "h_mm": 10,
  "fea_tip_deflection_mm": 1.5,
  "fea_peak_stress_MPa": 212.0,
  "fea_probe_stress_MPa": 104.0,
  "probe_distance_mm": 30,
  "fea_reaction_force_N": 500.0
}
```

**Response** (isError: false)
```json
{
  "material": "Al 6061-T6",
  "verdict": "consistent_with_beam_theory",
  "checks": [
    {
      "quantity": "reaction_force_N",
      "expected": 500.0,
      "fea": 500.0,
      "fea_to_expected_ratio": 1.0,
      "difference_percent": 0.0,
      "status": "agrees",
      "expected_bending_only": null,
      "expected_shear_part": null,
      "probe_distance_mm": null
    },
    {
      "quantity": "tip_deflection_mm",
      "expected": 1.463,
      "fea": 1.5,
      "fea_to_expected_ratio": 1.0253,
      "difference_percent": 2.53,
      "status": "agrees",
      "expected_bending_only": 1.4514,
      "expected_shear_part": 0.0116,
      "probe_distance_mm": null
    },
    {
      "quantity": "probe_bending_stress_MPa",
      "expected": 105.0,
      "fea": 104.0,
      "fea_to_expected_ratio": 0.9905,
      "difference_percent": -0.95,
      "status": "agrees",
      "expected_bending_only": null,
      "expected_shear_part": null,
      "probe_distance_mm": 30.0
    },
    {
      "quantity": "peak_stress_MPa",
      "expected": 150.0,
      "fea": 212.0,
      "fea_to_expected_ratio": 1.413,
      "difference_percent": 41.33,
      "status": "elevated_corner",
      "expected_bending_only": null,
      "expected_shear_part": null,
      "probe_distance_mm": null
    }
  ],
  "likely_causes": [
    "Peak stress is 1.4x nominal. At a sharp fixed corner this is a stress concentration or a mesh singularity: refine the mesh 3 times and run mesh_convergence_check on the peak. If it keeps rising, it is a singularity; use the probe stress or add the real fillet."
  ],
  "assumptions": [
    "rectangular cantilever, end point load, ideal fixed wall",
    "Timoshenko shear correction with kappa = 5/6, nu = 0.33",
    "tolerances: agrees <= 5%, check <= 15%"
  ],
  "warnings": []
}
```

## 3a. New tool: mesh_convergence_check on tip deflection [mm]

**Request** `tools/call` → `mesh_convergence_check`
```json
{
  "element_sizes_mm": [
    5,
    2.5,
    1.25,
    0.625
  ],
  "results": [
    1.452,
    1.489,
    1.497,
    1.499
  ]
}
```

**Response** (isError: false)
```json
{
  "behavior": "monotonic",
  "meshes_used_fine_to_coarse": [
    {
      "element_size_mm": 0.625,
      "result": 1.499
    },
    {
      "element_size_mm": 1.25,
      "result": 1.497
    },
    {
      "element_size_mm": 2.5,
      "result": 1.489
    }
  ],
  "refinement_ratios": [
    2.0,
    2.0
  ],
  "change_fine_two_percent": 0.133,
  "observed_order": 2.0,
  "extrapolated_value": 1.499667,
  "gci_fine_percent": 0.056,
  "converged": true,
  "recommendation": "GCI 0.06% <= target 5.0%: the finest mesh is adequate for this quantity.",
  "notes": []
}
```

## 3b. New tool: mesh_convergence_check on wall peak stress [MPa]

**Request** `tools/call` → `mesh_convergence_check`
```json
{
  "element_sizes_mm": [
    5,
    2.5,
    1.25,
    0.625
  ],
  "results": [
    180.0,
    205.0,
    241.0,
    290.0
  ]
}
```

**Response** (isError: false)
```json
{
  "behavior": "diverging",
  "meshes_used_fine_to_coarse": [
    {
      "element_size_mm": 0.625,
      "result": 290.0
    },
    {
      "element_size_mm": 1.25,
      "result": 241.0
    },
    {
      "element_size_mm": 2.5,
      "result": 205.0
    }
  ],
  "refinement_ratios": [
    2.0,
    2.0
  ],
  "change_fine_two_percent": 16.897,
  "observed_order": null,
  "extrapolated_value": null,
  "gci_fine_percent": null,
  "converged": false,
  "recommendation": "The result changes MORE as the mesh gets finer. For a peak stress at a sharp corner this is a stress singularity: the value will never converge. Read stress away from the corner, model the real fillet radius, or use deflection instead.",
  "notes": []
}
```

## 4a. Invalid input (schema): negative load

**Request** `tools/call` → `bending_stress`
```json
{
  "material": "Al 6061-T6",
  "F_N": -500,
  "L_mm": 100,
  "b_mm": 20,
  "h_mm": 10
}
```

**Response** (isError: true)
```text
Error executing tool bending_stress: 1 validation error for bending_stressArguments
F_N
  Input should be greater than 0 [type=greater_than, input_value=-500, input_type=int]
    For further information visit https://errors.pydantic.dev/2.14/v/greater_than
```

## 4b. Invalid input (domain): repeated mesh size

**Request** `tools/call` → `mesh_convergence_check`
```json
{
  "element_sizes_mm": [
    2,
    2,
    1
  ],
  "results": [
    1.0,
    1.1,
    1.2
  ]
}
```

**Response** (isError: true)
```text
Error executing tool mesh_convergence_check: Invalid input: Element sizes must all be different.
```
