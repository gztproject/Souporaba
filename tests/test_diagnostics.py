"""Tests for diagnostics."""

from __future__ import annotations

from freezegun import freeze_time
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_sharing.diagnostics import (
    async_get_config_entry_diagnostics,
)
from tests.conftest import set_cumulative_sources


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_diagnostics_include_snapshots_and_modes(
    hass: HomeAssistant,
    setup_export_and_percentage: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
    provider_export_total_entity: str,
) -> None:
    entry = setup_export_and_percentage
    manager = entry.runtime_data.manager
    await manager.async_process_now()
    set_cumulative_sources(
        hass,
        receiver_import_total_entity=receiver_import_total_entity,
        shared_energy_total_entity=shared_energy_total_entity,
        receiver_total=101.0,
        shared_total=10.7,
        provider_export_total_entity=provider_export_total_entity,
        provider_total=210.0,
    )
    await manager.async_process_now()

    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["runtime"]["operating_mode"] == "export_and_percentage"
    assert result["runtime"]["previous_snapshot"] is not None
    assert result["runtime"]["last_interval"] is not None
    assert result["entry"]["data"]["receiver_import_total_source"] == "**REDACTED**"
