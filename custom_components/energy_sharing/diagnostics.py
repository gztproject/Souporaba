"""Diagnostics support for Energy Sharing."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import EnergySharingConfigEntry
from .const import (
    CONF_ACTIVE_LOADS,
    CONF_FIXED_ALLOCATION_PERCENTAGE,
    CONF_PROVIDER_EXPORT_TOTAL_SOURCE,
    CONF_RECEIVER_IMPORT_TOTAL_SOURCE,
    CONF_SHARED_ENERGY_TOTAL_SOURCE,
)

TO_REDACT = {
    CONF_RECEIVER_IMPORT_TOTAL_SOURCE,
    CONF_SHARED_ENERGY_TOTAL_SOURCE,
    CONF_PROVIDER_EXPORT_TOTAL_SOURCE,
    CONF_FIXED_ALLOCATION_PERCENTAGE,
    CONF_ACTIVE_LOADS,
}


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
            "unique_id": entry.unique_id,
        },
        "runtime": snapshot,
        "reconciliation": (
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
