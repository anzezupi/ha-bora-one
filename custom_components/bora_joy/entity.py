"""Base entities for BORA JOY."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MANUFACTURER
from .coordinator import BoraJoyCoordinator
from .models import Cooktop, CookingZone, ZonePosition

# Remaining times are turned into end timestamps. Small drifts between polls are
# ignored so the state does not change on every update.
END_TIME_TOLERANCE = timedelta(seconds=10)


class BoraJoyEntity(CoordinatorEntity[BoraJoyCoordinator]):
    """An entity belonging to a BORA cooktop."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BoraJoyCoordinator, appliance_id: str, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._appliance_id = appliance_id
        self._attr_unique_id = f"{appliance_id}_{key}"
        cooktop = coordinator.data[appliance_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, appliance_id)},
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
        return self.coordinator.data[self._appliance_id]

    @property
    def available(self) -> bool:
        """Return True when the cooktop is reachable."""
        return (
            super().available
            and self._appliance_id in self.coordinator.data
            and self.cooktop.online
        )


class BoraJoyZoneEntity(BoraJoyEntity):
    """An entity belonging to one cooking zone."""

    def __init__(
        self,
        coordinator: BoraJoyCoordinator,
        appliance_id: str,
        position: ZonePosition,
        key: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, appliance_id, f"{position.value}_{key}")
        self._position = position

    @property
    def zone(self) -> CookingZone | None:
        """Return the current zone state."""
        return self.cooktop.zones.get(self._position)

    @property
    def available(self) -> bool:
        """Return True when the zone is reported."""
        return super().available and self.zone is not None


def end_time(remaining: int | None, previous: datetime | None) -> datetime | None:
    """Convert seconds remaining into a stable end timestamp."""
    if remaining is None:
        return None
    new = dt_util.utcnow() + timedelta(seconds=remaining)
    if previous is not None and abs(new - previous) < END_TIME_TOLERANCE:
        return previous
    return new.replace(microsecond=0)
