"""Connect through Home Assistant's shared Bluetooth stack (local adapters and proxies).

Adapted from ha-bora (MIT), see THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import time

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .ble.transport import BrpcConnection, ConnectionLost


RECONNECT_COOLDOWN = 3.0
"""Seconds between the end of a link and the next connection to the same device.

An ESPHome proxy reported a new connection open 7 ms after it was requested,
while the previous link to the same device was still being torn down; the new
link then rode on the dying one and the stack lost the device's bond record.
"""

_link_ended: dict[str, float] = {}


def _mark_link_ended(address: str) -> None:
    _link_ended[address.upper()] = time.monotonic()


async def _wait_cooldown(address: str) -> None:
    ended = _link_ended.get(address.upper())
    if ended is not None:
        remaining = RECONNECT_COOLDOWN - (time.monotonic() - ended)
        if remaining > 0:
            await asyncio.sleep(remaining)


def create_connection(
    hass: HomeAssistant, address: str, *, disconnected: Callable[[], None] | None = None
) -> BrpcConnection:
    """Return a BRPC connection that resolves a fresh BLE device on every connect."""

    async def connect(callback):
        await _wait_cooldown(address)

        def on_disconnect(client):
            _mark_link_ended(address)
            callback(client)

        device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
        if device is None:
            raise ConnectionLost("BORA is not in range of a connectable Bluetooth adapter")
        return await establish_connection(
            BleakClientWithServiceCache,
            device,
            "BORA",
            disconnected_callback=on_disconnect,
            ble_device_callback=lambda: bluetooth.async_ble_device_from_address(
                hass, address, connectable=True
            ),
            max_attempts=2,
            timeout=20,
            # Pairing can change the GATT table; always discover services.
            use_services_cache=False,
        )

    return BrpcConnection(connect, disconnected=disconnected)
