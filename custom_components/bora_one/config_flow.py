"""Config flow for BORA One: Bluetooth discovery, pairing and demo mode."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import logging
from typing import Any

from bleak.exc import BleakError
import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .adapter import create_connection
from .agent import pairing_agent
from .ble.transport import BoraError, PairingRequired
from .ble.wire import ProtocolError
from .const import CONF_MODE, DOMAIN, MODE_BLUETOOTH, MODE_DEMO, SERVICE_UUID
from .coordinator import CONF_EXTRACTOR, CONF_MODEL, CONF_ZONES
from .device import BoraBleDevice
from .mapper import PRODUCT_MODELS, zone_positions

_LOGGER = logging.getLogger(__name__)

PAIRING_TIMEOUT = 240
"""Pairing waits for the Connect button and may need a second tap."""


def is_bora(info: bluetooth.BluetoothServiceInfoBleak) -> bool:
    """Return True for a BORA appliance advertisement."""
    return SERVICE_UUID in {uuid.lower() for uuid in info.service_uuids} or (
        info.name or ""
    ).upper() in {"X PURE", "PURE", "S PURE", "M PURE"}


async def async_pair_and_probe(hass, address: str) -> dict[str, Any]:
    """Pair (if needed), read the appliance description and disconnect again."""
    device = BoraBleDevice(create_connection(hass, address))
    try:
        async with pairing_agent(), asyncio.timeout(PAIRING_TIMEOUT):
            await device.connect(pair=True, subscribe=False)
        product = device.information.get("product_name")
        return {
            CONF_ZONES: [p.value for p in zone_positions(device.descriptor).values()],
            CONF_EXTRACTOR: bool(device.descriptor.get("extractor_descriptor")),
            CONF_MODEL: PRODUCT_MODELS.get(product, product) if product else None,
        }
    finally:
        await device.disconnect()


class BoraOneConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BORA One."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._address: str | None = None
        self._name = "BORA"

    async def async_step_bluetooth(
        self, discovery_info: bluetooth.BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a discovered cooktop; pairing still needs confirmation."""
        if not is_bora(discovery_info):
            return self.async_abort(reason="not_supported")
        await self.async_set_unique_id(discovery_info.address.upper())
        self._abort_if_unique_id_configured()
        self._address = discovery_info.address.upper()
        self._name = discovery_info.name or "BORA"
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_pair()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose a discovered cooktop or the demo."""
        return self.async_show_menu(step_id="user", menu_options=["bluetooth_pick", MODE_DEMO])

    async def async_step_demo(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create a demo entry."""
        await self.async_set_unique_id(MODE_DEMO)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="BORA X Pure (demo)", data={CONF_MODE: MODE_DEMO})

    async def async_step_bluetooth_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a cooktop seen by Home Assistant's Bluetooth."""
        if user_input is not None:
            self._address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(self._address)
            self._abort_if_unique_id_configured()
            return await self.async_step_pair()

        current = self._async_current_ids(include_ignore=False)
        devices = {
            info.address.upper(): f"{info.name or 'BORA'} ({info.address})"
            for info in bluetooth.async_discovered_service_info(self.hass, connectable=True)
            if is_bora(info) and info.address.upper() not in current
        }
        if not devices:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="bluetooth_pick",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(devices)}),
        )

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Explain pairing, then pair and read the cooktop description."""
        errors: dict[str, str] = {}
        detail = ""
        if user_input is not None:
            assert self._address is not None
            try:
                details = await async_pair_and_probe(self.hass, self._address)
            except PairingRequired as err:
                _LOGGER.warning("Pairing with BORA %s not completed: %s", self._address, err)
                errors["base"] = "pairing_failed"
                detail = str(err)
            except (BoraError, BleakError, ProtocolError, TimeoutError) as err:
                _LOGGER.warning("Connecting to BORA %s failed: %r", self._address, err)
                errors["base"] = "cannot_connect"
                detail = f"{type(err).__name__}: {err}" if str(err) else type(err).__name__
            except Exception as err:
                _LOGGER.exception("Unexpected error while pairing with BORA")
                errors["base"] = "unknown"
                detail = f"{type(err).__name__}: {err}"
            else:
                data = {CONF_MODE: MODE_BLUETOOTH, CONF_ADDRESS: self._address, **details}
                if self.source == SOURCE_REAUTH:
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(), data=data
                    )
                title = f"BORA {details[CONF_MODEL]}" if details[CONF_MODEL] else self._name
                return self.async_create_entry(title=title, data=data)
        return self.async_show_form(
            step_id="pair",
            errors=errors,
            description_placeholders={"name": self._name, "error": detail},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Pair again after the cooktop forgot Home Assistant."""
        self._address = entry_data[CONF_ADDRESS]
        self._name = self._get_reauth_entry().title
        return await self.async_step_pair()
