"""Constants for the BORA One integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "bora_one"
MANUFACTURER: Final = "BORA"

CONF_MODE: Final = "mode"
MODE_BLUETOOTH: Final = "bluetooth"
MODE_DEMO: Final = "demo"

SERVICE_UUID: Final = "64cbfe50-126b-17ac-774e-f6fa40487dac"

UPDATE_INTERVAL: Final = timedelta(seconds=30)
DEMO_UPDATE_INTERVAL: Final = timedelta(seconds=10)
CONNECT_TIMEOUT: Final = 60

EVENT_BORA_ONE: Final = "bora_one_event"

DATA_PAIRING: Final = "pairing"
"""hass.data[DOMAIN] key: addresses with a pairing flow in progress."""
