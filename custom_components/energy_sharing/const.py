"""Constants for the Energy Sharing integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "energy_sharing"
MANUFACTURER: Final = "Energy Sharing"
MODEL: Final = "15-minute settlement calculator"

CONF_GRID_IMPORT_ENTITY: Final = "grid_import_entity"
CONF_SHARED_ENERGY_ENTITY: Final = "shared_energy_entity"
CONF_PERCENTAGE_MODE: Final = "percentage_mode"
CONF_PERCENTAGE_ENTITY: Final = "percentage_entity"
CONF_FIXED_PERCENTAGE: Final = "fixed_percentage"

CONF_INTERVAL_MINUTES: Final = "interval_minutes"
CONF_PROCESSING_DELAY: Final = "processing_delay"
CONF_MAX_WAIT: Final = "max_wait"
CONF_RETRY_INTERVAL: Final = "retry_interval"
CONF_RESET_TOLERANCE: Final = "reset_tolerance"
CONF_ALLOW_PERCENTAGE_ABOVE_100: Final = "allow_percentage_above_100"

PERCENTAGE_MODE_ENTITY: Final = "entity"
PERCENTAGE_MODE_FIXED: Final = "fixed"

DEFAULT_NAME: Final = "Energy Sharing"
DEFAULT_INTERVAL_MINUTES: Final = 15
DEFAULT_PROCESSING_DELAY: Final = 10
DEFAULT_MAX_WAIT: Final = 60
DEFAULT_RETRY_INTERVAL: Final = 5
DEFAULT_RESET_TOLERANCE: Final = 5
DEFAULT_FIXED_PERCENTAGE: Final = 7.0

ATTR_LAST_PERIOD: Final = "last_period"
ATTR_LAST_RESET: Final = "last_reset"

STORAGE_VERSION: Final = 1
STORAGE_KEY: Final = "energy_sharing.storage"

SERVICE_PROCESS_NOW: Final = "process_now"
SERVICE_RESET_TOTALS: Final = "reset_totals"

SERVICE_CONFIRM: Final = "confirm"

STATUS_WAITING: Final = "waiting"
STATUS_PROCESSING: Final = "processing"
STATUS_READY: Final = "ready"
STATUS_INPUTS_UNAVAILABLE: Final = "inputs_unavailable"
STATUS_INPUTS_UNSYNCHRONIZED: Final = "inputs_unsynchronized"
STATUS_INVALID_INPUT: Final = "invalid_input"
STATUS_PERCENTAGE_INVALID: Final = "percentage_invalid"

SUPPORTED_ENERGY_UNITS: Final = frozenset({"Wh", "kWh", "MWh"})

MIN_INTERVAL_MINUTES: Final = 1
MAX_INTERVAL_MINUTES: Final = 60
MIN_PROCESSING_DELAY: Final = 0
MAX_PROCESSING_DELAY: Final = 300
MIN_MAX_WAIT: Final = 10
MAX_MAX_WAIT: Final = 600
MIN_RETRY_INTERVAL: Final = 1
MAX_RETRY_INTERVAL: Final = 60
MIN_RESET_TOLERANCE: Final = 0
MAX_RESET_TOLERANCE: Final = 60

CONFIG_ENTRY_VERSION: Final = 1
CONFIG_ENTRY_MINOR_VERSION: Final = 1
