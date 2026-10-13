"""Sensors for BORA JOY."""

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
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BoraJoyConfigEntry, BoraJoyCoordinator
from .entity import BoraJoyEntity, BoraJoyZoneEntity, end_time
from .models import (
    AssistProgram,
    Cooktop,
    CookingZone,
    ExtractorMode,
    ZonePosition,
    ZoneState,
)

PARALLEL_UPDATES = 0

COOKTOP_STATUSES = ["off", "standby", "cooking", "paused", "after_run", "offline"]


def _cooktop_status(cooktop: Cooktop) -> str:
    if not cooktop.online:
        return "offline"
    if cooktop.paused:
        return "paused"
    if cooktop.is_cooking:
        return "cooking"
    if cooktop.extractor and cooktop.extractor.mode is ExtractorMode.AFTER_RUN:
        return "after_run"
    if cooktop.powered_on:
        return "standby"
    return "off"


@dataclass(frozen=True, kw_only=True)
class BoraJoySensorDescription(SensorEntityDescription):
    """Describes a cooktop-level sensor."""

    value_fn: Callable[[Cooktop], Any]
    exists_fn: Callable[[Cooktop], bool] = lambda _: True
    remaining_time: bool = False
    """value_fn returns seconds remaining; expose as end timestamp."""


@dataclass(frozen=True, kw_only=True)
class BoraJoyZoneSensorDescription(SensorEntityDescription):
    """Describes a cooking zone sensor."""

    value_fn: Callable[[CookingZone], Any]
    remaining_time: bool = False


COOKTOP_SENSORS: tuple[BoraJoySensorDescription, ...] = (
    BoraJoySensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=COOKTOP_STATUSES,
        value_fn=_cooktop_status,
    ),
    BoraJoySensorDescription(
        key="active_zones",
        translation_key="active_zones",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.active_zone_count,
    ),
    BoraJoySensorDescription(
        key="short_timer_end",
        translation_key="short_timer_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        remaining_time=True,
        value_fn=lambda c: c.short_timer_remaining,
    ),
    BoraJoySensorDescription(
        key="extractor_mode",
        translation_key="extractor_mode",
        device_class=SensorDeviceClass.ENUM,
        options=[m.value for m in ExtractorMode],
        exists_fn=lambda c: c.extractor is not None,
        value_fn=lambda c: c.extractor.mode.value if c.extractor else None,
    ),
    BoraJoySensorDescription(
        key="extractor_fan_level",
        translation_key="extractor_fan_level",
        state_class=SensorStateClass.MEASUREMENT,
        exists_fn=lambda c: c.extractor is not None,
        value_fn=lambda c: c.extractor.fan_level if c.extractor else None,
    ),
    BoraJoySensorDescription(
        key="after_run_end",
        translation_key="after_run_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        remaining_time=True,
        exists_fn=lambda c: c.extractor is not None,
        value_fn=lambda c: c.extractor.after_run_remaining if c.extractor else None,
    ),
    BoraJoySensorDescription(
        key="filter_remaining",
        translation_key="filter_remaining",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda c: (
            c.extractor is not None and c.extractor.filter_remaining_percent is not None
        ),
        value_fn=lambda c: c.extractor.filter_remaining_percent if c.extractor else None,
    ),
)

ZONE_SENSORS: tuple[BoraJoyZoneSensorDescription, ...] = (
    BoraJoyZoneSensorDescription(
        key="state",
        device_class=SensorDeviceClass.ENUM,
        options=[s.value for s in ZoneState],
        value_fn=lambda z: z.state.value,
    ),
    BoraJoyZoneSensorDescription(
        key="power_level",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda z: z.power_level,
    ),
    BoraJoyZoneSensorDescription(
        key="timer_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        remaining_time=True,
        value_fn=lambda z: z.timer_remaining,
    ),
    BoraJoyZoneSensorDescription(
        key="assist_program",
        device_class=SensorDeviceClass.ENUM,
        options=[p.value for p in AssistProgram],
        value_fn=lambda z: z.assist_program.value,
    ),
    BoraJoyZoneSensorDescription(
        key="assist_target_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda z: z.assist_target_temperature,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BoraJoyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []
    for appliance_id, cooktop in coordinator.data.items():
        entities.extend(
            BoraJoySensor(coordinator, appliance_id, description)
            for description in COOKTOP_SENSORS
            if description.exists_fn(cooktop)
        )
        entities.extend(
            BoraJoyZoneSensor(coordinator, appliance_id, position, description)
            for position in cooktop.zones
            for description in ZONE_SENSORS
        )
    async_add_entities(entities)


class _EndTimeMixin(SensorEntity):
    """Keeps a stable end timestamp for remaining-time sensors."""

    _end: datetime | None = None

    def _value(self, raw: Any, remaining_time: bool) -> Any:
        if not remaining_time:
            return raw
        self._end = end_time(raw, self._end)
        return self._end


class BoraJoySensor(BoraJoyEntity, _EndTimeMixin):
    """A cooktop-level sensor."""

    entity_description: BoraJoySensorDescription

    def __init__(
        self,
        coordinator: BoraJoyCoordinator,
        appliance_id: str,
        description: BoraJoySensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, appliance_id, description.key)
        self.entity_description = description
        self._update_value()

    @property
    def available(self) -> bool:
        """The status sensor stays available to report "offline"."""
        if self.entity_description.key == "status":
            return self.coordinator.last_update_success and (
                self._appliance_id in self.coordinator.data
            )
        return super().available

    def _update_value(self) -> None:
        self._attr_native_value = self._value(
            self.entity_description.value_fn(self.cooktop),
            self.entity_description.remaining_time,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        if self._appliance_id in self.coordinator.data:
            self._update_value()
        super()._handle_coordinator_update()


class BoraJoyZoneSensor(BoraJoyZoneEntity, _EndTimeMixin):
    """A cooking zone sensor."""

    entity_description: BoraJoyZoneSensorDescription

    def __init__(
        self,
        coordinator: BoraJoyCoordinator,
        appliance_id: str,
        position: ZonePosition,
        description: BoraJoyZoneSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, appliance_id, position, description.key)
        self.entity_description = description
        self._attr_translation_key = f"{position.value}_{description.key}"
        self._update_value()

    def _update_value(self) -> None:
        zone = self.zone
        raw = self.entity_description.value_fn(zone) if zone else None
        self._attr_native_value = self._value(raw, self.entity_description.remaining_time)

    @callback
    def _handle_coordinator_update(self) -> None:
        if self._appliance_id in self.coordinator.data:
            self._update_value()
        super()._handle_coordinator_update()
