"""Diagnostics support for Energy Sharing."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import EnergySharingConfigEntry
from .const import (
    CONF_GRID_IMPORT_ENTITY,
    CONF_PERCENTAGE_ENTITY,
    CONF_SHARED_ENERGY_ENTITY,
)

TO_REDACT = {
    CONF_GRID_IMPORT_ENTITY,
    CONF_SHARED_ENERGY_ENTITY,
    CONF_PERCENTAGE_ENTITY,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EnergySharingConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    manager = entry.runtime_data.manager
    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
            "unique_id": entry.unique_id,
        },
        "runtime": manager.get_diagnostics_snapshot(),
    }
