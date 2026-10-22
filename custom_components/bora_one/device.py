"""Read-only connection to a BORA appliance over Bluetooth.

Connection setup follows ha-bora's BoraDevice, reduced to status reads and
status subscriptions. No setter RPC is ever sent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
import logging
import time
from typing import Any

from .ble import cooktop, extractor, identify, zone
from .ble.transport import BrpcConnection, ConnectionLost, RpcError
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

# While a zone is on, an X Pure behind a BlueZ adapter was seen to stop
# answering and drop the link a few seconds after a status subscription.
# A link lost this soon after subscribing means: use periodic reads only.
STREAM_GRACE = 60.0

# While cooking, an X Pure was seen to leave a request unanswered and drop
# the link when requests follow each other closely. Leave a short gap.
REQUEST_GAP = 0.3


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
        self.use_streams = True
        self._subscribed_at: float | None = None
        self._lock = asyncio.Lock()
        self._ready = False
        self._have_metadata = False
        self.connecting = False

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

    async def connect(
        self, *, pair: bool = False, subscribe: bool = True, read_status: bool = True
    ) -> None:
        """Connect, read capabilities and status, then subscribe to status streams."""
        async with self._lock:
            if self.connected and self._ready:
                return
            self._ready = False
            self._subscribed_at = None
            self.connecting = True
            try:
                # A failed subscription closes the connection; reconnect without it.
                for _attempt in range(len(STREAMS) + 2):
                    try:
                        await self.connection.connect(pair=pair)
                        await self._read_metadata()
                        # Read first, so a subscription that upsets the
                        # cooktop cannot keep us from ever seeing its status.
                        if read_status:
                            await self._read_statuses()
                        if subscribe and self.use_streams and not await self._subscribe():
                            continue
                    except BaseException:
                        await self.connection.disconnect()
                        raise
                    if self.connection.subscription_count:
                        self._subscribed_at = time.monotonic()
                    self._ready = True
                    return
                raise ConnectionLost("Unable to set up BORA status subscriptions")
            finally:
                self.connecting = False

    def connection_lost(self) -> None:
        """The link dropped; stop using streams if it dropped soon after subscribing."""
        subscribed_at, self._subscribed_at = self._subscribed_at, None
        if subscribed_at is not None and time.monotonic() - subscribed_at < STREAM_GRACE:
            self._disable_streams("BORA dropped the connection soon after subscribing")

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

    async def _rpc(self, *args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(REQUEST_GAP)
        return await self.connection.rpc(*args, **kwargs)

    async def _read_metadata(self) -> None:
        if self._have_metadata:
            # Capabilities do not change; fewer requests per connection
            # means fewer chances for the cooktop to stop answering.
            return
        self.descriptor = identify.decode_descriptor(
            await self._rpc(*identify.get_descriptor())
        )
        if not self.descriptor.get("extractor_descriptor") and not self.zone_uids:
            raise ProtocolError("BORA descriptor lists no zones or extractor")
        path, body = identify.get_information()
        try:
            self.information = identify.decode_information(await self._rpc(path, body))
        except RpcError as err:
            if not _unimplemented(err, path, (Stream.NONE,)):
                raise
            self.information = {}
        self._have_metadata = True

    async def _subscribe(self) -> bool:
        """Subscribe to all supported streams; False means reconnect and retry."""
        for path, category, decoder in STREAMS:
            if path in self._unsupported_streams or (category == "zones" and not self.zone_uids):
                continue
            try:
                await self.connection.subscribe(path, self._stream_callback(category, decoder))
            except RpcError as err:
                if not _unimplemented(err, path, (Stream.NONE, Stream.START)):
                    raise
                self._unsupported_streams.add(path)
                return False
            except ProtocolError:
                raise
            except Exception as err:  # noqa: BLE001
                # No answer or a dropped link: the cooktop stops answering
                # after an earlier subscription too, so poll everything.
                self._disable_streams(f"BORA does not answer {path} ({err!r})")
                return False
        return True

    def _disable_streams(self, reason: str) -> None:
        if self.use_streams:
            _LOGGER.warning("%s; using periodic reads instead of status updates", reason)
        self.use_streams = False

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
            await self._rpc(
                *extractor.get_status(), received=store("extractor", extractor.decode_status)
            )
        await self._rpc(
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
                    # X Pure answers this for every zone once it is switched
                    # off but still holds the Bluetooth link: the zone is off.
                    unavailable = True
                    self._state["zones"][expected] = {"uid": expected, "unavailable": True}

            try:
                await self._rpc(
                    *zone.get_status(uid), received=store_zone, failed=failed_zone
                )
            except RpcError as err:
                # An unavailable zone is switched off; keep reading the others.
                if err.code != UNAVAILABLE or not unavailable:
                    raise
            except (ConnectionLost, ProtocolError):
                raise
            except Exception as err:  # noqa: BLE001
                # X Pure sometimes refuses a single read at GATT level; the
                # link stays usable, so treat this zone as unknown for now.
                if not self.connected:
                    raise
                _LOGGER.warning("Reading zone %s failed: %r", uid, err)
                self._state["zones"].pop(uid, None)
        if not self.connected:
            raise ConnectionLost("Bluetooth disconnected during status read")
