"""BORA BRPC framing and minimal Protobuf primitives.

Reconstructed independently from BORA One descriptors and verified recordings.
This module performs no I/O and does not import Home Assistant or Bleak.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from enum import IntEnum

MAX_FRAME_SIZE = 1024 * 1024


class ProtocolError(ValueError):
    """Malformed or unsupported protocol data."""


class Stream(IntEnum):
    NONE = 0
    CONTINUE = 1
    STOP = 2
    START = 3


def varint(value: int) -> bytes:
    if not 0 <= value < 2**64:
        raise ProtocolError("Varint outside uint64 range")
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def uint(number: int, value: int) -> bytes:
    """Encode an unsigned integer field, including explicit zero."""
    return varint(number << 3) + varint(value)


def sint32(number: int, value: int) -> bytes:
    if not -(2**31) <= value < 2**31:
        raise ProtocolError("Value outside int32 range")
    return uint(number, value if value >= 0 else value + 2**64)


def blob(number: int, value: bytes) -> bytes:
    return varint((number << 3) | 2) + varint(len(value)) + value


def string(number: int, value: str) -> bytes:
    return blob(number, value.encode("utf-8"))


def frame(payload: bytes) -> bytes:
    packet = payload + struct.pack(">I", zlib.crc32(payload))
    return (
        b"\x7e"
        + b"".join(
            bytes((0x7D, b & 0x5F)) if b in (0x7C, 0x7D, 0x7E) else bytes((b,)) for b in packet
        )
        + b"\x7c"
    )


class FrameDecoder:
    """Incrementally decode notifications; reject corrupt frames before routing."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._buffer: bytearray | None = None
        self._escaped = False

    @property
    def incomplete(self) -> bool:
        return self._buffer is not None

    def feed(self, data: bytes | bytearray) -> list[bytes]:
        packets = []
        for value in data:
            if value == 0x7E:
                self._buffer = bytearray()
                self._escaped = False
            elif self._buffer is None:
                continue
            elif self._escaped:
                if value not in (0x5C, 0x5D, 0x5E):
                    self.reset()
                    raise ProtocolError("Invalid frame escape")
                self._buffer.append(value | 0x20)
                self._escaped = False
            elif value == 0x7D:
                self._escaped = True
            elif value == 0x7C:
                packet = bytes(self._buffer)
                self.reset()
                if len(packet) < 4:
                    raise ProtocolError("Frame shorter than CRC")
                payload, checksum = packet[:-4], packet[-4:]
                if zlib.crc32(payload) != struct.unpack(">I", checksum)[0]:
                    raise ProtocolError("Frame CRC mismatch")
                packets.append(payload)
            else:
                self._buffer.append(value)
            if self._buffer is not None and len(self._buffer) > MAX_FRAME_SIZE:
                self.reset()
                raise ProtocolError("Frame too large")
        return packets


@dataclass(frozen=True)
class Field:
    number: int
    wire: int
    value: int | bytes


class Message:
    """Preserve repeated fields and their order, including oneof selection."""

    def __init__(self, data: bytes = b"") -> None:
        self.fields: list[Field] = []
        offset = 0

        def read_varint() -> int:
            nonlocal offset
            result = 0
            for shift in range(0, 70, 7):
                if offset >= len(data):
                    raise ProtocolError("Truncated varint")
                value = data[offset]
                offset += 1
                if shift == 63 and value > 1:
                    raise ProtocolError("Varint overflow")
                result |= (value & 127) << shift
                if value < 128:
                    return result
            raise ProtocolError("Varint too long")

        while offset < len(data):
            tag = read_varint()
            number, wire = tag >> 3, tag & 7
            if not 0 < number < 2**29:
                raise ProtocolError("Invalid field number")
            if wire == 0:
                value = read_varint()
            elif wire in (1, 2, 5):
                size = read_varint() if wire == 2 else {1: 8, 5: 4}[wire]
                if offset + size > len(data):
                    raise ProtocolError("Truncated field")
                value = data[offset : offset + size]
                offset += size
            else:
                raise ProtocolError(f"Unsupported wire type {wire}")
            self.fields.append(Field(number, wire, value))

    def has(self, number: int) -> bool:
        return any(field.number == number for field in self.fields)

    def value(self, number: int, wire: int, default=None):
        for field in reversed(self.fields):
            if field.number == number:
                if field.wire != wire:
                    raise ProtocolError(f"Unexpected wire type for field {number}")
                return field.value
        return default

    def uint(self, number: int, default: int = 0) -> int:
        return self.value(number, 0, default)

    def int32(self, number: int, default: int = 0) -> int:
        value = self.uint(number, default) & 0xFFFFFFFF
        return value - 2**32 if value & 0x80000000 else value

    def boolean(self, number: int) -> bool:
        return bool(self.uint(number))

    def bytes(self, number: int, default: bytes = b"") -> bytes:
        return self.value(number, 2, default)

    def text(self, number: int, default: str = "") -> str:
        try:
            return self.bytes(number, default.encode()).decode("utf-8")
        except UnicodeDecodeError as err:
            raise ProtocolError("Invalid UTF-8 string") from err

    def message(self, number: int) -> Message:
        return Message(self.bytes(number))

    def messages(self, number: int) -> list[Message]:
        result = []
        for field in self.fields:
            if field.number == number:
                if field.wire != 2:
                    raise ProtocolError("Expected repeated message")
                result.append(Message(field.value))
        return result

    def oneof(self, numbers: set[int]) -> int | None:
        return next(
            (field.number for field in reversed(self.fields) if field.number in numbers), None
        )


def request(path: str, request_id: int, body: bytes = b"", *, stop: bool = False) -> bytes:
    if not 1 <= request_id <= 0xFFFFFFFF:
        raise ProtocolError("Request ID must be a nonzero uint32")
    payload = string(2, path) + uint(3, request_id)
    if body:
        payload += blob(4, body)
    if stop:
        payload += uint(6, Stream.STOP)
    return frame(payload)


@dataclass(frozen=True)
class Response:
    request_id: int
    code: int
    body: bytes | None
    error: bytes | None
    stream: Stream

    @classmethod
    def decode(cls, payload: bytes) -> Response:
        message = Message(payload)
        try:
            stream = Stream(message.uint(7))
        except ValueError as err:
            raise ProtocolError("Unknown stream marker") from err
        request_id = message.uint(3)
        if not 1 <= request_id <= 0xFFFFFFFF:
            raise ProtocolError("Invalid response request ID")
        return cls(request_id, message.uint(2), message.value(4, 2), message.value(5, 2), stream)
