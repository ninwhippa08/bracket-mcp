"""End-to-end tests through a real MCP client session (in-process transport)."""

import pytest

from mcp import Client

from bracket_mcp.server import mcp

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_lists_five_tools_with_schemas():
    async with Client(mcp) as client:
        tools = (await client.list_tools()).tools
        names = {t.name for t in tools}
        assert names == {"bending_stress", "tip_deflection", "safety_check",
                         "validate_fea_result", "mesh_convergence_check"}
        for t in tools:
            assert t.output_schema is not None, t.name
        bs = next(t for t in tools if t.name == "bending_stress")
        assert bs.input_schema["properties"]["F_N"]["exclusiveMinimum"] == 0
        assert "Al 6061-T6" in bs.input_schema["properties"]["material"]["enum"]


async def test_original_tool_structured_result():
    async with Client(mcp) as client:
        r = await client.call_tool("bending_stress", {"material": "Al 6061-T6", "F_N": 500,
                                                      "L_mm": 100, "b_mm": 20, "h_mm": 10})
        assert not r.is_error
        assert r.structured_content["max_stress_MPa"] == pytest.approx(150.0)


async def test_invalid_input_is_rejected_by_schema():
    async with Client(mcp) as client:
        r = await client.call_tool("bending_stress", {"material": "Al 6061-T6", "F_N": -500,
                                                      "L_mm": 100, "b_mm": 20, "h_mm": 10})
        assert r.is_error
        assert "F_N" in r.content[0].text


async def test_domain_error_is_reported():
    async with Client(mcp) as client:
        r = await client.call_tool("mesh_convergence_check",
                                   {"element_sizes_mm": [2, 2, 1], "results": [1.0, 1.1, 1.2]})
        assert r.is_error
        assert "different" in r.content[0].text


async def test_material_resource():
    async with Client(mcp) as client:
        res = await client.read_resource("materials://library")
        assert "Al 6061-T6" in res.contents[0].text
