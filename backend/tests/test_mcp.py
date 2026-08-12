"""The MCP client: schema conversion, result handling, and graceful degradation.

The gateway's job when the server is missing or broken is to let the turn continue
without tools, so an unreachable server costs the tools and not the exchange.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.mcp.client import NO_TOOLS, ToolGateway, ToolSession
from app.mcp.schema import normalise_input_schema, to_tool_spec


class FakeBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeResult:
    def __init__(self, blocks: list[Any], is_error: bool = False, structured: Any = None) -> None:
        self.content = blocks
        self.is_error = is_error
        self.structured_content = structured


class FakeSession:
    def __init__(self, result: Any) -> None:
        self._result = result
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        # BaseException, not Exception: a group holding only CancelledError is not an
        # anyio reports transport failures as a group, which is the case under test.
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


class TestSchemaConversion:
    def test_drops_presentation_keys_pydantic_adds(self) -> None:
        """Mistral is less tolerant of unexpected schema keys than Claude."""
        schema = {
            "type": "object",
            "title": "search_layersArguments",
            "properties": {"query": {"type": "string", "title": "Query"}},
            "required": ["query"],
        }
        cleaned = normalise_input_schema(schema)
        assert "title" not in cleaned
        assert "title" not in cleaned["properties"]["query"]
        assert cleaned["required"] == ["query"]

    def test_forces_an_object_schema(self) -> None:
        assert normalise_input_schema({"type": "string"})["type"] == "object"
        assert normalise_input_schema(None) == {"type": "object", "properties": {}}
        assert normalise_input_schema({"type": "object"})["properties"] == {}

    def test_drops_a_malformed_required_list(self) -> None:
        assert "required" not in normalise_input_schema(
            {"type": "object", "properties": {}, "required": "query"}
        )

    def test_cleans_nested_schemas(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "bbox": {
                    "title": "Bbox",
                    "anyOf": [{"type": "array", "items": {"type": "number"}}, {"type": "null"}],
                }
            },
        }
        cleaned = normalise_input_schema(schema)
        assert "title" not in cleaned["properties"]["bbox"]
        assert cleaned["properties"]["bbox"]["anyOf"][0]["items"] == {"type": "number"}

    def test_builds_a_bedrock_tool_spec(self) -> None:
        spec = to_tool_spec("search_layers", "Find datasets.", {"type": "object", "properties": {}})
        assert spec["toolSpec"]["name"] == "search_layers"
        assert spec["toolSpec"]["description"] == "Find datasets."
        assert spec["toolSpec"]["inputSchema"]["json"]["type"] == "object"

    def test_falls_back_to_the_name_when_a_tool_has_no_description(self) -> None:
        assert to_tool_spec("t", None, {})["toolSpec"]["description"] == "t"

    def test_truncates_an_enormous_description(self) -> None:
        spec = to_tool_spec("t", "x" * 5000, {})
        assert len(spec["toolSpec"]["description"]) <= 900


class TestToolSession:
    async def test_parses_json_output_into_data(self) -> None:
        payload = {"layers": [{"layer_id": "ch.bafu.x"}]}
        session = ToolSession(FakeSession(FakeResult([FakeBlock(json.dumps(payload))])), [])
        outcome = await session.call("search_layers", {"query": "x"})
        assert outcome.is_error is False
        assert outcome.data == payload

    async def test_non_json_output_still_reaches_the_model_as_text(self) -> None:
        session = ToolSession(FakeSession(FakeResult([FakeBlock("plain text answer")])), [])
        outcome = await session.call("t", {})
        assert outcome.text == "plain text answer"
        assert outcome.data is None

    async def test_prefers_structured_content_when_present(self) -> None:
        session = ToolSession(
            FakeSession(FakeResult([FakeBlock("ignored")], structured={"a": 1})), []
        )
        assert (await session.call("t", {})).data == {"a": 1}

    @pytest.mark.parametrize("structured", [None, {"error": ""}, {"error": 500}])
    async def test_only_a_non_empty_top_level_string_is_a_semantic_error(
        self, structured: Any
    ) -> None:
        data = structured if structured is not None else {"items": [{"error": "row value"}]}
        session = ToolSession(
            FakeSession(FakeResult([FakeBlock(json.dumps(data))], structured=data)), []
        )

        outcome = await session.call("filter_features", {})

        assert outcome.is_error is False
        assert outcome.data == data

    async def test_a_top_level_tool_error_becomes_a_failed_outcome(self) -> None:
        reason = "Result contains more than 100,000 features. Narrow the place, area, or dataset."
        payload = {"error": reason, "feature_count": 100_001, "limit": 100_000}
        session = ToolSession(
            FakeSession(FakeResult([FakeBlock("ignored")], structured=payload)), []
        )

        outcome = await session.call("filter_features", {})

        assert outcome.is_error is True
        assert outcome.text == reason
        assert outcome.data == payload

    async def test_a_json_text_tool_error_becomes_a_failed_outcome(self) -> None:
        payload = {"error": "Could not publish the layer."}
        session = ToolSession(FakeSession(FakeResult([FakeBlock(json.dumps(payload))])), [])

        outcome = await session.call("display_layer", {})

        assert outcome.is_error is True
        assert outcome.text == payload["error"]
        assert outcome.data == payload

    async def test_a_tool_error_is_reported_not_raised(self) -> None:
        session = ToolSession(FakeSession(FakeResult([FakeBlock("boom")], is_error=True)), [])
        outcome = await session.call("t", {})
        assert outcome.is_error is True

    async def test_a_transport_failure_becomes_a_failed_tool(self) -> None:
        """The model can then try something else or explain the gap."""
        secret = "https://bucket.test/layer?X-Amz-Signature=do-not-leak"
        session = ToolSession(FakeSession(RuntimeError(secret)), [])
        outcome = await session.call("filter_features", {"token": "also-secret"})
        assert outcome.is_error is True
        assert outcome.text == "Tool filter_features failed: RuntimeError"
        assert secret not in outcome.text
        assert "also-secret" not in outcome.text
        assert outcome.data is None

    async def test_an_exception_group_is_handled(self) -> None:
        """anyio reports transport failures as groups."""
        group = BaseExceptionGroup("transport", [RuntimeError("closed")])
        session = ToolSession(FakeSession(group), [])
        assert (await session.call("t", {})).is_error is True

    async def test_cancellation_is_never_swallowed(self) -> None:
        """A cancelled turn must stop, not be logged as a failed tool call."""
        group = BaseExceptionGroup("cancelled", [asyncio.CancelledError()])
        session = ToolSession(FakeSession(group), [])
        with pytest.raises(BaseExceptionGroup):
            await session.call("t", {})

    async def test_empty_output_is_reported_rather_than_blank(self) -> None:
        session = ToolSession(FakeSession(FakeResult([])), [])
        assert (await session.call("t", {})).text == "(no output)"

    async def test_no_tools_session_reports_unavailability(self) -> None:
        outcome = await NO_TOOLS.call("search_layers", {})
        assert outcome.is_error is True
        assert NO_TOOLS.tool_specs == []

    def test_exposes_tool_names(self) -> None:
        session = ToolSession(None, [to_tool_spec("a", "a", {}), to_tool_spec("b", "b", {})])
        assert session.tool_names == ["a", "b"]


class TestGateway:
    async def test_an_unconfigured_gateway_yields_no_tools(self) -> None:
        gateway = ToolGateway("")
        assert gateway.configured is False
        async with gateway.session() as session:
            assert session.tool_specs == []

    async def test_an_unreachable_server_degrades_instead_of_failing(self) -> None:
        gateway = ToolGateway("http://127.0.0.1:1/mcp", read_timeout=1.0)
        async with gateway.session() as session:
            assert session.tool_specs == []

    async def test_caller_exceptions_are_not_mistaken_for_transport_failures(self) -> None:
        """The yield must sit outside the connection error handler."""
        gateway = ToolGateway("")
        with pytest.raises(ValueError, match="from the caller"):
            async with gateway.session():
                raise ValueError("from the caller")


def test_only_a_configured_url_counts_as_production() -> None:
    """The stand-in returns real data but is not swisstopo's server, so it must not
    satisfy the production check (app/ws.py refuses turns on it)."""
    assert ToolGateway("https://mcp.example.ch/mcp").is_production is True
    assert ToolGateway(server=object()).is_production is False
    assert ToolGateway().is_production is False
    # `configured` is a different question and still answers yes for the stand-in.
    assert ToolGateway(server=object()).configured is True


async def test_an_empty_tool_catalogue_is_not_cached() -> None:
    """A server that answers before it is ready returns no tools; caching that leaves the
    agent toolless for the process lifetime while /health stays green."""

    class Listing:
        def __init__(self, tools: list[Any]) -> None:
            self.tools = tools

    class Tool:
        def __init__(self, name: str) -> None:
            self.name = name
            self.description = name
            self.input_schema = {"type": "object"}

    class Session:
        def __init__(self) -> None:
            self.calls = 0

        async def list_tools(self) -> Any:
            self.calls += 1
            return Listing([] if self.calls == 1 else [Tool("search_layers")])

    gateway = ToolGateway("https://mcp.example.ch/mcp")
    session = Session()
    assert await gateway._resolve_specs(session) == []
    second = await gateway._resolve_specs(session)
    assert [spec["toolSpec"]["name"] for spec in second] == ["search_layers"]
    # A non-empty catalogue is still cached.
    assert await gateway._resolve_specs(session) is second


class TestCatalogueRetrieval:
    """`tools/list` is cached, paginated and TTL-bounded (docs/architecture.md)."""

    class _Listing:
        def __init__(self, tools: list[Any], cursor: str | None = None, ttl_ms: int = 0) -> None:
            self.tools = tools
            self.next_cursor = cursor
            self.ttl_ms = ttl_ms
            self.cache_scope = "private"

    class _Tool:
        def __init__(self, name: str) -> None:
            self.name = name
            self.description = name
            self.input_schema = {"type": "object"}

    async def test_every_page_is_followed(self) -> None:
        """Without the cursor, tools past page one are invisible to the model."""
        pages = {
            None: TestCatalogueRetrieval._Listing([TestCatalogueRetrieval._Tool("a")], "c1"),
            "c1": TestCatalogueRetrieval._Listing([TestCatalogueRetrieval._Tool("b")], "c2"),
            "c2": TestCatalogueRetrieval._Listing([TestCatalogueRetrieval._Tool("c")]),
        }

        class Session:
            async def list_tools(self, *, params: Any = None) -> Any:
                cursor = params.cursor if params is not None else None
                return pages[cursor]

        gateway = ToolGateway("https://mcp.example.ch/mcp")
        specs = await gateway._resolve_specs(Session())
        assert [spec["toolSpec"]["name"] for spec in specs] == ["a", "b", "c"]

    async def test_a_bare_cursor_client_is_also_supported(self) -> None:
        """The in-process Client takes `cursor=`, ClientSession takes `params=`."""
        pages = {
            None: TestCatalogueRetrieval._Listing([TestCatalogueRetrieval._Tool("a")], "c1"),
            "c1": TestCatalogueRetrieval._Listing([TestCatalogueRetrieval._Tool("b")]),
        }

        class Session:
            async def list_tools(self, *, cursor: str | None = None) -> Any:
                return pages[cursor]

        gateway = ToolGateway("https://mcp.example.ch/mcp")
        specs = await gateway._resolve_specs(Session())
        assert [spec["toolSpec"]["name"] for spec in specs] == ["a", "b"]

    async def test_an_advertised_ttl_expires_the_cache(self) -> None:
        calls = {"n": 0}

        class Session:
            async def list_tools(self, *, params: Any = None) -> Any:
                calls["n"] += 1
                name = "a" if calls["n"] == 1 else "b"
                return TestCatalogueRetrieval._Listing(
                    [TestCatalogueRetrieval._Tool(name)], ttl_ms=1
                )

        gateway = ToolGateway("https://mcp.example.ch/mcp")
        session = Session()
        assert [s["toolSpec"]["name"] for s in await gateway._resolve_specs(session)] == ["a"]
        await asyncio.sleep(0.01)
        assert [s["toolSpec"]["name"] for s in await gateway._resolve_specs(session)] == ["b"]

    async def test_no_ttl_means_cached_for_the_process(self) -> None:
        calls = {"n": 0}

        class Session:
            async def list_tools(self, *, params: Any = None) -> Any:
                calls["n"] += 1
                return TestCatalogueRetrieval._Listing([TestCatalogueRetrieval._Tool("a")])

        gateway = ToolGateway("https://mcp.example.ch/mcp")
        session = Session()
        await gateway._resolve_specs(session)
        await gateway._resolve_specs(session)
        assert calls["n"] == 1
