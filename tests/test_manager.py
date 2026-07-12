"""Tests for the settlement manager."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import PropertyMock, patch

import pytest
from freezegun import freeze_time
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_sharing.helpers import (
    get_expected_interval_end,
    interval_id_from_end,
)


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_process_interval_shared_less_than_imported(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    grid_import_entity: str,
    shared_energy_entity: str,
) -> None:
    """Test calculation when shared is less than imported."""
    entry = setup_integration
    manager = entry.runtime_data.manager

    result = await manager.async_process_now()
    assert result == "processed"

    last = manager.data.last_interval
    assert last is not None
    assert last.imported_kwh == pytest.approx(1.0)
    assert last.shared_kwh == pytest.approx(0.2)
    assert last.used_kwh == pytest.approx(0.2)
    assert last.billable_kwh == pytest.approx(0.8)


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_process_interval_shared_greater_than_imported(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    grid_import_entity: str,
    shared_energy_entity: str,
) -> None:
    """Test calculation when shared is greater than imported."""
    interval_end = datetime(
        2026, 7, 12, 15, 0, 0, tzinfo=dt_util.get_time_zone("Europe/Ljubljana")
    )
    hass.states.async_set(
        grid_import_entity,
        "0",
        attributes={
            "last_period": 0.5,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    hass.states.async_set(
        shared_energy_entity,
        "0",
        attributes={
            "last_period": 1.0,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )

    manager = setup_integration.runtime_data.manager
    await manager.async_process_now()
    last = manager.data.last_interval
    assert last is not None
    assert last.used_kwh == pytest.approx(0.5)
    assert last.unused_kwh == pytest.approx(0.5)
    assert last.billable_kwh == pytest.approx(0.0)


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_wh_inputs_converted(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    grid_import_entity: str,
    shared_energy_entity: str,
) -> None:
    """Test Wh inputs are converted to kWh."""
    interval_end = datetime(
        2026, 7, 12, 15, 0, 0, tzinfo=dt_util.get_time_zone("Europe/Ljubljana")
    )
    hass.states.async_set(
        grid_import_entity,
        "0",
        attributes={
            "last_period": 1000.0,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": "Wh",
        },
    )
    hass.states.async_set(
        shared_energy_entity,
        "0",
        attributes={
            "last_period": 200.0,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": "Wh",
        },
    )

    manager = setup_integration.runtime_data.manager
    await manager.async_process_now()
    last = manager.data.last_interval
    assert last is not None
    assert last.imported_kwh == pytest.approx(1.0)
    assert last.shared_kwh == pytest.approx(0.2)


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_unsynchronized_resets_retry_then_skip(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    grid_import_entity: str,
    shared_energy_entity: str,
) -> None:
    """Test unsynchronized resets cause retry and eventual skip."""
    tz = dt_util.get_time_zone("Europe/Ljubljana")
    grid_reset = datetime(2026, 7, 12, 15, 0, 0, tzinfo=tz)
    shared_reset = datetime(2026, 7, 12, 15, 0, 10, tzinfo=tz)
    hass.states.async_set(
        grid_import_entity,
        "0",
        attributes={
            "last_period": 1.0,
            "last_reset": grid_reset.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    hass.states.async_set(
        shared_energy_entity,
        "0",
        attributes={
            "last_period": 0.2,
            "last_reset": shared_reset.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )

    manager = setup_integration.runtime_data.manager
    with patch.object(
        type(manager), "max_wait", new_callable=PropertyMock, return_value=0
    ):
        result = await manager.async_process_now()
    assert result.startswith("skipped:")
    assert manager.data.processed_intervals == 0
    assert manager.data.skipped_intervals == 1


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_inputs_ready_during_retry_processed_once(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    grid_import_entity: str,
    shared_energy_entity: str,
) -> None:
    """Test inputs becoming ready during retry are processed once."""
    tz = dt_util.get_time_zone("Europe/Ljubljana")
    grid_reset = datetime(2026, 7, 12, 15, 0, 0, tzinfo=tz)
    shared_reset = datetime(2026, 7, 12, 15, 0, 10, tzinfo=tz)
    interval_end = grid_reset

    hass.states.async_set(
        grid_import_entity,
        "0",
        attributes={
            "last_period": 1.0,
            "last_reset": grid_reset.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    hass.states.async_set(
        shared_energy_entity,
        "0",
        attributes={
            "last_period": 0.2,
            "last_reset": shared_reset.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )

    manager = setup_integration.runtime_data.manager
    first = await manager._async_attempt_processing("manual")
    assert first.startswith("retrying:")

    hass.states.async_set(
        shared_energy_entity,
        "0",
        attributes={
            "last_period": 0.2,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )

    second = await manager._async_attempt_processing("retry")
    assert second == "processed"
    assert manager.data.processed_intervals == 1
    assert await manager.async_process_now() == "duplicate"


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_duplicate_interval_not_processed_twice(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """Test the same interval cannot be processed twice."""
    manager = setup_integration.runtime_data.manager
    assert await manager.async_process_now() == "processed"
    assert await manager.async_process_now() == "duplicate"
    assert manager.data.processed_intervals == 1


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_reload_does_not_duplicate_totals(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """Test restart/reload does not duplicate totals."""
    manager = setup_integration.runtime_data.manager
    await manager.async_process_now()
    totals = manager.data.cumulative_imported

    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_setup(setup_integration.entry_id)
    await hass.async_block_till_done()

    reloaded = setup_integration.runtime_data.manager
    assert reloaded.data.cumulative_imported == totals
    assert await reloaded.async_process_now() == "duplicate"


@freeze_time("2026-07-12 15:45:10+02:00")
async def test_missed_intervals_not_reconstructed(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    grid_import_entity: str,
    shared_energy_entity: str,
) -> None:
    """Test missed intervals are not falsely reconstructed."""
    manager = setup_integration.runtime_data.manager
    tz = dt_util.get_time_zone("Europe/Ljubljana")
    first_end = get_expected_interval_end(
        datetime(2026, 7, 12, 15, 0, 10, tzinfo=tz),
        15,
    )
    manager.data.last_processed_interval_id = interval_id_from_end(first_end)
    manager.data.processed_intervals = 1
    manager.data.cumulative_imported = 1.0
    manager.data.cumulative_shared = 0.2
    manager.data.cumulative_used = 0.2
    manager.data.cumulative_billable = 0.8

    later_end = get_expected_interval_end(dt_util.now(), 15)
    for unsub in manager._entity_update_callbacks:
        unsub()
    manager._entity_update_callbacks.clear()
    hass.states.async_set(
        grid_import_entity,
        "0",
        attributes={
            "last_period": 2.0,
            "last_reset": later_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    hass.states.async_set(
        shared_energy_entity,
        "0",
        attributes={
            "last_period": 0.4,
            "last_reset": later_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    await hass.async_block_till_done()
    manager._clear_retry_state()

    assert await manager.async_process_now() == "processed"
    assert manager.data.processed_intervals == 2
    assert manager.data.skipped_intervals >= 2
    assert manager.data.last_interval is not None
    assert manager.data.last_interval.imported_kwh == pytest.approx(2.0)


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_percentage_zero_skipped(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    percentage_entity: str,
) -> None:
    """Test percentage zero causes skip."""
    hass.states.async_set(percentage_entity, "0")
    manager = setup_integration.runtime_data.manager
    result = await manager.async_process_now()
    assert result == "skipped:percentage_zero"


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_cumulative_totals_never_decrease(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    grid_import_entity: str,
    shared_energy_entity: str,
) -> None:
    """Test cumulative sensors never decrease during normal operation."""
    manager = setup_integration.runtime_data.manager
    await manager.async_process_now()
    first_total = manager.data.cumulative_imported

    tz = dt_util.get_time_zone("Europe/Ljubljana")
    next_end = datetime(2026, 7, 12, 15, 15, 0, tzinfo=tz)
    with freeze_time("2026-07-12 15:15:10+02:00"):
        hass.states.async_set(
            grid_import_entity,
            "0",
            attributes={
                "last_period": 0.5,
                "last_reset": next_end.isoformat(),
                "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
            },
        )
        hass.states.async_set(
            shared_energy_entity,
            "0",
            attributes={
                "last_period": 0.1,
                "last_reset": next_end.isoformat(),
                "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
            },
        )
        await manager.async_process_now()

    assert manager.data.cumulative_imported >= first_total


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_unload_removes_callbacks(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """Test integration unload removes listeners and scheduled callbacks."""
    manager = setup_integration.runtime_data.manager
    assert manager._unsub_schedule is None
    assert manager._entity_update_callbacks

    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert manager._entity_update_callbacks == []


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_reset_totals(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """Test reset totals action."""
    manager = setup_integration.runtime_data.manager
    await manager.async_process_now()
    assert manager.data.cumulative_imported > 0

    await manager.async_reset_totals()
    assert manager.data.cumulative_imported == 0.0
    assert manager.data.processed_intervals == 0
