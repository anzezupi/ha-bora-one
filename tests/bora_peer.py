"""A simulated BORA cooktop speaking BRPC over a fake GATT client.

Responses are taken from recordings of a real X Pure (tests/fixtures), so
the integration is exercised through the real framing, CRC, chunking and
protobuf decoding. No Bluetooth hardware is used.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
from pathlib import Path

from custom_components.bora_one.ble import wire
from custom_components.bora_one.ble.transport import (
    BOND_UUID,
    RESPONSE_UUID,
    WRITE_UUID,
    BrpcConnection,
)

FIXTURES = Path(__file__).parent / "fixtures"
EXTRACTOR = "/bora.generic.extractor.v1.ExtractorService/"
COOKTOP = "/bora.generic.cooktop.v1.CooktopService/"
ZONE = "/bora.generic.zone.v1.ZoneService/"
IDENTIFY = "/bora.generic.identify.v1.IdentifyService/"


def _recorded() -> dict[str, bytes]:
    """Return response bodies keyed by '<session>/<method>' (first occurrence)."""
    data = json.loads((FIXTURES / "x_pure_3_0_9.json").read_text())
    bodies: dict[str, bytes] = {}
    decoder = wire.FrameDecoder()
    for session in data["sessions"]:
        methods: dict[int, str] = {}
        for event in session["events"]:
            if event["event"] == "request":
                methods[event["request_id"]] = event["method"]
                continue
            for payload in decoder.feed(bytes.fromhex(event["hex"])):
                response = wire.Response.decode(payload)
                key = f"{session['name']}/{methods.get(response.request_id)}"
                if response.body is not None:
                    bodies.setdefault(key, response.body)
    cooking = json.loads((FIXTURES / "x_pure_cooking_2026_09_26.json").read_text())
    for name, item in cooking["responses"].items():
        response = wire.Response.decode(bytes.fromhex(item["response_payload_hex"]))
        if response.body is not None:
            bodies[f"cooking/{name}"] = response.body
    return bodies


RECORDED = _recorded()
DESCRIPTOR = RECORDED["device-descriptor-1/GetSystemValueRangeDescriptor"]
COOKTOP_STATUS = RECORDED["cooktop-status-1/GetCooktopStatus"]
EXTRACTOR_LEVEL_3 = RECORDED["status-request-2/GetExtractorStatus"]
EXTRACTOR_OFF = RECORDED["standby-extractor-1/GetExtractorStatus"]
EXTRACTOR_AFTER_RUN = RECORDED["poll-observation-1/GetExtractorStatus"]
ZONE_OFF = {
    "front_left": RECORDED["zone-status-left_down/GetZoneStatus"],
    "back_left": RECORDED["zone-status-left_upper/GetZoneStatus"],
    "back_right": RECORDED["zone-status-right_upper/GetZoneStatus"],
    "front_right": RECORDED["zone-status-right_down/GetZoneStatus"],
}
BACK_LEFT_LEVEL_7 = RECORDED["cooking/back_left_power_7"]

INFORMATION = (
    wire.uint(1, 2)  # x_pure
    + wire.string(7, "1")
    + wire.string(8, "3.0.9")
    + wire.string(9, "SERIAL123")
)


def zone_status(
    uid: str,
    *,
    power: int | None = None,
    timer_remaining_ms: int | None = None,
    frying: tuple[int, int] | None = None,
    residual_heat: bool = False,
) -> bytes:
    """Build a ZoneStatus body. ``frying`` is (target temperature, phase)."""
    if frying is not None:
        target, phase = frying
        csf = wire.blob(1, wire.uint(4, 2) + wire.uint(5, target)) + wire.uint(2, phase)
        mode = wire.blob(2, csf)
    else:
        mode = wire.sint32(1, power or 0)
    settings = wire.string(1, uid) + wire.blob(2, mode)
    if timer_remaining_ms is not None:
        settings += wire.blob(3, wire.uint(1, 600000) + wire.uint(2, timer_remaining_ms) + wire.uint(3, 1))
    body = wire.blob(1, settings)
    if residual_heat:
        body += wire.uint(2, 1)
    return body


class FakeBoraPeer:
    """Fake Bleak client plus the appliance behind it."""

    def __init__(self) -> None:
        self.is_connected = False
        self.bonded = True
        self.encrypted = False
        self.stale_keys = False
        self.unpaired = False
        self.accept_pairing = True
        self.confirm_delay = 0.0
        """Seconds until the user taps Connect on the cooktop."""
        self.advertising = True
        self.requests: list[str] = []
        self.status: dict[str, bytes] = {
            EXTRACTOR + "GetExtractorStatus": EXTRACTOR_LEVEL_3,
            COOKTOP + "GetCooktopStatus": COOKTOP_STATUS,
            IDENTIFY + "GetSystemValueRangeDescriptor": DESCRIPTOR,
            IDENTIFY + "GetSystemInformation": INFORMATION,
        }
        self.zones = dict(ZONE_OFF)
        self.zones["back_left"] = BACK_LEFT_LEVEL_7
        self.subscriptions: dict[str, int] = {}
        self._notify: Callable | None = None
        self._disconnected: Callable | None = None
        self._decoder = wire.FrameDecoder()

    # Connector used by BrpcConnection

    async def connect(self, disconnected: Callable) -> FakeBoraPeer:
        if not self.advertising:
            raise TimeoutError("not advertising")
        self._disconnected = disconnected
        self.is_connected = True
        self.encrypted = False
        self.subscriptions.clear()
        return self

    def connection(self, disconnected: Callable[[], None] | None = None) -> BrpcConnection:
        return BrpcConnection(self.connect, timeout=2, disconnected=disconnected, pair_wait=0.5)

    # Bleak client API

    async def read_gatt_char(self, uuid: str) -> bytearray:
        if uuid == BOND_UUID:
            # Like the real cooktop: reports bonded only on an encrypted link.
            return bytearray([1 if self.bonded and self.encrypted else 0])
        if uuid == RESPONSE_UUID and self.bonded and not self.stale_keys:
            self.encrypted = True  # BlueZ encrypts with stored keys on protected access
        return bytearray()

    async def pair(self) -> None:
        if self.stale_keys:
            return  # BlueZ believes it is already paired
        if self.accept_pairing:
            await asyncio.sleep(self.confirm_delay)
            self.bonded = True
            self.encrypted = True

    async def unpair(self) -> None:
        self.unpaired = True
        self.stale_keys = False

    async def start_notify(self, uuid: str, callback: Callable) -> None:
        assert uuid == RESPONSE_UUID
        self._notify = callback

    async def disconnect(self) -> None:
        self.is_connected = False

    async def write_gatt_char(self, uuid: str, data: bytes, response: bool) -> None:
        assert uuid == WRITE_UUID and len(data) <= 20
        for payload in self._decoder.feed(data):
            self._handle(wire.Message(payload))

    # Appliance behaviour

    def _handle(self, request: wire.Message) -> None:
        path, request_id = request.text(2), request.uint(3)
        body = wire.Message(request.bytes(4))
        self.requests.append(path)
        if request.uint(6) == wire.Stream.STOP:
            self._reply(request_id, stream=wire.Stream.STOP)
        elif path.split("/")[-1].startswith("Stream"):
            self.subscriptions[path] = request_id
            self._reply(request_id, stream=wire.Stream.START)
        elif path == ZONE + "GetZoneStatus":
            self._reply(request_id, self.zones[body.text(1)])
        elif path in self.status:
            self._reply(request_id, self.status[path])
        else:
            self._reply(request_id, code=12)

    def _reply(
        self,
        request_id: int,
        body: bytes | None = None,
        *,
        code: int = 0,
        stream: wire.Stream = wire.Stream.NONE,
    ) -> None:
        payload = wire.uint(3, request_id)
        if code:
            payload = wire.uint(2, code) + payload
        if body is not None:
            payload += wire.blob(4, body)
        if stream:
            payload += wire.uint(7, stream)
        frame = wire.frame(payload)
        loop = asyncio.get_running_loop()
        for offset in range(0, len(frame), 20):
            loop.call_soon(self._notify, None, bytearray(frame[offset : offset + 20]))

    def push(self, path: str, body: bytes) -> None:
        """Send a stream update, like the appliance does when something changes."""
        self._reply(self.subscriptions[path], body, stream=wire.Stream.CONTINUE)

    def switch_off(self) -> None:
        """The cooktop is switched off: Bluetooth drops and advertising stops."""
        self.advertising = False
        self.is_connected = False
        if self._disconnected:
            self._disconnected(self)
