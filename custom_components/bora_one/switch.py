"""Switch that lets Home Assistant hold or release the Bluetooth connection.

The cooktop accepts one Bluetooth client at a time. Turning this off lets the
BORA One app on a phone connect. It never sends anything to the cooktop.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import BoraOneConfigEntry, BoraOneCoordinator
from .entity import BoraOneEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BoraOneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the connection switch."""
    if not entry.runtime_data.demo:
        async_add_entities([BoraOneConnectionSwitch(entry.runtime_data)])


class BoraOneConnectionSwitch(BoraOneEntity, SwitchEntity, RestoreEntity):
    """Allow Home Assistant to connect to the cooktop."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "bluetooth_connection"

    def __init__(self, coordinator: BoraOneCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "bluetooth_connection")

    async def async_added_to_hass(self) -> None:
        """Restore the previous choice."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) and last.state == STATE_OFF:
            await self.coordinator.async_set_connection_enabled(False)

    @property
    def is_on(self) -> bool:
        """Return True when Home Assistant may connect."""
        return self.coordinator.connection_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Let Home Assistant connect."""
        await self.coordinator.async_set_connection_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Release the connection so the phone app can connect."""
        await self.coordinator.async_set_connection_enabled(False)
