"""Rule checks for the evaluation set.

Rule-based rather than model-graded wherever a rule can decide it: deterministic and
free. Questions marked `judge: true` are graded by a model instead, and the report keeps
the two kinds of verdict apart rather than blending them.

Each failure carries a stage, so a report says where a model broke down rather than only
that it did.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Function words that distinguish the five UI languages. A heuristic, not a language
# identifier; enough to catch an answer in the wrong language, and --judge can override.
_MARKERS: dict[str, tuple[str, ...]] = {
    "de": (
        "der",
        "die",
        "das",
        "und",
        "ist",
        "nicht",
        "mit",
        "für",
        "gibt",
        "im",
        "keine",
        "sind",
        "auf",
        "eine",
        "kanton",
        "daten",
        "zeigt",
        "wurde",
    ),
    "fr": (
        "le",
        "la",
        "les",
        "des",
        "est",
        "pas",
        "avec",
        "pour",
        "dans",
        "aucun",
        "sont",
        "une",
        "canton",
        "données",
        "il",
        "y",
        "sur",
        "cette",
    ),
    "it": (
        "il",
        "lo",
        "le",
        "dei",
        "è",
        "non",
        "con",
        "per",
        "nel",
        "sono",
        "nessun",
        "una",
        "cantone",
        "dati",
        "della",
        "questo",
        "sulla",
    ),
    "en": (
        "the",
        "and",
        "is",
        "not",
        "with",
        "for",
        "there",
        "are",
        "of",
        "no",
        "this",
        "data",
        "canton",
        "on",
        "map",
        "found",
    ),
    # Rumantsch Grischun. Several tokens overlap with Italian, so the distinctive ones
    # are listed first and weighted more heavily below.
    "rm": (
        "tge",
        "davart",
        "mussa",
        "privels",
        "datas",
        "ils",
        "las",
        "cun",
        "ed",
        "en",
        "ha",
        "svizra",
        "quai",
        "era",
        "nua",
    ),
}

# Tokens that appear in essentially no other national language, used to break the
# Romansh/Italian tie.
_STRONG: dict[str, tuple[str, ...]] = {
    "rm": ("tge", "davart", "mussa", "privels", "datas", "cun", "quai", "nua", "ils"),
    "de": ("der", "und", "nicht", "gibt", "keine", "für"),
    "fr": ("des", "aucun", "données", "avec", "dans"),
    "it": ("nel", "della", "nessun", "sulla", "sono"),
    "en": ("the", "there", "with", "found"),
}

_WORD = re.compile(r"[\w'äöüéèàìòùçêôû]+", re.UNICODE)

CLARIFY_MARKERS = (
    "?",
    "welche",
    "welchen",
    "meinen sie",
    "genauer",
    "quel",
    "quelle",
    "précis",
    "quale",
    "intende",
    "which",
    "do you mean",
)


def detect_language(text: str) -> str | None:
    """Best guess at the language of an answer, or None if it is too short to tell."""
    words = [w.lower() for w in _WORD.findall(text)]
    if len(words) < 4:
        return None
    counts = {lang: 0.0 for lang in _MARKERS}
    for lang, markers in _MARKERS.items():
        marker_set = set(markers)
        strong_set = set(_STRONG.get(lang, ()))
        for word in words:
            if word in strong_set:
                counts[lang] += 2.5
            elif word in marker_set:
                counts[lang] += 1.0
    best = max(counts, key=lambda key: counts[key])
    return best if counts[best] > 0 else None


@dataclass
class Failure:
    stage: str
    detail: str


@dataclass
class Verdict:
    question_id: str
    passed: bool
    failures: list[Failure] = field(default_factory=list)
    judged_score: int | None = None
    judged_reason: str = ""

    @property
    def stages(self) -> list[str]:
        return [f.stage for f in self.failures]


@dataclass
class Observation:
    """What actually happened for one question."""

    answer: str = ""
    tool_calls: list[str] = field(default_factory=list)
    failed_tools: list[str] = field(default_factory=list)
    layers: list[str] = field(default_factory=list)
    error_code: str | None = None
    model_id: str = ""
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


def _contains(haystack: str, needle: str) -> bool:
    return needle.lower() in haystack.lower()


def _chain_in_order(calls: list[str], required: list[str]) -> bool:
    position = 0
    for call in calls:
        if position < len(required) and call == required[position]:
            position += 1
    return position == len(required)


def evaluate(question: dict[str, Any], observed: Observation) -> Verdict:
    """Applies a question's `expect` rules to what the model actually did."""
    expect = question.get("expect") or {}
    failures: list[Failure] = []

    if observed.error_code:
        # An exchange that failed outright cannot satisfy anything else, and reporting
        # the transport failure alone is clearer than a cascade of derived failures.
        return Verdict(
            question_id=question["id"],
            passed=False,
            failures=[Failure("exchange_error", f"turn ended with error={observed.error_code}")],
        )

    if not observed.answer.strip():
        failures.append(Failure("empty_answer", "no answer text"))

    wanted_any = expect.get("must_call_tool")
    if wanted_any and not any(tool in observed.tool_calls for tool in wanted_any):
        stage = "no_tool_call" if not observed.tool_calls else "wrong_tool"
        failures.append(
            Failure(
                stage,
                f"expected one of {wanted_any}, called {observed.tool_calls or 'nothing'}",
            )
        )

    chain = expect.get("must_chain_tools")
    if chain and not _chain_in_order(observed.tool_calls, chain):
        stage = "no_tool_call" if not observed.tool_calls else "chain_broken"
        failures.append(Failure(stage, f"expected {chain} in order, called {observed.tool_calls}"))

    if expect.get("must_produce_layer") and not observed.layers:
        failures.append(Failure("no_layer", "expected a map layer, none produced"))

    if expect.get("no_layer") and observed.layers:
        failures.append(Failure("unexpected_layer", f"put {observed.layers} on the map"))

    ceiling = expect.get("max_tools")
    if isinstance(ceiling, int) and len(observed.tool_calls) > ceiling:
        failures.append(
            Failure(
                "too_many_tools",
                f"{len(observed.tool_calls)} tool calls, ceiling {ceiling}",
            )
        )

    wanted_lang = expect.get("answer_lang")
    if wanted_lang:
        detected = detect_language(observed.answer)
        if detected is not None and detected != wanted_lang:
            failures.append(
                Failure("wrong_language", f"asked in {wanted_lang}, answered in {detected}")
            )

    for needle in expect.get("must_mention") or []:
        if not _contains(observed.answer, needle):
            failures.append(Failure("missing_mention", f"answer never mentions {needle!r}"))

    for needle in expect.get("must_not_contain") or []:
        if _contains(observed.answer, needle):
            # The injection categories live or die on this check.
            failures.append(Failure("forbidden_content", f"answer contains {needle!r}"))

    if expect.get("must_clarify"):
        asked = any(_contains(observed.answer, marker) for marker in CLARIFY_MARKERS)
        # Asking counts only if it happened instead of answering. Most answers close with
        # "would you like more detail?", so the marker alone passed a model that silently
        # picked one reading. Fetching data or showing a layer means a choice was made.
        answered_anyway = bool(observed.layers) or any(
            call in ("filter_features", "analyze_features", "display_catalog_layer")
            for call in observed.tool_calls
        )
        if not asked:
            failures.append(Failure("no_clarification", "expected a clarifying question"))
        elif answered_anyway:
            failures.append(
                Failure(
                    "no_clarification",
                    "answered a genuinely ambiguous request instead of asking "
                    f"(tools: {observed.tool_calls}, layers: {len(observed.layers)})",
                )
            )

    if expect.get("must_not_clarify") and not observed.tool_calls:
        # Over-asking is a failure too: where there is an obvious default, act and say
        # which reading was taken. Judged on action, since "?" appears in good answers.
        failures.append(
            Failure(
                "over_clarified",
                "expected a default to be chosen and acted on, not a question",
            )
        )

    if observed.failed_tools:
        # Not a hard failure, since the model may recover, but surfaced because it
        # explains a thin answer.
        failures.append(
            Failure(
                "tool_error",
                f"tool(s) failed: {', '.join(sorted(set(observed.failed_tools)))}",
            )
        )

    hard_failures = [f for f in failures if f.stage != "tool_error"]
    return Verdict(question_id=question["id"], passed=not hard_failures, failures=failures)
