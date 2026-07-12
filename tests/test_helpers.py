"""Tests for helper utilities."""

from __future__ import annotations

from datetime import datetime

import pytest
from homeassistant.util import dt as dt_util

from custom_components.energy_sharing.helpers import (
    convert_energy_to_kwh,
    count_missed_intervals,
    interval_id_from_end,
    parse_non_negative_number,
    resets_match,
)


def test_convert_wh_to_kwh() -> None:
    """Test Wh conversion."""
    assert convert_energy_to_kwh(1500.0, "Wh") == pytest.approx(1.5)


def test_convert_unsupported_unit() -> None:
    """Test unsupported unit rejection."""
    with pytest.raises(ValueError, match="unsupported_unit"):
        convert_energy_to_kwh(1.0, "bananas")


def test_parse_non_negative_number() -> None:
    """Test numeric parsing."""
    assert parse_non_negative_number("1.5") == 1.5
    assert parse_non_negative_number(-1.0) is None
    assert parse_non_negative_number("invalid") is None


def test_resets_match_within_tolerance() -> None:
    """Test reset timestamp tolerance."""
    first = datetime(2026, 7, 12, 15, 0, 0, tzinfo=dt_util.UTC)
    second = datetime(2026, 7, 12, 15, 0, 3, tzinfo=dt_util.UTC)
    assert resets_match(first, second, 5)
    assert not resets_match(first, second, 2)


def test_count_missed_intervals() -> None:
    """Test missed interval counting."""
    end_1 = datetime(2026, 7, 12, 15, 0, 0, tzinfo=dt_util.UTC)
    end_2 = datetime(2026, 7, 12, 15, 45, 0, tzinfo=dt_util.UTC)
    missed = count_missed_intervals(
        interval_id_from_end(end_1),
        interval_id_from_end(end_2),
        15,
    )
    assert missed == 2
