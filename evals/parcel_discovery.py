"""Evaluation-only ablation of the stable parcel dataset hint."""

PARCEL_HINT = (
    'official cadastral survey - titled "OpenData-AV", layer id '
    "`ch.swisstopo-vd.amtliche-vermessung` - and display that result. That dataset is named "
    "here as a stable official identifier; `search_layers` also indexes multilingual parcel "
    "and cadastral terms. Confirm it with `describe_layer` when needed. "
)


def without_parcel_hints(prompt: str) -> str:
    # Fail closed when the production prompt changes: an unchanged hinted prompt must
    # never be silently recorded as a successful no-hint evaluation.
    if prompt.count(PARCEL_HINT) != 1:
        raise ValueError("Parcel hint changed; review the evaluation ablation first")
    result = prompt.replace(
        PARCEL_HINT,
        "parcel geometry dataset discovered with `search_layers` and checked with "
        "`describe_layer`, and display that result. ",
    )
    for hint in (
        "OpenData-AV",
        "ch.swisstopo-vd.amtliche-vermessung",
        "CadastralWebMap",
        "ch.kantone.cadastralwebmap-farbe",
    ):
        if hint.casefold() in result.casefold():
            raise ValueError(f"Dataset hint remains in evaluation prompt: {hint}")
    return result
