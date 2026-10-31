"""Buttons that send a command to the appliance.

Only harmless commands are offered: stopping, never starting.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BoraOneConfigEntry, BoraOneCoordinator
from .entity import BoraOneEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BoraOneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons."""
    coordinator = entry.runtime_data
    if coordinator.is_oven and not coordinator.demo:
        async_add_entities([BoraOneStopProgramButton(coordinator)])


class BoraOneStopProgramButton(BoraOneEntity, ButtonEntity):
    """Stop the programme the oven is running."""

    _attr_translation_key = "stop_program"

    def __init__(self, coordinator: BoraOneCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, "stop_program")

    @property
    def available(self) -> bool:
        """Only while the oven is connected."""
        return super().available and self.cooktop.online

    async def async_press(self) -> None:
        """Send the stop command."""
        await self.coordinator.async_stop_oven_program()
