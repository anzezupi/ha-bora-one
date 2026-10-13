"""Binary sensors for BORA JOY."""

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

from .coordinator import BoraJoyConfigEntry, BoraJoyCoordinator
from .entity import BoraJoyEntity, BoraJoyZoneEntity
from .models import Cooktop, CookingZone, ZonePosition

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class BoraJoyBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a cooktop-level binary sensor."""

    value_fn: Callable[[Cooktop], bool | None]
    exists_fn: Callable[[Cooktop], bool] = lambda _: True


@dataclass(frozen=True, kw_only=True)
class BoraJoyZoneBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a cooking zone binary sensor."""

    value_fn: Callable[[CookingZone], bool | None]


COOKTOP_BINARY_SENSORS: tuple[BoraJoyBinarySensorDescription, ...] = (
    BoraJoyBinarySensorDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.online,
    ),
    BoraJoyBinarySensorDescription(
        key="power",
        translation_key="power",
        device_class=BinarySensorDeviceClass.POWER,
        value_fn=lambda c: c.powered_on,
    ),
    BoraJoyBinarySensorDescription(
        key="cooking",
        translation_key="cooking",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda c: c.is_cooking,
    ),
    BoraJoyBinarySensorDescription(
        key="paused",
        translation_key="paused",
        value_fn=lambda c: c.paused,
    ),
    BoraJoyBinarySensorDescription(
        key="child_lock",
        translation_key="child_lock",
        value_fn=lambda c: c.child_lock,
    ),
    BoraJoyBinarySensorDescription(
        key="cleaning_lock",
        translation_key="cleaning_lock",
        value_fn=lambda c: c.cleaning_lock,
    ),
    BoraJoyBinarySensorDescription(
        key="extractor_running",
        translation_key="extractor_running",
        device_class=BinarySensorDeviceClass.RUNNING,
        exists_fn=lambda c: c.extractor is not None,
        value_fn=lambda c: c.extractor.is_running if c.extractor else None,
    ),
    BoraJoyBinarySensorDescription(
        key="filter_service",
        translation_key="filter_service",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda c: (
            c.extractor is not None and c.extractor.filter_service_required is not None
        ),
        value_fn=lambda c: c.extractor.filter_service_required if c.extractor else None,
    ),
    BoraJoyBinarySensorDescription(
        key="residual_heat",
        translation_key="residual_heat",
        device_class=BinarySensorDeviceClass.HEAT,
        value_fn=lambda c: any(z.residual_heat for z in c.zones.values()),
    ),
)

ZONE_BINARY_SENSORS: tuple[BoraJoyZoneBinarySensorDescription, ...] = (
    BoraJoyZoneBinarySensorDescription(
        key="active",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda z: z.is_active,
    ),
    BoraJoyZoneBinarySensorDescription(
        key="residual_heat",
        device_class=BinarySensorDeviceClass.HEAT,
        value_fn=lambda z: z.residual_heat,
    ),
    BoraJoyZoneBinarySensorDescription(
        key="pan_detected",
        device_class=BinarySensorDeviceClass.OCCUPANCY,
        value_fn=lambda z: z.pan_detected,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BoraJoyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = []
    for appliance_id, cooktop in coordinator.data.items():
        entities.extend(
            BoraJoyBinarySensor(coordinator, appliance_id, description)
            for description in COOKTOP_BINARY_SENSORS
            if description.exists_fn(cooktop)
        )
        entities.extend(
            BoraJoyZoneBinarySensor(coordinator, appliance_id, position, description)
            for position in cooktop.zones
            for description in ZONE_BINARY_SENSORS
        )
    async_add_entities(entities)


class BoraJoyBinarySensor(BoraJoyEntity, BinarySensorEntity):
    """A cooktop-level binary sensor."""

    entity_description: BoraJoyBinarySensorDescription

    def __init__(
        self,
        coordinator: BoraJoyCoordinator,
        appliance_id: str,
        description: BoraJoyBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, appliance_id, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """The connectivity sensor stays available to report "offline"."""
        if self.entity_description.key == "online":
            return self.coordinator.last_update_success and (
                self._appliance_id in self.coordinator.data
            )
        return super().available

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        return self.entity_description.value_fn(self.cooktop)


class BoraJoyZoneBinarySensor(BoraJoyZoneEntity, BinarySensorEntity):
    """A cooking zone binary sensor."""

    entity_description: BoraJoyZoneBinarySensorDescription

    def __init__(
        self,
        coordinator: BoraJoyCoordinator,
        appliance_id: str,
        position: ZonePosition,
        description: BoraJoyZoneBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, appliance_id, position, description.key)
        self.entity_description = description
        self._attr_translation_key = f"{position.value}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        zone = self.zone
        return self.entity_description.value_fn(zone) if zone else None
