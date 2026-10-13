"""API clients for BORA JOY.

BORA does not publish an API for the BORA JOY app. The cloud client below is a
scaffold: endpoint paths and the payload mapping in ``parse_cooktop`` have to be
confirmed by capturing the app's traffic (see docs/API_DISCOVERY.md).

Until then the demo client can be used to build dashboards and automations.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

import aiohttp

from .models import (
    AssistProgram,
    Cooktop,
    CookingZone,
    Extractor,
    ExtractorMode,
    ZonePosition,
    ZoneState,
)

# TODO(api-discovery): fill in once the BORA JOY traffic has been captured.
API_BASE_URL: str | None = None
LOGIN_PATH = "/auth/login"
APPLIANCES_PATH = "/appliances"
APPLIANCE_STATE_PATH = "/appliances/{appliance_id}/state"

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)


class BoraJoyError(Exception):
    """Base error for BORA JOY."""


class BoraJoyConnectionError(BoraJoyError):
    """The BORA cloud could not be reached."""


class BoraJoyAuthError(BoraJoyError):
    """Credentials were rejected."""


class BoraJoyApiNotAvailable(BoraJoyError):
    """The cloud API has not been implemented yet."""


class BoraJoyClient(ABC):
    """Common interface for all clients."""

    @abstractmethod
    async def async_login(self) -> None:
        """Authenticate; raise BoraJoyAuthError on bad credentials."""

    @abstractmethod
    async def async_get_cooktops(self) -> dict[str, Cooktop]:
        """Return all cooktops on the account, keyed by appliance id."""

    async def async_close(self) -> None:
        """Release resources."""


class BoraJoyCloudClient(BoraJoyClient):
    """Client for the BORA JOY cloud (scaffold, see module docstring)."""

    def __init__(
        self, session: aiohttp.ClientSession, username: str, password: str
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._username = username
        self._password = password
        self._token: str | None = None

    async def async_login(self) -> None:
        """Authenticate against the BORA cloud."""
        if API_BASE_URL is None:
            raise BoraJoyApiNotAvailable
        data = await self._request(
            "POST",
            LOGIN_PATH,
            json={"username": self._username, "password": self._password},
            authenticated=False,
        )
        self._token = data.get("access_token") or data.get("token")
        if not self._token:
            raise BoraJoyAuthError("No token in login response")

    async def async_get_cooktops(self) -> dict[str, Cooktop]:
        """Fetch the appliance list and the state of every cooktop."""
        if self._token is None:
            await self.async_login()
        appliances = await self._request("GET", APPLIANCES_PATH)
        items = appliances if isinstance(appliances, list) else appliances.get("items", [])
        cooktops: dict[str, Cooktop] = {}
        for item in items:
            appliance_id = str(item.get("id"))
            state = await self._request(
                "GET", APPLIANCE_STATE_PATH.format(appliance_id=appliance_id)
            )
            cooktop = parse_cooktop({**item, "state": state})
            cooktops[cooktop.appliance_id] = cooktop
        return cooktops

    async def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        retry_auth: bool = True,
        **kwargs: Any,
    ) -> Any:
        headers = kwargs.pop("headers", {})
        if authenticated and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            async with self._session.request(
                method,
                f"{API_BASE_URL}{path}",
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                **kwargs,
            ) as resp:
                if resp.status in (401, 403):
                    if authenticated and retry_auth:
                        await self.async_login()
                        return await self._request(
                            method, path, retry_auth=False, **kwargs
                        )
                    raise BoraJoyAuthError(f"HTTP {resp.status}")
                resp.raise_for_status()
                return await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise BoraJoyConnectionError(str(err)) from err


def _seconds(value: Any) -> int | None:
    if value in (None, 0, "0", ""):
        return None
    return int(value)


def _enum(enum_cls: type, value: Any, default: Any) -> Any:
    try:
        return enum_cls(str(value).lower())
    except ValueError:
        return default


def parse_cooktop(raw: dict[str, Any]) -> Cooktop:
    """Map a raw appliance payload onto a Cooktop.

    The key names are provisional and must be aligned with the real payload.
    Everything is read defensively so unknown payloads still produce a device.
    """
    state: dict[str, Any] = raw.get("state") or {}
    zones: dict[ZonePosition, CookingZone] = {}
    for zone_raw in state.get("zones", []):
        position = _enum(ZonePosition, zone_raw.get("position"), None)
        if position is None:
            continue
        zones[position] = CookingZone(
            position=position,
            state=_enum(ZoneState, zone_raw.get("state"), ZoneState.OFF),
            power_level=int(zone_raw.get("powerLevel") or 0),
            residual_heat=bool(zone_raw.get("residualHeat")),
            pan_detected=zone_raw.get("panDetected"),
            timer_remaining=_seconds(zone_raw.get("timerRemaining")),
            assist_program=_enum(
                AssistProgram, zone_raw.get("assist") or "none", AssistProgram.OTHER
            ),
            assist_target_temperature=zone_raw.get("assistTargetTemperature"),
            assist_target_reached=zone_raw.get("assistTargetReached"),
        )

    extractor: Extractor | None = None
    if (ext_raw := state.get("extractor")) is not None:
        extractor = Extractor(
            mode=_enum(ExtractorMode, ext_raw.get("mode"), ExtractorMode.MANUAL),
            fan_level=int(ext_raw.get("level") or 0),
            after_run_remaining=_seconds(ext_raw.get("afterRunRemaining")),
            filter_remaining_percent=ext_raw.get("filterRemaining"),
            filter_service_required=ext_raw.get("filterServiceRequired"),
        )

    return Cooktop(
        appliance_id=str(raw.get("id")),
        name=raw.get("name") or raw.get("model") or "BORA",
        model=raw.get("model"),
        serial_number=raw.get("serialNumber"),
        software_version=raw.get("softwareVersion"),
        hardware_version=raw.get("hardwareVersion"),
        online=bool(raw.get("online", True)),
        powered_on=bool(state.get("poweredOn")),
        child_lock=bool(state.get("childLock")),
        cleaning_lock=bool(state.get("cleaningLock")),
        paused=bool(state.get("paused")),
        short_timer_remaining=_seconds(state.get("shortTimerRemaining")),
        zones=zones,
        extractor=extractor,
        raw=raw,
    )


class BoraJoyDemoClient(BoraJoyClient):
    """Simulates a BORA X Pure cooking session on a 20 minute loop."""

    CYCLE = 1200

    def __init__(self, start: float | None = None) -> None:
        """Initialize the demo client."""
        self._start = time.monotonic() if start is None else start

    async def async_login(self) -> None:
        """Nothing to do."""

    async def async_get_cooktops(self) -> dict[str, Cooktop]:
        """Return the simulated cooktop."""
        cooktop = self.snapshot((time.monotonic() - self._start) % self.CYCLE)
        return {cooktop.appliance_id: cooktop}

    @staticmethod
    def snapshot(t: float) -> Cooktop:
        """Return the simulated state ``t`` seconds into the cycle."""
        t = int(t)
        zones = {pos: CookingZone(position=pos) for pos in ZonePosition}
        fl = zones[ZonePosition.FRONT_LEFT]
        fr = zones[ZonePosition.FRONT_RIGHT]
        rl = zones[ZonePosition.REAR_LEFT]

        # Front left: pasta, level 7 then 5, 10 minute zone timer.
        if 60 <= t < 660:
            fl.state = ZoneState.POWER_BOOST if t < 180 else ZoneState.ON
            fl.power_level = 9 if t < 180 else 5
            fl.pan_detected = True
            fl.timer_remaining = 660 - t
        elif 660 <= t < 900:
            fl.state, fl.residual_heat = ZoneState.RESIDUAL_HEAT, True

        # Front right: Assist Fry at 180 degC.
        if 180 <= t < 780:
            fr.state = ZoneState.ASSIST
            fr.power_level = 6
            fr.pan_detected = True
            fr.assist_program = AssistProgram.FRY
            fr.assist_target_temperature = 180
            fr.assist_target_reached = t >= 300
        elif 780 <= t < 1000:
            fr.state, fr.residual_heat = ZoneState.RESIDUAL_HEAT, True

        # Rear left: keep warm.
        if 360 <= t < 780:
            rl.state = ZoneState.KEEP_WARM
            rl.power_level = 1
            rl.pan_detected = True
        elif 780 <= t < 950:
            rl.state, rl.residual_heat = ZoneState.RESIDUAL_HEAT, True

        powered_on = 60 <= t < 780
        if powered_on:
            level = max(4, max(z.power_level for z in zones.values()))
            extractor = Extractor(mode=ExtractorMode.AUTOMATIC, fan_level=level)
        elif 780 <= t < 1080:
            extractor = Extractor(
                mode=ExtractorMode.AFTER_RUN,
                fan_level=3,
                after_run_remaining=1080 - t,
            )
        else:
            extractor = Extractor()
        extractor.filter_remaining_percent = 63
        extractor.filter_service_required = False

        return Cooktop(
            appliance_id="demo-xpure",
            name="BORA X Pure (demo)",
            model="X Pure",
            serial_number="DEMO0001",
            software_version="1.0.0",
            hardware_version="1",
            powered_on=powered_on,
            paused=500 <= t < 510,
            short_timer_remaining=(480 - t) if 240 <= t < 480 else None,
            zones=zones,
            extractor=extractor,
            raw={"demo": True, "cycle_seconds": t},
        )
