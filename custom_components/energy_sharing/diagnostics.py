"""Diagnostics support for Energy Sharing."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.components.diagnostics.const import REDACTED
from homeassistant.core import HomeAssistant

from . import EnergySharingConfigEntry
from .const import (
    CONF_ACTIVE_LOAD_POWER_SENSOR_ENTITY_ID,
    CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID,
    CONF_ACTIVE_LOADS,
    CONF_ACTIVE_POWER_SENSOR_ENTITY_ID,
    CONF_ACTIVE_SWITCH_ENTITY_ID,
    CONF_ALLOCATION_PERCENTAGE_SOURCE,
    CONF_FIXED_ALLOCATION_PERCENTAGE,
    CONF_FIXED_PERCENTAGE,
    CONF_GRID_IMPORT_ENTITY,
    CONF_MONTHLY_PRODUCTION,
    CONF_PERCENTAGE_ENTITY,
    CONF_PROVIDER_EXPORT_SOURCE,
    CONF_PROVIDER_EXPORT_TOTAL_SOURCE,
    CONF_RECEIVER_IMPORT_SOURCE,
    CONF_RECEIVER_IMPORT_TOTAL_SOURCE,
    CONF_REPORTED_ALLOCATION_SOURCE,
    CONF_SHARED_ENERGY_ENTITY,
    CONF_SHARED_ENERGY_TOTAL_SOURCE,
    MONTHLY_PRODUCTION_OPTION_KEYS,
)

TO_REDACT = {
    CONF_RECEIVER_IMPORT_TOTAL_SOURCE,
    CONF_SHARED_ENERGY_TOTAL_SOURCE,
    CONF_PROVIDER_EXPORT_TOTAL_SOURCE,
    CONF_FIXED_ALLOCATION_PERCENTAGE,
    CONF_ACTIVE_LOADS,
    CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID,
    CONF_ACTIVE_LOAD_POWER_SENSOR_ENTITY_ID,
    CONF_MONTHLY_PRODUCTION,
    *MONTHLY_PRODUCTION_OPTION_KEYS.values(),
    # Legacy keys that entries created by older versions may still carry.
    CONF_PROVIDER_EXPORT_SOURCE,
    CONF_RECEIVER_IMPORT_SOURCE,
    CONF_REPORTED_ALLOCATION_SOURCE,
    CONF_GRID_IMPORT_ENTITY,
    CONF_SHARED_ENERGY_ENTITY,
    CONF_ALLOCATION_PERCENTAGE_SOURCE,
    CONF_PERCENTAGE_ENTITY,
    CONF_FIXED_PERCENTAGE,
    CONF_ACTIVE_SWITCH_ENTITY_ID,
    CONF_ACTIVE_POWER_SENSOR_ENTITY_ID,
}

# Runtime values are exported only when their key is listed here. Entity ids,
# source states and attributes, energy, power and percentage values, and any
# field added later are redacted by default.
RUNTIME_SAFE_KEYS = frozenset(
    {
        "operating_mode",
        "retry_deadline",
        "last_processed_interval_id",
        "processed_intervals",
        "skipped_intervals",
        "baseline_initialization_count",
        "source_reset_count",
        "invalid_reading_count",
        "reconciliation_mismatch_count",
        "last_updated",
        "interval_id",
        "interval_start",
        "interval_end",
        "processed_at",
        "timestamp",
        "source_key",
        "provider_export_source_type",
        "reconciliation_status",
        "settlement_accumulated",
        "seconds_remaining",
        "available_load_count",
        "configured_load_count",
        "estimated_load_count",
        "control_enabled",
        "calibration_in_progress",
        "calibration_last_finished_at",
        "calibrated_loads",
        "considered_loads",
        "prediction_sample_count",
        "priority",
        "enabled",
        "switch_is_on",
        "switch_available",
        "owns_switch",
        "accepting_power",
        "startup_probing",
        "idle_latched",
        "manually_excluded",
        "last_start_ts",
        "last_stop_ts",
        "sample_count",
        "excluded_dark_sample_count",
        "target_month",
        "deadline_date",
        "deadline_passed",
        "reference_month",
        "observation_start",
        "observation_end",
        "daylight_intervals",
        "production_curve_source",
        "fallback_used",
    }
)

# Status and reason codes are kept, but only their plain code segments; a
# segment carrying a value such as ``diff_kwh=0.1`` or an entity id is redacted.
RUNTIME_CODE_KEYS = frozenset({"status", "baseline_status", "reason", "skip_reason"})

_CODE_SEGMENT = re.compile(r"[a-z][a-z0-9_]*")


def _redact_code(value: Any) -> Any:
    if not isinstance(value, str):
        return REDACTED
    return ":".join(
        segment if _CODE_SEGMENT.fullmatch(segment) else REDACTED
        for segment in value.split(":")
    )


def _redact_runtime(value: Any, key: str | None = None) -> Any:
    """Return ``value`` with every field not known to be safe redacted."""
    if isinstance(value, Mapping):
        if key == "attributes" or not all(
            isinstance(item, str) and _CODE_SEGMENT.fullmatch(item) for item in value
        ):
            return REDACTED
        return {item: _redact_runtime(value[item], item) for item in value}
    if isinstance(value, list | tuple):
        return [_redact_runtime(item, key) for item in value]
    if value is None:
        return None
    if key in RUNTIME_CODE_KEYS:
        return _redact_code(value)
    if key in RUNTIME_SAFE_KEYS and isinstance(value, str | int | float | bool):
        return value
    return REDACTED


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EnergySharingConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    manager = entry.runtime_data.manager
    snapshot = manager.get_diagnostics_snapshot()
    last_interval = snapshot.get("last_interval")

    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
            "unique_id": REDACTED if entry.unique_id else None,
        },
        "runtime": _redact_runtime(snapshot),
        "reconciliation": _redact_runtime(
            {
                "status": last_interval.get("reconciliation_status"),
                "expected_shared_kwh": last_interval.get("expected_shared_kwh"),
                "actual_shared_kwh": last_interval.get("shared_energy_interval_kwh"),
                "allocation_difference_kwh": last_interval.get(
                    "allocation_difference_kwh"
                ),
                "allocation_difference_pct": last_interval.get(
                    "allocation_difference_pct"
                ),
            }
            if last_interval
            else None
        ),
    }
