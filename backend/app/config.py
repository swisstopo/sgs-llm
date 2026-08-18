"""The deploy-time environment contract, as a settings object.

Every name here matches the table in docs/deployment.md#environment-contract and
the Environment block of infra/backend-service.yaml. Defaults are chosen so the
container starts healthy with *nothing* configured - CI smoke-tests the image with
no AWS credentials and no MCP server (.github/workflows/backend.yml), and that has
to keep working.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    port: int = 8787
    log_level: str = "info"

    bedrock_region: str = "eu-central-1"
    bedrock_primary_model_id: str = ""
    bedrock_secondary_model_id: str = ""
    bedrock_secondary_region: str = ""

    feedback_table: str = ""
    conversation_table: str = ""
    feedback_ttl_days: int = 365
    conversation_ttl_days: int = 90

    data_layer_bucket: str = ""
    data_layer_presign_ttl: int = 3600

    public_base_url: str = ""
    allowed_origins: str = ""

    mcp_server_url: str = ""
    mcp_server_token: str = ""

    # Official layers travel as small references and the browser resolves their current
    # WMS/WMTS/GeoJSON configuration directly from geo.admin.ch. Kept as an emergency
    # rollout switch, but enabled now that protocol v1 renders inline layer actions.
    enable_catalog_layers: bool = True

    # Empty disables the key, which is the deployed default. Served from the public
    # config.json, so it is a speed bump rather than a boundary (docs/protocol.md).
    api_key: str = ""

    max_message_chars: int = 4000
    max_history_entries: int = 40
    max_frame_bytes: int = 262_144
    turn_timeout_seconds: float = 90.0
    max_tool_iterations: int = 8
    rate_limit_messages_per_minute: int = 20
    max_connections_per_ip: int = 8

    @property
    def secondary_region(self) -> str:
        """Where the secondary model lives; the pilot's Mistral is eu-west-1 only."""
        return self.bedrock_secondary_region or self.bedrock_region

    @property
    def origin_allowlist(self) -> tuple[str, ...]:
        """Accepted WebSocket origins. Empty means "allow any" (local development)."""
        return tuple(o.strip() for o in self.allowed_origins.split(",") if o.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
