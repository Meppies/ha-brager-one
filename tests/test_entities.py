"""Tests for the entity platforms."""

from __future__ import annotations

from datetime import timedelta
import json

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.brager_one.binary_sensor import pump_running
from custom_components.brager_one.const import API_BASE_URL

from .conftest import DEVID, load, mock_api, setup_integration


def _params_with(**changes: dict[str, object]) -> dict[str, object]:
    data = load("parameters.json")
    for pool, values in changes.items():
        for key, value in values.items():
            data[DEVID].setdefault(pool, {})[key] = {"value": value}
    return data


async def test_sensors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
) -> None:
    """Sensor values come from the right parameters."""
    mock_api(aioclient_mock)
    await setup_integration(hass, mock_entry)
    expected = {
        "sensor.pellet_stove_boiler_temperature": "78.0",
        "sensor.pellet_stove_return_temperature": "70.0",
        "sensor.pellet_stove_feeder_temperature": "58.5",
        "sensor.pellet_stove_flame_brightness": "0.0",
        "sensor.pellet_stove_burner_power": "12.5",
        "sensor.pellet_stove_blower_output": "40.0",
        "sensor.pellet_stove_operating_state_code": "5.0",
        "sensor.pellet_stove_operating_state": "standby",
        "sensor.pellet_stove_last_alarm": "2026-11-16T20:55:30+00:00",
        "sensor.pellet_stove_active_alarms": "0",
        "binary_sensor.pellet_stove_boiler_pump": STATE_ON,
        "binary_sensor.pellet_stove_return_pump": STATE_ON,
        "binary_sensor.pellet_stove_hot_water_pump": STATE_OFF,
        "switch.pellet_stove_boiler": STATE_ON,
        "number.pellet_stove_boiler_setpoint": "77.0",
        "number.pellet_stove_hot_water_setpoint": "45.0",
    }
    for entity_id, state in expected.items():
        assert hass.states.get(entity_id).state == state, entity_id

    last = hass.states.get("sensor.pellet_stove_last_alarm").attributes
    assert last["code"] == 500
    assert last["description"] == "Serious alarm cleared remotely by the user"
    assert last["ended"] == "2026-11-16T21:04:27.000000Z"
    assert [a["code"] for a in last["recent"]] == [500, 54, 55]
    assert last["recent"][2]["ended"] is None

    setpoint = hass.states.get("number.pellet_stove_boiler_setpoint")
    assert setpoint.attributes["min"] == 65
    assert setpoint.attributes["max"] == 85

    # Parameters missing on this stove create no entity.
    registry = er.async_get(hass)
    assert registry.async_get("sensor.pellet_stove_flue_gas_temperature") is None
    # Niche sensors exist but are disabled by default.
    entry = registry.async_get("sensor.pellet_stove_outdoor_temperature")
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert entry.unique_id == f"{DEVID}_outdoor_temperature"


async def test_sensor_odd_values(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
) -> None:
    """Non-numeric values give an unknown state instead of an error."""
    mock_api(
        aioclient_mock,
        parameters=_params_with(
            P4={"v0": "n/a", "v14": True}, P5={"s0": "x", "s5": 0x0700}
        ),
        history={"alarms": {"data": []}},
    )
    await setup_integration(hass, mock_entry)
    assert hass.states.get("sensor.pellet_stove_operating_state").state == "unknown"
    last = hass.states.get("sensor.pellet_stove_last_alarm")
    assert last.state == "unknown"
    assert last.attributes["recent"] == []
    assert last.attributes["code"] is None
    assert hass.states.get("sensor.pellet_stove_boiler_temperature").state == "unknown"
    assert hass.states.get("sensor.pellet_stove_burner_power").state == "unknown"
    assert hass.states.get("switch.pellet_stove_boiler").state == "unknown"


async def test_number_fallback_limits(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
) -> None:
    """Without limits from the cloud the documented range is used."""
    data = load("parameters.json")
    for key in ("n0", "x0", "u0"):
        del data[DEVID]["P6"][key]
    data[DEVID]["P6"]["v0"] = {"value": True}
    mock_api(aioclient_mock, parameters=data)
    await setup_integration(hass, mock_entry)
    state = hass.states.get("number.pellet_stove_boiler_setpoint")
    assert state.state == "unknown"
    assert state.attributes["min"] == 65
    assert state.attributes["max"] == 85

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: "number.pellet_stove_boiler_setpoint", ATTR_VALUE: 70},
        blocking=True,
    )
    call = [
        c for c in aioclient_mock.mock_calls if str(c[1]).endswith("/module/command")
    ]
    assert call[-1][2]["unit"] == 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (3, True),
        (1, False),
        (0, False),
        (2, None),
        (True, None),
        ("3", None),
        (None, None),
    ],
)
def test_pump_running(value: object, expected: bool | None) -> None:
    """Pump status words map to on, off or unknown."""
    assert pump_running(value) is expected  # type: ignore[arg-type]


async def test_switch(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The switch sends the raw boiler commands and shows the new state."""
    mock_api(aioclient_mock)
    await setup_integration(hass, mock_entry)

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: "switch.pellet_stove_boiler"},
        blocking=True,
    )
    raw = [c for c in aioclient_mock.mock_calls if str(c[1]).endswith("/command/raw")]
    assert raw[-1][2] == {"command": "BOILER_STOP", "devid": DEVID, "value": 0}
    # The cloud still says "on"; the switch keeps showing the command it sent.
    assert hass.states.get("switch.pellet_stove_boiler").state == STATE_OFF
    await hass.async_block_till_done()
    assert hass.states.get("switch.pellet_stove_boiler").state == STATE_OFF

    # After the pending window the cloud value wins again.
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("switch.pellet_stove_boiler").state == STATE_ON

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "switch.pellet_stove_boiler"},
        blocking=True,
    )
    raw = [c for c in aioclient_mock.mock_calls if str(c[1]).endswith("/command/raw")]
    assert raw[-1][2] == {"command": "BOILER_START", "devid": DEVID, "value": 1}
    await hass.async_block_till_done()
    # Confirmed by the cloud straight away: pending state cleared.
    assert hass.states.get("switch.pellet_stove_boiler").state == STATE_ON


async def test_switch_command_fails(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
) -> None:
    """A rejected command raises a translated error."""
    mock_api(aioclient_mock)
    await setup_integration(hass, mock_entry)
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{API_BASE_URL}/module/command/raw", status=500)
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: "switch.pellet_stove_boiler"},
            blocking=True,
        )
    assert err.value.translation_key == "command_failed"


async def test_number_set(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
) -> None:
    """Setting a setpoint writes P6 with the parameter's unit."""
    mock_api(aioclient_mock)
    await setup_integration(hass, mock_entry)
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: "number.pellet_stove_boiler_setpoint", ATTR_VALUE: 80},
        blocking=True,
    )
    call = [
        c for c in aioclient_mock.mock_calls if str(c[1]).endswith("/module/command")
    ]
    assert call[-1][2] == {
        "pool": "P6",
        "parameter": "v0",
        "value": 80,
        "parameterName": "parameters.PARAM_0",
        "devid": DEVID,
        "unit": 1,
    }
    assert hass.states.get("number.pellet_stove_boiler_setpoint").state == "80.0"


async def test_number_out_of_range(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
) -> None:
    """Values outside the controller's limits are refused before sending."""
    mock_api(aioclient_mock)
    await setup_integration(hass, mock_entry)
    entity = hass.data["entity_components"][NUMBER_DOMAIN].get_entity(
        "number.pellet_stove_hot_water_setpoint"
    )
    with pytest.raises(ServiceValidationError) as err:
        await entity.async_set_native_value(90)
    assert err.value.translation_key == "out_of_range"


async def test_number_command_fails(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
) -> None:
    """A failed write raises a translated error."""
    mock_api(aioclient_mock)
    await setup_integration(hass, mock_entry)
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{API_BASE_URL}/module/command", status=500)
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: "number.pellet_stove_boiler_setpoint", ATTR_VALUE: 70},
            blocking=True,
        )
    assert err.value.translation_key == "command_failed"


async def test_diagnostics_redacts(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
) -> None:
    """Diagnostics contain the parameters but no credentials or devid."""
    from custom_components.brager_one.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    mock_api(aioclient_mock)
    await setup_integration(hass, mock_entry)
    result = await async_get_config_entry_diagnostics(hass, mock_entry)
    dumped = json.dumps(result)
    assert "secret" not in dumped
    assert "user@example.com" not in dumped
    assert DEVID not in dumped
    assert result["parameters"]["P4"]["v0"] == 78
    assert result["module"]["gateway_version"] == "V2.09"


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        (0x0500, ("standby", "5.0")),
        (0x5300, ("work", "3.0")),
        (0x0400, ("damping", "4.0")),
        (0x0100, ("cleaning", "1.0")),
        (0x0200, ("unknown", "2.0")),
        ("x", ("unknown", "unknown")),
    ],
)
async def test_operating_state_from_status_word(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
    word: object,
    expected: tuple[str, str],
) -> None:
    """The state comes from bits 8-11 of P5 s5, as matched against the app."""
    state, code = expected
    mock_api(aioclient_mock, parameters=_params_with(P5={"s5": word}))
    await setup_integration(hass, mock_entry)
    assert hass.states.get("sensor.pellet_stove_operating_state").state == state
    assert hass.states.get("sensor.pellet_stove_operating_state_code").state == code
