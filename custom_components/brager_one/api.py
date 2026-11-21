"""Async client for the (unofficial) BragerOne cloud API.

The client talks to the same endpoints as the BragerOne web app at
https://one.brager.pl. It never creates its own HTTP session: Home Assistant
passes its shared aiohttp session in.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .const import API_BASE_URL, APP_VERSION, LOGGER, WEB_ORIGIN

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)

type ParameterValue = int | float | str | bool
type Pools = dict[str, dict[str, ParameterValue]]


class BragerOneError(Exception):
    """Base error for the BragerOne client."""


class BragerOneConnectionError(BragerOneError):
    """The BragerOne cloud could not be reached or returned an error."""


class BragerOneAuthError(BragerOneError):
    """The credentials were rejected."""


@dataclass(frozen=True, slots=True)
class BragerOneModule:
    """A BragerOne module (one controller behind one gateway)."""

    devid: str
    name: str
    object_id: int
    object_name: str
    gateway_version: str | None = None
    device_name: str | None = None
    device_software: str | None = None


@dataclass(slots=True)
class BragerOneSnapshot:
    """Everything one poll returns for a module."""

    pools: Pools = field(default_factory=dict)
    alarms: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    alarm_texts: dict[str, str] = field(default_factory=dict)

    def alarm_text(self, code: int) -> str:
        """Return the alarm description in the Home Assistant language."""
        if text := self.alarm_texts.get(str(code)):
            return text
        return self.alarm_texts.get("unknown", "Unknown alarm {code}").replace(
            "{code}", str(code)
        )

    def value(self, pool: str, key: str) -> ParameterValue | None:
        """Return a single parameter value, or None when it is missing."""
        return self.pools.get(pool, {}).get(key)


def parse_parameters(raw: dict[str, Any]) -> Pools:
    """Flatten ``{"P4": {"v0": {"value": 78, ...}}}`` into ``{"P4": {"v0": 78}}``."""
    pools: Pools = {}
    for pool, items in raw.items():
        if not isinstance(items, dict):
            continue
        flat: dict[str, ParameterValue] = {}
        for key, item in items.items():
            value = item.get("value") if isinstance(item, dict) else item
            if isinstance(value, (bool, int, float, str)):
                flat[key] = value
        pools[pool] = flat
    return pools


def normalise_alarms(raw: Any) -> list[dict[str, Any]]:
    """Return alarms as ``{"code", "started", "ended"}`` dicts.

    BragerOne returns ``{"id", "devid", "created_at", "finished_at"}``; only
    the code and the two timestamps are kept, so the module id never ends up
    in attributes or diagnostics.
    """
    if not isinstance(raw, list):
        return []
    alarms: list[dict[str, Any]] = []
    for item in raw:
        data = item if isinstance(item, dict) else {}
        code = data.get("id", data.get("code")) if data else item
        if isinstance(code, bool) or not isinstance(code, (int, str)):
            continue
        try:
            number = int(code)
        except ValueError:
            continue
        alarms.append(
            {
                "code": number,
                "started": data.get("created_at"),
                "ended": data.get("finished_at"),
            }
        )
    return alarms


class BragerOneClient:
    """Client for io.brager.pl."""

    def __init__(
        self, session: aiohttp.ClientSession, email: str, password: str
    ) -> None:
        """Initialise the client."""
        self._session = session
        self._email = email
        self._password = password
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._auth_lock = asyncio.Lock()

    @property
    def email(self) -> str:
        """Return the account e-mail address."""
        return self._email

    def _headers(self, *, auth: bool) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Origin": WEB_ORIGIN,
            "Referer": f"{WEB_ORIGIN}/",
            "x-appversion": APP_VERSION,
        }
        if auth and self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    async def _raw_request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str | int] | None = None,
        auth: bool = True,
    ) -> tuple[int, Any]:
        try:
            async with self._session.request(
                method,
                f"{API_BASE_URL}{path}",
                json=json,
                params=params,
                headers=self._headers(auth=auth),
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                try:
                    body: Any = await resp.json(content_type=None)
                except ValueError:
                    body = None
                return resp.status, body
        except (aiohttp.ClientError, TimeoutError) as err:
            raise BragerOneConnectionError(
                f"Error talking to BragerOne: {err!r}"
            ) from err

    async def async_login(self) -> None:
        """Log in with e-mail and password."""
        status, body = await self._raw_request(
            "POST",
            "/auth/user",
            json={"email": self._email, "password": self._password},
            auth=False,
        )
        if status in (400, 401, 403, 422):
            raise BragerOneAuthError("BragerOne rejected the credentials")
        if status != 200 or not isinstance(body, dict):
            raise BragerOneConnectionError(f"Login failed with HTTP {status}")
        self._store_tokens(body)

    def _store_tokens(self, body: dict[str, Any]) -> None:
        access = body.get("accessToken")
        if not isinstance(access, str) or not access:
            raise BragerOneConnectionError("BragerOne returned no access token")
        self._access_token = access
        refresh = body.get("refreshToken")
        self._refresh_token = refresh if isinstance(refresh, str) else None

    async def _async_refresh(self) -> None:
        """Renew the tokens, falling back to a full login."""
        if self._refresh_token:
            status, body = await self._raw_request(
                "POST",
                "/auth/refresh",
                json={"refreshToken": self._refresh_token},
                auth=False,
            )
            if status == 200 and isinstance(body, dict):
                try:
                    self._store_tokens(body)
                except BragerOneConnectionError:
                    pass
                else:
                    return
            LOGGER.debug("Token refresh failed with HTTP %s, logging in again", status)
        self._access_token = None
        self._refresh_token = None
        await self.async_login()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str | int] | None = None,
    ) -> Any:
        """Do an authenticated request, renewing the token once on 401."""
        sent_token = self._access_token
        if sent_token is None:
            async with self._auth_lock:
                if self._access_token is None:
                    await self.async_login()
            sent_token = self._access_token
        status, body = await self._raw_request(method, path, json=json, params=params)
        if status == 401:
            async with self._auth_lock:
                # Another call may already have renewed the token.
                if self._access_token == sent_token:
                    await self._async_refresh()
            status, body = await self._raw_request(
                method, path, json=json, params=params
            )
            if status == 401:
                raise BragerOneAuthError("BragerOne keeps rejecting the session")
        if status >= 400:
            raise BragerOneConnectionError(f"{method} {path} returned HTTP {status}")
        return body

    async def async_get_modules(self) -> list[BragerOneModule]:
        """Return every module in every object of the account."""
        body = await self._request("GET", "/objects")
        objects = body.get("objects") if isinstance(body, dict) else None
        modules: list[BragerOneModule] = []
        for obj in objects or []:
            if not isinstance(obj, dict) or "id" not in obj:
                continue
            object_id = int(obj["id"])
            data = await self._request(
                "GET",
                "/modules",
                params={"page": 1, "limit": 999, "group_id": object_id},
            )
            for item in (data.get("data") if isinstance(data, dict) else None) or []:
                if not isinstance(item, dict) or not item.get("devid"):
                    continue
                gateway = item.get("gateway") or {}
                devices = item.get("devices") or []
                device = devices[0] if devices and isinstance(devices[0], dict) else {}
                devid = str(item["devid"])
                modules.append(
                    BragerOneModule(
                        devid=devid,
                        name=str(item.get("name") or devid),
                        object_id=object_id,
                        object_name=str(obj.get("name") or object_id),
                        gateway_version=gateway.get("version"),
                        device_name=device.get("name"),
                        device_software=device.get("sw_ver_txt"),
                    )
                )
        return modules

    async def async_get_parameters(self, devid: str) -> Pools:
        """Return all parameter pools of a module."""
        body = await self._request(
            "POST", "/modules/parameters", json={"modules": [devid]}
        )
        if not isinstance(body, dict):
            raise BragerOneConnectionError("Unexpected parameters response")
        raw = body.get(devid)
        if not isinstance(raw, dict):
            raise BragerOneConnectionError(f"No parameters returned for {devid}")
        return parse_parameters(raw)

    async def async_get_alarms(self, devid: str) -> list[dict[str, Any]]:
        """Return the active alarms of a module."""
        body = await self._request("POST", "/modules/alarms", json={"modules": [devid]})
        alarms = body.get("alarms") if isinstance(body, dict) else None
        return normalise_alarms(alarms)

    async def async_get_alarm_history(self, devid: str) -> list[dict[str, Any]]:
        """Return the most recent alarms (first page, newest first)."""
        body = await self._request(
            "POST",
            "/modules/alarms/history",
            json={"modules": [devid], "page": 1, "filters": {}},
        )
        root = body.get("alarms") if isinstance(body, dict) else None
        items = root.get("data") if isinstance(root, dict) else root
        return normalise_alarms(items)

    async def async_set_parameter(
        self, devid: str, pool: str, index: int, value: int, unit: int = 0
    ) -> None:
        """Write a settable parameter, for example the boiler setpoint (P6 v0)."""
        await self._request(
            "POST",
            "/module/command",
            json={
                "pool": pool,
                "parameter": f"v{index}",
                "value": value,
                "parameterName": f"parameters.PARAM_{index}",
                "devid": devid,
                "unit": unit,
            },
        )

    async def async_send_command(self, devid: str, command: str, value: int) -> None:
        """Send a raw module command such as BOILER_START."""
        await self._request(
            "POST",
            "/module/command/raw",
            json={"command": command, "devid": devid, "value": value},
        )
