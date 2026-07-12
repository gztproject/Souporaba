"""Constants for the Energy Sharing integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "energy_sharing"
MANUFACTURER: Final = "Energy Sharing"
MODEL: Final = "Internal interval settlement calculator"

# Required cumulative sources (config entry data)
CONF_RECEIVER_IMPORT_TOTAL_SOURCE: Final = "receiver_import_total_source"
CONF_SHARED_ENERGY_TOTAL_SOURCE: Final = "shared_energy_total_source"

# Conditional sources (options)
CONF_PROVIDER_EXPORT_TOTAL_SOURCE: Final = "provider_export_total_source"
CONF_FIXED_ALLOCATION_PERCENTAGE: Final = "fixed_allocation_percentage"

# Legacy keys (migration only)
CONF_PROVIDER_EXPORT_SOURCE: Final = "provider_export_source"
CONF_RECEIVER_IMPORT_SOURCE: Final = "receiver_import_source"
CONF_REPORTED_ALLOCATION_SOURCE: Final = "reported_allocation_source"
CONF_GRID_IMPORT_ENTITY: Final = "grid_import_entity"
CONF_SHARED_ENERGY_ENTITY: Final = "shared_energy_entity"
CONF_ALLOCATION_PERCENTAGE_MODE: Final = "allocation_percentage_mode"
CONF_ALLOCATION_PERCENTAGE_SOURCE: Final = "allocation_percentage_source"
CONF_PERCENTAGE_MODE: Final = "percentage_mode"
CONF_PERCENTAGE_ENTITY: Final = "percentage_entity"
CONF_FIXED_PERCENTAGE: Final = "fixed_percentage"

# Timing (options)
CONF_INTERVAL_MINUTES: Final = "interval_minutes"
CONF_PROCESSING_DELAY: Final = "processing_delay"
CONF_MAX_WAIT: Final = "max_wait"
CONF_RETRY_INTERVAL: Final = "retry_interval"
CONF_SOURCE_FRESHNESS_TOLERANCE: Final = "source_freshness_tolerance"

# Optional timestamp attribute names per source (options)
CONF_RECEIVER_TIMESTAMP_ATTR: Final = "receiver_timestamp_attr"
CONF_SHARED_TIMESTAMP_ATTR: Final = "shared_timestamp_attr"
CONF_PROVIDER_TIMESTAMP_ATTR: Final = "provider_timestamp_attr"

# Reconciliation (options)
CONF_ALLOCATION_TOLERANCE_KWH: Final = "allocation_tolerance_kwh"
CONF_ALLOCATION_TOLERANCE_PCT: Final = "allocation_tolerance_pct"
CONF_RECONCILIATION_FAILURE_MODE: Final = "reconciliation_failure_mode"

RECONCILIATION_MODE_WARN: Final = "warn"
RECONCILIATION_MODE_SKIP_INTERVAL: Final = "skip_interval"

# Operating modes
MODE_PERCENTAGE_ONLY: Final = "percentage_only"
MODE_EXPORT_ONLY: Final = "export_only"
MODE_EXPORT_AND_PERCENTAGE: Final = "export_and_percentage"

# Provider export source types
EXPORT_TYPE_MEASURED: Final = "measured"
EXPORT_TYPE_INFERRED: Final = "inferred"
EXPORT_TYPE_NONE: Final = "none"

DEFAULT_NAME: Final = "Energy Sharing"
DEFAULT_INTERVAL_MINUTES: Final = 15
DEFAULT_PROCESSING_DELAY: Final = 10
DEFAULT_MAX_WAIT: Final = 60
DEFAULT_RETRY_INTERVAL: Final = 5
DEFAULT_SOURCE_FRESHNESS_TOLERANCE: Final = 300
DEFAULT_FIXED_ALLOCATION_PERCENTAGE: Final = 7.0
DEFAULT_ALLOCATION_TOLERANCE_KWH: Final = 0.01
DEFAULT_ALLOCATION_TOLERANCE_PCT: Final = 5.0
DEFAULT_RECONCILIATION_FAILURE_MODE: Final = RECONCILIATION_MODE_WARN

SUPPORTED_ENERGY_UNITS: Final = frozenset({"Wh", "kWh"})

MIN_INTERVAL_MINUTES: Final = 1
MAX_INTERVAL_MINUTES: Final = 60
MIN_PROCESSING_DELAY: Final = 0
MAX_PROCESSING_DELAY: Final = 300
MIN_MAX_WAIT: Final = 10
MAX_MAX_WAIT: Final = 600
MIN_RETRY_INTERVAL: Final = 1
MAX_RETRY_INTERVAL: Final = 60
MIN_SOURCE_FRESHNESS_TOLERANCE: Final = 30
MAX_SOURCE_FRESHNESS_TOLERANCE: Final = 3600
MIN_ALLOCATION_PERCENTAGE: Final = 0.01
MAX_ALLOCATION_PERCENTAGE: Final = 100.0

STORAGE_VERSION: Final = 3
STORAGE_KEY: Final = "energy_sharing.storage"

SERVICE_PROCESS_NOW: Final = "process_now"
SERVICE_RESET_TOTALS: Final = "reset_totals"
SERVICE_REINITIALIZE_BASELINE: Final = "reinitialize_baseline"
SERVICE_CONFIRM: Final = "confirm"

# Processing statuses
STATUS_INITIALIZING_BASELINE: Final = "initializing_baseline"
STATUS_WAITING_FOR_BOUNDARY: Final = "waiting_for_boundary"
STATUS_WAITING_FOR_SOURCES: Final = "waiting_for_sources"
STATUS_PROCESSING: Final = "processing"
STATUS_READY: Final = "ready"
STATUS_SOURCE_UNAVAILABLE: Final = "source_unavailable"
STATUS_INVALID_SOURCE_VALUE: Final = "invalid_source_value"
STATUS_SOURCE_COUNTER_RESET: Final = "source_counter_reset"
STATUS_RECONCILIATION_WARNING: Final = "reconciliation_warning"
STATUS_INTERVAL_SKIPPED: Final = "interval_skipped"

# Reconciliation statuses
RECONCILIATION_MATCHED: Final = "matched"
RECONCILIATION_NOT_CONFIGURED: Final = "not_configured"
RECONCILIATION_MISMATCH_WARN: Final = "mismatch_warn"
RECONCILIATION_MISMATCH_SKIP: Final = "mismatch_skip"

# Baseline statuses
BASELINE_NOT_INITIALIZED: Final = "not_initialized"
BASELINE_INITIALIZED: Final = "initialized"

CONFIG_ENTRY_VERSION: Final = 3
CONFIG_ENTRY_MINOR_VERSION: Final = 1
