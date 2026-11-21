"""Diagnostics for BragerOne."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import CONF_DEVID, CONF_OBJECT_ID
from .coordinator import BragerOneConfigEntry

TO_REDACT = {CONF_EMAIL, CONF_PASSWORD, CONF_DEVID, CONF_OBJECT_ID}
# P11 v6 holds "ID ETH: <devid>".
REDACT_PARAMETERS = {("P11", "v6")}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BragerOneConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = entry.runtime_data
    snapshot = runtime.coordinator.data
    pools = {
        pool: {
            key: "**REDACTED**" if (pool, key) in REDACT_PARAMETERS else value
            for key, value in items.items()
        }
        for pool, items in snapshot.pools.items()
    }
    module = runtime.module
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "module": {
            "name": module.name,
            "gateway_version": module.gateway_version,
            "device_name": module.device_name,
            "device_software": module.device_software,
        },
        "last_update_success": runtime.coordinator.last_update_success,
        "alarms": snapshot.alarms,
        "parameters": pools,
    }
