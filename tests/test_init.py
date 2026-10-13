"""Setup, entity and event tests using the demo cooktop."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.bora_joy.const import CONF_MODE, DOMAIN, EVENT_BORA_JOY, MODE_DEMO

PREFIX = "bora_x_pure_demo"


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=MODE_DEMO, data={CONF_MODE: MODE_DEMO})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_and_unload(hass: HomeAssistant, demo_client) -> None:
    """The entry loads, creates one device and unloads cleanly."""
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    assert devices[0].manufacturer == "BORA"
    assert devices[0].model == "X Pure"

    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert len(entities) == 7 + 4 * 5 + 9 + 4 * 3

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_states_while_cooking(hass: HomeAssistant, demo_client) -> None:
    """Entity states reflect the simulated cooking session."""
    demo_client.t = 400
    await _setup(hass)

    def state(entity_id: str) -> str:
        return hass.states.get(entity_id).state

    assert state(f"sensor.{PREFIX}_status") == "cooking"
    assert state(f"sensor.{PREFIX}_active_zones") == "3"
    assert state(f"sensor.{PREFIX}_extractor_mode") == "automatic"
    assert state(f"sensor.{PREFIX}_extractor_fan_level") == "6"
    assert state(f"sensor.{PREFIX}_odour_filter_remaining") == "63"
    assert state(f"sensor.{PREFIX}_front_left_power_level") == "5"
    assert state(f"sensor.{PREFIX}_front_left_state") == "on"
    assert state(f"sensor.{PREFIX}_front_left_timer_end") not in ("unknown", "unavailable")
    assert state(f"sensor.{PREFIX}_front_right_assist_programme") == "fry"
    assert state(f"sensor.{PREFIX}_front_right_assist_target_temperature") == "180"
    assert state(f"sensor.{PREFIX}_rear_left_state") == "keep_warm"
    assert state(f"sensor.{PREFIX}_rear_right_state") == "off"
    assert state(f"binary_sensor.{PREFIX}_cooking") == "on"
    assert state(f"binary_sensor.{PREFIX}_power") == "on"
    assert state(f"binary_sensor.{PREFIX}_online") == "on"
    assert state(f"binary_sensor.{PREFIX}_front_left_active") == "on"
    assert state(f"binary_sensor.{PREFIX}_rear_right_active") == "off"


async def test_timer_end_is_stable(hass: HomeAssistant, demo_client) -> None:
    """The timer end timestamp does not jitter between polls."""
    demo_client.t = 400
    entry = await _setup(hass)
    entity_id = f"sensor.{PREFIX}_front_left_timer_end"
    first = hass.states.get(entity_id).state

    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == first


async def test_events(hass: HomeAssistant, demo_client) -> None:
    """Transitions fire bora_joy_event."""
    demo_client.t = 30
    entry = await _setup(hass)
    events = async_capture_events(hass, EVENT_BORA_JOY)
    coordinator = entry.runtime_data

    async def step(t: int) -> list[str]:
        events.clear()
        demo_client.t = t
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        return [e.data["type"] for e in events]

    assert await step(70) == ["cooking_started"]
    assert await step(290) == []
    assert await step(310) == ["assist_target_reached"]
    assert events[0].data["zone"] == "front_right"
    assert events[0].data["temperature"] == 180
    assert "short_timer_finished" in await step(490)
    assert await step(670) == ["zone_timer_finished"]
    types = await step(790)
    assert "cooking_finished" in types
    assert "assist_finished" in types
    assert await step(1100) == ["after_run_finished"]

    await step(70)
    assert hass.states.get(f"sensor.{PREFIX}_status").state == "cooking"
