"""Fixtures for BORA One tests."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from homeassistant import setup

from custom_components.bora_one.const import DOMAIN, SERVICE_UUID

from .bora_peer import FakeBoraPeer

ADDRESS = "AA:BB:CC:DD:EE:FF"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations."""


@pytest.fixture
def peer() -> FakeBoraPeer:
    """A simulated cooktop."""
    return FakeBoraPeer()


class FakeBluetooth:
    """Stands in for Home Assistant's Bluetooth manager."""

    def __init__(self, peer: FakeBoraPeer) -> None:
        self.peer = peer
        self.advertisement_callbacks: list = []

    def advertise(self) -> None:
        """Deliver an advertisement from the cooktop."""
        self.peer.advertising = True
        for callback in self.advertisement_callbacks:
            callback(None, None)


@pytest.fixture
def bluetooth(peer: FakeBoraPeer) -> Generator[FakeBluetooth]:
    """Replace the physical Bluetooth layer with the simulated cooktop."""
    fake = FakeBluetooth(peer)
    original_deps = setup.async_process_deps_reqs

    async def process_deps(hass, config, integration):
        # Skip only our own dependency on real Bluetooth adapters.
        if integration.domain == DOMAIN:
            return None
        return await original_deps(hass, config, integration)

    def register_callback(hass, callback, matcher, mode):
        fake.advertisement_callbacks.append(callback)
        return lambda: fake.advertisement_callbacks.remove(callback)

    def connection(hass, address, disconnected=None):
        assert address == ADDRESS
        return peer.connection(disconnected)

    @asynccontextmanager
    async def no_agent():
        yield

    service_info = SimpleNamespace(address=ADDRESS, name="X PURE", service_uuids=[SERVICE_UUID])
    with (
        patch("homeassistant.setup.async_process_deps_reqs", side_effect=process_deps),
        patch("custom_components.bora_one.coordinator.create_connection", side_effect=connection),
        patch("custom_components.bora_one.config_flow.create_connection", side_effect=connection),
        patch("custom_components.bora_one.config_flow.pairing_agent", no_agent),
        patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            side_effect=lambda hass, address, connectable=True: object() if peer.advertising else None,
        ),
        patch(
            "homeassistant.components.bluetooth.async_register_callback",
            side_effect=register_callback,
        ),
        patch(
            "homeassistant.components.bluetooth.async_discovered_service_info",
            side_effect=lambda hass, connectable=True: [service_info] if peer.advertising else [],
        ),
    ):
        yield fake
