"""Switches of the BORA One integration.

"Allow Bluetooth connection" holds or releases the Bluetooth connection: the
appliance accepts one client at a time, turning it off lets the BORA One app
connect. "Stop before end signal" (ovens) stops a programme shortly before
its end so the oven does not ring.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF, STATE_ON, EntityCategory
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
    coordinator = entry.runtime_data
    if coordinator.demo:
        return
    entities: list[SwitchEntity] = [BoraOneConnectionSwitch(coordinator)]
    if coordinator.is_oven:
        entities.append(BoraOneStopBeforeEndSwitch(coordinator))
    async_add_entities(entities)


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


class BoraOneStopBeforeEndSwitch(BoraOneEntity, SwitchEntity, RestoreEntity):
    """Stop a running oven programme just before it ends.

    The oven rings at the end of a programme until its screen is touched; a
    programme stopped shortly before its end finishes without that signal.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "stop_before_end_signal"

    def __init__(self, coordinator: BoraOneCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "stop_before_end_signal")

    async def async_added_to_hass(self) -> None:
        """Restore the previous choice."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) and last.state == STATE_ON:
            self.coordinator.stop_before_end_signal = True

    @property
    def is_on(self) -> bool:
        """Return True when programmes are stopped before their end."""
        return self.coordinator.stop_before_end_signal

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Stop programmes shortly before their end."""
        self.coordinator.stop_before_end_signal = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Let programmes run to their end (and ring)."""
        self.coordinator.stop_before_end_signal = False
        self.async_write_ha_state()
