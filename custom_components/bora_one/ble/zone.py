"""Offline zone codecs reconstructed from BORA One 1.9.1 descriptors.

These functions perform no I/O. Setters return an RPC path and encoded body;
they do not establish that a device supports the operation. Capability checks
and physical validation belong to the caller. Timer values retain their raw
wire units. See bora-research/ZONE-STATIC.md for evidence and open semantics.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any

from .wire import Message, ProtocolError, blob, sint32, string, uint

SERVICE_PATH = "/bora.generic.zone.v1.ZoneService/"
GET_PATH = SERVICE_PATH + "GetZoneStatus"
SETTINGS_PATH = SERVICE_PATH + "GetZoneSettings"
DESCRIPTOR_PATH = SERVICE_PATH + "GetZoneValueDescriptor"
STREAM_PATH = SERVICE_PATH + "StreamZoneStatusUpdates"

KEEP_WARM_MODES = {0: "unspecified", 1: "melting", 2: "keep_warm", 3: "simmering"}
ZONE_MODE_TYPES = {0: "unspecified", 1: "power_level", 2: "csf", 3: "heat_retention", 4: "heat_up"}
CSF_TYPES = {
    0: "unspecified",
    1: "pasta",
    2: "frying",
    3: "grill",
    4: "steamer",
    5: "quickstart",
    6: "warming",
    7: "coffee",
    8: "hold",
}
CSF_PHASES = {0: "unspecified", 1: "preheat", 2: "confirmation_required", 3: "active", 4: "expired"}


def csf_phase_name(status: Mapping[str, Any]) -> str | None:
    """Describe the observed program, never a locally selected start draft."""
    if status.get("settings_present") is not True:
        return None
    if status.get("mode") in {"power_level", "heat_retention", "heat_up"}:
        return "inactive"
    if status.get("mode") != "csf":
        return None
    phase = (status.get("csf") or {}).get("phase")
    return None if phase is None else CSF_PHASES.get(phase, f"unknown_{phase}")


def csf_confirmation_required(status: Mapping[str, Any]) -> bool | None:
    """Unknown phases cannot be interpreted as confirmation already complete."""
    phase = csf_phase_name(status)
    if phase == "confirmation_required":
        return True
    if phase in {"inactive", "preheat", "active", "expired"}:
        return False
    return None


_CSF_FIELDS = {
    "csf_id": (1, False),
    "csf_index": (3, False),
    "csf_type": (4, False),
    "csf_type_target_value": (5, False),
    "csf_target_step_size": (7, False),
    "csf_target_min_val": (8, True),
    "csf_target_max_val": (9, True),
    "csf_settings": (10, False),
    "csf_timer_duration": (11, False),
}

type RPC = tuple[str, bytes]


def _integer(value: int, minimum: int, maximum: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ProtocolError(f"{name} must be an integer in {minimum}..{maximum}")
    return value


def _uid(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProtocolError("An observed nonempty zone UID is required")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as err:
        raise ProtocolError("Zone UID must be valid UTF-8") from err
    return value


def _uint32(message: Message, number: int) -> int:
    return _integer(message.uint(number), 0, 2**32 - 1, f"Field {number}")


def _presence(message: Message) -> tuple[int, ...]:
    return tuple(field.number for field in message.fields)


def decode_timer(body: bytes) -> dict[str, Any]:
    """Decode zone timer values in protocol milliseconds, preserving presence."""
    message = Message(body)
    return {
        "duration": _uint32(message, 1),
        "remaining": _uint32(message, 2),
        "running": message.boolean(3),
        "present_fields": _presence(message),
    }


def decode_csf_parameter(body: bytes) -> dict[str, Any]:
    """Decode CSF parameters, preserving unknown enum values and obsolete data."""
    message = Message(body)
    result = {
        name: message.int32(number) if signed or name == "csf_type" else _uint32(message, number)
        for name, (number, signed) in _CSF_FIELDS.items()
    }
    result["csf_time_to_set_obsolete"] = (
        decode_timer(message.bytes(6)) if message.has(6) else None
    )
    result["present_fields"] = _presence(message)
    return result


def decode_csf_status(body: bytes) -> dict[str, Any]:
    message = Message(body)
    return {
        "parameters": decode_csf_parameter(message.bytes(1)) if message.has(1) else None,
        "phase": message.int32(2),
        "present_fields": _presence(message),
    }


def decode_settings(body: bytes) -> dict[str, Any]:
    """Decode ZoneSettings, including setter replies; never merge stale modes."""
    message = Message(body)
    mode = message.message(2)
    result: dict[str, Any] = {
        "uid": message.text(1),
        "mode": "unknown" if mode.fields else None,
        "power_level": None,
        "keep_warm": None,
        "heat_up_power": None,
        "csf": None,
        "timer": decode_timer(message.bytes(3)) if message.has(3) else None,
        "bridged": message.boolean(4),
        "bridged_to_uid": message.text(5),
        "settings_fields": _presence(message),
        "mode_fields": _presence(mode),
    }
    match mode.oneof({1, 2, 3}):
        case 1:
            result.update(mode="power_level", power_level=mode.int32(1))
        case 2:
            result.update(mode="csf", csf=decode_csf_status(mode.bytes(2)))
        case 3:
            pure = mode.message(3)
            result["mode"] = "unknown"
            match pure.oneof({1, 2}):
                case 1:
                    result.update(mode="heat_retention", keep_warm=pure.message(1).int32(1))
                case 2:
                    result.update(mode="heat_up", heat_up_power=pure.message(2).int32(1))
    return result


def decode_status(body: bytes) -> dict[str, Any]:
    """Decode a GetZoneStatus reply or a validated stream CONTINUE body."""
    message = Message(body)
    result = decode_settings(message.bytes(1))
    result.update(
        residual_heat=message.boolean(2),
        pot_detection_active=message.boolean(3),
        settings_present=message.has(1),
        status_fields=_presence(message),
    )
    return result


def decode_bridged(body: bytes) -> dict[str, dict[str, Any] | None]:
    """SetBridged returns two optional ZoneSettings messages."""
    message = Message(body)
    return {
        "settings1": decode_settings(message.bytes(1)) if message.has(1) else None,
        "settings2": decode_settings(message.bytes(2)) if message.has(2) else None,
    }


def get_status(uid: str) -> RPC:
    return GET_PATH, string(1, _uid(uid))


def get_settings(uid: str) -> RPC:
    return SETTINGS_PATH, string(1, _uid(uid))


def get_descriptor() -> RPC:
    return DESCRIPTOR_PATH, b""


def _set_mode(uid: str, mode: bytes) -> RPC:
    return SERVICE_PATH + "SetMode", string(1, _uid(uid)) + blob(2, mode)


def _power(level: int, allowed_levels: Collection[int] | None) -> int:
    level = _integer(level, 0, 2**31 - 1, "Power level")
    if allowed_levels is not None and level not in allowed_levels:
        raise ProtocolError("Power level is not in the device descriptor")
    return level


def set_power(uid: str, level: int, *, allowed_levels: Collection[int] | None = None) -> RPC:
    """Select power, preserving explicit zero. Pass device levels to constrain it."""
    return _set_mode(uid, sint32(1, _power(level, allowed_levels)))


def set_keep_warm(uid: str, mode: int | str) -> RPC:
    """Encode a known retention mode; capability support is a caller check."""
    if isinstance(mode, str):
        mode = next((number for number, label in KEEP_WARM_MODES.items() if label == mode), -1)
    mode = _integer(mode, 1, 3, "Heat retention mode")
    return _set_mode(uid, blob(3, blob(1, uint(1, mode))))


def set_heat_up(uid: str, level: int, *, allowed_levels: Collection[int] | None = None) -> RPC:
    return _set_mode(uid, blob(3, blob(2, sint32(1, _power(level, allowed_levels)))))


def set_timer(
    uid: str,
    duration: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> RPC:
    """Encode raw duration. Zero/start/pause/reset behavior is not inferred."""
    duration = _integer(duration, 0, 2**32 - 1, "Timer duration")
    if minimum is not None:
        minimum = _integer(minimum, 0, 2**32 - 1, "Minimum duration")
    if maximum is not None:
        maximum = _integer(maximum, 0, 2**32 - 1, "Maximum duration")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ProtocolError("Timer minimum exceeds maximum")
    if minimum is not None and duration < minimum or maximum is not None and duration > maximum:
        raise ProtocolError("Timer duration is outside the device descriptor")
    return SERVICE_PATH + "SetTimer", string(1, _uid(uid)) + uint(2, duration)


def set_timer_state(uid: str, running: bool) -> RPC:
    """Encode reqState; the effect of false on firmware is not yet verified."""
    if not isinstance(running, bool):
        raise ProtocolError("Timer state must be a bool")
    return SERVICE_PATH + "SetTimerState", string(1, _uid(uid)) + uint(2, int(running))


def set_bridged(uid1: str, uid2: str) -> RPC:
    """Encode two distinct observed UIDs. An unbridge encoding is not proven."""
    uid1, uid2 = _uid(uid1), _uid(uid2)
    if uid1 == uid2:
        raise ProtocolError("Bridge requires two distinct zone UIDs")
    return SERVICE_PATH + "SetBridged", string(1, uid1) + string(2, uid2)


def encode_csf_parameter(parameters: Mapping[str, int]) -> bytes:
    """Encode explicit fields only; this does not prove a valid CSF workflow.

    No field 2 exists. Obsolete timer data and unknown csfSettings bit meanings
    are never synthesized. Descriptor ranges must be checked by the caller.
    """
    if not isinstance(parameters, Mapping) or not parameters:
        raise ProtocolError("CSF parameters must be a nonempty mapping")
    if unknown := parameters.keys() - _CSF_FIELDS.keys():
        raise ProtocolError(f"Unknown CSF parameter fields: {sorted(unknown, key=str)}")
    encoded = bytearray()
    for name, (number, signed) in _CSF_FIELDS.items():
        if name not in parameters:
            continue
        value = parameters[name]
        _integer(value, -(2**31) if signed else 0, 2**31 - 1 if signed else 2**32 - 1, name)
        if name == "csf_type" and value not in CSF_TYPES:
            raise ProtocolError("Unknown CSF type for a control request")
        encoded.extend(sint32(number, value) if signed else uint(number, value))
    return bytes(encoded)


def start_or_modify_csf(uid: str, parameters: Mapping[str, int]) -> RPC:
    """Build the known request schema, without assuming partial-patch semantics."""
    return (
        SERVICE_PATH + "StartOrModifyCsf",
        blob(1, encode_csf_parameter(parameters)) + string(2, _uid(uid)),
    )


def stop_csf(uid: str) -> RPC:
    return SERVICE_PATH + "StopCsf", string(1, _uid(uid))
