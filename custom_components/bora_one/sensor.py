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
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import BoraOneConfigEntry, BoraOneCoordinator
from .entity import BoraOneEntity, BoraOneZoneEntity, end_time
from .models import (
    AssistPhase,
    AssistProgram,
    Cooktop,
    CookingZone,
    ExtractorMode,
    KeepWarmMode,
    OvenProgram,
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
    if cooktop.switched_off and not (cooktop.extractor and cooktop.extractor.is_running):
        return "off"
    return "standby"


@dataclass(frozen=True, kw_only=True)
class BoraOneSensorDescription(SensorEntityDescription):
    """Describes a cooktop-level sensor."""

    value_fn: Callable[[Cooktop], Any]
    exists_fn: Callable[[BoraOneCoordinator], bool] = lambda _: True
    remaining_time: bool = False
    """value_fn returns seconds remaining; expose as end timestamp."""
    clock_text: bool = False
    """With remaining_time: show the end as local HH:MM text, a dash when there is none."""


@dataclass(frozen=True, kw_only=True)
class BoraOneZoneSensorDescription(SensorEntityDescription):
    """Describes a cooking zone sensor."""

    value_fn: Callable[[CookingZone], Any]
    remaining_time: bool = False


# Shown by text sensors whose value does not apply right now (no programme,
# no timer), so they do not read "unknown" as if a reading were missing.
NOT_ACTIVE = "—"
NO_COUNTDOWN = "--:--"


def _text(attribute: str) -> Callable[[Cooktop], Any]:
    def value(cooktop: Cooktop) -> Any:
        if cooktop.oven is None:
            return None
        return getattr(cooktop.oven, attribute) or NOT_ACTIVE

    return value


def _countdown(seconds: int | None) -> str | None:
    """Format a remaining time as mm:ss (h:mm:ss from one hour)."""
    if seconds is None:
        return NO_COUNTDOWN
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _has_extractor(coordinator: BoraOneCoordinator) -> bool:
    return coordinator.has_extractor


def _is_cooktop(coordinator: BoraOneCoordinator) -> bool:
    return not coordinator.is_oven


def _is_oven(coordinator: BoraOneCoordinator) -> bool:
    return coordinator.is_oven


def _oven(attr: str) -> Callable[[Cooktop], Any]:
    """Return a value function reading one Oven attribute."""
    return lambda c: getattr(c.oven, attr) if c.oven else None


def _oven_or_zero(attr: str) -> Callable[[Cooktop], Any]:
    """Like _oven, but 0 instead of unknown when the value does not apply right now."""

    def value(cooktop: Cooktop) -> Any:
        if cooktop.oven is None or not cooktop.online:
            return None
        reading = getattr(cooktop.oven, attr)
        return 0 if reading is None else reading

    return value


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
        exists_fn=_is_cooktop,
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
    # Oven (X BO)
    BoraOneSensorDescription(
        key="oven_program",
        translation_key="oven_program",
        device_class=SensorDeviceClass.ENUM,
        options=[p.value for p in OvenProgram],
        exists_fn=_is_oven,
        value_fn=lambda c: c.oven.program.value if c.oven else None,
    ),
    BoraOneSensorDescription(
        key="oven_program_name",
        translation_key="oven_program_name",
        exists_fn=_is_oven,
        value_fn=_text("program_name"),
    ),
    BoraOneSensorDescription(
        key="oven_cooking_step",
        translation_key="oven_cooking_step",
        exists_fn=_is_oven,
        value_fn=_text("cooking_step"),
    ),
    BoraOneSensorDescription(
        key="oven_temperature",
        translation_key="oven_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        exists_fn=_is_oven,
        value_fn=_oven("current_temperature"),
    ),
    BoraOneSensorDescription(
        key="oven_target_temperature",
        translation_key="oven_target_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        exists_fn=_is_oven,
        value_fn=_oven_or_zero("target_temperature"),
    ),
    BoraOneSensorDescription(
        key="oven_humidity",
        translation_key="oven_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        exists_fn=_is_oven,
        value_fn=_oven_or_zero("current_humidity"),
    ),
    BoraOneSensorDescription(
        key="oven_target_humidity",
        translation_key="oven_target_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        exists_fn=_is_oven,
        value_fn=_oven_or_zero("target_humidity"),
    ),
    BoraOneSensorDescription(
        key="core_temperature",
        translation_key="core_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        exists_fn=_is_oven,
        value_fn=_oven_or_zero("core_temperature"),
    ),
    BoraOneSensorDescription(
        key="target_core_temperature",
        translation_key="target_core_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        exists_fn=_is_oven,
        value_fn=_oven_or_zero("target_core_temperature"),
    ),
    BoraOneSensorDescription(
        key="step_end",
        translation_key="step_end",
        remaining_time=True,
        clock_text=True,
        exists_fn=_is_oven,
        value_fn=_oven("step_remaining"),
    ),
    BoraOneSensorDescription(
        key="program_end",
        translation_key="program_end",
        remaining_time=True,
        clock_text=True,
        exists_fn=_is_oven,
        value_fn=_oven("program_remaining"),
    ),
    BoraOneSensorDescription(
        key="step_remaining",
        translation_key="step_remaining",
        exists_fn=_is_oven,
        value_fn=lambda c: _countdown(c.oven.step_remaining) if c.oven else None,
    ),
    BoraOneSensorDescription(
        key="program_remaining",
        translation_key="program_remaining",
        exists_fn=_is_oven,
        value_fn=lambda c: _countdown(c.oven.program_remaining) if c.oven else None,
    ),
    BoraOneSensorDescription(
        key="egg_timer_remaining",
        translation_key="egg_timer_remaining",
        exists_fn=_is_oven,
        value_fn=lambda c: _countdown(c.oven.egg_timer_remaining) if c.oven else None,
    ),
    BoraOneSensorDescription(
        key="egg_timer_end",
        translation_key="egg_timer_end",
        remaining_time=True,
        clock_text=True,
        exists_fn=_is_oven,
        value_fn=_oven("egg_timer_remaining"),
    ),
    BoraOneSensorDescription(
        key="program_progress",
        translation_key="program_progress",
        native_unit_of_measurement=PERCENTAGE,
        exists_fn=_is_oven,
        value_fn=_oven_or_zero("program_progress"),
    ),
    BoraOneSensorDescription(
        key="operating_hours",
        translation_key="operating_hours",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=_is_oven,
        value_fn=_oven("operating_hours"),
    ),
    BoraOneSensorDescription(
        key="oven_filter_lifetime",
        translation_key="filter_lifetime",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        exists_fn=_is_oven,
        value_fn=_oven("filter_lifetime_raw"),
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
    if coordinator.is_oven and not coordinator.demo:
        entities.append(BoraOneProgrammeResultSensor(coordinator))
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
        raw = self.entity_description.value_fn(self.cooktop)
        if self.entity_description.clock_text:
            self._end = end_time(raw, self._end)
            if self._end is not None:
                self._attr_native_value = dt_util.as_local(self._end).strftime("%H:%M")
            elif self.cooktop.oven is not None and self.cooktop.online:
                self._attr_native_value = NOT_ACTIVE
            else:
                self._attr_native_value = None
            return
        self._attr_native_value = self._value(raw, self.entity_description.remaining_time)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_value()
        super()._handle_coordinator_update()


class BoraOneProgrammeResultSensor(BoraOneEntity, SensorEntity):
    """Running, or how the last programme ended (finished / stopped).

    Stays on finished or stopped until the next programme starts or the oven
    switches off, so a dashboard shows what happened.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["idle", "running", "finished", "stopped"]
    _attr_translation_key = "programme_result"

    def __init__(self, coordinator: BoraOneCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "programme_result")

    @property
    def native_value(self) -> str | None:
        """Return the programme result."""
        oven = self.cooktop.oven
        if oven is None or not self.cooktop.online:
            return None
        if oven.is_running:
            return "running"
        return self.coordinator.programme_result


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
