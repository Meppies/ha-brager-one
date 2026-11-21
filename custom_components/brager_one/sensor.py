"""Sensors for BragerOne."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import BragerOneSnapshot, ParameterValue
from .coordinator import BragerOneConfigEntry, BragerOneCoordinator, alarm_text
from .entity import BragerOneEntity

PARALLEL_UPDATES = 0


def _number(value: ParameterValue | None) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tenths(value: ParameterValue | None) -> float | None:
    number = _number(value)
    return None if number is None else round(number / 10, 1)


@dataclass(frozen=True, kw_only=True)
class BragerOneSensorDescription(SensorEntityDescription):
    """Describes a sensor backed by one BragerOne parameter."""

    pool: str
    parameter: str
    convert: Callable[[ParameterValue | None], float | None] = _number


def _temperature(
    key: str, parameter: str, *, enabled: bool = True
) -> BragerOneSensorDescription:
    return BragerOneSensorDescription(
        key=key,
        translation_key=key,
        pool="P4",
        parameter=parameter,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=enabled,
    )


SENSORS: tuple[BragerOneSensorDescription, ...] = (
    _temperature("boiler_temperature", "v0"),
    _temperature("return_temperature", "v1"),
    _temperature("hot_water_temperature", "v2", enabled=False),
    _temperature("feeder_temperature", "v3"),
    _temperature("outdoor_temperature", "v4", enabled=False),
    _temperature("valve_1_temperature", "v5", enabled=False),
    _temperature("buffer_temperature", "v6", enabled=False),
    _temperature("flue_gas_temperature", "v7", enabled=False),
    BragerOneSensorDescription(
        key="fuel_level",
        translation_key="fuel_level",
        pool="P4",
        parameter="v8",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    BragerOneSensorDescription(
        key="flame_brightness",
        translation_key="flame_brightness",
        pool="P4",
        parameter="v13",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    BragerOneSensorDescription(
        key="burner_power",
        translation_key="burner_power",
        pool="P4",
        parameter="v14",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        convert=_tenths,
    ),
    BragerOneSensorDescription(
        key="blower_output",
        translation_key="blower_output",
        pool="P4",
        parameter="v15",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    BragerOneSensorDescription(
        key="oxygen",
        translation_key="oxygen",
        pool="P4",
        parameter="v16",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    BragerOneSensorDescription(
        key="operating_state_code",
        translation_key="operating_state_code",
        pool="P5",
        parameter="s3",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BragerOneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up BragerOne sensors."""
    coordinator = entry.runtime_data.coordinator
    snapshot = coordinator.data
    entities: list[SensorEntity] = [
        BragerOneSensor(coordinator, description)
        for description in SENSORS
        if snapshot.value(description.pool, description.parameter) is not None
    ]
    entities.append(BragerOneAlarmSensor(coordinator))
    async_add_entities(entities)


class BragerOneSensor(BragerOneEntity, SensorEntity):
    """A sensor that reads one parameter."""

    entity_description: BragerOneSensorDescription

    def __init__(
        self,
        coordinator: BragerOneCoordinator,
        description: BragerOneSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        """Return the parameter value."""
        description = self.entity_description
        return description.convert(
            self.coordinator.data.value(description.pool, description.parameter)
        )


class BragerOneAlarmSensor(BragerOneEntity, SensorEntity):
    """Number of active alarms, with their descriptions as attributes."""

    _attr_translation_key = "active_alarms"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: BragerOneCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, "active_alarms")

    @property
    def _snapshot(self) -> BragerOneSnapshot:
        return self.coordinator.data

    @property
    def native_value(self) -> int:
        """Return how many alarms are active."""
        return len(self._snapshot.alarms)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the active alarms."""
        return {
            "alarms": [
                {"code": alarm["code"], "description": alarm_text(alarm["code"])}
                for alarm in self._snapshot.alarms
            ]
        }
