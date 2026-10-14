"""Demo cooktop tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.bora_one.const import CONF_MODE, DOMAIN, EVENT_BORA_ONE, MODE_DEMO
from custom_components.bora_one.demo import demo_snapshot

P = "bora_x_pure_demo"


class Clock:
    """Position in the simulated cooking session."""

    t = 400


@pytest.fixture
def clock() -> Generator[Clock]:
    """Control the demo clock."""
    clock = Clock()
    with patch(
        "custom_components.bora_one.coordinator.demo_snapshot",
        side_effect=lambda _elapsed: demo_snapshot(clock.t),
    ):
        yield clock


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=MODE_DEMO, title="BORA X Pure (demo)", data={CONF_MODE: MODE_DEMO}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_demo_states(hass: HomeAssistant, clock: Clock) -> None:
    """The demo cooktop exposes a cooking session."""
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(f"sensor.{P}_status").state == "cooking"
    assert hass.states.get(f"sensor.{P}_active_zones").state == "3"
    assert hass.states.get(f"sensor.{P}_front_left_power_level").state == "5"
    assert hass.states.get(f"sensor.{P}_back_left_keep_warm").state == "keep_warm"
    assert hass.states.get(f"sensor.{P}_front_right_assist_programme").state == "frying"
    assert hass.states.get(f"sensor.{P}_extractor_mode").state == "automatic"

    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert len(entities) == (8 + 4 * 7) + (9 + 4 * 3)

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_demo_events(hass: HomeAssistant, clock: Clock) -> None:
    """Transitions in the simulation fire events."""
    clock.t = 30
    entry = await _setup(hass)
    events = async_capture_events(hass, EVENT_BORA_ONE)

    async def step(t: int) -> list[str]:
        events.clear()
        clock.t = t
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        return [e.data["type"] for e in events]

    assert await step(70) == ["switched_on", "cooking_started"]
    assert await step(290) == []
    assert await step(310) == ["assist_target_reached"]
    assert await step(670) == ["zone_timer_finished"]
    assert {"cooking_finished", "assist_finished"} <= set(await step(790))
    assert await step(1090) == ["after_run_finished"]
    assert await step(1150) == ["switched_off"]
