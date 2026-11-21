"""Setpoints for BragerOne."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import BragerOneError
from .const import DOMAIN
from .coordinator import BragerOneConfigEntry, BragerOneCoordinator
from .entity import BragerOneWritableEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class BragerOneNumberDescription(NumberEntityDescription):
    """Describes a writable setting in pool P6.

    Every P6 setting comes with its own limits: ``v<n>`` value, ``n<n>``
    minimum, ``x<n>`` maximum and ``u<n>`` unit code.
    """

    index: int
    fallback_min: float
    fallback_max: float


NUMBERS: tuple[BragerOneNumberDescription, ...] = (
    BragerOneNumberDescription(
        key="boiler_setpoint",
        translation_key="boiler_setpoint",
        index=0,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_step=1,
        mode=NumberMode.BOX,
        fallback_min=65,
        fallback_max=85,
    ),
    BragerOneNumberDescription(
        key="hot_water_setpoint",
        translation_key="hot_water_setpoint",
        index=51,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_step=1,
        mode=NumberMode.BOX,
        fallback_min=30,
        fallback_max=70,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BragerOneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up BragerOne setpoints."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        BragerOneSetpoint(coordinator, description)
        for description in NUMBERS
        if coordinator.data.value("P6", f"v{description.index}") is not None
    )


class BragerOneSetpoint(BragerOneWritableEntity, NumberEntity):
    """A temperature setpoint."""

    entity_description: BragerOneNumberDescription

    def __init__(
        self,
        coordinator: BragerOneCoordinator,
        description: BragerOneNumberDescription,
    ) -> None:
        """Initialise the setpoint."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    def _p6(self, prefix: str) -> float | None:
        value = self.coordinator.data.value(
            "P6", f"{prefix}{self.entity_description.index}"
        )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def _confirmed_value(self) -> float | None:
        return self._p6("v")

    @property
    def native_value(self) -> float | None:
        """Return the setpoint."""
        value: float | None = self._current_value()
        return value

    @property
    def native_min_value(self) -> float:
        """Return the minimum the controller accepts."""
        value = self._p6("n")
        return self.entity_description.fallback_min if value is None else value

    @property
    def native_max_value(self) -> float:
        """Return the maximum the controller accepts."""
        value = self._p6("x")
        return self.entity_description.fallback_max if value is None else value

    async def async_set_native_value(self, value: float) -> None:
        """Write a new setpoint."""
        if not self.native_min_value <= value <= self.native_max_value:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="out_of_range",
                translation_placeholders={
                    "value": str(value),
                    "min": str(self.native_min_value),
                    "max": str(self.native_max_value),
                },
            )
        unit = self.coordinator.data.value("P6", f"u{self.entity_description.index}")
        try:
            await self.coordinator.client.async_set_parameter(
                self.coordinator.module.devid,
                "P6",
                self.entity_description.index,
                int(round(value)),
                unit if isinstance(unit, int) and not isinstance(unit, bool) else 0,
            )
        except BragerOneError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self._set_pending(float(round(value)))
