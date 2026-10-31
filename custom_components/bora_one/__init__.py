"""The BORA One integration (local Bluetooth)."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
import voluptuous as vol

from .const import CONF_MODE, DOMAIN, MODE_DEMO
from .coordinator import BoraOneConfigEntry, BoraOneCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
]


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
    _register_services(hass)
    return True


EXPERIMENT_COMMANDS = ("start_device", "start_preset", "start_favorite")


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, "oven_experiment"):
        return

    async def oven_experiment(call: ServiceCall) -> None:
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            coordinator: BoraOneCoordinator = entry.runtime_data
            if coordinator.is_oven and not coordinator.demo:
                await coordinator.async_oven_experiment(call.data["command"])
                return
        raise HomeAssistantError("No connected BORA oven")

    hass.services.async_register(
        DOMAIN,
        "oven_experiment",
        oven_experiment,
        schema=vol.Schema({vol.Required("command"): vol.In(EXPERIMENT_COMMANDS)}),
    )


async def async_unload_entry(hass: HomeAssistant, entry: BoraOneConfigEntry) -> bool:
    """Unload a config entry."""
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_shutdown()
    return unloaded
