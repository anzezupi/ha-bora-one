"""Pure protocol codec for bora.generic.extractor.v1.ExtractorService.

Evidence: bora-research/CONTROL-STATIC.md and AFTER-RUN-STATIC.md. Request
constructors only return bytes; they do not connect or operate the appliance.
Only remainingAfterRun has a confirmed millisecond unit. Common Timer values
remain raw. Callers must enforce device-advertised capabilities and ranges.
"""

from __future__ import annotations

from collections.abc import Collection

from .wire import Message, ProtocolError, blob, sint32, uint

PREFIX = "/bora.generic.extractor.v1.ExtractorService/"
GET_PATH = PREFIX + "GetExtractorStatus"
STREAM_PATH = PREFIX + "StreamExtractorStatusUpdates"
SETTINGS_PATH = PREFIX + "GetExtractorSettings"
AFTER_RUN_MINUTES = {1: 20, 2: 15, 3: 10, 4: 30, 5: 40}
Request = tuple[str, bytes]


def _integer(value: int, minimum: int, maximum: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ProtocolError(f"{name} outside {minimum}..{maximum}")
    return value


def _boolean(value: bool, name: str) -> bool:
    if not isinstance(value, bool):
        raise ProtocolError(f"{name} must be a bool")
    return value


def _uint32(message: Message, number: int) -> int:
    return _integer(message.uint(number), 0, 0xFFFFFFFF, "uint32 field")


def _nested(message: Message, number: int) -> bytes | None:
    """Merge repeated occurrences of a singular embedded message."""
    if not message.has(number):
        return None
    message.messages(number)  # Validate all occurrences before merging.
    return b"".join(field.value for field in message.fields if field.number == number)


def decode_timer(body: bytes) -> dict:
    """Decode common.Timer, retaining unconfirmed units as raw values."""
    message = Message(body)
    return {
        "duration_raw": _uint32(message, 1),
        "remaining_raw": _uint32(message, 2),
        "running": message.boolean(3),
    }


def decode_mode(body: bytes) -> dict:
    message = Message(body)
    selected = message.oneof({1, 2})
    if selected == 1:
        Message(message.bytes(1))  # Validate the selected empty message.
        return {"mode": "auto"}
    if selected == 2:
        return {"mode": "power_level", "power_level": message.int32(2)}
    return {"mode": None}


def decode_settings(body: bytes) -> dict:
    message = Message(body)
    timer = _nested(message, 1)
    mode = _nested(message, 2)
    pure = _nested(message, 3)
    settings = {
        "egg_timer": None if timer is None else decode_timer(timer),
        "extractor_mode": None if mode is None else decode_mode(mode),
        "pure": None,
    }
    if pure is not None:
        value = Message(pure).int32(1)
        settings["pure"] = {
            "after_run_duration": value,
            "after_run_minutes": AFTER_RUN_MINUTES.get(value),
        }
    return settings


def decode_status(body: bytes) -> dict:
    message = Message(body)
    settings = _nested(message, 1)
    return {
        "extractor_settings": None if settings is None else decode_settings(settings),
        "remaining_after_run_ms": _uint32(message, 2),
    }


def get_status() -> Request:
    return GET_PATH, b""


def get_settings() -> Request:
    return SETTINGS_PATH, b""


def stream_status() -> Request:
    """Initial subscription; transport handles NONE and same-ID STOP."""
    return STREAM_PATH, b""


def set_power_level(power_level: int, *, allowed_levels: Collection[int] | None = None) -> Request:
    _integer(power_level, -(2**31), 2**31 - 1, "power level")
    if allowed_levels is not None and power_level not in allowed_levels:
        raise ProtocolError("Power level is not advertised by this device")
    # Keep the oneof tag for manual zero. Missing mode does not mean off.
    return PREFIX + "SetExtractorMode", blob(1, sint32(2, power_level))


def set_auto_mode() -> Request:
    return PREFIX + "SetExtractorMode", blob(1, blob(1, b""))


def set_after_run_duration(value: int, *, allowed_values: Collection[int] | None = None) -> Request:
    _integer(value, 1, 5, "after-run duration enum")
    if allowed_values is not None and value not in allowed_values:
        raise ProtocolError("After-run duration is not advertised by this device")
    return PREFIX + "SetDurationAfterRun", uint(1, value)


def stop_after_run() -> Request:
    return PREFIX + "StopAfterRun", b""


def set_egg_timer(duration_raw: int, *, minimum: int = 0, maximum: int = 0xFFFFFFFF) -> Request:
    """Encode the raw duration; no time-unit conversion is assumed."""
    _integer(duration_raw, 0, 0xFFFFFFFF, "timer duration")
    _integer(minimum, 0, 0xFFFFFFFF, "timer minimum")
    _integer(maximum, minimum, 0xFFFFFFFF, "timer maximum")
    if not minimum <= duration_raw <= maximum:
        raise ProtocolError("Timer duration is outside the advertised limits")
    return PREFIX + "SetEggTimer", uint(1, duration_raw)


def set_egg_timer_state(requested_state: bool) -> Request:
    """Exact requested-state bool; start/reset side effects remain unverified."""
    return PREFIX + "SetEggTimerState", uint(1, int(_boolean(requested_state, "timer state")))
