# bracket-analysis MCP server

An [MCP](https://modelcontextprotocol.io) server that gives any MCP client (Claude Desktop, Claude Code,
MCP Inspector, ...) five deterministic analysis tools for a **rectangular cantilever bracket** fixed at a wall
with a point load at the free end. It was built for 24-679 Design AI (HW5) on top of the HW4 bracket-sizing agent, for
**novice ANSYS Mechanical users** who need to know whether a simulation result can be trusted.

```
 wall ||=========================  <- bracket, b x h cross-section
      ||<---------- L ---------->|
                                 v F
```

**Units everywhere:** force N, length mm, stress MPa, E GPa, density g/cm³.

| # | Tool | Origin | Purpose |
|---|------|--------|---------|
| 1 | `bending_stress` | HW4 | Nominal max bending stress at the wall |
| 2 | `tip_deflection` | HW4 | Tip deflection (Euler-Bernoulli) |
| 3 | `safety_check` | HW4 | Safety factor vs yield, pass/fail |
| 4 | `validate_fea_result` | **new** | Checks an ANSYS result against beam theory and flags setup errors |
| 5 | `mesh_convergence_check` | **new** | Grid Convergence Index: is the FEA result mesh-independent? |

Resource: `materials://library` lists the 15 preset materials (E, yield, density, plastic flag).

## Setup

Requires Python ≥ 3.10.

```bash
git clone https://github.com/ninwhippa08/bracket-mcp.git
cd bracket-mcp
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pytest -q                      # 16 tests: HW4 hand check, GCI verification, MCP end-to-end
python demo/run_demo.py        # records demo/demo_transcript.md over stdio
```

### Connect a client

**MCP Inspector** (needs Node.js), run from the repo folder:
```bash
npx @modelcontextprotocol/inspector .venv/Scripts/python -m bracket_mcp.server     # Windows
npx @modelcontextprotocol/inspector .venv/bin/python -m bracket_mcp.server         # macOS/Linux
```

**Claude Code:**
```bash
claude mcp add bracket-analysis -- /absolute/path/to/bracket-mcp/.venv/Scripts/python -m bracket_mcp.server
```
Start Claude Code from the repo folder, or set `PYTHONPATH` to it, so `bracket_mcp` can be imported.

**Claude Desktop** (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "bracket-analysis": {
      "command": "C:/absolute/path/to/bracket-mcp/.venv/Scripts/python.exe",
      "args": ["-m", "bracket_mcp.server"],
      "env": { "PYTHONPATH": "C:/absolute/path/to/bracket-mcp" }
    }
  }
}
```

## Shared assumptions

Euler-Bernoulli beam (slender, L/h ≥ 10), linear-elastic isotropic material, small deflection (δ/L ≤ 5%), ideal
fixed support, end point load, self-weight neglected, nominal stress (Kt = 1). Composites are not supported.
Every result carries a `warnings` list when an input leaves the valid range: L/h < 10, stress ≥ yield,
δ/L > 5%, or a plastic material (creep, temperature).

## Tool reference

All tools are read-only and deterministic (`readOnlyHint`, `idempotentHint`). Inputs are validated by a JSON
Schema generated from Pydantic types. Each tool publishes an `outputSchema` and returns `structuredContent`.

Common inputs: `material` (enum of 15 presets), `F_N` (0, 1e6] N, `L_mm` (0, 5000] mm, `b_mm` (0, 1000] mm,
`h_mm` (0, 1000] mm.

### 1. `bending_stress` (HW4)
- **Method:** σ = 6FL/(bh²) at the top/bottom surface of the fixed end.
- **Inputs:** common inputs.
- **Output:** `max_stress_MPa`, `yield_MPa`, `location`, `warnings`.

### 2. `tip_deflection` (HW4)
- **Method:** δ = FL³/(3EI) = 4FL³/(Ebh³).
- **Inputs:** common inputs.
- **Output:** `tip_deflection_mm`, `deflection_to_length_percent`, `warnings`.

### 3. `safety_check` (HW4)
- **Method:** SF = Sy/σ. Static yield on nominal stress only; no fatigue, no Kt.
- **Inputs:** common inputs plus `required_SF` [1, 10].
- **Output:** `max_stress_MPa`, `yield_MPa`, `safety_factor`, `required_SF`, `passes`, `warnings`.

### 4. `validate_fea_result` (new)
Answers *"Is my ANSYS result believable?"*
| Input | Unit | Range | Required |
|---|---|---|---|
| common bracket inputs | | | yes |
| `fea_tip_deflection_mm` | mm | (0, 1e4] | yes |
| `fea_peak_stress_MPa` (max von Mises) | MPa | (0, 1e6] | yes |
| `fea_probe_stress_MPa` (top surface, away from the wall) | MPa | (0, 1e6] | no |
| `probe_distance_mm` (from the wall) | mm | 0 < x < L | with probe |
| `fea_reaction_force_N` | N | ≤ 1e6 | no |

Checks:
1. **Reaction force vs applied load.** Catches a wrong load, wrong units, or an extra support carrying load.
2. **Tip deflection** vs δ_bending + δ_shear, where δ_shear = FL/(κGA), κ = 5/6 and G = E/(2(1+ν)). Deflection is
   a global quantity, so it is the most reliable check.
3. **Probe stress** vs σ(x) = 6F(L−x)/(bh²).
4. **Wall peak stress / nominal.** Classified as `near_nominal` (≤1.3×), `elevated_corner` (≤3×) or
   `likely_singularity` (>3×). A sharp re-entrant corner gives a peak that grows as the mesh is refined, so the
   peak is never used for the verdict.

Bands: `agrees` ≤ 5%, `check` 5–15%, `mismatch` > 15%. Ratios near ×1000, ×10⁶ or ×9.81 trigger a units hint.

**Output:** `verdict` (`consistent_with_beam_theory` / `plausible_check_details` / `setup_error_likely`), `checks[]`
(expected, FEA, ratio, % difference, status), `likely_causes[]`, `assumptions[]`, `warnings[]`.

### 5. `mesh_convergence_check` (new)
Answers *"Is my mesh fine enough?"*
| Input | Unit | Range |
|---|---|---|
| `element_sizes_mm` | mm | 3–8 values, each in (0, 1000], all different, any order |
| `results` | unit of the quantity | same length, finite |
| `target_gci_percent` | % | (0, 50], default 5 |

**Method:** Celik et al. (2008), *J. Fluids Eng.* 130(7), 078001. It uses the three finest meshes, the refinement
ratios r21 and r32 (non-constant ratios are allowed), and the observed order p from fixed-point iteration. It then
computes the Richardson extrapolation φ_ext = (r21^p φ1 − φ2)/(r21^p − 1) and GCI_fine = 1.25·|(φ2−φ1)/φ1| / (r21^p − 1).

**Output:** `behavior` (`monotonic` / `oscillatory` / `diverging` / `converged_identical`), `observed_order`,
`extrapolated_value`, `gci_fine_percent`, `converged`, `recommendation`, `notes`. `diverging` means the changes get
larger as the mesh is refined, which is the signature of a stress singularity.

## Invalid-input behavior

There are two layers, and both return a normal MCP result with `isError: true` and a readable message, so the
client can fix the call and retry:
1. **Schema layer:** out-of-range or missing arguments, or an unknown material, are rejected before any math
   runs. Example: `F_N = -500` → `Input should be greater than 0`.
2. **Domain layer:** inputs that are well-typed but inconsistent give a message starting `Invalid input: ...`.
   Examples: repeated mesh sizes, a probe stress without a probe distance, a probe beyond L.

See `demo/demo_transcript.md` for a recorded session.

## Client vs server responsibilities

| Server (this repo) | Client (LLM app / Inspector) |
|---|---|
| Validates types, units and ranges | Turns the user's words into arguments and converts units (in → mm, kN → N) |
| Runs deterministic closed-form math | Decides which tool to call and in what order (e.g. validate, then converge) |
| Returns structured results plus warnings and likely causes | Explains the results in plain language and relays every warning |
| Holds the material data | Asks the user for missing inputs instead of guessing |
| Never calls ANSYS or reads files | Reads numbers out of ANSYS (or asks the user to) |

## What a human must verify

- The bracket really matches the model: rectangular section, fixed wall, end load, no holes or fillets.
  Otherwise the "expected" values are wrong.
- The FEA numbers were read correctly: the right result type (von Mises vs normal stress), units, and location.
- The material values match the real supplier datasheet.
- A `consistent_with_beam_theory` verdict means the result is *not obviously wrong*, not that the design is safe.
  Fatigue, buckling, joints and stress concentrations still need engineering review.
