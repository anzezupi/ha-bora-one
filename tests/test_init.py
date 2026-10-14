"""Integration tests against the simulated cooktop (recorded X Pure responses)."""

from __future__ import annotations

from datetime import timedelta

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.bora_one.const import CONF_MODE, DOMAIN, EVENT_BORA_ONE, MODE_BLUETOOTH

from .bora_peer import EXTRACTOR, EXTRACTOR_AFTER_RUN, ZONE, FakeBoraPeer, zone_status
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

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, ADDRESS)})
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

    peer.switch_off()
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert _state(hass, f"sensor.{P}_status") == "off"
    assert _state(hass, f"binary_sensor.{P}_bluetooth_connection") == "off"
    assert _state(hass, f"sensor.{P}_back_left_state") == "off"
    assert _state(hass, f"sensor.{P}_extractor_mode") == "off"
    assert {"switched_off", "cooking_finished"} <= {e.data["type"] for e in events}

    events.clear()
    bluetooth.advertise()
    await hass.async_block_till_done()
    assert _state(hass, f"sensor.{P}_status") == "cooking"
    assert {"switched_on", "cooking_started"} <= {e.data["type"] for e in events}


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


async def test_lost_pairing_starts_reauth(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer
) -> None:
    """When the cooktop forgot the pairing, Home Assistant asks to pair again."""
    entry = await _setup(hass)
    peer.switch_off()
    await hass.async_block_till_done()

    peer.bonded = False
    bluetooth.advertise()
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    assert any(
        f["context"]["source"] == SOURCE_REAUTH and f["context"]["entry_id"] == entry.entry_id
        for f in flows
    )
