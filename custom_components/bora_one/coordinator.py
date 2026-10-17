"""Coordinator for BORA One: Bluetooth push updates, periodic reads and events."""

from __future__ import annotations

import asyncio
import logging
import time

from bleak.exc import BleakError

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .adapter import create_connection
from .ble.transport import BoraError, PairingRequired
from .ble.wire import ProtocolError
from .const import (
    CONF_MODE,
    CONNECT_TIMEOUT,
    DEMO_UPDATE_INTERVAL,
    DOMAIN,
    EVENT_BORA_ONE,
    MODE_DEMO,
    UPDATE_INTERVAL,
)
from .demo import DEMO_POSITIONS, demo_snapshot
from .device import BoraBleDevice
from .mapper import map_cooktop, offline_cooktop
from .models import AssistProgram, Cooktop, ExtractorMode, ZonePosition, ZoneState

_LOGGER = logging.getLogger(__name__)

CONF_ZONES = "zones"
CONF_EXTRACTOR = "extractor"
CONF_MODEL = "model"

type BoraOneConfigEntry = ConfigEntry[BoraOneCoordinator]

CONNECTION_ERRORS = (BoraError, BleakError, ProtocolError, TimeoutError)


class BoraOneCoordinator(DataUpdateCoordinator[Cooktop]):
    """Keeps the cooktop state; offline is a normal state, not an error."""

    config_entry: BoraOneConfigEntry

    def __init__(self, hass: HomeAssistant, entry: BoraOneConfigEntry) -> None:
        """Initialize the coordinator."""
        self.demo = entry.data[CONF_MODE] == MODE_DEMO
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=DEMO_UPDATE_INTERVAL if self.demo else UPDATE_INTERVAL,
        )
        self.connection_enabled = True
        if self.demo:
            self.positions: tuple[ZonePosition, ...] = DEMO_POSITIONS
            self.has_extractor = True
        else:
            self.positions = tuple(ZonePosition(p) for p in entry.data.get(CONF_ZONES, []))
            self.has_extractor = entry.data.get(CONF_EXTRACTOR, True)
        self._identity = Cooktop(
            appliance_id=entry.unique_id or entry.entry_id,
            name=entry.title,
            model=entry.data.get(CONF_MODEL),
        )
        self._demo_start = time.monotonic()
        self._closed = False
        self.address: str | None = entry.data.get(CONF_ADDRESS)
        self.device: BoraBleDevice | None = None
        if not self.demo:
            self.device = BoraBleDevice(
                create_connection(hass, self.address, disconnected=self._on_disconnect),
                updated=self._on_push,
            )

    # Data sources

    def _offline(self) -> Cooktop:
        return offline_cooktop(self._identity, self.positions, self.has_extractor)

    def _current(self) -> Cooktop:
        assert self.device is not None
        cooktop = map_cooktop(
            self._identity.appliance_id,
            self._identity.name,
            self.device.information,
            self.device.descriptor,
            self.device.state,
        )
        for attr in ("model", "serial_number", "software_version", "hardware_version"):
            if value := getattr(cooktop, attr):
                setattr(self._identity, attr, value)
            else:
                setattr(cooktop, attr, getattr(self._identity, attr))
        return cooktop

    async def _async_update_data(self) -> Cooktop:
        if self.demo:
            new = demo_snapshot(time.monotonic() - self._demo_start)
        else:
            new = await self._async_update_ble()
        self._fire_events(new)
        return new

    async def _async_update_ble(self) -> Cooktop:
        assert self.device is not None and self.address is not None
        if self._closed or not self.connection_enabled:
            if self.device.connected:
                await self.device.disconnect()
            return self._offline()

        if self.device.connected:
            try:
                await self.device.refresh()
            except CONNECTION_ERRORS as err:
                _LOGGER.warning("Reading BORA status failed, disconnecting: %r", err)
                await self.device.disconnect()
                return self._offline()
            return self._current()

        # Only try to connect while the cooktop is advertising (switched on).
        if bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True) is None:
            return self._offline()
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):
                await self.device.connect()
        except PairingRequired as err:
            raise ConfigEntryAuthFailed("Pair Home Assistant with the cooktop again") from err
        except CONNECTION_ERRORS as err:
            _LOGGER.info("Could not connect to BORA: %r", err)
            await self.device.disconnect()
            return self._offline()
        cooktop = self._current()
        _LOGGER.info(
            "Connected to BORA %s: %d active zone(s), extractor %s",
            cooktop.model or "",
            cooktop.active_zone_count,
            cooktop.extractor.mode.value if cooktop.extractor else "n/a",
        )
        self._update_device_registry(cooktop)
        return cooktop

    @callback
    def _on_push(self) -> None:
        """A status stream delivered an update."""
        if self._closed or self.device is None or not self.device.connected:
            return
        new = self._current()
        _LOGGER.debug(
            "BORA update: %s",
            {p.value: (z.state.value, z.power_level) for p, z in new.zones.items()},
        )
        self._fire_events(new)
        self.async_set_updated_data(new)

    @callback
    def _on_disconnect(self) -> None:
        """The connection dropped (normally: cooktop switched off) or failed."""
        if self._closed or self.device is None:
            return
        connection = self.device.connection
        _LOGGER.info(
            "BORA connection ended (protocol error: %s, last RPC error: %s)",
            connection.last_protocol_error,
            connection.last_rpc_error,
        )
        # A failed stream leaves the Bluetooth link open; close it so the
        # cooktop is free and we can reconnect.
        self.config_entry.async_create_task(
            self.hass, self.device.disconnect(), "bora_one_disconnect"
        )
        new = self._offline()
        self._fire_events(new)
        self.async_set_updated_data(new)

    @callback
    def async_on_advertisement(self) -> None:
        """The cooktop is advertising; connect right away if we are offline."""
        if (
            not self._closed
            and self.connection_enabled
            and self.device is not None
            and not self.device.connected
            and self.data is not None
            and not self.data.online
        ):
            self.config_entry.async_create_task(
                self.hass, self.async_request_refresh(), "bora_one_connect"
            )

    async def async_set_connection_enabled(self, enabled: bool) -> None:
        """Hold or release the Bluetooth connection (lets the BORA One app connect)."""
        self.connection_enabled = enabled
        await self.async_refresh()

    async def async_shutdown(self) -> None:
        """Close the Bluetooth connection."""
        self._closed = True
        if self.device is not None:
            await self.device.disconnect()
        await super().async_shutdown()

    def _update_device_registry(self, cooktop: Cooktop) -> None:
        registry = dr.async_get(self.hass)
        for device in dr.async_entries_for_config_entry(registry, self.config_entry.entry_id):
            registry.async_update_device(
                device.id,
                model=cooktop.model,
                serial_number=cooktop.serial_number,
                sw_version=cooktop.software_version,
                hw_version=cooktop.hardware_version,
            )

    # Events

    def _fire(self, cooktop: Cooktop, event_type: str, **data: object) -> None:
        self.hass.bus.async_fire(
            EVENT_BORA_ONE,
            {"device_id": cooktop.appliance_id, "name": cooktop.name, "type": event_type, **data},
        )

    def _fire_events(self, new: Cooktop) -> None:
        """Fire bus events on meaningful state transitions."""
        if (old := self.data) is None:
            return
        if not old.online and new.online:
            self._fire(new, "switched_on")
        elif old.online and not new.online:
            self._fire(new, "switched_off")
        if not old.is_cooking and new.is_cooking:
            self._fire(new, "cooking_started")
        elif old.is_cooking and not new.is_cooking:
            self._fire(new, "cooking_finished")

        for position, zone in new.zones.items():
            if (prev := old.zones.get(position)) is None:
                continue
            if prev.timer_remaining and zone.timer_remaining is None and not zone.is_active:
                self._fire(new, "zone_timer_finished", zone=position.value)
            if (
                zone.assist_program is AssistProgram.FRYING
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
                    new, "assist_finished", zone=position.value, program=prev.assist_program.value
                )

        if old.extractor and new.extractor:
            if (
                old.extractor.mode is ExtractorMode.AFTER_RUN
                and new.extractor.mode is ExtractorMode.OFF
            ):
                self._fire(new, "after_run_finished")
            if new.extractor.filter_service_required and not old.extractor.filter_service_required:
                self._fire(new, "filter_service_required")
