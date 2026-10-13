"""Config flow for BORA JOY."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    BoraJoyApiNotAvailable,
    BoraJoyAuthError,
    BoraJoyCloudClient,
    BoraJoyConnectionError,
)
from .const import (
    CONF_MODE,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MODE_CLOUD,
    MODE_DEMO,
)
from .coordinator import BoraJoyConfigEntry

_LOGGER = logging.getLogger(__name__)

CLOUD_SCHEMA = vol.Schema(
    {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
)


class BoraJoyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BORA JOY."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick cloud account or demo mode."""
        return self.async_show_menu(step_id="user", menu_options=[MODE_CLOUD, MODE_DEMO])

    async def async_step_demo(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create a demo entry."""
        await self.async_set_unique_id(MODE_DEMO)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="BORA JOY (demo)", data={CONF_MODE: MODE_DEMO})

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Log in with a BORA JOY account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
            self._abort_if_unique_id_configured()
            if (error := await self._async_validate(user_input)) is None:
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME],
                    data={CONF_MODE: MODE_CLOUD, **user_input},
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="cloud",
            data_schema=self.add_suggested_values_to_schema(CLOUD_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            if (error := await self._async_validate(data)) is None:
                return self.async_update_reload_and_abort(entry, data=data)
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={CONF_USERNAME: entry.data[CONF_USERNAME]},
            errors=errors,
        )

    async def _async_validate(self, data: Mapping[str, Any]) -> str | None:
        client = BoraJoyCloudClient(
            async_get_clientsession(self.hass), data[CONF_USERNAME], data[CONF_PASSWORD]
        )
        try:
            await client.async_login()
        except BoraJoyApiNotAvailable:
            return "api_not_available"
        except BoraJoyAuthError:
            return "invalid_auth"
        except BoraJoyConnectionError:
            return "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error during login")
            return "unknown"
        return None

    @staticmethod
    @callback
    def async_get_options_flow(entry: BoraJoyConfigEntry) -> BoraJoyOptionsFlow:
        """Return the options flow."""
        return BoraJoyOptionsFlow()


class BoraJoyOptionsFlow(OptionsFlowWithReload):
    """Polling interval option."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=600)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
