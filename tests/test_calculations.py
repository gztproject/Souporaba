"""Tests for settlement calculations."""

from __future__ import annotations

import pytest

from custom_components.energy_sharing.models import calculate_interval, clamp


@pytest.mark.parametrize(
    ("imported", "shared", "percentage", "expected"),
    [
        (
            2.0,
            1.0,
            7.0,
            {
                "exported_kwh": pytest.approx(14.285714, rel=1e-4),
                "used_kwh": 1.0,
                "unused_kwh": 0.0,
                "billable_kwh": 1.0,
                "required_share_pct": pytest.approx(14.0, rel=1e-4),
                "ideal_share_pct": 14.0,
                "allocation_utilization_pct": 100.0,
                "consumption_coverage_pct": 50.0,
            },
        ),
        (
            1.0,
            2.0,
            7.0,
            {
                "exported_kwh": pytest.approx(28.571428, rel=1e-4),
                "used_kwh": 1.0,
                "unused_kwh": 1.0,
                "billable_kwh": 0.0,
                "required_share_pct": pytest.approx(3.5, rel=1e-4),
                "ideal_share_pct": 3.5,
                "allocation_utilization_pct": 50.0,
                "consumption_coverage_pct": 100.0,
            },
        ),
        (
            0.0,
            1.0,
            7.0,
            {
                "exported_kwh": pytest.approx(14.285714, rel=1e-4),
                "used_kwh": 0.0,
                "unused_kwh": 1.0,
                "billable_kwh": 0.0,
                "required_share_pct": 0.0,
                "ideal_share_pct": 0.0,
                "allocation_utilization_pct": 0.0,
                "consumption_coverage_pct": None,
            },
        ),
        (
            1.0,
            0.0,
            7.0,
            {
                "exported_kwh": 0.0,
                "used_kwh": 0.0,
                "unused_kwh": 0.0,
                "billable_kwh": 1.0,
                "required_share_pct": None,
                "ideal_share_pct": None,
                "allocation_utilization_pct": None,
                "consumption_coverage_pct": 0.0,
            },
        ),
        (
            5.0,
            1.0,
            0.0,
            {
                "exported_kwh": None,
                "used_kwh": 1.0,
                "unused_kwh": 0.0,
                "billable_kwh": 4.0,
                "required_share_pct": None,
                "ideal_share_pct": None,
                "allocation_utilization_pct": 100.0,
                "consumption_coverage_pct": 20.0,
            },
        ),
        (
            2.0,
            0.5,
            10.0,
            {
                "exported_kwh": 5.0,
                "used_kwh": 0.5,
                "unused_kwh": 0.0,
                "billable_kwh": 1.5,
                "required_share_pct": 40.0,
                "ideal_share_pct": 40.0,
                "allocation_utilization_pct": 100.0,
                "consumption_coverage_pct": 25.0,
            },
        ),
        (
            20.0,
            1.0,
            7.0,
            {
                "exported_kwh": pytest.approx(14.285714, rel=1e-4),
                "used_kwh": 1.0,
                "unused_kwh": 0.0,
                "billable_kwh": 19.0,
                "required_share_pct": pytest.approx(140.0, rel=1e-4),
                "ideal_share_pct": 100.0,
                "allocation_utilization_pct": 100.0,
                "consumption_coverage_pct": 5.0,
            },
        ),
    ],
)
def test_calculate_interval(
    imported: float,
    shared: float,
    percentage: float,
    expected: dict[str, float | None],
) -> None:
    """Test interval calculations for common scenarios."""
    result = calculate_interval(imported, shared, percentage)
    for key, value in expected.items():
        assert result[key] == value


def test_clamp() -> None:
    """Test clamp helper."""
    assert clamp(140.0, 0.0, 100.0) == 100.0
    assert clamp(-5.0, 0.0, 100.0) == 0.0
