"""Binary sensors for BragerOne."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import ParameterValue
from .coordinator import BragerOneConfigEntry, BragerOneCoordinator
from .entity import BragerOneEntity

PARALLEL_UPDATES = 0

# Pump status words in pool P5, as shown by the BragerOne app:
# 3 is shown as "On", 1 as "Off". Other values are not mapped yet.
PUMP_ON = 3
PUMP_OFF = frozenset({0, 1})


def pump_running(value: ParameterValue | None) -> bool | None:
    """Translate a pump status word into on, off or unknown."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value == PUMP_ON:
        return True
    if value in PUMP_OFF:
        return False
    return None


@dataclass(frozen=True, kw_only=True)
class BragerOneBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a pump status binary sensor."""

    pool: str
    parameter: str


BINARY_SENSORS: tuple[BragerOneBinarySensorDescription, ...] = (
    BragerOneBinarySensorDescription(
        key="boiler_pump",
        translation_key="boiler_pump",
        device_class=BinarySensorDeviceClass.RUNNING,
        pool="P5",
        parameter="s11",
    ),
    BragerOneBinarySensorDescription(
        key="return_pump",
        translation_key="return_pump",
        device_class=BinarySensorDeviceClass.RUNNING,
        pool="P5",
        parameter="s12",
    ),
    BragerOneBinarySensorDescription(
        key="hot_water_pump",
        translation_key="hot_water_pump",
        device_class=BinarySensorDeviceClass.RUNNING,
        pool="P5",
        parameter="s19",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BragerOneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up BragerOne binary sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        BragerOnePumpSensor(coordinator, description)
        for description in BINARY_SENSORS
        if coordinator.data.value(description.pool, description.parameter) is not None
    )


class BragerOnePumpSensor(BragerOneEntity, BinarySensorEntity):
    """Whether a pump is running."""

    entity_description: BragerOneBinarySensorDescription

    def __init__(
        self,
        coordinator: BragerOneCoordinator,
        description: BragerOneBinarySensorDescription,
    ) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return whether the pump runs."""
        description = self.entity_description
        return pump_running(
            self.coordinator.data.value(description.pool, description.parameter)
        )
