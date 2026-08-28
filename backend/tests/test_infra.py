"""Static deployment-contract tests for failure modes invisible to unit tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


class _CloudFormationLoader(yaml.SafeLoader):
    """Load intrinsic tags as ordinary values so deployment structure is testable."""


def _construct_intrinsic(loader: _CloudFormationLoader, _suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


_CloudFormationLoader.add_multi_constructor("!", _construct_intrinsic)


def test_geosearch_service_connect_does_not_cut_long_filters_at_fifteen_seconds() -> None:
    template = yaml.load(
        (REPO_ROOT / "infra" / "geosearch-service.yaml").read_text(encoding="utf-8"),
        Loader=_CloudFormationLoader,
    )

    service = template["Resources"]["Service"]["Properties"]
    published_mcp = service["ServiceConnectConfiguration"]["Services"][0]

    assert published_mcp["Timeout"]["PerRequestTimeoutSeconds"] == 90


def test_service_has_no_cognito_dependency() -> None:
    template = yaml.load(
        (REPO_ROOT / "infra" / "backend-service.yaml").read_text(encoding="utf-8"),
        Loader=_CloudFormationLoader,
    )
    environment = template["Resources"]["TaskDefinition"]["Properties"]["ContainerDefinitions"][0][
        "Environment"
    ]
    names = {entry["Name"] for entry in environment}
    assert not {"COGNITO_USER_POOL_ID", "COGNITO_APP_CLIENT_ID", "COGNITO_ADMIN_GROUP"} & names


def test_backend_image_gives_the_non_root_user_a_writable_admin_database() -> None:
    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "ADMIN_USER_DB_PATH=/var/lib/sgs-llm/admin-users.sqlite3" in dockerfile
    assert "install -d -o sgs -g sgs /var/lib/sgs-llm" in dockerfile


def test_local_runtime_endpoints_share_one_hostname_for_strict_admin_cookies() -> None:
    config = json.loads((REPO_ROOT / "frontend" / "public" / "config.json").read_text())
    hostnames = {
        urlparse(config[name]).hostname for name in ("agentWsUrl", "feedbackUrl", "adminApiUrl")
    }
    assert hostnames == {"127.0.0.1"}


def _backend_container() -> dict[str, Any]:
    template = yaml.load(
        (REPO_ROOT / "infra" / "backend-service.yaml").read_text(encoding="utf-8"),
        Loader=_CloudFormationLoader,
    )
    return template["Resources"]["TaskDefinition"]["Properties"]["ContainerDefinitions"][0]


def _names(entries: list[Any]) -> set[str]:
    """Entry names, seeing through a conditional entry - `!If` loads as a list here."""
    names: set[str] = set()
    for entry in entries:
        candidates = entry if isinstance(entry, list) else [entry]
        names.update(item["Name"] for item in candidates if isinstance(item, dict))
    return names


def test_the_apertus_key_arrives_from_secrets_manager_not_ssm() -> None:
    """sgs-llm-backend-task has no ssm:GetParameter, and the fix is not to grant it: the
    key is populated in the Secrets Manager secret both task roles already read, so
    wiring it needs no IAM change (docs/apertus-endpoint.md)."""
    container = _backend_container()

    assert "APERTUS_API_KEY" in _names(container["Secrets"])
    assert "APERTUS_API_KEY" not in _names(container["Environment"])


def test_the_apertus_secret_is_not_read_unless_apertus_is_switched_on() -> None:
    """A Secrets entry naming a key the secret does not hold fails EVERY task start. Off
    by default, so enabling Apertus is the only way to take that risk."""
    template = yaml.load(
        (REPO_ROOT / "infra" / "backend-service.yaml").read_text(encoding="utf-8"),
        Loader=_CloudFormationLoader,
    )

    assert template["Parameters"]["ApertusBaseUrl"]["Default"] == ""

    conditional = [entry for entry in _backend_container()["Secrets"] if isinstance(entry, list)]
    assert [entry[0] for entry in conditional] == ["HasApertus"]


def test_the_apertus_endpoint_is_configured_as_plain_environment() -> None:
    assert {"APERTUS_BASE_URL", "APERTUS_MODEL_ID"} <= _names(_backend_container()["Environment"])


def _apertus_stack() -> dict[str, Any]:
    return yaml.load(
        (REPO_ROOT / "infra" / "apertus-service.yaml").read_text(encoding="utf-8"),
        Loader=_CloudFormationLoader,
    )


# vLLM's own report on the deployed instance: "GPU KV cache size: 28,400 tokens"
# (docs/apertus-endpoint.md). The pool is shared across all in-flight requests, and the
# container refuses to start when MaxModelLen exceeds it.
KV_CACHE_TOKENS = 28_400


def test_the_context_window_fits_the_agent_loop_and_the_kv_cache() -> None:
    """The system prompt plus the ten tool definitions is ~3.6-4.1k tokens before any
    history, and every tool result is re-sent on each of up to 8 iterations, so 4096
    cannot serve a single turn."""
    max_model_len = int(_apertus_stack()["Parameters"]["MaxModelLen"]["Default"])

    assert 16384 <= max_model_len <= KV_CACHE_TOKENS


def test_one_sequence_at_a_time_so_a_second_request_queues_instead_of_preempting() -> None:
    """max_num_seqs is a scheduler cap, not a memory reservation. With a context this
    large one sequence can exhaust the KV pool, so admitting a second means preemption
    and recompute rather than interleaving."""
    stack = _apertus_stack()

    max_model_len = int(stack["Parameters"]["MaxModelLen"]["Default"])
    max_num_seqs = int(stack["Parameters"]["MaxNumSeqs"]["Default"])

    assert max_model_len * max_num_seqs <= KV_CACHE_TOKENS


def test_the_repeated_prompt_prefix_is_cached() -> None:
    """The system prompt and all tool specs repeat on every iteration of every turn.
    Prefill is ~2,100 tok/s, so re-prefilling a 26k prompt eight times is ~99 s of pure
    prefill - more than the turn budget on its own."""
    user_data = _apertus_stack()["Resources"]["Instance"]["Properties"]["UserData"]

    assert "--enable-prefix-caching" in str(user_data)
