"""Event entity for the end of an oven programme.

Fires "finished" when a programme ran to its end (also when "Stop before end
signal" stopped it just before) and "stopped" when it was cancelled. With the
oven's own end signal skipped, this is what automations react to.
"""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BoraOneConfigEntry, BoraOneCoordinator
from .entity import BoraOneEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BoraOneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the event entity."""
    coordinator = entry.runtime_data
    if coordinator.is_oven and not coordinator.demo:
        async_add_entities([BoraOneProgrammeEndEvent(coordinator)])


class BoraOneProgrammeEndEvent(BoraOneEntity, EventEntity):
    """An oven programme ended."""

    _attr_translation_key = "programme_end"
    _attr_event_types = ["finished", "stopped"]

    def __init__(self, coordinator: BoraOneCoordinator) -> None:
        """Initialize the event entity."""
        super().__init__(coordinator, "programme_end")

    async def async_added_to_hass(self) -> None:
        """Listen for programme ends."""
        await super().async_added_to_hass()
        listeners = self.coordinator.programme_end_listeners
        listeners.append(self._ended)
        self.async_on_remove(lambda: listeners.remove(self._ended))

    @property
    def available(self) -> bool:
        """Keep the last event visible while the oven is off."""
        return True

    @callback
    def _ended(self, reason: str) -> None:
        self._trigger_event(reason)
        self.async_write_ha_state()
