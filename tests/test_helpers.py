"""Tests for helper utilities."""

from __future__ import annotations

from datetime import datetime

import pytest
from homeassistant.util import dt as dt_util

from custom_components.energy_sharing.helpers import (
    IntervalSourceReading,
    IntervalSourceValidationError,
    convert_energy_to_kwh,
    count_missed_intervals,
    interval_id_from_reset,
    normalize_reset_to_utc,
    parse_non_negative_number,
    resets_match_utc,
    validate_sources_synchronized,
)


def test_convert_wh_to_kwh() -> None:
    """Test Wh conversion."""
    assert convert_energy_to_kwh(1500.0, "Wh") == pytest.approx(1.5)


def test_convert_unsupported_unit() -> None:
    """Test unsupported unit rejection."""
    with pytest.raises(IntervalSourceValidationError, match="unsupported_energy_unit"):
        convert_energy_to_kwh(1.0, "bananas")


def test_parse_non_negative_number() -> None:
    """Test numeric parsing."""
    assert parse_non_negative_number("1.5") == 1.5
    assert parse_non_negative_number(-1.0) is None
    assert parse_non_negative_number("invalid") is None


def test_resets_match_within_tolerance() -> None:
    """Test reset timestamp tolerance in UTC."""
    first = datetime(2026, 7, 12, 13, 0, 0, tzinfo=dt_util.UTC)
    second = datetime(2026, 7, 12, 13, 0, 3, tzinfo=dt_util.UTC)
    assert resets_match_utc(first, second, 5)
    assert not resets_match_utc(first, second, 2)


def test_equivalent_utc_and_local_reset_timestamps_match() -> None:
    """Test equivalent UTC and local reset timestamps synchronize."""
    local = datetime(
        2026, 7, 12, 15, 0, 0, tzinfo=dt_util.get_time_zone("Europe/Ljubljana")
    )
    utc = normalize_reset_to_utc(local)
    assert resets_match_utc(utc, local, 0)


def test_count_missed_intervals() -> None:
    """Test missed interval counting."""
    end_1 = datetime(2026, 7, 12, 13, 0, 0, tzinfo=dt_util.UTC)
    end_2 = datetime(2026, 7, 12, 13, 45, 0, tzinfo=dt_util.UTC)
    missed = count_missed_intervals(
        interval_id_from_reset(end_1),
        interval_id_from_reset(end_2),
        15,
    )
    assert missed == 2


def test_validate_sources_synchronized_rejects_different_intervals() -> None:
    """Test required sources with different resets are rejected."""
    first = IntervalSourceReading(
        entity_id="sensor.a",
        last_period_kwh=1.0,
        reset_utc=datetime(2026, 7, 12, 13, 0, 0, tzinfo=dt_util.UTC),
        unit="kWh",
    )
    second = IntervalSourceReading(
        entity_id="sensor.b",
        last_period_kwh=1.0,
        reset_utc=datetime(2026, 7, 12, 13, 15, 0, tzinfo=dt_util.UTC),
        unit="kWh",
    )
    with pytest.raises(
        IntervalSourceValidationError, match="source_intervals_unsynchronized"
    ):
        validate_sources_synchronized([first, second], tolerance_seconds=5)
