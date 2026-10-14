"""Read-only BORA metadata, capabilities and optional diagnostic RPC codecs.

These schemas come from BORA One 1.9.1 field descriptors. Units are left raw
where static descriptors do not establish them. No hardware I/O occurs here.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .wire import Message, ProtocolError, sint32

IDENTIFY_SERVICE = "/bora.generic.identify.v1.IdentifyService/"
WIFI_SERVICE = "/bora.generic.wifi.v1.WiFiProvisioningService/"

PRODUCT_NAMES = {
    0: "unspecified",
    1: "pure",
    2: "x_pure",
    3: "s_pure",
    4: "s_pure_plus",
    5: "m_pure",
    6: "x_pure_max",
    7: "m_pure_max",
}
WIFI_STATUS_NAMES = {
    0: "unspecified",
    1: "not_provisioned",
    2: "disconnected",
    3: "connecting",
    4: "wifi_connected",
    5: "unable_to_connect",
    6: "invalid_password",
    7: "dhcp_timeout",
    8: "no_internet",
    9: "internet_access",
    10: "wps_enabled",
    11: "wps_success",
    12: "wps_pin_retrieved",
    13: "wps_timeout",
    14: "wps_failed",
    15: "iot_provisioning_success_obsolete",
    16: "iot_provisioning_error",
    17: "iot_hub_connection_success",
}


# Exact BORA One 1.9.1 enum labels. System enum initializers span
# 0x1009ae0a0..0x1009bb79c; user initializers span 0x1009c5b0c..0x1009c7dc4.
# These describe recorded event categories, not current faults or measurements.
SYS_EVENT_NAMES = {
    0: "EVENT_TYPE_UNSPECIFIED",
    1: "EVENT_TYPE_BLE_MANAGER_STARTED",
    2: "EVENT_TYPE_BLE_MANAGER_STOPPED",
    3: "EVENT_TYPE_BLE_MANAGER_RESTART",
    4: "EVENT_TYPE_BLE_GAP_SECURITY_INITIATED",
    5: "EVENT_TYPE_BLE_SERVER_STARTED",
    6: "EVENT_TYPE_BLE_SERVER_STOPPED",
    7: "EVENT_TYPE_BLE_SERVER_DISCONNECT_ALL_CLIENTS",
    8: "EVENT_TYPE_BLE_SERVER_REMOVE_BONDED_DEVICES",
    9: "EVENT_TYPE_BLE_SERVER_UPDATE_DEVICE_INFO_SERVICE",
    10: "EVENT_TYPE_BLE_MTU_SET",
    11: "EVENT_TYPE_BLE_PEER_CONNECTED",
    12: "EVENT_TYPE_BLE_PEER_DISCONNECTED",
    13: "EVENT_TYPE_BLE_PEER_SUBSCRIBED",
    14: "EVENT_TYPE_BLE_PEER_UNSUBSCRIBED",
    15: "EVENT_TYPE_BLE_SETUP_CHARACTERISTIC",
    16: "EVENT_TYPE_BLE_CONNECTION_STATE",
    17: "EVENT_TYPE_BLE_RESERVE_1",
    18: "EVENT_TYPE_BLE_RESERVE_2",
    19: "EVENT_TYPE_BLE_RESERVE_3",
    20: "EVENT_TYPE_BLE_RESERVE_4",
    21: "EVENT_TYPE_IOT_STARTED",
    22: "EVENT_TYPE_IOT_STOPPED",
    23: "EVENT_TYPE_IOT_PROVISIONING_SUCCESSFUL",
    24: "EVENT_TYPE_IOT_PROVISIONING_FAILED",
    25: "EVENT_TYPE_IOT_REDO_PROVISIONING",
    26: "EVENT_TYPE_IOT_NOT_PROVISIONED",
    27: "EVENT_TYPE_IOT_SUBSCRIBED",
    28: "EVENT_TYPE_IOT_DELETED_PROVISIONING_DATA",
    29: "EVENT_TYPE_IOT_RESERVE_1",
    30: "EVENT_TYPE_IOT_RESERVE_2",
    31: "EVENT_TYPE_WIFI_STARTED",
    32: "EVENT_TYPE_WIFI_STOPPED",
    33: "EVENT_TYPE_WIFI_CONNECTED",
    34: "EVENT_TYPE_WIFI_CONNECTING",
    35: "EVENT_TYPE_WIFI_DISCONNECTING",
    36: "EVENT_TYPE_WIFI_DISCONNECTED",
    37: "EVENT_TYPE_WIFI_UNINTENDED_DISCONNECTED",
    38: "EVENT_TYPE_WIFI_SCAN_ENABLED",
    39: "EVENT_TYPE_WIFI_SCANNING",
    40: "EVENT_TYPE_WIFI_EVENT_SCAN_DONE",
    41: "EVENT_TYPE_WIFI_SCANNING_FAILURE",
    42: "EVENT_TYPE_WIFI_SCAN_STOP",
    43: "EVENT_TYPE_WIFI_SCAN_SET_TIMER_FAILED",
    44: "EVENT_TYPE_WIFI_SET_CREDENTIALS",
    45: "EVENT_TYPE_WIFI_DELETE_CREDENTIALS",
    46: "EVENT_TYPE_WIFI_DHCP_SET_TIMER_FAILED",
    47: "EVENT_TYPE_WIFI_DHCP_TIMEOUT",
    48: "EVENT_TYPE_WIFI_WPS_PBC_START",
    49: "EVENT_TYPE_WIFI_WPS_PIN_START",
    50: "EVENT_TYPE_WIFI_INTERNET_ACCESS_SET_TIMER_FAILED",
    51: "EVENT_TYPE_WIFI_INTERNET_ACCESS_TIMEOUT",
    52: "EVENT_TYPE_WIFI_INTERNET_ACCESS_CONFIRMED",
    53: "EVENT_TYPE_WIFI_EVENT_WPS_STOP",
    54: "EVENT_TYPE_WIFI_WPS_TIMEOUT",
    55: "EVENT_TYPE_WIFI_WPS_ENABLED",
    56: "EVENT_TYPE_WIFI_WPS_RETRIEVE_PIN",
    57: "EVENT_TYPE_WIFI_EVENT_STA_DISCONNECTED",
    58: "EVENT_TYPE_WIFI_EVENT_STA_CONNECTED",
    59: "EVENT_TYPE_WIFI_REASON_ASSOC_LEAVE",
    60: "EVENT_TYPE_WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT",
    61: "EVENT_TYPE_WIFI_REASON_AUTH_FAIL",
    62: "EVENT_TYPE_WIFI_REASON_AUTH_EXPIRE",
    63: "EVENT_TYPE_WIFI_REASON_802_1X_AUTH_FAILED",
    64: "EVENT_TYPE_WIFI_REASON_IE_IN_4WAY_DIFFERS",
    65: "EVENT_TYPE_WIFI_STATUS_INVALID_PASSWORD",
    66: "EVENT_TYPE_WIFI_STATUS_UNABLE_TO_CONNECT",
    67: "EVENT_TYPE_WIFI_EVENT_STA_WPS_ER_SUCCESS",
    68: "EVENT_TYPE_WIFI_EVENT_STA_WPS_ER_FAILED",
    69: "EVENT_TYPE_WIFI_EVENT_STA_WPS_ER_TIMEOUT",
    70: "EVENT_TYPE_WIFI_EVENT_STA_WPS_ER_PIN",
    71: "EVENT_TYPE_WIFI_EVENT_STA_WPS_ER_PBC_OVERLAP",
    72: "EVENT_TYPE_WIFI_EVENT_RESERVE_1",
    73: "EVENT_TYPE_WIFI_EVENT_RESERVE_2",
    74: "EVENT_TYPE_WIFI_EVENT_RESERVE_3",
    75: "EVENT_TYPE_WIFI_EVENT_RESERVE_4",
    76: "EVENT_TYPE_IP_EVENT_STA_GOT_IP",
    77: "EVENT_TYPE_IP_EVENT_RESERVE_1",
    78: "EVENT_TYPE_IP_EVENT_RESERVE_2",
    79: "EVENT_TYPE_IP_EVENT_RESERVE_3",
    80: "EVENT_TYPE_IP_EVENT_RESERVE_4",
    81: "EVENT_TYPE_ENERGY_CONNECTIVITY_ON",
    82: "EVENT_TYPE_ENERGY_CONNECTIVITY_OFF",
    83: "EVENT_TYPE_ENERGY_STANDBY_FOR",
    84: "EVENT_TYPE_ENERGY_STANDBY_UART_WAKEUP",
    85: "EVENT_TYPE_ENERGY_CONNECTIVITY_BLE_ONLY",
    86: "EVENT_TYPE_ENERGY_CONNECTIVITY_WIFI_ONLY",
    87: "EVENT_TYPE_ENERGY_DEVICE_FACTORY_RESET",
    88: "EVENT_TYPE_ENERGY_EVENT_RESERVE_1",
    89: "EVENT_TYPE_ENERGY_EVENT_RESERVE_2",
    90: "EVENT_TYPE_ENERGY_EVENT_RESERVE_3",
    91: "EVENT_TYPE_CSF_SAVED_PRESET_TO_NVS",
    92: "EVENT_TYPE_CSF_DELETED_PRESET_FROM_NVS",
    93: "EVENT_TYPE_CSF_EVENT_RESERVE_1",
    94: "EVENT_TYPE_CSF_EVENT_RESERVE_2",
    95: "EVENT_TYPE_CSF_EVENT_RESERVE_3",
    96: "EVENT_TYPE_PRODUCT",
    97: "EVENT_TYPE_BUS",
    98: "EVENT_TYPE_NO_HOST_DEVICE",
    99: "EVENT_TYPE_ESP_LOG",
}

USER_EVENT_NAMES = {
    0: "EVENT_TYPE_UNSPECIFIED",
    1: "EVENT_TYPE_COOKTOP_DATA_UPDATE",
    2: "EVENT_TYPE_COOKTOP_RESERVE_1",
    3: "EVENT_TYPE_COOKTOP_RESERVE_2",
    4: "EVENT_TYPE_COOKTOP_RESERVE_3",
    5: "EVENT_TYPE_EXTRACTOR_DATA_UPDATE",
    6: "EVENT_TYPE_EXTRACTOR_RESERVE_1",
    7: "EVENT_TYPE_EXTRACTOR_RESERVE_2",
    8: "EVENT_TYPE_EXTRACTOR_RESERVE_3",
    9: "EVENT_TYPE_ZONE_DATA_FL_UPDATE",
    10: "EVENT_TYPE_ZONE_DATA_BL_UPDATE",
    11: "EVENT_TYPE_ZONE_DATA_BR_UPDATE",
    12: "EVENT_TYPE_ZONE_DATA_FR_UPDATE",
    13: "EVENT_TYPE_CONNECTIVITY_UPDATE",
    14: "EVENT_TYPE_CONNECTIVITY_DATA_RESERVE_1",
    15: "EVENT_TYPE_CONNECTIVITY_DATA_RESERVE_2",
    16: "EVENT_TYPE_CONNECTIVITY_DATA_RESERVE_3",
}


def get_information() -> tuple[str, bytes]:
    """Read identity and per-part hardware/software metadata."""
    return IDENTIFY_SERVICE + "GetSystemInformation", b""


def get_descriptor() -> tuple[str, bytes]:
    """Read device-advertised ranges, labels and capabilities."""
    return IDENTIFY_SERVICE + "GetSystemValueRangeDescriptor", b""


def get_wifi_status() -> tuple[str, bytes]:
    """Read optional Wi-Fi diagnostics without changing provisioning."""
    return WIFI_SERVICE + "GetWiFiStatus", b""


def get_heartbeat_status() -> tuple[str, bytes]:
    """Read debug counters; this does not activate or send a heartbeat."""
    return "/bora.generic.debug.v1.DebugService/GetHeartbeatStatus", b""


def get_heartbeat_period() -> tuple[str, bytes]:
    return "/bora.generic.heartbeat.v1.HeartbeatService/GetHeartbeatPeriod", b""


def list_sys_events(number_of_results: int = 20) -> tuple[str, bytes]:
    """Read a bounded event history. Timestamp units remain unverified."""
    return _list_events("sysevent", "SysEvent", number_of_results)


def list_user_events(number_of_results: int = 20) -> tuple[str, bytes]:
    return _list_events("userevent", "UserEvent", number_of_results)


def _list_events(namespace: str, name: str, count: int) -> tuple[str, bytes]:
    # A conservative integration limit, not a claimed firmware limit. Avoid
    # relying on unknown zero/negative-count semantics or unbounded history.
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 100:
        raise ValueError("Event count must be an integer from 1 to 100")
    return (
        f"/bora.generic.logging.{namespace}.v1.{name}Service/List{name}s",
        sint32(1, count),
    )


def _uint32(message: Message, number: int) -> int:
    value = message.uint(number)
    if value >= 2**32:
        raise ProtocolError("Value outside uint32 range")
    return value


def _optional(message: Message, number: int, decode: Callable[[Message], Any]) -> Any | None:
    if not message.has(number):
        return None
    message.messages(number)  # Validate every occurrence, including earlier wire types.
    # Singular protobuf messages merge across occurrences; repeated child
    # entries concatenate and later scalar values override earlier ones.
    merged = b"".join(field.value for field in message.fields if field.number == number)
    return decode(Message(merged))


def _enum_values(message: Message, number: int) -> list[int]:
    """Decode protobuf enum repetitions in both packed and unpacked form."""
    result: list[int] = []
    for field in message.fields:
        if field.number != number:
            continue
        if field.wire == 0:
            values = [field.value]
        elif field.wire == 2:
            values = []
            offset = 0
            packed = field.value
            while offset < len(packed):
                value = 0
                for shift in range(0, 70, 7):
                    if offset >= len(packed):
                        raise ProtocolError("Truncated packed enum")
                    byte = packed[offset]
                    offset += 1
                    if shift == 63 and byte > 1:
                        raise ProtocolError("Packed enum overflow")
                    value |= (byte & 127) << shift
                    if byte < 128:
                        values.append(value)
                        break
                else:
                    raise ProtocolError("Packed enum too long")
        else:
            raise ProtocolError("Expected packed or unpacked enum")
        for value in values:
            value &= 0xFFFFFFFF
            result.append(value - 2**32 if value & 0x80000000 else value)
    return result


def decode_information(body: bytes) -> dict[str, Any]:
    message = Message(body)
    product = message.int32(1)
    return {
        "product": product,
        "product_name": PRODUCT_NAMES.get(product, f"unknown_{product}"),
        "fd": message.text(2),
        "e_nr": message.text(3),
        "pure": _optional(message, 4, _product_descriptor),
        "cm_identifier": message.text(6),
        "cm_hw_version_no": message.text(7),
        "cm_sw_version_no": message.text(8),
        "cm_serial_number": message.text(9),
    }


def _product_descriptor(message: Message) -> dict[str, Any]:
    return {
        "product_meta_data": [
            {
                "part_identifier": part.text(1),
                "device_hw_version_no": part.text(2),
                "device_sw_version_no": part.text(3),
                "serial_number": part.text(4),
            }
            for part in message.messages(1)
        ]
    }


def _power_level(message: Message) -> dict[str, Any]:
    return {"index": message.int32(1), "level_name": message.text(2)}


def _timer_limits(message: Message) -> dict[str, int]:
    return {"min_duration": _uint32(message, 1), "max_duration": _uint32(message, 2)}


def _zone_uids(message: Message) -> dict[str, str]:
    return {
        name: message.text(number)
        for number, name in enumerate(
            (
                "left_down_zone_uid",
                "left_upper_zone_uid",
                "right_upper_zone_uid",
                "right_down_zone_uid",
                "mid_back_zone_uid",
                "mid_front_zone_uid",
            ),
            start=1,
        )
    }


def _zone_mode_descriptor(message: Message) -> dict[str, Any]:
    return {"u_id": message.text(1), "supported_csf": _enum_values(message, 2)}


def _zone_descriptor(message: Message) -> dict[str, Any]:
    return {
        "timer_limits": _optional(message, 1, _timer_limits),
        "zone_mode_types": _enum_values(message, 2),
        "power_levels": [_power_level(item) for item in message.messages(3)],
        "variable_heat_retention_support": message.boolean(4),
        "zone_mode_descriptor": [_zone_mode_descriptor(item) for item in message.messages(5)],
    }


def _extractor_descriptor(message: Message) -> dict[str, Any]:
    return {
        "extractor_mode_types": _enum_values(message, 1),
        "power_levels": [_power_level(item) for item in message.messages(2)],
        "type": message.int32(3),
        "egg_timer_limits": _optional(message, 4, _timer_limits),
        "pure": _optional(
            message,
            5,
            lambda item: {
                "after_run_durations": _enum_values(item, 1),
            },
        ),
    }


def _csf_descriptor(message: Message) -> dict[str, Any]:
    return {
        "index_range": _optional(
            message,
            1,
            lambda item: {
                "min": _uint32(item, 1),
                "max": _uint32(item, 2),
            },
        ),
        "timer_limit": _optional(message, 2, _timer_limits),
        "type_descriptors": [
            {
                "csf_type": item.int32(1),
                "number_of_phases": _uint32(item, 2),
                "csf_type_min_step_size": _uint32(item, 3),
                "csf_type_max_step_size": _uint32(item, 4),
                "csf_type_min_val": _uint32(item, 5),
                "csf_type_max_val": _uint32(item, 6),
            }
            for item in message.messages(3)
        ],
    }


def _pure_descriptor(message: Message) -> dict[str, Any]:
    return {
        "filter_unit_types": [
            {"index": item.int32(1), "filter": item.text(2), "lifetime": item.int32(3)}
            for item in message.messages(1)
        ]
    }


def decode_descriptor(body: bytes) -> dict[str, Any]:
    """Decode all known SystemValueRangeDescriptor fields, preserving labels.

    Lists contain advertised options only. Missing message fields are None;
    missing scalars inside a present message keep protobuf defaults.
    """
    message = Message(body)
    return {
        "zone_uids": _optional(message, 1, _zone_uids),
        "zone_descriptor": _optional(message, 2, _zone_descriptor),
        "extractor_descriptor": _optional(message, 3, _extractor_descriptor),
        "signal_volume_levels": [_power_level(item) for item in message.messages(4)],
        "csf_descriptor": _optional(message, 5, _csf_descriptor),
        "pure": _optional(message, 6, _pure_descriptor),
    }


def decode_wifi_status(body: bytes) -> dict[str, Any] | None:
    """Decode GetWiFiStatusResponse (field 1 wraps the status message)."""
    return _optional(Message(body), 1, _wifi_status)


def decode_wifi_status_update(body: bytes) -> dict[str, Any]:
    """Decode the direct WiFiStatus message sent by its stream."""
    return _wifi_status(Message(body))


def _wifi_status(message: Message) -> dict[str, Any]:
    status = message.int32(1)
    return {
        "connection_status": status,
        "connection_status_name": WIFI_STATUS_NAMES.get(status, f"unknown_{status}"),
        "ssid": message.text(2),
        "mac_address": message.bytes(3).hex(":"),
        # Do not guess device-specific IPv4 byte order from its uint32 field.
        "ip_v4_address": _uint32(message, 4),
        "posix_time_zone": message.text(5),
    }


def decode_heartbeat_status(body: bytes) -> dict[str, Any]:
    message = Message(body)
    return {
        "heartbeat_request_active": message.boolean(1),
        "heartbeat_counter": _uint32(message, 2),
        "heartbeat_period": _uint32(message, 3),
    }


def decode_heartbeat_period(body: bytes) -> dict[str, int]:
    return {"heartbeat_period": _uint32(Message(body), 1)}


def decode_event(body: bytes) -> dict[str, int]:
    """Decode a direct SysEvent or UserEvent without assuming timestamp units."""
    message = Message(body)
    return {"timestamp": _uint32(message, 1), "event_type": message.int32(2)}


def decode_events(body: bytes) -> list[dict[str, int]]:
    """Both event-list responses have repeated events at field 1."""
    return [
        {"timestamp": _uint32(item, 1), "event_type": item.int32(2)}
        for item in Message(body).messages(1)
    ]


def _named_event(event: dict[str, int], names: dict[int, str]) -> dict[str, int | str]:
    event_type = event["event_type"]
    return {**event, "event_type_name": names.get(event_type, f"unknown_{event_type}")}


def decode_sys_event(body: bytes) -> dict[str, int | str]:
    """Decode a direct SysEvent with its exact SDK category label."""
    return _named_event(decode_event(body), SYS_EVENT_NAMES)


def decode_user_event(body: bytes) -> dict[str, int | str]:
    """Decode a direct UserEvent with its exact SDK category label."""
    return _named_event(decode_event(body), USER_EVENT_NAMES)


def decode_sys_events(body: bytes) -> list[dict[str, int | str]]:
    """Label a SysEvent list, retaining raw timestamps and wire order.

    No timestamp unit, chronological order or current fault is inferred.
    """
    return [_named_event(event, SYS_EVENT_NAMES) for event in decode_events(body)]


def decode_user_events(body: bytes) -> list[dict[str, int | str]]:
    """Label a UserEvent list without interpreting timestamps or wire order."""
    return [_named_event(event, USER_EVENT_NAMES) for event in decode_events(body)]


def get_saved_csf() -> tuple[str, bytes]:
    """Read saved cooking presets; support must be established per device."""
    return "/bora.generic.csf.v1.CsfService/GetSavedCsf", b""


def decode_saved_csf(body: bytes) -> list[dict[str, Any]]:
    from .zone import decode_csf_parameter

    result = []
    for field in Message(body).fields:
        if field.number == 1:
            if field.wire != 2:
                raise ProtocolError("Expected repeated CSF parameter message")
            result.append(decode_csf_parameter(field.value))
    return result


def decode_zone_descriptor(body: bytes) -> dict[str, Any]:
    """Decode the direct response to ZoneService.GetZoneValueDescriptor."""
    return _zone_descriptor(Message(body))
