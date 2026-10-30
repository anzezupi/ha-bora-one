"""Read-only codecs for BORA ovens (X BO).

Ovens use the newer ``generic.*`` / ``bs_sys.*`` service family instead of the
``bora.generic.*`` services of the cooktops. Transport, framing and pairing are
the same. Message layouts come from the pbandk descriptors of the BORA One
Android app; field numbers below follow those descriptors. Units are not
stated there: temperatures are assumed degC, humidity %, remaining times
seconds. The raw decoded values are kept for diagnostics so they can be checked.

No setter RPC is defined here.
"""

from __future__ import annotations

import struct
from typing import Any

from .wire import Message, ProtocolError

IDENTIFY_SERVICE = "/generic.identify.v1.IdentifyService/"
STATUS_SERVICE = "/generic.status.v1.DeviceStatusService/"
OVEN_STATUS_SERVICE = "/bs_sys.generic.status.v1.StatusService/"

STREAM_PATH = STATUS_SERVICE + "StreamDeviceStatusUpdates"

# generic.identify.v1.Product.bs_product
BS_PRODUCT_NAMES = {0: "unspecified", 1: "xbo", 2: "zbo"}
# generic.status.v1.OperatingState
OPERATING_STATES = {0: "unspecified", 1: "idle", 2: "running", 3: "paused"}
# bs_sys.generic.status.v1.Program
PROGRAMS = {
    0: "none",
    1: "manual_cooking",
    2: "automatic_cooking",
    3: "special_program",
    4: "cleaning",
}
# bs_sys.generic.status.v1.DoorState (0 = OPEN, 1 = CLOSE)
DOOR_OPEN = 0


def get_information() -> tuple[str, bytes]:
    """Read product, FD number and software versions."""
    return IDENTIFY_SERVICE + "GetSystemInformation", b""


def get_status() -> tuple[str, bytes]:
    """Read the device status including the oven overview."""
    return STATUS_SERVICE + "GetDeviceStatus", b""


def get_full_status() -> tuple[str, bytes]:
    """Read programme progress (optional, not every firmware may answer)."""
    return OVEN_STATUS_SERVICE + "GetFullOvenStatus", b""


def _float(message: Message, number: int) -> float | None:
    raw = message.value(number, 5)
    if raw is None:
        return None
    if len(raw) != 4:
        raise ProtocolError(f"Field {number} is not a float")
    return round(struct.unpack("<f", raw)[0], 1)


def _optional(message: Message, number: int, decoder) -> dict[str, Any] | None:
    if not message.has(number):
        return None
    return decoder(message.bytes(number))


def decode_information(body: bytes) -> dict[str, Any]:
    """Decode generic.identify.v1.SystemInformation."""
    message = Message(body)
    product = message.message(3)
    bs_product = product.int32(1)
    result: dict[str, Any] = {
        "fd": message.text(1),
        "e_nr": message.text(2),
        "bs_product": bs_product,
        "product_name": BS_PRODUCT_NAMES.get(bs_product, f"unknown_{bs_product}"),
    }
    if message.has(4):
        bs_sys = message.message(4)
        result.update(
            {
                "hmi_fd_nr": bs_sys.text(2),
                "io_fd_nr": bs_sys.text(3),
                "bundle_sw_version": bs_sys.text(4),
                "hmi_sw_version": bs_sys.text(5),
                "io_sw_version": bs_sys.text(6),
            }
        )
        if bs_sys.has(7):
            result["device_language"] = bs_sys.message(7).text(2)
    return result


def _core_temperature(body: bytes) -> dict[str, Any]:
    message = Message(body)
    return {
        "timestamp": message.uint(1),
        "target": _float(message, 2),
        "current": _float(message, 3),
        "sensors": [_float(message, number) for number in (4, 5, 6, 7)],
    }


def _xbo_overview(body: bytes) -> dict[str, Any]:
    message = Message(body)
    return {
        "remaining_filter_lifetime": message.int32(1),
        "filter_changed": message.uint(2),
        "filter_time_limit_warning": message.boolean(3),
        "core_temperature": _optional(message, 4, _core_temperature),
        "program_name": message.text(5),
    }


def decode_overview(body: bytes) -> dict[str, Any]:
    """Decode bs_sys.generic.status.v1.OvenOverview."""
    message = Message(body)
    program = message.int32(3)
    return {
        "demo_mode": message.boolean(1),
        "child_lock": message.boolean(2),
        "program": PROGRAMS.get(program, f"unknown_{program}"),
        "cooking_step": message.text(4),
        "target_temperature": message.int32(5),
        "current_temperature": message.int32(6),
        "target_humidity": message.uint(7),
        "current_humidity": message.uint(8),
        "step_remaining": message.int32(9),
        "xbo": _optional(message, 10, _xbo_overview),
        "has_hz": message.has(11),
        "program_remaining": message.int32(12),
        # proto3 drops the default (0 = OPEN): only a sent value is trusted.
        "door_open": (message.int32(13) == DOOR_OPEN) if message.has(13) else None,
    }


def decode_status(body: bytes) -> dict[str, Any]:
    """Decode generic.status.v1.DeviceStatus."""
    message = Message(body)
    state = message.int32(2)
    result: dict[str, Any] = {
        "turned_on": message.boolean(1),
        "operating_state": OPERATING_STATES.get(state, f"unknown_{state}"),
        "overview": None,
    }
    if message.has(3):
        operating = message.message(3)
        result["operating_hours"] = operating.int32(1)
        result["session_minutes"] = operating.int32(2)
    if message.has(4):
        oven_status = message.message(4)  # OvenStatus { OvenOverview overview = 1 }
        if oven_status.has(1):
            result["overview"] = decode_overview(oven_status.bytes(1))
    return result


def decode_full_status(body: bytes) -> dict[str, Any]:
    """Decode bs_sys.generic.status.v1.FullStatusResponse."""
    message = Message(body)
    return {
        "automatic_program_id": message.uint(1),
        "current_step": message.uint(2),
        "step_progress": message.uint(3),
        "program_progress": message.uint(4),
        "step_time_running": message.uint(5),
        "program_time_running": message.uint(6),
        "overview": _optional(message, 7, decode_overview),
        "seconds_until_start": message.uint(8),
    }
