"""Diagnostics for BORA JOY.

The raw payloads are the main tool for mapping the (undocumented) cloud API,
so they are included in full apart from credentials and identifiers.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import BoraJoyConfigEntry

TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    "serial_number",
    "serialNumber",
    "email",
    "token",
    "access_token",
    "refresh_token",
    "mac",
    "macAddress",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BoraJoyConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "cooktops": {
            appliance_id: async_redact_data(asdict(cooktop), TO_REDACT)
            for appliance_id, cooktop in (coordinator.data or {}).items()
        },
    }
