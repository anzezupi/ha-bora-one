"""Data update coordinator for BORA JOY."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BoraJoyAuthError, BoraJoyClient, BoraJoyError
from .const import (
    CONF_MODE,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEMO_SCAN_INTERVAL,
    DOMAIN,
    EVENT_BORA_JOY,
    MODE_DEMO,
)
from .models import AssistProgram, Cooktop, ExtractorMode, ZoneState

_LOGGER = logging.getLogger(__name__)

type BoraJoyConfigEntry = ConfigEntry[BoraJoyCoordinator]


class BoraJoyCoordinator(DataUpdateCoordinator[dict[str, Cooktop]]):
    """Polls all cooktops on the account."""

    config_entry: BoraJoyConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: BoraJoyConfigEntry, client: BoraJoyClient
    ) -> None:
        """Initialize the coordinator."""
        if entry.data[CONF_MODE] == MODE_DEMO:
            interval = DEMO_SCAN_INTERVAL
        else:
            interval = timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=interval,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Cooktop]:
        try:
            cooktops = await self.client.async_get_cooktops()
        except BoraJoyAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except BoraJoyError as err:
            raise UpdateFailed(str(err)) from err

        if self.data:
            for appliance_id, new in cooktops.items():
                if (old := self.data.get(appliance_id)) is not None:
                    self._fire_events(old, new)
        return cooktops

    def _fire(self, cooktop: Cooktop, event_type: str, **data: object) -> None:
        self.hass.bus.async_fire(
            EVENT_BORA_JOY,
            {
                "appliance_id": cooktop.appliance_id,
                "name": cooktop.name,
                "type": event_type,
                **data,
            },
        )

    def _fire_events(self, old: Cooktop, new: Cooktop) -> None:
        """Fire bus events on meaningful state transitions."""
        if not old.is_cooking and new.is_cooking:
            self._fire(new, "cooking_started")
        elif old.is_cooking and not new.is_cooking:
            self._fire(new, "cooking_finished")

        for position, zone in new.zones.items():
            prev = old.zones.get(position)
            if prev is None:
                continue
            if prev.timer_remaining and zone.timer_remaining is None and not zone.is_active:
                self._fire(new, "zone_timer_finished", zone=position.value)
            if (
                zone.assist_program is AssistProgram.FRY
                and zone.assist_target_reached
                and not prev.assist_target_reached
            ):
                self._fire(
                    new,
                    "assist_target_reached",
                    zone=position.value,
                    temperature=zone.assist_target_temperature,
                )
            if prev.state is ZoneState.ASSIST and zone.state is not ZoneState.ASSIST:
                self._fire(
                    new,
                    "assist_finished",
                    zone=position.value,
                    program=prev.assist_program.value,
                )

        if old.short_timer_remaining and new.short_timer_remaining is None:
            self._fire(new, "short_timer_finished")

        if old.extractor and new.extractor:
            if (
                old.extractor.mode is ExtractorMode.AFTER_RUN
                and new.extractor.mode is ExtractorMode.OFF
            ):
                self._fire(new, "after_run_finished")
            if new.extractor.filter_service_required and not old.extractor.filter_service_required:
                self._fire(new, "filter_service_required")
