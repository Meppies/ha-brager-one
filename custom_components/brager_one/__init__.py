"""The BragerOne integration."""

from __future__ import annotations

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BragerOneAuthError, BragerOneClient, BragerOneError
from .const import CONF_DEVID, DOMAIN
from .coordinator import (
    BragerOneConfigEntry,
    BragerOneCoordinator,
    BragerOneRuntimeData,
    alarm_issue_id,
)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: BragerOneConfigEntry) -> bool:
    """Set up BragerOne from a config entry."""
    client = BragerOneClient(
        async_get_clientsession(hass),
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
    )
    devid: str = entry.data[CONF_DEVID]
    try:
        modules = await client.async_get_modules()
    except BragerOneAuthError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="auth_failed"
        ) from err
    except BragerOneError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": str(err)},
        ) from err

    module = next((m for m in modules if m.devid == devid), None)
    if module is None:
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="module_not_found",
            translation_placeholders={"devid": devid},
        )

    coordinator = BragerOneCoordinator(hass, entry, client, module)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = BragerOneRuntimeData(
        client=client, module=module, coordinator=coordinator
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BragerOneConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: BragerOneConfigEntry) -> None:
    """Clean up repair issues when the entry is removed."""
    ir.async_delete_issue(hass, DOMAIN, alarm_issue_id(entry.data[CONF_DEVID]))
