"""Tests for the BragerOne client's token handling and parsing."""

from __future__ import annotations

from collections import deque
from typing import Any

import aiohttp
import pytest

from custom_components.brager_one.api import (
    BragerOneAuthError,
    BragerOneClient,
    BragerOneConnectionError,
    normalise_alarms,
    parse_parameters,
)


class FakeResponse:
    """Minimal stand-in for an aiohttp response."""

    def __init__(self, status: int, body: Any) -> None:
        self.status = status
        self._body = body

    async def json(self, content_type: str | None = None) -> Any:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeSession:
    """Plays back scripted responses and records requests."""

    def __init__(self, *responses: tuple[int, Any] | Exception) -> None:
        self.responses = deque(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, url.rsplit("/v1", 1)[1], kwargs))
        item = self.responses.popleft()
        if isinstance(item, Exception):
            raise item
        return FakeResponse(*item)


TOKENS = (200, {"accessToken": "a1", "refreshToken": "r1"})


def client(session: FakeSession) -> BragerOneClient:
    return BragerOneClient(session, "u@example.com", "pw")  # type: ignore[arg-type]


async def test_login_sends_credentials_without_auth_header() -> None:
    session = FakeSession(TOKENS)
    api = client(session)
    await api.async_login()
    method, path, kwargs = session.calls[0]
    assert (method, path) == ("POST", "/auth/user")
    assert kwargs["json"] == {"email": "u@example.com", "password": "pw"}
    assert "Authorization" not in kwargs["headers"]
    assert api.email == "u@example.com"


@pytest.mark.parametrize("status", [400, 401, 403, 422])
async def test_login_rejected(status: int) -> None:
    with pytest.raises(BragerOneAuthError):
        await client(FakeSession((status, {}))).async_login()


@pytest.mark.parametrize(
    "response", [(500, {}), (200, "nope"), (200, {"accessToken": ""})]
)
async def test_login_bad_response(response: tuple[int, Any]) -> None:
    with pytest.raises(BragerOneConnectionError):
        await client(FakeSession(response)).async_login()


async def test_network_error_is_wrapped() -> None:
    with pytest.raises(BragerOneConnectionError):
        await client(FakeSession(aiohttp.ClientError("boom"))).async_login()


async def test_non_json_body() -> None:
    session = FakeSession(TOKENS, (200, ValueError("not json")))
    with pytest.raises(BragerOneConnectionError):
        await client(session).async_get_parameters("D")


async def test_refresh_on_401() -> None:
    session = FakeSession(
        TOKENS,
        (401, None),
        (200, {"accessToken": "a2", "refreshToken": "r2"}),
        (200, {"status": "SUCCESS", "alarms": [7]}),
    )
    api = client(session)
    assert await api.async_get_alarms("D") == [{"code": 7}]
    paths = [c[1] for c in session.calls]
    assert paths == [
        "/auth/user",
        "/modules/alarms",
        "/auth/refresh",
        "/modules/alarms",
    ]
    assert session.calls[2][2]["json"] == {"refreshToken": "r1"}
    assert session.calls[3][2]["headers"]["Authorization"] == "Bearer a2"


async def test_refresh_fails_falls_back_to_login() -> None:
    session = FakeSession(
        TOKENS,
        (401, None),
        (401, None),
        (200, {"accessToken": "a3"}),
        (200, {"alarms": []}),
    )
    api = client(session)
    assert await api.async_get_alarms("D") == []
    assert [c[1] for c in session.calls][2:4] == ["/auth/refresh", "/auth/user"]


async def test_refresh_returns_garbage_falls_back_to_login() -> None:
    session = FakeSession(
        TOKENS,
        (401, None),
        (200, {"accessToken": None}),
        TOKENS,
        (200, {"alarms": []}),
    )
    assert await client(session).async_get_alarms("D") == []
    assert [c[1] for c in session.calls][3] == "/auth/user"


async def test_no_refresh_token_logs_in_again() -> None:
    session = FakeSession(
        (200, {"accessToken": "a1"}),
        (401, None),
        TOKENS,
        (200, {"alarms": None}),
    )
    assert await client(session).async_get_alarms("D") == []
    assert [c[1] for c in session.calls] == [
        "/auth/user",
        "/modules/alarms",
        "/auth/user",
        "/modules/alarms",
    ]


async def test_still_401_after_refresh() -> None:
    session = FakeSession(
        TOKENS,
        (401, None),
        (200, {"accessToken": "a2", "refreshToken": "r2"}),
        (401, None),
    )
    with pytest.raises(BragerOneAuthError):
        await client(session).async_get_alarms("D")


async def test_http_error() -> None:
    with pytest.raises(BragerOneConnectionError):
        await client(FakeSession(TOKENS, (503, None))).async_get_alarms("D")


async def test_parameters_errors() -> None:
    with pytest.raises(BragerOneConnectionError):
        await client(FakeSession(TOKENS, (200, []))).async_get_parameters("D")
    with pytest.raises(BragerOneConnectionError):
        await client(FakeSession(TOKENS, (200, {"X": {}}))).async_get_parameters("D")


async def test_modules_tolerates_odd_items() -> None:
    session = FakeSession(
        TOKENS,
        (200, {"objects": [{"id": 5}, {"name": "no id"}, "junk"]}),
        (200, {"data": [{"devid": "D1"}, {"devid": ""}, "junk"]}),
    )
    modules = await client(session).async_get_modules()
    assert len(modules) == 1
    module = modules[0]
    assert (module.devid, module.name, module.object_name) == ("D1", "D1", "5")
    assert module.gateway_version is None
    assert module.device_name is None


async def test_modules_no_objects() -> None:
    assert await client(FakeSession(TOKENS, (200, None))).async_get_modules() == []


async def test_commands_payload() -> None:
    session = FakeSession(TOKENS, (200, {}), (200, {}))
    api = client(session)
    await api.async_set_parameter("D", "P6", 51, 50, 1)
    await api.async_send_command("D", "BOILER_START", 1)
    assert session.calls[1][2]["json"] == {
        "pool": "P6",
        "parameter": "v51",
        "value": 50,
        "parameterName": "parameters.PARAM_51",
        "devid": "D",
        "unit": 1,
    }
    assert session.calls[2][1] == "/module/command/raw"


def test_parse_parameters() -> None:
    raw = {
        "P4": {"v0": {"value": 78}, "u0": 1, "x": {"value": [1]}, "y": {"nope": 1}},
        "P9": "junk",
    }
    assert parse_parameters(raw) == {"P4": {"v0": 78, "u0": 1}}


def test_normalise_alarms() -> None:
    assert normalise_alarms(None) == []
    assert normalise_alarms([{"code": "38"}, {"id": None}, 54]) == [
        {"code": 38},
        {"code": 54},
    ]
