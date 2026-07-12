"""Tests for diagnostics."""

from __future__ import annotations

from freezegun import freeze_time
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_sharing.diagnostics import (
    async_get_config_entry_diagnostics,
)


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_diagnostics_contains_useful_data(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Test diagnostics contain useful data and no unsafe fields."""
    entry = setup_integration
    manager = entry.runtime_data.manager
    await manager.async_process_now()

    result = await async_get_config_entry_diagnostics(hass, entry)
    assert "entry" in result
    assert "runtime" in result
    assert result["runtime"]["processed_intervals"] == 1
    assert result["entry"]["data"]["grid_import_entity"] == "**REDACTED**"
    assert result["runtime"]["last_interval"] is not None
