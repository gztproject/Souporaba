"""Constants for the Energy Sharing integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "energy_sharing"
MANUFACTURER: Final = "Energy Sharing"
MODEL: Final = "15-minute settlement calculator"

# Required interval sources (config entry data)
CONF_PROVIDER_EXPORT_SOURCE: Final = "provider_export_source"
CONF_RECEIVER_IMPORT_SOURCE: Final = "receiver_import_source"

# Legacy v1 keys (migration only)
CONF_GRID_IMPORT_ENTITY: Final = "grid_import_entity"
CONF_SHARED_ENERGY_ENTITY: Final = "shared_energy_entity"

# Allocation percentage (options)
CONF_ALLOCATION_PERCENTAGE_MODE: Final = "allocation_percentage_mode"
CONF_ALLOCATION_PERCENTAGE_SOURCE: Final = "allocation_percentage_source"
CONF_FIXED_ALLOCATION_PERCENTAGE: Final = "fixed_allocation_percentage"

# Legacy percentage keys (migration only)
CONF_PERCENTAGE_MODE: Final = "percentage_mode"
CONF_PERCENTAGE_ENTITY: Final = "percentage_entity"
CONF_FIXED_PERCENTAGE: Final = "fixed_percentage"

PERCENTAGE_MODE_ENTITY: Final = "entity"
PERCENTAGE_MODE_FIXED: Final = "fixed"

# Optional reconciliation source (options)
CONF_REPORTED_ALLOCATION_SOURCE: Final = "reported_allocation_source"

# Timing and synchronization (options)
CONF_INTERVAL_MINUTES: Final = "interval_minutes"
CONF_PROCESSING_DELAY: Final = "processing_delay"
CONF_MAX_WAIT: Final = "max_wait"
CONF_RETRY_INTERVAL: Final = "retry_interval"
CONF_RESET_TOLERANCE: Final = "reset_tolerance"

# Reconciliation options
CONF_ALLOCATION_TOLERANCE_KWH: Final = "allocation_tolerance_kwh"
CONF_ALLOCATION_TOLERANCE_PCT: Final = "allocation_tolerance_pct"
CONF_RECONCILIATION_FAILURE_MODE: Final = "reconciliation_failure_mode"
CONF_ALLOW_PERCENTAGE_ABOVE_100: Final = "allow_percentage_above_100"

RECONCILIATION_MODE_WARN: Final = "warn"
RECONCILIATION_MODE_SKIP_INTERVAL: Final = "skip_interval"

DEFAULT_NAME: Final = "Energy Sharing"
DEFAULT_INTERVAL_MINUTES: Final = 15
DEFAULT_PROCESSING_DELAY: Final = 10
DEFAULT_MAX_WAIT: Final = 60
DEFAULT_RETRY_INTERVAL: Final = 5
DEFAULT_RESET_TOLERANCE: Final = 5
DEFAULT_FIXED_ALLOCATION_PERCENTAGE: Final = 7.0
DEFAULT_ALLOCATION_TOLERANCE_KWH: Final = 0.01
DEFAULT_ALLOCATION_TOLERANCE_PCT: Final = 5.0
DEFAULT_RECONCILIATION_FAILURE_MODE: Final = RECONCILIATION_MODE_WARN

ATTR_LAST_PERIOD: Final = "last_period"
ATTR_LAST_RESET: Final = "last_reset"

STORAGE_VERSION: Final = 2
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
STATUS_RECONCILIATION_MISMATCH: Final = "reconciliation_mismatch"

RECONCILIATION_MATCHED: Final = "matched"
RECONCILIATION_NOT_CONFIGURED: Final = "not_configured"
RECONCILIATION_MISMATCH_WARN: Final = "mismatch_warn"
RECONCILIATION_MISMATCH_SKIP: Final = "mismatch_skip"

SUPPORTED_ENERGY_UNITS: Final = frozenset({"Wh", "kWh"})

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

CONFIG_ENTRY_VERSION: Final = 2
CONFIG_ENTRY_MINOR_VERSION: Final = 1
