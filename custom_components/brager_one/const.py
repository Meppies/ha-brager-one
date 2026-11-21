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

UPDATE_INTERVAL: Final = timedelta(seconds=60)
# BragerOne relays a command to the controller and back; the new value
# usually shows up in the cloud a few seconds after the command returns.
COMMAND_REFRESH_DELAY: Final = 5.0
# How long an entity keeps showing the value it just wrote while the cloud
# still reports the old one.
PENDING_TIMEOUT: Final = timedelta(seconds=45)

# Raw module commands, as used by the BragerOne web app.
COMMAND_BOILER_START: Final = "BOILER_START"
COMMAND_BOILER_STOP: Final = "BOILER_STOP"

# Alarm descriptions for the HT-Tronic / Brager controller family. The cloud
# only returns the numeric code; these texts come from the controller manual.
ALARM_DESCRIPTIONS: Final[dict[int, str]] = {
    0: "Boiler sensor fault",
    1: "Return sensor fault",
    2: "Hot water sensor fault",
    3: "Feeder sensor fault",
    4: "Outdoor sensor fault",
    5: "Mixing valve 1 sensor fault",
    6: "Buffer sensor (top) fault",
    7: "Flue gas sensor fault",
    8: "Fuel level sensor fault",
    13: "Flame sensor fault",
    15: "Fan speed sensor fault",
    18: "Buffer sensor (bottom) fault",
    23: "Boiler overheated",
    24: "Hot water overheated",
    25: "Feeder too hot (burn-back risk)",
    26: "Safety thermostat (STB) tripped",
    28: "Feeder blocked",
    30: "Flue gas too hot",
    31: "No draught (chimney or door open)",
    38: "Out of fuel",
    39: "Hopper lid open",
    44: "Fan fault",
    54: "Ignition failed",
    55: "Flame lost or power failure",
    56: "Start-up assistant required",
    57: "Service or inspection required",
    170: "Ash removal fault",
    500: "Alarm acknowledged manually",
    501: "Module not connected",
}
