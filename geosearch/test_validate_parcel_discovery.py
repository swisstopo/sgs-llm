from typing import Any
import pytest
from mcp.server import MCPServer

from .validate_parcel_discovery import MAP, PARCEL, assess, validate


def test_rank_and_product_distinction():
    raw = {"layers": [{"layer_id": PARCEL}, {"layer_id": MAP}]}
    result = assess(raw, PARCEL)
    assert result["passed"]
    assert result["expected_rank"] == 1
    assert result["other_cadastral_rank"] == 2
    assert result["raw"] == raw
    assert not assess(raw, MAP)["passed"]


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        {"layers": []},
        {"layers": [{}]},
        {"layers": [{"layer_id": PARCEL}], "note": "Vector similarity only"},
        {"layers": [{"layer_id": PARCEL}, {"layer_id": PARCEL}]},
        {"layers": [{"layer_id": str(i)} for i in range(3)] + [{"layer_id": PARCEL}]},
    ],
)
def test_incomplete_or_degraded_results_cannot_pass(data):
    assert not assess(data, PARCEL)["passed"]


@pytest.mark.anyio
async def test_mcp_results_and_errors_are_preserved():
    server = MCPServer(name="ranking-contract")

    @server.tool()
    async def search_layers(query: str, lang: str, top_n: int) -> dict[str, Any]:
        if query == "EGRID":
            raise ValueError("upstream unavailable")
        layer = MAP if query.startswith("Katasterplan") else PARCEL
        return {"layers": [{"layer_id": layer}]}

    report = await validate(server)
    assert not report["passed"]
    assert len(report["queries"]) == 4
    assert report["queries"][0].get("expected_rank") == 1, report
    assert not report["queries"][2]["passed"]
    assert report["queries"][3]["passed"]
