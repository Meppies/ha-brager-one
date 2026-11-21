"""Base entity for BragerOne."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import BragerOneError
from .const import (
    COMMAND_REFRESH_DELAY,
    COMMAND_VERIFY_DELAY,
    DOMAIN,
    LOGGER,
    WEB_ORIGIN,
)
from .coordinator import BragerOneCoordinator, command_issue_id


class BragerOneEntity(CoordinatorEntity[BragerOneCoordinator]):
    """Common base for BragerOne entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BragerOneCoordinator, key: str) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        module = coordinator.module
        self._attr_unique_id = f"{module.devid}_{key}"
        controller = coordinator.data.value("P11", "v1")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, module.devid)},
            name=module.name,
            manufacturer="Brager",
            model=module.device_name,
            serial_number=module.devid,
            sw_version=str(controller) if controller else module.device_software,
            hw_version=module.gateway_version,
            configuration_url=WEB_ORIGIN,
        )


class BragerOneWritableEntity(BragerOneEntity):
    """Entity that writes to the stove and checks that the stove follows.

    The written value is shown straight away. If the stove has not taken it
    over after a while, the command is sent once more; if it still does not
    follow, a repair issue is raised and the entity shows the stove's value.
    """

    _pending: Any = None
    _resent: bool = False
    _cancel_refresh: CALLBACK_TYPE | None = None
    _cancel_verify: CALLBACK_TYPE | None = None

    async def _async_write(self, value: Any) -> None:
        """Send the value to the stove."""
        raise NotImplementedError  # pragma: no cover

    def _confirmed_value(self) -> Any:
        """Return the value as currently reported by the cloud."""
        raise NotImplementedError  # pragma: no cover

    async def _async_command(self, value: Any) -> None:
        """Write a value, one command at a time, and start watching for it."""
        try:
            await self.coordinator.async_run_command(lambda: self._async_write(value))
        except BragerOneError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self._resent = False
        self._set_pending(value)

    def _set_pending(self, value: Any) -> None:
        self._pending = value
        self.async_write_ha_state()
        self._cancel_timers()
        self._cancel_refresh = async_call_later(
            self.hass, COMMAND_REFRESH_DELAY, self._delayed_refresh
        )
        self._cancel_verify = async_call_later(
            self.hass, COMMAND_VERIFY_DELAY, self._async_verify
        )

    def _cancel_timers(self) -> None:
        for cancel in (self._cancel_refresh, self._cancel_verify):
            if cancel is not None:
                cancel()
        self._cancel_refresh = self._cancel_verify = None

    async def async_will_remove_from_hass(self) -> None:
        """Stop pending timers."""
        self._cancel_timers()
        await super().async_will_remove_from_hass()

    async def _delayed_refresh(self, _now: datetime) -> None:
        self._cancel_refresh = None
        await self.coordinator.async_request_refresh()

    async def _async_verify(self, _now: datetime) -> None:
        """Resend once when the stove has not followed, then give up."""
        self._cancel_verify = None
        await self.coordinator.async_refresh()
        if self._pending is None:
            return
        value = self._pending
        devid = self.coordinator.module.devid
        if not self._resent:
            LOGGER.warning(
                "%s: the stove has not taken over %s yet, sending it again",
                self.entity_id,
                value,
            )
            self._resent = True
            try:
                await self.coordinator.async_run_command(
                    lambda: self._async_write(value)
                )
            except BragerOneError as err:
                LOGGER.warning("%s: resending failed: %s", self.entity_id, err)
            self._set_pending(value)
            return
        LOGGER.warning(
            "%s: the stove did not take over %s, even after sending it twice",
            self.entity_id,
            value,
        )
        self._pending = None
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            command_issue_id(devid),
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="command_not_confirmed",
            translation_placeholders={
                "entity": self.entity_id or "",
                "value": str(value),
            },
        )
        self.async_write_ha_state()

    def _current_value(self) -> Any:
        """Return the pending value while the cloud has not caught up yet."""
        if self._pending is not None:
            return self._pending
        return self._confirmed_value()

    @callback
    def _handle_coordinator_update(self) -> None:
        if self._pending is not None and self._confirmed_value() == self._pending:
            self._pending = None
            self._cancel_timers()
            ir.async_delete_issue(
                self.hass, DOMAIN, command_issue_id(self.coordinator.module.devid)
            )
        super()._handle_coordinator_update()
