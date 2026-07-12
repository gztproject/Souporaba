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

from custom_components.energy_sharing.const import (
    CONF_ALLOCATION_PERCENTAGE_MODE,
    CONF_ALLOCATION_PERCENTAGE_SOURCE,
    CONF_ALLOCATION_TOLERANCE_KWH,
    CONF_ALLOCATION_TOLERANCE_PCT,
    CONF_FIXED_ALLOCATION_PERCENTAGE,
    CONF_RECONCILIATION_FAILURE_MODE,
    CONF_REPORTED_ALLOCATION_SOURCE,
    PERCENTAGE_MODE_FIXED,
    RECONCILIATION_MATCHED,
    RECONCILIATION_MISMATCH_WARN,
    RECONCILIATION_MODE_SKIP_INTERVAL,
    RECONCILIATION_MODE_WARN,
)
from custom_components.energy_sharing.helpers import (
    get_expected_interval_end,
    interval_id_from_reset,
)
from tests.conftest import set_interval_sources


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_direct_provider_export_used_as_authoritative_input(
    setup_integration: MockConfigEntry,
) -> None:
    """Test provider export is read directly, not reconstructed."""
    manager = setup_integration.runtime_data.manager
    result = await manager.async_process_now()
    assert result == "processed"

    last = manager.data.last_interval
    assert last is not None
    assert last.provider_exported_kwh == pytest.approx(10.0)
    assert last.calculated_allocated_kwh == pytest.approx(0.7)
    assert last.receiver_imported_kwh == pytest.approx(1.0)


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_provider_export_not_reconstructed_from_reported_allocation(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    provider_export_entity: str,
    receiver_import_entity: str,
    reported_allocation_entity: str,
    interval_end: datetime,
) -> None:
    """Test provider export is never derived from reported allocation."""
    hass.config_entries.async_update_entry(
        setup_integration,
        options={
            **setup_integration.options,
            CONF_REPORTED_ALLOCATION_SOURCE: reported_allocation_entity,
        },
    )
    manager = setup_integration.runtime_data.manager
    manager.entry = setup_integration
    manager.async_reconfigure()

    set_interval_sources(
        hass,
        provider_export_entity=provider_export_entity,
        receiver_import_entity=receiver_import_entity,
        interval_end=interval_end,
        provider_export_kwh=10.0,
        receiver_import_kwh=1.0,
        reported_allocation_entity=reported_allocation_entity,
        reported_allocated_kwh=0.7,
    )

    await manager.async_process_now()
    last = manager.data.last_interval
    assert last is not None
    assert last.provider_exported_kwh == pytest.approx(10.0)
    assert last.reported_allocated_kwh == pytest.approx(0.7)


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_calculation_at_seven_percent(
    setup_integration: MockConfigEntry,
) -> None:
    """Test correct calculation at 7%."""
    await setup_integration.runtime_data.manager.async_process_now()
    last = setup_integration.runtime_data.manager.data.last_interval
    assert last is not None
    assert last.allocation_percentage == pytest.approx(7.0)
    assert last.calculated_allocated_kwh == pytest.approx(0.7)


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_calculation_at_another_percentage(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    percentage_entity: str,
) -> None:
    """Test correct calculation at another percentage."""
    hass.states.async_set(percentage_entity, "10")
    await setup_integration.runtime_data.manager.async_process_now()
    last = setup_integration.runtime_data.manager.data.last_interval
    assert last is not None
    assert last.calculated_allocated_kwh == pytest.approx(1.0)


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_fixed_percentage_mode(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """Test fixed percentage mode."""
    hass.config_entries.async_update_entry(
        setup_integration,
        options={
            **setup_integration.options,
            CONF_ALLOCATION_PERCENTAGE_MODE: PERCENTAGE_MODE_FIXED,
            CONF_FIXED_ALLOCATION_PERCENTAGE: 10.0,
            CONF_ALLOCATION_PERCENTAGE_SOURCE: None,
        },
    )
    manager = setup_integration.runtime_data.manager
    manager.entry = setup_integration
    await manager.async_process_now()
    last = manager.data.last_interval
    assert last is not None
    assert last.allocation_percentage == pytest.approx(10.0)
    assert last.allocation_percentage_source is None


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_percentage_entity_mode_persists_with_interval(
    setup_integration: MockConfigEntry,
    percentage_entity: str,
) -> None:
    """Test percentage entity mode persists effective percentage."""
    await setup_integration.runtime_data.manager.async_process_now()
    last = setup_integration.runtime_data.manager.data.last_interval
    assert last is not None
    assert last.allocation_percentage_source == percentage_entity


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_required_share_above_100_ideal_capped(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    provider_export_entity: str,
    receiver_import_entity: str,
    interval_end: datetime,
) -> None:
    """Test required share above 100 while ideal is capped."""
    set_interval_sources(
        hass,
        provider_export_entity=provider_export_entity,
        receiver_import_entity=receiver_import_entity,
        interval_end=interval_end,
        provider_export_kwh=1.0,
        receiver_import_kwh=20.0,
    )
    await setup_integration.runtime_data.manager.async_process_now()
    last = setup_integration.runtime_data.manager.data.last_interval
    assert last is not None
    assert last.required_share_pct == pytest.approx(2000.0)
    assert last.ideal_share_pct == pytest.approx(100.0)


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_optional_reported_allocation_absent(
    setup_integration: MockConfigEntry,
) -> None:
    """Test processing without optional reported allocation."""
    await setup_integration.runtime_data.manager.async_process_now()
    last = setup_integration.runtime_data.manager.data.last_interval
    assert last is not None
    assert last.reported_allocated_kwh is None
    assert last.reconciliation_status == "not_configured"


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_reported_allocation_matches_calculated(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    provider_export_entity: str,
    receiver_import_entity: str,
    reported_allocation_entity: str,
    interval_end: datetime,
) -> None:
    """Test reported allocation matching calculated allocation."""
    hass.config_entries.async_update_entry(
        setup_integration,
        options={
            **setup_integration.options,
            CONF_REPORTED_ALLOCATION_SOURCE: reported_allocation_entity,
        },
    )
    manager = setup_integration.runtime_data.manager
    manager.entry = setup_integration
    manager.async_reconfigure()

    set_interval_sources(
        hass,
        provider_export_entity=provider_export_entity,
        receiver_import_entity=receiver_import_entity,
        interval_end=interval_end,
        reported_allocation_entity=reported_allocation_entity,
        reported_allocated_kwh=0.7,
    )
    await manager.async_process_now()
    last = manager.data.last_interval
    assert last is not None
    assert last.reconciliation_status == RECONCILIATION_MATCHED


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_reconciliation_within_absolute_tolerance(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    provider_export_entity: str,
    receiver_import_entity: str,
    reported_allocation_entity: str,
    interval_end: datetime,
) -> None:
    """Test reconciliation within absolute tolerance."""
    hass.config_entries.async_update_entry(
        setup_integration,
        options={
            **setup_integration.options,
            CONF_REPORTED_ALLOCATION_SOURCE: reported_allocation_entity,
            CONF_ALLOCATION_TOLERANCE_KWH: 0.05,
            CONF_ALLOCATION_TOLERANCE_PCT: 0.0,
        },
    )
    manager = setup_integration.runtime_data.manager
    manager.entry = setup_integration
    manager.async_reconfigure()

    set_interval_sources(
        hass,
        provider_export_entity=provider_export_entity,
        receiver_import_entity=receiver_import_entity,
        interval_end=interval_end,
        reported_allocation_entity=reported_allocation_entity,
        reported_allocated_kwh=0.72,
    )
    await manager.async_process_now()
    assert manager.data.last_interval.reconciliation_status == RECONCILIATION_MATCHED


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_reconciliation_fails_warn_mode(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    provider_export_entity: str,
    receiver_import_entity: str,
    reported_allocation_entity: str,
    interval_end: datetime,
) -> None:
    """Test reconciliation failure in warn mode still processes."""
    hass.config_entries.async_update_entry(
        setup_integration,
        options={
            **setup_integration.options,
            CONF_REPORTED_ALLOCATION_SOURCE: reported_allocation_entity,
            CONF_RECONCILIATION_FAILURE_MODE: RECONCILIATION_MODE_WARN,
            CONF_ALLOCATION_TOLERANCE_KWH: 0.001,
            CONF_ALLOCATION_TOLERANCE_PCT: 0.0,
        },
    )
    manager = setup_integration.runtime_data.manager
    manager.entry = setup_integration
    manager.async_reconfigure()

    set_interval_sources(
        hass,
        provider_export_entity=provider_export_entity,
        receiver_import_entity=receiver_import_entity,
        interval_end=interval_end,
        reported_allocation_entity=reported_allocation_entity,
        reported_allocated_kwh=0.5,
    )
    assert await manager.async_process_now() == "processed"
    last = manager.data.last_interval
    assert last.reconciliation_status == RECONCILIATION_MISMATCH_WARN
    assert manager.data.processed_intervals == 1


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_reconciliation_fails_skip_interval_mode(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    provider_export_entity: str,
    receiver_import_entity: str,
    reported_allocation_entity: str,
    interval_end: datetime,
) -> None:
    """Test reconciliation failure in skip_interval mode."""
    hass.config_entries.async_update_entry(
        setup_integration,
        options={
            **setup_integration.options,
            CONF_REPORTED_ALLOCATION_SOURCE: reported_allocation_entity,
            CONF_RECONCILIATION_FAILURE_MODE: RECONCILIATION_MODE_SKIP_INTERVAL,
            CONF_ALLOCATION_TOLERANCE_KWH: 0.001,
            CONF_ALLOCATION_TOLERANCE_PCT: 0.0,
        },
    )
    manager = setup_integration.runtime_data.manager
    manager.entry = setup_integration
    manager.async_reconfigure()

    set_interval_sources(
        hass,
        provider_export_entity=provider_export_entity,
        receiver_import_entity=receiver_import_entity,
        interval_end=interval_end,
        reported_allocation_entity=reported_allocation_entity,
        reported_allocated_kwh=0.5,
    )
    result = await manager.async_process_now()
    assert result.startswith("skipped:reconciliation_mismatch_skip")
    assert manager.data.processed_intervals == 0
    assert manager.data.reconciliation_mismatch_count == 1


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_optional_source_different_interval(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    provider_export_entity: str,
    receiver_import_entity: str,
    reported_allocation_entity: str,
    interval_end: datetime,
) -> None:
    """Test optional reported source on a different interval is rejected."""
    hass.config_entries.async_update_entry(
        setup_integration,
        options={
            **setup_integration.options,
            CONF_REPORTED_ALLOCATION_SOURCE: reported_allocation_entity,
        },
    )
    manager = setup_integration.runtime_data.manager
    manager.entry = setup_integration
    manager.async_reconfigure()

    set_interval_sources(
        hass,
        provider_export_entity=provider_export_entity,
        receiver_import_entity=receiver_import_entity,
        interval_end=interval_end,
    )
    different_end = datetime(
        2026, 7, 12, 14, 45, 0, tzinfo=dt_util.get_time_zone("Europe/Ljubljana")
    )
    hass.states.async_set(
        reported_allocation_entity,
        "0",
        attributes={
            "last_period": 0.7,
            "last_reset": different_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )

    with patch.object(
        type(manager), "max_wait", new_callable=PropertyMock, return_value=0
    ):
        result = await manager.async_process_now()
    assert result.startswith("skipped:")


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_required_sources_different_intervals(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    provider_export_entity: str,
    receiver_import_entity: str,
    interval_end: datetime,
) -> None:
    """Test required sources on different intervals are rejected."""
    manager = setup_integration.runtime_data.manager
    different_end = datetime(
        2026, 7, 12, 14, 45, 0, tzinfo=dt_util.get_time_zone("Europe/Ljubljana")
    )
    hass.states.async_set(
        provider_export_entity,
        "0",
        attributes={
            "last_period": 10.0,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    hass.states.async_set(
        receiver_import_entity,
        "0",
        attributes={
            "last_period": 1.0,
            "last_reset": different_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )

    with patch.object(
        type(manager), "max_wait", new_callable=PropertyMock, return_value=0
    ):
        result = await manager.async_process_now()
    assert result.startswith("skipped:")


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_wh_inputs_converted(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    provider_export_entity: str,
    receiver_import_entity: str,
    interval_end: datetime,
) -> None:
    """Test Wh inputs are converted to kWh."""
    set_interval_sources(
        hass,
        provider_export_entity=provider_export_entity,
        receiver_import_entity=receiver_import_entity,
        interval_end=interval_end,
        provider_export_kwh=10000.0,
        receiver_import_kwh=1000.0,
        unit="Wh",
    )
    await setup_integration.runtime_data.manager.async_process_now()
    last = setup_integration.runtime_data.manager.data.last_interval
    assert last is not None
    assert last.provider_exported_kwh == pytest.approx(10.0)
    assert last.receiver_imported_kwh == pytest.approx(1.0)


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_unsupported_unit_rejected(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    provider_export_entity: str,
    receiver_import_entity: str,
    interval_end: datetime,
) -> None:
    """Test unsupported units are rejected."""
    hass.states.async_set(
        provider_export_entity,
        "0",
        attributes={
            "last_period": 10.0,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": "bananas",
        },
    )
    result = await setup_integration.runtime_data.manager.async_process_now()
    assert result == "skipped:unsupported_energy_unit"


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_missing_last_period_rejected(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    provider_export_entity: str,
    interval_end: datetime,
) -> None:
    """Test missing last_period is rejected."""
    hass.states.async_set(
        provider_export_entity,
        "0",
        attributes={
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    result = await setup_integration.runtime_data.manager.async_process_now()
    assert result == "skipped:last_period_missing"


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_missing_last_reset_rejected(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    provider_export_entity: str,
) -> None:
    """Test missing last_reset is rejected."""
    hass.states.async_set(
        provider_export_entity,
        "0",
        attributes={
            "last_period": 10.0,
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    result = await setup_integration.runtime_data.manager.async_process_now()
    assert result == "skipped:last_reset_missing"


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_zero_provider_export(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    provider_export_entity: str,
    receiver_import_entity: str,
    interval_end: datetime,
) -> None:
    """Test zero provider export."""
    set_interval_sources(
        hass,
        provider_export_entity=provider_export_entity,
        receiver_import_entity=receiver_import_entity,
        interval_end=interval_end,
        provider_export_kwh=0.0,
        receiver_import_kwh=1.0,
    )
    await setup_integration.runtime_data.manager.async_process_now()
    last = setup_integration.runtime_data.manager.data.last_interval
    assert last.calculated_allocated_kwh == 0.0
    assert last.required_share_pct is None


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_zero_receiver_import(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    provider_export_entity: str,
    receiver_import_entity: str,
    interval_end: datetime,
) -> None:
    """Test zero receiver import."""
    set_interval_sources(
        hass,
        provider_export_entity=provider_export_entity,
        receiver_import_entity=receiver_import_entity,
        interval_end=interval_end,
        provider_export_kwh=10.0,
        receiver_import_kwh=0.0,
    )
    await setup_integration.runtime_data.manager.async_process_now()
    last = setup_integration.runtime_data.manager.data.last_interval
    assert last.used_shared_kwh == 0.0
    assert last.consumption_coverage_pct is None


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_zero_allocation_percentage_skipped(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    percentage_entity: str,
) -> None:
    """Test zero allocation percentage causes skip."""
    hass.states.async_set(percentage_entity, "0")
    result = await setup_integration.runtime_data.manager.async_process_now()
    assert result == "skipped:percentage_zero"


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_duplicate_interval_protection_survives_restart(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """Test duplicate interval protection survives restart."""
    manager = setup_integration.runtime_data.manager
    await manager.async_process_now()
    totals = manager.data.cumulative_receiver_import

    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(setup_integration.entry_id)
    await hass.async_block_till_done()

    reloaded = setup_integration.runtime_data.manager
    assert reloaded.data.cumulative_receiver_import == totals
    assert await reloaded.async_process_now() == "duplicate"


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_options_reload_does_not_duplicate_interval(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """Test options reload does not duplicate the latest interval."""
    manager = setup_integration.runtime_data.manager
    await manager.async_process_now()
    processed = manager.data.processed_intervals

    hass.config_entries.async_update_entry(
        setup_integration,
        options={**setup_integration.options, "processing_delay": 12},
    )
    await hass.async_block_till_done()

    reloaded = setup_integration.runtime_data.manager
    assert await reloaded.async_process_now() == "duplicate"
    assert reloaded.data.processed_intervals == processed


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_inputs_ready_during_retry_processed_once(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    provider_export_entity: str,
    receiver_import_entity: str,
    interval_end: datetime,
) -> None:
    """Test inputs becoming ready during retry are processed once."""
    tz = dt_util.get_time_zone("Europe/Ljubljana")
    provider_reset = interval_end
    receiver_reset = datetime(2026, 7, 12, 15, 0, 10, tzinfo=tz)

    hass.states.async_set(
        provider_export_entity,
        "0",
        attributes={
            "last_period": 10.0,
            "last_reset": provider_reset.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    hass.states.async_set(
        receiver_import_entity,
        "0",
        attributes={
            "last_period": 1.0,
            "last_reset": receiver_reset.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )

    manager = setup_integration.runtime_data.manager
    first = await manager._async_attempt_processing("manual")
    assert first.startswith("retrying:")

    set_interval_sources(
        hass,
        provider_export_entity=provider_export_entity,
        receiver_import_entity=receiver_import_entity,
        interval_end=interval_end,
    )
    second = await manager._async_attempt_processing("retry")
    assert second == "processed"
    assert manager.data.processed_intervals == 1


@freeze_time("2026-07-12 15:45:10+02:00")
async def test_missed_intervals_not_reconstructed(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    provider_export_entity: str,
    receiver_import_entity: str,
) -> None:
    """Test missed intervals are not falsely reconstructed."""
    manager = setup_integration.runtime_data.manager
    tz = dt_util.get_time_zone("Europe/Ljubljana")
    first_end = get_expected_interval_end(
        datetime(2026, 7, 12, 15, 0, 10, tzinfo=tz),
        15,
    )
    manager.data.last_processed_interval_id = interval_id_from_reset(
        dt_util.as_utc(first_end)
    )
    manager.data.processed_intervals = 1
    manager.data.cumulative_receiver_import = 1.0

    later_end = get_expected_interval_end(dt_util.now(), 15)
    set_interval_sources(
        hass,
        provider_export_entity=provider_export_entity,
        receiver_import_entity=receiver_import_entity,
        interval_end=later_end,
        provider_export_kwh=20.0,
        receiver_import_kwh=2.0,
    )
    manager._clear_retry_state()
    assert await manager.async_process_now() == "processed"
    assert manager.data.skipped_intervals >= 2
    assert manager.data.last_interval.receiver_imported_kwh == pytest.approx(2.0)
