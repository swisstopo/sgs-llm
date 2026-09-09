"""Pins each prompt rule a swisstopo test finding produced.

The prompt is the deliverable for most of those findings, so a rule silently dropped by a
later edit is a regression with no other detector. Each class names the questions from
swisstopo's 2026-09-08 round that it answers.
"""

from __future__ import annotations

import pytest

from app.agent.prompts import system_prompt


@pytest.fixture
def prompt() -> str:
    return system_prompt("de")


class TestDisplayDiscipline:
    """Q7: the answer counted 481 buildings and told the user to press a button that was
    never created, quoting its English label into a German interface."""

    def test_forbids_quoting_the_button_label(self, prompt: str) -> None:
        assert "Show result on map" not in prompt

    def test_forbids_describing_a_card_without_display_layer(self, prompt: str) -> None:
        assert "unless `display_layer` returned successfully" in prompt

    def test_requires_displaying_what_was_counted(self, prompt: str) -> None:
        assert "A number the user cannot see on the map is half an answer." in prompt


class TestPlaceKindDiscipline:
    """Q3: "Stadt Bern" resolved to nothing and the answer fell back to the canton.
    Q4: "in Bern" became the canton without asking. division_by_name orders
    coarsest-first and takes LIMIT 1, so an omitted kind is silently the canton."""

    def test_requires_place_kind_alongside_place(self, prompt: str) -> None:
        assert "Always pass `place_kind` together with `place`" in prompt

    def test_strips_the_administrative_word_into_the_kind(self, prompt: str) -> None:
        assert "Stadt Bern" in prompt
        assert "The word is the `kind`, not part of the `name`." in prompt

    def test_names_the_level_it_chose_when_a_name_is_canton_and_commune(self, prompt: str) -> None:
        """Sonnet resolved "in Bern" to the commune and said so, which is the behaviour
        wanted: ask only where neither reading is more likely."""
        assert "both a canton and a commune" in prompt
        assert "**name the level you used in the answer**" in prompt

    def test_asks_only_when_neither_reading_is_more_likely(self, prompt: str) -> None:
        assert "Only when neither reading is more likely" in prompt

    def test_does_not_ask_when_the_request_already_says_which(self, prompt: str) -> None:
        assert "When the request does say which, do not ask." in prompt


class TestParcelAndPlanRules:
    """Q6: the Katasterplan was identified and then not offered, and the parcel result
    alternated between a geocoded point and the real cadastral polygon."""

    def test_a_parcel_answer_is_a_polygon_not_a_point(self, prompt: str) -> None:
        assert "the answer is the parcel *polygon*, never the geocoder's point" in prompt

    def test_a_named_official_plan_is_the_answer(self, prompt: str) -> None:
        assert "Katasterplan" in prompt
        assert "do not substitute an administrative boundary" in prompt


class TestNamedFeatureRules:
    """Q5: "le parc naturel du Chasseral" names a feature, not a place.
    search_locations answers it with Chesières, Chessel and Le Châtelard - plausible
    place names with nothing to do with the park - and the model then called
    filter_features with neither place nor bbox, twice."""

    def test_a_named_feature_is_not_resolved_as_a_place(self, prompt: str) -> None:
        assert "names a specific feature rather than an area" in prompt

    def test_gives_the_nationwide_name_filter(self, prompt: str) -> None:
        assert '`place: "Schweiz"` with `place_kind: "land"`' in prompt

    def test_forbids_an_area_less_filter_call(self, prompt: str) -> None:
        assert "never call `filter_features` with neither `place` nor `bbox`" in prompt


class TestEgridRule:
    """Q6: "If I use EGRID numbers, hallucinations explode". Measured against the live
    SearchServer: CH343546791597 returns the parcel, CH 3435 4679 1597 returns nothing -
    and the spaced form is what the tools themselves put in their labels."""

    def test_an_egrid_is_passed_without_spaces(self, prompt: str) -> None:
        assert "remove the spaces from an EGRID" in prompt


class TestParcelMechanismRules:
    """Q6b. Measured against the live services: identify on ch.swisstopo-vd.amtliche-
    vermessung at the geocoder's full-precision point returns parcel number 20 with the
    matching egris_egrid as a Polygon, so the polygon IS reachable. Two things stopped
    the agent finding it - search_layers cannot surface a layer whose whole searchable
    identity is the label "OpenData-AV", and rounding the point to four decimals returns
    a neighbouring parcel (473) instead."""

    def test_names_the_cadastral_survey_dataset(self, prompt: str) -> None:
        assert "ch.swisstopo-vd.amtliche-vermessung" in prompt
        assert "OpenData-AV" in prompt

    def test_forbids_retyping_a_coordinate_from_a_tool_result(self, prompt: str) -> None:
        assert "never re-type or round a coordinate" in prompt


class TestDisambiguationIsScoped:
    """The canton-or-commune rule leaked. Asked for "die Gefahrenkarte für Brügg" — where
    several Brügg/Brugg exist — Sonnet resolved it to "Gemeinde Brügg (BE)", named the
    level as the rule says, and offered a layer instead of asking which one. That is a
    different ambiguity and must still be a question."""

    def test_bounds_the_rule_to_one_name_at_two_levels(self, prompt: str) -> None:
        assert "only where one name is both a canton and a commune" in prompt

    def test_distinct_places_sharing_a_name_are_still_a_question(self, prompt: str) -> None:
        assert "two different places" in prompt
        assert "Brügg" in prompt
