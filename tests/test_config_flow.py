"""Tests for the config flow."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.brager_one.const import (
    API_BASE_URL,
    CONF_DEVID,
    CONF_OBJECT_ID,
    DOMAIN,
)

from .conftest import DEVID, EMAIL, PASSWORD, TOKENS, load, mock_api

USER_INPUT = {CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD}

TWO_MODULES = {
    "data": [
        *load("modules.json")["data"],
        {"devid": "KLMNOPQRST", "name": "Second stove", "gateway": {}, "devices": []},
        {"name": "no devid"},
        "junk",
    ]
}


@pytest.fixture(autouse=True)
def no_setup() -> object:
    """Do not set the entry up after the flow."""
    with patch("custom_components.brager_one.async_setup_entry", return_value=True):
        yield


async def test_user_flow_single_module(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """One module is created straight away."""
    mock_api(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Pellet stove"
    assert result["data"] == {
        **USER_INPUT,
        CONF_DEVID: DEVID,
        CONF_OBJECT_ID: 1001,
    }
    assert result["result"].unique_id == DEVID


async def test_user_flow_pick_module(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """With several modules the user picks one."""
    mock_api(aioclient_mock, modules=TWO_MODULES)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "module"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVID: "KLMNOPQRST"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Second stove"


async def test_user_flow_skips_configured(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
) -> None:
    """Modules that are already added are not offered again."""
    mock_entry.add_to_hass(hass)
    mock_api(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("status", "modules", "error"),
    [
        (401, None, "invalid_auth"),
        (500, None, "cannot_connect"),
        (200, {"data": []}, "no_modules"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    status: int,
    modules: object,
    error: str,
) -> None:
    """Errors are shown on the form and the flow recovers."""
    mock_api(aioclient_mock, login_status=status, modules=modules)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    aioclient_mock.clear_requests()
    mock_api(aioclient_mock)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_unexpected_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Unexpected exceptions are caught."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with patch(
        "custom_components.brager_one.config_flow.BragerOneClient.async_login",
        side_effect=RuntimeError,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["errors"] == {"base": "unknown"}


async def test_reauth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
) -> None:
    """Reauth stores the new password."""
    mock_entry.add_to_hass(hass)
    result = await mock_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    aioclient_mock.post(f"{API_BASE_URL}/auth/user", status=401)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    aioclient_mock.clear_requests()
    mock_api(aioclient_mock)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_entry.data[CONF_PASSWORD] == "new"


async def test_reauth_wrong_account(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
) -> None:
    """Reauth aborts when the module is not in the account."""
    mock_entry.add_to_hass(hass)
    result = await mock_entry.start_reauth_flow(hass)
    mock_api(
        aioclient_mock,
        modules={"data": [{"devid": "OTHER", "name": "x"}]},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "module_missing"


async def test_reconfigure(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
) -> None:
    """Reconfigure changes the account."""
    mock_entry.add_to_hass(hass)
    result = await mock_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"

    aioclient_mock.post(f"{API_BASE_URL}/auth/user", status=500)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: "new@example.com", CONF_PASSWORD: "pw"}
    )
    assert result["errors"] == {"base": "cannot_connect"}

    aioclient_mock.clear_requests()
    mock_api(aioclient_mock)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: "new@example.com", CONF_PASSWORD: "pw"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_entry.data[CONF_EMAIL] == "new@example.com"


async def test_reconfigure_wrong_account(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
) -> None:
    """Reconfigure refuses an account without the module."""
    mock_entry.add_to_hass(hass)
    result = await mock_entry.start_reconfigure_flow(hass)
    aioclient_mock.post(f"{API_BASE_URL}/auth/user", json=TOKENS)
    aioclient_mock.get(f"{API_BASE_URL}/objects", json={"objects": []})
    aioclient_mock.get(f"{API_BASE_URL}/objects", json={"objects": []})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    # An account without modules is reported as an error, not an abort.
    assert result["errors"] == {"base": "no_modules"}

    aioclient_mock.clear_requests()
    mock_api(aioclient_mock, modules={"data": [{"devid": "OTHER"}]})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "module_missing"


async def test_options_flow_sets_interval(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
) -> None:
    """The polling interval can be changed and defaults to 60 seconds."""
    mock_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    schema_default = next(iter(result["data_schema"].schema)).description
    assert schema_default == {"suggested_value": 60}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 10.0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_entry.options == {CONF_SCAN_INTERVAL: 10}
