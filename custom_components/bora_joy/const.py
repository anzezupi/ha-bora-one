"""Constants for the BORA JOY integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "bora_joy"
MANUFACTURER: Final = "BORA"

CONF_MODE: Final = "mode"
MODE_CLOUD: Final = "cloud"
MODE_DEMO: Final = "demo"

CONF_SCAN_INTERVAL: Final = "scan_interval"
DEFAULT_SCAN_INTERVAL: Final = 30
DEMO_SCAN_INTERVAL: Final = timedelta(seconds=10)

EVENT_BORA_JOY: Final = "bora_joy_event"
