import pytest
from app.agent.prompts import system_prompt

from evals.parcel_discovery import PARCEL_HINT, without_parcel_hints


@pytest.mark.parametrize("model", ["", "claude", "ministral", "apertus"])
def test_ablation_keeps_geometry_and_precision_instructions(model):
    original = system_prompt("de", model_id=model)
    ablated = without_parcel_hints(original)
    assert PARCEL_HINT in original
    assert "OpenData-AV" not in ablated
    assert "ch.swisstopo-vd.amtliche-vermessung" not in ablated
    for instruction in (
        "parcel *polygon*",
        '`origins: ["parcel"]`',
        "`return_geometry: true`",
        "Pass the `location_ref`",
        "never re-type or round a coordinate",
    ):
        assert instruction in ablated
    assert system_prompt("de", model_id=model) == original


def test_changed_or_additional_hints_fail_closed():
    with pytest.raises(ValueError, match="hint changed"):
        without_parcel_hints("a changed prompt")
    with pytest.raises(ValueError, match="hint remains"):
        without_parcel_hints(system_prompt("de") + " OpenData-AV")


@pytest.mark.parametrize("parcel_hints", [True, False])
async def test_real_loop_model_input_uses_requested_variant(settings, parcel_hints):
    from app.mcp.client import NO_TOOLS
    from tests.conftest import HANDLE, FakeGateway, FakeModels, text_result

    from evals.run import ask

    models = FakeModels([text_result("Antwort")])
    observation = await ask(
        {"id": "no-hint", "question": "Zeige mir eine Parzelle", "lang": "de"},
        models=models, handle=HANDLE, gateway=FakeGateway(NO_TOOLS), settings=settings,
        parcel_hints=parcel_hints,
    )
    assert observation.answer == "Antwort"
    assert (PARCEL_HINT in models.calls[0]["system"]) is parcel_hints
