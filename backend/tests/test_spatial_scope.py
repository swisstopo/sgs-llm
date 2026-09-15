"""The agent must accept whole-object selection and preserve it on retries."""

import pytest

from app.agent.loop import _named_filter_scope, _restore_failed_named_scope, _verify_named_filter
from app.mcp.client import ToolOutcome


@pytest.mark.parametrize("mode,key", [("intersects", "selected_by"), ("clip", "clipped_to")])
def test_agent_accepts_only_the_requested_spatial_operation(mode, key):
    arguments = {
        "layer_id": "ch.parks",
        "place": "Bern",
        "place_kind": "kanton",
        "spatial_mode": mode,
    }
    outcome = ToolOutcome(
        is_error=False, text="complete", data={"result_id": "fs_1", key: "kanton Bern"}
    )
    assert _verify_named_filter("filter_features", arguments, outcome) is outcome
    other = "clipped_to" if key == "selected_by" else "selected_by"
    wrong = ToolOutcome(
        is_error=False, text="wrong operation", data={"result_id": "fs_2", other: "kanton Bern"}
    )
    assert _verify_named_filter("filter_features", arguments, wrong).is_error


def test_bbox_retry_preserves_whole_object_selection():
    scope = _named_filter_scope(
        "filter_features", {"place": "Bern", "place_kind": "kanton", "spatial_mode": "intersects"}
    )
    restored = _restore_failed_named_scope(
        "filter_features", {"layer_id": "ch.parks", "bbox": [7, 46, 8, 47]}, {"ch.parks": scope}
    )
    assert restored == {
        "layer_id": "ch.parks",
        "place": "Bern",
        "place_kind": "kanton",
        "spatial_mode": "intersects",
    }


def test_reference_scope_is_verified_and_preserved_on_bbox_retry():
    arguments = {
        "layer_id": "ch.parks",
        "place_ref": "divisions/BE/bern",
        "spatial_mode": "intersects",
    }
    scope = _named_filter_scope("filter_features", arguments)
    restored = _restore_failed_named_scope(
        "filter_features", {"layer_id": "ch.parks", "bbox": [7, 46, 8, 47]}, {"ch.parks": scope}
    )
    assert restored == arguments
    data = {"result_id": "fs_1", "selected_by": "kanton Bern", "division_ref": "divisions/BE/bern"}
    outcome = ToolOutcome(text="selected", data=data, is_error=False)
    assert _verify_named_filter("filter_features", arguments, outcome) is outcome
    data["division_ref"] = "divisions/ZG/zug"
    assert _verify_named_filter("filter_features", arguments, outcome).is_error
