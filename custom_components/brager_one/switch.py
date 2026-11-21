"""Boiler on/off switch for BragerOne."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import BragerOneError
from .const import COMMAND_BOILER_START, COMMAND_BOILER_STOP, DOMAIN
from .coordinator import BragerOneConfigEntry, BragerOneCoordinator
from .entity import BragerOneWritableEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BragerOneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the boiler switch."""
    coordinator = entry.runtime_data.coordinator
    if coordinator.data.value("P5", "s0") is not None:
        async_add_entities([BragerOneBoilerSwitch(coordinator)])


class BragerOneBoilerSwitch(BragerOneWritableEntity, SwitchEntity):
    """Starts and stops the boiler (bit 0 of status word P5 s0)."""

    _attr_translation_key = "boiler"

    def __init__(self, coordinator: BragerOneCoordinator) -> None:
        """Initialise the switch."""
        super().__init__(coordinator, "boiler")

    def _confirmed_value(self) -> bool | None:
        value = self.coordinator.data.value("P5", "s0")
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return bool(value & 1)

    @property
    def is_on(self) -> bool | None:
        """Return whether the boiler is switched on."""
        value: bool | None = self._current_value()
        return value

    async def _async_send(self, on: bool) -> None:
        command = COMMAND_BOILER_START if on else COMMAND_BOILER_STOP
        try:
            await self.coordinator.client.async_send_command(
                self.coordinator.module.devid, command, 1 if on else 0
            )
        except BragerOneError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self._set_pending(on)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the boiler."""
        await self._async_send(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the boiler."""
        await self._async_send(False)
