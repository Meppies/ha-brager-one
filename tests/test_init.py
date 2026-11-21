"""Tests for setup, unload and the coordinator."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.brager_one.const import API_BASE_URL, DOMAIN

from .conftest import DEVID, TOKENS, load, mock_api, setup_integration


async def test_setup_and_unload(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
) -> None:
    """The entry loads, creates entities and unloads cleanly."""
    mock_api(aioclient_mock)
    await setup_integration(hass, mock_entry)
    assert mock_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.pellet_stove_boiler_temperature").state == "78.0"

    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_auth_failed(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
) -> None:
    """Rejected credentials start a reauth flow."""
    mock_api(aioclient_mock, login_status=401)
    await setup_integration(hass, mock_entry)
    assert mock_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_setup_not_ready(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
) -> None:
    """A cloud outage retries later."""
    aioclient_mock.post(f"{API_BASE_URL}/auth/user", json=TOKENS)
    aioclient_mock.get(f"{API_BASE_URL}/objects", status=502)
    await setup_integration(hass, mock_entry)
    assert mock_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_module_missing(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
) -> None:
    """A module that left the account is a hard error."""
    mock_api(aioclient_mock, modules={"data": []})
    await setup_integration(hass, mock_entry)
    assert mock_entry.state is ConfigEntryState.SETUP_ERROR


async def test_first_refresh_fails(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
) -> None:
    """A failing first poll retries setup."""
    mock_api(aioclient_mock, parameters={"OTHER": {}})
    await setup_integration(hass, mock_entry)
    assert mock_entry.state is ConfigEntryState.SETUP_RETRY


async def test_update_failure_marks_unavailable(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Entities become unavailable when polling fails and recover after."""
    mock_api(aioclient_mock)
    await setup_integration(hass, mock_entry)

    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{API_BASE_URL}/modules/parameters", status=500)
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert (
        hass.states.get("sensor.pellet_stove_boiler_temperature").state
        == STATE_UNAVAILABLE
    )

    aioclient_mock.clear_requests()
    mock_api(aioclient_mock)
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.pellet_stove_boiler_temperature").state == "78.0"


async def test_update_auth_failure_starts_reauth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A session that cannot be renewed starts reauth."""
    mock_api(aioclient_mock)
    await setup_integration(hass, mock_entry)

    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{API_BASE_URL}/modules/parameters", status=401)
    aioclient_mock.post(f"{API_BASE_URL}/auth/refresh", status=401)
    aioclient_mock.post(f"{API_BASE_URL}/auth/user", status=401)
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_alarm_repair_issue(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """An active alarm raises a repair issue that clears with the alarm."""
    mock_api(aioclient_mock, alarms=[{"id": 38}, 54, "junk"])
    await setup_integration(hass, mock_entry)

    issue = issue_registry.async_get_issue(DOMAIN, f"active_alarm_{DEVID}")
    assert issue is not None
    assert issue.translation_placeholders == {
        "name": "Pellet stove",
        "alarms": "Out of fuel, Ignition failed",
    }
    state = hass.states.get("sensor.pellet_stove_active_alarms")
    assert state.state == "2"
    assert state.attributes["alarms"] == [
        {"code": 38, "description": "Out of fuel"},
        {"code": 54, "description": "Ignition failed"},
    ]

    aioclient_mock.clear_requests()
    mock_api(aioclient_mock)
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert issue_registry.async_get_issue(DOMAIN, f"active_alarm_{DEVID}") is None


async def test_remove_entry_deletes_issue(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Removing the entry removes its repair issue."""
    mock_api(aioclient_mock, alarms=[999])
    await setup_integration(hass, mock_entry)
    issue = issue_registry.async_get_issue(DOMAIN, f"active_alarm_{DEVID}")
    assert issue is not None
    assert issue.translation_placeholders["alarms"] == "Unknown alarm 999"

    await hass.config_entries.async_remove(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert issue_registry.async_get_issue(DOMAIN, f"active_alarm_{DEVID}") is None


async def test_device_info(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
) -> None:
    """The module shows up as one device with its firmware."""
    from homeassistant.helpers import device_registry as dr

    mock_api(aioclient_mock)
    await setup_integration(hass, mock_entry)
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, DEVID)})
    assert device is not None
    assert device.name == "Pellet stove"
    assert device.sw_version == "Z.HT900TO v2.12 Mar 12 2019"
    assert device.hw_version == "V2.09"
    assert device.model == "HT Connect Tronic"
    assert load("parameters.json")[DEVID]["P4"]["v0"]["value"] == 78
