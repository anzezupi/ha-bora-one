"""Connect through Home Assistant's shared Bluetooth stack (local adapters and proxies).

Adapted from ha-bora (MIT), see THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

from collections.abc import Callable

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .ble.transport import BrpcConnection, ConnectionLost


def create_connection(
    hass: HomeAssistant, address: str, *, disconnected: Callable[[], None] | None = None
) -> BrpcConnection:
    """Return a BRPC connection that resolves a fresh BLE device on every connect."""

    async def connect(callback):
        device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
        if device is None:
            raise ConnectionLost("BORA is not in range of a connectable Bluetooth adapter")
        return await establish_connection(
            BleakClientWithServiceCache,
            device,
            "BORA",
            disconnected_callback=callback,
            ble_device_callback=lambda: bluetooth.async_ble_device_from_address(
                hass, address, connectable=True
            ),
            max_attempts=2,
            timeout=20,
        )

    return BrpcConnection(connect, disconnected=disconnected)
