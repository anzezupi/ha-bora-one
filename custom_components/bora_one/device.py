"""Read-only connection to a BORA appliance over Bluetooth.

Connection setup follows ha-bora's BoraDevice, reduced to status reads and
status subscriptions. No setter RPC is ever sent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
import logging
from typing import Any

from .ble import cooktop, extractor, identify, zone
from .ble.transport import BrpcConnection, ConnectionLost, RequestTimeout, RpcError
from .ble.wire import ProtocolError, Stream

_LOGGER = logging.getLogger(__name__)

UNIMPLEMENTED = 12
UNAVAILABLE = 14

# The cooktop status stream is not used: X Pure does not answer it, and its
# content (pause, locks, errors) is read with every periodic refresh.
STREAMS = (
    (extractor.STREAM_PATH, "extractor", extractor.decode_status),
    (zone.STREAM_PATH, "zones", zone.decode_status),
)


def _unimplemented(err: RpcError, path: str, streams: tuple[Stream, ...]) -> bool:
    """Return True when the appliance rejected exactly this request as unsupported."""
    return (
        err.code == UNIMPLEMENTED
        and err.path == path
        and err.request_id is not None
        and err.stream in streams
    )


class BoraBleDevice:
    """Keeps the latest decoded status of one appliance."""

    def __init__(
        self, connection: BrpcConnection, updated: Callable[[], None] | None = None
    ) -> None:
        """Initialize the device."""
        self.connection = connection
        self._updated = updated
        self.information: dict[str, Any] = {}
        self.descriptor: dict[str, Any] = {}
        self._state: dict[str, Any] = {"extractor": None, "cooktop": None, "zones": {}}
        self._unsupported_streams: set[str] = set()
        self._lock = asyncio.Lock()
        self._ready = False

    @property
    def connected(self) -> bool:
        """Return True while the Bluetooth connection is up."""
        return self.connection.connected

    @property
    def state(self) -> dict[str, Any]:
        """Return a copy of the decoded status."""
        return deepcopy(self._state)

    @property
    def zone_uids(self) -> tuple[str, ...]:
        """Return the zone UIDs advertised by the appliance."""
        uids = (self.descriptor.get("zone_uids") or {}).values()
        return tuple(dict.fromkeys(uid for uid in uids if uid))

    async def connect(self, *, pair: bool = False, subscribe: bool = True) -> None:
        """Connect, read capabilities, subscribe to status streams and read status."""
        async with self._lock:
            if self.connected and self._ready:
                return
            self._ready = False
            # A failed subscription closes the connection; reconnect without that stream.
            for _attempt in range(len(STREAMS) + 1):
                try:
                    await self.connection.connect(pair=pair)
                    await self._read_metadata()
                    if subscribe and not await self._subscribe():
                        continue
                    await self._read_statuses()
                except BaseException:
                    await self.connection.disconnect()
                    raise
                self._ready = True
                return
            raise ConnectionLost("Unable to set up BORA status subscriptions")

    async def refresh(self) -> None:
        """Re-read all status values on the open connection."""
        async with self._lock:
            if not self.connected:
                raise ConnectionLost("BORA is not connected")
            await self._read_statuses()

    async def disconnect(self) -> None:
        """Stop subscriptions and close the connection."""
        self._ready = False
        await self.connection.disconnect()

    async def _read_metadata(self) -> None:
        self.descriptor = identify.decode_descriptor(
            await self.connection.rpc(*identify.get_descriptor())
        )
        if not self.descriptor.get("extractor_descriptor") and not self.zone_uids:
            raise ProtocolError("BORA descriptor lists no zones or extractor")
        path, body = identify.get_information()
        try:
            self.information = identify.decode_information(await self.connection.rpc(path, body))
        except RpcError as err:
            if not _unimplemented(err, path, (Stream.NONE,)):
                raise
            self.information = {}

    async def _subscribe(self) -> bool:
        """Subscribe to all supported streams; False means reconnect and retry."""
        for path, category, decoder in STREAMS:
            if path in self._unsupported_streams or (category == "zones" and not self.zone_uids):
                continue
            try:
                await self.connection.subscribe(path, self._stream_callback(category, decoder))
            except RequestTimeout:
                # No answer at all: use periodic reads for this status instead.
                _LOGGER.info("BORA does not answer %s; using periodic reads", path)
                self._unsupported_streams.add(path)
                return False
            except RpcError as err:
                if not _unimplemented(err, path, (Stream.NONE, Stream.START)):
                    raise
                self._unsupported_streams.add(path)
                return False
        return True

    def _stream_callback(self, category: str, decoder: Callable[[bytes], dict]):
        def update(body: bytes) -> None:
            status = decoder(body)
            if category == "zones":
                uid = status.get("uid")
                if uid not in self.zone_uids:
                    raise ProtocolError("Zone stream contains an unadvertised zone")
                self._state["zones"][uid] = status
            else:
                self._state[category] = status
            if self._ready and self._updated:
                self._updated()

        return update

    async def _read_statuses(self) -> None:
        def store(category: str, decoder: Callable[[bytes], dict]) -> Callable[[bytes], None]:
            def received(body: bytes) -> None:
                self._state[category] = decoder(body)

            return received

        if self.descriptor.get("extractor_descriptor"):
            await self.connection.rpc(
                *extractor.get_status(), received=store("extractor", extractor.decode_status)
            )
        await self.connection.rpc(
            *cooktop.get_status(), received=store("cooktop", cooktop.decode_status)
        )

        self._state["zones"] = {
            uid: status for uid, status in self._state["zones"].items() if uid in self.zone_uids
        }
        for uid in self.zone_uids:
            unavailable = False

            def store_zone(body: bytes, expected: str = uid) -> None:
                status = zone.decode_status(body)
                if status.get("uid") != expected:
                    raise ProtocolError("Zone status does not match the requested zone")
                self._state["zones"][expected] = status

            def failed_zone(error: RpcError, expected: str = uid) -> None:
                nonlocal unavailable
                if error.code == UNAVAILABLE:
                    unavailable = True
                    self._state["zones"].pop(expected, None)

            try:
                await self.connection.rpc(
                    *zone.get_status(uid), received=store_zone, failed=failed_zone
                )
            except RpcError as err:
                # An unavailable zone is unknown, not off; keep reading the others.
                if err.code != UNAVAILABLE or not unavailable:
                    raise
        if not self.connected:
            raise ConnectionLost("Bluetooth disconnected during status read")
