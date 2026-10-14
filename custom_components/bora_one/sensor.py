"""Sensors for BORA One."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BoraOneConfigEntry, BoraOneCoordinator
from .entity import BoraOneEntity, BoraOneZoneEntity, end_time
from .models import (
    AssistPhase,
    AssistProgram,
    Cooktop,
    CookingZone,
    ExtractorMode,
    KeepWarmMode,
    ZonePosition,
    ZoneState,
)

PARALLEL_UPDATES = 0

COOKTOP_STATUSES = ["off", "standby", "cooking", "paused", "after_run", "error"]


def _cooktop_status(cooktop: Cooktop) -> str:
    if not cooktop.online:
        return "off"
    if cooktop.errors:
        return "error"
    if cooktop.paused:
        return "paused"
    if cooktop.is_cooking:
        return "cooking"
    if cooktop.extractor and cooktop.extractor.mode is ExtractorMode.AFTER_RUN:
        return "after_run"
    return "standby"


@dataclass(frozen=True, kw_only=True)
class BoraOneSensorDescription(SensorEntityDescription):
    """Describes a cooktop-level sensor."""

    value_fn: Callable[[Cooktop], Any]
    exists_fn: Callable[[BoraOneCoordinator], bool] = lambda _: True
    remaining_time: bool = False
    """value_fn returns seconds remaining; expose as end timestamp."""


@dataclass(frozen=True, kw_only=True)
class BoraOneZoneSensorDescription(SensorEntityDescription):
    """Describes a cooking zone sensor."""

    value_fn: Callable[[CookingZone], Any]
    remaining_time: bool = False


def _has_extractor(coordinator: BoraOneCoordinator) -> bool:
    return coordinator.has_extractor


COOKTOP_SENSORS: tuple[BoraOneSensorDescription, ...] = (
    BoraOneSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=COOKTOP_STATUSES,
        value_fn=_cooktop_status,
    ),
    BoraOneSensorDescription(
        key="active_zones",
        translation_key="active_zones",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.active_zone_count,
    ),
    BoraOneSensorDescription(
        key="error",
        translation_key="error",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: ", ".join(c.errors) if c.errors else "none",
    ),
    BoraOneSensorDescription(
        key="extractor_mode",
        translation_key="extractor_mode",
        device_class=SensorDeviceClass.ENUM,
        options=[m.value for m in ExtractorMode],
        exists_fn=_has_extractor,
        value_fn=lambda c: c.extractor.mode.value if c.extractor else None,
    ),
    BoraOneSensorDescription(
        key="extractor_fan_level",
        translation_key="extractor_fan_level",
        state_class=SensorStateClass.MEASUREMENT,
        exists_fn=_has_extractor,
        value_fn=lambda c: c.extractor.fan_level if c.extractor else None,
    ),
    BoraOneSensorDescription(
        key="after_run_end",
        translation_key="after_run_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        remaining_time=True,
        exists_fn=_has_extractor,
        value_fn=lambda c: c.extractor.after_run_remaining if c.extractor else None,
    ),
    BoraOneSensorDescription(
        key="after_run_duration",
        translation_key="after_run_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=_has_extractor,
        value_fn=lambda c: c.extractor.after_run_duration if c.extractor else None,
    ),
    BoraOneSensorDescription(
        key="filter_lifetime",
        translation_key="filter_lifetime",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        exists_fn=_has_extractor,
        value_fn=lambda c: c.extractor.filter_lifetime_raw if c.extractor else None,
    ),
)

ZONE_SENSORS: tuple[BoraOneZoneSensorDescription, ...] = (
    BoraOneZoneSensorDescription(
        key="state",
        device_class=SensorDeviceClass.ENUM,
        options=[s.value for s in ZoneState],
        value_fn=lambda z: z.state.value,
    ),
    BoraOneZoneSensorDescription(
        key="power_level",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda z: z.power_level,
    ),
    BoraOneZoneSensorDescription(
        key="timer_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        remaining_time=True,
        value_fn=lambda z: z.timer_remaining,
    ),
    BoraOneZoneSensorDescription(
        key="keep_warm_mode",
        device_class=SensorDeviceClass.ENUM,
        options=["none", *(m.value for m in KeepWarmMode)],
        value_fn=lambda z: z.keep_warm_mode.value if z.keep_warm_mode else "none",
    ),
    BoraOneZoneSensorDescription(
        key="assist_program",
        device_class=SensorDeviceClass.ENUM,
        options=[p.value for p in AssistProgram],
        value_fn=lambda z: z.assist_program.value,
    ),
    BoraOneZoneSensorDescription(
        key="assist_phase",
        device_class=SensorDeviceClass.ENUM,
        options=[p.value for p in AssistPhase],
        value_fn=lambda z: z.assist_phase.value,
    ),
    BoraOneZoneSensorDescription(
        key="assist_target_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda z: z.assist_target_temperature,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BoraOneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        BoraOneSensor(coordinator, description)
        for description in COOKTOP_SENSORS
        if description.exists_fn(coordinator)
    ]
    entities.extend(
        BoraOneZoneSensor(coordinator, position, description)
        for position in coordinator.positions
        for description in ZONE_SENSORS
    )
    async_add_entities(entities)


class _EndTimeSensor(SensorEntity):
    """Keeps a stable end timestamp for remaining-time sensors."""

    _end: datetime | None = None

    def _value(self, raw: Any, remaining_time: bool) -> Any:
        if not remaining_time:
            return raw
        self._end = end_time(raw, self._end)
        return self._end


class BoraOneSensor(BoraOneEntity, _EndTimeSensor):
    """A cooktop-level sensor."""

    entity_description: BoraOneSensorDescription

    def __init__(
        self, coordinator: BoraOneCoordinator, description: BoraOneSensorDescription
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._update_value()

    def _update_value(self) -> None:
        self._attr_native_value = self._value(
            self.entity_description.value_fn(self.cooktop),
            self.entity_description.remaining_time,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_value()
        super()._handle_coordinator_update()


class BoraOneZoneSensor(BoraOneZoneEntity, _EndTimeSensor):
    """A cooking zone sensor."""

    entity_description: BoraOneZoneSensorDescription

    def __init__(
        self,
        coordinator: BoraOneCoordinator,
        position: ZonePosition,
        description: BoraOneZoneSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, position, description.key)
        self.entity_description = description
        self._attr_translation_key = f"{position.value}_{description.key}"
        self._update_value()

    def _update_value(self) -> None:
        zone = self.zone
        raw = self.entity_description.value_fn(zone) if zone else None
        self._attr_native_value = self._value(raw, self.entity_description.remaining_time)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_value()
        super()._handle_coordinator_update()
