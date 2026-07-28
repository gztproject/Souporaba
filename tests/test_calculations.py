"""Tests for settlement calculations."""

from __future__ import annotations

import pytest

from custom_components.energy_sharing.const import (
    EXPORT_TYPE_INFERRED,
    EXPORT_TYPE_MEASURED,
    MODE_EXPORT_AND_PERCENTAGE,
    MODE_EXPORT_ONLY,
    MODE_PERCENTAGE_ONLY,
)
from custom_components.energy_sharing.models import (
    StorageData,
    calculate_interval_delta,
    calculate_settlement,
    clamp,
    evaluate_reconciliation,
    migrate_storage,
    resolve_operating_mode,
)


def test_resolve_operating_modes() -> None:
    assert resolve_operating_mode(True, True) == MODE_EXPORT_AND_PERCENTAGE
    assert resolve_operating_mode(True, False) == MODE_EXPORT_ONLY
    assert resolve_operating_mode(False, True) == MODE_PERCENTAGE_ONLY


def test_calculate_interval_delta_normal() -> None:
    delta, reset = calculate_interval_delta(110.0, 100.0)
    assert delta == pytest.approx(10.0)
    assert reset is False


def test_calculate_interval_delta_reset() -> None:
    delta, reset = calculate_interval_delta(5.0, 100.0)
    assert delta is None
    assert reset is True


def test_percentage_only_mode_seven_percent() -> None:
    result = calculate_settlement(
        operating_mode=MODE_PERCENTAGE_ONLY,
        imported=1.0,
        shared=0.7,
        provider_export=None,
        fixed_percentage=7.0,
    )
    assert result["provider_export_interval_kwh"] == pytest.approx(10.0)
    assert result["provider_export_source_type"] == EXPORT_TYPE_INFERRED
    assert result["used_shared_kwh"] == pytest.approx(0.7)
    assert result["billable_energy_kwh"] == pytest.approx(0.3)


def test_export_only_mode() -> None:
    result = calculate_settlement(
        operating_mode=MODE_EXPORT_ONLY,
        imported=1.0,
        shared=0.7,
        provider_export=10.0,
        fixed_percentage=None,
    )
    assert result["provider_export_source_type"] == EXPORT_TYPE_MEASURED
    assert result["effective_allocation_pct"] == pytest.approx(7.0)
    assert result["required_share_pct"] == pytest.approx(10.0)


def test_export_and_percentage_mode() -> None:
    result = calculate_settlement(
        operating_mode=MODE_EXPORT_AND_PERCENTAGE,
        imported=1.0,
        shared=0.7,
        provider_export=10.0,
        fixed_percentage=7.0,
    )
    assert result["expected_shared_kwh"] == pytest.approx(0.7)
    assert result["allocation_difference_kwh"] == pytest.approx(0.0)


def test_shared_greater_than_imported() -> None:
    result = calculate_settlement(
        operating_mode=MODE_PERCENTAGE_ONLY,
        imported=0.5,
        shared=0.7,
        provider_export=None,
        fixed_percentage=7.0,
    )
    assert result["used_shared_kwh"] == pytest.approx(0.5)
    assert result["unused_shared_kwh"] == pytest.approx(0.2)
    assert result["billable_energy_kwh"] == 0.0


def test_required_above_100_ideal_capped() -> None:
    result = calculate_settlement(
        operating_mode=MODE_EXPORT_ONLY,
        imported=20.0,
        shared=1.0,
        provider_export=1.0,
        fixed_percentage=None,
    )
    assert result["required_share_pct"] == pytest.approx(2000.0)
    assert result["ideal_share_pct"] == pytest.approx(100.0)


def test_zero_imported() -> None:
    result = calculate_settlement(
        operating_mode=MODE_EXPORT_ONLY,
        imported=0.0,
        shared=0.7,
        provider_export=10.0,
        fixed_percentage=None,
    )
    assert result["consumption_coverage_pct"] is None


def test_zero_shared() -> None:
    result = calculate_settlement(
        operating_mode=MODE_EXPORT_ONLY,
        imported=1.0,
        shared=0.0,
        provider_export=10.0,
        fixed_percentage=None,
    )
    assert result["allocation_utilization_pct"] is None


def test_clamp() -> None:
    assert clamp(140.0, 0.0, 100.0) == 100.0


def test_reconciliation_tolerances() -> None:
    assert evaluate_reconciliation(0.7, 0.705, 0.01, 0.0)["reconciled"] is True
    assert evaluate_reconciliation(0.7, 0.734, 0.0, 5.0)["reconciled"] is True
    assert evaluate_reconciliation(0.7, 0.8, 0.001, 1.0)["reconciled"] is False


def test_migrate_storage_v3_billable_keys() -> None:
    payload = {
        "version": 3,
        "cumulative_billable": 1.23,
        "last_interval": {"billable_grid_kwh": 0.45},
    }
    migrated = migrate_storage(payload, 3)
    assert migrated["version"] == 5
    assert migrated["cumulative_billable_energy"] == pytest.approx(1.23)
    assert "cumulative_billable" not in migrated
    assert migrated["last_interval"]["billable_energy_kwh"] == pytest.approx(0.45)


def test_storage_from_dict_tolerates_malformed_nested_data() -> None:
    payload = {
        "version": 4,
        "baseline_initialized": True,
        "previous_snapshot": 123,
        "last_interval": "invalid",
        "last_failure": [],
        "last_source_reset": None,
        "cumulative_receiver_import": "10.5",
        "cumulative_billable_energy": "not-a-number",
        "processed_intervals": "7",
    }
    storage = StorageData.from_dict(payload)
    assert storage.baseline_initialized is True
    assert storage.previous_snapshot is None
    assert storage.last_interval is None
    assert storage.last_failure is None
    assert storage.cumulative_receiver_import == pytest.approx(10.5)
    assert storage.cumulative_billable_energy == pytest.approx(0.0)
    assert storage.processed_intervals == 7


def test_migrate_storage_v4_adds_active_load_estimates() -> None:
    payload = {
        "version": 4,
        "cumulative_receiver_import": 1.0,
    }
    migrated = migrate_storage(payload, 4)
    assert migrated["version"] == 5
    assert migrated["active_load_estimated_power_w"] == {}
