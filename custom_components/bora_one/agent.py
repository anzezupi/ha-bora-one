"""Temporary BlueZ pairing agent.

The cooktop asks for a pairing confirmation (like the "Pair" prompt on a
phone). Without an agent BlueZ cancels the pairing, so while the user pairs
from the config flow we register an agent that accepts the confirmation.
The user still has to approve pairing with the Connect button on the cooktop.

Annotations are D-Bus signatures read by dbus-fast, so this module must not
use ``from __future__ import annotations``.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
import logging

_LOGGER = logging.getLogger(__name__)

AGENT_PATH = "/io/home_assistant/bora_one/agent"
CAPABILITY = "DisplayYesNo"


def _agent_class():
    from dbus_fast import DBusError  # noqa: PLC0415
    from dbus_fast.service import ServiceInterface, method  # noqa: PLC0415

    def rejected(what: str) -> DBusError:
        _LOGGER.warning("BORA pairing asked for %s, which is not supported", what)
        return DBusError("org.bluez.Error.Rejected", f"{what} not supported")

    class PairingAgent(ServiceInterface):
        """org.bluez.Agent1 that accepts confirmation requests."""

        def __init__(self) -> None:
            super().__init__("org.bluez.Agent1")

        @method()
        def Release(self):  # noqa: N802
            _LOGGER.debug("BlueZ released the pairing agent")

        @method()
        def RequestPinCode(self, device: "o") -> "s":  # noqa: F821, N802
            raise rejected("a PIN code")

        @method()
        def DisplayPinCode(self, device: "o", pincode: "s"):  # noqa: F821, N802
            _LOGGER.info("BORA pairing PIN code: %s", pincode)

        @method()
        def RequestPasskey(self, device: "o") -> "u":  # noqa: F821, N802
            raise rejected("a passkey")

        @method()
        def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):  # noqa: F821, N802
            _LOGGER.info("BORA pairing passkey: %06d", passkey)

        @method()
        def RequestConfirmation(self, device: "o", passkey: "u"):  # noqa: F821, N802
            _LOGGER.info("Accepting BORA pairing confirmation (code %06d)", passkey)

        @method()
        def RequestAuthorization(self, device: "o"):  # noqa: F821, N802
            _LOGGER.info("Accepting BORA pairing authorization")

        @method()
        def AuthorizeService(self, device: "o", uuid: "s"):  # noqa: F821, N802
            _LOGGER.debug("Authorizing service %s", uuid)

        @method()
        def Cancel(self):  # noqa: N802
            _LOGGER.warning("BlueZ cancelled the BORA pairing request")

    return PairingAgent


@asynccontextmanager
async def pairing_agent() -> AsyncIterator[None]:
    """Register a default BlueZ agent while pairing; no-op where BlueZ is unavailable."""
    bus = manager = None
    try:
        from dbus_fast import BusType  # noqa: PLC0415
        from dbus_fast.aio import MessageBus  # noqa: PLC0415

        async with asyncio.timeout(5):
            bus = await MessageBus(bus_type=BusType.SYSTEM, negotiate_unix_fd=False).connect()
            bus.export(AGENT_PATH, _agent_class()())
            introspection = await bus.introspect("org.bluez", "/org/bluez")
            manager = bus.get_proxy_object(
                "org.bluez", "/org/bluez", introspection
            ).get_interface("org.bluez.AgentManager1")
            await manager.call_register_agent(AGENT_PATH, CAPABILITY)
            await manager.call_request_default_agent(AGENT_PATH)
        _LOGGER.debug("Registered BlueZ pairing agent")
    except Exception as err:  # noqa: BLE001
        # Bluetooth proxies and non-BlueZ systems handle pairing themselves.
        _LOGGER.debug("No BlueZ pairing agent registered: %s", err)
        manager = None
    try:
        yield
    finally:
        if manager is not None:
            with suppress(Exception):
                await manager.call_unregister_agent(AGENT_PATH)
        if bus is not None:
            with suppress(Exception):
                bus.disconnect()
