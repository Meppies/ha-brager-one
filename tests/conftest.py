"""Fixtures for BragerOne tests."""

from __future__ import annotations

from collections.abc import Generator
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.brager_one.const import (
    API_BASE_URL,
    CONF_DEVID,
    CONF_OBJECT_ID,
    DOMAIN,
)

FIXTURES = Path(__file__).parent / "fixtures"
DEVID = "ABCDEFGHIJ"
EMAIL = "user@example.com"
PASSWORD = "secret"
TOKENS = {"accessToken": "access-1", "refreshToken": "refresh-1"}


def load(name: str) -> Any:
    """Load a JSON fixture."""
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in every test."""


@pytest.fixture(autouse=True)
def no_command_delay() -> Generator[None]:
    """Make the post-command refresh immediate."""
    with patch("custom_components.brager_one.entity.COMMAND_REFRESH_DELAY", 0):
        yield


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    """Return a config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Pellet stove",
        unique_id=DEVID,
        data={
            CONF_EMAIL: EMAIL,
            CONF_PASSWORD: PASSWORD,
            CONF_DEVID: DEVID,
            CONF_OBJECT_ID: 1001,
        },
    )


def mock_api(
    aioclient_mock: AiohttpClientMocker,
    *,
    parameters: Any = None,
    alarms: Any = None,
    history: Any = None,
    modules: Any = None,
    login_status: int = 200,
) -> None:
    """Register the standard BragerOne responses."""
    aioclient_mock.post(f"{API_BASE_URL}/auth/user", status=login_status, json=TOKENS)
    aioclient_mock.get(f"{API_BASE_URL}/objects", json=load("objects.json"))
    aioclient_mock.get(
        f"{API_BASE_URL}/modules",
        params={"page": 1, "limit": 999, "group_id": 1001},
        json=modules if modules is not None else load("modules.json"),
    )
    aioclient_mock.post(
        f"{API_BASE_URL}/modules/parameters",
        json=parameters if parameters is not None else load("parameters.json"),
    )
    aioclient_mock.post(
        f"{API_BASE_URL}/modules/alarms",
        json={"status": "SUCCESS", "alarms": alarms if alarms is not None else []},
    )
    aioclient_mock.post(
        f"{API_BASE_URL}/modules/alarms/history",
        json=history if history is not None else load("alarm_history.json"),
    )
    aioclient_mock.post(f"{API_BASE_URL}/module/command", json={"status": "SUCCESS"})
    aioclient_mock.post(
        f"{API_BASE_URL}/module/command/raw", json={"status": "SUCCESS"}
    )


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add and set up the entry."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
