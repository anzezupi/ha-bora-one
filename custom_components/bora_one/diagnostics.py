"""Diagnostics for BORA One."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from .coordinator import BoraOneConfigEntry

TO_REDACT = {
    CONF_ADDRESS,
    "appliance_id",
    "serial_number",
    "cm_serial_number",
    "cm_identifier",
    "fd",
    "e_nr",
    "ssid",
    "mac_address",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BoraOneConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    connection = coordinator.device.connection if coordinator.device else None
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "connection_enabled": coordinator.connection_enabled,
        "connected": bool(connection and connection.connected),
        "bond_state": connection.bond_state if connection else None,
        "last_protocol_error": connection.last_protocol_error if connection else None,
        "last_rpc_error": connection.last_rpc_error if connection else None,
        "cooktop": async_redact_data(asdict(coordinator.data), TO_REDACT),
    }
