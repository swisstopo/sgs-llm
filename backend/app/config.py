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

    # Apertus 1.5, self-hosted on an OpenAI-compatible vLLM endpoint. Empty base url
    # disables the model entirely, which is the default and what CI smoke-tests.
    apertus_base_url: str = ""
    apertus_api_key: str = ""
    apertus_model_id: str = "apertus-8b"
    apertus_region: str = "eu-central-1"
    apertus_max_tokens: int = 2048
    # Its own budget: ~16.8 tok/s decode plus up to 8 tool iterations does not fit the
    # 90 s the Bedrock models are given (docs/apertus-endpoint.md).
    apertus_turn_timeout_seconds: float = 240.0

    feedback_table: str = ""
    conversation_table: str = ""
    feedback_ttl_days: int = 365
    conversation_ttl_days: int = 90

    # A deliberately small application-user store for the admin dashboard. Passwords
    # are scrypt hashes and browser sessions are stored as revocable token hashes.
    admin_user_db_path: str = "./admin-users.sqlite3"
    admin_session_hours: int = 8
    admin_cookie_secure: bool = False

    data_layer_bucket: str = ""
    data_layer_presign_ttl: int = 3600

    public_base_url: str = ""
    allowed_origins: str = ""

    mcp_server_url: str = ""
    mcp_server_token: str = ""

    # The public, read-only exploration MCP is served by this same process at /mcp.
    # It has no model or AWS calls, but it does call public geo.admin.ch APIs, so its
    # limits are independent from the Bedrock-backed chat limits below.
    exploration_mcp_allowed_origins: str = "https://claude.ai,https://claude.com"
    exploration_mcp_requests_per_minute: int = 120
    exploration_mcp_max_concurrent_requests: int = 8

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

    def turn_timeout_for(self, role: str) -> float:
        """The wall-clock budget for one turn on the selected model.

        Apertus decodes at about 16.8 tok/s on the deployed L4 and re-prefills a growing
        conversation on every tool iteration, so the Bedrock models' budget does not fit
        it (docs/apertus-endpoint.md).
        """
        if role == "apertus":
            return self.apertus_turn_timeout_seconds
        return self.turn_timeout_seconds

    @property
    def origin_allowlist(self) -> tuple[str, ...]:
        """Accepted WebSocket origins. Empty means "allow any" (local development)."""
        return tuple(o.strip() for o in self.allowed_origins.split(",") if o.strip())

    @property
    def exploration_mcp_origin_allowlist(self) -> tuple[str, ...]:
        """Browser origins allowed to call the public MCP; non-browser clients omit it."""
        return tuple(
            origin.strip()
            for origin in self.exploration_mcp_allowed_origins.split(",")
            if origin.strip()
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
