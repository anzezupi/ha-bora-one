"""Map decoded BORA Bluetooth status onto the integration models."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .ble import cooktop as cooktop_codec, zone as zone_codec
from .models import (
    AssistPhase,
    AssistProgram,
    Cooktop,
    CookingZone,
    Extractor,
    ExtractorMode,
    KeepWarmMode,
    ZonePosition,
    ZoneState,
)

# Descriptor field -> physical position.
ZONE_UID_FIELDS = {
    "left_down_zone_uid": ZonePosition.FRONT_LEFT,
    "left_upper_zone_uid": ZonePosition.BACK_LEFT,
    "right_upper_zone_uid": ZonePosition.BACK_RIGHT,
    "right_down_zone_uid": ZonePosition.FRONT_RIGHT,
    "mid_back_zone_uid": ZonePosition.MID_BACK,
    "mid_front_zone_uid": ZonePosition.MID_FRONT,
}
KEEP_WARM_MODES = {1: KeepWarmMode.MELTING, 2: KeepWarmMode.KEEP_WARM, 3: KeepWarmMode.SIMMERING}
PRODUCT_MODELS = {
    "pure": "Pure",
    "x_pure": "X Pure",
    "s_pure": "S Pure",
    "s_pure_plus": "S Pure Plus",
    "m_pure": "M Pure",
    "x_pure_max": "X Pure Max",
    "m_pure_max": "M Pure Max",
}


def zone_positions(descriptor: dict[str, Any]) -> dict[str, ZonePosition]:
    """Return zone UID -> position for the zones the appliance advertises."""
    uids = descriptor.get("zone_uids") or {}
    return {uids[key]: position for key, position in ZONE_UID_FIELDS.items() if uids.get(key)}


def _level(levels: list[dict[str, Any]], index: int | None) -> tuple[int | None, bool]:
    """Translate a power index into (numeric level, is_boost) using descriptor labels."""
    if index is None:
        return None, False
    numeric = [int(item["level_name"]) for item in levels if item["level_name"].isdigit()]
    for item in levels:
        if item["index"] == index:
            label = item["level_name"]
            if label.isdigit():
                return int(label), False
            return (max(numeric) if numeric else index), True
    return index, False


def map_zone(
    position: ZonePosition, status: dict[str, Any], levels: list[dict[str, Any]]
) -> CookingZone:
    """Build a CookingZone from a decoded ZoneStatus."""
    zone = CookingZone(position=position, residual_heat=bool(status.get("residual_heat")))
    timer = status.get("timer")
    if timer and timer.get("running") and timer.get("remaining"):
        zone.timer_remaining = round(timer["remaining"] / 1000)

    match status.get("mode"):
        case "power_level":
            level, boost = _level(levels, status.get("power_level"))
            zone.power_level = level
            if boost:
                zone.state = ZoneState.POWER_BOOST
            elif level:
                zone.state = ZoneState.ON
        case "heat_retention":
            zone.state = ZoneState.KEEP_WARM
            zone.power_level = None
            zone.keep_warm_mode = KEEP_WARM_MODES.get(status.get("keep_warm"))
        case "heat_up":
            zone.state = ZoneState.HEAT_UP
            zone.power_level, _ = _level(levels, status.get("heat_up_power"))
        case "csf":
            csf = status.get("csf") or {}
            parameters = csf.get("parameters") or {}
            program = zone_codec.CSF_TYPES.get(parameters.get("csf_type", 0), "other")
            zone.state = ZoneState.ASSIST
            zone.power_level = None
            zone.assist_program = (
                AssistProgram(program) if program in set(AssistProgram) else AssistProgram.OTHER
            )
            phase = zone_codec.CSF_PHASES.get(csf.get("phase", 0), "unspecified")
            zone.assist_phase = AssistPhase(phase) if phase != "unspecified" else AssistPhase.NONE
            if zone.assist_program is AssistProgram.FRYING:
                zone.assist_target_temperature = parameters.get("csf_type_target_value") or None
        case _:
            zone.power_level = None

    if zone.state is ZoneState.OFF and zone.residual_heat:
        zone.state = ZoneState.RESIDUAL_HEAT
    return zone


def map_extractor(
    status: dict[str, Any], levels: list[dict[str, Any]], pure_settings: dict[str, Any] | None
) -> Extractor:
    """Build an Extractor from a decoded ExtractorStatus and cooktop settings."""
    extractor = Extractor()
    settings = status.get("extractor_settings") or {}
    mode = settings.get("extractor_mode") or {}
    remaining_ms = status.get("remaining_after_run_ms") or 0

    if mode.get("mode") == "auto":
        extractor.mode = ExtractorMode.AUTOMATIC
        extractor.fan_level = None
    else:
        level, boost = _level(levels, mode.get("power_level"))
        extractor.fan_level = level
        if remaining_ms:
            extractor.mode = ExtractorMode.AFTER_RUN
        elif boost:
            extractor.mode = ExtractorMode.POWER_BOOST
        elif level:
            extractor.mode = ExtractorMode.MANUAL
    if remaining_ms:
        extractor.after_run_remaining = round(remaining_ms / 1000)
    if pure := settings.get("pure"):
        extractor.after_run_duration = pure.get("after_run_minutes")
    if pure_settings:
        extractor.filter_service_required = cooktop_codec.filter_change_required(pure_settings)
        if extractor.filter_service_required is not None:
            extractor.filter_lifetime_raw = pure_settings.get("remaining_filter_lifetime_raw")
    return extractor


def offline_cooktop(
    base: Cooktop, positions: Iterable[ZonePosition], has_extractor: bool
) -> Cooktop:
    """Return the state shown while Bluetooth is unreachable.

    X Pure only drops Bluetooth after it has been switched off and the
    extractor has stopped, so zones and fan are reported as off.
    """
    return Cooktop(
        appliance_id=base.appliance_id,
        name=base.name,
        model=base.model,
        serial_number=base.serial_number,
        software_version=base.software_version,
        hardware_version=base.hardware_version,
        online=False,
        zones={position: CookingZone(position=position) for position in positions},
        extractor=Extractor() if has_extractor else None,
    )


def map_cooktop(
    appliance_id: str,
    name: str,
    information: dict[str, Any],
    descriptor: dict[str, Any],
    state: dict[str, Any],
) -> Cooktop:
    """Build a Cooktop from the connected appliance's decoded data."""
    cooktop_status = state.get("cooktop") or {}
    settings = cooktop_status.get("cooktop_settings") or {}
    pure_settings = settings.get("pure") or None

    product = information.get("product_name")
    cooktop = Cooktop(
        appliance_id=appliance_id,
        name=name,
        model=PRODUCT_MODELS.get(product, product) if product else None,
        serial_number=information.get("cm_serial_number") or None,
        software_version=information.get("cm_sw_version_no") or None,
        hardware_version=information.get("cm_hw_version_no") or None,
        paused=bool(settings.get("pause")),
        child_lock=settings.get("childlock_setting") == 1,
        cleaning_lock=bool(pure_settings and pure_settings.get("clean_lock")),
        errors=[
            cooktop_codec.ERROR_CODE_NAMES.get(code, f"unknown_{code}")
            for code in cooktop_status.get("current_primary_device_errors") or []
        ],
        raw={"information": information, "descriptor": descriptor, "state": state},
    )

    zone_levels = (descriptor.get("zone_descriptor") or {}).get("power_levels", [])
    statuses = state.get("zones") or {}
    for uid, position in zone_positions(descriptor).items():
        if (status := statuses.get(uid)) is not None:
            cooktop.zones[position] = map_zone(position, status, zone_levels)

    if (extractor_descriptor := descriptor.get("extractor_descriptor")) and (
        extractor_status := state.get("extractor")
    ) is not None:
        cooktop.extractor = map_extractor(
            extractor_status, extractor_descriptor.get("power_levels", []), pure_settings
        )
    return cooktop
