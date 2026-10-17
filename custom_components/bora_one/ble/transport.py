"""Asynchronous BRPC transport with bounded requests and no command replay.

Modified for bora_one: bond verification and pairing work with BlueZ (see connect).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import Protocol

from .wire import FrameDecoder, ProtocolError, Response, Stream, request

SERVICE_UUID = "64cbfe50-126b-17ac-774e-f6fa40487dac"
WRITE_UUID = "64cbfe51-126b-17ac-774e-f6fa40487dac"
RESPONSE_UUID = "64cbfe52-126b-17ac-774e-f6fa40487dac"
BOND_UUID = "64cbfe53-126b-17ac-774e-f6fa40487dac"

_LOGGER = logging.getLogger(__name__)


class BoraError(Exception):
    """A BORA operation failed."""


class ConnectionLost(BoraError):
    """The BLE connection is unavailable."""


class PairingRequired(BoraError):
    """The adapter needs to pair with the appliance."""


class RequestTimeout(BoraError):
    """No response arrived; a write may have reached the appliance."""


class RpcError(BoraError):
    """The appliance rejected an RPC."""

    def __init__(
        self,
        code: int,
        error: bytes | None = None,
        *,
        request_id: int | None = None,
        path: str | None = None,
        stream: Stream | None = None,
    ) -> None:
        # Keep raw appliance details private, out of exception messages/logs.
        super().__init__(f"BORA returned response code {code}")
        self.code = code
        self.error = error
        self.request_id = request_id
        self.path = path
        self.stream = stream


class GattClient(Protocol):
    """Subset of Bleak used here; allows independent simulated-peer testing."""

    @property
    def is_connected(self) -> bool: ...
    async def start_notify(self, uuid: str, callback: Callable) -> None: ...
    async def read_gatt_char(self, uuid: str) -> bytearray: ...
    async def write_gatt_char(self, uuid: str, data: bytes, response: bool) -> None: ...
    async def pair(self) -> None: ...
    async def disconnect(self) -> None: ...  # unpair() is optional


type Connector = Callable[[Callable[[GattClient], None]], Awaitable[GattClient]]
type UpdateCallback = Callable[[bytes], None]
type ErrorCallback = Callable[[RpcError], None]


@dataclass
class Subscription:
    path: str
    callback: UpdateCallback


class BrpcConnection:
    """One connection generation; every connect receives a fresh GATT client.

    The caller supplies a connector (HA uses its shared Bluetooth manager).
    There are no background retries or heartbeats. Control requests are never
    automatically retried, including when the reply is lost after transmission.
    """

    def __init__(
        self,
        connector: Connector,
        *,
        timeout: float = 10,
        connect_timeout: float = 60,
        disconnect_timeout: float = 5,
        disconnected: Callable[[], None] | None = None,
        pair_wait: float = 50,
    ) -> None:
        self._connector = connector
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.disconnect_timeout = disconnect_timeout
        self._disconnected_callback = disconnected
        self.pair_wait = pair_wait
        self._client: GattClient | None = None
        self._generation: object | None = None
        self._decoder = FrameDecoder()
        self._pending: dict[int, asyncio.Future[Response]] = {}
        self._request_paths: dict[int, str | None] = {}
        self._receivers: dict[int, UpdateCallback] = {}
        self._error_receivers: dict[int, ErrorCallback] = {}
        self._subscriptions: dict[int, Subscription] = {}
        self._write_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()
        self._counter = 0
        self._closing = False
        self._failed = False
        self.bond_state: int | None = None
        self.last_protocol_error: str | None = None
        self._last_rpc_error: dict | None = None

    @property
    def connected(self) -> bool:
        return bool(self._client and self._client.is_connected and not self._failed)

    @property
    def subscription_count(self) -> int:
        return len(self._subscriptions)

    @property
    def last_rpc_error(self) -> dict | None:
        """Source of the latest active response error, without raw error data."""
        return None if self._last_rpc_error is None else dict(self._last_rpc_error)

    async def connect(self, *, pair: bool = False) -> None:
        """Connect, make sure the link is bonded and subscribe.

        Pairing only happens when ``pair`` is set (explicit setup). On BlueZ an
        existing bond is used only once the link is encrypted, which happens
        when a protected characteristic is accessed. After pairing the GATT
        table can change, so the bond is verified on a fresh connection.
        """
        async with self._connect_lock:
            if self.connected:
                return
            if self._client:
                await self.disconnect()
            done: set[str] = set()
            for _attempt in range(6):
                action = await self._open(pair=pair, done=done)
                if action is None:
                    return
                # Pairing (or removing a stale bond) happened; verify on a new link.
                await self.disconnect()
            raise PairingRequired("Bluetooth bonding did not complete")

    async def _read_bond_state(self, client: GattClient) -> int:
        state = bytes(await client.read_gatt_char(BOND_UUID))
        if len(state) != 1 or state[0] not in (0, 1, 2):
            raise ProtocolError("Invalid bonding status")
        return state[0]

    async def _initial_bond_state(self, client: GattClient, *, pair: bool) -> int:
        """Read the bond state; while pairing, a refused read counts as unbonded."""
        try:
            return await self._read_bond_state(client)
        except ProtocolError:
            raise
        except Exception:
            if not pair or not client.is_connected:
                raise
            return 0

    async def _pair_and_wait(self, client: GattClient) -> int | None:
        """Request pairing and keep the link open until the user confirms on the cooktop.

        Returns the bond state, or None when the GATT table changed and a new
        connection is needed.
        """
        loop = asyncio.get_running_loop()
        pairing = asyncio.ensure_future(client.pair())
        deadline = loop.time() + self.pair_wait
        try:
            while True:
                if pairing.done() and not pairing.cancelled():
                    pairing.exception()  # retrieved; a failed pair() may still bond later
                with suppress(Exception):
                    await client.read_gatt_char(RESPONSE_UUID)
                try:
                    if await self._read_bond_state(client) == 1:
                        return 1
                except ProtocolError:
                    raise
                except Exception as err:  # noqa: BLE001
                    if "not found" in str(err).lower():
                        return None
                if not client.is_connected:
                    raise ConnectionLost("Bluetooth disconnected while pairing")
                if loop.time() >= deadline:
                    return 0
                await asyncio.sleep(1)
        finally:
            if not pairing.done():
                pairing.cancel()
            with suppress(BaseException):
                await pairing

    async def _open(self, *, pair: bool, done: set[str]) -> str | None:
        """Open one connection; return None when ready, else the pairing action taken."""
        self._closing = False
        self._failed = False
        self._decoder.reset()
        self.last_protocol_error = None
        self._last_rpc_error = None
        generation = self._generation = object()

        def on_disconnect(client: GattClient) -> None:
            if self._generation is generation and self._client is client:
                self._client = None
                self._fail(ConnectionLost("Bluetooth disconnected"))

        try:
            budget = self.connect_timeout + (self.pair_wait if pair else 0)
            async with asyncio.timeout(budget):
                client = await self._connector(on_disconnect)
                if self._generation is not generation:
                    await client.disconnect()
                    raise ConnectionLost("Connection attempt was closed")
                self._client = client
                if not client.is_connected:
                    raise ConnectionLost("Connector returned a disconnected client")

                def on_notification(_sender, value: bytearray) -> None:
                    if self._generation is generation and not self._failed:
                        self._receive(value)

                # Subscribing writes the protected CCCD, which makes BlueZ
                # encrypt the link with stored keys (like the BORA One app).
                notifying = False
                try:
                    await client.start_notify(RESPONSE_UUID, on_notification)
                    notifying = True
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("Subscribing before bond check failed: %r", err)
                state = await self._initial_bond_state(client, pair=pair)
                _LOGGER.debug("Connected; bond state %s", state)
                if state != 1:
                    # Encrypt with stored keys by touching the protected channel;
                    # encryption completes asynchronously, so poll for a moment.
                    for _ in range(6):
                        with suppress(Exception):
                            await client.read_gatt_char(RESPONSE_UUID)
                        state = await self._initial_bond_state(client, pair=pair)
                        if state == 1 or not client.is_connected:
                            break
                        await asyncio.sleep(0.5)
                    _LOGGER.debug("Bond state after touching the protected channel: %s", state)
                self.bond_state = state
                if state != 1:
                    if not pair:
                        raise PairingRequired("Pair this Bluetooth adapter with BORA first")
                    if "pair" not in done:
                        done.add("pair")
                        result = await self._pair_and_wait(client)
                        if result is None:
                            return "pair"  # GATT table changed; continue on a new link
                        state = result
                    if state != 1:
                        if "unpair" not in done and hasattr(client, "unpair"):
                            # The adapter may hold keys the cooktop has forgotten.
                            done.add("unpair")
                            done.discard("pair")
                            with suppress(Exception):
                                await client.unpair()
                            return "unpair"
                        raise PairingRequired("Bluetooth bonding did not complete")
                    self.bond_state = state

                if self._generation is not generation:
                    raise ConnectionLost("Connection closed during setup")
                if notifying:
                    return None
                try:
                    await client.start_notify(RESPONSE_UUID, on_notification)
                except Exception as err:
                    if "pair" in done and "not found" in str(err).lower():
                        return "pair"  # GATT table changed after pairing
                    raise
                return None
        except BaseException:
            await self.disconnect()
            raise

    def _fail(self, error: Exception) -> None:
        self._failed = True
        for future in tuple(self._pending.values()):
            if not future.done():
                future.set_exception(error)
        self._pending.clear()
        self._request_paths.clear()
        self._receivers.clear()
        self._error_receivers.clear()
        self._subscriptions.clear()
        if not self._closing and self._disconnected_callback:
            self._disconnected_callback()

    def _receive(self, chunk: bytearray) -> None:
        try:
            for payload in self._decoder.feed(chunk):
                reply = Response.decode(payload)
                _LOGGER.debug(
                    "Received id=%s code=%s stream=%s body=%s bytes",
                    reply.request_id, reply.code, reply.stream.name,
                    len(reply.body) if reply.body is not None else None,
                )
                future = self._pending.get(reply.request_id)
                subscription = self._subscriptions.get(reply.request_id)
                if reply.code or reply.error is not None:
                    active_request = future is not None and not future.done()
                    if not active_request and subscription is None:
                        continue
                    path = self._request_paths.get(reply.request_id) if active_request else None
                    if path is None and subscription is not None:
                        path = subscription.path
                    error = RpcError(
                        reply.code, reply.error, request_id=reply.request_id,
                        path=path, stream=reply.stream,
                    )
                    self._last_rpc_error = {
                        "request_id": reply.request_id, "path": path,
                        "code": reply.code, "stream": reply.stream.name,
                    }
                    if active_request:
                        if reply.stream == Stream.NONE and (
                            failed := self._error_receivers.get(reply.request_id)
                        ):
                            # Invalidate in wire arrival order, before any
                            # later stream can restore this request's state.
                            failed(error)
                        future.set_exception(error)
                    elif subscription:
                        self._fail(error)
                    continue
                if subscription and reply.stream == Stream.CONTINUE:
                    if reply.body is None:
                        raise ProtocolError("Stream update has no body")
                    subscription.callback(reply.body)
                elif future and not future.done():
                    if reply.stream == Stream.NONE and (
                        receiver := self._receivers.get(reply.request_id)
                    ):
                        # Commit in wire arrival order, before resolving the
                        # waiter. A later stream event in this notification
                        # must remain newer than this unary snapshot.
                        receiver(reply.body or b"")
                    future.set_result(reply)
                elif subscription and reply.stream == Stream.STOP:
                    self._fail(ConnectionLost("Appliance ended a status subscription"))
                # An unrelated or late response must not satisfy a newer RPC.
        except (ProtocolError, ValueError, TypeError) as err:
            self.last_protocol_error = str(err)
            self._fail(BoraError("Invalid BORA protocol response"))

    def _next_id(self) -> int:
        # IDs are uint32. Never reuse an ID still associated with a request.
        while True:
            self._counter = self._counter % 0xFFFFFFFF + 1
            if self._counter not in self._pending and self._counter not in self._subscriptions:
                return self._counter

    async def _send(self, packet: bytes) -> None:
        client = self._client
        generation = self._generation
        async with self._write_lock:
            if (
                not self.connected
                or self._client is not client
                or self._generation is not generation
            ):
                raise ConnectionLost("Bluetooth is not connected")
            for offset in range(0, len(packet), 20):
                if not self.connected or self._generation is not generation:
                    raise ConnectionLost("Bluetooth disconnected during write")
                # Conservative ATT size works without assuming a negotiated MTU.
                await client.write_gatt_char(
                    WRITE_UUID, packet[offset : offset + 20], response=True
                )

    async def _exchange(
        self,
        request_id: int,
        packet: bytes,
        *,
        wait_seconds: float | None = None,
        received: UpdateCallback | None = None,
        failed: ErrorCallback | None = None,
        path: str | None = None,
    ) -> Response:
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        self._request_paths[request_id] = path
        if received is not None:
            self._receivers[request_id] = received
        if failed is not None:
            self._error_receivers[request_id] = failed
        try:
            async with asyncio.timeout(self.timeout if wait_seconds is None else wait_seconds):
                _LOGGER.debug("Sending %s id=%s (%s bytes)", path, request_id, len(packet))
                await self._send(packet)
                return await future
        except TimeoutError as err:
            _LOGGER.warning("BORA did not reply to %s (id=%s)", path, request_id)
            raise RequestTimeout("BORA did not reply; the request will not be replayed") from err
        finally:
            if self._pending.get(request_id) is future:
                self._pending.pop(request_id)
                self._request_paths.pop(request_id, None)
                self._receivers.pop(request_id, None)
                self._error_receivers.pop(request_id, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                # Retrieve a disconnect exception even if a write failed first.
                future.exception()

    async def rpc(
        self,
        path: str,
        body: bytes = b"",
        *,
        received: UpdateCallback | None = None,
        failed: ErrorCallback | None = None,
    ) -> bytes:
        request_id = self._next_id()
        reply = await self._exchange(
            request_id, request(path, request_id, body), received=received, failed=failed, path=path
        )
        if reply.stream != Stream.NONE:
            raise ProtocolError("Unexpected streaming reply to a unary request")
        return reply.body or b""

    async def subscribe(self, path: str, callback: UpdateCallback) -> int:
        request_id = self._next_id()
        self._subscriptions[request_id] = Subscription(path, callback)
        try:
            reply = await self._exchange(request_id, request(path, request_id), path=path)
            if reply.stream != Stream.START:
                raise ProtocolError("Missing stream START")
        except BaseException:
            self._subscriptions.pop(request_id, None)
            # A timeout may have left a remote subscription alive. Close the
            # connection instead of silently leaking it or replaying requests.
            await self.disconnect()
            raise
        return request_id

    async def unsubscribe(self, request_id: int) -> None:
        subscription = self._subscriptions.get(request_id)
        if subscription is None:
            return
        try:
            reply = await self._exchange(
                request_id,
                request(subscription.path, request_id, stop=True),
                wait_seconds=min(self.timeout, 3),
                path=subscription.path,
            )
            if reply.stream != Stream.STOP:
                raise ProtocolError("Missing stream STOP")
        finally:
            self._subscriptions.pop(request_id, None)

    async def disconnect(self) -> None:
        """Stop read subscriptions and close; never alter appliance settings."""
        self._closing = True
        client = self._client
        try:
            if self.connected:
                for request_id in tuple(self._subscriptions):
                    with suppress(Exception):
                        await self.unsubscribe(request_id)
        finally:
            self._client = None
            self._generation = None
            self._fail(ConnectionLost("Bluetooth connection closed"))
            self._decoder.reset()
            if client:
                with suppress(Exception):
                    async with asyncio.timeout(self.disconnect_timeout):
                        await client.disconnect()
