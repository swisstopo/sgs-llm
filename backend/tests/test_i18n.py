"""Progress labels the user reads while a turn runs."""

from __future__ import annotations

import pytest

from app.i18n import TOOL_RUNNING, tool_running

# Romansh is absent from these tables by design and falls back to German.
LABELLED = set(TOOL_RUNNING["search_layers"])


@pytest.mark.parametrize("tool", sorted(TOOL_RUNNING))
def test_every_labelled_tool_covers_every_language(tool: str) -> None:
    assert set(TOOL_RUNNING[tool]) == LABELLED


def test_the_geosearch_tools_are_all_labelled() -> None:
    """A missing entry renders as "Running tool: display_division" mid-answer."""
    for tool in (
        "search_layers",
        "search_locations",
        "geocode_location",
        "describe_layer",
        "identify_at_point",
        "filter_features",
        "analyze_features",
        "display_layer",
        "display_catalog_layer",
        "display_division",
    ):
        assert tool in TOOL_RUNNING, tool


def test_an_unknown_tool_still_names_itself() -> None:
    assert tool_running("summarise_wetlands", "de") == "Führe Werkzeug aus: summarise_wetlands"
