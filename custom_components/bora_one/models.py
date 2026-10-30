"""Data models for BORA cooktops and ovens.

These models are independent of Home Assistant. ``mapper.py`` builds them from
the decoded Bluetooth status; ``demo.py`` builds them from a simulation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ZonePosition(StrEnum):
    """Physical position of a cooking zone, named like the BORA zone UIDs."""

    FRONT_LEFT = "front_left"
    BACK_LEFT = "back_left"
    BACK_RIGHT = "back_right"
    FRONT_RIGHT = "front_right"
    MID_BACK = "mid_back"
    MID_FRONT = "mid_front"


class ZoneState(StrEnum):
    """Operating state of a single cooking zone."""

    OFF = "off"
    ON = "on"
    POWER_BOOST = "power_boost"
    KEEP_WARM = "keep_warm"
    HEAT_UP = "heat_up"
    ASSIST = "assist"
    RESIDUAL_HEAT = "residual_heat"


class AssistProgram(StrEnum):
    """BORA Assist (cooking support function) programmes."""

    NONE = "none"
    PASTA = "pasta"
    FRYING = "frying"
    GRILL = "grill"
    STEAMER = "steamer"
    QUICKSTART = "quickstart"
    WARMING = "warming"
    COFFEE = "coffee"
    HOLD = "hold"
    OTHER = "other"


class AssistPhase(StrEnum):
    """Phase of a running Assist programme."""

    NONE = "none"
    PREHEAT = "preheat"
    CONFIRMATION_REQUIRED = "confirmation_required"
    ACTIVE = "active"
    EXPIRED = "expired"


class KeepWarmMode(StrEnum):
    """Heat retention level."""

    MELTING = "melting"
    KEEP_WARM = "keep_warm"
    SIMMERING = "simmering"


class ExtractorMode(StrEnum):
    """Operating mode of the cooktop extractor."""

    OFF = "off"
    MANUAL = "manual"
    AUTOMATIC = "automatic"
    POWER_BOOST = "power_boost"
    AFTER_RUN = "after_run"


@dataclass(slots=True)
class CookingZone:
    """State of one cooking zone."""

    position: ZonePosition
    state: ZoneState = ZoneState.OFF
    power_level: int | None = 0
    """Power level 0-9. Power boost (P) is reported as 9 with state POWER_BOOST."""
    residual_heat: bool = False
    timer_remaining: int | None = None
    """Seconds left on a running zone timer, None when no timer is running."""
    keep_warm_mode: KeepWarmMode | None = None
    assist_program: AssistProgram = AssistProgram.NONE
    assist_phase: AssistPhase = AssistPhase.NONE
    assist_target_temperature: int | None = None
    """Frying target temperature in degC."""

    @property
    def is_active(self) -> bool:
        """Return True when the zone is heating."""
        return self.state in (
            ZoneState.ON,
            ZoneState.POWER_BOOST,
            ZoneState.KEEP_WARM,
            ZoneState.HEAT_UP,
            ZoneState.ASSIST,
        )

    @property
    def assist_target_reached(self) -> bool | None:
        """Return True once a frying Assist has reached its temperature."""
        if self.assist_program is not AssistProgram.FRYING:
            return None
        return self.assist_phase in (
            AssistPhase.CONFIRMATION_REQUIRED,
            AssistPhase.ACTIVE,
            AssistPhase.EXPIRED,
        )


@dataclass(slots=True)
class Extractor:
    """State of the integrated cooktop extractor."""

    mode: ExtractorMode = ExtractorMode.OFF
    fan_level: int | None = 0
    """Fan level; None in automatic mode. Boost (P) reports the highest level."""
    after_run_remaining: int | None = None
    """Seconds left of the automatic after-run, None when not running."""
    after_run_duration: int | None = None
    """Configured after-run duration in minutes."""
    filter_service_required: bool | None = None
    """Odour filter change needed (recirculation models only)."""
    filter_lifetime_raw: int | None = None
    """Remaining odour filter lifetime as reported, unit not confirmed."""

    @property
    def is_running(self) -> bool:
        """Return True when the fan is running."""
        if self.mode in (ExtractorMode.AUTOMATIC, ExtractorMode.AFTER_RUN):
            return True
        return bool(self.fan_level)


class OvenProgram(StrEnum):
    """Kind of programme an oven runs."""

    NONE = "none"
    MANUAL_COOKING = "manual_cooking"
    AUTOMATIC_COOKING = "automatic_cooking"
    SPECIAL_PROGRAM = "special_program"
    CLEANING = "cleaning"


class OvenOperatingState(StrEnum):
    """Operating state reported by an oven."""

    UNSPECIFIED = "unspecified"
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"


@dataclass(slots=True)
class Oven:
    """State of a BORA oven (X BO)."""

    turned_on: bool = False
    operating_state: OvenOperatingState = OvenOperatingState.UNSPECIFIED
    program: OvenProgram = OvenProgram.NONE
    program_name: str | None = None
    cooking_step: str | None = None
    current_temperature: int | None = None
    """Cooking chamber temperature in degC (unit assumed)."""
    target_temperature: int | None = None
    current_humidity: int | None = None
    """Cooking chamber humidity in % (unit assumed)."""
    target_humidity: int | None = None
    core_temperature: float | None = None
    """Core temperature probe in degC, None when not reported."""
    target_core_temperature: float | None = None
    step_remaining: int | None = None
    """Seconds left of the current cooking step (unit assumed)."""
    program_remaining: int | None = None
    """Seconds left of the whole programme (unit assumed)."""
    program_progress: int | None = None
    """Programme progress in %, from the optional full status."""
    door_open: bool | None = None
    filter_warning: bool | None = None
    filter_lifetime_raw: int | None = None
    operating_hours: int | None = None

    @property
    def is_running(self) -> bool:
        """Return True while a programme runs (paused counts as running)."""
        return self.operating_state in (OvenOperatingState.RUNNING, OvenOperatingState.PAUSED)


@dataclass(slots=True)
class Cooktop:
    """A BORA appliance: a cooktop, or an oven when ``oven`` is set."""

    appliance_id: str
    name: str
    model: str | None = None
    serial_number: str | None = None
    software_version: str | None = None
    hardware_version: str | None = None
    online: bool = True
    """Connected over Bluetooth. X Pure turns Bluetooth off shortly after
    being switched off, so offline normally means switched off."""
    switched_off: bool = False
    """Connected, but every zone is reported unavailable: the cooktop was
    switched off and has not dropped Bluetooth yet."""
    paused: bool = False
    child_lock: bool = False
    cleaning_lock: bool = False
    errors: list[str] = field(default_factory=list)
    zones: dict[ZonePosition, CookingZone] = field(default_factory=dict)
    extractor: Extractor | None = None
    oven: Oven | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)
    """Decoded protocol data, exposed via diagnostics."""

    @property
    def active_zone_count(self) -> int:
        """Return the number of heating zones."""
        return sum(1 for zone in self.zones.values() if zone.is_active)

    @property
    def is_cooking(self) -> bool:
        """Return True when at least one zone is heating or the oven runs a programme."""
        if self.oven is not None:
            return self.oven.is_running
        return self.active_zone_count > 0

    @property
    def has_residual_heat(self) -> bool:
        """Return True when any zone is still hot."""
        return any(zone.residual_heat for zone in self.zones.values())
