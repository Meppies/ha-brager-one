"""Constants for the BragerOne integration."""

from __future__ import annotations

from datetime import timedelta
from logging import Logger, getLogger
from typing import Final

DOMAIN: Final = "brager_one"
LOGGER: Logger = getLogger(__package__)

CONF_DEVID: Final = "devid"
CONF_OBJECT_ID: Final = "object_id"

API_BASE_URL: Final = "https://io.brager.pl/v1"
WEB_ORIGIN: Final = "https://one.brager.pl"
APP_VERSION: Final = "1.04.16"

# Polling interval in seconds; the user can change it in the options.
DEFAULT_SCAN_INTERVAL: Final = 60
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 300
# The alarm history is read less often; it is also re-read whenever the set of
# active alarms changes.
HISTORY_INTERVAL: Final = timedelta(minutes=10)
# BragerOne relays a command to the controller and back; the new value
# usually shows up in the cloud a few seconds after the command returns.
COMMAND_REFRESH_DELAY: Final = 5.0
# How long an entity keeps showing the value it just wrote while the cloud
# still reports the old one.
PENDING_TIMEOUT: Final = timedelta(seconds=45)

# Raw module commands, as used by the BragerOne web app.
COMMAND_BOILER_START: Final = "BOILER_START"
COMMAND_BOILER_STOP: Final = "BOILER_STOP"

# Operating state word P5 s10, as shown by the BragerOne app. Only the values
# below have been seen; others are reported as unknown with the raw code.
OPERATING_STATES: Final[dict[int, str]] = {
    1: "standby",
    3: "work",
}

# Alarm texts live in translations/<language>.json under
# selector.alarm.options.<code>, so they follow the Home Assistant language.
ALARM_TRANSLATION_PREFIX: Final = f"component.{DOMAIN}.selector.alarm.options."
