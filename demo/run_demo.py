"""Record a demo session: launch the server over stdio with the official MCP Python client,
list the tools, make the required calls, and write every request/response to demo_transcript.md.

Run from the repo root:  .venv/Scripts/python demo/run_demo.py   (Windows)
                         .venv/bin/python demo/run_demo.py       (macOS/Linux)

The FEA numbers below are ILLUSTRATIVE inputs for the hand-check bracket (Al 6061-T6, 500 N,
100 x 20 x 10 mm); replace them with values read from your own ANSYS Mechanical model.
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).with_name("demo_transcript.md")
BRACKET = {"material": "Al 6061-T6", "F_N": 500, "L_mm": 100, "b_mm": 20, "h_mm": 10}

CALLS = [
    ("1. Original tool: safety_check", "safety_check", {**BRACKET, "required_SF": 2.0}),
    ("2. New tool: validate_fea_result (ANSYS run of the same bracket)", "validate_fea_result",
     {**BRACKET, "fea_tip_deflection_mm": 1.50, "fea_peak_stress_MPa": 212.0,
      "fea_probe_stress_MPa": 104.0, "probe_distance_mm": 30, "fea_reaction_force_N": 500.0}),
    ("3a. New tool: mesh_convergence_check on tip deflection [mm]", "mesh_convergence_check",
     {"element_sizes_mm": [5, 2.5, 1.25, 0.625], "results": [1.452, 1.489, 1.497, 1.499]}),
    ("3b. New tool: mesh_convergence_check on wall peak stress [MPa]", "mesh_convergence_check",
     {"element_sizes_mm": [5, 2.5, 1.25, 0.625], "results": [180.0, 205.0, 241.0, 290.0]}),
    ("4a. Invalid input (schema): negative load", "bending_stress", {**BRACKET, "F_N": -500}),
    ("4b. Invalid input (domain): repeated mesh size", "mesh_convergence_check",
     {"element_sizes_mm": [2, 2, 1], "results": [1.0, 1.1, 1.2]}),
]


def block(obj) -> str:
    return "```json\n" + json.dumps(obj, indent=2, ensure_ascii=False) + "\n```"


async def main() -> None:
    params = StdioServerParameters(command=sys.executable, args=["-m", "bracket_mcp.server"], cwd=str(ROOT))
    lines = [f"# Demo transcript: bracket-analysis MCP server",
             f"Recorded {datetime.now():%Y-%m-%d %H:%M} with the official MCP Python client over stdio "
             f"(`{Path(sys.executable).name} -m bracket_mcp.server`).", ""]
    async with Client(params) as client:
        tools = (await client.list_tools()).tools
        lines += ["## tools/list", "", "| tool | inputs (required*) |", "|---|---|"]
        for t in tools:
            req = set(t.input_schema.get("required", []))
            args = ", ".join(f"{k}{'*' if k in req else ''}" for k in t.input_schema["properties"])
            lines.append(f"| `{t.name}` | {args} |")
        lines.append("")
        for title, name, args in CALLS:
            r = await client.call_tool(name, args)
            lines += [f"## {title}", "", f"**Request** `tools/call` → `{name}`", block(args), "",
                      f"**Response** (isError: {str(r.is_error).lower()})"]
            lines.append(block(r.structured_content) if r.structured_content and not r.is_error
                         else "```text\n" + "\n".join(c.text for c in r.content if hasattr(c, "text")) + "\n```")
            lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
