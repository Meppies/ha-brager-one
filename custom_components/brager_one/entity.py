"""Base entity for BragerOne."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import COMMAND_REFRESH_DELAY, DOMAIN, PENDING_TIMEOUT, WEB_ORIGIN
from .coordinator import BragerOneCoordinator


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
    """Entity that writes to the stove and shows the new value until confirmed."""

    _pending: Any = None
    _pending_since: datetime | None = None

    def _set_pending(self, value: Any) -> None:
        self._pending = value
        self._pending_since = dt_util.utcnow()
        self.async_write_ha_state()
        self.async_on_remove(
            async_call_later(self.hass, COMMAND_REFRESH_DELAY, self._delayed_refresh)
        )

    async def _delayed_refresh(self, _now: datetime) -> None:
        await self.coordinator.async_request_refresh()

    def _confirmed_value(self) -> Any:
        """Return the value as currently reported by the cloud."""
        raise NotImplementedError  # pragma: no cover

    def _current_value(self) -> Any:
        """Return the pending value while the cloud has not caught up yet."""
        if self._pending is not None:
            return self._pending
        return self._confirmed_value()

    @callback
    def _handle_coordinator_update(self) -> None:
        if self._pending is not None and (
            self._confirmed_value() == self._pending
            or self._pending_since is None
            or dt_util.utcnow() - self._pending_since > PENDING_TIMEOUT
        ):
            self._pending = None
            self._pending_since = None
        super()._handle_coordinator_update()
