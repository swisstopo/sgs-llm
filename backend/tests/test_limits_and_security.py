"""Rate limiting, connection caps, origin checks and the optional key."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.limits import ConnectionRegistry, RateLimiter, TooManyConnections
from app.security import (
    client_key,
    key_from_subprotocols,
    key_matches,
    origin_allowed,
)


def test_large_layer_time_budgets_are_coherent() -> None:
    settings = Settings()
    assert settings.mcp_read_timeout_seconds == 240
    assert settings.turn_timeout_seconds == 300
    assert settings.turn_timeout_seconds > settings.mcp_read_timeout_seconds


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestRateLimiter:
    def test_allows_up_to_capacity_then_refuses(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(3, now=clock)
        assert [limiter.allow("ip") for _ in range(3)] == [True, True, True]
        assert limiter.allow("ip") is False

    def test_refills_over_a_minute(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(60, now=clock)
        for _ in range(60):
            limiter.allow("ip")
        assert limiter.allow("ip") is False
        clock.advance(1.0)
        assert limiter.allow("ip") is True

    def test_clients_are_independent(self) -> None:
        limiter = RateLimiter(1, now=FakeClock())
        assert limiter.allow("a") is True
        assert limiter.allow("b") is True
        assert limiter.allow("a") is False

    def test_never_refills_beyond_capacity(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(2, now=clock)
        limiter.allow("ip")
        clock.advance(3600)
        assert [limiter.allow("ip") for _ in range(2)] == [True, True]
        assert limiter.allow("ip") is False

    def test_forget_does_not_reset_an_unreplenished_bucket(self) -> None:
        """A client must not be able to clear its own allowance by reconnecting, which is
        when forget() is called."""
        clock = FakeClock()
        limiter = RateLimiter(1, now=clock)
        assert limiter.allow("ip") is True
        limiter.forget("ip")
        assert limiter.allow("ip") is False

    def test_forget_drops_a_bucket_once_it_has_refilled(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(1, now=clock)
        limiter.allow("ip")
        clock.advance(60)
        limiter.forget("ip")
        assert limiter._buckets == {}


class TestConnectionRegistry:
    def test_caps_concurrent_connections(self) -> None:
        registry = ConnectionRegistry(limit=2)
        with registry.hold("ip"), registry.hold("ip"):
            assert registry.count("ip") == 2
            with pytest.raises(TooManyConnections), registry.hold("ip"):
                pass

    def test_releases_on_exit_including_on_error(self) -> None:
        registry = ConnectionRegistry(limit=1)
        with pytest.raises(ValueError), registry.hold("ip"):
            raise ValueError("boom")
        assert registry.is_idle("ip")
        with registry.hold("ip"):
            pass

    def test_idle_keys_are_forgotten(self) -> None:
        registry = ConnectionRegistry(limit=2)
        with registry.hold("ip"):
            assert not registry.is_idle("ip")
        assert registry.is_idle("ip")


class TestOrigin:
    def test_an_empty_allowlist_accepts_anything(self) -> None:
        assert origin_allowed("https://anywhere.test", ())

    def test_only_listed_origins_are_accepted(self) -> None:
        allowlist = ("https://denpw8uo5zpkl.cloudfront.net",)
        assert origin_allowed("https://denpw8uo5zpkl.cloudfront.net", allowlist)
        assert not origin_allowed("https://evil.test", allowlist)

    def test_a_missing_origin_is_accepted(self) -> None:
        """Non-browser clients send none - including CI's raw upgrade check, which
        gates the deploy."""
        assert origin_allowed(None, ("https://denpw8uo5zpkl.cloudfront.net",))


class TestClientKey:
    def test_prefers_the_cloudfront_viewer_address(self) -> None:
        assert client_key("203.0.113.7, 130.59.1.1", "10.0.0.5") == "203.0.113.7"

    def test_falls_back_to_the_peer(self) -> None:
        assert client_key(None, "10.0.0.5") == "10.0.0.5"
        assert client_key("", "10.0.0.5") == "10.0.0.5"

    def test_never_returns_empty(self) -> None:
        assert client_key(None, None) == "unknown"


class TestApiKey:
    def test_an_unset_key_accepts_everything(self) -> None:
        assert key_matches("", None)
        assert key_matches("", "anything")

    def test_a_configured_key_must_match(self) -> None:
        assert key_matches("s3cret", "s3cret")
        assert not key_matches("s3cret", "wrong")
        assert not key_matches("s3cret", None)
        assert not key_matches("s3cret", "")

    def test_extracts_the_key_from_a_subprotocol(self) -> None:
        assert key_from_subprotocols(["sgs-llm-key.abc123"]) == "abc123"
        assert key_from_subprotocols(["other", "sgs-llm-key.abc"]) == "abc"

    def test_no_subprotocol_yields_nothing(self) -> None:
        assert key_from_subprotocols(None) is None
        assert key_from_subprotocols([]) is None
        assert key_from_subprotocols(["unrelated"]) is None
