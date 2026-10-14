"""Binary sensors for BORA One."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BoraOneConfigEntry, BoraOneCoordinator
from .entity import BoraOneEntity, BoraOneZoneEntity
from .models import AssistPhase, Cooktop, CookingZone, ZonePosition

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class BoraOneBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a cooktop-level binary sensor."""

    value_fn: Callable[[Cooktop], bool | None]
    exists_fn: Callable[[BoraOneCoordinator], bool] = lambda _: True


@dataclass(frozen=True, kw_only=True)
class BoraOneZoneBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a cooking zone binary sensor."""

    value_fn: Callable[[CookingZone], bool | None]


def _has_extractor(coordinator: BoraOneCoordinator) -> bool:
    return coordinator.has_extractor


COOKTOP_BINARY_SENSORS: tuple[BoraOneBinarySensorDescription, ...] = (
    BoraOneBinarySensorDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.online,
    ),
    BoraOneBinarySensorDescription(
        key="cooking",
        translation_key="cooking",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda c: c.is_cooking,
    ),
    BoraOneBinarySensorDescription(
        key="residual_heat",
        translation_key="residual_heat",
        device_class=BinarySensorDeviceClass.HEAT,
        value_fn=lambda c: c.has_residual_heat,
    ),
    BoraOneBinarySensorDescription(
        key="paused",
        translation_key="paused",
        value_fn=lambda c: c.paused,
    ),
    BoraOneBinarySensorDescription(
        key="child_lock",
        translation_key="child_lock",
        value_fn=lambda c: c.child_lock,
    ),
    BoraOneBinarySensorDescription(
        key="cleaning_lock",
        translation_key="cleaning_lock",
        value_fn=lambda c: c.cleaning_lock,
    ),
    BoraOneBinarySensorDescription(
        key="problem",
        translation_key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: bool(c.errors),
    ),
    BoraOneBinarySensorDescription(
        key="extractor_running",
        translation_key="extractor_running",
        device_class=BinarySensorDeviceClass.RUNNING,
        exists_fn=_has_extractor,
        value_fn=lambda c: c.extractor.is_running if c.extractor else None,
    ),
    BoraOneBinarySensorDescription(
        key="filter_service",
        translation_key="filter_service",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=_has_extractor,
        value_fn=lambda c: c.extractor.filter_service_required if c.extractor else None,
    ),
)

ZONE_BINARY_SENSORS: tuple[BoraOneZoneBinarySensorDescription, ...] = (
    BoraOneZoneBinarySensorDescription(
        key="active",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda z: z.is_active,
    ),
    BoraOneZoneBinarySensorDescription(
        key="residual_heat",
        device_class=BinarySensorDeviceClass.HEAT,
        value_fn=lambda z: z.residual_heat,
    ),
    BoraOneZoneBinarySensorDescription(
        key="assist_confirmation",
        value_fn=lambda z: z.assist_phase is AssistPhase.CONFIRMATION_REQUIRED,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BoraOneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        BoraOneBinarySensor(coordinator, description)
        for description in COOKTOP_BINARY_SENSORS
        if description.exists_fn(coordinator)
    ]
    entities.extend(
        BoraOneZoneBinarySensor(coordinator, position, description)
        for position in coordinator.positions
        for description in ZONE_BINARY_SENSORS
    )
    async_add_entities(entities)


class BoraOneBinarySensor(BoraOneEntity, BinarySensorEntity):
    """A cooktop-level binary sensor."""

    entity_description: BoraOneBinarySensorDescription

    def __init__(
        self, coordinator: BoraOneCoordinator, description: BoraOneBinarySensorDescription
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        return self.entity_description.value_fn(self.cooktop)


class BoraOneZoneBinarySensor(BoraOneZoneEntity, BinarySensorEntity):
    """A cooking zone binary sensor."""

    entity_description: BoraOneZoneBinarySensorDescription

    def __init__(
        self,
        coordinator: BoraOneCoordinator,
        position: ZonePosition,
        description: BoraOneZoneBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, position, description.key)
        self.entity_description = description
        self._attr_translation_key = f"{position.value}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        zone = self.zone
        return self.entity_description.value_fn(zone) if zone else None
