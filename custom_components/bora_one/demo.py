"""Simulated BORA X Pure for trying the integration without an appliance."""

from __future__ import annotations

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

CYCLE = 1200
"""The simulated cooking session repeats every 20 minutes."""

DEMO_POSITIONS = (
    ZonePosition.FRONT_LEFT,
    ZonePosition.BACK_LEFT,
    ZonePosition.BACK_RIGHT,
    ZonePosition.FRONT_RIGHT,
)


def demo_snapshot(t: float) -> Cooktop:
    """Return the simulated state ``t`` seconds into the cycle.

    The cooktop is switched off (offline) for the first minute and after the
    after-run has finished, like a real X Pure that turns Bluetooth off.
    """
    t = int(t) % CYCLE
    zones = {pos: CookingZone(position=pos) for pos in DEMO_POSITIONS}
    fl = zones[ZonePosition.FRONT_LEFT]
    fr = zones[ZonePosition.FRONT_RIGHT]
    bl = zones[ZonePosition.BACK_LEFT]

    # Front left: pasta water, boost then level 5, 10 minute zone timer.
    if 60 <= t < 660:
        boost = t < 180
        fl.state = ZoneState.POWER_BOOST if boost else ZoneState.ON
        fl.power_level = 9 if boost else 5
        fl.timer_remaining = 660 - t
    elif 660 <= t < 900:
        fl.state, fl.residual_heat = ZoneState.RESIDUAL_HEAT, True

    # Front right: Assist Fry at 180 degC.
    if 180 <= t < 780:
        fr.state = ZoneState.ASSIST
        fr.power_level = None
        fr.assist_program = AssistProgram.FRYING
        fr.assist_target_temperature = 180
        fr.assist_phase = AssistPhase.PREHEAT if t < 300 else AssistPhase.ACTIVE
    elif 780 <= t < 1000:
        fr.state, fr.residual_heat = ZoneState.RESIDUAL_HEAT, True

    # Back left: keep warm.
    if 360 <= t < 780:
        bl.state = ZoneState.KEEP_WARM
        bl.power_level = None
        bl.keep_warm_mode = KeepWarmMode.KEEP_WARM
    elif 780 <= t < 950:
        bl.state, bl.residual_heat = ZoneState.RESIDUAL_HEAT, True

    if 60 <= t < 780:
        extractor = Extractor(mode=ExtractorMode.AUTOMATIC, fan_level=None)
    elif 780 <= t < 1080:
        extractor = Extractor(
            mode=ExtractorMode.AFTER_RUN, fan_level=1, after_run_remaining=1080 - t
        )
    else:
        extractor = Extractor()
    extractor.after_run_duration = 30
    extractor.filter_service_required = False
    extractor.filter_lifetime_raw = 7234

    return Cooktop(
        appliance_id="demo",
        name="BORA X Pure (demo)",
        model="X Pure",
        serial_number="DEMO0001",
        software_version="3.0.9",
        online=60 <= t < 1100,
        paused=500 <= t < 510,
        zones=zones,
        extractor=extractor,
        raw={"demo": True, "cycle_seconds": t},
    )
