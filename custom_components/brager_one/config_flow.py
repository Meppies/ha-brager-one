"""Config flow for BragerOne."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .api import (
    BragerOneAuthError,
    BragerOneClient,
    BragerOneConnectionError,
    BragerOneModule,
)
from .const import (
    CONF_DEVID,
    CONF_OBJECT_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
    }
)
PASSWORD_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        )
    }
)


class BragerOneConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BragerOne."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> BragerOneOptionsFlow:
        """Return the options flow."""
        return BragerOneOptionsFlow()

    def __init__(self) -> None:
        """Initialise the flow."""
        self._credentials: dict[str, str] = {}
        self._modules: dict[str, BragerOneModule] = {}

    async def _async_fetch_modules(
        self, email: str, password: str
    ) -> tuple[list[BragerOneModule], dict[str, str]]:
        """Log in and list modules; return errors keyed for the form."""
        client = BragerOneClient(async_get_clientsession(self.hass), email, password)
        try:
            await client.async_login()
            modules = await client.async_get_modules()
        except BragerOneAuthError:
            return [], {"base": "invalid_auth"}
        except BragerOneConnectionError:
            return [], {"base": "cannot_connect"}
        except Exception:  # noqa: BLE001
            LOGGER.exception("Unexpected error while validating BragerOne login")
            return [], {"base": "unknown"}
        if not modules:
            return [], {"base": "no_modules"}
        return modules, {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the BragerOne account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            modules, errors = await self._async_fetch_modules(
                user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if not errors:
                self._credentials = {
                    CONF_EMAIL: user_input[CONF_EMAIL],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                }
                configured = self._async_current_ids(include_ignore=False)
                self._modules = {
                    m.devid: m for m in modules if m.devid not in configured
                }
                if not self._modules:
                    return self.async_abort(reason="already_configured")
                if len(self._modules) == 1:
                    return await self._async_create(next(iter(self._modules.values())))
                return await self.async_step_module()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                CREDENTIALS_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_module(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick a module when the account has several."""
        if user_input is not None:
            return await self._async_create(self._modules[user_input[CONF_DEVID]])
        options = [
            SelectOptionDict(value=m.devid, label=f"{m.name} ({m.object_name})")
            for m in self._modules.values()
        ]
        return self.async_show_form(
            step_id="module",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVID): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.LIST
                        )
                    )
                }
            ),
        )

    async def _async_create(self, module: BragerOneModule) -> ConfigFlowResult:
        await self.async_set_unique_id(module.devid)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=module.name,
            data={
                **self._credentials,
                CONF_DEVID: module.devid,
                CONF_OBJECT_ID: module.object_id,
            },
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication after the password stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            modules, errors = await self._async_fetch_modules(
                entry.data[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if not errors:
                if entry.data[CONF_DEVID] not in {m.devid for m in modules}:
                    return self.async_abort(reason="module_missing")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=PASSWORD_SCHEMA,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the account e-mail address or password."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            modules, errors = await self._async_fetch_modules(
                user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if not errors:
                if entry.data[CONF_DEVID] not in {m.devid for m in modules}:
                    return self.async_abort(reason="module_missing")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                CREDENTIALS_SCHEMA,
                user_input or {CONF_EMAIL: entry.data[CONF_EMAIL]},
            ),
            errors=errors,
        )


class BragerOneOptionsFlow(OptionsFlowWithReload):
    """Let the user choose how often BragerOne is polled."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the polling interval."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )
        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=5,
                        mode=NumberSelectorMode.SLIDER,
                        unit_of_measurement="s",
                    )
                )
            }
        )
        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema, {CONF_SCAN_INTERVAL: current}
            ),
        )
