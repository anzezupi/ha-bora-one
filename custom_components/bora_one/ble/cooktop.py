"""Offline codec for bora.generic.cooktop.v1 and nested bora.pure messages.

See bora-research/CONTROL-STATIC.md for descriptor addresses and limitations.
These constructors do not validate model support or imply live verification.
No filter-time unit, filter-reset meaning, or super-simple enable/disable
semantics are assumed. The caller owns capability checks and command dispatch.
"""

from __future__ import annotations

from collections.abc import Collection

from .wire import Message, ProtocolError, blob, sint32, uint

PREFIX = "/bora.generic.cooktop.v1.CooktopService/"
GET_PATH = PREFIX + "GetCooktopStatus"
STREAM_PATH = PREFIX + "StreamCooktopStatusUpdates"
SETTINGS_PATH = PREFIX + "GetCooktopSettings"
CHILD_LOCK_NAMES = {0: "unspecified", 1: "locked", 2: "temp_unlocked", 3: "unlocked"}
CONNECTIVITY_NAMES = {0: "unspecified", 1: "off", 2: "ble_only", 3: "wifi_only", 4: "on"}
SENSITIVITY_NAMES = {0: "unspecified", 1: "slow", 2: "default", 3: "fast"}
MAX_OP_DURATION_NAMES = {0: "unspecified", 1: "default", 2: "high", 3: "max"}
EXTRACTION_TYPE_NAMES = {0: "unspecified", 1: "circulation", 2: "extraction"}
POWER_MANAGEMENT_NAMES = {0: "unspecified", 1: "1phase_16a", 2: "1phase_20a", 3: "full_performance"}
# Exact SDK labels; these are diagnostics, not descriptions of causes.
ERROR_CODE_NAMES = {
    0: "UNSPECIFIED",
    1: "E_1_LEFT_FRONT",
    2: "E_2_LEFT_FRONT",
    3: "E_3_LEFT_FRONT",
    4: "E_4_LEFT_FRONT",
    5: "E_5_LEFT_FRONT",
    6: "E_6_LEFT_FRONT",
    7: "E_7_LEFT_FRONT",
    8: "E_8_LEFT_FRONT",
    9: "E_9_LEFT_FRONT",
    10: "E_A_LEFT_FRONT",
    11: "H_LEFT_FRONT",
    12: "E_1_LEFT_BACK",
    13: "E_2_LEFT_BACK",
    14: "E_3_LEFT_BACK",
    15: "E_4_LEFT_BACK",
    16: "E_5_LEFT_BACK",
    17: "E_6_LEFT_BACK",
    18: "E_7_LEFT_BACK",
    19: "E_8_LEFT_BACK",
    20: "E_9_LEFT_BACK",
    21: "E_A_LEFT_BACK",
    22: "H_LEFT_BACK",
    23: "E_1_RIGHT_BACK",
    24: "E_2_RIGHT_BACK",
    25: "E_3_RIGHT_BACK",
    26: "E_4_RIGHT_BACK",
    27: "E_5_RIGHT_BACK",
    28: "E_6_RIGHT_BACK",
    29: "E_7_RIGHT_BACK",
    30: "E_8_RIGHT_BACK",
    31: "E_9_RIGHT_BACK",
    32: "E_A_RIGHT_BACK",
    33: "H_RIGHT_BACK",
    34: "E_1_RIGHT_FRONT",
    35: "E_2_RIGHT_FRONT",
    36: "E_3_RIGHT_FRONT",
    37: "E_4_RIGHT_FRONT",
    38: "E_5_RIGHT_FRONT",
    39: "E_6_RIGHT_FRONT",
    40: "E_7_RIGHT_FRONT",
    41: "E_8_RIGHT_FRONT",
    42: "E_9_RIGHT_FRONT",
    43: "E_A_RIGHT_FRONT",
    44: "H_RIGHT_FRONT",
    45: "E_03",
    46: "E_07",
    47: "E_13",
    48: "E_21",
    49: "E_22",
    50: "E_35",
    51: "E_58",
    52: "E_90",
    53: "E_91",
    54: "E_92",
    55: "E_93",
    56: "U_400",
    57: "E_0_C",
    58: "E_E",
    59: "E_B_LEFT_FRONT",
    60: "E_B_LEFT_BACK",
    61: "E_B_RIGHT_BACK",
    62: "E_B_RIGHT_FRONT",
    63: "E_1_MID_BACK",
    64: "E_2_MID_BACK",
    65: "E_3_MID_BACK",
    66: "E_4_MID_BACK",
    67: "E_5_MID_BACK",
    68: "E_6_MID_BACK",
    69: "E_7_MID_BACK",
    70: "E_8_MID_BACK",
    71: "E_9_MID_BACK",
    72: "E_A_MID_BACK",
    73: "H_MID_BACK",
    74: "E_B_MID_BACK",
    75: "E_1_MID_FRONT",
    76: "E_2_MID_FRONT",
    77: "E_3_MID_FRONT",
    78: "E_4_MID_FRONT",
    79: "E_5_MID_FRONT",
    80: "E_6_MID_FRONT",
    81: "E_7_MID_FRONT",
    82: "E_8_MID_FRONT",
    83: "E_9_MID_FRONT",
    84: "E_A_MID_FRONT",
    85: "H_MID_FRONT",
    86: "E_B_MID_FRONT",
}

_DISABLED_FIELDS = (
    "cleaning_lock_disabled",
    "pause_disabled",
    "warming_disabled",
    "timer_disabled",
    "hot_key_disabled",
)
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


def _nested(message: Message, number: int) -> bytes | None:
    if not message.has(number):
        return None
    message.messages(number)  # Validate every occurrence and embedded payload.
    return b"".join(field.value for field in message.fields if field.number == number)


def _optional(message: Message, number: int, decoder):
    data = _nested(message, number)
    return None if data is None else decoder(data)


def decode_disabled_functions(body: bytes) -> dict:
    message = Message(body)
    return {name: message.boolean(index) for index, name in enumerate(_DISABLED_FIELDS, 1)}


def decode_super_simple_mode(body: bytes) -> dict:
    message = Message(body)
    return {
        "active": message.boolean(1),
        "disabled_functions": _optional(message, 2, decode_disabled_functions),
    }


def decode_dealer_menu(body: bytes) -> dict:
    message = Message(body)
    return {
        "extraction_type": message.int32(1),
        "power_management": message.int32(2),
        "demo_mode": message.boolean(3),
    }


def decode_pure_settings(body: bytes) -> dict:
    message = Message(body)
    return {
        "clean_lock": message.boolean(1),
        "permanent_child_lock": message.boolean(2),
        "sensitivity": message.int32(3),
        "automatic_pot_detection": message.boolean(4),
        "max_op_duration": message.int32(5),
        "super_simple_mode": _optional(message, 6, decode_super_simple_mode),
        "remaining_filter_lifetime_raw": _integer(
            message.uint(7), 0, 0xFFFFFFFF, "filter lifetime"
        ),
        "dealer_menu_config": _optional(message, 8, decode_dealer_menu),
    }


def filter_change_required(settings: dict) -> bool | None:
    """Apply the app's zero threshold only to known recirculation settings.

    The app compares its Int with 1 using signed arithmetic. UInt32 values
    with the high bit set have no established lifetime meaning, so stay
    unknown. This establishes a warning, not hours, percent or filter type.
    """
    if (settings.get("dealer_menu_config") or {}).get("extraction_type") != 1:
        return None
    remaining = settings.get("remaining_filter_lifetime_raw")
    if (
        isinstance(remaining, int) and not isinstance(remaining, bool)
        and 0 <= remaining <= 0x7FFFFFFF
    ):
        return remaining == 0
    return None


def decode_settings(body: bytes) -> dict:
    message = Message(body)
    return {
        "pause": message.boolean(1),
        "childlock_setting": message.int32(2),
        "connectivity_setting": message.int32(3),
        "signal_volume": message.int32(4),
        "pure": _optional(message, 5, decode_pure_settings),
    }


def _signed_enum(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - 2**32 if value & 0x80000000 else value


def decode_errors(body: bytes) -> list[int]:
    """Preserve ordered packed/unpacked ErrorCode values, including unknowns."""
    result = []
    for field in Message(body).fields:
        if field.number != 1:
            continue
        if field.wire == 0:
            result.append(_signed_enum(field.value))
        elif field.wire == 2:
            offset = 0
            while offset < len(field.value):
                value = 0
                for shift in range(0, 70, 7):
                    if offset >= len(field.value):
                        raise ProtocolError("Truncated packed error code")
                    byte = field.value[offset]
                    offset += 1
                    if shift == 63 and byte > 1:
                        raise ProtocolError("Packed error code overflow")
                    value |= (byte & 127) << shift
                    if byte < 128:
                        result.append(_signed_enum(value))
                        break
                else:
                    raise ProtocolError("Packed error code too long")
        else:
            raise ProtocolError("Invalid wire type for error code")
    return result


def decode_status(body: bytes) -> dict:
    message = Message(body)
    return {
        "cooktop_settings": _optional(message, 1, decode_settings),
        "ready_for_sleep": message.boolean(2),
        "primary_device_factory_reset": message.boolean(3),
        "primary_device_restart": message.boolean(4),
        "primary_device_send_connect_state_req": message.boolean(5),
        "recovery_state_active": message.boolean(6),
        "current_primary_device_errors": _optional(message, 7, decode_errors),
    }


def get_status() -> Request:
    return GET_PATH, b""


def get_settings() -> Request:
    return SETTINGS_PATH, b""


def stream_status() -> Request:
    return STREAM_PATH, b""


def set_paused(paused: bool) -> Request:
    return PREFIX + "SetPaused", uint(1, int(_boolean(paused, "paused")))


def set_child_lock(setting: int) -> Request:
    return PREFIX + "SetChildLock", uint(1, _integer(setting, 1, 3, "child-lock enum"))


def set_signal_volume(index: int, *, allowed_levels: Collection[int] | None = None) -> Request:
    _integer(index, -(2**31), 2**31 - 1, "signal-volume index")
    if allowed_levels is not None and index not in allowed_levels:
        raise ProtocolError("Signal volume is not advertised by this device")
    return PREFIX + "SetSignalVolume", sint32(1, index)


def _pure_request(field: int, body: bytes) -> Request:
    return PREFIX + "SetSpecificCooktopSetting", blob(1, blob(field, body))


def set_cleaning_lock(enabled: bool) -> Request:
    return _pure_request(1, uint(1, int(_boolean(enabled, "cleaning lock"))))


def set_permanent_child_lock(enabled: bool) -> Request:
    return _pure_request(2, uint(1, int(_boolean(enabled, "permanent child lock"))))


def set_touch_sensitivity(value: int) -> Request:
    return _pure_request(3, uint(1, _integer(value, 1, 3, "sensitivity enum")))


def set_led_test(requested: bool) -> Request:
    """Wire-level LED-test request; effects have not been physically tested."""
    return _pure_request(4, uint(1, int(_boolean(requested, "LED-test request"))))


def set_automatic_pot_detection(enabled: bool) -> Request:
    return _pure_request(5, uint(1, int(_boolean(enabled, "automatic pot detection"))))


def set_maximum_op_duration(value: int) -> Request:
    return _pure_request(6, uint(1, _integer(value, 1, 3, "maximum-operation-duration enum")))


def set_super_simple_disabled_functions(
    *,
    cleaning_lock_disabled: bool,
    pause_disabled: bool,
    warming_disabled: bool,
    timer_disabled: bool,
    hot_key_disabled: bool,
) -> Request:
    """Encode the entire group; this is not a partial patch or enable toggle."""
    values = (
        cleaning_lock_disabled,
        pause_disabled,
        warming_disabled,
        timer_disabled,
        hot_key_disabled,
    )
    group = b"".join(
        uint(index, int(_boolean(value, name)))
        for index, (name, value) in enumerate(zip(_DISABLED_FIELDS, values, strict=True), 1)
    )
    return _pure_request(7, blob(1, group))


def set_filter_unit() -> Request:
    """Exact empty request; filter selection/reset semantics remain unknown."""
    return _pure_request(8, b"")


def restart_connectivity_module() -> Request:
    """Construct a restart command, not a connectivity setting toggle."""
    return PREFIX + "RestartConnectivityModule", b""
