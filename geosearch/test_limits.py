"""Large-query bounds and adaptive pagination.

These tests deliberately avoid geo.admin.ch. A limit that is only exercised against a
live dense layer is a production incident waiting to happen.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from .limits import MAX_FEATURES, FeatureBudget
from .swisstopo import CellResult, Swisstopo


def _point(
    feature_id: object, coordinates: list[float] | None = None
) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": feature_id,
        "geometry": {"type": "Point", "coordinates": coordinates or [7.0, 46.0]},
        "properties": {"name": str(feature_id)},
    }


def test_default_budget_is_exactly_one_hundred_thousand_features() -> None:
    assert MAX_FEATURES == 100_000


def test_budget_refuses_the_first_feature_past_its_count_limit() -> None:
    budget = FeatureBudget(max_features=2, max_coordinates=100, max_bytes=10_000)

    assert budget.add(_point(1))
    assert budget.add(_point(2))
    assert not budget.add(_point(3))
    assert budget.reason == "feature_limit"
    assert budget.feature_count == 2


def test_budget_counts_every_coordinate_position() -> None:
    budget = FeatureBudget(max_features=10, max_coordinates=2, max_bytes=10_000)

    assert budget.add(_point(1))
    assert not budget.add(
        {
            "type": "Feature",
            "id": 2,
            "geometry": {"type": "LineString", "coordinates": [[7, 46], [8, 47]]},
            "properties": {},
        }
    )
    assert budget.reason == "coordinate_limit"


def test_budget_accounts_for_uncompressed_json_bytes() -> None:
    feature = _point(1)
    generous = FeatureBudget(max_features=10, max_coordinates=100, max_bytes=10_000)
    assert generous.add(feature)

    budget = FeatureBudget(
        max_features=10,
        max_coordinates=100,
        max_bytes=generous.byte_count - 1,
    )
    assert not budget.add(feature)
    assert budget.reason == "byte_limit"


def test_capped_parent_is_discarded_and_replaced_by_four_children() -> None:
    api = Swisstopo()
    parent = (7.0, 46.0, 8.0, 47.0)
    calls: list[tuple[float, float, float, float]] = []

    async def newest(_layer_id: str, _lang: str) -> str | None:
        return None

    async def fetch_cell(
        _layer_id: str,
        cell: tuple[float, float, float, float],
        _lang: str,
        _instant: str | None,
    ) -> CellResult:
        calls.append(cell)
        if cell == parent:
            return CellResult([_point("discard-me")], capped=True)
        return CellResult([_point(str(cell))], capped=False)

    api._newest_timestamp = newest  # type: ignore[assignment]
    api._fetch_cell = fetch_cell  # type: ignore[assignment]

    result = asyncio.run(api.fetch_features("ch.test", parent, grid=1))

    assert result.complete
    assert result.capped_cells == 1
    assert len(result.features) == 4
    assert all(feature["id"] != "discard-me" for feature in result.features)
    assert len(calls) == 5


def test_a_failed_cell_marks_the_result_incomplete_without_losing_other_cells() -> None:
    api = Swisstopo()

    async def newest(_layer_id: str, _lang: str) -> str | None:
        return None

    calls = 0

    async def fetch_cell(
        _layer_id: str,
        _cell: tuple[float, float, float, float],
        _lang: str,
        _instant: str | None,
    ) -> CellResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("upstream broke")
        return CellResult([_point(calls)], capped=False)

    api._newest_timestamp = newest  # type: ignore[assignment]
    api._fetch_cell = fetch_cell  # type: ignore[assignment]

    result = asyncio.run(api.fetch_features("ch.test", [7, 46, 8, 47], grid=2))

    assert not result.complete
    assert result.limit_reason == "upstream_cell_failure"
    assert result.failed_cells == 1
    assert len(result.features) == 3


@pytest.mark.asyncio
async def test_cancelling_a_query_cancels_all_inflight_cell_requests() -> None:
    api = Swisstopo()
    started = 0
    cancelled = 0
    release = asyncio.Event()

    async def newest(_layer_id: str, _lang: str) -> str | None:
        return None

    async def fetch_cell(*_args: Any) -> CellResult:
        nonlocal started, cancelled
        started += 1
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled += 1
            raise
        return CellResult([], capped=False)

    api._newest_timestamp = newest  # type: ignore[assignment]
    api._fetch_cell = fetch_cell  # type: ignore[assignment]
    request = asyncio.create_task(api.fetch_features("ch.test", [7, 46, 8, 47], grid=4))
    while started == 0:
        await asyncio.sleep(0)
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    await asyncio.sleep(0)

    assert cancelled == started
