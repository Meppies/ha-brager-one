"""Data update coordinator for BragerOne."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.translation import async_get_translations
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    BragerOneAuthError,
    BragerOneClient,
    BragerOneError,
    BragerOneModule,
    BragerOneSnapshot,
)
from .const import (
    ALARM_TRANSLATION_PREFIX,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    HISTORY_INTERVAL,
    LOGGER,
)


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
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        self.module = module
        self._history: list[dict[str, Any]] = []
        self._history_fetched: datetime | None = None
        self._last_codes: list[int] | None = None
        self._alarm_texts: dict[str, str] = {}
        self._texts_language: str | None = None

    async def _async_alarm_texts(self) -> dict[str, str]:
        """Load the alarm texts for the current Home Assistant language."""
        language = self.hass.config.language
        if language != self._texts_language:
            translations = await async_get_translations(
                self.hass, language, "selector", {DOMAIN}
            )
            self._alarm_texts = {
                key.removeprefix(ALARM_TRANSLATION_PREFIX): text
                for key, text in translations.items()
                if key.startswith(ALARM_TRANSLATION_PREFIX)
            }
            self._texts_language = language
        return self._alarm_texts

    async def _async_fetch(self) -> BragerOneSnapshot:
        devid = self.module.devid
        pools = await self.client.async_get_parameters(devid)
        alarms = await self.client.async_get_alarms(devid)
        codes = sorted(alarm["code"] for alarm in alarms)
        now = dt_util.utcnow()
        if (
            self._history_fetched is None
            or codes != self._last_codes
            or now - self._history_fetched >= HISTORY_INTERVAL
        ):
            self._history = await self.client.async_get_alarm_history(devid)
            self._history_fetched = now
        self._last_codes = codes
        return BragerOneSnapshot(
            pools=pools,
            alarms=alarms,
            history=self._history,
            alarm_texts=await self._async_alarm_texts(),
        )

    async def _async_update_data(self) -> BragerOneSnapshot:
        try:
            snapshot = await self._async_fetch()
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
        texts = ", ".join(
            snapshot.alarm_text(alarm["code"]) for alarm in snapshot.alarms
        )
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
