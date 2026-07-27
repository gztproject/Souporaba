"""Tests for the settlement manager."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from freezegun import freeze_time
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_sharing.const import (
    CONF_ALLOCATION_TOLERANCE_KWH,
    CONF_ALLOCATION_TOLERANCE_PCT,
    CONF_RECONCILIATION_FAILURE_MODE,
    EXPORT_TYPE_INFERRED,
    EXPORT_TYPE_MEASURED,
    MODE_EXPORT_AND_PERCENTAGE,
    MODE_EXPORT_ONLY,
    MODE_PERCENTAGE_ONLY,
    RECONCILIATION_MATCHED,
    RECONCILIATION_MISMATCH_WARN,
    RECONCILIATION_MODE_SKIP_INTERVAL,
    RECONCILIATION_MODE_WARN,
)
from tests.conftest import set_cumulative_sources


async def _establish_baseline_and_process(
    manager,
    hass: HomeAssistant,
    entry: MockConfigEntry,
    receiver_entity: str,
    shared_entity: str,
    *,
    provider_entity: str | None = None,
    receiver_total: float,
    shared_total: float,
    provider_total: float | None = None,
    interval_end: datetime,
) -> str:
    set_cumulative_sources(
        hass,
        receiver_import_total_entity=receiver_entity,
        shared_energy_total_entity=shared_entity,
        receiver_total=receiver_total,
        shared_total=shared_total,
        provider_export_total_entity=provider_entity,
        provider_total=provider_total,
    )
    baseline = await manager.async_process_now()
    assert baseline == "baseline_initialized"

    set_cumulative_sources(
        hass,
        receiver_import_total_entity=receiver_entity,
        shared_energy_total_entity=shared_entity,
        receiver_total=receiver_total + 1.0,
        shared_total=shared_total + 0.7,
        provider_export_total_entity=provider_entity,
        provider_total=(provider_total + 10.0) if provider_total is not None else None,
    )
    return await manager.async_process_now()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_first_boundary_initializes_baseline(
    setup_percentage_only: MockConfigEntry,
) -> None:
    manager = setup_percentage_only.runtime_data.manager
    result = await manager.async_process_now()
    assert result == "baseline_initialized"
    assert manager.data.baseline_initialized is True
    assert manager.data.processed_intervals == 0
    assert manager.data.previous_snapshot is not None


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_next_boundary_calculates_deltas(
    hass: HomeAssistant,
    setup_percentage_only: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
) -> None:
    manager = setup_percentage_only.runtime_data.manager
    result = await _establish_baseline_and_process(
        manager,
        hass,
        setup_percentage_only,
        receiver_import_total_entity,
        shared_energy_total_entity,
        receiver_total=100.0,
        shared_total=10.0,
        interval_end=datetime(
            2026, 7, 12, 15, 0, 0, tzinfo=dt_util.get_time_zone("Europe/Ljubljana")
        ),
    )
    assert result == "processed"
    last = manager.data.last_interval
    assert last.receiver_import_interval_kwh == pytest.approx(1.0)
    assert last.shared_energy_interval_kwh == pytest.approx(0.7)


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_percentage_only_mode_inferred_export(
    hass: HomeAssistant,
    setup_percentage_only: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
) -> None:
    manager = setup_percentage_only.runtime_data.manager
    await _establish_baseline_and_process(
        manager,
        hass,
        setup_percentage_only,
        receiver_import_total_entity,
        shared_energy_total_entity,
        receiver_total=100.0,
        shared_total=10.0,
        interval_end=datetime(
            2026, 7, 12, 15, 0, 0, tzinfo=dt_util.get_time_zone("Europe/Ljubljana")
        ),
    )
    last = manager.data.last_interval
    assert last.operating_mode == MODE_PERCENTAGE_ONLY
    assert last.provider_export_source_type == EXPORT_TYPE_INFERRED
    assert last.provider_export_interval_kwh == pytest.approx(10.0)


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_export_only_mode(
    hass: HomeAssistant,
    mock_config_entry_export_only: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
    provider_export_total_entity: str,
) -> None:
    mock_config_entry_export_only.add_to_hass(hass)
    set_cumulative_sources(
        hass,
        receiver_import_total_entity=receiver_import_total_entity,
        shared_energy_total_entity=shared_energy_total_entity,
        receiver_total=100.0,
        shared_total=10.0,
        provider_export_total_entity=provider_export_total_entity,
        provider_total=200.0,
    )
    await hass.config_entries.async_setup(mock_config_entry_export_only.entry_id)
    await hass.async_block_till_done()
    manager = mock_config_entry_export_only.runtime_data.manager
    assert manager.operating_mode == MODE_EXPORT_ONLY

    await _establish_baseline_and_process(
        manager,
        hass,
        mock_config_entry_export_only,
        receiver_import_total_entity,
        shared_energy_total_entity,
        provider_entity=provider_export_total_entity,
        receiver_total=100.0,
        shared_total=10.0,
        provider_total=200.0,
        interval_end=datetime(
            2026, 7, 12, 15, 0, 0, tzinfo=dt_util.get_time_zone("Europe/Ljubljana")
        ),
    )
    last = manager.data.last_interval
    assert last.provider_export_source_type == EXPORT_TYPE_MEASURED
    assert last.effective_allocation_pct == pytest.approx(7.0)


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_export_and_percentage_mode(
    hass: HomeAssistant,
    setup_export_and_percentage: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
    provider_export_total_entity: str,
) -> None:
    manager = setup_export_and_percentage.runtime_data.manager
    assert manager.operating_mode == MODE_EXPORT_AND_PERCENTAGE
    await _establish_baseline_and_process(
        manager,
        hass,
        setup_export_and_percentage,
        receiver_import_total_entity,
        shared_energy_total_entity,
        provider_entity=provider_export_total_entity,
        receiver_total=100.0,
        shared_total=10.0,
        provider_total=200.0,
        interval_end=datetime(
            2026, 7, 12, 15, 0, 0, tzinfo=dt_util.get_time_zone("Europe/Ljubljana")
        ),
    )
    last = manager.data.last_interval
    assert last.expected_shared_kwh == pytest.approx(0.7)
    assert last.reconciliation_status == RECONCILIATION_MATCHED


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_receiver_counter_reset(
    hass: HomeAssistant,
    setup_percentage_only: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
) -> None:
    manager = setup_percentage_only.runtime_data.manager
    await manager.async_process_now()
    set_cumulative_sources(
        hass,
        receiver_import_total_entity=receiver_import_total_entity,
        shared_energy_total_entity=shared_energy_total_entity,
        receiver_total=50.0,
        shared_total=11.0,
    )
    result = await manager.async_process_now()
    assert result.startswith("skipped:counter_reset:receiver_import")
    assert manager.data.source_reset_count == 1


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_shared_counter_reset(
    hass: HomeAssistant,
    setup_percentage_only: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
) -> None:
    manager = setup_percentage_only.runtime_data.manager
    await manager.async_process_now()
    set_cumulative_sources(
        hass,
        receiver_import_total_entity=receiver_import_total_entity,
        shared_energy_total_entity=shared_energy_total_entity,
        receiver_total=101.0,
        shared_total=5.0,
    )
    result = await manager.async_process_now()
    assert result.startswith("skipped:counter_reset:shared_energy")


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_negative_source_rejected(
    hass: HomeAssistant,
    setup_percentage_only: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
) -> None:
    manager = setup_percentage_only.runtime_data.manager
    await manager.async_process_now()
    hass.states.async_set(
        receiver_import_total_entity,
        "-1",
        attributes={"unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR},
    )
    result = await manager.async_process_now()
    assert result == "skipped:source_not_numeric"


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_wh_to_kwh_conversion(
    hass: HomeAssistant,
    setup_percentage_only: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
) -> None:
    manager = setup_percentage_only.runtime_data.manager
    await manager.async_process_now()
    hass.states.async_set(
        receiver_import_total_entity,
        "101000",
        attributes={"unit_of_measurement": "Wh"},
    )
    hass.states.async_set(
        shared_energy_total_entity,
        "10700",
        attributes={"unit_of_measurement": "Wh"},
    )
    result = await manager.async_process_now()
    assert result == "processed"
    assert manager.data.last_interval.receiver_import_interval_kwh == pytest.approx(1.0)


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_duplicate_interval_protection(
    hass: HomeAssistant,
    setup_percentage_only: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
) -> None:
    manager = setup_percentage_only.runtime_data.manager
    await _establish_baseline_and_process(
        manager,
        hass,
        setup_percentage_only,
        receiver_import_total_entity,
        shared_energy_total_entity,
        receiver_total=100.0,
        shared_total=10.0,
        interval_end=datetime(
            2026, 7, 12, 15, 0, 0, tzinfo=dt_util.get_time_zone("Europe/Ljubljana")
        ),
    )
    assert await manager.async_process_now() == "duplicate"


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_restart_restores_snapshots(
    hass: HomeAssistant,
    setup_percentage_only: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
) -> None:
    manager = setup_percentage_only.runtime_data.manager
    await _establish_baseline_and_process(
        manager,
        hass,
        setup_percentage_only,
        receiver_import_total_entity,
        shared_energy_total_entity,
        receiver_total=100.0,
        shared_total=10.0,
        interval_end=datetime(
            2026, 7, 12, 15, 0, 0, tzinfo=dt_util.get_time_zone("Europe/Ljubljana")
        ),
    )
    snapshot = manager.data.previous_snapshot
    processed = manager.data.processed_intervals

    await hass.config_entries.async_unload(setup_percentage_only.entry_id)
    await hass.async_block_till_done()
    await hass.config_entries.async_setup(setup_percentage_only.entry_id)
    await hass.async_block_till_done()

    reloaded = setup_percentage_only.runtime_data.manager
    assert reloaded.data.previous_snapshot.interval_id == snapshot.interval_id
    assert reloaded.data.processed_intervals == processed
    assert await reloaded.async_process_now() == "duplicate"


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_skipped_interval_does_not_merge_into_next(
    hass: HomeAssistant,
    setup_export_and_percentage: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
    provider_export_total_entity: str,
) -> None:
    hass.config_entries.async_update_entry(
        setup_export_and_percentage,
        options={
            **setup_export_and_percentage.options,
            CONF_RECONCILIATION_FAILURE_MODE: RECONCILIATION_MODE_SKIP_INTERVAL,
            CONF_ALLOCATION_TOLERANCE_KWH: 0.001,
            CONF_ALLOCATION_TOLERANCE_PCT: 0.0,
        },
    )
    manager = setup_export_and_percentage.runtime_data.manager
    manager.entry = setup_export_and_percentage
    await manager.async_process_now()

    with freeze_time("2026-07-12 15:15:10+02:00"):
        set_cumulative_sources(
            hass,
            receiver_import_total_entity=receiver_import_total_entity,
            shared_energy_total_entity=shared_energy_total_entity,
            receiver_total=101.0,
            shared_total=10.5,
            provider_export_total_entity=provider_export_total_entity,
            provider_total=210.0,
        )
        skip_result = await manager.async_process_now()
    assert skip_result.startswith("skipped:reconciliation_mismatch")
    snapshot_after_skip = manager.data.previous_snapshot.receiver_import_total_kwh

    with freeze_time("2026-07-12 15:30:10+02:00"):
        set_cumulative_sources(
            hass,
            receiver_import_total_entity=receiver_import_total_entity,
            shared_energy_total_entity=shared_energy_total_entity,
            receiver_total=102.0,
            shared_total=11.2,
            provider_export_total_entity=provider_export_total_entity,
            provider_total=220.0,
        )
        next_result = await manager.async_process_now()
    assert next_result == "processed"
    last = manager.data.last_interval
    assert last.receiver_import_interval_kwh == pytest.approx(1.0)
    assert snapshot_after_skip == pytest.approx(101.0)


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_reconciliation_warn_mode(
    hass: HomeAssistant,
    setup_export_and_percentage: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
    provider_export_total_entity: str,
) -> None:
    hass.config_entries.async_update_entry(
        setup_export_and_percentage,
        options={
            **setup_export_and_percentage.options,
            CONF_RECONCILIATION_FAILURE_MODE: RECONCILIATION_MODE_WARN,
            CONF_ALLOCATION_TOLERANCE_KWH: 0.001,
            CONF_ALLOCATION_TOLERANCE_PCT: 0.0,
        },
    )
    manager = setup_export_and_percentage.runtime_data.manager
    manager.entry = setup_export_and_percentage
    await manager.async_process_now()

    with freeze_time("2026-07-12 15:15:10+02:00"):
        set_cumulative_sources(
            hass,
            receiver_import_total_entity=receiver_import_total_entity,
            shared_energy_total_entity=shared_energy_total_entity,
            receiver_total=101.0,
            shared_total=10.2,
            provider_export_total_entity=provider_export_total_entity,
            provider_total=210.0,
        )
        result = await manager.async_process_now()
    assert result == "processed"
    assert (
        manager.data.last_interval.reconciliation_status
        == RECONCILIATION_MISMATCH_WARN
    )


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_reinitialize_baseline(
    hass: HomeAssistant,
    setup_percentage_only: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
) -> None:
    manager = setup_percentage_only.runtime_data.manager
    await manager.async_process_now()
    set_cumulative_sources(
        hass,
        receiver_import_total_entity=receiver_import_total_entity,
        shared_energy_total_entity=shared_energy_total_entity,
        receiver_total=150.0,
        shared_total=20.0,
    )
    result = await manager.async_reinitialize_baseline()
    assert result == "baseline_reinitialized"
    assert manager.data.previous_snapshot.receiver_import_total_kwh == pytest.approx(
        150.0
    )
    assert manager.data.last_processed_interval_id is None


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_cumulative_totals_never_decrease(
    hass: HomeAssistant,
    setup_percentage_only: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
) -> None:
    manager = setup_percentage_only.runtime_data.manager
    await _establish_baseline_and_process(
        manager,
        hass,
        setup_percentage_only,
        receiver_import_total_entity,
        shared_energy_total_entity,
        receiver_total=100.0,
        shared_total=10.0,
        interval_end=datetime(
            2026, 7, 12, 15, 0, 0, tzinfo=dt_util.get_time_zone("Europe/Ljubljana")
        ),
    )
    first_total = manager.data.cumulative_receiver_import
    with freeze_time("2026-07-12 15:15:10+02:00"):
        set_cumulative_sources(
            hass,
            receiver_import_total_entity=receiver_import_total_entity,
            shared_energy_total_entity=shared_energy_total_entity,
            receiver_total=102.0,
            shared_total=11.4,
        )
        await manager.async_process_now()
    assert manager.data.cumulative_receiver_import >= first_total


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_setup_recovers_from_invalid_stored_data(
    hass: HomeAssistant,
    mock_config_entry_percentage_only: MockConfigEntry,
) -> None:
    mock_config_entry_percentage_only.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_percentage_only.entry_id)
    await hass.async_block_till_done()

    manager = mock_config_entry_percentage_only.runtime_data.manager
    manager.storage.async_load = AsyncMock(
        return_value={"version": 4, "last_interval": 123}
    )

    await manager.async_setup()
    assert manager.data.version == 4
