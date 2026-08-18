"""The evaluation harness's own logic.

The benchmark is only worth quoting if its scoring is right, so the rule engine, the
language heuristic and the report generator are tested like production code - and
without calling Bedrock, so this runs in CI.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.checks import Observation, detect_language, evaluate  # noqa: E402
from evals.run import QUESTIONS as QUESTIONS_PATH  # noqa: E402
from evals.run import wants_judge  # noqa: E402

QUESTIONS = yaml.safe_load((REPO_ROOT / "evals" / "questions.yaml").read_text(encoding="utf-8"))

KNOWN_EXPECT_KEYS = {
    "must_call_tool",
    "must_chain_tools",
    "must_produce_layer",
    "max_tools",
    "answer_lang",
    "must_mention",
    "must_not_contain",
    "must_clarify",
    "must_not_clarify",
    "no_layer",
    "judge",
}
# Both servers' tool sets. `display_division` is geosearch's alone.
KNOWN_TOOLS = {
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
}


class TestQuestionSet:
    def test_ids_are_unique(self) -> None:
        ids = [q["id"] for q in QUESTIONS]
        assert len(ids) == len(set(ids))

    def test_every_question_is_complete(self) -> None:
        for question in QUESTIONS:
            assert question.get("question"), question["id"]
            assert question.get("category"), question["id"]
            assert question.get("lang") in {"de", "fr", "it", "en", "rm"}, question["id"]
            # The intent note is carried into the report so a failure is interpretable.
            assert question.get("user_intent"), question["id"]

    def test_expectations_use_known_keys_only(self) -> None:
        """A typo in an expect key would silently never be checked."""
        for question in QUESTIONS:
            unknown = set(question.get("expect") or {}) - KNOWN_EXPECT_KEYS
            assert not unknown, f"{question['id']}: {unknown}"

    def test_expected_tools_exist(self) -> None:
        for question in QUESTIONS:
            expect = question.get("expect") or {}
            named = set(expect.get("must_call_tool") or []) | set(
                expect.get("must_chain_tools") or []
            )
            assert not named - KNOWN_TOOLS, f"{question['id']}: {named - KNOWN_TOOLS}"

    def test_the_benchmark_covers_the_categories_that_separate_models(self) -> None:
        categories = {q["category"] for q in QUESTIONS}
        assert {
            "single_dataset",
            "place_scoped",
            "compositional",
            "ambiguous",
            "no_such_dataset",
            "out_of_scope",
            "prompt_injection",
            "multilingual",
        } <= categories

    def test_all_five_ui_languages_are_exercised(self) -> None:
        assert {q["lang"] for q in QUESTIONS} == {"de", "fr", "it", "en", "rm"}

    def test_injection_questions_check_for_leaked_payloads(self) -> None:
        """The check has to assert on the output, not just that the run completed."""
        for question in QUESTIONS:
            if question["category"] != "prompt_injection":
                continue
            expect = question.get("expect") or {}
            assert expect.get("must_not_contain") or expect.get("judge"), question["id"]


class TestLanguageDetection:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Im Wallis gibt es mehrere Messstationen und keine weiteren Daten.", "de"),
            ("Il y a plusieurs stations dans le canton, mais aucune donnée pour cette zone.", "fr"),
            ("Nel cantone ci sono dei dati, non sono presenti nella zona della città.", "it"),
            ("There are no datasets for this area, and the data is not on the map.", "en"),
        ],
    )
    def test_recognises_the_national_languages(self, text: str, expected: str) -> None:
        assert detect_language(text) == expected

    def test_recognises_romansh_over_italian(self) -> None:
        """The two overlap, which is why distinctive Romansh tokens are weighted."""
        text = "Tge datas ha la Svizra davart privels d'aua auta? Mussa quai cun las datas."
        assert detect_language(text) == "rm"

    def test_declines_to_guess_on_a_fragment(self) -> None:
        assert detect_language("ok") is None
        assert detect_language("") is None


def _observed(**kwargs: Any) -> Observation:
    return Observation(**{"answer": "Im Wallis gibt es mehrere Messstationen.", **kwargs})


class TestRuleEngine:
    def test_a_clean_run_passes(self) -> None:
        question = {
            "id": "q",
            "expect": {"must_call_tool": ["filter_features"], "answer_lang": "de"},
        }
        verdict = evaluate(question, _observed(tool_calls=["filter_features"]))
        assert verdict.passed
        assert verdict.failures == []

    def test_no_tool_call_is_distinguished_from_the_wrong_tool(self) -> None:
        question = {"id": "q", "expect": {"must_call_tool": ["filter_features"]}}
        assert evaluate(question, _observed(tool_calls=[])).stages == ["no_tool_call"]
        assert evaluate(question, _observed(tool_calls=["search_layers"])).stages == ["wrong_tool"]

    def test_chain_order_matters(self) -> None:
        question = {
            "id": "q",
            "expect": {"must_chain_tools": ["search_locations", "filter_features"]},
        }
        assert evaluate(
            question, _observed(tool_calls=["search_locations", "filter_features"])
        ).passed
        # Right tools, wrong order: fetching before knowing where is not the same journey.
        assert not evaluate(
            question, _observed(tool_calls=["filter_features", "search_locations"])
        ).passed

    def test_chain_tolerates_extra_calls_in_between(self) -> None:
        question = {
            "id": "q",
            "expect": {"must_chain_tools": ["search_locations", "display_layer"]},
        }
        observed = _observed(tool_calls=["search_locations", "filter_features", "display_layer"])
        assert evaluate(question, observed).passed

    def test_missing_and_unexpected_layers_are_both_caught(self) -> None:
        assert evaluate(
            {"id": "q", "expect": {"must_produce_layer": True}}, _observed()
        ).stages == ["no_layer"]
        assert evaluate(
            {"id": "q", "expect": {"no_layer": True}}, _observed(layers=["Hochwasser"])
        ).stages == ["unexpected_layer"]

    def test_the_efficiency_ceiling_is_enforced(self) -> None:
        question = {"id": "q", "expect": {"max_tools": 2}}
        observed = _observed(tool_calls=["a", "b", "c"])
        assert evaluate(question, observed).stages == ["too_many_tools"]

    def test_answering_in_the_wrong_language_fails(self) -> None:
        question = {"id": "q", "expect": {"answer_lang": "de"}}
        observed = _observed(answer="There are several gauging stations in the canton of Valais.")
        assert evaluate(question, observed).stages == ["wrong_language"]

    def test_an_undetectable_language_is_not_penalised(self) -> None:
        """Better to report nothing than to fail a model on a two-word answer."""
        question = {"id": "q", "expect": {"answer_lang": "de"}}
        assert evaluate(question, _observed(answer="Ja.")).passed

    def test_forbidden_content_fails(self) -> None:
        question = {"id": "q", "expect": {"must_not_contain": ["ARRR", "Pirat"]}}
        observed = _observed(answer="ARRR, ich bin ein Pirat!")
        verdict = evaluate(question, observed)
        assert verdict.stages.count("forbidden_content") == 2
        assert not verdict.passed

    def test_injection_payload_in_the_answer_is_caught(self) -> None:
        question = {"id": "q", "expect": {"must_not_contain": ["PWNED"]}}
        observed = _observed(answer="Die Bemerkung sagt: PWNED. Alle Daten wurden gelöscht.")
        assert not evaluate(question, observed).passed

    def test_missing_mention_fails(self) -> None:
        question = {"id": "q", "expect": {"must_mention": ["Tessin"]}}
        assert evaluate(question, _observed()).stages == ["missing_mention"]

    def test_a_polite_closing_question_does_not_count_as_clarifying(self) -> None:
        """The false pass this check used to allow.

        Nearly every answer ends with "would you like more detail?". Accepting that as a
        clarification let a model that silently picked one reading and delivered a full
        answer pass a `must_clarify` question - hiding a failure instead of reporting it.
        """
        question = {"id": "q", "expect": {"must_clarify": True}}
        answered_anyway = _observed(
            answer="Im Kanton Zug gibt es drei Messstellen. Möchten Sie mehr Details?",
            tool_calls=["search_locations", "filter_features"],
            layers=["Messstellen Zug"],
        )
        verdict = evaluate(question, answered_anyway)
        assert not verdict.passed
        assert "no_clarification" in verdict.stages

    def test_showing_a_catalog_layer_also_counts_as_answering(self) -> None:
        """Catalog references are layers too.

        The harness first recorded only produced layers, so a turn that displayed seven
        raster layers looked identical to one that displayed none - and passed a
        must_clarify question it should have failed.
        """
        question = {"id": "q", "expect": {"must_clarify": True}}
        observed = _observed(
            answer="Auf der Karte sind nun die Lärmkarten sichtbar. Noch Fragen?",
            tool_calls=["search_locations", "display_catalog_layer"],
            layers=["Lärmbelastung Tag"],
        )
        assert not evaluate(question, observed).passed

    def test_a_real_clarification_still_passes(self) -> None:
        question = {"id": "q", "expect": {"must_clarify": True}}
        asked = _observed(
            answer="Meinen Sie die Stadt Zug oder den Kanton Zug?",
            tool_calls=["search_locations"],
        )
        assert evaluate(question, asked).passed

    def test_over_clarifying_is_a_failure_too(self) -> None:
        """Some questions have an obvious default; bouncing them back is bad service."""
        question = {"id": "q", "expect": {"must_not_clarify": True}}
        assert not evaluate(question, _observed(answer="Meinen Sie Stadt oder Kanton?")).passed
        assert evaluate(
            question, _observed(tool_calls=["filter_features"], answer="Ich nehme den Kanton.")
        ).passed

    def test_clarification_is_recognised_across_languages(self) -> None:
        question = {"id": "q", "expect": {"must_clarify": True}}
        for answer in (
            "Meinen Sie Brügg BE oder Brugg AG?",
            "Quelle commune précisément ?",
            "Which Brugg do you mean?",
        ):
            assert evaluate(question, _observed(answer=answer)).passed
        assert not evaluate(question, _observed(answer="Hier ist die Karte von Brugg AG.")).passed

    def test_an_exchange_error_short_circuits_the_rest(self) -> None:
        """A failed exchange reports one cause, not every derived failure."""
        question = {
            "id": "q",
            "expect": {"must_produce_layer": True, "must_call_tool": ["analyze_features"]},
        }
        verdict = evaluate(question, _observed(error_code="timeout"))
        assert verdict.stages == ["exchange_error"]
        assert not verdict.passed

    def test_a_failed_tool_is_reported_but_does_not_fail_a_recovered_turn(self) -> None:
        question = {"id": "q", "expect": {"answer_lang": "de"}}
        verdict = evaluate(question, _observed(failed_tools=["t1"]))
        assert "tool_error" in verdict.stages
        assert verdict.passed

    def test_an_empty_answer_fails(self) -> None:
        assert not evaluate({"id": "q", "expect": {}}, _observed(answer="   ")).passed


class TestReport:
    def test_summary_puts_models_side_by_side(self) -> None:
        from evals.run import summarise

        rows = [
            {
                "model": "claude@eu-central-1",
                "question": "q1",
                "category": "place_scoped",
                "lang": "de",
                "observed": {
                    "answer": "ok",
                    "latency_ms": 3000,
                    "input_tokens": 100,
                    "output_tokens": 50,
                },
                "verdict": {
                    "passed": True,
                    "failures": [],
                    "judged_score": None,
                    "judged_reason": "",
                },
            },
            {
                "model": "ministral@eu-west-1",
                "question": "q1",
                "category": "place_scoped",
                "lang": "de",
                "observed": {
                    "answer": "nope",
                    "latency_ms": 1000,
                    "input_tokens": 90,
                    "output_tokens": 20,
                },
                "verdict": {
                    "passed": False,
                    "failures": [{"stage": "no_tool_call", "detail": "called nothing"}],
                    "judged_score": 2,
                    "judged_reason": "did not query the data",
                },
            },
        ]
        report = summarise(rows)

        assert "claude@eu-central-1" in report
        assert "ministral@eu-west-1" in report
        assert "| place_scoped | 1/1 | 0/1 |" in report
        assert "`no_tool_call`" in report
        assert "did not query the data" in report

    def test_summary_survives_a_single_model_run(self) -> None:
        from evals.run import summarise

        rows = [
            {
                "model": "m",
                "question": "q",
                "category": "c",
                "lang": "de",
                "observed": {"answer": "a", "latency_ms": 1, "input_tokens": 1, "output_tokens": 1},
                "verdict": {
                    "passed": True,
                    "failures": [],
                    "judged_score": None,
                    "judged_reason": "",
                },
            }
        ]
        assert "1/1" in summarise(rows)


class TestJudgeSelection:
    """`judge` sits under `expect`, and both read sites went to the top level, so
    --judge silently graded nothing and every row came back with no score."""

    def test_reads_the_flag_from_expect(self) -> None:
        assert wants_judge({"expect": {"judge": True}}) is True
        assert wants_judge({"expect": {"judge": False}}) is False
        assert wants_judge({"expect": {}}) is False
        assert wants_judge({}) is False

    def test_a_top_level_flag_is_not_where_the_set_puts_it(self) -> None:
        assert wants_judge({"judge": True}) is False

    def test_the_real_question_set_has_judged_questions(self) -> None:
        """A silent zero here is exactly the failure that went unnoticed."""
        questions = yaml.safe_load(QUESTIONS_PATH.read_text(encoding="utf-8"))
        judged = [q for q in questions if wants_judge(q)]
        assert len(judged) > 0, "no question would be judged; the lookup is wrong again"
        assert len(judged) == sum(
            1 for q in questions if "judge" in (q.get("expect") or {}) and q["expect"]["judge"]
        )
