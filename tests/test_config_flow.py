"""Config flow tests."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.bora_joy.const import CONF_MODE, DOMAIN, MODE_DEMO


async def test_demo_flow(hass: HomeAssistant, demo_client) -> None:
    """Demo mode creates an entry, and only once."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": MODE_DEMO}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_MODE: MODE_DEMO}
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": MODE_DEMO}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_cloud_flow_not_available(hass: HomeAssistant) -> None:
    """The cloud step reports that the API is not available yet."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "cloud"}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "a@b.si", CONF_PASSWORD: "x"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "api_not_available"}
