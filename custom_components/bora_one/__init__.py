"""The BORA One integration (local Bluetooth)."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, callback

from .const import CONF_MODE, MODE_DEMO
from .coordinator import BoraOneConfigEntry, BoraOneCoordinator

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: BoraOneConfigEntry) -> bool:
    """Set up BORA One from a config entry."""
    coordinator = BoraOneCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    if entry.data[CONF_MODE] != MODE_DEMO:

        @callback
        def _on_advertisement(
            _info: bluetooth.BluetoothServiceInfoBleak, _change: bluetooth.BluetoothChange
        ) -> None:
            coordinator.async_on_advertisement()

        entry.async_on_unload(
            bluetooth.async_register_callback(
                hass,
                _on_advertisement,
                {"address": entry.data[CONF_ADDRESS], "connectable": True},
                bluetooth.BluetoothScanningMode.PASSIVE,
            )
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BoraOneConfigEntry) -> bool:
    """Unload a config entry."""
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_shutdown()
    return unloaded
