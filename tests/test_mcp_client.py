"""MCP read server: the one door out (packages/mcp/healthsave_mcp/client.py).

The server must talk to the configured Observatory and nothing else, with GET
only, and turn every refusal into a code an AI client can explain.
"""

from __future__ import annotations

import httpx
import pytest
from healthsave_mcp import __version__
from healthsave_mcp.client import Config, ConfigError, ObservatoryClient, ObservatoryError

URL = "http://obs.test:8000"


def _client(handler, key: str = "read-key") -> tuple[ObservatoryClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return ObservatoryClient(Config(URL, key), transport=httpx.MockTransport(record)), seen


async def test_reads_with_the_key_header_and_a_named_user_agent() -> None:
    client, seen = _client(lambda r: httpx.Response(200, json={"ok": True}))
    assert await client.get("/api/v2/readiness", {"owner": None, "limit": 3}) == {"ok": True}
    [request] = seen
    assert request.method == "GET"
    assert str(request.url) == f"{URL}/api/v2/readiness?limit=3"
    assert request.headers["x-api-key"] == "read-key"
    assert request.headers["user-agent"] == f"healthsave-mcp/{__version__}"


@pytest.mark.parametrize(
    "path",
    [
        "https://elsewhere.example/api/v2/readiness",
        "//elsewhere.example/api/v2/readiness",
        "/api/v2/../apple/batch",
        "/api/apple/status",
        "/metrics",
        "api/v2/readiness",
    ],
)
async def test_refuses_every_path_outside_the_read_api(path) -> None:
    client, seen = _client(lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValueError, match="only /api/v2/"):
        await client.get(path)
    assert seen == []


async def test_never_follows_a_redirect_to_another_host() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "obs.test":
            return httpx.Response(302, headers={"location": "https://collector.example/steal"})
        raise AssertionError("followed a redirect off the configured host")

    client, seen = _client(handler)
    with pytest.raises(ObservatoryError) as exc:
        await client.get("/api/v2/readiness")
    assert exc.value.code == "redirect_refused"
    assert [r.url.host for r in seen] == ["obs.test"]


def test_ignores_proxy_settings_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:3128")
    client = ObservatoryClient(Config(URL, "k"))
    assert client._http._trust_env is False
    assert not client._http._mounts  # no proxy transport mounted from the environment


@pytest.mark.parametrize(
    ("status", "body", "code"),
    [
        (401, {"detail": "invalid_api_key"}, "key_rejected"),
        (403, {"detail": "api_key_scope: read key cannot call GET /api/v2/labs"}, "key_scope"),
        (404, {"detail": "no results"}, "not_found"),
        (422, {"detail": "year 2031 has not started"}, "rejected"),
        (503, {"detail": "database unavailable"}, "unavailable"),
        (418, {}, "http_error"),
    ],
)
async def test_every_refusal_has_a_stable_code_and_a_plain_sentence(status, body, code) -> None:
    client, _ = _client(lambda r: httpx.Response(status, json=body))
    with pytest.raises(ObservatoryError) as exc:
        await client.get("/api/v2/labs")
    assert exc.value.code == code and exc.value.status == status
    if body.get("detail") and code != "key_rejected":
        assert body["detail"] in str(exc.value)
    assert exc.value.as_limitation()["code"] == code


async def test_unreachable_and_not_json_are_reported_not_raised_raw() -> None:
    def down(request):
        raise httpx.ConnectError("refused")

    client, _ = _client(down)
    with pytest.raises(ObservatoryError, match="Could not reach") as exc:
        await client.get("/api/v2/readiness")
    assert exc.value.code == "unreachable"
    client, _ = _client(lambda r: httpx.Response(200, text="<html>router login</html>"))
    with pytest.raises(ObservatoryError) as exc:
        await client.get("/api/v2/readiness")
    assert exc.value.code == "not_json"


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({}, "HEALTHSAVE_URL is not set"),
        ({"HEALTHSAVE_URL": "obs.local:8000"}, "http:// or https://"),
        ({"HEALTHSAVE_URL": "ftp://obs.local"}, "http:// or https://"),
        ({"HEALTHSAVE_URL": "http://u:p@obs.local:8000"}, "user name or password"),
        ({"HEALTHSAVE_URL": "http://obs.local:8000/api/v2"}, "address only"),
        ({"HEALTHSAVE_URL": "http://obs.local:8000?x=1"}, "address only"),
        ({"HEALTHSAVE_URL": "http://obs.local", "HEALTHSAVE_API_KEY": "a b"}, "spaces"),
    ],
)
def test_config_refuses_what_it_cannot_use(env, message) -> None:
    with pytest.raises(ConfigError, match=message):
        Config.from_env(env)


def test_config_trims_and_keeps_an_empty_key_for_open_mode() -> None:
    config = Config.from_env({"HEALTHSAVE_URL": " http://obs.local:8000/ "})
    assert (config.url, config.api_key) == ("http://obs.local:8000", "")
