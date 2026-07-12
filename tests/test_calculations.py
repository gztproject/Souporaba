"""Tests for settlement calculations."""

from __future__ import annotations

import pytest

from custom_components.energy_sharing.models import (
    calculate_interval,
    clamp,
    evaluate_reconciliation,
)


@pytest.mark.parametrize(
    ("provider_export", "receiver_import", "percentage", "expected"),
    [
        (
            10.0,
            1.0,
            7.0,
            {
                "calculated_allocated_kwh": pytest.approx(0.7, rel=1e-4),
                "used_shared_kwh": pytest.approx(0.7, rel=1e-4),
                "unused_shared_kwh": 0.0,
                "billable_grid_kwh": pytest.approx(0.3, rel=1e-4),
                "required_share_pct": 10.0,
                "ideal_share_pct": 10.0,
                "allocation_utilization_pct": 100.0,
                "consumption_coverage_pct": 70.0,
            },
        ),
        (
            10.0,
            2.0,
            7.0,
            {
                "calculated_allocated_kwh": pytest.approx(0.7, rel=1e-4),
                "used_shared_kwh": pytest.approx(0.7, rel=1e-4),
                "unused_shared_kwh": 0.0,
                "billable_grid_kwh": pytest.approx(1.3, rel=1e-4),
                "required_share_pct": 20.0,
                "ideal_share_pct": 20.0,
                "allocation_utilization_pct": 100.0,
                "consumption_coverage_pct": 35.0,
            },
        ),
        (
            10.0,
            0.5,
            7.0,
            {
                "calculated_allocated_kwh": pytest.approx(0.7, rel=1e-4),
                "used_shared_kwh": 0.5,
                "unused_shared_kwh": pytest.approx(0.2, rel=1e-4),
                "billable_grid_kwh": 0.0,
                "required_share_pct": 5.0,
                "ideal_share_pct": 5.0,
                "allocation_utilization_pct": pytest.approx(71.4285, rel=1e-3),
                "consumption_coverage_pct": 100.0,
            },
        ),
        (
            0.0,
            1.0,
            7.0,
            {
                "calculated_allocated_kwh": 0.0,
                "used_shared_kwh": 0.0,
                "unused_shared_kwh": 0.0,
                "billable_grid_kwh": 1.0,
                "required_share_pct": None,
                "ideal_share_pct": None,
                "allocation_utilization_pct": None,
                "consumption_coverage_pct": 0.0,
            },
        ),
        (
            10.0,
            0.0,
            7.0,
            {
                "calculated_allocated_kwh": pytest.approx(0.7, rel=1e-4),
                "used_shared_kwh": 0.0,
                "unused_shared_kwh": pytest.approx(0.7, rel=1e-4),
                "billable_grid_kwh": 0.0,
                "required_share_pct": 0.0,
                "ideal_share_pct": 0.0,
                "allocation_utilization_pct": 0.0,
                "consumption_coverage_pct": None,
            },
        ),
        (
            5.0,
            1.0,
            10.0,
            {
                "calculated_allocated_kwh": 0.5,
                "used_shared_kwh": 0.5,
                "unused_shared_kwh": 0.0,
                "billable_grid_kwh": 0.5,
                "required_share_pct": 20.0,
                "ideal_share_pct": 20.0,
                "allocation_utilization_pct": 100.0,
                "consumption_coverage_pct": 50.0,
            },
        ),
        (
            1.0,
            20.0,
            7.0,
            {
                "calculated_allocated_kwh": pytest.approx(0.07, rel=1e-4),
                "used_shared_kwh": pytest.approx(0.07, rel=1e-4),
                "unused_shared_kwh": 0.0,
                "billable_grid_kwh": pytest.approx(19.93, rel=1e-4),
                "required_share_pct": 2000.0,
                "ideal_share_pct": 100.0,
                "allocation_utilization_pct": 100.0,
                "consumption_coverage_pct": pytest.approx(0.35, rel=1e-3),
            },
        ),
    ],
)
def test_calculate_interval(
    provider_export: float,
    receiver_import: float,
    percentage: float,
    expected: dict[str, float | None],
) -> None:
    """Test interval calculations for common scenarios."""
    result = calculate_interval(provider_export, receiver_import, percentage)
    for key, value in expected.items():
        assert result[key] == value


def test_clamp() -> None:
    """Test clamp helper."""
    assert clamp(140.0, 0.0, 100.0) == 100.0
    assert clamp(-5.0, 0.0, 100.0) == 0.0


def test_reconciliation_within_absolute_tolerance() -> None:
    """Test reconciliation passes on absolute kWh tolerance."""
    result = evaluate_reconciliation(0.7, 0.705, tolerance_kwh=0.01, tolerance_pct=0.0)
    assert result["reconciled"] is True


def test_reconciliation_within_percentage_tolerance() -> None:
    """Test reconciliation passes on percentage tolerance."""
    result = evaluate_reconciliation(0.7, 0.734, tolerance_kwh=0.0, tolerance_pct=5.0)
    assert result["reconciled"] is True


def test_reconciliation_fails_outside_tolerance() -> None:
    """Test reconciliation fails when outside both tolerances."""
    result = evaluate_reconciliation(0.7, 0.8, tolerance_kwh=0.01, tolerance_pct=1.0)
    assert result["reconciled"] is False
    assert result["allocation_difference_kwh"] == pytest.approx(0.1)
