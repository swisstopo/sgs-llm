"""Record parcel search rankings from a real geosearch MCP endpoint.

Run with python -m geosearch.validate_parcel_discovery --mcp-url URL --output report.json.
This checks discovery only; the separate no-hint agent evaluation checks the workflow.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp import Client

PARCEL = "ch.swisstopo-vd.amtliche-vermessung"
MAP = "ch.kantone.cadastralwebmap-farbe"
CASES = (
    ("Parzelle", "de", PARCEL),
    ("parcelle", "fr", PARCEL),
    ("EGRID", "de", PARCEL),
    ("Katasterplan Belp", "de", MAP),
)


def assess(data: Any, expected: str) -> dict[str, Any]:
    """Keep exact output alongside ranks, including a failure or vector-only warning."""
    layers = data.get("layers") if isinstance(data, dict) else None
    if not isinstance(layers, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("layer_id"), str)
        for row in layers
    ):
        return {"passed": False, "error": "Malformed search_layers result", "raw": data}
    ids = [row["layer_id"] for row in layers]
    rank = ids.index(expected) + 1 if expected in ids else None
    other = MAP if expected == PARCEL else PARCEL
    other_rank = ids.index(other) + 1 if other in ids else None
    # The expected dataset must be prominent and precede the other cadastral product.
    # Vector-only fallback is useful evidence but cannot validate the reranker.
    return {
        "passed": bool(
            rank
            and rank <= 3
            and (not other_rank or rank < other_rank)
            and not data.get("note")
            and len(set(ids)) == len(ids)
        ),
        "expected_rank": rank,
        "other_cadastral_rank": other_rank,
        "ranked_layer_ids": ids,
        "raw": data,
    }


async def validate(url: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "checked_at": datetime.now(UTC).isoformat(),
        "mcp_url": url,
        "scope": "search_layers rankings only",
        "passed": False,
        "queries": rows,
    }
    try:
        async with asyncio.timeout(240), Client(url) as client:
            for query, lang, expected in CASES:
                row: dict[str, Any] = {
                    "query": query,
                    "lang": lang,
                    "expected": expected,
                }
                rows.append(row)
                try:
                    async with asyncio.timeout(55):
                        result = await client.call_tool(
                            "search_layers", {"query": query, "lang": lang, "top_n": 8}
                        )
                    row.update(assess(result.structured_content, expected))
                    if result.is_error:
                        row.update(passed=False, error="MCP tool returned an error")
                except Exception as exc:
                    row.update(passed=False, error=f"{type(exc).__name__}: {exc}")
        report["passed"] = len(rows) == len(CASES) and all(
            row["passed"] for row in rows
        )
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mcp-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(validate(args.mcp_url))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"{'PASS' if report['passed'] else 'FAIL'}: {args.output}")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
