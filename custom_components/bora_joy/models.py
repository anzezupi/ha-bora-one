"""Data models for BORA cooktops.

These models are intentionally independent of Home Assistant so they can be
unit-tested and reused. The cloud client maps raw API payloads onto them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ZonePosition(StrEnum):
    """Physical position of a cooking zone (BORA Pure / X Pure layout)."""

    FRONT_LEFT = "front_left"
    REAR_LEFT = "rear_left"
    FRONT_RIGHT = "front_right"
    REAR_RIGHT = "rear_right"


class ZoneState(StrEnum):
    """Operating state of a single cooking zone."""

    OFF = "off"
    ON = "on"
    POWER_BOOST = "power_boost"
    KEEP_WARM = "keep_warm"
    ASSIST = "assist"
    PAUSED = "paused"
    NO_PAN = "no_pan"
    RESIDUAL_HEAT = "residual_heat"


class AssistProgram(StrEnum):
    """BORA Assist programmes."""

    NONE = "none"
    FRY = "fry"
    BOIL = "boil"
    OTHER = "other"


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
    power_level: int = 0
    """Power level 0-9. Power boost (P) is reported as 9 with state POWER_BOOST."""
    residual_heat: bool = False
    pan_detected: bool | None = None
    timer_remaining: int | None = None
    """Seconds left on the cooking zone timer, None when no timer is running."""
    assist_program: AssistProgram = AssistProgram.NONE
    assist_target_temperature: int | None = None
    """Fry target temperature in degC (120-220 in 20 degC steps)."""
    assist_target_reached: bool | None = None

    @property
    def is_active(self) -> bool:
        """Return True when the zone is heating."""
        return self.state in (
            ZoneState.ON,
            ZoneState.POWER_BOOST,
            ZoneState.KEEP_WARM,
            ZoneState.ASSIST,
        )


@dataclass(slots=True)
class Extractor:
    """State of the integrated cooktop extractor."""

    mode: ExtractorMode = ExtractorMode.OFF
    fan_level: int = 0
    """Fan level 0-9. Power boost (P) is reported as 9 with mode POWER_BOOST."""
    after_run_remaining: int | None = None
    """Seconds left of the automatic after-run, None when not running."""
    filter_remaining_percent: int | None = None
    """Odour filter life left (recirculation models only)."""
    filter_service_required: bool | None = None

    @property
    def is_running(self) -> bool:
        """Return True when the fan is running."""
        return self.mode is not ExtractorMode.OFF and (
            self.fan_level > 0 or self.mode is ExtractorMode.AFTER_RUN
        )


@dataclass(slots=True)
class Cooktop:
    """A connected BORA cooktop (with or without extractor)."""

    appliance_id: str
    name: str
    model: str | None = None
    serial_number: str | None = None
    software_version: str | None = None
    hardware_version: str | None = None
    online: bool = True
    powered_on: bool = False
    child_lock: bool = False
    cleaning_lock: bool = False
    paused: bool = False
    short_timer_remaining: int | None = None
    """Seconds left on the egg-timer (short-time timer)."""
    zones: dict[ZonePosition, CookingZone] = field(default_factory=dict)
    extractor: Extractor | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)
    """Untouched payload from the API, exposed via diagnostics."""

    @property
    def active_zone_count(self) -> int:
        """Return the number of heating zones."""
        return sum(1 for zone in self.zones.values() if zone.is_active)

    @property
    def is_cooking(self) -> bool:
        """Return True when at least one zone is heating."""
        return self.active_zone_count > 0
