"""Base entities for BORA One."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.const import CONF_ADDRESS
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MANUFACTURER
from .coordinator import BoraOneCoordinator
from .models import Cooktop, CookingZone, ZonePosition

# Remaining times become end timestamps. Small drifts between updates are
# ignored so the state does not change on every update.
END_TIME_TOLERANCE = timedelta(seconds=10)


class BoraOneEntity(CoordinatorEntity[BoraOneCoordinator]):
    """An entity of a BORA cooktop."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BoraOneCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        cooktop = coordinator.data
        self._attr_unique_id = f"{cooktop.appliance_id}_{key}"
        address = coordinator.config_entry.data.get(CONF_ADDRESS)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, cooktop.appliance_id)},
            connections={(CONNECTION_BLUETOOTH, address)} if address else set(),
            manufacturer=MANUFACTURER,
            name=cooktop.name,
            model=cooktop.model,
            serial_number=cooktop.serial_number,
            sw_version=cooktop.software_version,
            hw_version=cooktop.hardware_version,
        )

    @property
    def cooktop(self) -> Cooktop:
        """Return the current cooktop state."""
        return self.coordinator.data


class BoraOneZoneEntity(BoraOneEntity):
    """An entity of one cooking zone."""

    def __init__(
        self, coordinator: BoraOneCoordinator, position: ZonePosition, key: str
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, f"{position.value}_{key}")
        self._position = position

    @property
    def zone(self) -> CookingZone | None:
        """Return the current zone state."""
        return self.cooktop.zones.get(self._position)

    @property
    def available(self) -> bool:
        """Unavailable while the cooktop reports this zone as unknown."""
        return super().available and self.zone is not None


def end_time(remaining: int | None, previous: datetime | None) -> datetime | None:
    """Convert seconds remaining into a stable end timestamp."""
    if remaining is None:
        return None
    new = dt_util.utcnow() + timedelta(seconds=remaining)
    if previous is not None and abs(new - previous) < END_TIME_TOLERANCE:
        return previous
    return new.replace(microsecond=0)
