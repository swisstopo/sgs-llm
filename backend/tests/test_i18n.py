"""Progress labels the user reads while a turn runs."""

from __future__ import annotations

import pytest

from app.i18n import TOOL_RUNNING, tool_running

# Romansh is deliberately absent from these tables and falls back to German, so the bar
# is "the same languages as every other label", not "every supported language".
LABELLED = set(TOOL_RUNNING["search_layers"])


@pytest.mark.parametrize("tool", sorted(TOOL_RUNNING))
def test_every_labelled_tool_covers_every_language(tool: str) -> None:
    assert set(TOOL_RUNNING[tool]) == LABELLED


def test_the_geosearch_tools_are_all_labelled() -> None:
    """The tool set the deployed server serves. A missing entry is not a failure, it
    renders as "Running tool: display_division" mid-answer."""
    for tool in (
        "search_layers",
        "search_locations",
        "filter_features",
        "compute",
        "display_layer",
        "display_catalog_layer",
        "display_division",
    ):
        assert tool in TOOL_RUNNING, tool


def test_an_unknown_tool_still_names_itself() -> None:
    assert tool_running("summarise_wetlands", "de") == "Führe Werkzeug aus: summarise_wetlands"
