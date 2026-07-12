"""Diagnostics support for Energy Sharing."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import EnergySharingConfigEntry
from .const import (
    CONF_ALLOCATION_PERCENTAGE_SOURCE,
    CONF_PROVIDER_EXPORT_SOURCE,
    CONF_RECEIVER_IMPORT_SOURCE,
    CONF_REPORTED_ALLOCATION_SOURCE,
)

TO_REDACT = {
    CONF_PROVIDER_EXPORT_SOURCE,
    CONF_RECEIVER_IMPORT_SOURCE,
    CONF_REPORTED_ALLOCATION_SOURCE,
    CONF_ALLOCATION_PERCENTAGE_SOURCE,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EnergySharingConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    manager = entry.runtime_data.manager
    snapshot = manager.get_diagnostics_snapshot()
    last_interval = snapshot.get("last_interval")
    reconciliation = None
    if last_interval:
        reconciliation = {
            "status": last_interval.get("reconciliation_status"),
            "reported_allocated_kwh": last_interval.get("reported_allocated_kwh"),
            "calculated_allocated_kwh": last_interval.get("calculated_allocated_kwh"),
            "allocation_difference_kwh": last_interval.get(
                "allocation_difference_kwh"
            ),
            "allocation_difference_pct": last_interval.get(
                "allocation_difference_pct"
            ),
            "reported_allocation_source": last_interval.get(
                "reported_allocation_source"
            ),
        }

    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
            "unique_id": entry.unique_id,
        },
        "runtime": snapshot,
        "reconciliation": reconciliation,
        "reconciliation_mismatch_count": snapshot.get(
            "reconciliation_mismatch_count"
        ),
    }
