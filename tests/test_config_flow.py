"""Config flow tests: discovery, pairing and demo."""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant import config_entries
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.bora_one.const import CONF_MODE, DOMAIN, MODE_BLUETOOTH, MODE_DEMO, SERVICE_UUID

from .conftest import ADDRESS

EXPECTED_DATA = {
    CONF_MODE: MODE_BLUETOOTH,
    CONF_ADDRESS: ADDRESS,
    "zones": ["front_left", "back_left", "back_right", "front_right"],
    "extractor": True,
    "model": "X Pure",
}


async def _start_pick(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "bluetooth_pick"}
    )


async def test_pick_and_pair(hass: HomeAssistant, bluetooth, peer) -> None:
    """A bonded cooktop is set up from the device list."""
    result = await _start_pick(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_pick"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS}
    )
    assert result["step_id"] == "pair"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "BORA X Pure"
    assert result["data"] == EXPECTED_DATA
    await hass.async_block_till_done()
    assert all("/Get" in path or "/Stream" in path for path in peer.requests)


async def test_first_time_pairing(hass: HomeAssistant, bluetooth, peer) -> None:
    """An unbonded cooktop is paired when confirmed."""
    peer.bonded = False
    result = await _start_pick(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert peer.bonded


async def test_pairing_with_stale_adapter_keys(hass: HomeAssistant, bluetooth, peer) -> None:
    """Stale keys on the adapter are removed and pairing is repeated."""
    peer.bonded = False
    peer.stale_keys = True
    result = await _start_pick(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert peer.unpaired
    assert peer.bonded


async def test_pairing_not_confirmed(hass: HomeAssistant, bluetooth, peer) -> None:
    """Pairing that is not confirmed on the cooktop shows an error."""
    peer.bonded = False
    peer.accept_pairing = False
    result = await _start_pick(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "pairing_failed"}

    peer.accept_pairing = True
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_cannot_connect(hass: HomeAssistant, bluetooth, peer) -> None:
    """A cooktop that switched off meanwhile shows an error."""
    result = await _start_pick(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS}
    )
    peer.advertising = False
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "cannot_connect"}


async def test_no_devices(hass: HomeAssistant, bluetooth, peer) -> None:
    """Without a cooktop in range the flow aborts."""
    peer.advertising = False
    result = await _start_pick(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_bluetooth_discovery(hass: HomeAssistant, bluetooth, peer) -> None:
    """A discovered cooktop goes straight to pairing."""
    info = SimpleNamespace(address=ADDRESS.lower(), name="X PURE", service_uuids=[SERVICE_UUID])
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=info
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == EXPECTED_DATA


async def test_demo_flow(hass: HomeAssistant) -> None:
    """Demo mode creates an entry, and only once."""
    for expected in (FlowResultType.CREATE_ENTRY, FlowResultType.ABORT):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": MODE_DEMO}
        )
        assert result["type"] is expected
        await hass.async_block_till_done()
