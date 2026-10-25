"""Integration tests against the simulated cooktop (recorded X Pure responses)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import time

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.bora_one.const import CONF_MODE, DOMAIN, EVENT_BORA_ONE, MODE_BLUETOOTH

from .bora_peer import (
    EXTRACTOR,
    EXTRACTOR_AFTER_RUN,
    EXTRACTOR_OFF,
    IDENTIFY,
    ZONE,
    FakeBoraPeer,
    zone_status,
)
from .conftest import ADDRESS, FakeBluetooth

P = "bora_x_pure"
ZONE_STREAM = ZONE + "StreamZoneStatusUpdates"
EXTRACTOR_STREAM = EXTRACTOR + "StreamExtractorStatusUpdates"


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDRESS,
        title="BORA X Pure",
        data={
            CONF_MODE: MODE_BLUETOOTH,
            CONF_ADDRESS: ADDRESS,
            "zones": ["front_left", "back_left", "back_right", "front_right"],
            "extractor": True,
            "model": "X Pure",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _state(hass: HomeAssistant, entity_id: str) -> str:
    return hass.states.get(entity_id).state


async def test_entities_from_recorded_cooktop(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer
) -> None:
    """States come from real X Pure responses; only reads are sent."""
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    assert _state(hass, f"sensor.{P}_status") == "cooking"
    assert _state(hass, f"sensor.{P}_active_zones") == "1"
    assert _state(hass, f"sensor.{P}_back_left_power_level") == "7"
    assert _state(hass, f"sensor.{P}_back_left_state") == "on"
    assert _state(hass, f"binary_sensor.{P}_back_left_active") == "on"
    assert _state(hass, f"sensor.{P}_front_left_state") == "off"
    assert _state(hass, f"sensor.{P}_front_left_power_level") == "0"
    assert _state(hass, f"sensor.{P}_extractor_mode") == "manual"
    assert _state(hass, f"sensor.{P}_extractor_fan_level") == "3"
    assert _state(hass, f"sensor.{P}_after_run_duration") == "30"
    assert _state(hass, f"sensor.{P}_error_code") == "none"
    assert _state(hass, f"binary_sensor.{P}_bluetooth_connection") == "on"
    assert _state(hass, f"binary_sensor.{P}_child_lock") == "off"
    assert _state(hass, f"binary_sensor.{P}_odour_filter_change") == "off"
    assert _state(hass, f"binary_sensor.{P}_extractor_running") == "on"
    assert _state(hass, f"switch.{P}_allow_bluetooth_connection") == "on"

    [device] = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert (DOMAIN, ADDRESS) in device.identifiers
    assert device.model == "X Pure"
    assert device.sw_version == "3.0.9"

    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert len(entities) == (8 + 4 * 7) + (9 + 4 * 3) + 1

    methods = {path.rsplit("/", 1)[1] for path in peer.requests}
    assert all(m.startswith(("Get", "Stream")) for m in methods), methods

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not peer.is_connected


async def test_push_updates_and_events(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer
) -> None:
    """Stream updates change entities immediately and fire events."""
    await _setup(hass)
    events = async_capture_events(hass, EVENT_BORA_ONE)

    peer.push(ZONE_STREAM, zone_status("back_left", power=0, residual_heat=True))
    await hass.async_block_till_done()
    assert _state(hass, f"sensor.{P}_back_left_state") == "residual_heat"
    assert _state(hass, f"binary_sensor.{P}_residual_heat") == "on"
    assert _state(hass, f"sensor.{P}_status") == "standby"
    assert [e.data["type"] for e in events] == ["cooking_finished"]

    peer.push(EXTRACTOR_STREAM, EXTRACTOR_AFTER_RUN)
    await hass.async_block_till_done()
    assert _state(hass, f"sensor.{P}_extractor_mode") == "after_run"
    assert _state(hass, f"sensor.{P}_status") == "after_run"
    end = dt_util.parse_datetime(_state(hass, f"sensor.{P}_after_run_end"))
    assert abs(end - (dt_util.utcnow() + timedelta(seconds=1279))) < timedelta(seconds=15)


async def test_frying_assist_and_timer(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer
) -> None:
    """Assist Fry phases and zone timers are mapped."""
    await _setup(hass)
    events = async_capture_events(hass, EVENT_BORA_ONE)

    peer.push(ZONE_STREAM, zone_status("front_right", frying=(180, 1)))
    peer.push(ZONE_STREAM, zone_status("front_left", power=5, timer_remaining_ms=120000))
    await hass.async_block_till_done()
    assert _state(hass, f"sensor.{P}_front_right_state") == "assist"
    assert _state(hass, f"sensor.{P}_front_right_assist_programme") == "frying"
    assert _state(hass, f"sensor.{P}_front_right_assist_phase") == "preheat"
    assert _state(hass, f"sensor.{P}_front_right_assist_target_temperature") == "180"
    end = dt_util.parse_datetime(_state(hass, f"sensor.{P}_front_left_timer_end"))
    assert abs(end - (dt_util.utcnow() + timedelta(seconds=120))) < timedelta(seconds=15)

    peer.push(ZONE_STREAM, zone_status("front_right", frying=(180, 2)))
    await hass.async_block_till_done()
    assert _state(hass, f"binary_sensor.{P}_front_right_assist_confirmation_required") == "on"
    reached = [e.data for e in events if e.data["type"] == "assist_target_reached"]
    assert reached == [
        {
            "device_id": ADDRESS,
            "name": "BORA X Pure",
            "type": "assist_target_reached",
            "zone": "front_right",
            "temperature": 180,
        }
    ]


async def test_switch_off_and_on_again(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer
) -> None:
    """Switching the cooktop off is a normal state; it reconnects when back."""
    entry = await _setup(hass)
    events = async_capture_events(hass, EVENT_BORA_ONE)

    # Like a real X Pure: zones report unavailable first, then Bluetooth drops.
    peer.status[EXTRACTOR + "GetExtractorStatus"] = EXTRACTOR_OFF
    peer.unavailable_zones.update(("front_left", "back_left", "back_right", "front_right"))
    await entry.runtime_data.async_refresh()
    peer.switch_off()
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert _state(hass, f"sensor.{P}_status") == "off"
    assert _state(hass, f"binary_sensor.{P}_bluetooth_connection") == "off"
    assert _state(hass, f"sensor.{P}_back_left_state") == "off"
    assert _state(hass, f"sensor.{P}_extractor_mode") == "off"
    assert {"switched_off", "cooking_finished"} <= {e.data["type"] for e in events}

    # The dropped client must still be closed, or BlueZ duplicates notifications.
    assert peer.sessions == 0

    events.clear()
    peer.unavailable_zones.clear()
    bluetooth.advertise()
    await hass.async_block_till_done()
    assert _state(hass, f"sensor.{P}_status") == "cooking"
    assert {"switched_on", "cooking_started"} <= {e.data["type"] for e in events}
    assert peer.sessions == 1


async def test_stream_error_frees_cooktop_and_reconnects(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer
) -> None:
    """A failed status stream closes the Bluetooth link and reconnects right away."""
    await _setup(hass)
    peer.push_error(ZONE_STREAM)
    await hass.async_block_till_done()
    assert peer.is_connected
    assert peer.sessions == 1
    assert _state(hass, f"sensor.{P}_status") == "cooking"


async def test_short_drop_keeps_last_state_and_reconnects(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer
) -> None:
    """A dropped link while the cooktop still advertises is not reported as off."""
    await _setup(hass)
    events = async_capture_events(hass, EVENT_BORA_ONE)

    peer._drop()
    await hass.async_block_till_done()
    assert peer.is_connected
    assert peer.sessions == 1
    assert _state(hass, f"sensor.{P}_status") == "cooking"
    assert _state(hass, f"binary_sensor.{P}_bluetooth_connection") == "on"
    assert not events

    # Capabilities are read once, not on every reconnect.
    assert peer.requests.count(IDENTIFY + "GetSystemValueRangeDescriptor") == 1
    assert peer.requests.count(IDENTIFY + "GetSystemInformation") == 1


async def test_drop_keeps_state_although_not_advertising(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer, monkeypatch
) -> None:
    """After a long connection HA no longer lists the cooktop; a drop is still short."""
    entry = await _setup(hass)
    peer.advertising = False
    peer._drop()
    await hass.async_block_till_done()
    assert _state(hass, f"sensor.{P}_status") == "cooking"
    assert _state(hass, f"binary_sensor.{P}_bluetooth_connection") == "on"

    peer.advertising = True
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert peer.is_connected
    assert _state(hass, f"sensor.{P}_status") == "cooking"

    # Without a successful read for longer than the grace period: offline.
    monkeypatch.setattr("custom_components.bora_one.coordinator.OFFLINE_GRACE", 0)
    peer.advertising = False
    peer._drop()
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert _state(hass, f"sensor.{P}_status") == "off"


async def test_unexpected_error_does_not_make_entities_unavailable(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer, monkeypatch
) -> None:
    """An unexpected error while reading keeps the entities and reconnects."""
    entry = await _setup(hass)
    device = entry.runtime_data.device
    original = device.refresh

    async def broken() -> None:
        raise KeyError("unexpected")

    monkeypatch.setattr(device, "refresh", broken)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert entry.runtime_data.last_update_success
    assert _state(hass, f"sensor.{P}_status") == "cooking"
    assert peer.is_connected
    monkeypatch.setattr(device, "refresh", original)


async def test_drop_after_grace_goes_offline(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer, monkeypatch
) -> None:
    """Without a recent successful read, a dropped link means offline."""
    monkeypatch.setattr("custom_components.bora_one.coordinator.OFFLINE_GRACE", 0)
    await _setup(hass)
    peer._drop()
    await hass.async_block_till_done()
    assert _state(hass, f"sensor.{P}_status") == "off"
    assert peer.sessions == 0


async def test_unanswered_stream_falls_back_to_polling(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer
) -> None:
    """A status stream the cooktop never answers is skipped; reads still work."""
    peer.silent.add(ZONE_STREAM)
    await _setup(hass)
    assert _state(hass, f"sensor.{P}_status") == "cooking"
    assert _state(hass, f"sensor.{P}_back_left_power_level") == "7"
    assert ZONE_STREAM not in peer.subscriptions


@pytest.mark.parametrize("delay", [0, 0.05])
async def test_link_dropped_after_subscribing_falls_back_to_polling(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer, delay: float
) -> None:
    """A cooktop that drops the link after a subscription is read periodically."""
    peer.stream_drop_delay = delay
    entry = await _setup(hass)
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()
    bluetooth.advertise()
    await hass.async_block_till_done()

    assert peer.is_connected
    assert not entry.runtime_data.device.use_streams
    assert _state(hass, f"sensor.{P}_status") == "cooking"
    assert _state(hass, f"sensor.{P}_back_left_power_level") == "7"

    peer.zones["back_left"] = zone_status("back_left", power=4)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert peer.is_connected
    assert not peer.subscriptions
    assert _state(hass, f"sensor.{P}_back_left_power_level") == "4"


async def test_refused_zone_read_keeps_other_zones(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer
) -> None:
    """A zone the cooktop refuses to report is unknown; the rest still works."""
    peer.refused_zones.add("back_right")
    await _setup(hass)
    assert _state(hass, f"sensor.{P}_status") == "cooking"
    assert _state(hass, f"sensor.{P}_back_left_power_level") == "7"
    assert _state(hass, f"sensor.{P}_back_right_state") == "unavailable"


async def test_switched_off_but_still_connected_shows_off(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer
) -> None:
    """Zones the cooktop reports unavailable after switching off are off, not unknown."""
    entry = await _setup(hass)
    peer.status[EXTRACTOR + "GetExtractorStatus"] = EXTRACTOR_OFF
    peer.unavailable_zones.update(("front_left", "back_left", "back_right", "front_right"))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert peer.is_connected
    assert _state(hass, f"binary_sensor.{P}_bluetooth_connection") == "on"
    assert _state(hass, f"sensor.{P}_status") == "off"
    assert _state(hass, f"sensor.{P}_back_left_state") == "off"
    assert _state(hass, f"sensor.{P}_back_left_power_level") == "0"
    assert _state(hass, f"sensor.{P}_active_zones") == "0"

    peer.unavailable_zones.clear()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert _state(hass, f"sensor.{P}_status") == "cooking"
    assert _state(hass, f"sensor.{P}_back_left_power_level") == "7"


async def test_drop_during_after_run_keeps_state(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer
) -> None:
    """Cooktop off but the extractor still running: a dropped link is not shown as off."""
    entry = await _setup(hass)
    peer.status[EXTRACTOR + "GetExtractorStatus"] = EXTRACTOR_AFTER_RUN
    peer.unavailable_zones.update(("front_left", "back_left", "back_right", "front_right"))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert _state(hass, f"sensor.{P}_status") == "after_run"

    peer.advertising = False
    peer._drop()
    await hass.async_block_till_done()
    assert _state(hass, f"sensor.{P}_status") == "after_run"
    assert _state(hass, f"binary_sensor.{P}_bluetooth_connection") == "on"


async def test_setup_while_cooktop_is_off(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer
) -> None:
    """Setup succeeds with the cooktop off; entities exist and show off."""
    peer.advertising = False
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert _state(hass, f"sensor.{P}_status") == "off"
    assert _state(hass, f"sensor.{P}_front_left_state") == "off"

    bluetooth.advertise()
    await hass.async_block_till_done()
    assert _state(hass, f"sensor.{P}_status") == "cooking"


async def test_refused_connections_back_off(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer
) -> None:
    """A cooktop Home Assistant still lists but that refuses connections is not hammered."""
    peer.refuse_connections = True
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    await coordinator.async_refresh()
    attempts = peer.connect_attempts
    assert attempts >= 2

    await coordinator.async_refresh()
    await coordinator.async_refresh()
    assert peer.connect_attempts == attempts
    assert _state(hass, f"sensor.{P}_status") == "off"

    # An advertisement received since the last failure retries at once, even when
    # Home Assistant does not call back for a repeated identical advertisement.
    bluetooth.last_advertisement = time.monotonic()
    await coordinator.async_refresh()
    assert peer.connect_attempts > attempts

    # Switched on: a fresh advertisement connects at once despite the back-off.
    peer.refuse_connections = False
    bluetooth.advertise()
    await hass.async_block_till_done()
    assert _state(hass, f"sensor.{P}_status") == "cooking"


async def test_failing_reconnects_while_cooking_keep_state(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer, monkeypatch
) -> None:
    """Drops while cooking with failing reconnects: no off, no back-off while it advertises."""
    monkeypatch.setattr("custom_components.bora_one.coordinator.OFFLINE_GRACE", 0.2)
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    peer.refuse_connections = True
    peer._drop()
    await hass.async_block_till_done()
    assert _state(hass, f"sensor.{P}_status") == "cooking"

    # Longer than the grace since the last read, but the cooktop still advertises.
    await asyncio.sleep(0.3)
    bluetooth.advertise()
    for _ in range(3):
        attempts = peer.connect_attempts
        await coordinator.async_refresh()
        assert peer.connect_attempts > attempts
    assert _state(hass, f"sensor.{P}_status") == "cooking"
    assert _state(hass, f"sensor.{P}_active_zones") != "0"

    peer.refuse_connections = False
    await coordinator.async_refresh()
    assert peer.is_connected
    assert _state(hass, f"sensor.{P}_status") == "cooking"

    # Switched off while disconnected: no more advertisements, so off after the grace.
    peer.refuse_connections = True
    peer._drop()
    await hass.async_block_till_done()
    await asyncio.sleep(0.3)
    await coordinator.async_refresh()
    assert _state(hass, f"sensor.{P}_status") == "off"


async def test_cooktop_that_answers_is_retried_without_back_off(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer
) -> None:
    """A connection that reaches the cooktop but then fails means it is on: retry soon."""
    peer.advertising = False
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    peer.advertising = True
    peer.refuse_writes = True
    for _ in range(3):
        attempts = peer.connect_attempts
        await coordinator.async_refresh()
        assert peer.connect_attempts > attempts
    assert _state(hass, f"sensor.{P}_status") == "off"

    peer.refuse_writes = False
    await coordinator.async_refresh()
    assert _state(hass, f"sensor.{P}_status") == "cooking"


async def test_connection_switch_releases_cooktop(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer
) -> None:
    """Turning the switch off disconnects so the phone app can connect."""
    await _setup(hass)
    entity_id = f"switch.{P}_allow_bluetooth_connection"

    await hass.services.async_call("switch", "turn_off", {"entity_id": entity_id}, blocking=True)
    assert not peer.is_connected
    assert _state(hass, entity_id) == "off"
    assert _state(hass, f"sensor.{P}_status") == "off"

    bluetooth.advertise()
    await hass.async_block_till_done()
    assert not peer.is_connected

    await hass.services.async_call("switch", "turn_on", {"entity_id": entity_id}, blocking=True)
    assert peer.is_connected
    assert _state(hass, f"sensor.{P}_status") == "cooking"


def _reauth_started(hass: HomeAssistant, entry: MockConfigEntry) -> bool:
    return any(
        f["context"]["source"] == SOURCE_REAUTH and f["context"]["entry_id"] == entry.entry_id
        for f in hass.config_entries.flow.async_progress()
    )


async def test_single_failed_bond_check_does_not_start_reauth(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer
) -> None:
    """One unconfirmed bond is retried; the pairing is not declared lost."""
    entry = await _setup(hass)
    peer.switch_off()
    await hass.async_block_till_done()

    peer.advertising = True
    peer.bonded = False
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert not _reauth_started(hass, entry)
    # Seen on a real X Pure during drops while cooking: the last state is kept.
    assert _state(hass, f"sensor.{P}_status") == "cooking"

    peer.bonded = True
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert _state(hass, f"sensor.{P}_status") == "cooking"


async def test_lost_pairing_starts_reauth(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer, monkeypatch
) -> None:
    """When the cooktop keeps refusing the bond, Home Assistant asks to pair again."""
    monkeypatch.setattr("custom_components.bora_one.coordinator.PAIRING_GRACE", 0)
    entry = await _setup(hass)
    peer.switch_off()
    await hass.async_block_till_done()

    peer.advertising = True
    peer.bonded = False
    for _ in range(3):
        assert not _reauth_started(hass, entry)
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    assert _reauth_started(hass, entry)
