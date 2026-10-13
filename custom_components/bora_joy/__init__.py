"""The BORA JOY integration."""

from __future__ import annotations

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BoraJoyClient, BoraJoyCloudClient, BoraJoyDemoClient
from .const import CONF_MODE, MODE_DEMO
from .coordinator import BoraJoyConfigEntry, BoraJoyCoordinator

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: BoraJoyConfigEntry) -> bool:
    """Set up BORA JOY from a config entry."""
    client: BoraJoyClient
    if entry.data[CONF_MODE] == MODE_DEMO:
        client = BoraJoyDemoClient()
    else:
        client = BoraJoyCloudClient(
            async_get_clientsession(hass),
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
        )

    coordinator = BoraJoyCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BoraJoyConfigEntry) -> bool:
    """Unload a config entry."""
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.client.async_close()
    return unloaded

