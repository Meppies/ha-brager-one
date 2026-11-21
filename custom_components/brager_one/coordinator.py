"""Data update coordinator for BragerOne."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    BragerOneAuthError,
    BragerOneClient,
    BragerOneError,
    BragerOneModule,
    BragerOneSnapshot,
)
from .const import ALARM_DESCRIPTIONS, DOMAIN, LOGGER, UPDATE_INTERVAL


@dataclass(slots=True)
class BragerOneRuntimeData:
    """Runtime data stored on the config entry."""

    client: BragerOneClient
    module: BragerOneModule
    coordinator: BragerOneCoordinator


type BragerOneConfigEntry = ConfigEntry[BragerOneRuntimeData]


def alarm_issue_id(devid: str) -> str:
    """Return the repair issue id used for active alarms."""
    return f"active_alarm_{devid}"


def alarm_text(code: int) -> str:
    """Return a readable alarm description."""
    return ALARM_DESCRIPTIONS.get(code, f"Unknown alarm {code}")


class BragerOneCoordinator(DataUpdateCoordinator[BragerOneSnapshot]):
    """Polls one BragerOne module."""

    config_entry: BragerOneConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: BragerOneConfigEntry,
        client: BragerOneClient,
        module: BragerOneModule,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{module.devid}",
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.module = module

    async def _async_update_data(self) -> BragerOneSnapshot:
        try:
            snapshot = await self.client.async_get_snapshot(self.module.devid)
        except BragerOneAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except BragerOneError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self._sync_alarm_issue(snapshot)
        return snapshot

    def _sync_alarm_issue(self, snapshot: BragerOneSnapshot) -> None:
        """Raise a repair issue while the stove reports an alarm."""
        issue_id = alarm_issue_id(self.module.devid)
        if not snapshot.alarms:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            return
        texts = ", ".join(alarm_text(alarm["code"]) for alarm in snapshot.alarms)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="active_alarm",
            translation_placeholders={"name": self.module.name, "alarms": texts},
        )
