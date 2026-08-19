"""Static deployment-contract tests for failure modes invisible to unit tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
